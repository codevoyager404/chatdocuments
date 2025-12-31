// Μήνυμα "Ανέβασμα εγγράφου..." με animation
const stream = document.getElementById('stream');
const input = document.getElementById('input');
const sendBtn = document.getElementById('sendBtn');
const themeBtn = document.getElementById('themeBtn');
function getTypingRow() { return document.getElementById('typingRow'); }
const attachBtn = document.getElementById('attachBtn');
const fileInput = document.getElementById('fileInput');
const attachmentsWrap = document.getElementById('attachmentsWrap');
const attachmentsTrack = document.getElementById('attachmentsTrack');
const attPrev = document.getElementById('attPrev');
const attNext = document.getElementById('attNext');
let attachments = [];
const disableLLM = document.getElementById('disableLLM');
const llmExtractive = document.getElementById('llmExtractive');
const disableLLMBtn = document.getElementById('disableLLMBtn');
const llmExtractiveBtn = document.getElementById('llmExtractiveBtn');
const kInput = document.getElementById('kInput');
const sidebarBtn = document.getElementById('sidebarBtn');
const sidebar = document.getElementById('sidebar');
const historyList = document.getElementById('historyList');
const newChatBtnHeader = document.getElementById('newChatBtnHeader');
const ctxMenu = document.getElementById('ctxMenu');
let ctxTarget = null;
let isBusy = false;
let pendingControllers = [];
let indexingIndicatorRow = null;
function setBusy(next) {
  isBusy = !!next;
  if (sendBtn) {
    sendBtn.classList.toggle('busy', isBusy);
    if (isBusy) {
      sendBtn.textContent = '⏸';
      sendBtn.setAttribute('aria-label', 'Παύση');
      sendBtn.title = 'Παύση';
      sendBtn.disabled = false;
    } else {
      sendBtn.textContent = '➤';
      sendBtn.setAttribute('aria-label', 'Αποστολή');
      sendBtn.title = 'Αποστολή';
    }
  }
  updateSendAvailability();
}
function updateSendAvailability() {
  if (!sendBtn || !input) return;
  if (isBusy) {
    sendBtn.disabled = false;
    sendBtn.setAttribute('aria-disabled', 'false');
    sendBtn.classList.remove('is-disabled');
    return;
  }
  const hasText = input.value.trim().length > 0;
  const hasPending = (attachments && attachments.some(a => a.status === 'pending'));
  const shouldDisable = !(hasText || hasPending);
  sendBtn.disabled = shouldDisable;
  sendBtn.setAttribute('aria-disabled', shouldDisable ? 'true' : 'false');
  sendBtn.classList.toggle('is-disabled', shouldDisable);
}
function autoResizeTextarea(el) {
  if (!el) return;
  const maxPx = 160;
  const minPx = 46;
  el.style.height = 'auto';
  const next = Math.min(maxPx, Math.max(minPx, el.scrollHeight));
  el.style.height = next + 'px';
  el.style.overflowY = (el.scrollHeight > maxPx) ? 'auto' : 'hidden';
}
function addController(ctrl) { if (ctrl) pendingControllers.push(ctrl); }
function clearControllers() { pendingControllers = []; }
function stopAll() {
  try { for (const c of pendingControllers) { try { c.abort(); } catch { } } } catch { }
  clearControllers();
  if (indexingIndicatorRow) { try { indexingIndicatorRow.remove(); } catch { } indexingIndicatorRow = null; }
  const tr = getTypingRow();
  if (tr) { tr.classList.add('hidden'); }
  setBusy(false);
}
function now() {
  const d = new Date();
  return d.toLocaleTimeString('el-GR', { hour: '2-digit', minute: '2-digit' });
}
function createBubble(text, isMe = false, isError = false) {
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  if (String(text).length > 300) {
    bubble.classList.add('wide');
  }
  if (isError) {
    bubble.classList.add('error');
  }
  bubble.textContent = String(text);
  return bubble;
}
function addMe(text) {
  const row = document.createElement('div');
  row.className = 'msg-row me';
  const bubble = createBubble(text, true, false);
  row.appendChild(bubble);
  stream.appendChild(row);
  stream.parentElement.scrollTop = stream.parentElement.scrollHeight;
  return row;
}
function markQuestionError(userRow, reason, isNoDocs = false) {
  if (!userRow) return;
  userRow.classList.add('is-error');
  if (isNoDocs) userRow.classList.add('no-docs-warning');
  const bubble = userRow.querySelector('.bubble');
  if (bubble) {
    bubble.classList.add('is-error', 'error');
  }
  let note = userRow.querySelector('.status-note');
  if (!note) {
    note = document.createElement('div');
    note.className = 'status-note';
    userRow.appendChild(note);
  }
  if (reason) {
    note.title = String(reason);
    note.textContent = String(reason);
  }
  if (isNoDocs) {
    const sessionId = getCurrentSessionId();
    const messages = getSessionMessagesSync(sessionId);
    if (messages && messages.length > 0) {
      const lastUserMsg = messages[messages.length - 1];
      if (lastUserMsg && lastUserMsg.role === 'user') {
        lastUserMsg.noDocsWarning = true;
        setSessionMessagesSync(sessionId, messages);
      }
    }
  }
}
function addThem(text, meta, isError, sources) {
  const row = document.createElement('div');
  row.className = 'msg-row them' + (isError ? ' error' : '');
  const chunks = splitLongText(String(text), 600);
  row.innerHTML = ``;
  const wrap = document.createElement('div');
  chunks.forEach((chunk, i) => {
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.innerHTML = chunk.replace(/\n/g, '<br>');
    wrap.appendChild(bubble);
    if (i === chunks.length - 1) {
      const metaEl = document.createElement('div');
      metaEl.className = 'meta';
      metaEl.textContent = meta ? escapeHtml(meta) : (now() + ' · bot');
      wrap.appendChild(metaEl);
    }
  });

  // Προσθήκη sources αν υπάρχουν
  if (sources && Array.isArray(sources) && sources.length > 0) {
    const sourcesSection = document.createElement('div');
    sourcesSection.className = 'sources-section';

    const sourcesTitle = document.createElement('div');
    sourcesTitle.className = 'sources-title';
    sourcesTitle.textContent = 'Πηγές:';
    sourcesTitle.title = 'Οι πιο σχετικές πηγές που χρησιμοποιήθηκαν για την απάντηση';
    sourcesSection.appendChild(sourcesTitle);

    const sourcesList = document.createElement('div');
    sourcesList.className = 'sources-list';

    sources.forEach(source => {
      const tag = document.createElement('div');
      tag.className = 'source-tag';
      tag.title = `${source.filename} - Σελίδα/Διαφάνεια ${source.page}`;

      const icon = document.createElement('span');
      icon.className = 'source-icon';
      // Διαφορετικό icon ανάλογα με τον τύπο αρχείου
      if (source.filename.toLowerCase().endsWith('.pdf')) {
        icon.textContent = '📄';
      } else if (source.filename.toLowerCase().endsWith('.pptx')) {
        icon.textContent = '📊';
      } else {
        icon.textContent = '📎';
      }
      tag.appendChild(icon);

      const filename = document.createElement('span');
      filename.className = 'source-filename';
      // Αφαιρούμε την κατάληξη για πιο καθαρή εμφάνιση
      const nameWithoutExt = source.filename.replace(/\.(pdf|pptx)$/i, '');
      filename.textContent = nameWithoutExt;
      tag.appendChild(filename);

      const page = document.createElement('span');
      page.className = 'source-page';
      page.textContent = ` • σελ. ${source.page}`;
      tag.appendChild(page);

      sourcesList.appendChild(tag);
    });

    sourcesSection.appendChild(sourcesList);
    wrap.appendChild(sourcesSection);
  }

  row.appendChild(wrap);
  stream.appendChild(row);
  stream.parentElement.scrollTop = stream.parentElement.scrollHeight;
}
function splitLongText(text, maxLen) {
  const parts = [];
  let remaining = text;
  while (remaining.length > maxLen) {
    let idx = remaining.lastIndexOf(" ", maxLen);
    if (idx <= 0) idx = maxLen;
    parts.push(remaining.slice(0, idx));
    remaining = remaining.slice(idx).trim();
  }
  if (remaining.length) parts.push(remaining);
  return parts;
}
// Μήνυμα "Ανέβασμα εγγράφου..." με animation
function showIndexingMessage() {
  const row = document.createElement('div');
  row.className = 'msg-row them';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  const message = document.createElement('div');
  message.textContent = 'Ανέβασμα εγγράφου...';
  const dots = document.createElement('span');
  dots.className = 'typing';
  dots.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';
  bubble.appendChild(message);
  bubble.appendChild(document.createElement('br'));
  bubble.appendChild(dots);
  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = now() + ' · backend';
  row.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.appendChild(bubble);
  wrap.appendChild(meta);
  row.appendChild(wrap);
  stream.appendChild(row);
  stream.parentElement.scrollTop = stream.parentElement.scrollHeight;
  return row;
}
// Escape html χαρακτήρων
function escapeHtml(str) {
  return String(str).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]) || c);
}
// Κύρια συνάρτηση αποστολής ερώτησης/αρχείων
async function send() {
  const text = input.value.trim();
  const pendingCount = (attachments || []).filter(a => a.status === 'pending').length;
  if (!text && pendingCount === 0) return;
  setBusy(true);
  let userRow = null;
  let originalInputValue = text;
  // Ανέβασμα αρχείων αν υπάρχουν
  if (attachments && attachments.length > 0) {
    const toIndex = attachments.filter(a => a.status === 'pending');
    if (toIndex.length > 0) {
      if (text) { indexingIndicatorRow = showIndexingMessage(); }
      try {
        const uploadResults = await Promise.all(toIndex.map(uploadAttachment));
        if (!isBusy) {
          if (indexingIndicatorRow) { indexingIndicatorRow.remove(); indexingIndicatorRow = null; }
          setBusy(false);
          return;
        }
        const failedUploads = uploadResults.filter(result => result === false);
        if (failedUploads.length > 0 && text) {
          if (indexingIndicatorRow) { indexingIndicatorRow.remove(); indexingIndicatorRow = null; }
          setBusy(false);
          return;
        }
      } catch (_e) {
        if (!isBusy) {
          if (indexingIndicatorRow) { indexingIndicatorRow.remove(); indexingIndicatorRow = null; }
          setBusy(false);
          return;
        }
      }
      if (indexingIndicatorRow) { indexingIndicatorRow.remove(); indexingIndicatorRow = null; }
      if (!text) { setBusy(false); return; }
    }
  }
  // Αν ο χρήστης σταμάτησε
  if (!isBusy) {
    setBusy(false);
    return;
  }
  // Προσθήκη δικού μου μηνύματος
  if (text) {
    userRow = addMe(text);
    try {
      const sid = ensureCurrentSession();
      const msgs = getSessionMessagesSync(sid);
      msgs.push({ role: 'user', text });
      setSessionMessagesSync(sid, msgs);
      renameSessionIfNeeded(sid, text);
    } catch { }
  }
  input.value = '';
  queueMicrotask(() => autoResizeTextarea(input));
  // Εμφάνιση typing row
  const tr = getTypingRow();
  if (tr) {
    tr.classList.remove('hidden');
    stream.appendChild(tr);
  }
  stream.parentElement.scrollTop = stream.parentElement.scrollHeight;
  // Αν ακυρωθεί, επαναφορά
  if (!isBusy) {
    if (userRow) {
      userRow.remove();
    }
    input.value = originalInputValue;
    queueMicrotask(() => autoResizeTextarea(input));
    setBusy(false);
    return;
  }
  // Αποστολή ερώτησης στο backend
  try {
    const fd = new FormData();
    fd.append('question', text || 'Ερώτηση για τα ανεβασμένα έγγραφα');
    const kValue = (kInput && kInput.value) ? parseInt(kInput.value, 10) : 15;
    fd.append('k', String(Math.max(1, Math.min(50, kValue || 15))));  // k μεταξύ 1-50
    fd.append('use_llm', (disableLLM && disableLLM.checked) ? '0' : '1');
    fd.append('llm_extractive', (llmExtractive && llmExtractive.checked) ? '1' : '0');
    fd.append('session_id', getCurrentSessionId());
    const ctrlQ = new AbortController();
    addController(ctrlQ);
    const res = await fetch('/query', { method: 'POST', body: fd, signal: ctrlQ.signal });
    const data = await res.json();
    const tr2 = getTypingRow();
    if (tr2) { tr2.classList.add('hidden'); }
    if (!data.ok) {
      if (data.message && data.suggestion) {
        const fullMessage = `${data.error}\n\n${data.message}\n\n${data.suggestion}`;
        if (userRow) markQuestionError(userRow, fullMessage, true);
      } else {
        if (userRow) markQuestionError(userRow, data.error || 'Σφάλμα', true);
      }
      setBusy(false);
      return;
    }
    addThem(data.answer, null, false, data.sources);
    try {
      const sid = ensureCurrentSession();
      const msgs = getSessionMessagesSync(sid);
      msgs.push({ role: 'bot', text: data.answer, sources: data.sources });
      setSessionMessagesSync(sid, msgs);
    } catch { }
  } catch (err) {
    const tr3 = getTypingRow();
    if (tr3) { tr3.classList.add('hidden'); }
    if (!(err && err.name === 'AbortError')) {
      if (userRow) markQuestionError(userRow, err && err.message);
    }
  }
  setBusy(false);
}
// Event listeners για input/κουμπί αποστολής
if (input) {
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (isBusy) {
        stopAll();
      } else {
        if (sendBtn && sendBtn.disabled) return;
        send();
      }
    }
    queueMicrotask(() => autoResizeTextarea(input));
  });
  input.addEventListener('input', () => autoResizeTextarea(input));
  input.addEventListener('input', updateSendAvailability);
  queueMicrotask(() => { autoResizeTextarea(input); updateSendAvailability(); });
}
if (sendBtn) {
  sendBtn.addEventListener('click', () => {
    if (isBusy) {
      stopAll();
    } else {
      if (sendBtn.disabled) { return; }
      send();
    }
  });
}
// Εναλλαγή θέματος (dark/light)
if (themeBtn) {
  themeBtn.addEventListener('click', () => {
    document.body.classList.toggle('light');
  });
}
// Συντόμευση Ctrl+K ή Cmd+K για αλλαγή θέματος
window.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault(); document.body.classList.toggle('light');
  }
});
// Άνοιγμα file input με κουμπί
if (attachBtn) { attachBtn.addEventListener('click', () => fileInput && fileInput.click()); }
// Όταν ανεβαίνουν αρχεία από file input
if (fileInput) {
  fileInput.addEventListener('change', (ev) => {
    const files = Array.from(ev.target.files || []);
    if (!files.length) return;
    files.forEach(addAttachmentChip);
    updateAttachmentsUI();
    fileInput.value = '';
  });
}

// Drag and Drop Functionality 
let dragCounter = 0; // Μετράει πόσες φορές μπήκε στο drag zone

// Δημιουργία overlay για visual feedback κατά το drag
const dragOverlay = document.createElement('div');
dragOverlay.className = 'drag-overlay';
dragOverlay.innerHTML = `
  <div class="drag-content">
    <div class="drag-icon">📁</div>
    <div class="drag-text">Αφήστε τα αρχεία εδώ</div>
    <div class="drag-subtext">Υποστηρίζονται PDF και PowerPoint αρχεία</div>
  </div>
`;
dragOverlay.style.display = 'none';
document.body.appendChild(dragOverlay);

// Φιλτράρει μόνο αρχεία (όχι folders ή άλλα)
function filterValidFiles(items) {
  const validFiles = [];
  if (!items) return validFiles;

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    // Έλεγχος αν είναι αρχείο (όχι directory)
    if (item.kind === 'file') {
      const file = item.getAsFile();
      if (file) {
        // Έλεγχος τύπου αρχείου
        const name = file.name.toLowerCase();
        if (name.endsWith('.pdf') || name.endsWith('.pptx')) {
          validFiles.push(file);
        }
      }
    }
  }
  return validFiles;
}

// Προβολή drag overlay
function showDragOverlay() {
  if (dragOverlay) {
    dragOverlay.style.display = 'flex';
    setTimeout(() => {
      dragOverlay.classList.add('visible');
    }, 10);
  }
}

// Απόκρυψη drag overlay
function hideDragOverlay() {
  if (dragOverlay) {
    dragOverlay.classList.remove('visible');
    setTimeout(() => {
      dragOverlay.style.display = 'none';
    }, 200);
  }
}

// Event: Όταν αρχίζει το drag πάνω στο παράθυρο
document.addEventListener('dragenter', (e) => {
  e.preventDefault();
  dragCounter++;

  // Έλεγχος αν υπάρχουν αρχεία
  if (e.dataTransfer && e.dataTransfer.types && e.dataTransfer.types.includes('Files')) {
    if (dragCounter === 1) {
      showDragOverlay();
    }
  }
});

// Event: Κατά τη διάρκεια του drag
document.addEventListener('dragover', (e) => {
  e.preventDefault();
  // Ορίζει το effect σε copy (εμφανίζει + cursor)
  if (e.dataTransfer) {
    e.dataTransfer.dropEffect = 'copy';
  }
});

// Event: Όταν το drag φεύγει από το παράθυρο
document.addEventListener('dragleave', (e) => {
  e.preventDefault();
  dragCounter--;

  if (dragCounter === 0) {
    hideDragOverlay();
  }
});

// Event: Όταν γίνεται drop
document.addEventListener('drop', (e) => {
  e.preventDefault();
  e.stopPropagation();

  dragCounter = 0;
  hideDragOverlay();

  // Παίρνει τα αρχεία που έγιναν drop
  let files = [];

  if (e.dataTransfer && e.dataTransfer.items) {
    // Χρήση DataTransferItemList (πιο σύγχρονο API)
    files = filterValidFiles(e.dataTransfer.items);
  } else if (e.dataTransfer && e.dataTransfer.files) {
    // Fallback σε παλιό API
    const allFiles = Array.from(e.dataTransfer.files);
    files = allFiles.filter(f => {
      const name = f.name.toLowerCase();
      return name.endsWith('.pdf') || name.endsWith('.pptx');
    });
  }

  if (files.length === 0) {
    showError({
      title: 'Μη έγκυρα αρχεία',
      desc: 'Παρακαλώ σύρετε μόνο PDF ή PowerPoint αρχεία (.pdf, .pptx)'
    });
    return;
  }

  // Προσθήκη αρχείων στα attachments
  files.forEach(addAttachmentChip);
  updateAttachmentsUI();

  // Εμφάνιση toast notification (προαιρετικά)
  const plural = files.length > 1;
  console.log(`Προστέθηκαν ${files.length} αρχεί${plural ? 'α' : 'ο'}`);
});

// Αποτρέπει το default behavior του browser (άνοιγμα αρχείου)
window.addEventListener('dragover', (e) => {
  e.preventDefault();
}, false);

window.addEventListener('drop', (e) => {
  e.preventDefault();
}, false);
// Δημιουργία chip για κάθε αρχείο
function addAttachmentChip(file) {
  if (!attachmentsTrack) return;
  const kind = guessKind(file.name);
  const chip = document.createElement('div');
  chip.className = 'file-chip';
  chip.setAttribute('data-kind', kind);
  chip.setAttribute('title', file.name);
  const sizeKb = Math.max(1, Math.round(file.size / 1024));
  chip.innerHTML = `
    <div class="icon" aria-hidden="true">${kindIcon(kind)}</div>
    <div class="meta">
      <div class="name">${escapeHtml(file.name)}</div>
      <div class="sub">Σε αναμονή</div>
    </div>
    <div class="progress" aria-hidden="true" hidden><div class="fill" style="width:0%"></div></div>
    <div class="actions" style="display:flex; gap:4px; align-items:center; margin-left:4px;">
      <button class="cancel" aria-label="Διακοπή" hidden>⏹</button>
      <button class="retry" aria-label="Επανάληψη" hidden>↻</button>
      <button class="info" aria-label="Πληροφορίες" hidden>ℹ</button>
    </div>
    <button class="close" aria-label="Αφαίρεση">×</button>
  `;
  const entry = { file, el: chip, status: 'pending', errorMessage: '' };
  attachments.push(entry);
  attachmentsTrack.appendChild(chip);
  // Κλείσιμο/αφαίρεση αρχείου
  chip.querySelector('.close').addEventListener('click', () => {
    const wasSuccess = entry.status === 'success';
    try { if (entry && entry._aborter) { entry._aborter(); } } catch { }
    attachments = attachments.filter(x => x !== entry);
    chip.remove();
    updateAttachmentsUI();
    updateSendAvailability();
    if (wasSuccess && entry && entry.file && entry.file.name) {
      try {
        const fd = new FormData();
        fd.append('filename', entry.file.name);
        fd.append('session_id', getCurrentSessionId());
        fetch('/index/remove', { method: 'POST', body: fd });
      } catch { }
    }
  });
  // Retry κουμπί
  const retryBtn = chip.querySelector('.retry');
  if (retryBtn) {
    retryBtn.addEventListener('click', async () => {
      if (entry.status !== 'error') return;
      updateChipStatus(entry, 'uploading');
      await uploadAttachment(entry);
    });
  }
  // Cancel κουμπί
  const cancelBtn = chip.querySelector('.cancel');
  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => {
      if (entry.status !== 'uploading') return;
      try { if (entry && entry._aborter) { entry._aborter(); } } catch { }
      updateChipStatus(entry, 'canceled');
    });
  }
  // Info κουμπί για σφάλματα
  const infoBtn = chip.querySelector('.info');
  if (infoBtn) {
    infoBtn.addEventListener('click', () => {
      if (!entry.errorMessage) { return; }
      showError({
        title: 'Λεπτομέρειες σφάλματος',
        desc: escapeHtml(entry.errorMessage || 'Άγνωστο σφάλμα')
      });
    });
  }
  updateChipStatus(entry, 'pending');
}
// Ενημέρωση UI όταν αλλάζουν attachments
function updateAttachmentsUI() {
  if (!attachmentsWrap || !attachmentsTrack) return;
  const has = attachments.length > 0;
  attachmentsWrap.hidden = !has;
  queueMicrotask(() => {
    if (!attPrev || !attNext) return;
    const canScrollLeft = attachmentsTrack.scrollLeft > 0;
    const canScrollRight = attachmentsTrack.scrollLeft + attachmentsTrack.clientWidth < attachmentsTrack.scrollWidth - 1;
    attPrev.disabled = !canScrollLeft;
    attNext.disabled = !canScrollRight;
  });
}
// Καθαρισμός όλων των attachments
function clearAttachments() {
  attachments = [];
  if (attachmentsTrack) { attachmentsTrack.innerHTML = ''; }
  updateAttachmentsUI();
  updateSendAvailability();
}
// Ενημέρωση κατάστασης ενός attachment (pending, uploading, success, error, canceled)
function updateChipStatus(entry, status, errorMsg) {
  if (!entry || !entry.el) return;
  entry.status = status;
  entry.errorMessage = errorMsg || '';
  const chip = entry.el;
  chip.classList.remove('is-pending', 'is-uploading', 'is-success', 'is-error', 'is-canceled');
  chip.classList.add(
    status === 'pending' ? 'is-pending' :
      status === 'uploading' ? 'is-uploading' :
        status === 'success' ? 'is-success' :
          status === 'canceled' ? 'is-canceled' : 'is-error'
  );
  // Ενημέρωση κειμένου κατάστασης
  const sub = chip.querySelector('.sub');
  if (sub) {
    if (status === 'pending') sub.textContent = 'Σε αναμονή';
    else if (status === 'uploading') sub.textContent = 'Μεταφόρτωση…';
    else if (status === 'success') sub.textContent = 'Ολοκληρώθηκε';
    else if (status === 'canceled') sub.textContent = 'Ακυρώθηκε';
    else sub.textContent = 'Απέτυχε';
  }
  // Εμφάνιση/απόκρυψη κουμπιών (retry, info, cancel)
  const retryBtn = chip.querySelector('.retry');
  const infoBtn = chip.querySelector('.info');
  const cancelBtn = chip.querySelector('.cancel');
  if (retryBtn) {
    retryBtn.hidden = status !== 'error';
    retryBtn.disabled = status === 'uploading';
  }
  if (infoBtn) { infoBtn.hidden = status !== 'error'; }
  if (cancelBtn) { cancelBtn.hidden = status !== 'uploading'; }
  // Progress bar
  const fill = chip.querySelector('.progress .fill');
  const prog = chip.querySelector('.progress');
  if (prog) { prog.hidden = status !== 'uploading'; }
  if (fill && status !== 'uploading') { fill.style.width = '0%'; }
  updateAttachmentsUI();
  updateSendAvailability();
}
// Ρύθμιση progress ποσοστού (πχ. 50%)
function setChipProgress(entry, percent) {
  if (!entry || !entry.el) return;
  const fill = entry.el.querySelector('.progress .fill');
  if (!fill) return;
  const pct = Math.max(0, Math.min(100, Number(percent) || 0));
  fill.style.width = pct + '%';
}
// Αποστολή attachment στο backend
async function uploadAttachment(entry) {
  if (!entry || !entry.file) return false;
  updateChipStatus(entry, 'uploading');
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    // Abort χειρισμός
    const aborter = () => { try { xhr.abort(); } catch { } };
    addController({ abort: aborter });
    entry._aborter = aborter;
    // Ρύθμιση request
    xhr.open('POST', '/index/batch');
    xhr.responseType = 'json';
    // Φτιάχνουμε form με το αρχείο
    const formData = new FormData();
    formData.append('file', entry.file);
    formData.append('session_id', getCurrentSessionId());
    // Ενημέρωση progress bar
    xhr.upload.onprogress = (e) => {
      if (e && e.lengthComputable) {
        const pct = (e.loaded / e.total) * 100;
        setChipProgress(entry, pct);
      }
    };
    // Διαχείριση σφαλμάτων
    xhr.onerror = () => {
      updateChipStatus(entry, 'error', 'Σφάλμα δικτύου');
      resolve(false);
    };
    xhr.onabort = () => {
      updateChipStatus(entry, 'canceled');
      resolve(false);
    };
    // Όταν τελειώσει η αποστολή
    xhr.onload = () => {
      const status = xhr.status || 0;
      const data = xhr.response || null;
      const ok = status >= 200 && status < 300 && data && data.ok;
      if (!ok) {
        let msg = (data && (data.error || data.message)) || ('HTTP ' + status);

        // Αν υπάρχουν failed files, προσθέτουμε λεπτομέρειες
        if (data && data.failed && Array.isArray(data.failed) && data.failed.length > 0) {
          const failedFile = data.failed.find(f => f.name === entry.file.name);
          if (failedFile) {
            msg = failedFile.reason || msg;
            if (failedFile.stage) {
              msg += ` (Στάδιο: ${failedFile.stage})`;
            }
          }
        }

        updateChipStatus(entry, 'error', String(msg));
        resolve(false);
        return;
      }
      // Επιτυχία
      setChipProgress(entry, 100);
      updateChipStatus(entry, 'success');
      try {
        if (data && data.replaced) {
          const sub = entry.el && entry.el.querySelector && entry.el.querySelector('.sub');
          if (sub) { sub.textContent = 'Αντικαταστάθηκε με νεότερο αρχείο'; }
        }
      } catch { }
      // Ανανέωση του index panel αν είναι ανοιχτό (ΔΕΝ το ανοίγουμε αυτόματα)
      try {
        refreshIndexPanelIfOpen();
      } catch { }
      resolve(true);
    };
    // Στείλε το αρχείο
    try {
      xhr.send(formData);
    } catch (_e) {
      updateChipStatus(entry, 'error', 'Αποτυχία αποστολής');
      resolve(false);
    }
  });
}
// Προσδιορισμός τύπου αρχείου με βάση την κατάληξη
function guessKind(name) {
  const ext = String(name).toLowerCase().split('.').pop();
  if (['pdf'].includes(ext)) return 'pdf';
  if (['ppt', 'pptx'].includes(ext)) return 'pptx';
  if (['doc', 'docx'].includes(ext)) return 'docx';
  return 'other';
}
// Επιστρέφει emoji/icon για κάθε τύπο αρχείου
function kindIcon(kind) {
  switch (kind) {
    case 'pdf': return '📄';
    case 'pptx': return '📊';
    default: return '📎';
  }
}
// Κουμπιά πλοήγησης στα attachments (προηγούμενο/επόμενο)
if (attPrev) { attPrev.addEventListener('click', () => attachmentsTrack && attachmentsTrack.scrollBy({ left: -200, behavior: 'smooth' })); }
if (attNext) { attNext.addEventListener('click', () => attachmentsTrack && attachmentsTrack.scrollBy({ left: +200, behavior: 'smooth' })); }
// Ενημέρωση UI όταν γίνεται scroll στη λίστα attachments
if (attachmentsTrack) {
  attachmentsTrack.addEventListener('scroll', updateAttachmentsUI, { passive: true });
}
// Συγχρονίζει το aria-pressed attribute του button με την τιμή του checkbox
function syncAriaFromCheckbox(btn, checkbox) {
  if (!btn || !checkbox) return;
  btn.setAttribute('aria-pressed', checkbox.checked ? 'true' : 'false');
}
// Εναλλάσσει την κατάσταση button/checkbox όταν πατηθεί το κουμπί
function toggleFromButton(btn, checkbox) {
  if (!btn || !checkbox) return;
  const pressed = btn.getAttribute('aria-pressed') === 'true';
  const next = !pressed;
  btn.setAttribute('aria-pressed', next ? 'true' : 'false');
  checkbox.checked = next;
}
// Toggle για το "Απενεργοποίηση LLM"
if (disableLLMBtn && disableLLM) {
  syncAriaFromCheckbox(disableLLMBtn, disableLLM);
  disableLLMBtn.addEventListener('click', () => toggleFromButton(disableLLMBtn, disableLLM));
  disableLLM.addEventListener('change', () => syncAriaFromCheckbox(disableLLMBtn, disableLLM));
}
// Toggle για το "LLM Extractive Mode"
if (llmExtractiveBtn && llmExtractive) {
  syncAriaFromCheckbox(llmExtractiveBtn, llmExtractive);
  llmExtractiveBtn.addEventListener('click', () => toggleFromButton(llmExtractiveBtn, llmExtractive));
  llmExtractive.addEventListener('change', () => syncAriaFromCheckbox(llmExtractiveBtn, llmExtractive));
}
// Εναλλαγή εμφάνισης sidebar (ιστορικό συνομιλιών)
if (sidebarBtn && sidebar) {
  sidebarBtn.addEventListener('click', () => {
    const pressed = sidebarBtn.getAttribute('aria-pressed') === 'true';
    const next = !pressed;
    sidebarBtn.setAttribute('aria-pressed', next ? 'true' : 'false');
    document.body.classList.toggle('with-sidebar', next);
    // Κλείσιμο του index panel αν είναι ανοιχτό
    if (next && document.body.classList.contains('with-index-panel')) {
      document.body.classList.remove('with-index-panel');
      const indexBtn = document.getElementById('indexPanelBtn');
      if (indexBtn) { indexBtn.setAttribute('aria-pressed', 'false'); }
    }
  });
}
// Keys για αποθήκευση sessions στο localStorage
const SESSIONS_KEY = 'chat_sessions';
const CURRENT_KEY = 'chat_current_session';
const AUTO_CLEANUP_KEY = 'chat_auto_cleanup';
// Δημιουργεί μοναδικό ID για κάθε νέα συνεδρία
function genId() {
  return 's_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
}
// Φέρνει όλες τις συνεδρίες από το localStorage
// Επιστρέφει τις αποθηκευμένες συνεδρίες (από backend ή localStorage)
async function getSessions() {
  // Προσπαθεί να φορτώσει από το backend
  try {
    const response = await fetch('/chat/history/list');
    if (response.ok) {
      const data = await response.json();
      if (data.ok && data.sessions && data.sessions.length > 0) {
        // Αποθηκεύει και στο localStorage για fallback
        localStorage.setItem(SESSIONS_KEY, JSON.stringify(data.sessions));
        return data.sessions;
      }
    }
  } catch (err) {
    console.warn('Backend sessions not available, using localStorage:', err);
  }

  // Fallback σε localStorage
  try {
    return JSON.parse(localStorage.getItem(SESSIONS_KEY) || '[]');
  } catch {
    return [];
  }
}

// Συγχρονισμένη έκδοση για backward compatibility
function getSessionsSync() {
  try {
    return JSON.parse(localStorage.getItem(SESSIONS_KEY) || '[]');
  } catch {
    return [];
  }
}

// Αποθηκεύει τις συνεδρίες (localStorage only - το backend αποθηκεύει αυτόματα μέσω save_messages)
function setSessions(list) {
  localStorage.setItem(SESSIONS_KEY, JSON.stringify(list));
}
// Επιστρέφει τα μηνύματα για συγκεκριμένη συνεδρία (από backend ή localStorage)
async function getSessionMessages(sessionId) {
  if (!sessionId) return [];

  // Προσπαθεί να φορτώσει από το backend
  try {
    const response = await fetch(`/chat/history/load?session_id=${encodeURIComponent(sessionId)}`);
    if (response.ok) {
      const data = await response.json();
      if (data.ok && data.messages) {
        // Αποθηκεύει και στο localStorage για fallback
        localStorage.setItem('chat_session:' + sessionId, JSON.stringify(data.messages));
        return data.messages;
      }
    }
  } catch (err) {
    console.warn('Backend chat history not available, using localStorage:', err);
  }

  // Fallback σε localStorage
  try {
    return JSON.parse(localStorage.getItem('chat_session:' + sessionId) || '[]');
  } catch {
    return [];
  }
}

// Αποθηκεύει μηνύματα για συγκεκριμένη συνεδρία (στο backend και localStorage)
async function setSessionMessages(sessionId, msgs) {
  if (!sessionId) return;

  // Αποθηκεύει πρώτα στο localStorage (για άμεση διαθεσιμότητα)
  localStorage.setItem('chat_session:' + sessionId, JSON.stringify(msgs));

  // Παίρνει τα metadata της session
  const sessions = getSessionsSync();
  const session = sessions.find(s => s.id === sessionId);

  // Αποθηκεύει και στο backend με metadata
  try {
    const formData = new FormData();
    formData.append('session_id', sessionId);
    formData.append('messages', JSON.stringify(msgs));
    if (session) {
      formData.append('title', session.title || 'Νέα συνομιλία');
      formData.append('timestamp', session.ts || Date.now());
    }

    await fetch('/chat/history/save', {
      method: 'POST',
      body: formData
    });
  } catch (err) {
    console.warn('Failed to save chat history to backend:', err);
  }
}

// Συγχρονισμένη έκδοση του getSessionMessages για backward compatibility
function getSessionMessagesSync(sessionId) {
  try {
    return JSON.parse(localStorage.getItem('chat_session:' + sessionId) || '[]');
  } catch {
    return [];
  }
}

// Συγχρονισμένη έκδοση του setSessionMessages για backward compatibility
function setSessionMessagesSync(sessionId, msgs) {
  localStorage.setItem('chat_session:' + sessionId, JSON.stringify(msgs));

  // Παίρνει τα metadata της session
  const sessions = getSessionsSync();
  const session = sessions.find(s => s.id === sessionId);

  // Async save στο background με metadata
  (async () => {
    try {
      const formData = new FormData();
      formData.append('session_id', sessionId);
      formData.append('messages', JSON.stringify(msgs));
      if (session) {
        formData.append('title', session.title || 'Νέα συνομιλία');
        formData.append('timestamp', session.ts || Date.now());
      }
      await fetch('/chat/history/save', { method: 'POST', body: formData });
    } catch (err) { }
  })();
}
// Παίρνει το ID της τρέχουσας συνεδρίας
function getCurrentSessionId() {
  return localStorage.getItem(CURRENT_KEY) || '';
}
// Ορίζει το ID της τρέχουσας συνεδρίας
function setCurrentSessionId(id) {
  localStorage.setItem(CURRENT_KEY, id);
}
// Ελέγχει αν το auto-cleanup είναι ενεργοποιημένο
function getAutoCleanupEnabled() {
  return localStorage.getItem(AUTO_CLEANUP_KEY) === 'true';
}
// Ενεργοποιεί/απενεργοποιεί το auto-cleanup
function setAutoCleanupEnabled(enabled) {
  localStorage.setItem(AUTO_CLEANUP_KEY, enabled ? 'true' : 'false');
}
// Καθαρίζει ερωτήσεις χωρίς έγγραφα από μία συνεδρία
function cleanInvalidQuestions(sessionId) {
  const messages = getSessionMessagesSync(sessionId);
  if (!messages || messages.length === 0) return;
  const validMessages = [];
  let i = 0;
  while (i < messages.length) {
    const msg = messages[i];
    // Αν είναι ερώτηση χρήστη με flag noDocsWarning
    if (msg.role === 'user') {
      if (msg.noDocsWarning) {
        i++; // Σβήνει και το bot response που ακολουθεί
        if (i < messages.length && messages[i].role === 'bot') {
          i++;
        }
        continue; // Προχώρα χωρίς να το βάλεις στη λίστα
      }
    }
    validMessages.push(msg);
    i++;
  }
  setSessionMessagesSync(sessionId, validMessages);
  return validMessages.length !== messages.length;
}
// Καθαρίζει όλες τις συνεδρίες από άκυρες ερωτήσεις
function cleanAllInvalidQuestions() {
  const sessions = getSessionsSync();
  let totalCleaned = 0;
  sessions.forEach(session => {
    const cleaned = cleanInvalidQuestions(session.id);
    if (cleaned) {
      totalCleaned++;
    }
  });
  if (totalCleaned > 0) {
    console.log(`Auto-cleanup: Cleaned invalid questions from ${totalCleaned} sessions`);
  }
  return totalCleaned;
}
// Βεβαιώνεται ότι υπάρχει ενεργή συνεδρία, αλλιώς δημιουργεί νέα
function ensureCurrentSession() {
  let id = getCurrentSessionId();
  let sessions = getSessionsSync();
  if (!id || !sessions.find(s => s.id === id)) {
    id = createNewSession();
  }
  return id;
}
// Δημιουργεί νέα συνεδρία και την κάνει ενεργή
function createNewSession() {
  const session = { id: genId(), title: 'Νέα συνομιλία', ts: Date.now() };
  const sessions = getSessionsSync();
  sessions.unshift(session); // μπαίνει πρώτη στη λίστα
  setSessions(sessions);
  setSessionMessagesSync(session.id, []);
  setCurrentSessionId(session.id);
  renderHistory();
  clearChatView();
  return session.id;
}
// Δημιουργεί έξυπνο τίτλο από το κείμενο του χρήστη
function generateSmartTitle(text, maxLength = 50) {
  if (!text) return 'Νέα συνομιλία';

  // Καθαρίζει το κείμενο
  let cleaned = String(text).trim();

  // Αφαιρεί πολλαπλά spaces/newlines
  cleaned = cleaned.replace(/\s+/g, ' ');

  // Βρίσκει την πρώτη πρόταση (μέχρι ., ?, !, ; ή \n)
  const sentenceMatch = cleaned.match(/^[^.?!;\n]+[.?!;]?/);
  if (sentenceMatch) {
    cleaned = sentenceMatch[0].trim();
  }

  // Αφαιρεί τελικούς χαρακτήρες στίξης για πιο καθαρό τίτλο
  cleaned = cleaned.replace(/[.?!;]+$/, '');

  // Περιορίζει στο maxLength
  if (cleaned.length > maxLength) {
    // Κόβει στην τελευταία ολόκληρη λέξη
    cleaned = cleaned.slice(0, maxLength);
    const lastSpace = cleaned.lastIndexOf(' ');
    if (lastSpace > maxLength * 0.7) { // Κόβει μόνο αν δεν χάνουμε πολύ κείμενο
      cleaned = cleaned.slice(0, lastSpace);
    }
    // Προσθέτει ... αν έχει κοπεί
    if (text.length > maxLength) {
      cleaned = cleaned.trim();
    }
  }

  return cleaned.trim() || 'Νέα συνομιλία';
}

// Μετονομάζει τη συνεδρία αν είναι ακόμη "Νέα συνομιλία"
function renameSessionIfNeeded(sessionId, firstUserText) {
  if (!firstUserText) return;
  const sessions = getSessionsSync();
  const s = sessions.find(x => x.id === sessionId);
  if (!s) return;
  if (s.title === 'Νέα συνομιλία') {
    s.title = generateSmartTitle(firstUserText, 50);
    setSessions(sessions);
    renderHistory();
  }
}
// Εμφανίζει το ιστορικό συνεδριών στη sidebar
function renderHistory() {
  if (!historyList) return;
  const sessions = getSessionsSync();
  const current = getCurrentSessionId();
  historyList.innerHTML = '';
  sessions.forEach(s => {
    const btn = document.createElement('button');
    const isActive = s.id === current;
    btn.className = 'item' + (isActive ? ' is-active' : '');
    btn.dataset.id = s.id;
    if (isActive) btn.setAttribute('aria-current', 'page');
    btn.innerHTML = `<span class="label">${escapeHtml(s.title || 'Συνομιλία')}</span>`;
    btn.addEventListener('click', () => {
      setCurrentSessionId(s.id);
      renderHistory();
      renderSessionMessages(s.id);
    });
    historyList.appendChild(btn);
  });
}
// Εμφανίζει τα μηνύματα μιας συνεδρίας
async function renderSessionMessages(sessionId) {
  clearChatView();
  // Αν το auto-cleanup είναι ενεργό, καθαρίζει άκυρα Q&A
  if (getAutoCleanupEnabled()) {
    const cleaned = cleanInvalidQuestions(sessionId);
    if (cleaned) {
      console.log('Auto-cleanup: Removed invalid questions from session');
    }
  }
  // Παίρνει τα αποθηκευμένα μηνύματα και τα δείχνει (από backend)
  const msgs = await getSessionMessages(sessionId);
  for (const m of msgs) {
    if (m.role === 'user') {
      const userRow = addMe(m.text);
      if (m.noDocsWarning) {
        markQuestionError(userRow, 'Δεν έχουν ανέβει ακόμα έγγραφα. Ανεβάστε ένα PDF ή PowerPoint.', true);
      }
    } else {
      addThem(m.text, m.meta, false, m.sources);
    }
  }
  // Βάζει την ένδειξη "πληκτρολογεί…" στο τέλος
  {
    const tr = getTypingRow();
    if (tr) {
      tr.classList.add('hidden');
      stream.appendChild(tr);
    }
  }
}
// Καθαρίζει την οθόνη συνομιλίας
function clearChatView() {
  setBusy(false);
  clearAttachments();
  if (indexingIndicatorRow) {
    try { indexingIndicatorRow.remove(); } catch { }
    indexingIndicatorRow = null;
  }
  clearControllers();
  stream.innerHTML = '';
  const typing = document.createElement('div');
  typing.className = 'msg-row them hidden';
  typing.id = 'typingRow';
  typing.innerHTML = `
          <div>
            <div class="bubble"><span class="typing"><span class="dot"></span><span class="dot"></span><span class="dot"></span></span></div>
            <div class="meta">πληκτρολογεί…</div>
          </div>`;
  stream.appendChild(typing);
}
// Νέο chat από το header
if (newChatBtnHeader) {
  newChatBtnHeader.addEventListener('click', () => {
    const id = createNewSession();
    renderSessionMessages(id);
  });
}
// Αρχικοποίηση ιστορικού συνεδριών (φορτώνει από backend)
(async function initHistory() {
  if (!getAutoCleanupEnabled()) {
    setAutoCleanupEnabled(true);
  }

  // Φορτώνει τα sessions από το backend πρώτα
  const sessions = await getSessions();
  // Αν βρήκε sessions από backend, τα αποθηκεύει στο localStorage
  if (sessions && sessions.length > 0) {
    setSessions(sessions);
  }

  cleanAllInvalidQuestions();
  const id = ensureCurrentSession();
  renderHistory();
  await renderSessionMessages(id);
})();
//  Context Menu 
// Κρύβει το context menu
function hideCtx() { if (ctxMenu) { ctxMenu.hidden = true; ctxTarget = null; } }
document.addEventListener('click', hideCtx);
document.addEventListener('scroll', hideCtx, true);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideCtx(); });
// Ανοίγει context menu σε συγκεκριμένο σημείο
function openCtxMenu(x, y, target) {
  if (!ctxMenu) return;
  ctxTarget = target || null;
  ctxMenu.hidden = false;
  const vw = window.innerWidth || document.documentElement.clientWidth;
  const vh = window.innerHeight || document.documentElement.clientHeight;
  const mw = ctxMenu.offsetWidth || 180;
  const mh = ctxMenu.offsetHeight || 120;
  const left = Math.max(8, Math.min(x, vw - mw - 8));
  const top = Math.max(8, Math.min(y, vh - mh - 8));
  ctxMenu.style.left = left + 'px';
  ctxMenu.style.top = top + 'px';
}
// Δεξί κλικ στο stream (chat)
if (stream) {
  stream.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    openCtxMenu(e.clientX, e.clientY, { type: 'chat' });
  });
}
// Δεξί κλικ στη λίστα ιστορικού
if (historyList) {
  historyList.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    const btn = e.target && e.target.closest && e.target.closest('.item');
    const sid = (btn && btn.dataset && btn.dataset.id) ? btn.dataset.id : getCurrentSessionId();
    openCtxMenu(e.clientX, e.clientY, { type: 'session', id: sid });
  });
}
// Ενέργειες context menu
if (ctxMenu) {
  ctxMenu.addEventListener('click', async (e) => {
    const actionBtn = e.target && e.target.closest && e.target.closest('.ctx-menu-item');
    if (!actionBtn) return;
    const action = actionBtn.getAttribute('data-action');
    const currentId = getCurrentSessionId();
    if (action === 'rename') {
      if (!ctxTarget || (ctxTarget.type !== 'session' && ctxTarget.type !== 'chat')) return hideCtx();
      const sid = ctxTarget.type === 'session' ? ctxTarget.id : currentId;
      const sessions = getSessionsSync();
      const s = sessions.find(x => x.id === sid);
      const next = prompt('Νέος τίτλος:', s ? (s.title || '') : '');
      if (next && s) { s.title = next.slice(0, 64); setSessions(sessions); renderHistory(); }
      hideCtx();
    } else if (action === 'copy') {
      const text = buildQAText(currentId);
      try { await navigator.clipboard.writeText(text); } catch { }
      hideCtx();
    } else if (action === 'delete') {
      const sid = (ctxTarget && ctxTarget.type === 'session') ? ctxTarget.id : currentId;
      if (!sid) return hideCtx();
      hideCtx();
      const ok = await showConfirm({
        title: 'Διαγραφή συνομιλίας',
        desc: 'Είσαι σίγουρος ότι θέλεις να διαγράψεις αυτή τη συνομιλία; Η ενέργεια δεν αναιρείται.',
        okText: 'Διαγραφή',
        okVariant: 'danger',
        cancelText: 'Άκυρο'
      });
      if (ok) { deleteSession(sid); }
    }
  });
}
// Χτίζει κείμενο ερωτήσεων-απαντήσεων για copy
function buildQAText(sessionId) {
  const msgs = getSessionMessagesSync(sessionId) || [];
  const lines = [];
  let qIndex = 1;
  for (const m of msgs) {
    if (m.role === 'user') {
      lines.push(`Q${qIndex}: ${m.text}`);
    } else {
      lines.push(`A${qIndex}: ${m.text}`);
      qIndex++;
    }
  }
  return lines.join('\n\n');
}
// Διαγράφει συνεδρία (localStorage + backend)
async function deleteSession(sessionId) {
  const sessions = getSessionsSync();
  const next = sessions.filter(s => s.id !== sessionId);
  setSessions(next);

  // Διαγραφή από localStorage
  try {
    localStorage.removeItem('chat_session:' + sessionId);
  } catch { }

  // Διαγραφή από backend (chunks + chat history)
  try {
    const fd = new FormData();
    fd.append('session_id', sessionId);
    const response = await fetch('/sessions/remove', { method: 'POST', body: fd });
    if (response.ok) {
      const data = await response.json();
      console.log('Session deleted:', data);
    }
  } catch (err) {
    console.warn('Failed to delete session from backend:', err);
  }

  let current = getCurrentSessionId();
  if (current === sessionId) {
    if (next.length > 0) {
      current = next[0].id;
      setCurrentSessionId(current);
    } else {
      current = createNewSession();
    }
  }
  renderHistory();
  renderSessionMessages(current);
}
// Διάλογος για σφάλματα (μόνο κουμπί Κλείσιμο, χωρίς OK)
function showError(opts) {
  const o = Object.assign({ title: 'Λεπτομέρειες σφάλματος', desc: '' }, opts || {});
  const wrap = document.createElement('div');
  wrap.innerHTML = `
    <div class="ui-backdrop"></div>
    <div class="ui-dialog" role="dialog" aria-modal="true" aria-labelledby="uiTitle">
      <div class="ui-panel">
        <div class="ui-title" id="uiTitle">${escapeHtml(o.title)}</div>
        ${o.desc ? `<div class="ui-desc">${escapeHtml(o.desc)}</div>` : ''}
        <div class="ui-actions">
          <button class="ui-btn primary" data-x="0">Κλείσιμο</button>
        </div>
      </div>
    </div>`;
  const onClose = () => { try { document.body.removeChild(wrap); } catch { } };
  wrap.addEventListener('click', (e) => {
    const btn = e.target && e.target.closest && e.target.closest('[data-x]');
    if (btn) { onClose(); }
    if (e.target && e.target.classList && e.target.classList.contains('ui-backdrop')) { onClose(); }
  });
  document.addEventListener('keydown', function esc(e) { if (e.key === 'Escape') { e.preventDefault(); onClose(); document.removeEventListener('keydown', esc); } });
  document.body.appendChild(wrap);
  const closeBtn = wrap.querySelector('[data-x="0"]'); if (closeBtn) { try { closeBtn.focus(); } catch { } }
}
// Διάλογος επιβεβαίωσης (modal)
function showConfirm(opts) {
  return new Promise(resolve => {
    const o = Object.assign({ title: 'Επιβεβαίωση', desc: '', okText: 'OK', cancelText: 'Άκυρο', okVariant: 'primary' }, opts || {});
    const wrap = document.createElement('div');
    wrap.innerHTML = `
      <div class="ui-backdrop"></div>
      <div class="ui-dialog" role="dialog" aria-modal="true" aria-labelledby="uiTitle">
        <div class="ui-panel">
          <div class="ui-title" id="uiTitle">${escapeHtml(o.title)}</div>
          ${o.desc ? `<div class="ui-desc">${escapeHtml(o.desc)}</div>` : ''}
          <div class="ui-actions">
            <button class="ui-btn ghost" data-x="0">${escapeHtml(o.cancelText)}</button>
            <button class="ui-btn ${o.okVariant === 'danger' ? 'danger' : 'primary'}" data-x="1">${escapeHtml(o.okText)}</button>
          </div>
        </div>
      </div>`;
    const onDone = (val) => { try { document.body.removeChild(wrap); } catch { } resolve(!!val); };
    wrap.addEventListener('click', (e) => {
      const btn = e.target && e.target.closest && e.target.closest('[data-x]');
      if (btn) { onDone(btn.getAttribute('data-x') === '1'); }
      if (e.target && e.target.classList && e.target.classList.contains('ui-backdrop')) { onDone(false); }
    });
    document.addEventListener('keydown', function esc(e) { if (e.key === 'Escape') { e.preventDefault(); onDone(false); document.removeEventListener('keydown', esc); } });
    document.body.appendChild(wrap);
    const ok = wrap.querySelector('[data-x="1"]'); if (ok) { try { ok.focus(); } catch { } }
  });
}

//  Index Panel - Έγγραφα 
const indexPanelBtn = document.getElementById('indexPanelBtn');
const indexPanel = document.getElementById('indexPanel');
const closeIndexPanel = document.getElementById('closeIndexPanel');
const indexContent = document.getElementById('indexContent');

// Toggle για το Index Panel
if (indexPanelBtn) {
  indexPanelBtn.addEventListener('click', () => {
    const isOpen = document.body.classList.toggle('with-index-panel');
    indexPanelBtn.setAttribute('aria-pressed', isOpen ? 'true' : 'false');
    if (isOpen) {
      // Κλείσιμο του sidebar αν είναι ανοιχτό
      if (document.body.classList.contains('with-sidebar')) {
        document.body.classList.remove('with-sidebar');
        if (sidebarBtn) { sidebarBtn.setAttribute('aria-pressed', 'false'); }
      }
      // Φόρτωση δεδομένων
      loadIndexPanelData();
    }
  });
}

// Κλείσιμο του Index Panel
if (closeIndexPanel) {
  closeIndexPanel.addEventListener('click', () => {
    document.body.classList.remove('with-index-panel');
    if (indexPanelBtn) { indexPanelBtn.setAttribute('aria-pressed', 'false'); }
  });
}

// Φόρτωση δεδομένων για το Index Panel
async function loadIndexPanelData() {
  const sessionId = getCurrentSessionId();
  if (!sessionId) {
    indexContent.innerHTML = '<div class="index-empty"><p>Δεν υπάρχει ενεργή συνεδρία</p></div>';
    return;
  }

  try {
    const resp = await fetch(`/sessions/${sessionId}/stats`);
    const data = await resp.json();

    if (!data || !data.ok) {
      indexContent.innerHTML = '<div class="index-empty"><p>Αδυναμία φόρτωσης δεδομένων</p></div>';
      return;
    }

    const docs = data.documents || [];

    if (docs.length === 0) {
      indexContent.innerHTML = '<div class="index-empty"><p>Δεν έχουν ανέβει έγγραφα ακόμα</p></div>';
      return;
    }

    // Render document cards
    let html = '';
    for (const doc of docs) {
      const tokensFormatted = (doc.tokens || 0).toLocaleString('el-GR');

      html += `
        <div class="doc-card" data-filename="${escapeHtml(doc.name)}">
          <div class="doc-card-header">
            <div class="doc-card-info">
              <p class="doc-card-name" title="${escapeHtml(doc.name)}">${escapeHtml(doc.name)}</p>
              <div class="doc-card-meta">
                <span>${doc.chunks || 0} chunks</span>
                <span>${doc.pages || 0} σελίδες</span>
                <span>${tokensFormatted} tokens</span>
              </div>
            </div>
          </div>
          <div class="doc-card-actions">
            <button class="doc-card-btn danger" data-action="delete" data-filename="${escapeHtml(doc.name)}">
              Διαγραφή
            </button>
          </div>
        </div>
      `;
    }

    // Summary footer
    const totalTokens = (data.total_tokens || 0).toLocaleString('el-GR');
    const totalChunks = data.total_chunks || 0;
    const remainingBudget = (data.remaining_budget || 0).toLocaleString('el-GR');
    const usagePercent = data.usage_percentage ? data.usage_percentage.toFixed(1) : '0.0';

    html += `
      <div class="doc-card" style="background:rgba(86,182,255,.1); border-color:var(--accent);">
        <div class="doc-card-info">
          <p class="doc-card-name">Σύνολο Συνεδρίας</p>
          <div class="doc-card-meta">
            <span>${docs.length} έγγραφα</span>
            <span>${totalChunks} chunks</span>
            <span>${totalTokens} tokens</span>
          </div>
          <div class="doc-card-meta" style="margin-top:8px; padding-top:8px; border-top:1px solid var(--border-2);">
            <span>Διαθέσιμα: ${remainingBudget} tokens</span>
            <span>Χρήση: ${usagePercent}%</span>
          </div>
        </div>
      </div>
    `;

    indexContent.innerHTML = html;

    // Event listeners για delete buttons
    const deleteButtons = indexContent.querySelectorAll('[data-action="delete"]');
    deleteButtons.forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const filename = btn.getAttribute('data-filename');
        if (!filename) return;

        const confirmed = await showConfirm({
          title: `Διαγραφή "${filename}"`,
          desc: 'Το έγγραφο και τα chunks του θα διαγραφούν από τη συνεδρία. Αυτή η ενέργεια δεν μπορεί να αναιρεθεί.',
          okText: 'Διαγραφή',
          cancelText: 'Άκυρο'
        });

        if (!confirmed) return;

        // Disable button
        btn.disabled = true;
        btn.textContent = 'Διαγραφή...';

        try {
          const formData = new FormData();
          formData.append('filename', filename);
          formData.append('session_id', sessionId);

          const resp = await fetch('/index/remove', {
            method: 'POST',
            body: formData
          });

          const result = await resp.json();

          if (result && result.ok) {
            loadIndexPanelData();
          } else {
            console.error('Σφάλμα διαγραφής:', result.error || 'Αποτυχία διαγραφής εγγράφου');
            btn.disabled = false;
            btn.textContent = 'Διαγραφή';
          }
        } catch (err) {
          console.error('Σφάλμα δικτύου κατά τη διαγραφή:', err);
          btn.disabled = false;
          btn.textContent = 'Διαγραφή';
        }
      });
    });

  } catch (err) {
    console.error('Error loading index panel data:', err);
    indexContent.innerHTML = '<div class="index-empty"><p>Σφάλμα φόρτωσης δεδομένων</p></div>';
  }
}

// Refresh του index panel μετά από upload
function refreshIndexPanelIfOpen() {
  if (document.body.classList.contains('with-index-panel')) {
    loadIndexPanelData();
  }
}