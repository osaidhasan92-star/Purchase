const screen=workspacePage();
const scripts=['backend-client.js','app.js','frontend-dist/workspace-app.js'];
if(nativeRemainingView())scripts.push('remaining-workspace.js');
else if(nativeAdminView())scripts.push('admin-workspace.js');
else if(nativeExpenseView())scripts.push('expense-workspace.js');
else if(nativeProductionView())scripts.push('production-workspace.js');
else if(nativeInventoryView())scripts.push('inventory-workspace.js');
else if(nativeFinanceView())scripts.push('finance-workspace.js');
else if(NATIVE_HR_ROUTES[screen])scripts.push('hr-workspace.js');
else if(NATIVE_TRADE_ROUTES[screen])scripts.push('trade-workspace.js');
else if(['customers.html','crm-dashboard.html','leads.html','reminders.html'].includes(screen))scripts.push('crm-workspace.js');
(async()=>{
 try {
   for(const src of scripts)await new Promise((resolve,reject)=>{
     const script=document.createElement('script');script.src=src;script.onload=resolve;
     script.onerror=()=>reject(new Error('Could not load '+src));document.body.appendChild(script);
   });
   window.dispatchEvent(new Event('workspace:ready'));
 }catch(error){document.body.textContent='Unable to load the workspace. Refresh to try again.';console.error(error);}
})();
