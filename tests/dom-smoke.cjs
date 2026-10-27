/* Real HTTP backend + DOM execution. This is not a visual/browser layout test. */
const {JSDOM, VirtualConsole, CookieJar, ResourceLoader} = require('jsdom');
const {spawn, spawnSync} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');

const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'purchase-smoke-'));
const python = process.env.PYTHON || 'python';
const password = 'Automated-test-only-42';
const port = 18000 + Math.floor(Math.random() * 10000);
const base = `http://127.0.0.1:${port}`;
const env = {...process.env, DATABASE_URL: 'sqlite:///' + path.join(temp, 'test.sqlite'), COOKIE_SECURE: 'false'};
let server;

async function waitFor(predicate, message) {
  for (let i = 0; i < 100; i++) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 30));
  }
  throw new Error(message);
}

async function main() {
  const init = spawnSync(python, ['-m', 'flask', '--app', 'backend.app', 'init-db'], {env, encoding: 'utf8'});
  assert.equal(init.status, 0, init.stderr);
  const seed = spawnSync(python, ['-c', `from backend.app import app,db,User\nfrom werkzeug.security import generate_password_hash\nwith app.app_context():\n db.session.add(User(id='demo-admin',name='Test Administrator',email='admin@example.test',role='Admin',active=True,password_hash=generate_password_hash('${password}')))\n db.session.commit()`], {env, encoding: 'utf8'});
  assert.equal(seed.status, 0, seed.stderr);
  server = spawn(python, ['-m', 'flask', '--app', 'backend.app', 'run', '--port', String(port)], {env, stdio: 'ignore'});
  await waitFor(async () => {try {return (await fetch(base + '/api/health')).ok;} catch {return false;}}, 'Backend did not start');
  const login = await fetch(base + '/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({email: 'admin@example.test', password})});
  assert.equal(login.status, 200);
  const jar = new CookieJar();
  jar.setCookieSync(login.headers.get('set-cookie'), base);
  const errors = [];
  class LocalResources extends ResourceLoader {
    fetch(url, opts) {return url.startsWith(base) ? super.fetch(url, opts) : null;}
  }
  async function page(name) {
    const calls=[];
    const console = new VirtualConsole();
    console.on('jsdomError', error => {
      if (!error.message.includes('Could not load') && !error.message.includes('CSS') && !error.message.includes('navigation')) errors.push(name + ': ' + error.message);
    });
    const [plain,search]=name.split('?');const filename=name.startsWith('erp:')?'erp.html?view='+name.slice(4):plain+'.html'+(search?'?'+search:'');
    const dom = await JSDOM.fromURL(base + '/' + filename, {
      cookieJar: jar, runScripts: 'dangerously', resources: new LocalResources(), pretendToBeVisual: true, virtualConsole: console,
      beforeParse(window) {
        window.structuredClone = structuredClone;
        window.Headers = Headers;
        window.fetch = (url, options = {}) => {calls.push(new URL(url,window.location.href).pathname);return fetch(new URL(url, window.location.href), {
          ...options, headers: {...Object.fromEntries(new Headers(options.headers || {})), Cookie: jar.getCookieStringSync(base)}
        });};
        window.HTMLElement.prototype.scrollIntoView = function() {};
        window.matchMedia = () => ({matches: false, addEventListener() {}, removeEventListener() {}});
      }
    });
    await waitFor(() => dom.window.document.querySelector('.sidebar'), 'No sidebar on ' + name);
    const close=dom.window.close.bind(dom.window);dom.window.close=()=>{dom.window.ModernWorkspace?.dispose();close()};
    const document=dom.window.document;
    assert.equal(document.querySelector('.module-app').dataset.frontend,'react','Expected the React shell on '+name);
    assert.equal(dom.window.location.pathname,'/erp.html','Every module uses the shared workspace');
    assert.ok(dom.window.location.search.includes('view='),'Every screen has a view route');
    for(const link of document.querySelectorAll('.sidebar a[href],.module-tabs a[href]')){
      const target=new URL(link.href);
      assert.equal(target.pathname,'/erp.html','Navigation must use the shared workspace: '+link.href);
      assert.ok(target.searchParams.get('view'));
    }
    assert.ok(document.querySelector('.module-header h1'),'Missing shared header: '+name);
    assert.equal(document.querySelectorAll('.sidebar .nav-item.active').length,1,'Expected one active module: '+name);
    const module=document.querySelector('.module-app').dataset.module;
    if(module!=='overview'){
      assert.equal(document.querySelectorAll('.module-tabs').length,1,'Expected one shared submenu: '+name);
      assert.equal(document.querySelectorAll('.module-tabs [aria-current="page"]').length,1,'Expected one active tab: '+name);
      if(module!=='admin')assert.equal(document.querySelectorAll('.module-navigation .module-flow').length,1,'Missing workflow strip: '+name);
    }
    assert.equal(document.querySelectorAll('.sidebar a[href="leads.html"],.sidebar a[href="orders.html"],.sidebar a[href="hr-payroll.html"]').length,0,'Submenus must live in the module content: '+name);
    if(['customers.html','vendors.html','products.html','leads.html','reminders.html'].includes(dom.window.eval('workspacePage()'))){
      assert.ok(document.querySelector('[data-screen$="-react"]'));
      await waitFor(()=>document.querySelector('[aria-busy="false"]'),'Native screen did not finish loading');
      assert.ok(!calls.includes('/api/state')&&!calls.includes('/api/hr/state'),'Customers must not fetch full business/HR aggregates');
    }
    return dom;
  }

  const names = ['dashboard', 'users', 'vendors', 'products', 'requests', 'rfqs', 'quotations', 'comparison', 'orders',
    'receipts', 'invoices', 'payments', 'crm-dashboard', 'leads', 'reminders', 'sales', 'customers', 'sales-quotations',
    'sales-orders', 'sales-deliveries', 'sales-invoices', 'sales-payments', 'hr-dashboard', 'hr-employees', 'hr-manpower',
    'admin-data', 'hr-recruitment', 'hr-attendance', 'hr-leave', 'hr-payroll', 'hr-separation', 'hr-reports', 'reports', 'activities',
    'erp:overview','erp:accounting','erp:accounts','erp:journals','erp:reports','erp:aged','erp:bank','erp:inventory','erp:stock-moves','erp:manufacturing','erp:production-orders','erp:boms','erp:expenses','erp:expense-claims'];
  for (const name of names) {(await page(name)).window.close();}
  let profilePage=await page('sales');
  assert.equal(profilePage.window.document.querySelectorAll('#user-dropdown button[data-action="company-profile"]').length,1);
  await profilePage.window.openCompanyProfile();
  assert.ok(profilePage.window.document.getElementById('profile-name'),'Company profile opens outside ERP overview');
  profilePage.window.close();
  const userSetup=await page('users');userSetup.window.openUser();
  const setupDoc=userSetup.window.document;
  setupDoc.getElementById('user-role').value='Procurement Staff';userSetup.window.toggleUserManagerField();
  assert.equal(setupDoc.getElementById('user-manager-wrap').style.display,'block');
  setupDoc.getElementById('user-name').value='Procurement team user';
  setupDoc.getElementById('user-email').value='procurement-team@example.test';
  setupDoc.getElementById('user-password').value=password;
  setupDoc.getElementById('user-manager').value=userSetup.window.currentUser().id;
  await userSetup.window.saveUser('');
  const teamUser=userSetup.window.eval('db().users.find(u=>u.email==="procurement-team@example.test")');
  assert.equal(teamUser.managerId,userSetup.window.currentUser().id);
  const assignedSeller=await userSetup.window.eval('BackendPersistence.request')('/users',{method:'POST',body:JSON.stringify({name:'Assigned seller',email:'assigned-seller@example.test',password,role:'Salesperson',managerId:userSetup.window.currentUser().id,active:true})});
  userSetup.window.close();
  let handoff=await page('customers?module=crm');handoff.window.openCustomer();
  handoff.window.document.getElementById('cname').value='CRM shared customer';
  await handoff.window.saveCustomer();
  const sharedCustomer=handoff.window.eval('db().customers.find(c=>c.name==="CRM shared customer")');
  await assert.rejects(handoff.window.eval('save(db())'),/individual record saves/);handoff.window.close();
  handoff=await page('leads');handoff.window.openCrmLead();
  await waitFor(()=>[...handoff.window.document.getElementById('crm-lead-customer').options].some(o=>o.value===String(sharedCustomer.id))&&[...handoff.window.document.getElementById('crm-lead-owner').options].some(o=>o.value===assignedSeller.id),'CRM reference choices did not load');
  handoff.window.document.getElementById('crm-lead-customer').value=String(sharedCustomer.id);
  handoff.window.document.getElementById('crm-lead-owner').value=assignedSeller.id;
  await handoff.window.saveCrmLead();
  const assignedLead=handoff.window.eval('db().leads[0]');handoff.window.close();
  const assignedLogin=await fetch(base+'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'assigned-seller@example.test',password})});
  assert.equal(assignedLogin.status,200);jar.setCookieSync(assignedLogin.headers.get('set-cookie'),base);
  handoff=await page('leads');
  assert.equal(handoff.window.eval('db().leads.length'),1);
  assert.equal(handoff.window.eval('db().leads[0].id'),assignedLead.id);handoff.window.close();
  handoff=await page('sales-quotations?leadId='+assignedLead.id);
  await waitFor(()=>handoff.window.document.getElementById('sq-customer'),'Assigned seller cannot open CRM handoff');
  assert.equal(handoff.window.document.getElementById('sq-customer').value,String(sharedCustomer.id));handoff.window.close();
  jar.setCookieSync(login.headers.get('set-cookie'),base);
  // Shared master-data links retain their originating module's submenu.
  let contextPage=await page('customers?module=crm');
  assert.equal(contextPage.window.document.querySelector('.module-app').dataset.module,'crm');contextPage.window.close();
  contextPage=await page('products?module=purchase');
  assert.equal(contextPage.window.document.querySelector('.module-app').dataset.module,'purchase');contextPage.window.close();
  let dom = await page('vendors');
  dom.window.openVendor();
  dom.window.document.getElementById('vname').value = 'Persisted through the interface';
  await dom.window.saveVendor();
  await waitFor(()=>!dom.window.document.querySelector('[role="dialog"]')&&dom.window.document.querySelector('[aria-busy="false"]')&&dom.window.document.body.textContent.includes('Persisted through the interface'),'Vendor did not refresh');
  assert.match(dom.window.document.body.textContent, /Persisted through the interface/);
  dom.window.close();
  dom = await page('vendors');
  assert.match(dom.window.document.body.textContent, /Persisted through the interface/);
  dom.window.close();

  dom = await page('hr-employees');
  const form = dom.window.document.querySelector('form.hr-form');
  for (const [key, value] of Object.entries({employeeId: 'EMP-1', name: 'Database Employee', department: 'Finance',
      designation: 'Accountant', joiningDate: '2026-10-26', salary: '10000'})) form.elements[key].value = value;
  await dom.window.hrSubmit({preventDefault() {}, target: form}, 'employees');
  assert.match(dom.window.document.body.textContent, /Database Employee/);
  dom.window.close();
  dom = await page('hr-employees');
  assert.match(dom.window.document.body.textContent, /Database Employee/);
  dom.window.close();

  // Exercise the sales workflow against actual persisted state and CRM synchronization.
  dom = await page('sales-quotations');
  await dom.window.eval(`(async () => {
    const x=db();
    x.products.push({id:1003,name:'Test service',sku:'TEST-SVC',unit:'Service',rate:100});
    x.customers.push({id:1001,code:'CUS-TEST',name:'Workflow Customer',status:'Active'});
    x.leads.push({id:1002,customerId:1001,customerName:'Workflow Customer',ownerId:currentUser().id,stage:'Quotation Required'});
    await save(x);
  })()`);
  dom.window.openSalesQuotation(1002);
  dom.window.document.querySelector('.s-prod').value = '1003';
  dom.window.document.querySelector('.s-rate').value = '100';
  await dom.window.saveSalesQuotationWorkflow('Pending Approval', 1002);
  const quoteId = dom.window.eval('db().salesQuotations[0].id');
  await dom.window.approveSalesQuotation(quoteId);
  assert.equal(dom.window.eval('db().leads.find(l=>l.id===1002).stage'), 'Quotation Approved');
  await dom.window.sendSalesQuotationToCustomer(quoteId);
  await dom.window.acceptSalesQuotation(quoteId);
  assert.equal(dom.window.eval('db().leads.find(l=>l.id===1002).stage'), 'Closed Won');
  dom.window.openSalesOrderCreateModal(quoteId);
  await dom.window.saveSalesOrderFromModal();
  dom.window.close();
  dom = await page('sales-invoices');
  dom.window.downloadSalesInvoicePdf = () => {};
  dom.window.createInvoiceFromOrderModal();
  await dom.window.saveInvoiceFromOrderModal();
  dom.window.close();
  dom = await page('sales-payments');
  dom.window.downloadCustomerPaymentPdf = () => {};
  dom.window.openStandaloneCustomerPayment();
  dom.window.document.getElementById('cp-amount').value = '40';
  await dom.window.saveStandaloneCustomerPayment();
  // This wrapper delegates to the asynchronous saver; wait for its promise queue.
  await dom.window.eval('BackendPersistence.drain()');
  assert.equal(dom.window.eval('db().customerInvoices[0].paidAmount'), 40);
  dom.window.close();

  // Full purchasing screen flow, including stock valuation, supplier bill and bank payment.
  dom = await page('products');
  dom.window.openProduct();
  for(const [id,value] of Object.entries({pname:'Workflow raw material',psku:'RAW-UI-1',prate:'10'}))dom.window.document.getElementById(id).value=value;
  await dom.window.saveProduct();
  const rawId=dom.window.eval('db().products.at(-1).id');
  dom.window.close();
  dom=await page('requests');dom.window.openRequest();
  dom.window.document.querySelector('.req-product').value=String(rawId);
  dom.window.document.querySelector('.req-qty').value='20';
  dom.window.document.querySelector('.req-rate').value='10';
  await dom.window.saveRequest();
  const requestId=dom.window.eval('db().requests[0].id');
  await dom.window.approveRequest(requestId);dom.window.close();
  dom=await page('rfqs');dom.window.openRFQ(requestId);
  dom.window.document.getElementById('rfq-due').value='2026-12-31';
  dom.window.document.getElementById('rfq-vendors').options[0].selected=true;
  await dom.window.saveRFQ();const rfqId=dom.window.eval('db().rfqs[0].id');
  await dom.window.sendRFQ(rfqId);dom.window.close();
  dom=await page('quotations');dom.window.openQuotation(rfqId);
  dom.window.document.getElementById('q-vendor').selectedIndex=1;
  dom.window.document.getElementById('q-valid').value='2026-12-31';
  dom.window.document.querySelector('.q-rate').value='10';
  await dom.window.saveQuotation();const vendorQuote=dom.window.eval('db().quotations[0].id');
  await dom.window.awardQuotation(vendorQuote);dom.window.close();
  dom=await page('orders');dom.window.openPOFromQuotation();
  dom.window.document.getElementById('po-quotation').value=String(vendorQuote);
  dom.window.loadPODetails();dom.window.document.getElementById('po-delivery-date').value='2026-12-31';
  await dom.window.savePO();const poId=dom.window.eval('db().orders[0].id');
  for(const state of ['Pending Approval','Approved','Sent to Vendor'])await dom.window.updatePOStatus(poId,state);
  dom.window.close();
  dom=await page('receipts');dom.window.openGRN();
  dom.window.document.getElementById('grn-po').value=String(poId);dom.window.loadGRNPO();
  dom.window.document.querySelector('.grn-received').value='10';
  dom.window.document.querySelector('.grn-accepted').value='10';
  await dom.window.saveGRN();dom.window.close();
  dom=await page('invoices');dom.window.openInvoice();
  dom.window.document.getElementById('inv-po').value=String(poId);dom.window.loadInvoicePO();
  dom.window.document.getElementById('inv-no').value='UI-BILL-1';
  dom.window.document.getElementById('inv-due').value='2026-12-31';
  await dom.window.saveInvoice();const billId=dom.window.eval('db().invoices[0].id');
  await dom.window.approveInvoice(billId);dom.window.close();
  dom=await page('payments');dom.window.openPayment();
  dom.window.document.getElementById('pay-invoice').value=String(billId);dom.window.loadPaymentInvoice();
  await dom.window.savePayment();assert.equal(dom.window.eval('db().invoices[0].status'),'Paid');
  assert.equal(dom.window.eval('db().orders[0].status'),'Partially Received');dom.window.close();
  // Receive and bill the remaining half: the PO completes only after both installments.
  dom=await page('receipts');dom.window.openGRN();
  dom.window.document.getElementById('grn-po').value=String(poId);dom.window.loadGRNPO();
  await dom.window.saveGRN();dom.window.close();
  dom=await page('invoices');dom.window.openInvoice();
  dom.window.document.getElementById('inv-po').value=String(poId);dom.window.loadInvoicePO();
  assert.equal(Number(dom.window.document.getElementById('inv-amount').value),100);
  dom.window.document.getElementById('inv-no').value='UI-BILL-2';dom.window.document.getElementById('inv-due').value='2026-12-31';
  await dom.window.saveInvoice();const secondBillId=dom.window.eval('db().invoices[0].id');
  await dom.window.approveInvoice(secondBillId);dom.window.close();
  dom=await page('payments');dom.window.openPayment();
  dom.window.document.getElementById('pay-invoice').value=String(secondBillId);dom.window.loadPaymentInvoice();
  await dom.window.savePayment();assert.equal(dom.window.eval('db().orders[0].status'),'Completed');dom.window.close();

  // Manufacturing through the new screens, using the raw material received above.
  dom=await page('products');dom.window.openProduct();
  dom.window.document.getElementById('pname').value='Workflow finished kit';dom.window.document.getElementById('psku').value='FG-UI-1';
  await dom.window.saveProduct();const finishedId=dom.window.eval('db().products.at(-1).id');dom.window.close();
  dom=await page('erp:boms');await dom.window.erpNewBOM();
  dom.window.document.getElementById('bom-name').value='Workflow kit BoM';dom.window.document.getElementById('bom-product').value=String(finishedId);
  dom.window.document.querySelector('.bom-component').value=String(rawId);dom.window.document.querySelector('.bom-component-qty').value='2';
  await dom.window.erpSaveBOM();dom.window.close();
  dom=await page('erp:manufacturing');dom.window.erpNewMO();
  const moSave=dom.window.document.getElementById('erp-submit').getAttribute('onclick');await dom.window.eval(moSave);
  const moId=dom.window.ERP_CACHE?.orders?.[0]?.id||dom.window.eval('ERP_CACHE.orders[0].id');
  for(const action of ['confirm','start','complete'])await dom.window.erpAction(`/manufacturing/${moId}/${action}`);
  assert.equal(dom.window.eval('ERP_CACHE.orders[0].state'),'Done');dom.window.close();

  // Expense approval and reimbursement through the same interface.
  dom=await page('erp:expenses');dom.window.erpNewExpense();
  dom.window.document.getElementById('expense-description').value='Demo client visit';dom.window.document.getElementById('expense-amount').value='25';
  await dom.window.erpSaveExpense();const expenseId=dom.window.eval('ERP_CACHE.expenses[0].id');
  for(const action of ['submit','approve'])await dom.window.erpAction(`/expenses/${expenseId}/${action}`);
  await dom.window.erpAction(`/expenses/${expenseId}/pay`,{account:'1010'});
  assert.equal(dom.window.eval('ERP_CACHE.expenses[0].status'),'Paid');dom.window.close();

  // Payroll approval and payment automatically create the two salary journals.
  dom=await page('hr-payroll');const payrollForm=dom.window.document.querySelector('form.hr-form');
  for(const [key,value] of Object.entries({month:'2026-10',basic:'10000',allowances:'500',deductions:'100'}))payrollForm.elements[key].value=value;
  await dom.window.hrSubmit({preventDefault(){},target:payrollForm},'payroll');
  const payrollId=dom.window.hrState().payroll[0].id;
  await dom.window.hrSetPayrollStatus(payrollId,'Approved');await dom.window.hrSetPayrollStatus(payrollId,'Paid');dom.window.close();
  dom=await page('erp:journals');
  assert.ok(dom.window.eval(`ERP_CACHE.entries.some(e=>e.source==='payroll:${payrollId}')`));
  assert.ok(dom.window.eval(`ERP_CACHE.entries.some(e=>e.source==='payroll:${payrollId}:payment')`));
  dom.window.close();
  // Exercise remaining HR registers and their actual UI action handlers.
  async function hrRecord(screen,group,values){
    const view=await page(screen);const form=view.window.document.querySelector('form.hr-form');
    for(const [key,value] of Object.entries(values))form.elements[key].value=value;
    await view.window.hrSubmit({preventDefault(){},target:form},group);
    return view;
  }
  dom=await hrRecord('hr-manpower','manpower',{department:'Production',position:'Machine operator',count:'1',reason:'Demo expansion',requestedBy:'Demo manager'});
  await dom.window.hrAdvance(dom.window.hrState().manpower[0].id);
  assert.equal(dom.window.hrState().manpower[0].status,'Approved');dom.window.close();
  dom=await hrRecord('hr-recruitment','candidates',{name:'Demo candidate',position:'Machine operator',contact:'candidate@example.test',stage:'Hired'});
  assert.equal(dom.window.hrState().candidates[0].stage,'Hired');dom.window.close();
  dom=await hrRecord('hr-attendance','attendance',{date:'2026-10-26',attendanceStatus:'Present'});
  assert.equal(dom.window.hrState().attendance[0].attendanceStatus,'Present');
  const alerts=[];dom.window.alert=message=>alerts.push(message);
  let attendanceForm=dom.window.document.querySelector('form.hr-form');
  attendanceForm.elements.date.value='2026-10-26';
  await dom.window.hrSubmit({preventDefault(){},target:attendanceForm},'attendance');
  assert.equal(dom.window.hrState().attendance.length,1);assert.equal(alerts.length,1);dom.window.close();
  dom=await hrRecord('hr-leave','leaves',{from:'2026-11-01',to:'2026-11-02',reason:'Demo leave',leaveType:'Annual'});
  assert.equal(dom.window.hrState().leaves[0].days,2);
  await dom.window.hrSetLeaveStatus(dom.window.hrState().leaves[0].id,'Approved');
  assert.equal(dom.window.hrState().leaves[0].status,'Approved');
  dom.window.alert=message=>alerts.push(message);
  const leaveForm=dom.window.document.querySelector('form.hr-form');
  leaveForm.elements.from.value='2026-11-02';leaveForm.elements.to.value='2026-11-03';leaveForm.elements.reason.value='Overlapping leave';
  await dom.window.hrSubmit({preventDefault(){},target:leaveForm},'leaves');
  assert.equal(dom.window.hrState().leaves.length,1);assert.equal(alerts.length,2);dom.window.close();
  dom=await hrRecord('hr-separation','separations',{lastWorkingDate:'2026-11-30',reason:'Demo separation',finalSettlement:'0'});
  const separationId=dom.window.hrState().separations[0].id;
  await dom.window.hrSeparationStatus(separationId,'Approved');
  await dom.window.hrSeparationStatus(separationId,'Completed');
  assert.equal(dom.window.hrState().employees[0].status,'Separated');dom.window.close();
  dom=await page('hr-reports');assert.match(dom.window.document.body.textContent,/Separated Employees/);dom.window.close();
  dom = await page('sales-payments');
  assert.equal(dom.window.eval('db().customerInvoices[0].paidAmount'), 40);
  assert.equal(dom.window.eval('db().customerInvoices[0].status'), 'Partially Paid');
  dom.window.close();

  // Restricted users see only permitted modules/tabs, including on shared master-data pages.
  const adminCookie=jar.getCookieStringSync(base);
  const adminMe=await (await fetch(base+'/api/auth/me',{headers:{Cookie:adminCookie}})).json();
  const created=await fetch(base+'/api/users',{method:'POST',headers:{Cookie:adminCookie,'Content-Type':'application/json','X-CSRF-Token':adminMe.csrfToken},
    body:JSON.stringify({name:'Navigation Viewer',email:'nav-viewer@example.test',password,role:'Viewer',active:true})});
  assert.equal(created.status,200);
  const viewerLogin=await fetch(base+'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'nav-viewer@example.test',password})});
  assert.equal(viewerLogin.status,200);jar.setCookieSync(viewerLogin.headers.get('set-cookie'),base);
  dom=await page('sales-quotations');
  assert.equal(dom.window.document.querySelectorAll('.sidebar [data-workspace="hr"],.sidebar [data-workspace="accounting"],.sidebar [data-workspace="manufacturing"]').length,0);
  assert.equal(dom.window.document.querySelector('.module-tabs [aria-current="page"]').textContent,'Quotations');
  assert.equal(dom.window.document.querySelectorAll('#user-dropdown button[data-action="company-profile"]').length,0);
  dom.window.close();
  dom=await page('activities');
  assert.deepEqual([...dom.window.document.querySelectorAll('.module-tab')].map(e=>e.textContent),['Activity Log']);
  dom.window.close();
  jar.setCookieSync(login.headers.get('set-cookie'),base);

  assert.deepEqual(errors, []);
  console.log(`${names.length} pages/views rendered with shared module navigation; active tabs, module context and restricted roles passed; CRM/sales, purchasing, manufacturing, expenses, payroll, manpower, recruitment, attendance, leave and separation flows passed.`);
}

main().catch(error => {console.error(error); process.exitCode = 1;}).finally(() => {
  if (server) server.kill();
  fs.rmSync(temp, {recursive: true, force: true});
});
