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
