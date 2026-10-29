/* Finance API business simulation plus native React read models. */
module.exports=async({page,assert})=>{
 let dom=await page('erp:accounting');const request=dom.window.eval('BackendPersistence.request');let n=0;
 const call=async(kind,data)=>(await request('/finance/commands/'+kind,{method:'POST',body:JSON.stringify({...data,requestKey:'finance-dom-'+(++n)})})).record;
 const journal=async(memo,debit,credit,amount,partner='')=>{let j=await call('journal',{memo,date:'2026-10-28',lines:[{account:debit,debit:amount,partner},{account:credit,credit:amount,partner}]});return call('post',{id:j.id,version:j.version});};
 const j=await journal('Native Finance DOM','1010','3000',500);
 let s=await call('statement',{date:'2026-10-28',description:'Native statement DOM',account:'1010',amount:500});const bankLine=j.lines.find(l=>l.account==='1010');s=await call('match-bank',{id:s.id,version:s.version,lineId:bankLine.id,lineVersion:bankLine.version});assert.ok(s.matchedLine);
 await call('transfer',{date:'2026-10-28',fromAccount:'1010',toAccount:'1000',amount:20});
 const invoice=await journal('Native AR DOM','1100','4100',100,'customer:dom');const payment=await journal('Native collection DOM','1010','1100',60,'customer:dom');const d=invoice.lines.find(l=>l.account==='1100'),c=payment.lines.find(l=>l.account==='1100');await call('reconcile',{debitLine:d.id,creditLine:c.id,debitVersion:d.version,creditVersion:c.version,amount:60});
 const summary=await request('/finance/summary');assert.equal(Number(summary.balanceCheck),0);
 dom.window.close();for(const [view,text] of [['journals','Native Finance DOM'],['bank','Native statement DOM'],['aged','customer:dom'],['reports','Trial Balance']]){dom=await page('erp:'+view);assert.ok(dom.window.document.body.textContent.includes(text),view+' missing '+text);dom.window.close();}
};
