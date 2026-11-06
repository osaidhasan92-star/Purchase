const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
(async()=>{
 const cwd=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'approval-browser-'));
 const python=process.env.PYTHON||'python',port=22345,base=process.env.APPROVAL_TEST_URL||'http://127.0.0.1:'+port;
 const env={...process.env,DATABASE_URL:'sqlite:///'+path.join(temp,'test.sqlite'),COOKIE_SECURE:'false'};
 let server,browser;
 try{
  if(!process.env.APPROVAL_TEST_URL){
   const setup=spawnSync(python,['-c',`from backend.app import app,db,User\nfrom werkzeug.security import generate_password_hash\nwith app.app_context():\n result=app.test_cli_runner().invoke(args=['init-db'])\n assert result.exit_code==0,result.output\n for uid in ['maker','approver']:\n  db.session.add(User(id=uid,name=uid,email=uid+'@example.test',role='Admin',active=True,password_hash=generate_password_hash('Browser-approval-test-42')))\n db.session.commit()`],{cwd,env,encoding:'utf8'});
   assert.equal(setup.status,0,setup.stderr);
   server=spawn(python,['-m','flask','--app','backend.app','run','--port',String(port)],{cwd,env,stdio:'ignore'});
   for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
  }
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH,args:JSON.parse(process.env.CHROMIUM_ARGS||'["--no-sandbox"]')}: {})});
  const maker=await browser.newContext(),approver=await browser.newContext();
  const login=async(context,name)=>{const r=await context.request.post(base+'/api/auth/login',{data:{email:name+'@example.test',password:'Browser-approval-test-42'}});assert.equal(r.status(),200);return (await r.json()).csrfToken;};
  const csrf=await login(maker,'maker');await login(approver,'approver');
  const pending=await maker.request.post(base+'/api/finance/commands/transfer',{headers:{'X-CSRF-Token':csrf},data:{fromAccount:'1000',toAccount:'1010',amount:'500',date:'2026-11-06',requestKey:'browser-approval-'+Date.now()}});
  assert.equal(pending.status(),409);const row=(await pending.json()).approval;
  const page=await approver.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/erp.html?view=overview');
  await page.getByRole('button',{name:'Pending Approvals',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Pending Approvals',exact:true});await dialog.waitFor();
  await dialog.getByText('#'+row.id+' · accounting · PKR 500.00',{exact:true}).waitFor();
  await dialog.getByRole('button',{name:'Approve and execute',exact:true}).click();
  await dialog.getByRole('alert').getByText('Enter a reason for your decision.',{exact:true}).waitFor();
  await dialog.getByLabel('Decision reason for request '+row.id,{exact:true}).fill('Verified account transfer request');
  await dialog.getByRole('button',{name:'Approve and execute',exact:true}).click();
  await dialog.getByText('No requests to display.',{exact:true}).waitFor();
  await dialog.getByLabel('Approval status',{exact:true}).selectOption('Approved');
  await dialog.getByText(/Decision: Verified account transfer request/).waitFor();
  await dialog.getByText('Approval limits (administrator)',{exact:true}).click();
  await dialog.getByLabel('Approver',{exact:true}).selectOption('approver');
  await dialog.getByLabel('Module',{exact:true}).selectOption('accounting');
  await dialog.getByLabel('PKR approval limit',{exact:true}).fill('2000000');
  await dialog.getByRole('button',{name:'Save limit',exact:true}).click();
  await dialog.getByText('Current override: PKR 2000000.00',{exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});
  assert.ok((await dialog.boundingBox()).width<=390);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),390);
  const check=await approver.request.get(base+'/api/approvals');assert.equal((await check.json()).items.find(r=>r.id===row.id).status,'Approved');
  assert.deepEqual(errors,[]);console.log('Approvals browser: inbox, reason validation, execute, history, limit configuration and mobile layout passed');
 }finally{await browser?.close();server?.kill();fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
