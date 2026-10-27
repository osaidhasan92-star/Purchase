/* One workspace URL for every business screen. Route names are allowlisted. */
const WORKSPACE_ROUTES = {"activities": "activities.html", "admin-data": "admin-data.html", "companies": "companies.html", "comparison": "comparison.html", "crm-dashboard": "crm-dashboard.html", "crm-quotes": "crm-quotes.html", "customers": "customers.html", "dashboard": "dashboard.html", "hr-attendance": "hr-attendance.html", "hr-dashboard": "hr-dashboard.html", "hr-employees": "hr-employees.html", "hr-leave": "hr-leave.html", "hr-manpower": "hr-manpower.html", "hr-payroll": "hr-payroll.html", "hr-recruitment": "hr-recruitment.html", "hr-reports": "hr-reports.html", "hr-separation": "hr-separation.html", "invoices": "invoices.html", "leads": "leads.html", "orders": "orders.html", "payments": "payments.html", "products": "products.html", "purchase-dashboard": "purchase-dashboard.html", "purchase-reports": "reports.html", "quotations": "quotations.html", "receipts": "receipts.html", "reminders": "reminders.html", "requests": "requests.html", "rfqs": "rfqs.html", "sales": "sales.html", "sales-deliveries": "sales-deliveries.html", "sales-invoices": "sales-invoices.html", "sales-orders": "sales-orders.html", "sales-payments": "sales-payments.html", "sales-quotations": "sales-quotations.html", "users": "users.html", "vendors": "vendors.html"};
function workspacePage(url = new URL(location.href)) {
 const page=url.pathname.split('/').pop();
 return page==='erp.html' ? (WORKSPACE_ROUTES[url.searchParams.get('view')] || 'erp.html') : page;
}
function workspaceUrl(href) {
 const url=new URL(href,location.href);
 if(url.origin!==location.origin)return url.href;
 const page=url.pathname.split('/').pop();
 const route=Object.keys(WORKSPACE_ROUTES).find(key=>WORKSPACE_ROUTES[key]===page);
 if(route){url.pathname=url.pathname.replace(/[^/]*$/, 'erp.html');url.searchParams.set('view',route);}
 return url.href;
}
function workspaceLinks(root=document) {
 if(!root)return;
 root.querySelectorAll('a[href]').forEach(link=>{
   const target=workspaceUrl(link.href);
   if(link.href!==target)link.href=target;
 });
}
new MutationObserver(()=>workspaceLinks()).observe(document.documentElement,{childList:true,subtree:true});
document.addEventListener('click',event=>{
 const link=event.target.closest('a[href]');
 if(link)link.href=workspaceUrl(link.href);
},true);

if(location.pathname.endsWith('/erp.html')){
 const url=new URL(location.href),view=url.searchParams.get('view')||'overview';
 if(!Object.hasOwn(WORKSPACE_ROUTES,view)&&!['overview', 'accounting', 'accounts', 'journals', 'reports', 'aged', 'bank', 'inventory', 'manufacturing', 'boms', 'expenses', 'stock-moves', 'production-orders', 'expense-claims'].includes(view))url.searchParams.set('view','overview');
 else if(!url.searchParams.has('view'))url.searchParams.set('view','overview');
 if(url.href!==location.href)history.replaceState(null,'',url);
}

// Native transaction routes share compact bootstrap; no legacy register renderer is loaded.
const NATIVE_TRADE_ROUTES={
 'requests.html':{resource:'requests',permission:'requests',active:'requests',title:'Purchase Requests',area:'purchase'},
 'rfqs.html':{resource:'rfqs',permission:'rfqs',active:'rfqs',title:'Requests for Quotation',area:'purchase'},
 'quotations.html':{resource:'quotations',permission:'quotations',active:'quotations',title:'Vendor Quotations',area:'purchase'},
 'comparison.html':{resource:'comparisons',permission:'comparison',active:'comparison',title:'Quotation Comparison',area:'purchase'},
 'orders.html':{resource:'orders',permission:'orders',active:'orders',title:'Purchase Orders',area:'purchase'},
 'receipts.html':{resource:'receipts',permission:'receipts',active:'receipts',title:'Goods Receipts',area:'purchase'},
 'invoices.html':{resource:'invoices',permission:'invoices',active:'invoices',title:'Vendor Bills',area:'purchase'},
 'payments.html':{resource:'payments',permission:'payments',active:'payments',title:'Supplier Payments',area:'purchase'},
 'sales-quotations.html':{resource:'salesQuotations',permission:'sales_quotations',active:'sales-quotations',title:'Sales Quotations',area:'sales'},
 'sales-orders.html':{resource:'salesOrders',permission:'sales_orders',active:'sales-orders',title:'Sales Orders',area:'sales'},
 'sales-deliveries.html':{resource:'deliveries',permission:'sales_deliveries',active:'sales-deliveries',title:'Delivery Challans',area:'sales'},
 'sales-invoices.html':{resource:'customerInvoices',permission:'sales_invoices',active:'sales-invoices',title:'Customer Invoices',area:'sales'},
 'sales-payments.html':{resource:'customerPayments',permission:'sales_payments',active:'sales-payments',title:'Customer Payments',area:'sales'},
 'sales.html':{permission:'sales',active:'sales',title:'Sales Dashboard',area:'sales'},
 'purchase-dashboard.html':{permission:'dashboard',active:'purchase-dashboard',title:'Purchasing Dashboard',area:'purchase'},
 'reports.html':{permission:'reports',active:'reports',title:'Purchase Reports',area:'purchase'}
};

const NATIVE_HR_ROUTES={
'hr-employees.html':{resource:'employees',permission:'hr_employees',active:'hr-employees',title:'Employees'},'hr-manpower.html':{resource:'manpower',permission:'hr_manpower',active:'hr-manpower',title:'Manpower Requests'},'hr-recruitment.html':{resource:'candidates',permission:'hr_recruitment',active:'hr-recruitment',title:'Recruitment'},'hr-attendance.html':{resource:'attendance',permission:'hr_attendance',active:'hr-attendance',title:'Attendance'},'hr-leave.html':{resource:'leaves',permission:'hr_leave',active:'hr-leave',title:'Leave Requests'},'hr-payroll.html':{resource:'payroll',permission:'hr_payroll',active:'hr-payroll',title:'Payroll'},'hr-separation.html':{resource:'separations',permission:'hr_separation',active:'hr-separation',title:'Employee Separation'},
'hr-dashboard.html':{permission:'hr_dashboard',active:'hr-dashboard',title:'HR Dashboard'},'hr-reports.html':{permission:'hr_reports',active:'hr-reports',title:'HR Reports',reports:true}
};
