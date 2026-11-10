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
  `;

  const form = dialog.querySelector('[data-chat]');
  const input = form.elements.question;
  const submit = form.querySelector('button');
  const messages = dialog.querySelector('.erp-ai-messages');
  const mode = dialog.querySelector('[data-mode]');
  mode.textContent = config.configured
    ? 'Chat workflows · General questions may be sent to OpenAI'
    : 'Chat workflows · Quick commands available';

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

  message('assistant', 'Assalam o alaikum! Type what you want to do in ERP. I’ll ask for one detail at a time and show a summary before you confirm.');
  const workflows = setupAssistantWorkflows(config, message, scrollToLatest);
  const picker = dialog.querySelector('[data-process]');
  picker.add(new Option('Choose a workflow', ''));
  for (const process of config.processes.filter(item => workflows.has(item.id))) {
    picker.add(new Option(process.group + ' · ' + process.label, process.id));
  }
  picker.addEventListener('change', () => {
    if (submit.disabled || !picker.value) return;
    workflows.start(picker.value);
    picker.value = '';
    input.focus();
  });
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
      if (workflows.active()) return;
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
    submit.disabled = picker.disabled = true;
    input.value = '';
    message('user', question);
    let reply;
    try {
      if (await workflows.answer(question)) return;
      reply = message('assistant', 'Working on it…');
      const result = await BackendPersistence.request('/assistant/chat', {
        method: 'POST',
        body: JSON.stringify({question}),
      });
      reply.querySelector('p').textContent = result.answer;
      if (result.process && !workflows.start(result.process.id)) {
        reply.querySelector('p').textContent = 'This workflow is not available in chat yet.';
      }
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
      if (reply) reply.querySelector('p').textContent = error.message;
      else message('assistant', error.message);
    } finally {
      submit.disabled = picker.disabled = false;
      if (dialog.open) input.focus();
      scrollToLatest();
    }
  });
  document.body.append(launcher, dialog);
});

function setupAssistantWorkflows(config, message, scrollToLatest) {
  const processes = new Map(config.processes.map(item => [item.id, item]));
  const ask = text => message('assistant', text);
  const pageSize = 10;
  let draft = null;

  function has(id) {
    return processes.has(id) && !!assistantWorkflow(id);
  }

  function start(id) {
    if (!has(id)) return false;
    if (draft) {
      ask('Finish this draft or type Cancel before starting another workflow.');
      return true;
    }
    const flow = assistantWorkflow(id);
    draft = {
      id, flow, fields: [...flow.fields], values: {}, references: {},
      summary: [], key: 'assistant-' + crypto.randomUUID(),
    };
    ask(processes.get(id).label + '\nType Cancel at any time to discard the draft.');
    prompt();
    return true;
  }

  function prompt() {
    while (draft.fields[0]?.when && !draft.fields[0].when(draft.values)) draft.fields.shift();
    const field = draft.fields[0];
    if (!field) {
      const bubble = ask(processes.get(draft.id).label + '\n\n' +
        draft.summary.join('\n') + '\n\nType Confirm to submit, Restart to change the details, or Cancel.');
      bubble.dataset.workflowReview = '';
      scrollToLatest();
      return;
    }
    if (field.fromRecord) {
      field.options = field.fromRecord(draft.references);
      if (!field.options.length) {
        draft.blocked = true;
        ask('There are no eligible options for this record. Type Restart or Cancel.');
        return;
      }
    }
    if (field.recordActions) {
      const actions = draft.references.id.record.actions || [];
      field.choices = field.recordActions.filter(action => actions.includes(action));
      if (!field.choices.length) {
        draft.blocked = true;
        ask('There are no eligible chat actions for this record. Type Restart to choose another record or Cancel.');
        return;
      }
    }
    if (field.sourceLines) {
      draft.fields.shift();
      const lines = field.rows(draft.references[field.sourceLines]);
      if (!lines?.length) {
        draft.blocked = true;
        ask('There are no document lines available. Type Restart to choose another source or Cancel.');
        return;
      }
      const entries = draft.values[field.key] = lines.map(field.initial);
      draft.fields.unshift(...lines.flatMap((line, index) => {
        const label = line.product || line.productName || line.description || 'Item';
        const quantity = line.quantity == null ? '' : ' (' + line.quantity + ')';
        return field.columns(line).map(column => ({
          ...column, target: entries[index],
          label: 'Line ' + (index + 1) + ' · ' + label + quantity + ' · ' + column.label,
        }));
      }));
      prompt();
      return;
    }
    let suffix = '';
    if (field.lookup) {
      suffix = field.approval
        ? 'Type the approval ID or type List to see eligible requests.'
        : 'Type a name or number to search, or type List.';
    }
    if (field.choices) suffix = field.choices.join(' / ');
    if (field.options) suffix = field.options.map((row, index) => (index + 1) + '. ' + display(row)).join('\n');
    if (field.type === 'date') suffix = 'Use YYYY-MM-DD or type Today.';
    if (field.type === 'month') suffix = 'Use YYYY-MM.';
    if (field.optional) suffix += (suffix ? ' ' : '') + 'Type Skip to leave it blank.';
    if (field.repeat) suffix = 'Enter a whole number from ' + (field.minimum || 1) + ' to 20.';
    ask((field.repeat ? 'How many ' + field.label.toLowerCase() + ' entries?' : field.label + '?') +
      (suffix ? '\n' + suffix : ''));
  }

  function display(row) {
    const number = row.number || row.requestNo || row.rfqNo || row.quotationNo || row.poNo ||
      row.orderNo || row.invoiceNo || row.sku || row.code;
    const label = row.label || row.name || row.product || row.customerName || row.vendorName ||
      row.description || row.employee || row.memo;
    const amount = row.openAmount ?? row.total ?? row.amount;
    return [number || (!label || row.canDecide ? row.id : ''), label,
      amount == null ? '' : (row.currency || 'PKR') + ' ' + amount,
      row.remaining == null ? '' : 'Available ' + row.remaining, row.status || row.state]
      .filter(Boolean).join(' · ');
  }

  async function lookup(field, text, command) {
    const previous = field.results;
    if (previous && /^\d+$/.test(text) && Number(text) <= previous.rows.length && Number(text) > 0) {
      const row = previous.rows[Number(text) - 1];
      const details = field.detail
        ? await BackendPersistence.request(field.detail + '/' + encodeURIComponent(row.id))
        : {record: row};
      const record = details[field.recordKey || 'record'];
      const version = record[field.versionField || 'version'];
      if (field.version && !version) throw new Error('The source record is missing its version.');
      if (field.approval) {
        ask('Approval #' + row.id + ' · ' + row.label + '\n' +
          JSON.stringify({amount: row.currency + ' ' + row.amount, operation: row.operation,
            requestedBy: row.requester, details: row.details}, null, 2));
      }
      draft.references[field.key] = details;
      if (field.version) draft.values[field.version] = version;
      const linkedCustomer = field.key === 'leadId' && record.customerName ? ' · ' + record.customerName : '';
      return {value: field.approval ? row : record.id, shown: display({...row, ...record}) + linkedCustomer};
    }
    if (command === 'next' && !previous?.more) {
      ask('There are no more results. Type another search or List.');
      return null;
    }
    if (field.approval && !['list', 'next'].includes(command) && !/^\d+$/.test(text)) {
      ask('Type an approval ID or List.');
      return null;
    }
    const search = command === 'next' ? previous.search : command === 'list' ? '' : text;
    if (search.length > 160) throw new Error('Search terms can be up to 160 characters.');
    const page = command === 'next' ? previous.page + 1 : 1;
    const params = new URLSearchParams({
      page: String(page), pageSize: String(field.localSearch ? 100 : pageSize),
    });
    if (search && field.approval) params.set('id', search);
    else if (search && !field.localSearch) params.set('search', search);
    const path = typeof field.lookup === 'function' ? field.lookup(draft.values, draft.references) : field.lookup;
    const result = await BackendPersistence.request(path + (path.includes('?') ? '&' : '?') + params);
    if (field.approval && !result.enabled) {
      ask('Independent approvals are disabled. Type Cancel to return to chat.');
      return null;
    }
    const rows = result.items.filter(row => field.approval ? row.canDecide :
      !field.localSearch || display(row).toLowerCase().includes(search.toLowerCase()));
    const more = result.total == null ? result.items.length === pageSize : page * Number(params.get('pageSize')) < result.total;
    field.results = {rows, page, more, search};
    ask((rows.length
      ? rows.map((row, index) => (index + 1) + '. ' + display(row)).join('\n') + '\nType the option number to select.'
      : 'No eligible matches on this page. Try another search or List.') +
      (more ? '\nType Next for more results.' : ''));
    return null;
  }

  function parse(field, text, command) {
    if (field.choices) {
      const value = field.choices.find(option => option.toLowerCase() === command);
      if (!value) throw new Error('Choose ' + field.choices.join(' / ') + '.');
      return value;
    }
    if (field.type === 'number' || field.repeat) {
      const value = /^-?\d+(?:\.\d+)?$/.test(text) ? Number(text) : NaN;
      if (field.repeat) {
        if (!Number.isInteger(value) || value < (field.minimum || 1) || value > 20)
          throw new Error('Enter a whole number from ' + (field.minimum || 1) + ' to 20.');
      } else if (!Number.isFinite(value) || value < field.min || value > (field.max ?? 1e12) ||
        (field.nonzero && value === 0)) {
        throw new Error('Enter a valid number for ' + field.label + '.');
      }
      return value;
    }
    if (field.type === 'date') {
      if (command === 'today') return new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Karachi'}).format(new Date());
      if (!/^\d{4}-\d{2}-\d{2}$/.test(text) || Number.isNaN(Date.parse(text)) ||
        new Date(text).toISOString().slice(0, 10) !== text)
        throw new Error('Enter a valid date in YYYY-MM-DD format.');
    }
    if (field.type === 'month' && !/^\d{4}-(0[1-9]|1[0-2])$/.test(text))
      throw new Error('Enter a valid month in YYYY-MM format.');
    if (text.length > (field.max || 160)) throw new Error('This answer is too long for ' + field.label + '.');
    return text;
  }

  async function submitDraft() {
    const {id, flow, key, values, references} = draft;
    const payload = {...flow.defaults, ...values, requestKey: key};
    for (const key of flow.omit || []) delete payload[key];
    flow.prepare?.(payload, references);
    if (flow.nonzeroLines) payload[flow.nonzeroLines] = values[flow.nonzeroLines].filter(line => line.quantity > 0);
    let path = typeof flow.path === 'function' ? flow.path(values) : flow.path;
    if (id === 'review') {
      const {request, action, reason} = values;
      path = '/approvals/requests/' + encodeURIComponent(request.id) + '/' + action.toLowerCase();
      delete payload.request;
      delete payload.action;
      delete payload.requestKey;
      payload.version = request.version;
      payload.reason = reason;
    } else {
      if (id === 'rfq') payload.vendorIds = values.vendorIds.map(row => row.id);
      if (['goods-receipt', 'delivery', 'vendor-bill', 'customer-invoice'].includes(id)) {
        payload.items = values.items.filter(line => line.receivedQty || line.acceptedQty ||
          line.rejectedQty || line.deliveredQty || line.quantity);
      }
    }
    const result = await BackendPersistence.request(path, {
      method: 'POST', body: JSON.stringify(payload), keepApprovalInChat: true,
    });
    draft = null;
    if (result.approvalPending) {
      ask((result.message || 'Submitted for independent ERP approval.') + '\nApproval #' + result.approval.id);
      return;
    }
    const record = result.record || result.customer || result.approval;
    const detail = record ? display(record) : '';
    ask('Saved in ERP' + (detail ? ' · ' + detail : '') + '.');
  }

  async function answer(text) {
    if (!draft) return false;
    const command = text.toLowerCase();
    if (command === 'cancel' || command === 'restart') {
      const {id} = draft;
      draft = null;
      if (command === 'restart') start(id);
      else ask('Draft cancelled.');
      return true;
    }
    if (draft.blocked) {
      ask('Type Restart or Cancel.');
      return true;
    }
    const field = draft.fields[0];
    if (!field) {
      if (command !== 'confirm') ask('Type Confirm to submit, Restart to change the details, or Cancel.');
      else {
        try {
          await submitDraft();
        } catch (error) {
          ask(error.message + (error.status >= 400 && error.status < 500
            ? '\nType Restart to correct the details or Cancel.'
            : '\nType Confirm to retry the same submission, or Cancel.'));
        }
      }
      return true;
    }
    try {
      const skipped = field.optional && command === 'skip';
      let result;
      if (skipped) result = {value: undefined, shown: 'Skipped'};
      else if (field.lookup) result = await lookup(field, text, command);
      else if (field.options) {
        const row = /^\d+$/.test(text) && field.options[Number(text) - 1];
        if (!row) throw new Error('Type one of the option numbers.');
        result = {value: row.id, shown: display(row)};
      } else result = {value: parse(field, text, command)};
      if (field.returns && result.value > 0 && !field.returns.length)
        throw new Error('There is no validated stock return for this line. Enter 0 to skip it.');
      if (!result) return true;
      draft.fields.shift();
      if (field.repeat) {
        const entries = draft.values[field.key] = Array.from({length: result.value}, () => ({}));
        draft.fields.unshift(...entries.flatMap((entry, index) => field.repeat.map(item => ({
          ...item, target: entry, label: field.label + ' ' + (index + 1) + ' · ' + item.label,
        }))));
      } else if (!skipped) {
        (field.target || draft.values)[field.key] = result.value;
      }
      if (field.followUps?.[result.value]) draft.fields.unshift(...field.followUps[result.value]);
      if (field.returns && result.value > 0) draft.fields.unshift({
        key: 'returnId', label: 'Validated stock return for ' + field.label,
        target: field.target, options: field.returns,
      });
      draft.summary.push(field.label + ': ' + (result.shown ?? result.value));
      prompt();
    } catch (error) {
      ask(error.message);
    }
    return true;
  }

  return {has, start, answer, active: () => !!draft};
}
