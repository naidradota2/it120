from django import forms
from django.core.exceptions import ValidationError

from .models import Contact
from .validators import normalize_phone_number

MESSAGE_MAX_LENGTH = 480  # about 3 SMS segments


class SMSForm(forms.Form):
    contact = forms.ModelChoiceField(
        queryset=Contact.objects.all(),
        required=False,
        empty_label='— Type a number below or choose a contact —',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_contact'}),
    )
    recipient = forms.CharField(
        label='Recipient phone number',
        required=False,  # may come from the selected contact; checked in clean()
        max_length=25,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+639171234567 or 09171234567',
            'autocomplete': 'tel',
            'inputmode': 'tel',
        }),
        help_text='International format (+63...) or Philippine local format (09...).',
    )
    body = forms.CharField(
        label='Message',
        max_length=MESSAGE_MAX_LENGTH,
        strip=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 5,
            'placeholder': 'Type your message…',
            'maxlength': MESSAGE_MAX_LENGTH,
        }),
        error_messages={
            'required': 'Please enter a message.',
            'max_length': f'The message is too long (maximum {MESSAGE_MAX_LENGTH} characters).',
        },
    )

    def clean_body(self):
        body = self.cleaned_data.get('body', '')
        if not body.strip():
            raise ValidationError('Please enter a message.')
        return body

    def clean(self):
        cleaned = super().clean()
        contact = cleaned.get('contact')
        raw_number = (cleaned.get('recipient') or '').strip()

        if not raw_number and contact:
            raw_number = contact.phone_number

        try:
            cleaned['recipient'] = normalize_phone_number(raw_number)
        except ValidationError as exc:
            self.add_error('recipient', exc)
        return cleaned


class ContactForm(forms.ModelForm):
    # Allow longer raw input (spaces/dashes); it is normalised to E.164 in clean_phone_number().
    phone_number = forms.CharField(
        label='Phone number',
        max_length=25,
        help_text='Saved in international format (+63...).',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+639171234567 or 09171234567',
            'inputmode': 'tel',
        }),
    )

    class Meta:
        model = Contact
        fields = ['name', 'phone_number', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Juan Dela Cruz'}),
            'notes': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional'}),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise ValidationError('Please enter a name.')
        return name

    def clean_phone_number(self):
        number = normalize_phone_number(self.cleaned_data.get('phone_number'))
        duplicate = Contact.objects.filter(phone_number=number).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise ValidationError('A contact with this phone number already exists.')
        return number
