from django.db import models
from django.urls import reverse


class Contact(models.Model):
    """A saved recipient the user can pick when composing an SMS."""

    name = models.CharField(max_length=100)
    phone_number = models.CharField(
        max_length=16,
        unique=True,
        help_text='Stored in international (E.164) format, e.g. +639171234567.',
    )
    notes = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.phone_number})'


class Message(models.Model):
    """One sending attempt and its latest known status.

    Status flow:
        FAILED_TO_SUBMIT  - the provider never accepted the request (validation,
                            credentials, network or provider error).
        SUBMITTED         - the provider accepted the request. This is NOT delivery.
        SENT              - the phone/carrier reports the SMS left the device.
        DELIVERED         - the carrier confirmed delivery to the recipient.
        FAILED            - the provider/carrier reported a final failure.
        UNKNOWN           - no delivery report received (may still change).
    """

    class Status(models.TextChoices):
        FAILED_TO_SUBMIT = 'failed_to_submit', 'Not submitted'
        SUBMITTED = 'submitted', 'Submitted'
        SENT = 'sent', 'Sent'
        DELIVERED = 'delivered', 'Delivered'
        FAILED = 'failed', 'Failed'
        UNKNOWN = 'unknown', 'Unknown'

    # Statuses that will not change any more, so there is no point re-checking them.
    FINAL_STATUSES = {Status.FAILED_TO_SUBMIT, Status.DELIVERED, Status.FAILED}

    recipient = models.CharField(max_length=16)
    contact = models.ForeignKey(
        Contact, null=True, blank=True, on_delete=models.SET_NULL, related_name='messages'
    )
    body = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    provider = models.CharField(max_length=20)
    provider_reference = models.CharField(
        max_length=100, blank=True, help_text="Provider's batch/message id, used to check status."
    )
    provider_status = models.CharField(
        max_length=40, blank=True, help_text='Raw status text last reported by the provider.'
    )
    error_message = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'To {self.recipient} [{self.get_status_display()}]'

    def get_absolute_url(self):
        return reverse('sms_app:message_detail', args=[self.pk])

    @property
    def can_refresh_status(self):
        return bool(self.provider_reference) and self.status not in self.FINAL_STATUSES

    @property
    def status_badge(self):
        """Bootstrap colour for the status badge."""
        return {
            self.Status.FAILED_TO_SUBMIT: 'danger',
            self.Status.SUBMITTED: 'info',
            self.Status.SENT: 'primary',
            self.Status.DELIVERED: 'success',
            self.Status.FAILED: 'danger',
            self.Status.UNKNOWN: 'secondary',
        }.get(self.status, 'secondary')

    @property
    def progress_steps(self):
        """Steps for the status timeline: list of (label, state) where state is
        'done', 'current', 'failed' or 'todo'."""
        order = [self.Status.SUBMITTED, self.Status.SENT, self.Status.DELIVERED]
        labels = ['Submitted to provider', 'Sent from phone', 'Delivered to recipient']

        if self.status == self.Status.FAILED_TO_SUBMIT:
            return [('Not accepted by provider', 'failed')] + [(lbl, 'todo') for lbl in labels[1:]]
        if self.status == self.Status.FAILED:
            return [(labels[0], 'done'), ('Sending failed', 'failed'), (labels[2], 'todo')]
        if self.status == self.Status.UNKNOWN:
            return [(labels[0], 'done'), (labels[1], 'done'), ('Delivery not confirmed', 'current')]

        # Steps up to the current status are done; the next one is in progress.
        reached = order.index(self.status)
        steps = []
        for i, label in enumerate(labels):
            if i <= reached:
                steps.append((label, 'done'))
            elif i == reached + 1:
                steps.append((label, 'current'))
            else:
                steps.append((label, 'todo'))
        return steps

    @property
    def status_explanation(self):
        return {
            self.Status.FAILED_TO_SUBMIT: 'The SMS provider did not accept this message.',
            self.Status.SUBMITTED: 'Accepted by the provider and queued. Delivery is not confirmed yet.',
            self.Status.SENT: 'The SMS left the sending phone. Waiting for a delivery report.',
            self.Status.DELIVERED: 'The carrier confirmed the message was delivered.',
            self.Status.FAILED: 'The provider or carrier reported that sending failed.',
            self.Status.UNKNOWN: 'No delivery report was received. The status may still change.',
        }.get(self.status, '')
