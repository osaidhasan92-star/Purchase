/* The AI assistant uses the same authenticated transport as the workspace. */
window.addEventListener('workspace:ready', async () => {
  let config;
  try {
    await BackendPersistence.request('/auth/me');
    config = await BackendPersistence.request('/assistant/status');
  } catch {
    return;
  }

  if (!window.document?.body) return;

  const launcher = document.createElement('button');
  launcher.type = 'button';
  launcher.className = 'erp-ai-launcher';
  launcher.textContent = 'AI Assistant';
  const dialog = document.createElement('dialog');
  dialog.className = 'erp-ai-dialog';
  dialog.setAttribute('aria-labelledby', 'erp-ai-title');
  dialog.innerHTML = `
    <header class="erp-ai-heading">
      <div>
        <h2 id="erp-ai-title">ERP Assistant</h2>
        <p data-mode></p>
      </div>
      <button type="button" data-close>Close</button>
    </header>
    <div class="erp-ai-messages" role="log" aria-label="Conversation" aria-live="polite" tabindex="0"></div>
    <footer class="erp-ai-footer">
      <div class="erp-ai-suggestions" aria-label="Suggested messages"></div>
      <form data-chat class="erp-ai-composer">
        <input name="question" maxlength="800" required autocomplete="off"
          aria-label="Message ERP Assistant" placeholder="Type a message…">
        <button type="submit">Send</button>
      </form>
      <details class="erp-ai-browse">
        <summary>Browse workflows</summary>
        <label>Choose a workflow <select data-process></select></label>
      </details>
    </footer>
    <section data-reviews hidden aria-label="Pending approval decisions">
      <p>Select an eligible request and review it before deciding.</p>
      <a href="/erp.html?view=approvals">Open Pending Approvals</a>
      <label>Pending request <select data-review-list></select></label>
      <div class="erp-ai-review-nav">
        <button type="button" data-review-prev>Previous</button>
        <button type="button" data-review-next>Next</button>
      </div>
      <p data-review-status role="status"></p>
      <form data-decision hidden>
        <pre data-preview></pre>
        <label>Decision
          <select name="decision" required>
            <option value="">Choose a decision</option>
            <option value="approve">Approve and execute</option>
            <option value="reject">Reject</option>
          </select>
        </label>
        <label>Decision reason <textarea name="reason" required maxlength="500" rows="2"></textarea></label>
        <button type="submit">Confirm decision</button>
      </form>
    </section>
  `;

  const form = dialog.querySelector('[data-chat]');
  const input = form.elements.question;
  const submit = form.querySelector('button');
  const messages = dialog.querySelector('.erp-ai-messages');
  const mode = dialog.querySelector('[data-mode]');
  mode.textContent = config.configured ? 'AI enabled · Messages may be sent to OpenAI' : 'Quick commands · No AI model connected';

  function scrollToLatest() {
    messages.scrollTop = messages.scrollHeight;
  }

  function message(role, text) {
    const bubble = document.createElement('div');
    bubble.className = 'erp-ai-message erp-ai-message--' + role;
    const paragraph = document.createElement('p');
    paragraph.textContent = text;
    bubble.appendChild(paragraph);
    messages.appendChild(bubble);
    scrollToLatest();
    return bubble;
  }

  message('assistant', 'Assalam o alaikum! Type what you want to do in ERP. I can find a form or help you review a pending approval.');
  const workflows = setupProcesses(dialog, config, message, scrollToLatest);
  const examples = [
    ['rfq', 'RFQ banani hai'],
    ['sales-order', 'Create sales order'],
    ['expense', 'Expense claim banao'],
    ['review', 'Show pending approvals']
  ];
  const suggestions = dialog.querySelector('.erp-ai-suggestions');
  for (const [id, example] of examples) {
    if (!workflows.has(id)) continue;
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = example;
    button.addEventListener('click', () => {
      input.value = example;
      input.focus();
    });
    suggestions.appendChild(button);
  }

  launcher.addEventListener('click', () => {
    dialog.showModal();
    input.focus();
    scrollToLatest();
  });
  dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question || submit.disabled) return;
    submit.disabled = true;
    input.value = '';
    message('user', question);
    const reply = message('assistant', 'Working on it…');
    try {
      const result = await BackendPersistence.request('/assistant/chat', {
        method: 'POST',
        body: JSON.stringify({question}),
      });
      reply.querySelector('p').textContent = result.answer;
      if (result.process) await workflows.open(result.process.id, reply);
      if (result.snapshot) {
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        const figures = document.createElement('pre');
        summary.textContent = 'ERP figures used · ' + result.source;
        figures.textContent = JSON.stringify(result.snapshot, null, 2);
        details.append(summary, figures);
        reply.appendChild(details);
      }
    } catch (error) {
      reply.querySelector('p').textContent = error.message;
    } finally {
      submit.disabled = false;
      if (dialog.open) input.focus();
      scrollToLatest();
    }
  });
  document.body.append(launcher, dialog);
});

function setupProcesses(dialog, config, message, scrollToLatest) {
  const processes = new Map(config.processes.map(item => [item.id, item]));
  const picker = dialog.querySelector('[data-process]');
  const reviews = dialog.querySelector('[data-reviews]');
  const reviewList = reviews.querySelector('[data-review-list]');
  const reviewStatus = reviews.querySelector('[data-review-status]');
  const previous = reviews.querySelector('[data-review-prev]');
  const next = reviews.querySelector('[data-review-next]');
  const decision = reviews.querySelector('[data-decision]');
  let page = 1;
  let records = new Map();
  let reviewBusy = false;

  picker.add(new Option('Choose a workflow', ''));
  for (const process of processes.values()) {
    picker.add(new Option(process.group + ' · ' + process.label, process.id));
  }

  function showPreview() {
    const row = records.get(reviewList.value);
    decision.reset();
    decision.hidden = !row;
    if (row) {
      decision.querySelector('[data-preview]').textContent = JSON.stringify({
        request: row.label,
        module: row.module,
        operation: row.operation,
        amount: row.currency + ' ' + row.amount,
        requestedBy: row.requester,
        details: row.details,
      }, null, 2);
    }
  }

  function setReviewBusy(busy) {
    reviewBusy = busy;
    picker.disabled = busy;
    reviewList.disabled = busy;
    decision.querySelector('button').disabled = busy;
    if (busy) previous.disabled = next.disabled = true;
  }

  async function loadReviews(message = '') {
    setReviewBusy(true);
    records = new Map();
    reviewList.replaceChildren(new Option('Choose a pending request', ''));
    showPreview();
    reviewStatus.textContent = 'Loading pending requests…';
    try {
      const data = await BackendPersistence.request('/approvals/requests?' +
        new URLSearchParams({status: 'Pending', page: String(page), pageSize: '25'}));
      if (!data.enabled) {
        reviewStatus.textContent = 'Independent approvals are disabled.';
        return;
      }
      for (const row of data.items.filter(item => item.canDecide)) {
        records.set(String(row.id), row);
        reviewList.add(new Option(row.label + ' · ' + row.currency + ' ' + row.amount, row.id));
      }
      previous.disabled = page === 1;
      next.disabled = page * data.pageSize >= data.total;
      reviewStatus.textContent = message || (records.size
        ? 'Page ' + page
        : 'No eligible requests on page ' + page + '. Check other pages or open Pending Approvals.');
    } catch (error) {
      reviewStatus.textContent = error.message;
    } finally {
      setReviewBusy(false);
    }
  }

  async function openProcess(id, bubble) {
    const process = processes.get(id);
    if (!process) return;
    if (process.url) {
      const link = document.createElement('a');
      link.dataset.openProcess = '';
      link.href = process.url;
      link.textContent = process.label;
      bubble.appendChild(link);
      scrollToLatest();
    } else if (!reviewBusy) {
      bubble.appendChild(reviews);
      reviews.hidden = false;
      page = 1;
      await loadReviews();
      scrollToLatest();
    } else {
      const note = document.createElement('p');
      note.textContent = 'The pending approval panel is already processing a request.';
      bubble.appendChild(note);
    }
  }

  picker.addEventListener('change', () => {
    if (!picker.value || reviewBusy) return;
    const id = picker.value;
    picker.value = '';
    const reply = message('assistant', processes.get(id).label);
    void openProcess(id, reply);
  });

  reviewList.addEventListener('change', showPreview);
  previous.addEventListener('click', () => {
    if (!reviewBusy && page > 1) {
      page -= 1;
      void loadReviews();
    }
  });
  next.addEventListener('click', () => {
    if (!reviewBusy) {
      page += 1;
      void loadReviews();
    }
  });
  decision.addEventListener('submit', async event => {
    event.preventDefault();
    const row = records.get(reviewList.value);
    const action = decision.elements.decision.value;
    const reason = decision.elements.reason.value.trim();
    if (reviewBusy || !row || !['approve', 'reject'].includes(action) || !reason) return;
    setReviewBusy(true);
    reviewStatus.textContent = 'Submitting decision to ERP…';
    try {
      await BackendPersistence.request('/approvals/requests/' + encodeURIComponent(row.id) + '/' + action, {
        method: 'POST',
        body: JSON.stringify({version: row.version, reason}),
      });
      await loadReviews(action === 'approve' ? 'Approved and executed in ERP.' : 'Request rejected in ERP.');
    } catch (error) {
      reviewStatus.textContent = error.message;
    } finally {
      setReviewBusy(false);
    }
  });
  return {has: id => processes.has(id), open: openProcess};
}
