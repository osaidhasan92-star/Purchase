const assert=require('node:assert/strict'),path=require('node:path');
module.exports=async(page,base)=>{
 const get=async(p)=>{const r=await page.request.get(base+'/api'+p);assert.equal(r.status(),200,await r.text());return r.json()};
 const me=await get('/auth/me'), headers={'X-CSRF-Token':me.csrfToken};let count=0;
 const post=async(p,body)=>{const r=await page.request.post(base+'/api'+p,{headers,data:{...body,requestKey:'credit-browser-'+Date.now()+'-'+(++count)}});assert.equal(r.status(),200,await r.text());return r.json()};
 const invoices=(await get('/trade/customerInvoices?status=Paid&pageSize=100')).items;
 assert.ok(invoices.length,'A paid invoice from the trade simulation is required');
 const invoice=(await get('/trade/customerInvoices/'+invoices[0].id)).record;
 const deliveries=(await get('/trade/deliveries?orderId='+invoice.orderId+'&status=Delivered')).items;
 let original;
 for(const delivery of deliveries){for(const move of (await get('/inventory/movements?search='+encodeURIComponent('deliveries:'+delivery.id+':'))).items){const detail=(await get('/inventory/movements/'+move.id)).record;if(detail.canReturn&&Number(detail.returnRemaining)>=1){original=detail;break}}if(original)break}
 assert.ok(original,'A delivered quantity must be available to return');
 const returned=(await post('/inventory/commands/return',{moveId:original.id,version:original.version,quantity:1,date:new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Karachi'}),reason:'Browser credit return'})).record;
 const today=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Karachi'});
 await page.goto(base+'/erp.html?view=credits&kind=customer&invoiceId='+invoice.id);
 const form=page.getByRole('dialog',{name:'New Credit Note',exact:true});await form.waitFor();
 await page.getByLabel('Credit Reason',{exact:true}).fill('Browser return credit');
 await page.getByLabel('Credit Date',{exact:true}).fill(today);
 await page.getByLabel('Credit Quantity 1',{exact:true}).fill('1');
 await page.getByLabel('Stock Return 1',{exact:true}).selectOption(String(returned.id));
 await form.getByRole('button',{name:'Save Draft Credit',exact:true}).click();
 await form.waitFor({state:'hidden'});
 let detail=page.getByRole('dialog');await detail.getByRole('button',{name:'Submit for Review',exact:true}).waitFor();
 await detail.getByRole('button',{name:'Submit for Review',exact:true}).click();
 await detail.getByRole('button',{name:'Post Credit Note',exact:true}).waitFor();await detail.getByRole('button',{name:'Post Credit Note',exact:true}).click();
 await detail.getByRole('button',{name:'Register Refund',exact:true}).waitFor();await detail.getByRole('button',{name:'Register Refund',exact:true}).click();
 await page.getByLabel('Settlement Date',{exact:true}).fill(today);
 await detail.getByRole('button',{name:'Confirm Refund',exact:true}).click();
 await detail.getByRole('button',{name:'Close',exact:true}).waitFor();assert.equal(await detail.getByRole('button',{name:'Register Refund',exact:true}).count(),0);
 await detail.getByText('Refund paid',{exact:false}).waitFor();
 await detail.getByRole('button',{name:'Close',exact:true}).click();
 const notes=(await get('/credits?kind=customer')).items;const created=notes.find(n=>n.reason==='Browser return credit');assert.ok(created);assert.equal(Number(created.remaining),0);assert.equal(created.settlements.filter(s=>s.kind==='refund').length,1);
 for(const width of [1366,390]){
  await page.setViewportSize({width,height:900});
  await page.goto(base+'/erp.html?view=credits&kind=customer');await page.locator('[data-screen="credits-react"][aria-busy="false"]').waitFor();
  await page.waitForFunction(()=>innerWidth>900||document.querySelector('.sidebar').getBoundingClientRect().right<=1);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
  await page.getByRole('button',{name:'New Credit Note',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'New Credit Note',exact:true});await dialog.waitFor();
  assert.ok((await dialog.boundingBox()).width<=width);
  await page.screenshot({path:path.join(__dirname,'../test-results/credit-note-'+width+'.png')});
  await dialog.getByRole('button',{name:'Cancel',exact:true}).click();await dialog.waitFor({state:'hidden'});
 }
 await page.setViewportSize({width:1366,height:900});
 console.log('Credit workflow: linked stock return, draft/review/post/refund, no duplicate settlement and desktop/mobile forms passed');
};
