/* Native production API simulation plus shared React read models. */
module.exports=async({page,assert,rawId})=>{
 let dom=await page('erp:manufacturing');const request=dom.window.eval('BackendPersistence.request');let n=0;
 const call=async(kind,data)=>(await request('/production/commands/'+kind,{method:'POST',body:JSON.stringify({...data,requestKey:'production-dom-'+(++n)})})).record;
 const finished=(await request('/products',{method:'POST',body:JSON.stringify({name:'Workflow finished kit',sku:'FG-UI-1',rate:0,requestKey:'production-finished-dom'})})).record;
 let b=await call('bom',{name:'Workflow kit BoM',productId:finished.id,quantity:1,conversionCost:2,components:[{productId:rawId,quantity:2}]});
 let o=await call('order',{bomId:b.id,bomVersion:b.version,quantity:1,date:'2026-10-28'});for(const action of ['confirm','start','complete'])o=await call(action,{id:o.id,version:o.version});assert.equal(o.state,'Done');assert.equal(Number(o.actualCost),22);
 const report=await request('/finance/summary');assert.equal(Number(report.balanceCheck),0);dom.window.close();
 for(const [view,text] of [['manufacturing','Completed orders'],['boms','Workflow kit BoM'],['production-orders','Done']]){dom=await page('erp:'+view);assert.ok(dom.window.document.body.textContent.includes(text),view+' missing '+text);dom.window.close();}
};
