module.exports=async({page,assert})=>{
 let dom=await page('erp:inventory');const request=dom.window.eval('BackendPersistence.request');let n=0;
 const rows=await request('/inventory/products?type=stock');const p=rows.items[0];assert.ok(p);
 const call=async(kind,data)=>(await request('/inventory/commands/'+kind,{method:'POST',body:JSON.stringify({...data,requestKey:'inventory-dom-'+(++n)})})).record;
 const before=Number(p.quantity);let m=await call('adjust',{productId:p.id,version:p.version,quantity:3,unitCost:10,reason:'DOM count'});assert.ok(m.journalId);
 let current=(await request('/inventory/products/'+p.id)).record;await call('scrap',{productId:p.id,version:current.version,quantity:1,reason:'DOM scrap'});current=(await request('/inventory/products/'+p.id)).record;assert.equal(Number(current.quantity),before+2);dom.window.close();
 dom=await page('erp:stock-moves');assert.ok(dom.window.document.body.textContent.includes('Stock Adjustment'));assert.ok(dom.window.document.body.textContent.includes('Scrap'));dom.window.close();
};
