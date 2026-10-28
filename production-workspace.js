/* Native production screens use compact resources in the shared React workspace. */
window.addEventListener('workspace:ready',async()=>{
 const view=nativeProductionView();if(!view)return;
 await initAppState();if(!APP_STATE||!guard('manufacturing'))return;
 const titles={manufacturing:'Manufacturing',boms:'Bills of Materials','production-orders':'Manufacturing Orders'};
 renderModernWorkspace('manufacturing',titles[view],'WH / Stock · PKR','', 'production',{productionView:view});
});
