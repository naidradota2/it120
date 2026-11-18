/* Compose page: character/segment counter, live preview, contact picker,
 * client-side validation and double-submit protection.
 * The server validates everything again - this script only gives faster feedback. */
(function () {
  'use strict';

  const form = document.getElementById('sms-form');
  if (!form) return;

  const contactSelect = document.getElementById('id_contact');
  const recipient = document.getElementById('id_recipient');
  const body = document.getElementById('id_body');
  const maxLength = parseInt(document.getElementById('counter').dataset.max, 10);

  const el = (id) => document.getElementById(id);

  // --- SMS encoding and segment calculation -----------------------------------
  // Basic GSM 03.38 character set (1 unit each) and extension table (2 units each).
  const GSM_BASIC = '@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !"#¤%&\'()*+,-./0123456789:;<=>?' +
    '¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà';
  const GSM_EXTENDED = '^{}\\[~]|€\f';

  function analyse(text) {
    let gsmUnits = 0;
    let isGsm = true;
    for (const ch of text) {
      if (GSM_BASIC.includes(ch)) gsmUnits += 1;
      else if (GSM_EXTENDED.includes(ch)) gsmUnits += 2;
      else { isGsm = false; break; }
    }
    if (isGsm) {
      const units = gsmUnits;
      const perSegment = units <= 160 ? 160 : 153;
      const segments = units === 0 ? 0 : Math.ceil(units / perSegment);
      return { encoding: 'GSM-7', units, segments, perSegment };
    }
    // UCS-2: count UTF-16 code units (emoji take 2).
    const units = text.length;
    const perSegment = units <= 70 ? 70 : 67;
    return { encoding: 'Unicode', units, segments: Math.ceil(units / perSegment), perSegment };
  }

  // --- Validation (mirrors sms_app/validators.py) ------------------------------
  function normalisePhone(raw) {
    let n = (raw || '').trim().replace(/[\s\-().]/g, '');
    if (!n) return { error: 'Please enter the recipient phone number.' };
    if (!/^\+?\d+$/.test(n)) return { error: 'Phone numbers can only contain digits, spaces, dashes and a leading "+".' };
    if (n.startsWith('0')) n = '+63' + n.slice(1);
    else if (n.startsWith('63')) n = '+' + n;
    else if (!n.startsWith('+')) {
      return { error: 'Enter the number in international format (e.g. +639171234567) or Philippine local format (e.g. 09171234567).' };
    }
    if (!/^\+[1-9]\d{7,14}$/.test(n)) return { error: 'That phone number is not valid. It should have 8 to 15 digits, for example +639171234567.' };
    if (n.startsWith('+63') && !/^\+639\d{9}$/.test(n)) {
      return { error: 'Philippine mobile numbers must look like +639XXXXXXXXX or 09XXXXXXXXX (11 digits).' };
    }
    return { value: n };
  }

  function setInvalid(input, feedbackId, message) {
    input.classList.toggle('is-invalid', Boolean(message));
    if (message) el(feedbackId).textContent = message;
  }

  // --- UI updates ----------------------------------------------------------------
  function updateCounter() {
    const text = body.value;
    const info = analyse(text);
    el('char-count').textContent = text.length;
    el('segment-count').textContent = info.segments;
    el('encoding').textContent = info.encoding;
    el('encoding').className = 'badge border ' + (info.encoding === 'GSM-7' ? 'text-bg-light' : 'text-bg-warning');
    const used = info.units % info.perSegment;
    el('chars-left').textContent = info.units === 0 ? info.perSegment : (used === 0 ? 0 : info.perSegment - used);

    const pct = Math.min(100, Math.round((text.length / maxLength) * 100));
    const bar = el('char-progress');
    bar.style.width = pct + '%';
    bar.className = 'progress-bar ' + (pct >= 90 ? 'bg-danger' : pct >= 70 ? 'bg-warning' : '');
  }

  function updatePreview() {
    const option = contactSelect.selectedOptions[0];
    const phone = normalisePhone(recipient.value);
    let to = recipient.value.trim() ? (phone.value || recipient.value.trim()) : 'No recipient yet';
    if (option && option.value && option.dataset.phone === phone.value) {
      to = option.dataset.name + ' · ' + option.dataset.phone;
    }
    el('preview-to').textContent = to;

    const bubble = el('preview-bubble');
    if (body.value.trim()) {
      bubble.textContent = body.value; // textContent: never interpreted as HTML
    } else {
      bubble.innerHTML = '<span class="text-body-secondary fst-italic">Your message will appear here…</span>';
    }
    const info = analyse(body.value);
    el('preview-meta').textContent = info.segments ? `${info.segments} SMS · ${info.encoding}` : '';
  }

  function refresh() { updateCounter(); updatePreview(); }

  // --- Events ----------------------------------------------------------------------
  contactSelect.addEventListener('change', () => {
    const option = contactSelect.selectedOptions[0];
    if (option && option.value) {
      recipient.value = option.dataset.phone;
      setInvalid(recipient, 'recipient-feedback', '');
    }
    refresh();
  });

  recipient.addEventListener('input', () => {
    // If the typed number no longer matches the chosen contact, unselect it.
    const option = contactSelect.selectedOptions[0];
    if (option && option.value && normalisePhone(recipient.value).value !== option.dataset.phone) {
      contactSelect.value = '';
    }
    if (recipient.classList.contains('is-invalid')) setInvalid(recipient, 'recipient-feedback', normalisePhone(recipient.value).error);
    refresh();
  });

  body.addEventListener('input', () => {
    if (body.classList.contains('is-invalid') && body.value.trim()) setInvalid(body, 'body-feedback', '');
    refresh();
  });

  form.addEventListener('reset', () => {
    setTimeout(() => {
      recipient.classList.remove('is-invalid');
      body.classList.remove('is-invalid');
      refresh();
    }, 0);
  });

  form.addEventListener('submit', (event) => {
    const phoneError = normalisePhone(recipient.value).error;
    const bodyError = body.value.trim() ? '' : 'Please enter a message.';
    setInvalid(recipient, 'recipient-feedback', phoneError);
    setInvalid(body, 'body-feedback', bodyError);

    if (phoneError || bodyError) {
      event.preventDefault();
      (phoneError ? recipient : body).focus();
      return;
    }
    // Prevent double-sending (and double-charging) on repeated clicks.
    const btn = el('send-btn');
    btn.disabled = true;
    el('send-spinner').classList.remove('d-none');
    el('send-icon').classList.add('d-none');
  });

  refresh();
})();
