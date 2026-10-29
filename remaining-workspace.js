/* Overview and historical CRM registers use native React resources. */
window.addEventListener('workspace:ready',async()=>{
 const view=nativeRemainingView();if(!view)return;
 await initAppState();if(!APP_STATE)return;
 if(view!=='overview'&&!guard(view))return;
 renderModernWorkspace(view==='overview'?'overview':'crm',view==='overview'?'ERP Overview':view==='companies'?'CRM Companies':'CRM Quote Register','Pakistan · PKR · WH / Stock','', 'remaining',{remainingView:view});
});
