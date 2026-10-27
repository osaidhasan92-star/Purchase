const screen=workspacePage();
const scripts=['backend-client.js','app.js','frontend-dist/workspace-app.js','hr.js'];
if(NATIVE_TRADE_ROUTES[screen])scripts.push('trade-workspace.js');
else if(screen==='erp.html')scripts.push('crm.js','erp.js');
else if(['sales.html','customers.html','sales-quotations.html','sales-orders.html','sales-deliveries.html','sales-invoices.html','sales-payments.html'].includes(screen))scripts.push('crm.js','sales.js','sales_patch.js');
else if(['crm-dashboard.html','leads.html','reminders.html','companies.html','crm-quotes.html'].includes(screen))scripts.push('crm.js');
else if(screen==='admin-data.html')scripts.push('admin-data.js');
(async()=>{
 try {
   for(const src of scripts)await new Promise((resolve,reject)=>{
     const script=document.createElement('script');script.src=src;script.onload=resolve;
     script.onerror=()=>reject(new Error('Could not load '+src));document.body.appendChild(script);
   });
   window.dispatchEvent(new Event('workspace:ready'));
 }catch(error){document.body.textContent='Unable to load the workspace. Refresh to try again.';console.error(error);}
})();
