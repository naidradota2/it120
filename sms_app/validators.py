"""Phone number and message validation helpers."""
import re

from django.conf import settings
from django.core.exceptions import ValidationError

# E.164: "+" then country code (1-9) then up to 14 more digits, 8-15 digits total.
E164_PATTERN = re.compile(r'^\+[1-9]\d{7,14}$')

# Characters that are allowed as formatting and stripped before validation.
FORMATTING_CHARS = re.compile(r'[\s\-().]')


def normalize_phone_number(raw):
    """Clean up a phone number and convert it to E.164 format.

    Accepts:
      +639171234567, +63 917 123 4567, +63-917-123-4567  (international)
      09171234567                                        (Philippine local)
      639171234567                                       (missing "+")

    Raises ValidationError with a user-friendly message if it is invalid.
    """
    if raw is None or not str(raw).strip():
        raise ValidationError('Please enter the recipient phone number.', code='required')

    number = FORMATTING_CHARS.sub('', str(raw).strip())
    country_code = settings.SMS_DEFAULT_COUNTRY_CODE

    if not re.fullmatch(r'\+?\d+', number):
        raise ValidationError(
            'Phone numbers can only contain digits, spaces, dashes and a leading "+".',
            code='invalid_characters',
        )

    if number.startswith('+'):
        pass
    elif number.startswith('0'):
        # Local format such as 09171234567 -> +639171234567
        number = f'+{country_code}{number[1:]}'
    elif number.startswith(country_code):
        number = f'+{number}'
    else:
        raise ValidationError(
            'Enter the number in international format (e.g. +639171234567) '
            'or Philippine local format (e.g. 09171234567).',
            code='invalid_format',
        )

    if not E164_PATTERN.match(number):
        raise ValidationError(
            'That phone number is not valid. It should have 8 to 15 digits, '
            'for example +639171234567.',
            code='invalid_format',
        )

    # Extra check for Philippine mobile numbers: +63 9XX XXX XXXX (10 digits after +63).
    if number.startswith('+63') and not re.fullmatch(r'\+639\d{9}', number):
        raise ValidationError(
            'Philippine mobile numbers must look like +639XXXXXXXXX or 09XXXXXXXXX (11 digits).',
            code='invalid_ph_number',
        )

    return number
