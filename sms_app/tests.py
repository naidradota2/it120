"""Automated tests for the SMS app.

They cover every test case listed in the assignment (Step 6). The real SMS
provider is never called - HTTP requests are replaced with mocks, so the
tests are free and work offline.

Run with:  python manage.py test
"""
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import SMSForm
from .models import Contact, Message
from .providers import (
    SMSAuthenticationError,
    SMSConfigurationError,
    SMSNetworkError,
    SMSProviderError,
    TextBeeProvider,
    get_provider,
)
from .validators import normalize_phone_number

VALID_NUMBER = '+639171234567'


def fake_response(status_code=200, json_data=None):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = json_data if json_data is not None else {}
    return response


# --- Phone number validation -------------------------------------------------------

class PhoneValidationTests(TestCase):
    def test_accepts_international_format(self):
        self.assertEqual(normalize_phone_number('+639171234567'), VALID_NUMBER)

    def test_accepts_spaces_and_dashes(self):
        self.assertEqual(normalize_phone_number('+63 917-123-4567'), VALID_NUMBER)

    def test_converts_philippine_local_format(self):
        self.assertEqual(normalize_phone_number('09171234567'), VALID_NUMBER)

    def test_adds_missing_plus(self):
        self.assertEqual(normalize_phone_number('639171234567'), VALID_NUMBER)

    def test_accepts_other_countries(self):
        self.assertEqual(normalize_phone_number('+14155550101'), '+14155550101')

    def test_rejects_empty(self):
        with self.assertRaisesMessage(ValidationError, 'Please enter the recipient phone number.'):
            normalize_phone_number('   ')

    def test_rejects_letters(self):
        with self.assertRaises(ValidationError):
            normalize_phone_number('0917ABC4567')

    def test_rejects_too_short(self):
        with self.assertRaises(ValidationError):
            normalize_phone_number('+12345')

    def test_rejects_wrong_length_philippine_number(self):
        with self.assertRaises(ValidationError):
            normalize_phone_number('0917123456')  # 10 digits instead of 11

    def test_rejects_number_without_country_code(self):
        with self.assertRaises(ValidationError):
            normalize_phone_number('9171234567')


# --- Form validation ----------------------------------------------------------------

class SMSFormTests(TestCase):
    def test_valid_form(self):
        form = SMSForm(data={'recipient': '09171234567', 'body': 'Hello'})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['recipient'], VALID_NUMBER)

    def test_empty_phone_number(self):
        form = SMSForm(data={'recipient': '', 'body': 'Hello'})
        self.assertFalse(form.is_valid())
        self.assertIn('recipient', form.errors)

    def test_empty_message(self):
        form = SMSForm(data={'recipient': VALID_NUMBER, 'body': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('Please enter a message.', form.errors['body'])

    def test_whitespace_only_message(self):
        form = SMSForm(data={'recipient': VALID_NUMBER, 'body': '    '})
        self.assertFalse(form.is_valid())
        self.assertIn('body', form.errors)

    def test_message_too_long(self):
        form = SMSForm(data={'recipient': VALID_NUMBER, 'body': 'x' * 481})
        self.assertFalse(form.is_valid())
        self.assertIn('body', form.errors)

    def test_contact_fills_recipient(self):
        contact = Contact.objects.create(name='Ana', phone_number=VALID_NUMBER)
        form = SMSForm(data={'contact': contact.pk, 'recipient': '', 'body': 'Hi'})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['recipient'], VALID_NUMBER)


# --- textbee provider (HTTP mocked) ----------------------------------------------------

class TextBeeProviderTests(TestCase):
    def setUp(self):
        self.provider = TextBeeProvider(api_key='test-key', device_id='device123',
                                        base_url='https://api.example.test/api/v1', timeout=5)

    @mock.patch('sms_app.providers.requests.request')
    def test_successful_send_returns_batch_id(self, mock_request):
        mock_request.return_value = fake_response(200, {
            'data': {'success': True, 'message': 'SMS added to queue', 'smsBatchId': 'batch1', 'recipientCount': 1}
        })
        result = self.provider.send(VALID_NUMBER, 'Hello')

        self.assertEqual(result.reference, 'batch1')
        method, url = mock_request.call_args.args
        kwargs = mock_request.call_args.kwargs
        self.assertEqual(method, 'POST')
        self.assertEqual(url, 'https://api.example.test/api/v1/gateway/send-sms')
        self.assertEqual(kwargs['headers']['x-api-key'], 'test-key')
        self.assertEqual(kwargs['json'], {'recipients': [VALID_NUMBER], 'message': 'Hello', 'deviceId': 'device123'})
        self.assertEqual(kwargs['timeout'], 5)

    def test_missing_credentials(self):
        provider = TextBeeProvider(api_key='', device_id='', base_url='https://x.test')
        with self.assertRaises(SMSConfigurationError) as ctx:
            provider.send(VALID_NUMBER, 'Hello')
        self.assertIn('TEXTBEE_API_KEY', ctx.exception.user_message)

    @mock.patch('sms_app.providers.requests.request')
    def test_incorrect_credentials(self, mock_request):
        mock_request.return_value = fake_response(401, {'message': 'Unauthorized'})
        with self.assertRaises(SMSAuthenticationError) as ctx:
            self.provider.send(VALID_NUMBER, 'Hello')
        self.assertNotIn('test-key', ctx.exception.user_message)  # never leak the key

    @mock.patch('sms_app.providers.requests.request', side_effect=requests.ConnectionError('boom'))
    def test_network_error(self, _):
        with self.assertRaises(SMSNetworkError):
            self.provider.send(VALID_NUMBER, 'Hello')

    @mock.patch('sms_app.providers.requests.request', side_effect=requests.Timeout())
    def test_timeout(self, _):
        with self.assertRaisesMessage(SMSNetworkError, 'took too long'):
            self.provider.send(VALID_NUMBER, 'Hello')

    @mock.patch('sms_app.providers.requests.request')
    def test_provider_rejects_message(self, mock_request):
        mock_request.return_value = fake_response(400, {'message': 'No enabled device to send from'})
        with self.assertRaisesMessage(SMSProviderError, 'No enabled device'):
            self.provider.send(VALID_NUMBER, 'Hello')

    @mock.patch('sms_app.providers.requests.request')
    def test_rate_limited(self, mock_request):
        mock_request.return_value = fake_response(429, {})
        with self.assertRaisesMessage(SMSProviderError, 'limit'):
            self.provider.send(VALID_NUMBER, 'Hello')

    @mock.patch('sms_app.providers.requests.request')
    def test_success_false_is_rejection(self, mock_request):
        mock_request.return_value = fake_response(200, {'data': {'success': False, 'message': 'Device offline'}})
        with self.assertRaisesMessage(SMSProviderError, 'Device offline'):
            self.provider.send(VALID_NUMBER, 'Hello')

    @mock.patch('sms_app.providers.requests.request')
    def test_status_delivered(self, mock_request):
        mock_request.return_value = fake_response(200, {
            'data': {'batch': {'status': 'completed'}, 'messages': [{'status': 'delivered'}]}
        })
        result = self.provider.get_status('batch1')
        self.assertEqual(result.status, Message.Status.DELIVERED)
        self.assertTrue(mock_request.call_args.args[1].endswith('/gateway/devices/device123/sms-batch/batch1'))

    @mock.patch('sms_app.providers.requests.request')
    def test_status_failed_with_error(self, mock_request):
        mock_request.return_value = fake_response(200, {
            'data': {'messages': [{'status': 'failed', 'errorMessage': 'No load'}]}
        })
        result = self.provider.get_status('batch1')
        self.assertEqual(result.status, Message.Status.FAILED)
        self.assertEqual(result.error, 'No load')

    @mock.patch('sms_app.providers.requests.request')
    def test_status_falls_back_to_batch(self, mock_request):
        mock_request.return_value = fake_response(200, {'data': {'batch': {'status': 'processing'}}})
        self.assertEqual(self.provider.get_status('b').status, Message.Status.SUBMITTED)

    def test_unknown_provider_name(self):
        with self.assertRaises(SMSConfigurationError):
            get_provider('carrier-pigeon')


# --- Views (end-to-end through the web form) ---------------------------------------------

@override_settings(SMS_PROVIDER='console')
class ViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('tester', password='a-strong-pass-123')
        self.client.force_login(self.user)
        self.url = reverse('sms_app:compose')

    def test_login_required(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])

    def test_form_page_has_fields_and_csrf(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'name="recipient"')
        self.assertContains(response, 'name="body"')
        self.assertContains(response, 'Send SMS')
        self.assertContains(response, 'csrfmiddlewaretoken')

    def test_valid_send_shows_submitted_not_delivered(self):
        response = self.client.post(self.url, {'recipient': '09171234567', 'body': 'Hello'}, follow=True)
        message = Message.objects.get()
        self.assertEqual(message.status, Message.Status.SUBMITTED)
        self.assertEqual(message.recipient, VALID_NUMBER)
        self.assertContains(response, 'Message submitted')
        self.assertContains(response, 'Delivery is not confirmed yet')

    def test_empty_phone_rejected(self):
        response = self.client.post(self.url, {'recipient': '', 'body': 'Hello'})
        self.assertContains(response, 'Please enter the recipient phone number.')
        self.assertEqual(Message.objects.count(), 0)

    def test_empty_message_rejected(self):
        response = self.client.post(self.url, {'recipient': VALID_NUMBER, 'body': ''})
        self.assertContains(response, 'Please enter a message.')
        self.assertEqual(Message.objects.count(), 0)

    def test_invalid_phone_rejected(self):
        response = self.client.post(self.url, {'recipient': '12345', 'body': 'Hello'})
        self.assertContains(response, 'Please fix the errors below')
        self.assertEqual(Message.objects.count(), 0)

    @override_settings(SMS_PROVIDER='textbee', TEXTBEE_API_KEY='', TEXTBEE_DEVICE_ID='')
    def test_missing_credentials_shows_safe_error(self):
        response = self.client.post(self.url, {'recipient': VALID_NUMBER, 'body': 'Hello'})
        self.assertContains(response, 'Message not sent.')
        self.assertContains(response, 'missing its credentials')
        self.assertEqual(Message.objects.get().status, Message.Status.FAILED_TO_SUBMIT)

    @override_settings(SMS_PROVIDER='textbee', TEXTBEE_API_KEY='super-secret-key', TEXTBEE_DEVICE_ID='dev1')
    @mock.patch('sms_app.providers.requests.request')
    def test_wrong_credentials_do_not_leak_key(self, mock_request):
        mock_request.return_value = fake_response(401, {'message': 'Unauthorized'})
        response = self.client.post(self.url, {'recipient': VALID_NUMBER, 'body': 'Hello'})
        self.assertContains(response, 'rejected the API credentials')
        self.assertNotContains(response, 'super-secret-key')

    @override_settings(SMS_PROVIDER='textbee', TEXTBEE_API_KEY='k', TEXTBEE_DEVICE_ID='dev1')
    @mock.patch('sms_app.providers.requests.request', side_effect=requests.ConnectionError())
    def test_network_error_message(self, _):
        response = self.client.post(self.url, {'recipient': VALID_NUMBER, 'body': 'Hello'})
        self.assertContains(response, 'Could not reach the SMS provider')

    def test_failed_input_is_kept(self):
        response = self.client.post(self.url, {'recipient': 'abc', 'body': 'Keep me'})
        self.assertContains(response, 'Keep me')

    def test_refresh_status(self):
        self.client.post(self.url, {'recipient': VALID_NUMBER, 'body': 'Hello'})
        message = Message.objects.get()
        self.client.post(reverse('sms_app:message_refresh', args=[message.pk]))
        message.refresh_from_db()
        self.assertEqual(message.status, Message.Status.DELIVERED)  # simulated in test mode
        self.assertIsNotNone(message.status_checked_at)

    def test_refresh_ignores_external_next_url(self):
        self.client.post(self.url, {'recipient': VALID_NUMBER, 'body': 'Hello'})
        message = Message.objects.get()
        response = self.client.post(reverse('sms_app:message_refresh', args=[message.pk]),
                                    {'next': 'https://evil.example.com/'})
        self.assertEqual(response['Location'], message.get_absolute_url())

    def test_history_dashboard_pages(self):
        self.client.post(self.url, {'recipient': VALID_NUMBER, 'body': 'Hello history'})
        self.assertContains(self.client.get(reverse('sms_app:history')), 'Hello history')
        self.assertContains(self.client.get(reverse('sms_app:history') + '?status=submitted'), 'Hello history')
        self.assertContains(self.client.get(reverse('sms_app:dashboard')), 'Total attempts')

    def test_contact_crud(self):
        self.client.post(reverse('sms_app:contact_create'), {'name': 'Ben', 'phone_number': '0917 123 4567'})
        contact = Contact.objects.get()
        self.assertEqual(contact.phone_number, VALID_NUMBER)

        # Duplicate number is rejected
        response = self.client.post(reverse('sms_app:contact_create'), {'name': 'Dup', 'phone_number': VALID_NUMBER})
        self.assertContains(response, 'already exists')

        self.client.post(reverse('sms_app:contact_edit', args=[contact.pk]), {'name': 'Benjie', 'phone_number': VALID_NUMBER})
        contact.refresh_from_db()
        self.assertEqual(contact.name, 'Benjie')

        self.client.post(reverse('sms_app:contact_delete', args=[contact.pk]))
        self.assertFalse(Contact.objects.exists())

    def test_message_links_to_contact(self):
        contact = Contact.objects.create(name='Cara', phone_number=VALID_NUMBER)
        self.client.post(self.url, {'recipient': '09171234567', 'body': 'Hi Cara'})
        self.assertEqual(Message.objects.get().contact, contact)
