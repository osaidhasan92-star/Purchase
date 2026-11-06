/* Native stock records use bounded APIs inside the shared React shell. */
window.addEventListener('workspace:ready',async()=>{
 const view=nativeInventoryView();if(!view)return;
 await initAppState();if(!APP_STATE||!guard('inventory'))return;
 renderModernWorkspace('inventory',view==='inventory'?'Inventory':view==='warehouse'?'Warehouse Operations':'Stock Movements','WH / Stock · PKR','', 'inventory',{inventoryView:view});
});
