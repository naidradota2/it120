from django.conf import settings


def sms_settings(request):
    """Expose the current SMS mode to every template (never the credentials)."""
    provider = settings.SMS_PROVIDER
    return {
        'sms_provider': provider,
        'sms_test_mode': provider == 'console',
    }
