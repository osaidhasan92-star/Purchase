/* Route the native Sales/Purchasing screens through the shared React workspace. */
window.addEventListener('workspace:ready',async()=>{
 const entry=NATIVE_TRADE_ROUTES[workspacePage()];if(!entry)return;
 await initAppState();if(!APP_STATE||!guard(entry.permission))return;
 renderModernWorkspace(entry.active,entry.title,entry.subtitle,'',entry.resource?'trade':'trade-dashboard',{tradeResource:entry.resource,tradeArea:entry.area});
});
