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
const env = {...process.env, DATABASE_URL: 'sqlite:///' + path.join(temp, 'test.sqlite'), COOKIE_SECURE: 'false', APPROVAL_CONTROLS_ENABLED: 'false'};
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
      const isCrmQuoteArchive = name === 'crm-quotes';
      assert.equal(document.querySelectorAll('.module-tabs [aria-current="page"]').length,
        isCrmQuoteArchive ? 0 : 1, 'Unexpected active tab count: ' + name);
      if (module === 'crm') {
        const tabs = [...document.querySelectorAll('.module-tabs a[href]')];
        assert.ok(tabs.every(link => new URL(link.href).searchParams.get('view') !== 'crm-quotes'),
          'The legacy quote register must stay out of CRM navigation');
      }
      if(module!=='admin')assert.equal(document.querySelectorAll('.module-navigation .module-flow').length,1,'Missing workflow strip: '+name);
    }
    assert.equal(document.querySelectorAll('.sidebar a[href="leads.html"],.sidebar a[href="orders.html"],.sidebar a[href="hr-payroll.html"]').length,0,'Submenus must live in the module content: '+name);
    if(dom.window.eval('!!nativeRemainingView()')){
      await waitFor(()=>document.querySelector('[data-native-remaining][aria-busy="false"]'),'Native overview/register did not load');
      assert.ok(!calls.includes('/api/state')&&!calls.includes('/api/hr/state')&&!calls.includes('/api/erp/overview'),'Overview/registers must use compact SQL APIs');
    }
    if(dom.window.eval('!!nativeAdminView()')){
      await waitFor(()=>document.querySelector('[data-native-admin][aria-busy="false"]'),'Native administration did not load');
      assert.ok(!calls.includes('/api/state')&&!calls.includes('/api/hr/state')&&!calls.includes('/api/users'),'Administration must use bounded resources');
    }
    if(dom.window.eval('!!nativeExpenseView()')){
      await waitFor(()=>document.querySelector('[data-native-expenses][aria-busy="false"]'),'Native expenses did not load');
      assert.ok(!calls.includes('/api/state')&&!calls.includes('/api/hr/state')&&!calls.includes('/api/erp/expenses'),'Expenses must use scoped SQL APIs');
    }
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

  const names = ['companies','crm-quotes','dashboard', 'users', 'vendors', 'products', 'requests', 'rfqs', 'quotations', 'comparison', 'orders',
    'receipts', 'invoices', 'payments', 'crm-dashboard', 'leads', 'reminders', 'sales', 'customers', 'sales-quotations',
    'erp:credits', 'sales-orders', 'sales-deliveries', 'sales-invoices', 'sales-payments', 'hr-dashboard', 'hr-employees', 'hr-manpower',
    'admin-data', 'hr-recruitment', 'hr-attendance', 'hr-leave', 'hr-payroll', 'hr-separation', 'hr-reports', 'reports', 'activities',
    'erp:overview','erp:approvals','erp:accounting','erp:accounts','erp:journals','erp:reports','erp:aged','erp:bank','erp:inventory','erp:warehouse','erp:stock-moves','erp:manufacturing','erp:production-orders','erp:boms','erp:expenses','erp:expense-claims'];
  for (const name of names) {(await page(name)).window.close();}

  // Existing direct routes still open their native forms.
  for (const route of [
    'rfqs&new=1', 'sales-orders&new=1', 'vendors&new=1', 'customers&new=1',
    'expense-claims&new=1', 'hr-payroll&new=1', 'boms&new=1',
    'inventory&action=adjust', 'warehouse&new=1', 'journals&new=1', 'credits&new=1'
  ]) {
    const screen = await page('erp:' + route);
    await waitFor(() => screen.window.document.querySelector('#workspace-root [role="dialog"]'),
      'Workflow did not open the native form: ' + route);
    screen.window.close();
  }

  // Confirming in the assistant must use the native approval endpoint with the
  // selected version and reason. Opening the preview must not submit a decision.
  const assistantPage = await page('erp:overview');
  const assistantDoc = assistantPage.window.document;
  await waitFor(() => assistantDoc.querySelector('[data-process]'), 'Assistant process picker did not load');
  const approvalCalls = [];
  const persistence = assistantPage.window.eval('BackendPersistence');
  const request = persistence.request;
  persistence.request = async (path, options) => {
    if (path.startsWith('/approvals/requests?')) return {
      enabled: true, pageSize: 25, total: 2,
      items: approvalCalls.length ? [] : [
        {id: 21, label: 'Expense A', amount: '50.00', currency: 'PKR', canDecide: true, version: 'v21'},
        {id: 22, label: 'Expense B', amount: '70.00', currency: 'PKR', canDecide: false, version: 'v22'}
      ]
    };
    if (path.startsWith('/approvals/requests/')) {
      approvalCalls.push({path, options});
      return {approval: {status: 'Approved'}};
    }
    return request(path, options);
  };
  const catalogue = (await request('/assistant/status')).processes;
  assert.deepEqual([...assistantDoc.querySelector('[data-process]').options].slice(1).map(option => option.value),
    catalogue.map(process => process.id), 'Each available assistant workflow needs a chat questionnaire');
  const create = (path, body) => request(path, {
    method: 'POST', body: JSON.stringify({...body, requestKey: 'assistant-smoke-' + Math.random().toString(36).slice(2)}),
  });
  const product = (await create('/products', {name: 'Chat test product', sku: 'CHAT-ERP', rate: 25})).record;
  const vendor = (await create('/vendors', {name: 'Chat test vendor'})).record;
  let purchase = (await create('/trade/requests', {
    department: 'Chat smoke test', items: [{productId: product.id, quantity: 2, rate: 25}],
  })).record;
  for (const action of ['submit', 'approve']) {
    purchase = (await create('/trade/requests/' + purchase.id + '/actions/' + action, {version: purchase.version})).record;
  }
  const composer = assistantDoc.querySelector('[data-chat]');
  const send = async text => {
    composer.elements.question.value = text;
    composer.dispatchEvent(new assistantPage.window.Event('submit', {cancelable: true}));
    await waitFor(() => !composer.querySelector('button').disabled, 'Chat composer remained disabled');
  };
  const latest = () => [...assistantDoc.querySelectorAll('.erp-ai-message--assistant')].at(-1).textContent;
  await send('RFQ banani hai');
  assert.match(latest(), /Approved purchase request/);
  await send(purchase.requestNo);
  assert.match(latest(), new RegExp(purchase.requestNo));
  await send('1');
  assert.match(latest(), /How many vendor/);
  await send('1');
  await send(vendor.name);
  assert.match(latest(), /Chat test vendor/);
  await send('1');
  await send('2027-02-30');
  assert.match(latest(), /valid date/);
  await send('2099-12-31');
  await send('Skip');
  assert.match(assistantDoc.querySelector('[data-workflow-review]').textContent, /Chat test vendor/);
  assert.equal(assistantDoc.querySelector('[data-open-process], #workspace-root [role="dialog"]'), null);
  assert.equal((await request('/trade/rfqs')).total, 0);
  await send('Confirm');
  assert.match(latest(), /Saved in ERP/);
  assert.equal((await request('/trade/rfqs')).total, 1);
  await send('Confirm');
  assert.equal((await request('/trade/rfqs')).total, 1);

  await send('Send RFQ');
  assert.match(latest(), /Draft RFQ/);
  await send('List');
  await send('1');
  assert.match(latest(), /Confirm to submit/);
  assert.equal((await request('/trade/rfqs')).items[0].status, 'Draft');
  await send('Confirm');
  assert.equal((await request('/trade/rfqs')).items[0].status, 'Sent');

  await send('Record supplier quotation');
  await send('List');
  await send('1');
  assert.match(latest(), /Chat test vendor/);
  await send('1');
  await send('Today');
  await send('2099-12-31');
  await send('Skip');
  await send('Skip');
  assert.match(latest(), /Chat test product \(2\).*Vendor unit rate/);
  await send('30');
  await send('Skip');
  await send('Skip');
  await send('Skip');
  assert.match(latest(), /Confirm to submit/);
  await send('Confirm');
  assert.equal((await request('/trade/quotations')).items[0].total, 60);

  await send('Create expense claim');
  await send('Test cancelled draft');
  await send('Cancel');
  assert.match(latest(), /Draft cancelled/);
  assert.equal((await request('/expenses/claims')).total, 0);

  // The standard transport retains the assistant on the same page on a 202.
  const originalFetch = assistantPage.window.fetch;
  assistantPage.window.fetch = (url, options) => {
    if (url === '/api/expenses/commands/create') {
      return Promise.resolve(new Response(JSON.stringify({
        approvalPending: true, approval: {id: 55}, message: 'Submitted for independent approval.',
      }), {status: 202}));
    }
    return originalFetch(url, options);
  };
  await send('Create expense claim');
  await send('Test queued action');
  await send('Today');
  await send('List');
  await send('1');
  await send('25');
  await send('0');
  assert.match(latest(), /Confirm to submit/);
  await send('Confirm');
  assert.match(latest(), /Submitted for independent approval.*Approval #55/s);
  assert.equal(assistantPage.window.location.search, '?view=overview');
  assistantPage.window.fetch = originalFetch;

  await send('Show pending approvals');
  await send('List');
  assert.match(latest(), /Expense A/);
  assert.doesNotMatch(latest(), /Expense B/);
  await send('1');
  await send('Approve');
  await send('Verified receipt');
  assert.match(latest(), /Confirm to submit/);
  assert.equal(approvalCalls.length, 0);
  await send('Confirm');
  assert.equal(approvalCalls.length, 1);
  assert.equal(approvalCalls[0].path, '/approvals/requests/21/approve');
  assert.deepEqual(JSON.parse(approvalCalls[0].options.body), {version: 'v21', reason: 'Verified receipt'});
  assert.equal(approvalCalls[0].options.keepApprovalInChat, true);
  const customer = (await create('/customers', {name: 'Chat order customer'})).customer;
  const customerSearches = [];
  const assistantRequest = persistence.request;
  persistence.request = (path, options) => {
    if (path.startsWith('/customers?')) customerSearches.push(path);
    return assistantRequest(path, options);
  };
  await send('aik new lead generate karni he');
  assert.match(latest(), /Which existing customer/);
  await send('kya batao customer name?');
  assert.match(latest(), /Type just the customer name/);
  assert.equal(customerSearches.length, 0);
  await send('Unlisted chat customer');
  assert.match(latest(), /No saved customer matched.*Add customer/s);
  await send('Chat order customer');
  assert.match(latest(), /1\. .*Chat order customer/);
  await send('1');
  assert.match(latest(), /Contact person/);
  await send('Cancel');
  persistence.request = assistantRequest;

  const service = (await create('/products', {name: 'Chat order service', productType: 'service', unit: 'Service'})).record;
  let quotation = (await create('/trade/salesQuotations', {
    customerId: customer.id, items: [{productId: service.id, quantity: 1, rate: 100}],
  })).record;
  for (const action of ['submit', 'approve', 'send', 'accept']) {
    quotation = (await create('/trade/salesQuotations/' + quotation.id + '/actions/' + action,
      {version: quotation.version})).record;
  }
  await send('Create sales order');
  assert.match(latest(), /Accepted sales quotation/);
  await send(quotation.quotationNo);
  await send('1');
  await send('Today');
  await send('Skip');
  assert.match(latest(), /Chat order customer/);
  assert.equal((await request('/trade/salesOrders')).total, 0);
  await send('Confirm');
  assert.equal(String((await request('/trade/salesOrders')).items[0].quotationId), String(quotation.id));
  assistantPage.window.close();

  let profilePage=await page('sales');
  assert.equal(profilePage.window.document.querySelectorAll('#user-dropdown button[data-action="company-profile"]').length,1);
  await profilePage.window.openCompanyProfile();
  await waitFor(()=>profilePage.window.document.getElementById('profile-name'),'Company profile opens outside ERP overview');
  profilePage.window.close();
  const userSetup=await page('users');
  const adminRequest=userSetup.window.eval('BackendPersistence.request');
  const teamUser=(await adminRequest('/administration/commands/create-user',{method:'POST',body:JSON.stringify({requestKey:'admin-dom-procurement',name:'Procurement team user',email:'procurement-team@example.test',password,role:'Procurement Staff',managerId:userSetup.window.currentUser().id,active:true})})).record;
  assert.equal(teamUser.managerId,userSetup.window.currentUser().id);
  const assignedSeller=(await adminRequest('/administration/commands/create-user',{method:'POST',body:JSON.stringify({requestKey:'admin-dom-seller',name:'Assigned seller',email:'assigned-seller@example.test',password,role:'Salesperson',managerId:userSetup.window.currentUser().id,active:true})})).record;
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
  // Operational registers belong to Inventory; financial registers belong to Accounting.
  for (const [view, module] of [['sales-invoices','accounting'],['sales-payments','accounting'],['invoices','accounting'],['payments','accounting'],['receipts','inventory'],['sales-deliveries','inventory']]) {
    const screen=await page(view);
    assert.equal(screen.window.document.querySelector('.module-app').dataset.module,module);
    screen.window.close();
  }
  for (const view of ['sales','purchase-dashboard']) {
    const screen=await page(view);
    const hrefs=[...screen.window.document.querySelectorAll('.module-tabs a')].map(a=>a.href);
    assert.ok(!hrefs.some(h=>/view=(sales-invoices|sales-payments|invoices|payments|receipts|sales-deliveries)(&|$)/.test(h)));
    screen.window.close();
  }
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

  await require('./expense-dom.cjs')({page,assert});

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
  assert.equal(dom.window.document.querySelectorAll('.sidebar [data-workspace="hr"],.sidebar [data-workspace="manufacturing"]').length,0);
  assert.equal(dom.window.document.querySelector('.module-tabs [aria-current="page"]').textContent,'Quotations');
  assert.equal(dom.window.document.querySelectorAll('#user-dropdown button[data-action="company-profile"]').length,0);
  dom.window.close();
  dom=await page('activities');
  assert.deepEqual([...dom.window.document.querySelectorAll('.module-tab')].map(e=>e.textContent),['Activity Log']);
  dom.window.close();
  jar.setCookieSync(login.headers.get('set-cookie'),base);

  assert.deepEqual(errors, []);
  console.log(`${names.length} pages/views rendered with shared module navigation; active tabs, module context and restricted roles passed; native Overview/CRM registers/Administration/Expenses/Production/Inventory/Finance/Sales/Purchasing/HR API and React read models, manufacturing and expense flows passed.`);
}

main().catch(error => {console.error(error); process.exitCode = 1;}).finally(() => {
  if (server) server.kill();
  fs.rmSync(temp, {recursive: true, force: true});
});
