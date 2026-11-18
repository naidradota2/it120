"""SMS provider integrations.

Each provider exposes the same two methods:

    send(to, body)         -> SendResult      (submit a message)
    get_status(reference)  -> StatusResult    (check what happened to it)

and raises an SMSError subclass with a *safe, user-friendly* message when
something goes wrong. Secrets (API keys) are never included in error messages.

Choose the provider with the SMS_PROVIDER setting:
    textbee  - real SMS through the textbee.dev Android SMS gateway
    console  - test mode, nothing is sent (logs the message instead)
"""
import logging
import uuid
from dataclasses import dataclass

import requests
from django.conf import settings

from .models import Message

logger = logging.getLogger(__name__)


# --- Errors ------------------------------------------------------------------

class SMSError(Exception):
    """Base error. `user_message` is safe to show in the web page."""

    default_message = 'The SMS could not be sent.'

    def __init__(self, user_message=None):
        self.user_message = user_message or self.default_message
        super().__init__(self.user_message)


class SMSConfigurationError(SMSError):
    default_message = (
        'The SMS service is not configured correctly. '
        'Check the SMS settings in the .env file.'
    )


class SMSAuthenticationError(SMSError):
    default_message = (
        'The SMS provider rejected the API credentials. '
        'Check that the API key in the .env file is correct.'
    )


class SMSNetworkError(SMSError):
    default_message = (
        'Could not reach the SMS provider. Check your internet connection and try again.'
    )


class SMSProviderError(SMSError):
    default_message = 'The SMS provider rejected the message.'


# --- Results -----------------------------------------------------------------

@dataclass
class SendResult:
    reference: str          # provider id used later to check the status
    provider_status: str    # raw status text from the provider
    note: str = ''          # optional extra information (e.g. a provider warning)


@dataclass
class StatusResult:
    status: str             # one of Message.Status values
    provider_status: str    # raw status text from the provider
    error: str = ''


# --- Providers ---------------------------------------------------------------

class BaseProvider:
    name = 'base'

    def send(self, to, body):
        raise NotImplementedError

    def get_status(self, reference):
        raise NotImplementedError


class ConsoleProvider(BaseProvider):
    """Test mode: pretends to send so the app can be developed without credits."""

    name = 'console'

    def send(self, to, body):
        reference = f'console-{uuid.uuid4().hex[:12]}'
        logger.info('[TEST MODE] SMS to %s (%d chars): %s', to, len(body), body)
        return SendResult(reference=reference, provider_status='test_mode_queued')

    def get_status(self, reference):
        # Simulate the carrier confirming delivery.
        return StatusResult(status=Message.Status.DELIVERED, provider_status='test_mode_delivered')


class TextBeeProvider(BaseProvider):
    """textbee.dev: sends SMS through a registered Android phone.

    API docs: https://textbee.dev/docs/api-reference
      POST {base}/gateway/send-sms                         -> {"data": {"smsBatchId": ...}}
      GET  {base}/gateway/devices/{id}/sms-batch/{batchId} -> batch + per-recipient messages
    """

    name = 'textbee'

    # Per-message status values reported by textbee -> our status.
    MESSAGE_STATUS_MAP = {
        'pending': Message.Status.SUBMITTED,
        'dispatched': Message.Status.SUBMITTED,
        'sent': Message.Status.SENT,
        'delivered': Message.Status.DELIVERED,
        'failed': Message.Status.FAILED,
        'delivery_failed': Message.Status.FAILED,
        'unknown': Message.Status.UNKNOWN,
    }

    # Batch-level status values (used only if per-message details are missing).
    BATCH_STATUS_MAP = {
        'pending': Message.Status.SUBMITTED,
        'processing': Message.Status.SUBMITTED,
        'completed': Message.Status.SENT,
        'partial_success': Message.Status.SENT,
        'sent': Message.Status.SENT,
        'delivered': Message.Status.DELIVERED,
        'failed': Message.Status.FAILED,
        'unknown': Message.Status.UNKNOWN,
    }

    def __init__(self, api_key=None, device_id=None, base_url=None, timeout=None):
        self.api_key = (api_key if api_key is not None else settings.TEXTBEE_API_KEY).strip()
        self.device_id = (device_id if device_id is not None else settings.TEXTBEE_DEVICE_ID).strip()
        self.base_url = (base_url or settings.TEXTBEE_BASE_URL).rstrip('/')
        self.timeout = timeout or settings.SMS_REQUEST_TIMEOUT

    # -- public API --

    def send(self, to, body):
        self._check_configuration()
        payload = {'recipients': [to], 'message': body, 'deviceId': self.device_id}
        data = self._request('POST', '/gateway/send-sms', json=payload)

        result = data.get('data') if isinstance(data, dict) else None
        if not isinstance(result, dict):
            raise SMSProviderError('The SMS provider returned an unexpected response.')

        if result.get('success') is False or (
            result.get('failureCount') and not result.get('successCount')
        ):
            detail = result.get('message') or 'The message was not accepted.'
            raise SMSProviderError(f'The SMS provider rejected the message: {_safe_text(detail)}')

        reference = str(result.get('smsBatchId') or '')
        note = ''
        warning = result.get('warning')
        if isinstance(warning, dict) and warning.get('message'):
            note = _safe_text(warning['message'])

        return SendResult(reference=reference, provider_status='accepted', note=note)

    def get_status(self, reference):
        self._check_configuration()
        if not reference:
            raise SMSProviderError('This message has no provider reference to check.')

        data = self._request('GET', f'/gateway/devices/{self.device_id}/sms-batch/{reference}')
        body = data.get('data', data) if isinstance(data, dict) else {}

        # Prefer the per-recipient message status (we always send to one recipient).
        messages = body.get('messages') if isinstance(body, dict) else None
        if isinstance(messages, list) and messages:
            msg = messages[0]
            raw = str(msg.get('status', 'unknown')).lower()
            error = msg.get('errorMessage') or msg.get('errorName') or ''
            return StatusResult(
                status=self.MESSAGE_STATUS_MAP.get(raw, Message.Status.UNKNOWN),
                provider_status=raw,
                error=_safe_text(error),
            )

        batch = body.get('batch', body) if isinstance(body, dict) else {}
        raw = str(batch.get('status', 'unknown')).lower() if isinstance(batch, dict) else 'unknown'
        return StatusResult(
            status=self.BATCH_STATUS_MAP.get(raw, Message.Status.UNKNOWN),
            provider_status=raw,
        )

    # -- helpers --

    def _check_configuration(self):
        missing = []
        if not self.api_key:
            missing.append('TEXTBEE_API_KEY')
        if not self.device_id:
            missing.append('TEXTBEE_DEVICE_ID')
        if missing:
            raise SMSConfigurationError(
                'The SMS service is missing its credentials ('
                + ', '.join(missing)
                + '). Add them to the .env file and restart the server.'
            )

    def _request(self, method, path, **kwargs):
        url = f'{self.base_url}{path}'
        headers = {'x-api-key': self.api_key, 'Accept': 'application/json'}
        try:
            response = requests.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
        except requests.Timeout:
            logger.warning('textbee request timed out: %s %s', method, path)
            raise SMSNetworkError('The SMS provider took too long to respond. Please try again.')
        except requests.ConnectionError:
            logger.warning('Could not connect to textbee: %s %s', method, path)
            raise SMSNetworkError()
        except requests.RequestException:
            logger.exception('textbee request failed: %s %s', method, path)
            raise SMSNetworkError('Something went wrong while contacting the SMS provider.')

        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code >= 400:
            detail = _extract_error(data)
            logger.warning('textbee error %s on %s %s: %s', response.status_code, method, path, detail)
            raise _error_for_status(response.status_code, detail)

        return data


def _extract_error(data):
    """Pull a readable error from a JSON error body (shape is not documented)."""
    if not isinstance(data, dict):
        return ''
    for key in ('message', 'error', 'detail'):
        value = data.get(key)
        if isinstance(value, list):
            value = '; '.join(str(v) for v in value)
        if value:
            return _safe_text(value)
    return ''


def _error_for_status(status_code, detail):
    suffix = f' ({detail})' if detail else ''
    if status_code == 401:
        return SMSAuthenticationError()
    if status_code == 403:
        return SMSProviderError('The SMS provider account is not allowed to send messages.' + suffix)
    if status_code == 404:
        return SMSConfigurationError(
            'The SMS provider could not find the device or message. '
            'Check TEXTBEE_DEVICE_ID in the .env file.'
        )
    if status_code == 429:
        return SMSProviderError('The SMS sending limit has been reached. Try again later.' + suffix)
    if status_code == 400:
        return SMSProviderError('The SMS provider rejected the message' + suffix + '.')
    if status_code >= 500:
        return SMSProviderError('The SMS provider is having problems right now. Try again later.')
    return SMSProviderError(f'The SMS provider returned an error (HTTP {status_code}){suffix}.')


def _safe_text(value, limit=200):
    text = ' '.join(str(value).split())
    return text[:limit]


# --- Factory -----------------------------------------------------------------

PROVIDERS = {
    TextBeeProvider.name: TextBeeProvider,
    ConsoleProvider.name: ConsoleProvider,
}


def get_provider(name=None):
    name = (name or settings.SMS_PROVIDER).lower()
    try:
        return PROVIDERS[name]()
    except KeyError:
        raise SMSConfigurationError(
            f'Unknown SMS_PROVIDER "{_safe_text(name, 30)}". Use "textbee" or "console".'
        )
