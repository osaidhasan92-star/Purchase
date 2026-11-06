const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
(async()=>{
 const dom=new JSDOM('<!doctype html><html><head></head><body></body></html>',{url:'http://localhost/erp.html',runScripts:'outside-only'}),w=dom.window;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 let status='Pending',override=null,calls=[];
 const row=()=>({id:1,module:'accounting',amount:'500.00',requesterId:'maker',creatorId:'maker',createdAt:'2026-11-06',status,reason:status==='Approved'?'Verified receipt':null,decidedBy:'reviewer',decidedAt:'2026-11-06',path:'/api/finance/commands/transfer',payload:{fromAccount:'1000',toAccount:'1010',amount:500,requestKey:'hidden-idempotency'},source:{memo:'<img src=x onerror=alert(1)>'},approvers:[{name:'Reviewer',id:'reviewer'}],canDecide:status==='Pending'});
 w.BackendPersistence={request:async(url,options)=>{
  calls.push([url,options]);
  if(url==='/auth/me')return {csrfToken:'test'};
  if(url==='/approvals/limits'){
   if(options?.method==='PUT')override=JSON.parse(options.body).amount;
   return {modules:['accounting'],users:[{id:'reviewer',name:'Reviewer',role:'Finance'}],items:override?[{userId:'reviewer',module:'accounting',amount:override}]:[]};
  }
  if(url==='/approvals/1/approve'){assert.equal(JSON.parse(options.body).reason,'Verified receipt');status='Approved';return {record:row()};}
  const params=new URL('http://localhost'+url).searchParams,filter=params.get('status');const items=filter&&filter!==status?[]:[row()];return {items,total:items.length,page:1,pageSize:25};
 }};
 w.eval(fs.readFileSync(path.join(__dirname,'../approval-inbox.js'),'utf8'));
 const wait=async fn=>{for(let i=0;i<30;i++){if(fn())return;await new Promise(r=>setTimeout(r,5));}assert.ok(fn());};
 const button=text=>Array.from(w.document.querySelectorAll('button')).find(e=>e.textContent===text);
 w.document.body.replaceChildren();await wait(()=>button('Pending Approvals'));
 button('Pending Approvals').click();await wait(()=>button('Approve and execute'));
 assert.ok(w.document.querySelector('dialog').open);
 assert.equal(w.document.querySelectorAll('img').length,0);
 assert.ok(!w.document.querySelector('dialog').textContent.includes('hidden-idempotency'));
 button('Approve and execute').click();assert.equal(w.document.querySelector('[role=alert]').textContent,'Enter a reason for your decision.');
 w.document.querySelector('textarea').value='Verified receipt';button('Approve and execute').click();
 await wait(()=>w.document.querySelector('section').textContent.includes('No requests to display.'));
 const filter=w.document.querySelector('[aria-label="Approval status"]');filter.value='Approved';filter.dispatchEvent(new w.Event('change'));
 await wait(()=>w.document.querySelector('section').textContent.includes('Verified receipt'));
 assert.equal(button('Approve and execute'),undefined);
 const input=w.document.querySelector('[aria-label="PKR approval limit"]');input.value='2000000';
 w.document.querySelector('form').dispatchEvent(new w.Event('submit',{cancelable:true}));await wait(()=>override==='2000000');
 button('Close').click();assert.equal(w.document.querySelector('dialog').open,false);
 assert.ok(calls.some(([url])=>url.includes('status=Approved')));
 w.close();console.log('Approval inbox DOM interactions, safe source rendering, reasons, history, limit settings and pagination passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
