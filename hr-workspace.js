/* HR records use bounded APIs inside the shared React workspace. */
window.addEventListener('workspace:ready',async()=>{
 const entry=NATIVE_HR_ROUTES[workspacePage()];if(!entry)return;
 await initAppState();if(!APP_STATE||!guard(entry.permission))return;
 renderModernWorkspace(entry.active,entry.title,'Employee lifecycle and payroll in PKR','',entry.resource?'hr':'hr-dashboard',{hrResource:entry.resource,hrReports:!!entry.reports});
});
