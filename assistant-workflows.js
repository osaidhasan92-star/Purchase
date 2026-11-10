/* Chat questionnaires use the same scoped lookups and commands as the ERP pages. */
function assistantWorkflow(id) {
  const field = (key, label, options = {}) => ({key, label, ...options});
  const optional = (key, label) => field(key, label, {optional: true});
  const date = (key, label) => field(key, label, {type: 'date'});
  const number = (key, label, min = 0) => field(key, label, {type: 'number', min});
  const choice = (key, label, ...choices) => field(key, label, {choices});
  const ref = (key, label, lookup, extra = {}) => field(key, label, {lookup, ...extra});
  const form = (path, ...fields) => ({path, fields});
  const record = (label, lookup, detail = lookup.split('?')[0]) =>
    ref('id', label, lookup, {detail, version: 'version'});
  const operations = (path, target, choices, followUps = {}) => ({
    ...form(path, target, field('action', 'Action', {recordActions: choices, followUps})),
    omit: ['action'],
  });
  const tradeActions = (resource, label, choices, followUps) => ({
    ...operations(values => '/trade/' + resource + '/' + encodeURIComponent(values.id) + '/actions/' + values.action,
      record(label, '/trade/' + resource), choices, followUps),
    omit: ['id', 'action'],
  });
  const source = (key, label, resource, status) =>
    ref(key, label, '/trade/' + resource + '?status=' + encodeURIComponent(status), {
      detail: '/trade/' + resource, version: 'parentVersion',
    });
  const pricedItems = field('items', 'Product line', {
    repeat: [
      ref('productId', 'Product', '/products'),
      number('quantity', 'Quantity', 0.000001),
      number('rate', 'Unit rate (PKR)'),
      field('discountPercent', 'Discount %', {type: 'number', min: 0, max: 100, optional: true}),
      field('taxPercent', 'Tax %', {type: 'number', min: 0, max: 100, optional: true}),
    ],
  });
  const sourcedLines = (key, reference, rows, initial, columns) =>
    field(key, 'Source lines', {sourceLines: reference, rows, initial, columns});
  const orderLines = (reference, ...columns) =>
    sourcedLines('items', reference, source => source.context?.lines,
      (line, index) => ({lineIndex: line.lineIndex ?? index}), () => columns);
  const rfqItems = sourcedLines('items', 'rfqId', source => source.record.items,
    line => ({productId: line.productId, quantity: line.quantity}), () => [
      number('rate', 'Vendor unit rate (PKR)', 0.01),
      field('discountPercent', 'Discount %', {type: 'number', min: 0, max: 100, optional: true}),
      field('taxPercent', 'Tax %', {type: 'number', min: 0, max: 100, optional: true}),
    ]);
  const credit = (kind, resource) => ({
    ...form('/credits/commands/create',
      ref('invoiceId', 'Original posted invoice or bill', '/trade/' + resource + '?status=Posted|Approved|Partially Paid|Paid',
        {detail: '/credits/source/' + kind, recordKey: 'invoice'}),
      date('date', 'Credit note date'), field('reason', 'Reason'),
      sourcedLines('lines', 'invoiceId', source => source.lines, line => ({lineIndex: line.index}),
        line => [field('quantity', 'Credit quantity (up to ' + line.remaining + ', 0 to skip)', {
          type: 'number', min: 0, max: Number(line.remaining),
          returns: line.stock ? line.returns : null,
        })])),
    defaults: {kind}, nonzeroLines: 'lines',
  });
  const notes = optional('notes', 'Notes');
  const party = [
    field('name', 'Name'), optional('contact', 'Contact person'),
    optional('phone', 'Phone'), optional('email', 'Email'), optional('category', 'Category'),
  ];
  const stock = ref('productId', 'Stock product', '/inventory/products?type=stock', {
    detail: '/inventory/products', version: 'version',
  });
  const ledger = (key, label) => ref(key, label, '/finance/accounts');
  const employee = resource => ref('employeeKey', 'Employee', '/hr/employee-options/' + resource);
  const methods = choice('method', 'Payment method', 'Bank Transfer', 'Cash', 'Cheque', 'Card', 'Online');
  const approvalFields = [
    ref('request', 'Pending approval', '/approvals/requests?status=Pending', {approval: true}),
    choice('action', 'Decision', 'Approve', 'Reject'),
    field('reason', 'Decision reason', {max: 500}),
  ];

  const flows = {
    review: form(null, ...approvalFields),
    'purchase-request': form('/trade/requests', date('date', 'Request date'),
      field('department', 'Department'), field('requester', 'Requester name'),
      choice('priority', 'Priority', 'Normal', 'High', 'Urgent'), pricedItems, notes),
    rfq: form('/trade/rfqs',
      source('requestId', 'Approved purchase request', 'requests', 'Approved'),
      field('vendorIds', 'Vendor', {repeat: [ref('id', 'Vendor', '/vendors?status=Active')]}),
      date('dueDate', 'Quotation due date'), notes),
    'rfq-register': {
      ...form(values => '/trade/rfqs/' + encodeURIComponent(values.id) + '/actions/send',
        record('Draft RFQ', '/trade/rfqs?status=Draft')),
      omit: ['id'],
    },
    'supplier-quote': form('/trade/quotations',
      source('rfqId', 'Sent RFQ', 'rfqs', 'Sent|Response Received'),
      field('vendorId', 'Vendor from this RFQ', {
        fromRecord: refs => refs.rfqId.record.vendors || [],
      }), date('quoteDate', 'Quote date'),
      date('validUntil', 'Valid until'), optional('paymentTerms', 'Payment terms'),
      optional('deliveryTime', 'Delivery time'), rfqItems, notes),
    'compare-quotes': tradeActions('quotations', 'Received supplier quotation', ['award']),
    'purchase-orders': tradeActions('orders', 'Purchase order', ['submit', 'send', 'cancel', 'close'],
      {close: [field('reason', 'Closure reason')]}),
    'sales-quotes': tradeActions('salesQuotations', 'Sales quotation', ['submit', 'send', 'accept', 'expire']),
    'sales-orders': tradeActions('salesOrders', 'Sales order', ['reserve', 'unreserve', 'cancel', 'close'],
      {close: [field('reason', 'Closure reason')]}),
    'purchase-order': form('/trade/orders',
      {...source('quotationId', 'Awarded supplier quotation', 'quotations', 'Selected'), optional: true},
      {...ref('vendorId', 'Vendor', '/vendors?status=Active'), when: values => !values.quotationId},
      date('poDate', 'Order date'), date('deliveryDate', 'Expected delivery date'),
      optional('deliveryLocation', 'Delivery location'), optional('paymentTerms', 'Payment terms'),
      {...pricedItems, when: values => !values.quotationId}, notes),
    'goods-receipt': form('/trade/receipts',
      source('poId', 'Purchase order', 'orders', 'Approved|Sent to Vendor|Partially Received'),
      date('receivedDate', 'Receipt date'), optional('receivedBy', 'Received by'),
      orderLines('poId', number('receivedQty', 'Received quantity'), number('acceptedQty', 'Accepted quantity'),
        number('rejectedQty', 'Rejected quantity')), notes),
    'vendor-bill': form('/trade/invoices',
      source('poId', 'Purchase order', 'orders', 'Approved|Sent to Vendor|Partially Received|Received|Closed'),
      field('invoiceNo', 'Vendor invoice number'), date('invoiceDate', 'Invoice date'), date('dueDate', 'Due date'),
      orderLines('poId', number('quantity', 'Bill quantity')), notes),
    'sales-quote': {
      ...form('/trade/salesQuotations',
      ref('leadId', 'Link a CRM lead', '/crm/leads', {
        optional: true, detail: '/trade/reference/leads', version: 'parentVersion',
      }),
      {...ref('customerId', 'Customer', '/customers'), when: values => !values.leadId},
      date('quotationDate', 'Quotation date'), date('validUntil', 'Valid until'),
      optional('paymentTerms', 'Payment terms'), optional('deliveryTerms', 'Delivery terms'),
      pricedItems, notes),
      prepare: (payload, refs) => {
        if (payload.leadId) payload.customerId = refs.leadId.record.customerId;
      },
    },
    'sales-order': form('/trade/salesOrders',
      source('quotationId', 'Accepted sales quotation', 'salesQuotations', 'Accepted'),
      date('orderDate', 'Order date'), notes),
    delivery: form('/trade/deliveries',
      source('orderId', 'Sales order', 'salesOrders', 'Confirmed|Partially Delivered|Delivered'),
      date('deliveryDate', 'Delivery date'), optional('deliveredBy', 'Delivered by'),
      optional('referenceNo', 'Challan reference'), orderLines('orderId', number('deliveredQty', 'Delivery quantity')), notes),
    'customer-invoice': form('/trade/customerInvoices',
      source('orderId', 'Sales order', 'salesOrders', 'Confirmed|Partially Delivered|Delivered|Closed'),
      date('invoiceDate', 'Invoice date'), date('dueDate', 'Due date'),
      orderLines('orderId', number('quantity', 'Invoice quantity')), notes),
    'supplier-payment': form('/trade/payments',
      source('invoiceId', 'Approved vendor bill', 'invoices', 'Approved|Partially Paid'),
      date('paymentDate', 'Payment date'), number('amount', 'Amount (PKR)', 0.01),
      methods, optional('referenceNo', 'Payment reference'), notes),
    'customer-payment': form('/trade/customerPayments',
      source('invoiceId', 'Posted customer invoice', 'customerInvoices', 'Posted|Partially Paid'),
      date('paymentDate', 'Payment date'), number('amount', 'Amount (PKR)', 0.01),
      methods, optional('referenceNo', 'Payment reference'), notes),
    vendor: form('/vendors', ...party, optional('trn', 'Tax registration / NTN')),
    customer: form('/customers', ...party,
      choice('paymentTerms', 'Payment terms', 'Cash', '15 Days', '30 Days', '45 Days'),
      number('creditLimit', 'Credit limit (PKR)'), optional('address', 'Address')),
    lead: form('/crm/leads', ref('customerId', 'Customer', '/customers'),
      optional('contact', 'Contact person'), optional('email', 'Email'),
      choice('stage', 'Stage', 'New', 'Contacted', 'Qualified', 'Quotation Required'),
      number('value', 'Opportunity value (PKR)'), optional('source', 'Lead source'), notes),
    reminder: form('/crm/reminders', ref('leadId', 'CRM lead', '/crm/leads'),
      choice('type', 'Reminder type', 'Call', 'Email', 'Meeting', 'Follow-up'),
      date('dueDate', 'Due date'), notes),
    product: form('/products', field('name', 'Product name'), optional('sku', 'SKU'),
      optional('category', 'Category'), choice('productType', 'Product type', 'stock', 'service'),
      field('unit', 'Unit'), number('rate', 'Default rate (PKR)')),
    expense: form('/expenses/commands/create', field('description', 'Expense description', {max: 500}),
      date('date', 'Expense date'), ref('account', 'Expense account', '/expenses/accounts', {localSearch: true}),
      number('amount', 'Amount (PKR)', 0.01), number('tax', 'Tax (PKR)')),
    'stock-adjustment': form('/inventory/commands/adjust', stock,
      field('quantity', 'Quantity change (negative for removal)', {type: 'number', min: -1e12, nonzero: true}),
      number('unitCost', 'Unit cost (PKR)'), date('date', 'Adjustment date'), field('reason', 'Reason')),
    'stock-scrap': form('/inventory/commands/scrap', stock, number('quantity', 'Quantity', 0.000001),
      date('date', 'Scrap date'), field('reason', 'Reason')),
    'stock-transfer': form('/warehouse/commands/transfer', {...stock, versionField: 'warehouseVersion'},
      choice('fromLocation', 'Source location', 'Stock', 'Production', 'Returns'),
      choice('toLocation', 'Destination location', 'Stock', 'Production', 'Returns'),
      number('quantity', 'Transfer quantity', 0.000001), date('date', 'Transfer date'), field('reason', 'Reason', {max: 300})),
    warehouse: {
      ...form(values => '/warehouse/commands/' + values.action,
        choice('action', 'Reservation action', 'reserve', 'release'),
        ref('orderId', 'Sales order', '/trade/salesOrders?status=Confirmed|Partially Delivered')),
      omit: ['action'],
    },
    'stock-return': form('/inventory/commands/return',
      ref('moveId', 'Stock movement', '/inventory/movements', {detail: '/inventory/movements', version: 'version'}),
      number('quantity', 'Return quantity', 0.000001), date('date', 'Return date'), field('reason', 'Reason')),
    bom: form('/production/commands/bom', field('name', 'BoM name'),
      ref('productId', 'Finished product', '/production/products'),
      number('quantity', 'Output quantity', 0.000001), number('conversionCost', 'Conversion cost (PKR)'),
      field('components', 'Component', {repeat: [
        ref('productId', 'Component product', '/production/products'),
        number('quantity', 'Component quantity', 0.000001),
      ]})),
    'production-order': form('/production/commands/order',
      ref('bomId', 'Bill of materials', '/production/boms', {detail: '/production/boms', version: 'bomVersion'}),
      number('quantity', 'Production quantity', 0.000001), date('date', 'Production date')),
    production: operations(values => '/production/commands/' + values.action,
      record('Manufacturing order', '/production/orders'), ['confirm', 'reserve', 'stage', 'start', 'complete', 'cancel'],
      {complete: [
        number('producedQuantity', 'Finished quantity', 0.0001), number('conversionCost', 'Actual conversion cost (PKR)'),
        sourcedLines('components', 'id', source => source.record.components, line => ({productId: line.productId}),
          () => [number('quantity', 'Consumed quantity'), number('scrap', 'Scrap quantity')]),
      ]}),
    expenses: operations(values => '/expenses/commands/' + values.action,
      record('Expense claim', '/expenses/claims'), ['submit', 'pay'],
      {pay: [ledger('account', 'Reimbursement account'), date('date', 'Payment date')]}),
    'journal-register': form('/finance/commands/post',
      record('Draft journal entry', '/finance/entries?status=Draft')),
    'bank-match': form('/finance/commands/match-bank',
      record('Unmatched bank statement line', '/finance/statements?status=Unmatched', null),
      ref('lineId', 'Matching posted journal item',
        values => '/finance/statements/' + encodeURIComponent(values.id) + '/candidates',
        {version: 'lineVersion'})),
    'match-items': form('/finance/commands/reconcile',
      ref('debitLine', 'Open debit item', '/finance/open-items?side=debit', {version: 'debitVersion'}),
      ref('creditLine', 'Matching open credit item', (_, refs) => '/finance/open-items?' +
        new URLSearchParams({side: 'credit', account: refs.debitLine.record.account,
          partner: refs.debitLine.record.partner || ''}), {version: 'creditVersion'}),
      number('amount', 'Matching amount (PKR)', 0.01)),
    'credit-note': credit('customer', 'customerInvoices'),
    'vendor-credit': credit('vendor', 'invoices'),
    'payroll-register': operations(values => '/hr/records/payroll/' + encodeURIComponent(values.id) + '/actions/' + values.action,
      record('Payroll entry', '/hr/records/payroll'), ['approve', 'pay']),
    account: form('/finance/commands/account', field('code', 'Account code'),
      field('name', 'Account name'), choice('type', 'Account type', 'asset', 'liability', 'equity', 'income', 'expense')),
    journal: form('/finance/commands/journal', date('date', 'Journal date'), field('memo', 'Memo'),
      field('lines', 'Journal line', {minimum: 2, repeat: [
        ledger('account', 'Ledger account'), number('debit', 'Debit (PKR)'), number('credit', 'Credit (PKR)'),
        optional('partner', 'Partner'),
      ]})),
    'bank-statement': form('/finance/commands/statement', date('date', 'Statement date'),
      ledger('account', 'Bank or cash account'), field('description', 'Description'),
      field('amount', 'Amount (PKR, signed)', {type: 'number', min: -1e12, nonzero: true})),
    'cash-transfer': form('/finance/commands/transfer', ledger('fromAccount', 'Source cash or bank account'),
      ledger('toAccount', 'Destination cash or bank account'), number('amount', 'Amount (PKR)', 0.01),
      date('date', 'Transfer date')),
    employee: form('/hr/records/employees', field('employeeId', 'Employee ID'),
      field('name', 'Full name'), field('department', 'Department'), field('designation', 'Designation'),
      optional('manager', 'Reporting manager'), date('joiningDate', 'Joining date'),
      number('salary', 'Monthly basic salary (PKR)'), optional('email', 'Contact email')),
    manpower: form('/hr/records/manpower', field('department', 'Department'), field('position', 'Position'),
      choice('requestType', 'Request type', 'New Position', 'Replacement'),
      number('count', 'Headcount', 1), field('reason', 'Reason'), field('requestedBy', 'Requested by')),
    recruitment: form('/hr/records/candidates', field('name', 'Candidate name'),
      field('position', 'Position'), field('contact', 'Email or phone')),
    attendance: form('/hr/records/attendance', employee('attendance'), date('date', 'Attendance date'),
      choice('attendanceStatus', 'Attendance status', 'Present', 'Absent', 'Late', 'Half Day', 'Work From Home')),
    leave: form('/hr/records/leaves', employee('leaves'),
      choice('leaveType', 'Leave type', 'Annual', 'Sick', 'Casual', 'Unpaid'),
      date('from', 'Leave start date'), date('to', 'Leave end date'), field('reason', 'Reason')),
    separation: form('/hr/records/separations', employee('separations'),
      date('lastWorkingDate', 'Last working date'), field('reason', 'Reason'),
      number('finalSettlement', 'Final settlement estimate (PKR)')),
    payroll: form('/hr/records/payroll', employee('payroll'),
      field('month', 'Payroll month', {type: 'month'}), number('basic', 'Basic salary (PKR)'),
      number('allowances', 'Allowances (PKR)'), number('deductions', 'Deductions (PKR)')),
  };
  return Object.hasOwn(flows, id) ? flows[id] : null;
}
