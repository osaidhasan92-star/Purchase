/* Native claims share the React ERP shell and scoped relational resources. */
window.addEventListener('workspace:ready',async()=>{
 const view=nativeExpenseView();if(!view)return;
 await initAppState();if(!APP_STATE||!guard('expenses'))return;
 renderModernWorkspace('expenses',view==='expenses'?'Expenses':'Expense Claims','PKR','', 'expenses',{expenseView:view});
});
