/* Native customer/CRM entry points; business records stay in relational APIs. */
window.addEventListener('workspace:ready', async () => {
  const routes = {
    'customers.html': ['sales_customers', 'customers', 'Customers', 'Customer master data shared by CRM and Sales', 'customers'],
    'crm-dashboard.html': ['leads', 'crm-dashboard', 'CRM Dashboard', 'Customer pipeline and follow-ups', 'crm-dashboard'],
    'leads.html': ['leads', 'leads', 'CRM Leads', 'Track opportunities through your sales pipeline', 'leads'],
    'reminders.html': ['reminders', 'reminders', 'CRM Reminders', 'Plan and complete customer follow-ups', 'reminders'],
  };
  const entry = routes[workspacePage()];
  if (!entry) return;
  await initAppState();
  if (!APP_STATE || !guard(entry[0])) return;
  renderModernWorkspace(entry[1], entry[2], entry[3], '', entry[4]);
});

// Retain the commands used by the compatibility boundary and integration tests.
window.openCustomer = () => window.ModernWorkspace.openCustomer();
window.saveCustomer = () => window.ModernWorkspace.saveCustomer();
window.openCrmLead = id => window.ModernWorkspace.openMaster(id ?? undefined);
window.saveCrmLead = () => window.ModernWorkspace.saveMaster();
window.openCrmReminder = () => window.ModernWorkspace.openMaster();
window.saveCrmReminder = () => window.ModernWorkspace.saveMaster();
