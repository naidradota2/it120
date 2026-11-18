from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import MESSAGE_MAX_LENGTH, ContactForm, SMSForm
from .models import Contact, Message
from .services import refresh_status, send_sms


# --- Sending -------------------------------------------------------------------

@login_required
def compose(request):
    """Show the SMS form (GET) and send the message (POST)."""
    if request.method == 'POST':
        form = SMSForm(request.POST)
        if form.is_valid():
            recipient = form.cleaned_data['recipient']
            body = form.cleaned_data['body']
            # Link the message to a saved contact if the number belongs to one.
            contact = Contact.objects.filter(phone_number=recipient).first()

            message, error = send_sms(recipient, body, contact)
            if error:
                messages.error(request, f'Message not sent. {error}')
                # Keep what the user typed so they can fix the problem and retry.
                return render(request, 'sms_app/compose.html', _compose_context(form, message))

            messages.success(
                request,
                f'Message submitted to the SMS provider for {recipient}. '
                'Delivery is not confirmed yet. Use "Check status" to see if it was delivered.',
            )
            if message.error_message:
                messages.warning(request, f'Provider warning: {message.error_message}')
            return redirect(message)

        messages.error(request, 'Please fix the errors below and try again.')
    else:
        initial = {}
        contact_id = request.GET.get('contact')
        if contact_id and contact_id.isdigit():
            contact = Contact.objects.filter(pk=contact_id).first()
            if contact:
                initial = {'contact': contact, 'recipient': contact.phone_number}
        form = SMSForm(initial=initial)

    return render(request, 'sms_app/compose.html', _compose_context(form))


def _compose_context(form, failed_message=None):
    return {
        'form': form,
        'contacts': Contact.objects.all(),
        'max_length': MESSAGE_MAX_LENGTH,
        'failed_message': failed_message,
        'recent_messages': Message.objects.select_related('contact')[:5],
    }


# --- History & status ------------------------------------------------------------

@login_required
def history(request):
    queryset = Message.objects.select_related('contact')
    status = request.GET.get('status', '')
    query = request.GET.get('q', '').strip()

    if status in Message.Status.values:
        queryset = queryset.filter(status=status)
    if query:
        queryset = queryset.filter(
            Q(recipient__icontains=query) | Q(body__icontains=query) | Q(contact__name__icontains=query)
        )

    page = Paginator(queryset, 15).get_page(request.GET.get('page'))
    return render(request, 'sms_app/history.html', {
        'page': page,
        'status': status,
        'query': query,
        'status_choices': Message.Status.choices,
    })


@login_required
def message_detail(request, pk):
    message = get_object_or_404(Message.objects.select_related('contact'), pk=pk)
    return render(request, 'sms_app/message_detail.html', {'message': message})


@login_required
@require_POST
def message_refresh(request, pk):
    message = get_object_or_404(Message, pk=pk)
    if not message.can_refresh_status:
        messages.info(request, 'This message already has a final status.')
    else:
        error = refresh_status(message)
        if error:
            messages.error(request, f'Could not check the status. {error}')
        else:
            messages.info(request, f'Status updated: {message.get_status_display()}.')
    # Only follow "next" if it points to this site (prevents open redirects).
    next_url = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = message.get_absolute_url()
    return redirect(next_url)


@login_required
@require_POST
def refresh_all(request):
    """Re-check every message that does not have a final status yet."""
    pending = [m for m in Message.objects.exclude(provider_reference='')[:50] if m.can_refresh_status]
    errors = 0
    for message in pending[:20]:
        if refresh_status(message):
            errors += 1
    if not pending:
        messages.info(request, 'There are no messages waiting for a status update.')
    elif errors:
        messages.warning(request, f'Checked {len(pending[:20])} message(s); {errors} could not be checked.')
    else:
        messages.success(request, f'Checked {len(pending[:20])} message(s).')
    return redirect('sms_app:history')


# --- Dashboard -------------------------------------------------------------------

@login_required
def dashboard(request):
    counts = dict(Message.objects.values_list('status').annotate(n=Count('id')))
    total = sum(counts.values())
    submitted = total - counts.get(Message.Status.FAILED_TO_SUBMIT, 0)
    delivered = counts.get(Message.Status.DELIVERED, 0)
    failed = counts.get(Message.Status.FAILED, 0) + counts.get(Message.Status.FAILED_TO_SUBMIT, 0)

    status_rows = [
        {
            'value': value,
            'label': label,
            'count': counts.get(value, 0),
            'percent': round(counts.get(value, 0) * 100 / total) if total else 0,
            'badge': Message(status=value).status_badge,
        }
        for value, label in Message.Status.choices
    ]

    return render(request, 'sms_app/dashboard.html', {
        'total': total,
        'submitted': submitted,
        'delivered': delivered,
        'failed': failed,
        'submit_rate': round(submitted * 100 / total) if total else 0,
        'delivery_rate': round(delivered * 100 / submitted) if submitted else 0,
        'status_rows': status_rows,
        'contact_count': Contact.objects.count(),
        'recent_messages': Message.objects.select_related('contact')[:8],
    })


# --- Contacts --------------------------------------------------------------------

@login_required
def contact_list(request):
    query = request.GET.get('q', '').strip()
    contacts = Contact.objects.annotate(message_count=Count('messages'))
    if query:
        contacts = contacts.filter(Q(name__icontains=query) | Q(phone_number__icontains=query))
    return render(request, 'sms_app/contact_list.html', {'contacts': contacts, 'query': query})


@login_required
def contact_create(request):
    form = ContactForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            contact = form.save()
            messages.success(request, f'Contact "{contact.name}" saved.')
            return redirect('sms_app:contact_list')
        messages.error(request, 'Please fix the errors below.')
    return render(request, 'sms_app/contact_form.html', {'form': form, 'is_new': True})


@login_required
def contact_edit(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    form = ContactForm(request.POST or None, instance=contact)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, f'Contact "{contact.name}" updated.')
            return redirect('sms_app:contact_list')
        messages.error(request, 'Please fix the errors below.')
    return render(request, 'sms_app/contact_form.html', {'form': form, 'is_new': False, 'contact': contact})


@login_required
def contact_delete(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    if request.method == 'POST':
        name = contact.name
        contact.delete()
        messages.success(request, f'Contact "{name}" deleted. Their message history was kept.')
        return redirect('sms_app:contact_list')
    return render(request, 'sms_app/contact_confirm_delete.html', {'contact': contact})
