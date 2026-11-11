/* Expense commands and scoped native React read models. */
module.exports=async({page,assert})=>{
 let dom=await page('erp:expenses'),request=dom.window.eval('BackendPersistence.request'),n=0;
 const cmd=async(a,d)=>(await request('/expenses/commands/'+a,{method:'POST',body:JSON.stringify({...d,requestKey:'expense-dom-'+(++n)})})).record;
 let e=await cmd('create',{description:'Demo client visit',amount:25,tax:0,date:'2026-10-28'});
 for(const a of ['submit','approve','pay'])e=await cmd(a,{id:e.id,version:e.version,account: a==='pay'?'1010':undefined});
 assert.equal(e.status,'Paid');assert.equal(Number((await request('/finance/summary')).balanceCheck),0);dom.window.close();
 dom=await page('erp:expense-claims');assert.match(dom.window.document.body.textContent,/Demo client visit/);assert.match(dom.window.document.body.textContent,/Paid/);dom.window.close();
};
