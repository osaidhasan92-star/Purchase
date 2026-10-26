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
    const console = new VirtualConsole();
    console.on('jsdomError', error => {
      if (!error.message.includes('Could not load') && !error.message.includes('CSS') && !error.message.includes('navigation')) errors.push(name + ': ' + error.message);
    });
    const dom = await JSDOM.fromURL(base + '/' + name + '.html', {
      cookieJar: jar, runScripts: 'dangerously', resources: new LocalResources(), pretendToBeVisual: true, virtualConsole: console,
      beforeParse(window) {
        window.structuredClone = structuredClone;
        window.Headers = Headers;
        window.fetch = (url, options = {}) => fetch(new URL(url, window.location.href), {
          ...options, headers: {...Object.fromEntries(new Headers(options.headers || {})), Cookie: jar.getCookieStringSync(base)}
        });
        window.HTMLElement.prototype.scrollIntoView = function() {};
        window.matchMedia = () => ({matches: false, addEventListener() {}, removeEventListener() {}});
      }
    });
    await waitFor(() => dom.window.document.querySelector('.sidebar'), 'No sidebar on ' + name);
    return dom;
  }

  const names = ['dashboard', 'users', 'vendors', 'products', 'requests', 'rfqs', 'quotations', 'comparison', 'orders',
    'receipts', 'invoices', 'payments', 'crm-dashboard', 'leads', 'reminders', 'sales', 'customers', 'sales-quotations',
    'sales-orders', 'sales-deliveries', 'sales-invoices', 'sales-payments', 'hr-dashboard', 'hr-employees', 'hr-manpower',
    'hr-recruitment', 'hr-attendance', 'hr-leave', 'hr-payroll', 'hr-separation', 'hr-reports', 'settings', 'reports', 'activities'];
  for (const name of names) {(await page(name)).window.close();}
  let dom = await page('vendors');
  dom.window.openVendor();
  dom.window.document.getElementById('vname').value = 'Persisted through the interface';
  await dom.window.saveVendor();
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
  assert.equal(dom.window.eval('db().leads[0].stage'), 'Quotation Approved');
  await dom.window.sendSalesQuotationToCustomer(quoteId);
  await dom.window.acceptSalesQuotation(quoteId);
  assert.equal(dom.window.eval('db().leads[0].stage'), 'Closed Won');
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
  dom = await page('sales-payments');
  assert.equal(dom.window.eval('db().customerInvoices[0].paidAmount'), 40);
  assert.equal(dom.window.eval('db().customerInvoices[0].status'), 'Partially Paid');
  dom.window.close();

  assert.deepEqual(errors, []);
  console.log(`${names.length} pages rendered; vendor/HR persistence and sales approval → CRM sync → order → invoice → partial payment passed; no script errors.`);
}

main().catch(error => {console.error(error); process.exitCode = 1;}).finally(() => {
  if (server) server.kill();
  fs.rmSync(temp, {recursive: true, force: true});
});
