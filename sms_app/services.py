"""Application logic for sending SMS and tracking status.

Views call these functions; they talk to the provider and record every
attempt (successful or not) in the Message table for the history page.
"""
import logging

from django.utils import timezone

from .models import Message
from .providers import SMSError, get_provider

logger = logging.getLogger(__name__)


def send_sms(recipient, body, contact=None):
    """Submit an SMS through the configured provider and save the attempt.

    Returns (message, error_text). error_text is None when the provider
    accepted the message. Acceptance is NOT delivery - the saved status is
    SUBMITTED until a status check confirms more.
    """
    provider_name = 'unknown'
    try:
        provider = get_provider()
        provider_name = provider.name
        result = provider.send(recipient, body)
    except SMSError as exc:
        message = Message.objects.create(
            recipient=recipient,
            contact=contact,
            body=body,
            provider=provider_name,
            status=Message.Status.FAILED_TO_SUBMIT,
            error_message=exc.user_message[:255],
        )
        return message, exc.user_message
    except Exception:  # Unexpected bug: log details, show a generic message.
        logger.exception('Unexpected error while sending SMS')
        error = 'An unexpected error occurred while sending the SMS.'
        message = Message.objects.create(
            recipient=recipient,
            contact=contact,
            body=body,
            provider=provider_name,
            status=Message.Status.FAILED_TO_SUBMIT,
            error_message=error,
        )
        return message, error

    message = Message.objects.create(
        recipient=recipient,
        contact=contact,
        body=body,
        provider=provider_name,
        status=Message.Status.SUBMITTED,
        provider_reference=result.reference,
        provider_status=result.provider_status,
        error_message=result.note[:255],
    )
    return message, None


def refresh_status(message):
    """Ask the provider for the latest status of a message.

    Returns an error string, or None on success.
    """
    if not message.can_refresh_status:
        return None
    try:
        provider = get_provider(message.provider)
        result = provider.get_status(message.provider_reference)
    except SMSError as exc:
        return exc.user_message
    except Exception:
        logger.exception('Unexpected error while checking SMS status')
        return 'An unexpected error occurred while checking the status.'

    message.status = result.status
    message.provider_status = result.provider_status
    if result.error:
        message.error_message = result.error[:255]
    message.status_checked_at = timezone.now()
    message.save(update_fields=['status', 'provider_status', 'error_message', 'status_checked_at'])
    return None
