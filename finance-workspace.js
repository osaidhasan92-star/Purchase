/* Native finance uses the shared shell and paginated SQL resources. */
window.addEventListener('workspace:ready',async()=>{
 const view=nativeFinanceView();if(!view)return;
 await initAppState();if(!APP_STATE||!guard('accounting'))return;
 const titles={accounting:'Accounting & Finance',accounts:'Chart of Accounts',journals:'Journal Entries',reports:'Financial Reports',aged:'Receivables & Payables',bank:'Bank Reconciliation'};
 renderModernWorkspace('accounting',titles[view],'Pakistan · PKR · One company','', 'finance',{financeView:view});
});
