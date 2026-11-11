/* Dedicated production-controls browser test; legacy workflow smoke stays separate. */
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const {chromium}=require('playwright');const temp=fs.mkdtempSync(path.join(os.tmpdir(),'approval-browser-')),port=24000+Math.floor(Math.random()*2000),base='http://127.0.0.1:'+port,python=process.env.PYTHON||'python',cwd=path.resolve(__dirname,'..'),password='Approval-browser-only-42';
 const env={...process.env,DATABASE_URL:'sqlite:///'+path.join(temp,'test.sqlite'),COOKIE_SECURE:'false',APPROVAL_CONTROLS_ENABLED:'true'};
 let server,browser,secondBrowser;
 try{
  const setup=spawnSync(python,['-c',`from backend.app import app,db,User\nfrom backend.approvals import ApprovalPolicy\nfrom werkzeug.security import generate_password_hash\nwith app.app_context():\n result=app.test_cli_runner().invoke(args=['init-db'])\n assert result.exit_code==0,result.output\n for uid,name in [('maker','Maker'),('reviewer','Reviewer')]:\n  db.session.add(User(id=uid,name=name,email=uid+'@example.test',role='Admin',active=True,password_hash=generate_password_hash('${password}')))\n db.session.add(ApprovalPolicy(id=1,limits={'Admin':'10000'}))\n db.session.commit()`],{env,cwd,encoding:'utf8'});assert.equal(setup.status,0,setup.stderr);
  server=spawn(python,['-m','flask','--app','backend.app','run','--port',String(port)],{env,cwd,stdio:'ignore'});
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break}catch{}await new Promise(r=>setTimeout(r,40))}
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH,args:JSON.parse(process.env.CHROMIUM_ARGS||'[]')}:{})});
  secondBrowser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH,args:JSON.parse(process.env.CHROMIUM_ARGS||'[]')}:{})});
  const maker=await browser.newContext({viewport:{width:1366,height:900}}),reviewer=await secondBrowser.newContext({viewport:{width:1366,height:900}});
  const errors=[];
  const login=async(context,who)=>{
    await context.route('**/*',route=>route.request().url().startsWith(base)?route.continue():route.abort());
    const login=await context.request.post(base+'/api/auth/login',{data:{email:who+'@example.test',password}});assert.equal(login.status(),200,await login.text());
    assert.equal((await login.json()).user.email,who+'@example.test');
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto(base+'/erp.html?view=approvals');await page.waitForSelector('[data-frontend="react"]');return page;
  };
  const m=await login(maker,'maker'),r=await login(reviewer,'reviewer');
  const auth=await(await maker.request.get(base+'/api/auth/me')).json();
  assert.equal(auth.user.id,'maker');assert.equal((await(await reviewer.request.get(base+'/api/auth/me')).json()).user.id,'reviewer');
  const created=await maker.request.post(base+'/api/products',{headers:{'X-CSRF-Token':auth.csrfToken},data:{name:'Approval browser stock',sku:'APPROVAL-STOCK',rate:10,requestKey:'approval-browser-product'}});assert.equal(created.status(),200,await created.text());const product=(await created.json()).record;
  await m.goto(base+'/erp.html?view=inventory');await m.locator('[data-native-inventory][aria-busy="false"]').waitFor();
  await m.getByRole('button',{name:'Stock Adjustment',exact:true}).click();
  let dialog=m.getByRole('dialog');
  const selection=dialog.getByLabel('Stock product',{exact:true});await selection.locator('option').filter({hasText:'Approval browser stock'}).waitFor({state:'attached'});await selection.selectOption(String(product.id));
  await dialog.locator('[name=quantity]').fill('5');await dialog.locator('[name=unitCost]').fill('10');await dialog.getByLabel('Reason',{exact:true}).fill('Five units verified against supplier document');
  await dialog.getByRole('button',{name:'Post Movement',exact:true}).click();
  await m.locator('[data-native-approvals][aria-busy="false"]').waitFor();
  const row=m.getByRole('row').filter({hasText:'Approval browser stock'});await row.getByRole('button',{name:'View Request',exact:true}).click();
  assert.equal(await m.getByRole('dialog').getByRole('button',{name:'Approve',exact:true}).count(),0);
  let stock=(await(await maker.request.get(base+'/api/inventory/products/'+product.id)).json()).record;assert.equal(Number(stock.quantity),0);
  await r.goto(base+'/erp.html?view=approvals');await r.locator('[data-native-approvals][aria-busy="false"]').waitFor();
  await r.getByRole('row').filter({hasText:'Approval browser stock'}).getByRole('button',{name:'View Request',exact:true}).click();
  const pending=await(await reviewer.request.get(base+'/api/approvals/requests')).json();assert.equal(pending.items[0].canDecide,true,JSON.stringify(pending));
  dialog=r.getByRole('dialog');await dialog.getByRole('button',{name:'Approve',exact:true}).click();await dialog.getByLabel('Decision reason',{exact:true}).fill('Independent count checked; approved PKR 50');await dialog.getByRole('button',{name:'Confirm Approval',exact:true}).click();await dialog.waitFor({state:'hidden'});
  stock=(await(await maker.request.get(base+'/api/inventory/products/'+product.id)).json()).record;assert.equal(Number(stock.quantity),5);assert.equal(Number(stock.value),50);
  for(const width of [1366,390]){
   await r.setViewportSize({width,height:900});await r.goto(base+'/erp.html?view=approvals');await r.locator('[data-native-approvals][aria-busy="false"]').waitFor();await r.getByRole('button',{name:'Approval Controls',exact:true}).click();dialog=r.getByRole('dialog',{name:'Approval Controls',exact:true});await dialog.waitFor();
   await dialog.getByLabel('Admin limit (PKR)',{exact:true}).fill('1000');await dialog.getByLabel('Policy change reason',{exact:true}).fill('Reviewed demo authority limits');
   await dialog.getByRole('button',{name:'Cancel',exact:true}).scrollIntoViewIfNeeded();assert.ok((await dialog.boundingBox()).width<=width);
   await r.screenshot({path:path.join(cwd,'test-results/approval-controls-'+width+'.png')});await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
   assert.equal((await(await reviewer.request.get(base+'/api/approvals/policy')).json()).limits.Admin,'10000');
  }
  await r.setViewportSize({width:1366,height:900});await r.goto(base+'/erp.html?view=approvals');await r.locator('[data-native-approvals][aria-busy="false"]').waitFor();await r.getByRole('button',{name:'Approval Controls',exact:true}).click();dialog=r.getByRole('dialog',{name:'Approval Controls',exact:true});await dialog.getByLabel('Admin limit (PKR)',{exact:true}).fill('1000');await dialog.getByLabel('Policy change reason',{exact:true}).fill('Client demo limit reviewed');await dialog.getByRole('button',{name:'Save Approval Limits',exact:true}).click();await dialog.waitFor({state:'hidden'});
  assert.equal((await(await reviewer.request.get(base+'/api/approvals/policy')).json()).limits.Admin,'1000.00');
  const expenseResponse=await maker.request.post(base+'/api/expenses/commands/create',{headers:{'X-CSRF-Token':auth.csrfToken},data:{description:'Approval browser expense',amount:10,tax:0,date:'2026-11-06',requestKey:'approval-browser-expense'}});assert.equal(expenseResponse.status(),200,await expenseResponse.text());let expense=(await expenseResponse.json()).record;
  const submittedExpense=await maker.request.post(base+'/api/expenses/commands/submit',{headers:{'X-CSRF-Token':auth.csrfToken},data:{id:expense.id,version:expense.version,requestKey:'approval-browser-expense-submit'}});assert.equal(submittedExpense.status(),200);
  await r.goto(base+'/erp.html?view=expense-claims');await r.locator('[data-native-expenses][aria-busy="false"]').waitFor();
  await r.getByRole('row').filter({hasText:'Approval browser expense'}).getByRole('button',{name:expense.number,exact:true}).click();await r.getByRole('dialog').getByRole('button',{name:'Reject',exact:true}).click();
  const rejection=r.getByRole('dialog',{name:'Record Decision Reason',exact:true});await rejection.waitFor();await rejection.getByLabel('Decision reason',{exact:true}).fill('Missing supporting receipt');await rejection.getByRole('button',{name:'Confirm Decision',exact:true}).click();await rejection.waitFor({state:'hidden'});
  await r.getByRole('dialog').getByText('Rejected',{exact:true}).waitFor();
  const rejected=await(await reviewer.request.get(base+'/api/approvals/requests?status=Rejected')).json();assert.equal(rejected.items[0].reason,'Missing supporting receipt');
  assert.deepEqual(errors,[]);console.log('Production approval browser: request redirect, no self approval, independent execution, PKR controls, policy audit and desktop/mobile Cancel passed; pageErrors=[]');
 }finally{if(browser)await browser.close();if(secondBrowser)await secondBrowser.close();if(server)server.kill();fs.rmSync(temp,{recursive:true,force:true})}
})().catch(error=>{console.error(error);process.exitCode=1});
