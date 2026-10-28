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
    if(dom.window.eval('!!nativeProductionView()')){
      await waitFor(()=>document.querySelector('[data-native-production][aria-busy="false"]'),'Native manufacturing did not load');
      assert.ok(!calls.includes('/api/state')&&!calls.includes('/api/hr/state')&&!calls.includes('/api/erp/manufacturing')&&!calls.includes('/api/erp/boms'),'Production must use bounded SQL APIs');
    }
    if(dom.window.eval('!!nativeInventoryView()')){
      await waitFor(()=>document.querySelector('[data-native-inventory][aria-busy="false"]'),'Native inventory did not load');
      assert.ok(!calls.includes('/api/state')&&!calls.includes('/api/hr/state')&&!calls.includes('/api/erp/inventory'),'Inventory must use bounded SQL APIs');
    }
    if(dom.window.eval('!!nativeFinanceView()')){
      await waitFor(()=>document.querySelector('[data-native-finance]')&&!document.querySelector('[data-native-finance][aria-busy="true"]'),'Native finance did not load');
      assert.ok(!calls.includes('/api/state')&&!calls.includes('/api/hr/state'),'Finance must use compact resources');
    }
    if(dom.window.eval('!!NATIVE_HR_ROUTES[workspacePage()]')){
      await waitFor(()=>document.querySelector('[data-native-hr]')&&!document.querySelector('[data-native-hr] [role="status"]')&&document.querySelector('[data-native-hr]').getAttribute('aria-busy')!=='true','Native HR did not load');
      assert.ok(!calls.includes('/api/state')&&!calls.includes('/api/hr/state'),'HR must use compact resources');
    }
    if(dom.window.eval('!!NATIVE_TRADE_ROUTES[workspacePage()]')){
      await waitFor(()=>document.querySelector('[data-screen^="trade-"] [aria-busy="false"]'),'Native transaction did not load');
      assert.ok(!calls.includes('/api/state')&&!calls.includes('/api/hr/state'),'Transactions must use compact resources');
    }
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
  await waitFor(()=>handoff.window.document.querySelector('select[name=customerId]')?.value===String(sharedCustomer.id),'Assigned seller cannot open CRM handoff');
  assert.equal(handoff.window.document.querySelector('select[name=customerId]').value,String(sharedCustomer.id));handoff.window.close();
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

  const {rawId}=await require('./trade-dom.cjs')({page,assert});

  await require('./production-dom.cjs')({page,assert,rawId});

  // Expense approval and reimbursement through the same interface.
  dom=await page('erp:expenses');dom.window.erpNewExpense();
  dom.window.document.getElementById('expense-description').value='Demo client visit';dom.window.document.getElementById('expense-amount').value='25';
  await dom.window.erpSaveExpense();const expenseId=dom.window.eval('ERP_CACHE.expenses[0].id');
  for(const action of ['submit','approve'])await dom.window.erpAction(`/expenses/${expenseId}/${action}`);
  await dom.window.erpAction(`/expenses/${expenseId}/pay`,{account:'1010'});
  assert.equal(dom.window.eval('ERP_CACHE.expenses[0].status'),'Paid');dom.window.close();

  await require('./hr-dom.cjs')({page,assert});
  await require('./finance-dom.cjs')({page,assert});
  await require('./inventory-dom.cjs')({page,assert});
  dom = await page('sales-payments');
  const persisted=await dom.window.eval("BackendPersistence.request('/trade/customerInvoices')");
  assert.equal(persisted.items[0].paidAmount,40);
  assert.equal(persisted.items[0].status,'Partially Paid');
  assert.equal(dom.window.eval('db().customerInvoices.length'),0,'Compact screens must not cache the entire register');
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
  console.log(`${names.length} pages/views rendered with shared module navigation; active tabs, module context and restricted roles passed; native Production/Inventory/Finance/Sales/Purchasing/HR API and React read models, manufacturing and expense flows passed.`);
}

main().catch(error => {console.error(error); process.exitCode = 1;}).finally(() => {
  if (server) server.kill();
  fs.rmSync(temp, {recursive: true, force: true});
});
