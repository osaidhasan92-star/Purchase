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
  const actions = document.createElement('fieldset');
  actions.className = 'erp-ai-actions';
  actions.setAttribute('aria-label', 'Available replies');
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
  const workflows = setupAssistantWorkflows(config, (text, choices) => {
    const bubble = message('assistant', text);
    if (choices) {
      actions.replaceChildren(...choices.map(([label, reply = label]) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = label;
        button.addEventListener('click', () => {
          if (button.isConnected) void send(reply, label);
        });
        return button;
      }));
    }
    if (actions.childElementCount) bubble.appendChild(actions);
    else actions.remove();
    scrollToLatest();
    return bubble;
  });
  const picker = dialog.querySelector('[data-process]');
  picker.add(new Option('Choose a workflow', ''));
  for (const process of config.processes.filter(item => workflows.has(item.id))) {
    picker.add(new Option(process.group + ' · ' + process.label, process.id));
  }
  picker.addEventListener('change', () => {
    if (submit.disabled || !picker.value) return;
    workflows.start(picker.value);
    picker.value = '';
    suggestions.hidden = workflows.active();
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
      if (!workflows.active()) void send(example);
    });
    suggestions.appendChild(button);
  }

  launcher.addEventListener('click', () => {
    dialog.showModal();
    input.focus();
    scrollToLatest();
  });
  dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
  form.addEventListener('submit', event => {
    event.preventDefault();
    void send(input.value.trim());
  });

  async function send(question, label = question) {
    if (!question || submit.disabled) return;
    submit.disabled = picker.disabled = actions.disabled = true;
    input.value = '';
    message('user', label);
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
      submit.disabled = picker.disabled = actions.disabled = false;
      suggestions.hidden = workflows.active();
      if (dialog.open) input.focus();
      scrollToLatest();
    }
  }
  document.body.append(launcher, dialog);
});

function setupAssistantWorkflows(config, ask) {
  const processes = new Map(config.processes.map(item => [item.id, item]));
  const cancel = ['Cancel'];
  const restart = ['Restart'];
  const recovery = [restart, cancel];
  const review = [['Confirm'], ...recovery];
  const pageSize = 10;
  let draft = null;

  function has(id) {
    return processes.has(id) && !!assistantWorkflow(id);
  }

  function start(id) {
    if (!has(id)) return false;
    if (draft) {
      ask('Finish or cancel this draft before starting another workflow.');
      return true;
    }
    const flow = assistantWorkflow(id);
    draft = {
      id, flow, fields: [...flow.fields], values: {}, references: {},
      summary: [], key: 'assistant-' + crypto.randomUUID(),
    };
    ask(processes.get(id).label, []);
    prompt();
    return true;
  }

  function prompt() {
    while (draft.fields[0]?.when && !draft.fields[0].when(draft.values)) draft.fields.shift();
    const field = draft.fields[0];
    if (!field) {
      const bubble = ask(processes.get(draft.id).label + '\n\n' +
        draft.summary.join('\n') + '\n\nReview the details. Choose Confirm to submit.', review);
      bubble.dataset.workflowReview = '';
      return;
    }
    if (field.fromRecord) {
      field.options = field.fromRecord(draft.references);
      if (!field.options.length) {
        draft.blocked = true;
        ask('There are no eligible options for this record.', recovery);
        return;
      }
    }
    if (field.recordActions) {
      const actions = draft.references.id.record.actions || [];
      field.choices = field.recordActions.filter(action => actions.includes(action));
      if (!field.choices.length) {
        draft.blocked = true;
        ask('There are no eligible chat actions for this record. Restart to choose another record.', recovery);
        return;
      }
    }
    if (field.sourceLines) {
      draft.fields.shift();
      const lines = field.rows(draft.references[field.sourceLines]);
      if (!lines?.length) {
        draft.blocked = true;
        ask('There are no document lines available. Restart to choose another source.', recovery);
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
    const choices = [];
    if (field.lookup) {
      suffix = field.guide || (field.approval
        ? 'Enter the approval ID or choose List to see eligible requests.'
        : 'Search by name or number, or choose List.');
      choices.push(['List']);
    }
    if (field.choices) {
      choices.push(...field.choices.map(choice => [choice[0].toUpperCase() + choice.slice(1), choice]));
    }
    if (field.options) choices.push(...rowChoices(field.options));
    if (field.type === 'date') {
      suffix = 'Use YYYY-MM-DD or choose Today.';
      choices.push(['Today']);
    }
    if (field.type === 'month') suffix = 'Use YYYY-MM.';
    if (field.repeat) {
      const minimum = field.minimum || 1;
      suffix = 'Choose a count or enter a whole number from ' + minimum + ' to 20.';
      for (let count = minimum; count <= 5; count++) choices.push([String(count)]);
    }
    ask((field.repeat ? 'How many ' + field.label.toLowerCase() + ' entries?' : field.label + '?') +
      (suffix ? '\n' + suffix : ''), withFieldControls(field, choices));
  }

  function withFieldControls(field, choices) {
    return [...choices, ...(field.optional ? [['Skip']] : []), cancel];
  }

  function rowChoices(rows) {
    return rows.map((row, index) => {
      const number = String(index + 1);
      return [number + '. ' + display(row), number];
    });
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
      ask('There are no more results. Try another search or choose List.');
      return null;
    }
    if (field.approval && !['list', 'next'].includes(command) && !/^\d+$/.test(text)) {
      ask('Enter an approval ID or choose List.');
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
      ask('Independent approvals are disabled.', [cancel]);
      return null;
    }
    const rows = result.items.filter(row => field.approval ? row.canDecide :
      !field.localSearch || display(row).toLowerCase().includes(search.toLowerCase()));
    const more = result.total == null ? result.items.length === pageSize : page * Number(params.get('pageSize')) < result.total;
    field.results = {rows, page, more, search};
    const choices = rowChoices(rows);
    if (more) choices.push(['Next']);
    choices.push(['List']);
    ask(rows.length
      ? 'Choose a result.'
      : field.noMatch
        ? field.noMatch + (has('customer')
          ? '\nIf the customer is new, choose Cancel, then start Add customer. After saving it, start the lead again.'
          : '\nIf the customer is new, ask someone with customer creation access to add it.')
        : 'No eligible matches on this page. Try another search or choose List.',
      withFieldControls(field, choices));
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
      ask((result.message || 'Submitted for independent ERP approval.') + '\nApproval #' + result.approval.id, []);
      return;
    }
    const record = result.record || result.customer || result.approval;
    const detail = record ? display(record) : '';
    ask('Saved in ERP' + (detail ? ' · ' + detail : '') + '.', []);
  }

  async function answer(text) {
    if (!draft) return false;
    const command = text.toLowerCase();
    if (command === 'cancel' || command === 'restart') {
      const {id} = draft;
      draft = null;
      if (command === 'restart') start(id);
      else ask('Draft cancelled.', []);
      return true;
    }
    if (draft.blocked) {
      ask('Choose Restart or Cancel.', recovery);
      return true;
    }
    const field = draft.fields[0];
    if (!field) {
      if (command !== 'confirm') ask('Choose Confirm to submit, Restart to change the details, or Cancel.', review);
      else {
        try {
          await submitDraft();
        } catch (error) {
          const needsCorrection = error.status >= 400 && error.status < 500;
          ask(error.message + (needsCorrection
            ? '\nRestart to correct the details.'
            : '\nChoose Confirm to retry the same submission.'), needsCorrection ? recovery : review);
        }
      }
      return true;
    }
    const clarification = command.replace(/[?!.,]+$/, '').trim();
    if (clarification === 'help' || (field.guide && (
      /^(?:kya|kia|kiya) (?:bata(?:o|un|oon)|likh(?:un|oon|o)|type kar(?:un|oon|o)|enter kar(?:un|oon|o))\b/.test(clarification) ||
      /^(?:what (?:should|do) i (?:enter|type|write)|(?:can|should|do) i (?:enter|type|write))\b/.test(clarification) ||
      /^(?:the )?customer(?:'s)? name\s*\?$/.test(command)
    ))) {
      prompt();
      return true;
    }
    try {
      const skipped = field.optional && command === 'skip';
      let result;
      if (skipped) result = {value: undefined, shown: 'Skipped'};
      else if (field.lookup) result = await lookup(field, text, command);
      else if (field.options) {
        const row = /^\d+$/.test(text) && field.options[Number(text) - 1];
        if (!row) throw new Error('Choose one of the listed options.');
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
