const API_BASE = window.API_BASE || '/api';
let APP_STATE = null;
let APP_STATE_LOADING = null;
let CURRENT_USER = null;

// Demo mode: this static frontend keeps its data in the current browser.
const DEMO_STATE_KEY = 'purchase_demo_state_v1';
const DEMO_USERS_KEY = 'purchase_demo_users_v1';
const DEMO_SESSION_KEY = 'purchase_demo_session_v1';
function createDemoState(){return {vendors:[{id:1,name:'Gulf Office Supplies LLC',trn:'100123456700003',contact:'Sara Khan',phone:'+971 4 555 0101',email:'sales@gulfoffice.example',category:'Office Supplies',status:'Active'},{id:2,name:'TechSource Middle East',trn:'100987654300003',contact:'Omar Ali',phone:'+971 4 555 0102',email:'orders@techsource.example',category:'IT Equipment',status:'Active'}],products:[{id:1,name:'Laptop Computer',sku:'IT-LAP-001',category:'IT Equipment',unit:'Each',rate:3500,status:'Active'},{id:2,name:'A4 Copier Paper',sku:'OFF-PAP-001',category:'Office Supplies',unit:'Box',rate:18,status:'Active'},{id:3,name:'Printer Toner',sku:'OFF-TON-001',category:'Office Supplies',unit:'Each',rate:280,status:'Active'}],requests:[],rfqs:[],quotations:[],comparisons:[],orders:[],receipts:[],invoices:[],payments:[],users:[{id:'demo-admin',name:'Demo Administrator',email:'admin@purchase.local',role:'Admin',active:true}],roles:null,activities:[]}}
function demoRead(key,fallback){try{const value=localStorage.getItem(key);return value?JSON.parse(value):fallback}catch(_){return fallback}}
function demoWrite(key,value){localStorage.setItem(key,JSON.stringify(value))}
function demoState(){const state=demoRead(DEMO_STATE_KEY,null)||createDemoState();if(!state.roles)state.roles=defaultRoles();demoWrite(DEMO_STATE_KEY,state);return state}
function demoUsers(){const users=demoRead(DEMO_USERS_KEY,null)||[{id:'demo-admin',name:'Demo Administrator',email:'admin@purchase.local',password:'Demo@123',role:'Admin',active:true}];demoWrite(DEMO_USERS_KEY,users);return users}

// Company configuration is stored in the frontend demo state for now.
// Backend integration will move this configuration to a tenant/company table.
const DEFAULT_COMPANY_SETTINGS = {
  name:'Demo Company LLC', legalName:'Demo Company LLC', country:'United Arab Emirates', address:'', phone:'', email:'', website:'', taxNumber:'', taxNumberLabel:'Tax Registration Number',
  currency:'PKR', currencySymbol:'Rs', currencyLocale:'en-PK', logo:'',
  purchaseTax:{enabled:true,label:'VAT',rate:5},
  salesTax:{enabled:true,label:'VAT',rate:5}
};
function companySettings(){
  const x=APP_STATE||{};
  if(!x.company) x.company=structuredClone(DEFAULT_COMPANY_SETTINGS);
  x.company={...structuredClone(DEFAULT_COMPANY_SETTINGS),...(x.company||{}),purchaseTax:{...DEFAULT_COMPANY_SETTINGS.purchaseTax,...(x.company?.purchaseTax||{})},salesTax:{...DEFAULT_COMPANY_SETTINGS.salesTax,...(x.company?.salesTax||{})}};
  if(x.company.currency==='A'+'E'+'D'||x.company.currencySymbol==='A'+'E'+'D'){x.company.currency='PKR';x.company.currencySymbol='Rs';x.company.currencyLocale='en-PK';}
  return x.company;
}
function purchaseTaxLabel(){const c=companySettings();return c.purchaseTax?.enabled===false?'Tax':(c.purchaseTax?.label||'Tax');}
function purchaseTaxRate(){const c=companySettings();return Number(c.purchaseTax?.enabled===false?0:(c.purchaseTax?.rate??0));}
function salesTaxLabel(){const c=companySettings();return c.salesTax?.enabled===false?'Tax':(c.salesTax?.label||'Tax');}
function salesTaxRate(){const c=companySettings();return Number(c.salesTax?.enabled===false?0:(c.salesTax?.rate??0));}
function companyTaxNumber(){const c=companySettings();return c.taxNumber||'—';}
function companyTaxLabel(){const c=companySettings();return c.taxNumberLabel||'Tax Registration Number';}
function companyCurrency(){const c=companySettings();return c.currencySymbol||c.currency||'';}
function defaultPOTerms(){const c=companySettings(),tax=purchaseTaxLabel(),country=c.country||'the applicable jurisdiction';return `1. Acceptance of Order This purchase order constitutes an offer to purchase the goods/services listed herein, subject to these terms. Acceptance by delivery, invoice, or written confirmation constitutes agreement to the stated terms. Any variation to price, quantity, or specification requires prior written approval.
2. Pricing Prices stated are fixed and firm unless otherwise agreed in writing. ${tax} must be shown separately where applicable under the laws of ${country}. No price escalation is permitted without prior written consent.
3. Delivery Goods/services must be delivered to the specified location, date, and time stated on this order. The Supplier must notify the Purchaser immediately of any anticipated delay.
4. Late Delivery / Penalty In case of delay not attributable to Force Majeure, the Purchaser reserves the right to apply an agreed penalty, cancel the order, and/or source alternatively at the Supplier's cost where permitted.
5. Inspection & Quality All goods are subject to inspection and testing upon receipt. Non-conforming goods may be rejected and must be replaced or corrected at no additional cost within an agreed timeframe.
6. Invoicing & Payment Invoices must reference the purchase order number, include the Purchaser's ${companyTaxLabel()}, and itemize applicable ${tax} separately. Payment terms are as specified on the purchase order.
7. Warranty The Supplier warrants that all goods/services are fit for the intended purpose and covered by the agreed warranty terms.
8. Compliance with Applicable Law The Supplier shall comply with all applicable laws, regulations, tax requirements, health and safety requirements, customs requirements, and environmental rules in ${country}.
9. Confidentiality The Supplier shall treat information relating to this order, pricing, and the Purchaser's business as confidential.
10. Insurance & Liability The Supplier shall maintain adequate insurance as applicable and indemnify the Purchaser against losses arising from defective goods or negligent performance.
11. Force Majeure Neither party shall be liable for delay or failure to perform due to circumstances beyond reasonable control, provided the affected party notifies the other promptly and mitigates the impact.`;}
function vendorRecord(x,id){return (x.vendors||[]).find(v=>String(v.id)===String(id));}
function vendorTRN(x,record){return record?.vendorTRN||record?.vendorTrn||record?.trn||vendorRecord(x,record?.vendorId)?.trn||((x.vendors||[]).find(v=>v.name===record?.vendorName)?.trn)||'';}

const api=async(path,options={})=>{const method=(options.method||'GET').toUpperCase(),body=typeof options.body==='string'?JSON.parse(options.body||'{}'):(options.body||{}),session=demoRead(DEMO_SESSION_KEY,null),users=demoUsers(),publicUser=u=>u&&({id:u.id,name:u.name,email:u.email,role:u.role,managerId:u.managerId||null,active:u.active!==false}),requireUser=()=>{const u=users.find(u=>String(u.id)===String(session?.userId)&&u.active!==false);if(!u)throw new Error('Your session has expired. Please sign in again.');return u};if(path==='/auth/login'&&method==='POST'){const u=users.find(u=>u.email.toLowerCase()===String(body.email||'').toLowerCase()&&u.password===body.password&&u.active!==false);if(!u)throw new Error('Invalid email or password');demoWrite(DEMO_SESSION_KEY,{userId:u.id});return {user:publicUser(u)}}if(path==='/auth/logout'){localStorage.removeItem(DEMO_SESSION_KEY);return {ok:true}}if(path==='/auth/me')return {user:publicUser(requireUser())};if(path==='/auth/change-password'&&method==='POST'){const u=requireUser();if(u.password!==body.currentPassword)throw new Error('Current password is incorrect');if(body.newPassword!==body.confirmPassword||String(body.newPassword||'').length<8)throw new Error('Enter a matching password of at least 8 characters');u.password=body.newPassword;demoWrite(DEMO_USERS_KEY,users);return {ok:true}}if(path==='/state'&&method==='GET'){requireUser();return demoState()}if(path==='/state'&&method==='PUT'){requireUser();demoWrite(DEMO_STATE_KEY,body);return {state:body}}requireUser();const match=path.match(/^\/users(?:\/([^/]+))?(?:\/password)?$/);if(match){const id=match[1],passwordRoute=path.endsWith('/password');let u=id&&users.find(u=>String(u.id)===String(id));if(method==='POST'&&!id){if(users.some(u=>u.email.toLowerCase()===String(body.email||'').toLowerCase()))throw new Error('A user with this email already exists');u={id:'user-'+Date.now(),name:body.name,email:String(body.email).toLowerCase(),password:body.password,role:body.role,managerId:body.managerId||null,active:body.active!==false};users.push(u)}else if(!u)throw new Error('User not found');else if(passwordRoute&&method==='POST')u.password=body.password;else if(method==='PUT'){Object.assign(u,{name:body.name,email:String(body.email).toLowerCase(),role:body.role,managerId:body.managerId||null,active:body.active!==false});if(body.password)u.password=body.password}demoWrite(DEMO_USERS_KEY,users);return publicUser(u)}throw new Error(`Demo API route not available: ${path}`)};

function db() {
  if (!APP_STATE) {
    APP_STATE = createDemoState();
    APP_STATE.roles = defaultRoles();
  }

  if (!Array.isArray(APP_STATE.comparisons)) APP_STATE.comparisons = [];
  companySettings();
  if (!Array.isArray(APP_STATE.companies)) APP_STATE.companies = [{id:101,name:'Al Noor Facilities',industry:'Facilities Management',contact:'Fatima Ahmed',email:'fatima@alnoor.example',phone:'+971 4 555 1101',status:'Active'},{id:102,name:'Crescent Retail Group',industry:'Retail',contact:'Daniel Wong',email:'daniel@crescent.example',phone:'+971 4 555 1102',status:'Active'}];
  if (!Array.isArray(APP_STATE.customers)) APP_STATE.customers=(APP_STATE.companies||[]).map((c,i)=>({id:c.id,code:'CUS-'+String(i+1).padStart(3,'0'),name:c.name,contact:c.contact||'',phone:c.phone||'',email:c.email||'',address:c.address||'',category:c.industry||'',paymentTerms:'Cash',creditLimit:0,status:c.status||'Active'}));
  if (!Array.isArray(APP_STATE.leads)) APP_STATE.leads = [{id:201,companyId:101,companyName:'Al Noor Facilities',contact:'Fatima Ahmed',email:'fatima@alnoor.example',stage:'Proposal Sent',value:85000,currency:'PKR',source:'Referral',expectedClose:'2026-10-15',notes:'Awaiting board review.',status:'Active'},{id:202,companyId:102,companyName:'Crescent Retail Group',contact:'Daniel Wong',email:'daniel@crescent.example',stage:'Demo',value:42000,currency:'PKR',source:'Website',expectedClose:'2026-11-01',notes:'Product demonstration scheduled.',status:'Active'}];
  APP_STATE.leads.forEach(l=>{if(l.customerId==null&&l.companyId!=null)l.customerId=l.companyId;if(!l.customerName&&l.companyName)l.customerName=l.companyName;if(!l.ownerId)l.ownerId=l.createdBy||null;if(!l.managerId&&l.ownerId){const ou=(APP_STATE.users||[]).find(u=>String(u.id)===String(l.ownerId));if(ou?.managerId)l.managerId=ou.managerId;}});
  if (!Array.isArray(APP_STATE.crmQuotes)) APP_STATE.crmQuotes = [{id:301,quoteNo:'CRM-Q-2026-001',leadId:201,companyName:'Al Noor Facilities',amount:85000,currency:'PKR',quoteDate:'2026-09-15',validUntil:'2026-10-15',status:'Sent'}];
  if (!Array.isArray(APP_STATE.reminders)) APP_STATE.reminders = [{id:401,leadId:201,leadName:'Al Noor Facilities',type:'Call',dueDate:'2026-09-22',notes:'Follow up on proposal approval.',done:false}];
  if (!Array.isArray(APP_STATE.activities)) APP_STATE.activities = [];
  APP_STATE.activities = APP_STATE.activities.filter(a => a.action !== 'Viewed');
  if (!Array.isArray(APP_STATE.users)) APP_STATE.users = [];
  if (!APP_STATE.roles) APP_STATE.roles = defaultRoles();
  const defaultRoleSet = defaultRoles();
  Object.keys(defaultRoleSet).forEach(role => {
    if (!APP_STATE.roles[role]) APP_STATE.roles[role] = structuredClone(defaultRoleSet[role]);
    else Object.keys(defaultRoleSet[role]).forEach(permission => {
      if (APP_STATE.roles[role][permission] === undefined) APP_STATE.roles[role][permission] = defaultRoleSet[role][permission];
    });
  });

  Object.keys(APP_STATE.roles || {}).forEach(role => {
    APP_STATE.roles[role].activities = true;
  });
  const crmPermissions={Admin:{leads:true,companies:true,crmQuotes:true,reminders:true},'Procurement Manager':{leads:true,companies:true,crmQuotes:true,reminders:true},Requester:{leads:true,companies:true,crmQuotes:false,reminders:true},'Procurement Staff':{leads:true,companies:true,crmQuotes:true,reminders:true},Finance:{leads:false,companies:true,crmQuotes:false,reminders:false},Viewer:{leads:true,companies:true,crmQuotes:true,reminders:true}};
  Object.entries(crmPermissions).forEach(([role,permissions])=>Object.entries(permissions).forEach(([module,allowed])=>{if(APP_STATE.roles[role][module]===undefined)APP_STATE.roles[role][module]=allowed}));
  const crmRoleTemplates={
    'CRM Manager':{dashboard:false,requests:false,rfqs:false,quotations:false,comparison:false,orders:false,receipts:false,invoices:false,payments:false,vendors:false,products:false,reports:true,users:false,activities:true,leads:true,companies:true,crmQuotes:true,reminders:true},
    'Sales Manager':{dashboard:false,requests:false,rfqs:false,quotations:false,comparison:false,orders:false,receipts:false,invoices:false,payments:false,vendors:false,products:false,reports:true,users:false,activities:true,leads:true,companies:true,crmQuotes:true,reminders:true},
    'Sales Representative':{dashboard:false,requests:false,rfqs:false,quotations:false,comparison:false,orders:false,receipts:false,invoices:false,payments:false,vendors:false,products:false,reports:false,users:false,activities:true,leads:true,companies:true,crmQuotes:false,reminders:true},
    'Quote Manager':{dashboard:false,requests:false,rfqs:false,quotations:false,comparison:false,orders:false,receipts:false,invoices:false,payments:false,vendors:false,products:false,reports:true,users:false,activities:true,leads:true,companies:true,crmQuotes:true,reminders:false}
  };
  Object.entries(crmRoleTemplates).forEach(([role,permissions])=>{if(!APP_STATE.roles[role])APP_STATE.roles[role]=permissions});
  Object.keys(APP_STATE.roles).forEach(role=>normalizeRolePermissions(role,APP_STATE.roles[role]));
  if(!APP_STATE.roles['Sales Manager']) APP_STATE.roles['Sales Manager']={dashboard:false,requests:false,rfqs:false,quotations:false,comparison:false,orders:false,receipts:false,invoices:false,payments:false,vendors:false,products:true,reports:true,users:false,activities:true,settings:false,leads:true,reminders:true,sales:true,sales_customers:true,sales_quotations:true,sales_orders:true,sales_deliveries:true,sales_invoices:true,sales_payments:true};
  if(!APP_STATE.roles['Salesperson']) APP_STATE.roles['Salesperson']={dashboard:false,requests:false,rfqs:false,quotations:false,comparison:false,orders:false,receipts:false,invoices:false,payments:false,vendors:false,products:true,reports:false,users:false,activities:true,settings:false,leads:true,reminders:true,sales:true,sales_customers:true,sales_quotations:true,sales_orders:true,sales_deliveries:true,sales_invoices:false,sales_payments:false};

  return APP_STATE;
}

async function initAppState() {
  if (APP_STATE_LOADING) return APP_STATE_LOADING;

  APP_STATE_LOADING = (async () => {
    try {
      const t0 = performance.now();
      const me = await api('/auth/me');
      console.log('[LOAD] /auth/me:', Math.round(performance.now() - t0), 'ms');
      const browserSession = sessionStorage.getItem('purchase_browser_session');

      // A persisted demo login may be restored in a new browser tab/session.
      if (!browserSession) sessionStorage.setItem('purchase_browser_session', 'active');

      CURRENT_USER = me.user;

      const t1 = performance.now();
      const data = await api('/state');
      console.log('[LOAD] /state:', Math.round(performance.now() - t1), 'ms');
      APP_STATE = data;

      // Normalize the loaded state once, after the persisted LocalStorage state
      // is available. This makes visiting any module safe even when an older
      // saved state is missing a newer array/setting. Never build a fresh state
      // on top of persisted data during page/module navigation.
      db();
      demoWrite(DEMO_STATE_KEY, APP_STATE);

      console.log('[LOAD] total init:', Math.round(performance.now() - t0), 'ms');
      return APP_STATE;
    } catch (error) {
      console.error('Unable to load application state:', error);
      toast(error.message || 'Unable to connect to the server');
      return null;
    }
  })();

  return APP_STATE_LOADING;
}

let APP_STATE_SAVE = Promise.resolve();

async function persistState() {
  if (!APP_STATE) return;

  try {
    const response = await api('/state', {
      method: 'PUT',
      body: JSON.stringify(APP_STATE)
    });

    if (response?.state) APP_STATE = response.state;
  } catch (error) {
    console.error('Unable to save application state:', error);
    toast(`Save failed: ${error.message}`);
  }
}

function defaultRoles(){return {Admin:{dashboard:true,requests:true,rfqs:true,quotations:true,comparison:true,orders:true,receipts:true,invoices:true,payments:true,vendors:true,products:true,reports:true,users:true,activities:true,settings:true,sales:true,sales_customers:true,sales_quotations:true,sales_orders:true,sales_deliveries:true,sales_invoices:true,sales_payments:true},'Procurement Manager':{dashboard:true,requests:true,rfqs:true,quotations:true,comparison:true,orders:true,receipts:true,invoices:false,payments:false,vendors:true,products:true,reports:true,users:false,activities:true,settings:false,sales:false,sales_customers:false,sales_quotations:false,sales_orders:false,sales_deliveries:false,sales_invoices:false,sales_payments:false},Requester:{dashboard:true,requests:true,rfqs:false,quotations:false,comparison:false,orders:false,receipts:false,invoices:false,payments:false,vendors:false,products:true,reports:false,users:false,activities:true,settings:false,sales:false,sales_customers:false,sales_quotations:false,sales_orders:false,sales_deliveries:false,sales_invoices:false,sales_payments:false},'Procurement Staff':{dashboard:true,requests:true,rfqs:true,quotations:true,comparison:true,orders:true,receipts:true,invoices:false,payments:false,vendors:true,products:true,reports:true,users:false,activities:true,settings:false,sales:false,sales_customers:false,sales_quotations:false,sales_orders:false,sales_deliveries:false,sales_invoices:false,sales_payments:false},Finance:{dashboard:true,requests:false,rfqs:false,quotations:false,comparison:false,orders:false,receipts:true,invoices:true,payments:true,vendors:true,products:false,reports:true,users:false,activities:true,settings:false,sales:false,sales_customers:false,sales_quotations:false,sales_orders:false,sales_deliveries:false,sales_invoices:false,sales_payments:false},Viewer:{dashboard:true,requests:true,rfqs:true,quotations:true,comparison:true,orders:true,receipts:true,invoices:true,payments:true,vendors:true,products:true,reports:true,users:false,activities:true,settings:false,sales:false,sales_customers:false,sales_quotations:false,sales_orders:false,sales_deliveries:false,sales_invoices:false,sales_payments:false}}}
const PERMISSION_ACTIONS=['view','create','edit','delete','approve','export'];
const PERMISSION_LABELS={view:'View',create:'Create',edit:'Edit',delete:'Delete',approve:'Approve',export:'Export'};
const PERMISSION_MODULES={dashboard:'Dashboard',requests:'Purchase Requests',rfqs:'RFQs',quotations:'Vendor Quotations',comparison:'Quotation Comparison',orders:'Purchase Orders',receipts:'Goods Receipts',invoices:'Vendor Invoices',payments:'Payments',vendors:'Vendors',products:'Products',reports:'Reports',users:'User Management',activities:'Activities',settings:'Company Settings',leads:'CRM Leads',reminders:'CRM Reminders',sales:'Sales Dashboard',sales_customers:'Customers',sales_quotations:'Sales Quotations',sales_orders:'Sales Orders',sales_deliveries:'Sales Deliveries',sales_invoices:'Customer Invoices',sales_payments:'Customer Payments'};
function currentUser(){return CURRENT_USER}
function roleActionDefaults(role,module,enabled){
  if(!enabled)return {view:false,create:false,edit:false,delete:false,approve:false,export:false};
  if(role==='Admin')return {view:true,create:true,edit:true,delete:true,approve:true,export:true};
  if(role==='Viewer')return {view:true,create:false,edit:false,delete:false,approve:false,export:true};
  const manager=['Procurement Manager','CRM Manager','Sales Manager','Quote Manager','Finance'].includes(role);
  const requester=role==='Requester';
  return {view:true,create:!requester,edit:!requester,delete:false,approve:manager && role!=='CRM Manager',export:true};
}
function normalizeRolePermissions(role,legacy){
  legacy=legacy||{};
  if(!legacy.permissions)legacy.permissions={};
  Object.keys(PERMISSION_MODULES).forEach(module=>{
    const enabled=legacy[module]===true || legacy.permissions[module]?.view===true;
    legacy.permissions[module]={...roleActionDefaults(role,module,enabled),...(legacy.permissions[module]||{})};
    legacy[module]=!!legacy.permissions[module].view;
  });
  return legacy;
}
function can(id,action='view'){
  const u=currentUser(),x=db(),role=u&&u.role&&x.roles&&x.roles[u.role];
  if(!role)return false;
  if(role.permissions?.[id] && typeof role.permissions[id][action] !== 'undefined')return !!role.permissions[id][action];
  return action==='view' ? role[id]===true : false;
}
function guard(id){need();if(id&&!can(id,'view')){toast('You do not have permission to access this module');setTimeout(()=>location.href='dashboard.html',500);return false}return true}
function guardAction(module,action='view'){need();if(!can(module,action)){toast('You do not have permission to '+(PERMISSION_LABELS[action]||action)+' this module');return false}return true}
function recordActivity(x,action,module,details='',entity=''){
  x.activities=x.activities||[];
  const u=currentUser()||{name:'System',email:'system',role:'System'};
  x.activities.unshift({id:Date.now()+Math.random(),userId:u.id||null,userName:u.name||'System',userEmail:u.email||'',role:u.role||'',action,module,details,entity,createdAt:new Date().toISOString()});
  if(x.activities.length>2000)x.activities=x.activities.slice(0,2000);
}
function logActivity(action,module,details='',entity=''){const x=db();recordActivity(x,action,module,details,entity);save(x)}
function save(x){
  // Browser demo mode: LocalStorage is the single source of truth.
  // IMPORTANT: do not queue an asynchronous /state PUT here. A delayed PUT can
  // race with another page's initialization and overwrite a newer state with an
  // older snapshot. Every mutation is therefore committed synchronously before
  // the UI navigates or re-renders.
  APP_STATE=x;
  try {
    demoWrite(DEMO_STATE_KEY, APP_STATE);
    APP_STATE_SAVE=Promise.resolve();
  } catch (error) {
    console.error('Unable to persist local state:', error);
    toast('Save failed: '+(error.message||'Unable to save data'));
  }
} function esc(x=''){return String(x).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))} function toast(m){const t=document.getElementById('toast')||document.body.appendChild(Object.assign(document.createElement('div'),{id:'toast'}));t.className='toast show';t.textContent=m;setTimeout(()=>t.classList.remove('show'),2500)}
function layout(active,title,sub,body){const isDashboard=['dashboard','purchase-dashboard','crm-dashboard','sales','hr-dashboard'].includes(active);document.body.innerHTML=`<div class="app"><aside class="sidebar" id="side"><div class="side-brand"><img src="${esc('logo.png')}" alt="${esc(companySettings().name||'Company')}"></div><div class="sidebar-scroll">${currentUser()?.role==='Admin'&&can('dashboard')?'<div class="nav-title">MAIN</div>'+nav('dashboard','Executive Dashboard','ti-dashboard',active):''}<div class="nav-title">CRM</div>${can('leads')?nav('crm-dashboard','CRM Dashboard','ti-layout-dashboard',active):''}${can('leads')?nav('leads','Leads','ti-users',active):''}${can('reminders')?nav('reminders','Reminders','ti-bell',active):''}<div class="nav-title">SALES</div>${can('sales')?nav('sales','Sales Dashboard','ti-chart-line',active):''}${can('sales_quotations')?nav('sales-quotations','Sales Quotations','ti-file-dollar',active):''}${can('sales_orders')?nav('sales-orders','Sales Orders','ti-shopping-cart',active):''}${can('sales_deliveries')?nav('sales-deliveries','Deliveries','ti-truck-delivery',active):''}${can('sales_invoices')?nav('sales-invoices','Customer Invoices','ti-receipt',active):''}${can('sales_payments')?nav('sales-payments','Customer Payments','ti-credit-card',active):''}<div class="nav-title">PURCHASING</div>${can('dashboard')?(currentUser()?.role==='Admin'?nav('purchase-dashboard','Purchase Dashboard','ti-layout-dashboard',active):nav('dashboard','Dashboard','ti-layout-dashboard',active)):''}${can('requests')?nav('requests','Purchase Requests','ti-file-invoice',active):''}${can('rfqs')?nav('rfqs','RFQs','ti-file-description',active):''}${can('quotations')?nav('quotations','Vendor Quotations','ti-file-dollar',active):''}${can('comparison')?nav('comparison','Quotation Comparison','ti-scale',active):''}${can('orders')?nav('orders','Purchase Orders','ti-shopping-cart',active):''}${can('receipts')?nav('receipts','Goods Receipts','ti-package',active):''}${can('invoices')?nav('invoices','Vendor Invoices','ti-receipt',active):''}${can('payments')?nav('payments','Payments','ti-credit-card',active):''}<div class="nav-title">Human Resources</div>${nav('hr-dashboard','HR Dashboard','ti-users',active)}${nav('hr-employees','Employees','ti-id-badge',active)}${nav('hr-manpower','Manpower Requests','ti-user-plus',active)}${nav('hr-recruitment','Recruitment','ti-clipboard-list',active)}${nav('hr-attendance','Attendance','ti-calendar-check',active)}${nav('hr-leave','Leave Management','ti-calendar-time',active)}${nav('hr-payroll','Payroll','ti-wallet',active)}${nav('hr-separation','Separation & Settlement','ti-user-x',active)}${nav('hr-reports','HR Reports','ti-chart-bar',active)}<div class="nav-title">MASTER DATA</div>${can('sales_customers')?nav('customers','Customers','ti-users',active):''}${can('vendors')?nav('vendors','Vendors','ti-building-store',active):''}${can('products')?nav('products','Products','ti-box',active):''}${can('users')?nav('users','User & Role Management','ti-users',active):''}${can('settings')?nav('settings','Company Settings','ti-settings',active):''}<div class="nav-title">REPORTS</div>${can('reports')?nav('reports','Reports','ti-chart-bar',active):''}${can('activities')?nav('activities','Activities','ti-activity',active):''}</div></aside><main class="main"><header class="top${isDashboard?' dashboard-top':''}"><button class="mobile-menu" onclick="document.getElementById('side').classList.toggle('open')"><i class="ti ti-menu-2"></i></button>${isDashboard?'':`<div><h1>${title}</h1><p>${sub}</p></div>`}<div class="user user-menu-wrap">
<button class="user-menu-trigger" onclick="toggleUserMenu(event)" type="button">
<span>${esc(currentUser()?.name||'Admin User')}</span>
<b>${esc((currentUser()?.name||'AU').split(' ').map(v=>v[0]).join('').slice(0,2).toUpperCase())}</b>
<i class="ti ti-chevron-down user-menu-arrow"></i>
</button>
<div class="user-dropdown" id="user-dropdown">
<div class="user-dropdown-head">
<b>${esc(currentUser()?.name||'Admin User')}</b>
<span>${esc(currentUser()?.role||'')}</span>
</div>
<div class="user-dropdown-divider"></div>
<button onclick="openChangePassword();closeUserMenu()"><i class="ti ti-key"></i><span>Change Password</span></button>
<button onclick="logout()"><i class="ti ti-logout"></i><span>Sign out</span></button>
</div>
</div></header><section class="content">${body}</section></main></div><div id="toast"></div>${USER_MENU_STYLE}`;if(isDashboard){const content=document.querySelector('.content'),top=document.querySelector('.top.dashboard-top'),account=top?.querySelector('.user-menu-wrap'),menuButton=top?.querySelector('.mobile-menu');if(active==='crm-dashboard'&&!content.querySelector('.admin-hero,.module-hero,.dashboard-identity')){content.insertAdjacentHTML('afterbegin',`<div class="module-hero dashboard-identity"><div class="module-hero-copy"><span class="module-eyebrow">CRM overview</span><h2>Customer Relationship Dashboard</h2><p>Manage customer pipeline, opportunities and follow-ups.</p></div></div>`)}const hero=content.querySelector('.admin-hero,.module-hero,.dashboard-identity');if(hero&&account){hero.appendChild(account);hero.classList.add('has-dashboard-account')}if(hero&&menuButton)hero.insertBefore(menuButton,hero.firstChild);if(top)top.remove();}restoreSidebarScroll();}
function toggleUserMenu(event){
  if(event) event.stopPropagation();
  const menu=document.getElementById('user-dropdown');
  if(!menu)return;
  menu.classList.toggle('show');
}

function closeUserMenu(){
  const menu=document.getElementById('user-dropdown');
  if(menu)menu.classList.remove('show');
}

if(!window.__userMenuClickHandler){
  window.__userMenuClickHandler=true;
  document.addEventListener('click',function(event){
    const wrap=event.target.closest('.user-menu-wrap');
    if(!wrap)closeUserMenu();
  });
}

const USER_MENU_STYLE = `
<style id="user-menu-style">
.top{
  position:relative;
}

.user-menu-wrap{
  position:relative;
  display:flex;
  align-items:center;
  justify-content:flex-end;
  min-width:130px;
}

.user-menu-trigger{
  border:0;
  background:transparent;
  display:flex;
  align-items:center;
  justify-content:flex-end;
  gap:10px;
  cursor:pointer;
  padding:4px 6px;
  margin:0;
  border-radius:10px;
  color:inherit;
  font:inherit;
  line-height:1;
}

.user-menu-trigger:hover{
  background:#f5f7fb;
}

.user-menu-trigger>span{
  display:flex;
  align-items:center;
  line-height:36px;
  white-space:nowrap;
}

.user-menu-trigger>b{
  width:36px;
  height:36px;
  min-width:36px;
  border-radius:50%;
  display:flex;
  align-items:center;
  justify-content:center;
  background:#eef1f8;
  color:#243575;
  font-weight:700;
  line-height:36px;
  margin:0;
}

.user-menu-arrow{
  font-size:14px;
  color:#6b7280;
  line-height:36px;
  margin-left:0;
  transition:transform .15s ease;
}

.user-dropdown{
  display:none;
  position:absolute;
  right:0;
  top:calc(100% + 8px);
  width:230px;
  box-sizing:border-box;
  background:#fff;
  border:1px solid #e5e7eb;
  border-radius:12px;
  box-shadow:0 12px 30px rgba(15,23,42,.14);
  padding:8px;
  z-index:9999;
  text-align:left;
}

.user-dropdown.show{
  display:block;
}

.user-dropdown-head{
  display:block;
  padding:9px 10px 10px;
  text-align:left;
}

.user-dropdown-head>b{
  display:block;
  width:auto;
  height:auto;
  min-width:0;
  border-radius:0;
  background:transparent;
  color:#111827;
  font-size:14px;
  font-weight:700;
  line-height:20px;
  margin:0;
  padding:0;
}

.user-dropdown-head>span{
  display:block;
  color:#6b7280;
  font-size:12px;
  line-height:18px;
  margin-top:2px;
}

.user-dropdown-divider{
  height:1px;
  background:#e5e7eb;
  margin:2px 0 6px;
}

.user-dropdown>button{
  width:100%;
  height:40px;
  box-sizing:border-box;
  border:0;
  background:transparent;
  display:flex;
  align-items:center;
  gap:10px;
  text-align:left;
  padding:0 10px;
  margin:0;
  border-radius:8px;
  cursor:pointer;
  color:#374151;
  font:inherit;
  font-size:13px;
  line-height:40px;
}

.user-dropdown>button:hover{
  background:#f5f7fb;
  color:#243575;
}

.user-dropdown>button>i{
  display:flex;
  align-items:center;
  justify-content:center;
  width:20px;
  min-width:20px;
  height:20px;
  font-size:17px;
  line-height:20px;
}

.user-dropdown>button>span{
  display:block;
  line-height:20px;
}
</style>`;

const SIDEBAR_SCROLL_KEY='purchase_sidebar_scroll_v1';
function rememberSidebarScroll(){
  const el=document.querySelector('.sidebar-scroll');
  if(!el)return;
  try{sessionStorage.setItem(SIDEBAR_SCROLL_KEY,String(el.scrollTop||0));}catch(e){}
}
function restoreSidebarScroll(){
  const el=document.querySelector('.sidebar-scroll');
  if(!el)return;
  let saved=0;
  try{saved=parseInt(sessionStorage.getItem(SIDEBAR_SCROLL_KEY)||'0',10)||0;}catch(e){}
  const apply=()=>{
    if(saved>0){el.scrollTop=saved;}
    else {
      const current=el.querySelector('.nav-item.active');
      if(current)current.scrollIntoView({block:'nearest'});
    }
  };
  apply();
  requestAnimationFrame(apply);
  el.addEventListener('scroll',()=>{
    try{sessionStorage.setItem(SIDEBAR_SCROLL_KEY,String(el.scrollTop||0));}catch(e){}
  },{passive:true});
}
function navigateAfterSave(event,link){
  event.preventDefault();
  const href=link?.href;
  if(!href)return false;
  rememberSidebarScroll();
  // save() is synchronous in demo mode, so navigation never needs to wait for
  // an asynchronous persistence queue.
  window.location.assign(href);
  return false;
}
function nav(id,label,icon,a){return `<a class="nav-item ${a===id?'active':''}" href="${id}.html" onclick="return navigateAfterSave(event,this)"><i class="ti ${icon}"></i><span>${label}</span></a>`}
function openChangePassword(){
  openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>Change Password</h3><small>Update your password securely</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><label>Current Password<input id="current-password" type="password" autocomplete="current-password" placeholder="Enter current password"></label><label>New Password<input id="new-password" type="password" autocomplete="new-password" minlength="8" placeholder="Minimum 8 characters"></label><label>Confirm New Password<input id="confirm-password" type="password" autocomplete="new-password" minlength="8" placeholder="Re-enter new password"></label><div class="detail-note"><b>Password requirement</b><p>Use at least 8 characters. Your new password must be different from the current password.</p></div></div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="saveChangePassword()"><i class="ti ti-check"></i> Change Password</button></div></div></div>`);
}

async function saveChangePassword(){
  const currentPassword=document.getElementById('current-password').value;
  const newPassword=document.getElementById('new-password').value;
  const confirmPassword=document.getElementById('confirm-password').value;

  if(!currentPassword||!newPassword||!confirmPassword){
    toast('All password fields are required');
    return;
  }

  if(newPassword.length<8){
    toast('New password must be at least 8 characters');
    return;
  }

  if(newPassword!==confirmPassword){
    toast('New passwords do not match');
    return;
  }

  if(currentPassword===newPassword){
    toast('New password must be different from the current password');
    return;
  }

  try{
    await api('/auth/change-password',{
      method:'POST',
      body:JSON.stringify({
        currentPassword,
        newPassword,
        confirmPassword
      })
    });

    closeModal();
    toast('Password changed successfully');
  }catch(error){
    toast(error.message||'Unable to change password');
  }
}

async function logout(){try{await api('/auth/logout',{method:'POST'})}catch(_){}CURRENT_USER=null;location.href='index.html'} function need(){if(!CURRENT_USER)location.href='index.html'} function money(n){const c=companySettings();return `${c.currencySymbol||c.currency||''} ${Number(n||0).toLocaleString(c.currencyLocale||'en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`.trim()} function stat(label,val,icon){return `<div class="stat-card"><div class="stat-icon"><i class="ti ${icon}"></i></div><div><div class="stat-label">${label}</div><div class="stat-value">${val}</div></div></div>`} function table(headers,rows){return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows||`<tr><td colspan="${headers.length}" class="empty">No records found</td></tr>`}</tbody></table></div>`}
function status(s){return `<span class="badge ${s.toLowerCase().replaceAll(' ','-')}">${esc(s)}</span>`}function formModal(title,fields,submit){return `<div class="modal" id="modal"><div class="modal-box"><div class="modal-head"><h3>${title}</h3><button onclick="closeModal()">×</button></div><div class="modal-body">${fields}</div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="${submit}">Save</button></div></div></div>`}function closeModal(){const m=document.getElementById('modal');if(m)m.remove();document.body.classList.remove('modal-open')}
function openModal(html){closeModal();document.body.insertAdjacentHTML('beforeend',html);const m=document.getElementById('modal');if(m){document.body.classList.add('modal-open');requestAnimationFrame(()=>m.classList.add('is-open'));}}
function bindModalEvents(){if(window.__modalEventsBound)return;window.__modalEventsBound=true;document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.getElementById('modal'))closeModal()});document.addEventListener('click',e=>{const m=document.getElementById('modal');if(m&&e.target===m)closeModal()});}
bindModalEvents()
function openVendor(id=null){const x=db(),v=id?(x.vendors||[]).find(a=>String(a.id)===String(id)):null;openModal(formModal(v?'Edit Vendor':'Add Vendor',`<div class="grid2"><label>Vendor Name<input id="vname" value="${esc(v?.name||'')}"></label><label>TRN Number<input id="vtrn" value="${esc(v?.trn||'')}" placeholder="UAE Tax Registration Number"></label><label>Contact Person<input id="vcontact" value="${esc(v?.contact||'')}"></label><label>Phone<input id="vphone" value="${esc(v?.phone||'')}"></label><label>Email<input id="vemail" value="${esc(v?.email||'')}"></label><label>Category<input id="vcat" value="${esc(v?.category||'')}" placeholder="e.g. IT Equipment"></label></div>`,'saveVendor(\''+(v?.id||'')+'\')'))}function saveVendor(id=''){let x=db();const payload={name:vname.value.trim(),trn:vtrn.value.trim(),contact:vcontact.value.trim(),phone:vphone.value.trim(),email:vemail.value.trim(),category:vcat.value.trim()};if(id){const v=(x.vendors||[]).find(a=>String(a.id)===String(id));if(!v){toast('Vendor not found');return}Object.assign(v,payload);recordActivity(x,'Updated','Vendors','Vendor updated: '+v.name,'Vendor')}else{x.vendors.push({id:Date.now(),...payload,status:'Active'});recordActivity(x,'Created','Vendors','Vendor added: '+payload.name,'Vendor')}save(x);closeModal();renderVendors();toast(id?'Vendor updated':'Vendor added')}
function requestItemRow(i=0,item={}){const x=db(),taxRate=item.taxPercent==null?purchaseTaxRate():item.taxPercent,base=(item.quantity||1)*(item.rate||0),tax=base*Number(taxRate||0)/100;return `<div class="request-item" data-item="${i}"><div class="item-grid"><label>Product / Service<select class="req-product" onchange="syncRequestRate(this)"><option value="">Select product</option>${x.products.map(p=>`<option value="${p.id}" data-rate="${p.rate}" ${String(item.productId)===String(p.id)?'selected':''}>${esc(p.name)} (${esc(p.sku)})</option>`).join('')}</select></label><label>Description<input class="req-desc" value="${esc(item.description||'')}" placeholder="Optional specification"></label><label>Quantity<input class="req-qty" type="number" min="0.01" step="0.01" value="${item.quantity||1}" oninput="recalcRequest()"></label><label>Estimated Rate<input class="req-rate" type="number" min="0" step="0.01" value="${item.rate||0}" oninput="recalcRequest()"></label><label>${esc(purchaseTaxLabel())} %<input class="req-tax" type="number" min="0" step="0.01" value="${taxRate}" oninput="recalcRequest()"></label><label>Unit<select class="req-unit"><option>Each</option><option>Box</option><option>Pack</option><option>Carton</option><option>Kg</option><option>Liter</option><option>Service</option></select></label><div class="item-total"><span>Total incl. ${esc(purchaseTaxLabel())}</span><b class="req-total">${money(base+tax)}</b></div></div><button type="button" class="remove-item" onclick="removeRequestItem(this)" title="Remove item"><i class="ti ti-trash"></i></button></div>`}
function openRequest(){const today=new Date().toISOString().slice(0,10);openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>New Purchase Request</h3><small>Create an internal request for goods or services</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="grid2"><label>Department<select id="rdept"><option>Administration</option><option>Finance</option><option>Human Resources</option><option>IT</option><option>Sales</option><option>Operations</option></select></label><label>Required Date<input id="rdate" type="date" value="${today}"></label></div><label>Justification<textarea id="rjust" rows="3" placeholder="Why is this purchase required?"></textarea></label><div class="items-head"><div><b>Request Items</b><small>Add the products/services and estimated cost</small></div><button type="button" class="btn-secondary" onclick="addRequestItem()"><i class="ti ti-plus"></i> Add Item</button></div><div id="request-items">${requestItemRow(0,{})}</div><div class="request-summary"><span>Estimated Total</span><strong id="request-total">${money(0)}</strong></div><div><label>Attachment</label><input id="rfile" type="file" class="file-input" accept=".pdf"><small class="hint">Demo mode stores the file name only; no file is uploaded.</small></div></div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="saveRequest()"><i class="ti ti-send"></i> Submit Request</button></div></div></div>`);recalcRequest()}
function addRequestItem(){const wrap=document.getElementById('request-items');wrap.insertAdjacentHTML('beforeend',requestItemRow(wrap.children.length,{}));}
function removeRequestItem(btn){const rows=document.querySelectorAll('#request-items .request-item');if(rows.length===1){toast('At least one item is required');return}btn.closest('.request-item').remove();recalcRequest()}
function syncRequestRate(sel){const opt=sel.selectedOptions[0];const row=sel.closest('.request-item');if(opt?.dataset.rate && Number(row.querySelector('.req-rate').value)===0)row.querySelector('.req-rate').value=opt.dataset.rate;recalcRequest()}
function recalcRequest(){let total=0;document.querySelectorAll('#request-items .request-item').forEach(row=>{const q=Number(row.querySelector('.req-qty').value||0),r=Number(row.querySelector('.req-rate').value||0),tax=Number(row.querySelector('.req-tax').value||0),base=q*r,t=base+(base*tax/100);total+=t;row.querySelector('.req-total').textContent=money(t)});const out=document.getElementById('request-total');if(out)out.textContent=money(total)}
function saveRequest(){const x=db(),rows=[...document.querySelectorAll('#request-items .request-item')];const items=rows.map(row=>{const product=row.querySelector('.req-product'),opt=product.selectedOptions[0],qty=Number(row.querySelector('.req-qty').value||0),rate=Number(row.querySelector('.req-rate').value||0),taxPercent=Number(row.querySelector('.req-tax').value||0),subtotal=qty*rate,tax=subtotal*taxPercent/100;return {productId:product.value||null,productName:opt?.textContent?.split(' (')[0]||'',description:row.querySelector('.req-desc').value.trim(),quantity:qty,rate,unit:row.querySelector('.req-unit').value,taxPercent,subtotal,tax,total:subtotal+tax}});if(items.some(i=>!i.productId||i.quantity<=0)){toast('Please select a product and enter valid quantities');return}const total=items.reduce((a,i)=>a+i.total,0),next=(x.requests.length?Math.max(...x.requests.map(r=>Number(String(r.requestNo).split('-').pop())||0))+1:1);const id=Date.now();x.requests.unshift({id,requestNo:'PR-2026-'+String(next).padStart(3,'0'),requester:currentUser()?.name||'User',department:document.getElementById('rdept').value,date:document.getElementById('rdate').value,status:'Pending Approval',items:items.length,total,justification:document.getElementById('rjust').value.trim(),lineItems:items,attachment:document.getElementById('rfile')?.files[0]?.name||'',createdAt:new Date().toISOString()});recordActivity(x,'Created','Purchase Requests','Purchase request '+('PR-2026-'+String(next).padStart(3,'0'))+' submitted for approval','PR-2026-'+String(next).padStart(3,'0'));save(x);closeModal();renderRequests();toast('Purchase request submitted for approval')}
function requestActions(r){
 const x=db();
 if(r.status==='Draft')return `<button class="btn-secondary" onclick="submitRequest(${r.id})">Submit</button>`;
 if(r.status==='Pending Approval'){const u=currentUser();if(u&&['Admin','Procurement Manager','Procurement Staff'].includes(u.role))return `<button class="btn-secondary" onclick="approveRequest(${r.id})">Approve</button> <button class="btn-secondary" onclick="rejectRequest(${r.id})">Reject</button>`;return '';}
 if(r.status==='Approved'){
  const existing=(x.rfqs||[]).find(q=>String(q.requestId)===String(r.id));
  const pdf=`<button class="btn-secondary" onclick="downloadPurchaseRequestPdf(${r.id})"><i class="ti ti-file-type-pdf"></i> Vendor PDF</button>`;
  if(existing){
   return `${pdf} <span class="btn-secondary"><i class="ti ti-file-description"></i> ${existing.status==="PO Created"?"PO Created":"RFQ Created"}</span>`;
  }
  return `${pdf} <button class="btn-secondary" onclick="openRFQ(${r.id})"><i class="ti ti-file-description"></i> Create RFQ</button>`;
 }
 return '—';
}
function downloadPDF(title, html, options={}){
  const c=companySettings();
  const w=window.open('', '_blank', 'width=900,height=1100');
  if(!w){toast('Please allow pop-ups to generate the PDF');return}
  const logo='data:image/png;base64,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';
  const stampImage='data:image/jpeg;base64,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sMEABSE+0AAAAAAAAAAAAAAAAAAAAAAAAAxhCBQBAyzxihABBChgihADCwABAhwigAAAAAAAAAAAAAAAAAAAAAAACtsEABQENcAAAACAAAAAAAAAAAAAAAAAAAQCQCRgAAjCAgSTCAgAgCwwQiABQiDzAAAAAAAAAAAAAAAAAAAAAAAAAAUsmgBQ0ucAAAAAAAAAAAAAAAAAAAAAAAACQgwwQQQRhjiBAiRBDCCDCwBQBBAChAAAAAAAAAAAAAAAAAAAAAAAAAAEukgBT2O4AAAAAAAAAAAAAAAAAAAAAAAABDRCDgAQACSwAAQxxiABDARwABRAgAAAAAAAAAAAAAAAAAAAAAAAAAABUMEABR0coAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABMOkABTUukAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABE8MABB/fvok000000000000000000000000000000000000000000000000000000000000000000000000000001O0k8AApIICS+98tLINs898898899988+/sZ5+/wD/ALzzzrj/AP8AffPHPDOPLHbDn9jnCjDf/wD/AMvw4L9s884o887/AP8AyzEgFaQAAoQ7sw888U4wxy8w8w8wwc8408w0w4wcdcc8400w88884wcc8wccQz9y08ww09TfeY1w8Uw08w8ww08c89+RjWwAAAEUze/9+/8AvPf/ADjTzzDXrD3zzzDTz/zDHbzzzzvjHTz3/wD85w8848888888887yx2888884w/8A+csNPffvOOOEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAAAAAAAAAAAAAAAAAAAAAABwAAAAAAAAAAAAAD//EAAL/2gAMAwEAAgADAAAAEAAAADABEDCIBHIAAAAACACAEBAAACACABCABBBECIBDBAAICADACADBABABAABABADCDAABACACABEAIAAAHAAA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9BmLYeL4Fly/s87Essl8ayIR1JLfrQj4Ufkwww4+4SET8gw0lltKE7iClEkjUe4g85pXVr4jryUMjOiFK4U7NKsaWGMy3o7ctERtX8BZ9H/WR9ht9GYshE0a+z2pLPT5kKxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpXONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpXONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxpXeNUxpHONUxpHONUxpHONUxpHONUxpHONUxpHONUxnr41TGkXxqmNIvjVMaRzjVMaRzjVMaRzjVMaRzjVMaV3jVMaVzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaV3jVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRzjVMaRfGqY0jnGqY0jnGqY0jnGqY0jnGqY0jnGqY0jnGqY0jnGqY0jnGqY0jnGqY0jnGqY0jnGqY0jnGqY0jnGqY0jnGqY0jnGqYrENRz7/aZZqfMxDQzUOjNQXM/PJS0b9hB9f/AFloljRw2ce9fbsmQj4bV3zL9J9qchCBpQlESHjqV4K8xXkchYdzvtJP2FmwWCkWbB4JCzYPBIWZBYJCzYPBIWbBYJCz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';
  const printScript='<scr'+'ipt>window.onload=function(){setTimeout(function(){window.print()},250)};window.onafterprint=function(){setTimeout(function(){window.close()},300)};</scr'+'ipt>';
  const page='<!doctype html><html><head><meta charset="utf-8"><title>'+esc(title)+'</title><style>'+
    '@page{size:A4;margin:14mm}*{box-sizing:border-box}body{font-family:Arial,Helvetica,sans-serif;color:#202735;font-size:12px;margin:0}'+
    '.topline{display:flex;justify-content:space-between;align-items:center;font-size:10px;color:#111;margin-bottom:22px}'+
    '.header{display:grid;grid-template-columns:42% 58%;align-items:center;padding-bottom:13px;border-bottom:4px solid #243575}'+
    '.brand-area{display:flex;align-items:center;gap:14px}.brand-logo{width:150px;height:auto;object-fit:contain}'+
    '.brand-name{font-size:30px;line-height:1.1;font-weight:800;color:#243575}.brand-sub{font-size:15px;color:#222;margin-top:7px}'+
    '.head-right{text-align:right}.doc-title{font-size:24px;line-height:1.15;font-weight:800;color:#243575;text-transform:uppercase}'+
    '.generated{font-size:11px;font-weight:800;margin-top:16px;color:#242424}'+
    '.intro{margin-top:30px;border-left:6px solid #243575;padding:18px 20px 18px 18px}'+
    '.intro h2{font-size:22px;color:#243575;margin:0 0 8px}.intro p{font-size:13px;margin:0;color:#30343b}'+
    '.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:0 42px;margin-top:26px;margin-bottom:20px}'+
    '.field{padding:10px 0;border-bottom:1px solid #d9dde5}.field span{display:block;color:#353942;font-size:11px;letter-spacing:.2px;margin-bottom:7px}.field b{font-size:13px;color:#202735}'+
    '.section{margin:25px 0}.section h3{font-size:14px;color:#243575;margin:0 0 9px;text-transform:uppercase}'+
    '.note{background:#f7f8fa;border:1px solid #d9dde5;padding:12px;margin-top:14px;white-space:pre-wrap}.total{margin-top:15px;text-align:right;font-size:17px;font-weight:800;color:#243575}'+
    '.footer{border-top:1px solid #d9dde5;margin-top:30px;padding-top:8px;color:#6b7280;font-size:9px;text-align:center}.po-stamp{margin-top:24px;page-break-inside:avoid;text-align:left}.po-stamp img{width:210px;height:auto;display:block}.po-stamp .authorized{font-size:10px;font-weight:700;margin-top:6px}.po-stamp .system-note{font-size:9px;line-height:1.35;margin-top:4px;color:#374151;max-width:520px}'+
    'table{width:100%;border-collapse:collapse;margin-top:8px}th,td{border:1px solid #cfd4dd;padding:8px;text-align:left;vertical-align:top}th{background:#f0f2f5;color:#202735;font-weight:800}'+
    '</style></head><body>'+
    '<div class="topline"><span>'+new Date().toLocaleDateString()+'</span><span>'+esc(title)+'</span></div>'+
    '<div class="header">'+
    '<div class="head-left"><img src="'+esc(logo)+'" style="width:150px;height:auto;display:block" alt="'+esc(c.name||'Company')+'"><div style="font-weight:800;font-size:13px;margin-top:7px">'+esc(c.name||'Company')+'</div><div style="font-size:9px;color:#6b7280;margin-top:2px">'+esc(c.address||'')+'</div><div style="font-size:9px;color:#6b7280;margin-top:2px">'+esc(c.taxNumber?((c.taxNumberLabel||'Tax Registration Number')+': '+c.taxNumber):'')+'</div></div>'+
    '<div class="head-right"><div class="doc-title">'+esc(title)+'</div><div class="generated">GENERATED '+new Date().toLocaleString(c.currencyLocale||'en-US')+'</div></div></div>'+
    html+
    (options.stamp?'<div class="po-stamp"><img src="'+esc(logo)+'" alt="'+esc(c.name||'Company')+'"><div class="system-note">This purchase order is system-generated by '+esc(c.name||'the company')+' and does not require a physical signature where permitted.</div></div>':'')+
    '<div class="footer">'+esc(c.name||'Company')+' | '+esc(c.legalName||'')+' | '+esc(c.country||'')+' | This document is system-generated for business purposes.</div>'+
    printScript+'</body></html>';
  w.document.open();w.document.write(page);w.document.close();
}
function pdfField(label,value){return `<div class="field"><span>${esc(label)}</span><b>${esc(value==null||value===''?'—':value)}</b></div>`}
function pdfTable(headers,rows){return `<table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table>`}
function requestDetails(id){const x=db(),r=x.requests.find(a=>a.id===id);if(!r)return;const items=r.lineItems||[];openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>${esc(r.requestNo)}</h3><small>Purchase request details</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="detail-grid"><div><span>Department</span><b>${esc(r.department)}</b></div><div><span>Requester</span><b>${esc(r.requester)}</b></div><div><span>Required Date</span><b>${esc(r.date)}</b></div><div><span>Status</span><b>${status(r.status)}</b></div></div><div class="detail-note"><b>Justification</b><p>${esc(r.justification||'No justification provided.')}</p></div>${table(['Product','Description','Qty','Rate',purchaseTaxLabel(),'Total'],items.map(i=>`<tr><td><b>${esc(i.productName)}</b></td><td>${esc(i.description||'—')}</td><td>${i.quantity} ${esc(i.unit||'')}</td><td>${money(i.rate)}</td><td>${i.taxPercent==null?'—':i.taxPercent+'%'}</td><td>${money(i.total)}</td></tr>`).join(''))}<div class="request-summary"><span>Estimated Total</span><strong>${money(r.total)}</strong></div>${r.attachment?`<div class="hint"><i class="ti ti-paperclip"></i> ${esc(r.attachment)}</div>`:''}</div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Close</button>${requestActions(r)}</div></div></div>`)}
function downloadPurchaseRequestPdf(id){
 const x=db(),r=(x.requests||[]).find(a=>a.id===id);
 if(!r)return;
 if(r.status!=='Approved'){toast('Purchase Request PDF is available only after approval');return}
 const items=r.lineItems||[];
 const rows=items.map((i,n)=>`<tr><td>${n+1}</td><td><b>${esc(i.productName||'')}</b></td><td>${esc(i.description||'—')}</td><td>${esc(i.quantity||0)}</td><td>${esc(i.unit||'—')}</td></tr>`).join('');
 const html=`
 <div class="vendor-doc-title">
   <h1>Request for Quotation</h1>
   <p>Purchase Request Reference: <b>${esc(r.requestNo)}</b> &nbsp;•&nbsp; Approved Procurement Requirement</p>
 </div>
 <div class="grid">
   <div class="field"><span>Purchase Request No.</span><b>${esc(r.requestNo||'—')}</b></div>
   <div class="field"><span>Request Date</span><b>${esc(r.date||'—')}</b></div>
   <div class="field"><span>Department</span><b>${esc(r.department||'—')}</b></div>
   <div class="field"><span>Required By</span><b>${esc(r.requiredDate||r.date||'—')}</b></div>
   <div class="field"><span>Request Status</span><b><span class="status-approved">Approved</span></b></div>
   <div class="field"><span>Requester</span><b>${esc(r.requester||'—')}</b></div>
   <div class="field"><span>Purchaser TRN</span><b>${esc(companyTaxNumber())}</b></div>
 </div>
 <div class="section">
   <h3>Quotation Requirements</h3>
   <p class="intro">Dear Vendor, please review the following procurement requirements and submit your best quotation against the requested items. <b>No internal estimated pricing is disclosed in this document.</b></p>
   <table class="item-table"><thead><tr><th>#</th><th>Product / Service</th><th>Description / Specification</th><th>Quantity</th><th>Unit</th></tr></thead><tbody>${rows||`<tr><td colspan="5">No items specified.</td></tr>`}</tbody></table>
 </div>
 <div class="instruction">
   <strong>Vendor Submission Instructions</strong><br>
   Please provide your quotation separately, clearly mentioning your unit rates, applicable taxes, delivery lead time, quotation validity and payment terms. Kindly reference <b>${esc(r.requestNo)}</b> on your quotation.
 </div>
 <div class="section">
   <h3>Justification / Additional Requirements</h3>
   <p class="intro">${esc(r.justification||'No additional requirements provided.')}</p>
 </div>
 <div class="signature-row">
   <div class="signature">Authorized by Procurement / Management</div>
   <div class="signature">Vendor Representative / Acknowledgement</div>
 </div>`;
 downloadPDF(`Request for Quotation - ${r.requestNo}`,html);
}
function tablePdf(headers, rows){
 return `<table style="width:100%;border-collapse:collapse;margin-top:10px"><thead><tr>${headers.map(h=>`<th style="text-align:left;background:#f3f4f6;border:1px solid #d1d5db;padding:8px">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows||`<tr><td colspan="${headers.length}" style="border:1px solid #d1d5db;padding:8px">No items</td></tr>`}</tbody></table>`;
}
function submitRequest(id){let x=db(),r=x.requests.find(a=>a.id===id);if(r){r.status='Pending Approval';save(x);renderRequests();toast('Request submitted for approval')}}
function approveRequest(id){const u=currentUser();if(!u||!['Admin','Procurement Manager','Procurement Staff'].includes(u.role)){toast('Only Admin, Procurement Manager or Procurement Staff can approve purchase requests');return}let x=db(),r=x.requests.find(a=>a.id===id);if(r){r.status='Approved';r.approvedAt=new Date().toISOString();recordActivity(x,'Approved','Purchase Requests',r.requestNo+' approved',r.requestNo);save(x);renderRequests();toast('Request approved')}}
function rejectRequest(id){const reason=prompt('Reason for rejection:');if(reason===null)return;let x=db(),r=x.requests.find(a=>a.id===id);if(r){r.status='Rejected';r.rejectionReason=reason;recordActivity(x,'Rejected','Purchase Requests',r.requestNo+' rejected: '+reason,r.requestNo);save(x);renderRequests();toast('Request rejected')}}
function dashboardMonthKey(value){const d=new Date(value||'');if(Number.isNaN(d.getTime()))return null;return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`}
function dashboardMonthLabel(key){const [y,m]=String(key||'').split('-').map(Number);if(!y||!m)return key||'';return new Date(y,m-1,1).toLocaleDateString(undefined,{month:'short'})}
function dashboardMonthlyTotals(records,dateFields,amountField,months=6){const now=new Date(),keys=[];for(let i=months-1;i>=0;i--){const d=new Date(now.getFullYear(),now.getMonth()-i,1);keys.push(`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`)}const out=Object.fromEntries(keys.map(k=>[k,0]));(records||[]).forEach(r=>{let key=null;for(const f of dateFields){key=dashboardMonthKey(r?.[f]);if(key)break}if(key&&Object.prototype.hasOwnProperty.call(out,key))out[key]+=Number(r?.[amountField]||0)});return keys.map(k=>({key:k,label:dashboardMonthLabel(k),value:out[k]}))}
function dashboardSvgTrend(salesSeries,purchaseSeries){const all=[...salesSeries,...purchaseSeries].map(d=>Number(d.value)||0),max=Math.max(...all,1),w=760,h=250,padX=44,padY=26,plotW=w-padX*2,plotH=h-padY*2;const points=series=>series.map((d,i)=>`${(padX+(plotW*(i/(series.length-1||1)))).toFixed(1)},${(h-padY-(Number(d.value||0)/max)*plotH).toFixed(1)}`).join(' ');const labels=salesSeries.map((d,i)=>`<text x="${(padX+(plotW*(i/(salesSeries.length-1||1)))).toFixed(1)}" y="235" text-anchor="middle">${esc(d.label)}</text>`).join('');const grids=[0,.25,.5,.75,1].map(v=>{const y=h-padY-v*plotH;return `<line x1="${padX}" y1="${y}" x2="${w-padX}" y2="${y}"/>`}).join('');const salesPts=points(salesSeries).split(' '),purchasePts=points(purchaseSeries).split(' ');return `<svg class="admin-trend-svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="Six month sales and purchase trend"><g class="grid">${grids}</g><polyline class="sales-line" points="${salesPts.join(' ')}"></polyline><polyline class="purchase-line" points="${purchasePts.join(' ')}"></polyline>${salesPts.map(p=>{const [cx,cy]=p.split(',');return `<circle class="sales-dot" cx="${cx}" cy="${cy}" r="4"></circle>`}).join('')}${purchasePts.map(p=>{const [cx,cy]=p.split(',');return `<circle class="purchase-dot" cx="${cx}" cy="${cy}" r="4"></circle>`}).join('')}${labels}</svg>`}
function dashboardCountBy(records,field,values){return (records||[]).filter(r=>values.includes(String(r?.[field]||''))).length}
function adminDashboard(){
  const x=db();
  const arr=k=>Array.isArray(x[k])?x[k]:[];
  const leads=arr('leads'), quotes=arr('salesQuotations'), salesOrders=arr('salesOrders'), deliveries=arr('deliveries'), salesInvoices=arr('customerInvoices'), salesPayments=arr('customerPayments'), purchaseOrders=arr('orders'), purchaseRequests=arr('requests'), purchaseQuotes=arr('quotations'), purchaseInvoices=arr('invoices');
  const salesValue=salesOrders.reduce((n,r)=>n+Number(r?.total||0),0);
  const purchaseValue=purchaseOrders.reduce((n,r)=>n+Number(r?.total||0),0);
  const receivable=salesInvoices.reduce((n,r)=>n+Math.max(0,Number(r?.balance ?? (Number(r?.amount||r?.total||0)-Number(r?.paidAmount||0)))),0);
  const payable=Math.max(0,purchaseInvoices.reduce((n,r)=>n+Number(r?.amount||r?.total||0),0)-purchaseInvoices.filter(r=>r?.status==='Paid').reduce((n,r)=>n+Number(r?.amount||r?.total||0),0));
  const pipelineValue=leads.reduce((n,r)=>n+Number(r?.value||0),0);
  const won=leads.filter(l=>['Won','Closed Won','Customer Accepted'].includes(String(l?.stage||''))).length;
  const lost=leads.filter(l=>['Lost','Closed Lost','Customer Rejected'].includes(String(l?.stage||''))).length;
  const activeLeads=Math.max(0,leads.length-won-lost);
  const pendingApprovals=purchaseRequests.filter(r=>['Pending Approval','Pending'].includes(String(r?.status||''))).length+quotes.filter(q=>q?.status==='Pending Approval').length;
  const openDeliveries=deliveries.filter(d=>d?.status!=='Delivered').length;
  const openSalesOrders=salesOrders.filter(o=>!['Completed','Cancelled'].includes(String(o?.status||''))).length;
  const unpaidSalesInvoices=salesInvoices.filter(i=>i?.status!=='Paid').length;
  const unpaidPurchaseInvoices=purchaseInvoices.filter(i=>i?.status!=='Paid').length;
  const salesApproved=quotes.filter(q=>['Approved','Sent','Accepted'].includes(String(q?.status||''))).length;
  const salesSent=quotes.filter(q=>['Sent','Accepted'].includes(String(q?.status||''))).length;
  const salesAccepted=quotes.filter(q=>q?.status==='Accepted').length;
  const purchaseApproved=purchaseQuotes.filter(q=>['Approved','Accepted','Selected'].includes(String(q?.status||''))).length;
  const purchaseOrderRate=purchaseRequests.length?Math.round((purchaseOrders.length/purchaseRequests.length)*100):0;
  const salesConversion=quotes.length?Math.round((salesAccepted/quotes.length)*100):0;
  const monthlySales=dashboardMonthlyTotals(salesOrders,['orderDate','createdAt'],'total');
  const monthlyPurchase=dashboardMonthlyTotals(purchaseOrders,['orderDate','createdAt'],'total');
  const pipeline=[['New',dashboardCountBy(leads,'stage',['New'])],['Qualified',dashboardCountBy(leads,'stage',['Qualified'])],['Quotation',leads.filter(l=>String(l?.stage||'').toLowerCase().includes('quotation')||String(l?.stage||'').toLowerCase().includes('proposal')).length],['Won',won],['Lost',lost]];
  const maxPipe=Math.max(...pipeline.map(v=>v[1]),1);
  const purchasePipeline=[['Requests',purchaseRequests.length],['RFQs',arr('rfqs').length],['Vendor Quotes',purchaseQuotes.length],['Orders',purchaseOrders.length]];
  const maxPurchase=Math.max(...purchasePipeline.map(v=>v[1]),1);
  const recent=arr('activities').slice(0,7);
  const customerTotals={};
  salesOrders.forEach(o=>{const name=o?.customerName||o?.customer||o?.companyName||'Unknown Customer';customerTotals[name]=(customerTotals[name]||0)+Number(o?.total||0)});
  const topCustomers=Object.entries(customerTotals).sort((a,b)=>b[1]-a[1]).slice(0,5);
  const maxCustomer=Math.max(...topCustomers.map(v=>v[1]),1);
  const statusCards=[
    ['Pending Approvals',pendingApprovals,'ti-clock','admin-mini-warn'],
    ['Open Deliveries',openDeliveries,'ti-truck-delivery','admin-mini-info'],
    ['Sales Invoices',unpaidSalesInvoices,'ti-file-invoice','admin-mini-sales'],
    ['Vendor Invoices',unpaidPurchaseInvoices,'ti-file-invoice','admin-mini-purchase']
  ];
  layout('dashboard','Executive Dashboard','Unified business overview across CRM, Sales and Purchasing',`
    <div class="admin-hero"><div class="admin-hero-copy"><span class="admin-eyebrow"><i class="ti ti-sparkles"></i> Executive overview</span><h2>${esc(companySettings().name||'Your Company')} <span>Business Command Center</span></h2><p>One live management view for CRM, Sales, Purchasing and financial operations.</p><div class="admin-hero-meta"><span><i class="ti ti-calendar"></i> ${new Date().toLocaleDateString(undefined,{weekday:'long',month:'short',day:'numeric',year:'numeric'})}</span><span><i class="ti ti-database"></i> ${leads.length+salesOrders.length+purchaseOrders.length} core records tracked</span></div></div></div>
    <div class="admin-stat-grid admin-stat-grid-six">
      <div class="admin-stat stat-sales"><div class="admin-stat-top"><span>Sales Value</span><i class="ti ti-chart-line"></i></div><strong>${money(salesValue)}</strong><small>${salesOrders.length} orders · ${openSalesOrders} open</small></div>
      <div class="admin-stat stat-purchase"><div class="admin-stat-top"><span>Purchase Value</span><i class="ti ti-shopping-cart"></i></div><strong>${money(purchaseValue)}</strong><small>${purchaseOrders.length} purchase orders</small></div>
      <div class="admin-stat stat-pipeline"><div class="admin-stat-top"><span>CRM Pipeline</span><i class="ti ti-users"></i></div><strong>${money(pipelineValue)}</strong><small>${activeLeads} active · ${won} won</small></div>
      <div class="admin-stat stat-cash"><div class="admin-stat-top"><span>Receivables</span><i class="ti ti-wallet"></i></div><strong>${money(receivable)}</strong><small>${unpaidSalesInvoices} unpaid customer invoices</small></div>
      <div class="admin-stat stat-payable"><div class="admin-stat-top"><span>Payables</span><i class="ti ti-building-bank"></i></div><strong>${money(payable)}</strong><small>${unpaidPurchaseInvoices} unpaid vendor invoices</small></div>
      <div class="admin-stat stat-approval"><div class="admin-stat-top"><span>Approvals</span><i class="ti ti-circle-check"></i></div><strong>${pendingApprovals}</strong><small>Items waiting for action</small></div>
    </div>
    <div class="admin-report-grid"><div class="admin-panel admin-trend-panel"><div class="admin-panel-head"><div><span class="panel-kicker">Financial performance</span><h3>Sales vs Purchasing</h3><p>Six-month transaction value trend</p></div><div class="chart-legend"><span><i class="legend-sales"></i> Sales</span><span><i class="legend-purchase"></i> Purchasing</span></div></div>${dashboardSvgTrend(monthlySales,monthlyPurchase)}</div><div class="admin-panel admin-pipeline-panel"><div class="admin-panel-head"><div><span class="panel-kicker">CRM</span><h3>Lead Pipeline</h3><p>Current opportunities by stage</p></div><div class="pipeline-total">${leads.length}</div></div><div class="pipeline-bars">${pipeline.map(([label,val])=>`<div class="pipeline-row"><div><span>${esc(label)}</span><b>${val}</b></div><div class="pipeline-track"><span style="width:${Math.max(4,(val/maxPipe)*100)}%"></span></div></div>`).join('')}</div><div class="pipeline-foot"><span>${won} won</span><span>${lost} lost</span><span>${salesConversion}% quote conversion</span></div></div></div>
    <div class="admin-report-grid admin-three-panels">
      <div class="admin-panel"><div class="admin-panel-head"><div><span class="panel-kicker">Sales</span><h3>Quotation Funnel</h3><p>Progress from quote to order</p></div><div class="panel-badge">${salesConversion}%</div></div><div class="funnel-list"><div><span>All quotations</span><b>${quotes.length}</b></div><div><span>Approved</span><b>${salesApproved}</b></div><div><span>Sent</span><b>${salesSent}</b></div><div><span>Accepted</span><b>${salesAccepted}</b></div><div class="funnel-progress"><span style="width:${Math.max(4,salesConversion)}%"></span></div></div></div>
      <div class="admin-panel"><div class="admin-panel-head"><div><span class="panel-kicker">Purchasing</span><h3>Purchase Pipeline</h3><p>Procurement volume by stage</p></div><div class="panel-badge">${purchaseOrderRate}%</div></div><div class="pipeline-bars compact">${purchasePipeline.map(([label,val])=>`<div class="pipeline-row"><div><span>${esc(label)}</span><b>${val}</b></div><div class="pipeline-track"><span style="width:${Math.max(4,(val/maxPurchase)*100)}%"></span></div></div>`).join('')}</div></div>
      <div class="admin-panel"><div class="admin-panel-head"><div><span class="panel-kicker">Customers</span><h3>Top Customers</h3><p>Sales order value</p></div></div><div class="customer-bars">${topCustomers.length?topCustomers.map(([name,val])=>`<div class="customer-row"><div><span>${esc(name)}</span><b>${money(val)}</b></div><div class="customer-track"><span style="width:${Math.max(5,(val/maxCustomer)*100)}%"></span></div></div>`).join(''):'<div class="empty-state">No sales order data yet.</div>'}</div></div>
    </div>
    <div class="admin-report-grid lower"><div class="admin-panel admin-metrics-panel"><div class="admin-panel-head"><div><span class="panel-kicker">Operations</span><h3>Business Health</h3><p>Key work in progress across the platform</p></div></div><div class="health-grid">${statusCards.map(([label,val,icon,cls])=>`<div class="${cls}"><i class="ti ${icon}"></i><b>${val}</b><span>${label}</span></div>`).join('')}</div><div class="finance-strip"><div><span>Receivables</span><b>${money(receivable)}</b></div><div><span>Payables</span><b>${money(payable)}</b></div><div><span>Net order value</span><b>${money(salesValue-purchaseValue)}</b></div></div></div><div class="admin-panel admin-activity-panel"><div class="admin-panel-head"><div><span class="panel-kicker">Activity</span><h3>Latest Activity</h3><p>Most recent system actions</p></div><a class="btn-secondary" href="activities.html">View all</a></div><div class="admin-activity-list">${recent.length?recent.map(a=>`<div class="admin-activity"><span class="activity-dot"></span><div><b>${esc(a.details||a.action||'Activity')}</b><small>${esc(a.userName||'System')} · ${a.createdAt?new Date(a.createdAt).toLocaleString():''}</small></div></div>`).join(''):`<div class="empty-state">No activity recorded yet.</div>`}</div></div></div>
    <div class="admin-quick-grid"><a href="crm-dashboard.html"><i class="ti ti-users"></i><div><b>CRM</b><span>Leads & pipeline</span></div><i class="ti ti-arrow-up-right"></i></a><a href="sales.html"><i class="ti ti-chart-line"></i><div><b>Sales</b><span>Quotations & orders</span></div><i class="ti ti-arrow-up-right"></i></a><a href="requests.html"><i class="ti ti-shopping-cart"></i><div><b>Purchasing</b><span>Requests & procurement</span></div><i class="ti ti-arrow-up-right"></i></a><a href="reports.html"><i class="ti ti-chart-bar"></i><div><b>Reports</b><span>Operational reporting</span></div><i class="ti ti-arrow-up-right"></i></a></div>`);
}
function renderPurchaseDashboard(){
  need();const x=db();
  const requests=x.requests||[],orders=x.orders||[],invoices=x.invoices||[],rfqs=x.rfqs||[],quotes=x.quotations||[],vendors=x.vendors||[],receipts=x.receipts||[];
  const pending=requests.filter(r=>['Pending Approval','Pending'].includes(String(r.status||''))).length;
  const open=orders.filter(r=>!['Completed','Cancelled'].includes(String(r.status||''))),unpaid=invoices.filter(r=>r.status!=='Paid');
  const spend=orders.reduce((s,r)=>s+Number(r.total||0),0),payable=unpaid.reduce((s,r)=>s+Math.max(0,Number(r.balance??(Number(r.amount||r.total||0)-Number(r.paidAmount||0)))),0),vendorCount=vendors.length;
  const monthly=Array.from({length:6},(_,i)=>{const d=new Date();d.setMonth(d.getMonth()-(5-i));const m=d.getMonth(),y=d.getFullYear();return orders.filter(o=>{const dt=new Date(o.orderDate||o.createdAt||'');return !Number.isNaN(dt.getTime())&&dt.getMonth()===m&&dt.getFullYear()===y}).reduce((s,o)=>s+Number(o.total||0),0)}),max=Math.max(...monthly,1),pts=monthly.map((v,i)=>`${30+i*120},${150-(v/max)*105}`).join(' '),labels=monthly.map((_,i)=>{const d=new Date();d.setMonth(d.getMonth()-(5-i));return d.toLocaleDateString(undefined,{month:'short'})});
  const svg=`<svg class="module-chart" viewBox="0 0 780 185" role="img" aria-label="Purchase order value trend"><g class="grid">${[25,60,95,130,155].map(y=>`<line x1="30" x2="750" y1="${y}" y2="${y}"/>`).join('')}</g><polyline class="module-line alt" points="${pts}"/>${monthly.map((v,i)=>`<circle class="module-dot alt" cx="${30+i*120}" cy="${150-(v/max)*105}" r="4"/>`).join('')}${labels.map((m,i)=>`<text x="${30+i*120}" y="174" text-anchor="middle">${m}</text>`).join('')}</svg>`;
  const pipeline=[['Requests',requests.length],['RFQs',rfqs.length],['Vendor Quotes',quotes.length],['Purchase Orders',orders.length]],maxP=Math.max(...pipeline.map(a=>a[1]),1);
  const recent=requests.slice(0,6),maxR=Math.max(...recent.map(r=>Number(r.total||0)),1);
  const health=[['Pending Approvals',pending,'ti-clock'],['Open Orders',open.length,'ti-shopping-cart'],['Unpaid Invoices',unpaid.length,'ti-file-invoice'],['Goods Receipts',receipts.length,'ti-package']];
  layout('purchase-dashboard','Purchase Dashboard','Procurement performance, supplier activity and purchasing controls',`<div class="module-dashboard">
    <div class="module-hero"><div class="module-hero-copy"><span class="module-eyebrow"><i class="ti ti-shopping-cart"></i> Procurement command view</span><h2>Procurement Performance Center</h2><p>Monitor requests, sourcing, purchase orders, supplier invoices and receiving.</p><div class="module-hero-meta"><span><i class="ti ti-building-store"></i> ${vendorCount} vendors</span><span><i class="ti ti-file-invoice"></i> ${requests.length} requests</span><span><i class="ti ti-shopping-cart"></i> ${open.length} open orders</span></div></div></div>
    <div class="module-kpi-grid"><div class="module-kpi blue"><div class="module-kpi-top"><span>Purchase Spend</span><i class="ti ti-cash"></i></div><strong>${money(spend)}</strong><small>Total purchase order value</small></div><div class="module-kpi purple"><div class="module-kpi-top"><span>Pending Approval</span><i class="ti ti-clock"></i></div><strong>${pending}</strong><small>Requests awaiting action</small></div><div class="module-kpi green"><div class="module-kpi-top"><span>Open Orders</span><i class="ti ti-shopping-cart"></i></div><strong>${open.length}</strong><small>Orders still active</small></div><div class="module-kpi amber"><div class="module-kpi-top"><span>Payables</span><i class="ti ti-file-invoice"></i></div><strong>${money(payable)}</strong><small>Outstanding supplier balance</small></div></div>
    <div class="module-grid-2"><div class="module-panel"><div class="module-panel-head"><div><span class="module-kicker">Procurement spend</span><h3>Purchase Order Trend</h3><p>Confirmed purchase order value over the last six months</p></div><span class="module-pill">${money(spend)} total</span></div>${svg}</div><div class="module-panel"><div class="module-panel-head"><div><span class="module-kicker">Sourcing pipeline</span><h3>Procurement Funnel</h3><p>Volume by purchasing stage</p></div><div class="module-badge">${orders.length}</div></div><div class="module-bars">${pipeline.map(([label,val])=>`<div class="module-bar-row"><div class="module-bar-label"><span>${label}</span><b>${val}</b></div><div class="module-track"><span style="width:${Math.max(5,val/maxP*100)}%"></span></div></div>`).join('')}</div><div class="module-foot"><span class="good">${quotes.length} vendor quotations</span><span>${rfqs.length} RFQs</span><span>${orders.length} purchase orders</span></div></div></div>
    <div class="module-grid-3"><div class="module-panel"><div class="module-panel-head"><div><span class="module-kicker">Operations</span><h3>Procurement Health</h3><p>Live work in progress</p></div></div><div class="module-mini-grid">${health.map(([label,val,icon])=>`<div class="module-mini"><i class="ti ${icon}"></i><b>${val}</b><span>${label}</span></div>`).join('')}</div></div>
      <div class="module-panel"><div class="module-panel-head"><div><span class="module-kicker">Requests</span><h3>Recent Purchase Requests</h3><p>Latest internal demand</p></div><a class="module-action" href="requests.html">View requests</a></div><div class="module-bars">${recent.length?recent.map(r=>`<div class="module-bar-row"><div class="module-bar-label"><span>${esc(r.requestNo||'Request')} · ${esc(r.department||'Department')}</span><b>${money(r.total)}</b></div><div class="module-track green"><span style="width:${Math.max(6,Number(r.total||0)/maxR*100)}%"></span></div></div>`).join(''):'<div class="module-empty">No purchase requests yet.</div>'}</div></div>
      <div class="module-panel"><div class="module-panel-head"><div><span class="module-kicker">Suppliers</span><h3>Supplier Overview</h3><p>Vendor and invoice position</p></div><a class="module-action" href="vendors.html">View vendors</a></div><div class="module-mini-grid"><div class="module-mini"><i class="ti ti-building-store"></i><b>${vendorCount}</b><span>Vendors</span></div><div class="module-mini"><i class="ti ti-file-description"></i><b>${quotes.length}</b><span>Vendor quotes</span></div><div class="module-mini"><i class="ti ti-file-invoice"></i><b>${unpaid.length}</b><span>Unpaid invoices</span></div><div class="module-mini"><i class="ti ti-package"></i><b>${receipts.length}</b><span>Goods receipts</span></div></div></div></div>
    <div class="module-panel"><div class="module-panel-head"><div><span class="module-kicker">Payables</span><h3>Outstanding Supplier Invoices</h3><p>Invoices requiring payment</p></div><a class="module-action" href="invoices.html">View invoices</a></div><div class="module-list">${unpaid.slice(0,6).map(i=>`<div class="module-list-row"><span class="module-list-icon"><i class="ti ti-file-invoice"></i></span><div><b>${esc(i.invoiceNo||'Invoice')} · ${esc(i.vendorName||i.vendor||'Vendor')}</b><small>Due ${esc(i.dueDate||'—')} · ${esc(i.status||'Open')}</small></div><strong>${money(Math.max(0,Number(i.balance??(Number(i.amount||i.total||0)-Number(i.paidAmount||0)))) )}</strong></div>`).join('')||'<div class="module-empty">No outstanding supplier invoices.</div>'}</div></div>
  </div>`);
}
function renderDashboard(){need();const x=db();if(currentUser()?.role==='Admin'){try{adminDashboard()}catch(error){console.error('Executive dashboard failed to render:',error);const safe=x||{};const req=Array.isArray(safe.requests)?safe.requests:[],orders=Array.isArray(safe.orders)?safe.orders:[],inv=Array.isArray(safe.invoices)?safe.invoices:[],leads=Array.isArray(safe.leads)?safe.leads:[];layout('dashboard','Executive Dashboard','Unified business overview across CRM, Sales and Purchasing', '<div class="admin-hero"><div class="admin-hero-copy"><span class="admin-eyebrow"><i class="ti ti-dashboard"></i> Executive overview</span><h2>'+esc(companySettings().name||'Your Company')+' <span>Business Command Center</span></h2><p>Live operational snapshot across CRM, Sales and Purchasing.</p></div></div><div class="stats">'+stat('CRM Leads',leads.length,'ti-users')+stat('Purchase Requests',req.length,'ti-file-invoice')+stat('Purchase Orders',orders.length,'ti-shopping-cart')+stat('Unpaid Invoices',inv.filter(r=>r.status!=='Paid').length,'ti-receipt')+'</div><div class="section-card"><div class="section-title">System Overview</div><p style="color:#8a94a6;font-size:12px;margin-top:6px">Your unified dashboard is loading in safe mode. Existing CRM, Sales and Purchasing data remains available.</p></div>')}return}renderPurchaseDashboard()}
function renderVendors(){
  need();
  const x=db();
  layout('vendors','Vendors','Manage your procurement vendors',`
    <div class="section-card">
      <div class="section-head">
        <div class="section-title">Vendor List</div>
        <button class="btn-primary" onclick="openVendor()"><i class="ti ti-plus"></i> Add Vendor</button>
      </div>
      <div class="filters">
        <input id="vendor-search" placeholder="Search vendors" oninput="filterRows()">
      </div>
      <div id="vendor-table">${vendorRows(x.vendors||[])}</div>
    </div>
  `);
}

function vendorRows(v){
  const total=v.length;
  const pages=Math.max(1,Math.ceil(total/25));
  let page=Number(window.VENDOR_PAGE||1);

  if(page<1) page=1;
  if(page>pages) page=pages;
  window.VENDOR_PAGE=page;

  const start=(page-1)*25;
  const visible=v.slice(start,start+25);

  const tableHtml=table(
    ['Vendor','TRN','Contact','Phone','Email','Category','Status','Actions'],
    visible.map(r=>`<tr><td><b>${esc(r.name)}</b></td><td>${esc(r.trn||'—')}</td><td>${esc(r.contact)}</td><td>${esc(r.phone)}</td><td>${esc(r.email)}</td><td>${esc(r.category)}</td><td>${status(r.status)}</td><td><button class="btn-sm" onclick="openVendor(&quot;${r.id}&quot;)"><i class="ti ti-edit"></i> Edit</button></td></tr>`).join('')
  );

  if(total<=25) return tableHtml;

  let pageButtons='';

  const addPage=(n)=>{
    pageButtons+=`<button class="pagination-page ${n===page?'active':''}" onclick="changeVendorPage(${n})">${n}</button>`;
  };

  const addDots=()=>{
    pageButtons+=`<span class="pagination-dots">…</span>`;
  };

  if(pages<=5){
    for(let i=1;i<=pages;i++) addPage(i);
  }else if(page<=3){
    addPage(1); addPage(2); addPage(3); addDots(); addPage(pages);
  }else if(page>=pages-2){
    addPage(1); addDots(); addPage(pages-2); addPage(pages-1); addPage(pages);
  }else{
    addPage(1); addDots(); addPage(page); addDots(); addPage(pages);
  }

  const from=start+1;
  const to=Math.min(start+25,total);

  return tableHtml+`
    <div class="pagination">
      <div class="pagination-showing">Showing ${from}–${to} of ${total}</div>
      <div class="pagination-controls">
        <button class="pagination-arrow" ${page<=1?'disabled':''} onclick="changeVendorPage(${page-1})">‹</button>
        ${pageButtons}
        <button class="pagination-arrow" ${page>=pages?'disabled':''} onclick="changeVendorPage(${page+1})">›</button>
      </div>
    </div>
  `;
}

function filterRows(resetPage=true){
  if(resetPage) window.VENDOR_PAGE=1;

  const x=db();
  const q=(document.getElementById('vendor-search')?.value||'').toLowerCase().trim();

  const rows=(x.vendors||[]).filter(v=>
    (v.name+' '+(v.trn||'')+' '+v.contact+' '+v.category)
      .toLowerCase()
      .includes(q)
  );

  const target=document.getElementById('vendor-table');
  if(target) target.innerHTML=vendorRows(rows);
}

function changeVendorPage(page){
  window.VENDOR_PAGE=page;
  filterRows(false);
}

function renderProducts(){
  need();
  const x=db(), products=x.products||[];
  const categories=[...new Set(products.map(p=>p.category).filter(Boolean))].sort();

  layout('products','Products & Services','Manage items available for purchasing',`
    <div class="section-card">
      <div class="section-head">
        <div class="section-title">Product Catalog</div>
        <button class="btn-primary" onclick="openProduct()"><i class="ti ti-plus"></i> Add Product</button>
      </div>

      <div class="filters">
        <input id="product-search" placeholder="Search product, SKU or category" oninput="filterProducts()">
        <select id="product-category" onchange="filterProducts()">
          <option value="">All Categories</option>
          ${categories.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('')}
        </select>
        <select id="product-sort" onchange="filterProducts()">
          <option value="latest">Latest Added</option>
          <option value="oldest">Oldest Added</option>
          <option value="name-asc">Product Name A–Z</option>
          <option value="name-desc">Product Name Z–A</option>
          <option value="sku-asc">SKU A–Z</option>
          <option value="sku-desc">SKU Z–A</option>
        </select>
      </div>

      <div id="product-table">${productRows(products)}</div>
    </div>
  `);
}

function productRows(rows){
  const total=rows.length;
  const pages=Math.max(1,Math.ceil(total/25));
  let page=Number(window.PRODUCT_PAGE||1);

  if(page<1) page=1;
  if(page>pages) page=pages;
  window.PRODUCT_PAGE=page;

  const start=(page-1)*25;
  const visible=rows.slice(start,start+25);

  const tableHtml=table(
    ['Product','SKU','Category','Unit','Default Rate'],
    visible.map(r=>`
      <tr>
        <td><b>${esc(r.name)}</b></td>
        <td>${esc(r.sku||'—')}</td>
        <td>${esc(r.category||'—')}</td>
        <td>${esc(r.unit||'—')}</td>
        <td>${money(r.rate)}</td>
      </tr>
    `).join('')
  );

  if(total<=25) return tableHtml;

  let pageButtons='';

  const addPage=(n)=>{
    pageButtons+=`<button class="pagination-page ${n===page?'active':''}" onclick="changeProductPage(${n})">${n}</button>`;
  };

  const addDots=()=>{
    pageButtons+=`<span class="pagination-dots">…</span>`;
  };

  if(pages<=5){
    for(let i=1;i<=pages;i++) addPage(i);
  }else if(page<=3){
    addPage(1);
    addPage(2);
    addPage(3);
    addDots();
    addPage(pages);
  }else if(page>=pages-2){
    addPage(1);
    addDots();
    addPage(pages-2);
    addPage(pages-1);
    addPage(pages);
  }else{
    addPage(1);
    addDots();
    addPage(page);
    addDots();
    addPage(pages);
  }

  const from=start+1;
  const to=Math.min(start+25,total);

  return tableHtml+`
    <div class="pagination">
      <div class="pagination-showing">Showing ${from}–${to} of ${total}</div>
      <div class="pagination-controls">
        <button class="pagination-arrow" ${page<=1?'disabled':''} onclick="changeProductPage(${page-1})">‹</button>
        ${pageButtons}
        <button class="pagination-arrow" ${page>=pages?'disabled':''} onclick="changeProductPage(${page+1})">›</button>
      </div>
    </div>
  `;
}

function filterProducts(resetPage=true){
  if(resetPage) window.PRODUCT_PAGE=1;

  const x=db();
  const q=(document.getElementById('product-search')?.value||'').toLowerCase().trim();
  const c=document.getElementById('product-category')?.value||'';
  const sort=document.getElementById('product-sort')?.value||'latest';

  const rows=(x.products||[]).filter(p=>{
    const text=(p.name+' '+(p.sku||'')+' '+(p.category||'')+' '+(p.unit||'')).toLowerCase();
    return (!q||text.includes(q))&&(!c||p.category===c);
  });

  rows.sort((a,b)=>{
    if(sort==='latest') return Number(b.id||0)-Number(a.id||0);
    if(sort==='oldest') return Number(a.id||0)-Number(b.id||0);

    const an=String(a.name||'').toLowerCase();
    const bn=String(b.name||'').toLowerCase();
    const as=String(a.sku||'').toLowerCase();
    const bs=String(b.sku||'').toLowerCase();

    if(sort==='name-asc') return an.localeCompare(bn);
    if(sort==='name-desc') return bn.localeCompare(an);
    if(sort==='sku-asc') return as.localeCompare(bs);
    if(sort==='sku-desc') return bs.localeCompare(as);

    return 0;
  });

  const target=document.getElementById('product-table');
  if(target) target.innerHTML=productRows(rows);
}

function changeProductPage(page){
  window.PRODUCT_PAGE=page;
  filterProducts(false);
}

function openProduct(){openModal(formModal('Add Product',`<div class="grid2"><label>Product Name<input id="pname"></label><label>SKU<input id="psku"></label><label>Category<input id="pcat"></label><label>Unit<select id="punit"><option>Each</option><option>Box</option><option>Pack</option><option>Carton</option><option>Kg</option><option>Liter</option><option>Service</option></select></label><label>Default Rate<input id="prate" type="number"></label></div>`,'saveProduct()'))}function saveProduct(){let x=db();x.products.push({id:Date.now(),name:pname.value,sku:psku.value,category:pcat.value,unit:punit.value,rate:Number(prate.value||0)});recordActivity(x,'Created','Products','Product added: '+pname.value,'Product');save(x);closeModal();renderProducts();toast('Product added')}
function renderRequests(){need();const x=db();const pending=x.requests.filter(r=>r.status==='Pending Approval').length,approved=x.requests.filter(r=>r.status==='Approved').length,total=x.requests.reduce((a,r)=>a+Number(r.total||0),0);layout('requests','Purchase Requests','Create and track internal purchase requests',`<div class="stats">${stat('Total Requests',x.requests.length,'ti-file-invoice')}${stat('Pending Approval',pending,'ti-clock')}${stat('Approved',approved,'ti-circle-check')}${stat('Estimated Value',money(total),'ti-cash')}</div><div class="section-card"><div class="section-head"><div><div class="section-title">Purchase Requests</div><div style="font-size:11px;color:#9CA3AF;margin-top:3px">Create, review and approve internal procurement requests</div></div><button class="btn-primary" onclick="openRequest()"><i class="ti ti-plus"></i> New Request</button></div><div class="filters"><input id="request-search" placeholder="Search request no., department or requester" oninput="filterRequests()"><select id="request-status" onchange="filterRequests()"><option value="">All Statuses</option><option>Draft</option><option>Pending Approval</option><option>Approved</option><option>Rejected</option></select><input id="request-date" type="date" onchange="filterRequests()"></div><div id="request-table">${requestRows(x.requests)}</div></div>`)}
function requestRows(rows){
  const total=rows.length;
  const pages=Math.max(1,Math.ceil(total/25));
  let page=Number(window.REQUEST_PAGE||1);

  if(page<1) page=1;
  if(page>pages) page=pages;
  window.REQUEST_PAGE=page;

  const start=(page-1)*25;
  const visible=rows.slice(start,start+25);

  const tableHtml=table(
    ['Request No.','Department','Requester','Required Date','Items','Estimated Total','Status','Actions'],
    visible.map(r=>`<tr><td><button class="link-btn" onclick="requestDetails(${r.id})">${esc(r.requestNo)}</button></td><td>${esc(r.department)}</td><td>${esc(r.requester)}</td><td>${esc(r.date)}</td><td>${r.lineItems?.length||r.items||0}</td><td>${money(r.total)}</td><td>${status(r.status)}</td><td>${requestActions(r)}</td></tr>`).join('')
  );

  if(total<=25) return tableHtml;

  let pageButtons='';

  const addPage=(n)=>{
    pageButtons+=`<button class="pagination-page ${n===page?'active':''}" onclick="changeRequestPage(${n})">${n}</button>`;
  };

  const addDots=()=>{
    pageButtons+=`<span class="pagination-dots">…</span>`;
  };

  if(pages<=5){
    for(let i=1;i<=pages;i++) addPage(i);
  }else if(page<=3){
    addPage(1);
    addPage(2);
    addPage(3);
    addDots();
    addPage(pages);
  }else if(page>=pages-2){
    addPage(1);
    addDots();
    addPage(pages-2);
    addPage(pages-1);
    addPage(pages);
  }else{
    addPage(1);
    addDots();
    addPage(page);
    addDots();
    addPage(pages);
  }

  const from=start+1;
  const to=Math.min(start+25,total);

  return tableHtml+`
    <div class="pagination">
      <div class="pagination-showing">Showing ${from}–${to} of ${total}</div>
      <div class="pagination-controls">
        <button class="pagination-arrow" ${page<=1?'disabled':''} onclick="changeRequestPage(${page-1})">‹</button>
        ${pageButtons}
        <button class="pagination-arrow" ${page>=pages?'disabled':''} onclick="changeRequestPage(${page+1})">›</button>
      </div>
    </div>
  `;
}

function filterRequests(resetPage=true){
  if(resetPage) window.REQUEST_PAGE=1;

  const x=db();
  const q=(document.getElementById('request-search')?.value||'').toLowerCase();
  const s=document.getElementById('request-status')?.value||'';
  const d=document.getElementById('request-date')?.value||'';

  const rows=x.requests.filter(r=>
    (!q||(r.requestNo+' '+r.department+' '+r.requester).toLowerCase().includes(q)) &&
    (!s||r.status===s) &&
    (!d||r.date===d)
  );

  const target=document.getElementById('request-table');
  if(target) target.innerHTML=requestRows(rows);
}

function changeRequestPage(page){
  window.REQUEST_PAGE=page;
  filterRequests(false);
}

function simpleList(active,title,sub,key,headers,empty,addText){need();const x=db();layout(active,title,sub,`<div class="section-card"><div class="section-head"><div class="section-title">${title}</div>${addText?`<button class="btn-primary" onclick="toast('Module form ready for next build step')"><i class="ti ti-plus"></i> ${addText}</button>`:''}</div>${table(headers,(x[key]||[]).map(r=>`<tr><td><b>${esc(r.requestNo||r.rfqNo||r.quotationNo||r.poNo||r.grnNo||r.invoiceNo||r.paymentNo||'—')}</b></td><td>${esc(r.vendor||r.supplier||r.department||'—')}</td><td>${esc(r.date||'—')}</td><td>${status(r.status||'Draft')}</td><td>${money(r.total||r.amount||0)}</td></tr>`).join(''))}</div>`)}

function receiptEligibleOrders(x){return (x.orders||[]).filter(o=>['Approved','Sent to Vendor','Partially Received'].includes(o.status));}
function orderReceivedQty(x,poId,itemIndex){return (x.receipts||[]).filter(r=>String(r.poId)===String(poId)).reduce((sum,r)=>sum+Number(r.items?.[itemIndex]?.acceptedQty||0),0)}
function receiptRemaining(x,o,i){return Math.max(0,Number(o.items?.[i]?.quantity||0)-orderReceivedQty(x,o.id,i));}
function renderReceipts(){
 need();const x=db(),receipts=x.receipts||[],received=receipts.filter(r=>r.status==='Received').length,partial=receipts.filter(r=>r.status==='Partially Received').length,pending=receiptEligibleOrders(x).length;
 layout('receipts','Goods Receipts (GRN)','Receive, inspect and record goods against approved purchase orders',`<div class="stats">${stat('Total GRNs',receipts.length,'ti-package')}${stat('Received',received,'ti-circle-check')}${stat('Partial Receipts',partial,'ti-truck-delivery')}${stat('POs Awaiting Receipt',pending,'ti-clock')}</div><div class="section-card"><div class="section-head"><div><div class="section-title">Goods Receipts</div><div style="font-size:11px;color:#9CA3AF;margin-top:3px">Record accepted and rejected quantities against Purchase Orders</div></div><button class="btn-primary" onclick="openGRN()"><i class="ti ti-plus"></i> Create GRN</button></div><div class="filters"><input id="grn-search" placeholder="Search GRN, PO or vendor" oninput="filterReceipts()"><select id="grn-status" onchange="filterReceipts()"><option value="">All Statuses</option><option>Received</option><option>Partially Received</option><option>Rejected</option></select></div><div id="grn-table">${receiptRows(receipts)}</div></div>`);
}
function receiptRows(rows){
  const total=rows.length;
  const pages=Math.max(1,Math.ceil(total/25));
  let page=Number(window.RECEIPT_PAGE||1);

  if(page<1) page=1;
  if(page>pages) page=pages;
  window.RECEIPT_PAGE=page;

  const start=(page-1)*25;
  const visible=rows.slice(start,start+25);

  const tableHtml=table(
    ['GRN No.','PO No.','Vendor','Received Date','Items','Accepted Qty','Rejected Qty','Status','Actions'],
    visible.map(r=>{
      const a=(r.items||[]).reduce((n,i)=>n+Number(i.acceptedQty||0),0);
      const rej=(r.items||[]).reduce((n,i)=>n+Number(i.rejectedQty||0),0);
      return `<tr><td><button class="link-btn" onclick="receiptDetails(${r.id})">${esc(r.grnNo)}</button></td><td>${esc(r.poNo||'—')}</td><td>${esc(r.vendorName||'—')}</td><td>${esc(r.receivedDate||'—')}</td><td>${(r.items||[]).length}</td><td><b>${a}</b></td><td>${rej}</td><td>${status(r.status)}</td><td><button class="btn-sm" onclick="receiptDetails(${r.id})"><i class="ti ti-eye"></i> View</button> <button class="btn-sm" onclick="downloadGRNPdf(${r.id})"><i class="ti ti-file-type-pdf"></i> PDF</button></td></tr>`;
    }).join('')
  );

  if(total<=25) return tableHtml;

  let pageButtons='';

  const addPage=(n)=>{
    pageButtons+=`<button class="pagination-page ${n===page?'active':''}" onclick="changeReceiptPage(${n})">${n}</button>`;
  };

  const addDots=()=>{
    pageButtons+=`<span class="pagination-dots">…</span>`;
  };

  if(pages<=5){
    for(let i=1;i<=pages;i++) addPage(i);
  }else if(page<=3){
    addPage(1);
    addPage(2);
    addPage(3);
    addDots();
    addPage(pages);
  }else if(page>=pages-2){
    addPage(1);
    addDots();
    addPage(pages-2);
    addPage(pages-1);
    addPage(pages);
  }else{
    addPage(1);
    addDots();
    addPage(page);
    addDots();
    addPage(pages);
  }

  const from=start+1;
  const to=Math.min(start+25,total);

  return tableHtml+`
    <div class="pagination">
      <div class="pagination-showing">Showing ${from}–${to} of ${total}</div>
      <div class="pagination-controls">
        <button class="pagination-arrow" ${page<=1?'disabled':''} onclick="changeReceiptPage(${page-1})">‹</button>
        ${pageButtons}
        <button class="pagination-arrow" ${page>=pages?'disabled':''} onclick="changeReceiptPage(${page+1})">›</button>
      </div>
    </div>
  `;
}

function filterReceipts(resetPage=true){
  if(resetPage) window.RECEIPT_PAGE=1;

  const x=db();
  const q=(document.getElementById('grn-search')?.value||'').toLowerCase();
  const st=document.getElementById('grn-status')?.value||'';

  const rows=(x.receipts||[]).filter(r=>
    (!q||(r.grnNo+' '+r.poNo+' '+r.vendorName).toLowerCase().includes(q)) &&
    (!st||r.status===st)
  );

  const target=document.getElementById('grn-table');
  if(target) target.innerHTML=receiptRows(rows);
}

function changeReceiptPage(page){
  window.RECEIPT_PAGE=page;
  filterReceipts(false);
}

function openGRN(){const x=db(),orders=receiptEligibleOrders(x);if(!orders.length){toast('No approved or sent purchase orders are awaiting receipt');return}openModal(`<div class="modal" id="modal"><div class="modal-box request-modal grn-modal"><div class="modal-head"><div><h3>Create Goods Receipt</h3><small>Record physical delivery against a Purchase Order</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="grid2"><label>Purchase Order<select id="grn-po" onchange="loadGRNPO()"><option value="">Select PO</option>${orders.map(o=>`<option value="${o.id}">${esc(o.poNo)} — ${esc(o.vendorName)} — ${money(o.total)}</option>`).join('')}</select></label><label>Receipt Date<input id="grn-date" type="date" value="${new Date().toISOString().slice(0,10)}"></label><label>Warehouse / Location<input id="grn-location" placeholder="e.g. Main Store"></label><label>Received By<input id="grn-receiver" value="Admin User"></label></div><div id="grn-preview"><div class="detail-note"><b>Select a Purchase Order</b><p>PO items and remaining quantities will appear here.</p></div></div><label>Inspection Notes<textarea id="grn-notes" rows="3" placeholder="Condition, inspection remarks, delivery note number, etc."></textarea></label></div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="saveGRN()"><i class="ti ti-device-floppy"></i> Save GRN</button></div></div></div>`);loadGRNPO()}
function loadGRNPO(){const x=db(),o=x.orders.find(a=>String(a.id)===String(document.getElementById('grn-po')?.value)),box=document.getElementById('grn-preview');if(!o||!box){if(box)box.innerHTML='<div class="detail-note"><b>Select a Purchase Order</b><p>PO items and remaining quantities will appear here.</p></div>';return}box.innerHTML=`<div class="detail-grid"><div><span>Vendor</span><b>${esc(o.vendorName)}</b></div><div><span>PO</span><b>${esc(o.poNo)}</b></div><div><span>RFQ</span><b>${esc(o.rfqNo||'—')}</b></div><div><span>PO Total</span><b>${money(o.total)}</b></div></div><div class="grn-items">${(o.items||[]).map((i,idx)=>{const rem=receiptRemaining(x,o,idx);return `<div class="grn-item" data-index="${idx}"><div><b>${esc(i.productName)}</b><small>Ordered: ${i.quantity} ${esc(i.unit||'')} · Previously accepted: ${Number(i.quantity||0)-rem}</small></div><div><label>Received<input class="grn-received" type="number" min="0" max="${rem}" step="0.01" value="${rem}" oninput="syncGRNRow(this)"></label></div><div><label>Accepted<input class="grn-accepted" type="number" min="0" max="${rem}" step="0.01" value="${rem}"></label></div><div><label>Rejected<input class="grn-rejected" type="number" min="0" max="${rem}" step="0.01" value="0"></label></div><div><label>Inspection<select class="grn-inspection"><option>Passed</option><option>Passed with Remarks</option><option>Failed</option><option>Pending Inspection</option></select></label></div><div><label>Remark<input class="grn-remark" placeholder="Optional"></label></div></div>`}).join('')}</div><div class="grn-help"><i class="ti ti-info-circle"></i> Received = physical quantity delivered. Accepted + Rejected must equal Received.</div>`}
function syncGRNRow(input){const row=input.closest('.grn-item'),received=Number(input.value||0);row.querySelector('.grn-accepted').max=received;row.querySelector('.grn-rejected').max=received;const accepted=Number(row.querySelector('.grn-accepted').value||0);if(accepted>received)row.querySelector('.grn-accepted').value=received;const rej=Number(row.querySelector('.grn-rejected').value||0);if(rej>received)row.querySelector('.grn-rejected').value=Math.max(0,received-Number(row.querySelector('.grn-accepted').value||0))}
function saveGRN(){const x=db(),po=x.orders.find(a=>String(a.id)===String(document.getElementById('grn-po')?.value));if(!po){toast('Select a purchase order');return}const date=document.getElementById('grn-date').value;if(!date){toast('Enter receipt date');return}const items=[...document.querySelectorAll('.grn-item')].map(row=>{const idx=Number(row.dataset.index),src=po.items[idx],received=Number(row.querySelector('.grn-received').value||0),accepted=Number(row.querySelector('.grn-accepted').value||0),rejected=Number(row.querySelector('.grn-rejected').value||0);return{productId:src.productId,productName:src.productName,unit:src.unit,orderedQty:Number(src.quantity||0),remainingQty:receiptRemaining(x,po,idx),receivedQty:received,acceptedQty:accepted,rejectedQty:rejected,inspection:row.querySelector('.grn-inspection').value,remark:row.querySelector('.grn-remark').value.trim()}});if(items.every(i=>i.receivedQty===0)){toast('Enter at least one received quantity');return}if(items.some(i=>i.acceptedQty+i.rejectedQty!==i.receivedQty)){toast('Accepted + Rejected must equal Received for every item');return}if(items.some(i=>i.receivedQty>i.remainingQty)){toast('Received quantity cannot exceed remaining PO quantity');return}if(items.some(i=>i.acceptedQty>i.receivedQty||i.rejectedQty>i.receivedQty)){toast('Accepted or rejected quantity cannot exceed received quantity');return}const acceptedAny=items.some(i=>i.acceptedQty>0),rejectedAny=items.some(i=>i.rejectedQty>0),allComplete=(po.items||[]).every((_,idx)=>receiptRemaining(x,po,idx)-Number(items[idx]?.acceptedQty||0)<=0);const next=(x.receipts||[]).length?Math.max(...x.receipts.map(a=>Number(String(a.grnNo||'').split('-').pop())||0))+1:1;x.receipts=x.receipts||[];x.receipts.unshift({id:Date.now(),grnNo:'GRN-2026-'+String(next).padStart(3,'0'),poId:po.id,poNo:po.poNo,quotationId:po.quotationId,rfqNo:po.rfqNo,requestNo:po.requestNo,vendorId:po.vendorId,vendorName:po.vendorName,receivedDate:date,location:document.getElementById('grn-location').value.trim(),receivedBy:document.getElementById('grn-receiver').value.trim(),items,status:allComplete&&acceptedAny?'Received':acceptedAny?'Partially Received':'Rejected',notes:document.getElementById('grn-notes').value.trim(),createdAt:new Date().toISOString()});po.status=allComplete&&acceptedAny?'Completed':acceptedAny?'Partially Received':po.status;po.receivedAt=new Date().toISOString();recordActivity(x,'Created','Goods Receipts','Goods receipt created for '+po.poNo,'GRN');save(x);closeModal();renderReceipts();toast('Goods Receipt created successfully')}
function receiptDetails(id){const x=db(),r=(x.receipts||[]).find(a=>a.id===id);if(!r)return;openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>${esc(r.grnNo)}</h3><small>${esc(r.vendorName)} — ${esc(r.poNo)}</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="detail-grid"><div><span>PO</span><b>${esc(r.poNo)}</b></div><div><span>Vendor</span><b>${esc(r.vendorName)}</b></div><div><span>Receipt Date</span><b>${esc(r.receivedDate)}</b></div><div><span>Status</span><b>${status(r.status)}</b></div><div><span>Location</span><b>${esc(r.location||'—')}</b></div><div><span>Received By</span><b>${esc(r.receivedBy||'—')}</b></div></div>${table(['Item','Ordered','Received','Accepted','Rejected','Inspection','Remark'],(r.items||[]).map(i=>`<tr><td>${esc(i.productName)}</td><td>${i.orderedQty}</td><td>${i.receivedQty}</td><td><b>${i.acceptedQty}</b></td><td>${i.rejectedQty}</td><td>${esc(i.inspection)}</td><td>${esc(i.remark||'—')}</td></tr>`).join(''))}${r.notes?`<div class="detail-note"><b>Inspection Notes</b><p>${esc(r.notes)}</p></div>`:''}</div><div class="modal-foot"><button class="btn-secondary" onclick="downloadGRNPdf(${r.id})"><i class="ti ti-file-type-pdf"></i> PDF</button><button class="btn-secondary" onclick="closeModal()">Close</button>${r.status!=='Rejected'?`<button class="btn-primary" onclick="closeModal();location.href='invoices.html'"><i class="ti ti-receipt"></i> Vendor Invoice</button>`:''}</div></div></div>`)}

window.addEventListener('DOMContentLoaded',async()=>{await initAppState();if(!APP_STATE)return;const p=location.pathname.split('/').pop();const pages={'dashboard.html':['dashboard',renderDashboard],'purchase-dashboard.html':['dashboard',renderPurchaseDashboard],'vendors.html':['vendors',renderVendors],'products.html':['products',renderProducts],'requests.html':['requests',renderRequests],'rfqs.html':['rfqs',renderRFQs],'quotations.html':['quotations',renderQuotations],'comparison.html':['comparison',renderComparison],'orders.html':['orders',renderOrders],'receipts.html':['receipts',renderReceipts],'invoices.html':['invoices',renderInvoices],'payments.html':['payments',renderPayments],'reports.html':['reports',()=>simpleList('reports','Reports','Purchase analytics and reports','requests',['Request No.','Department','Date','Status','Amount'],'No report data','')],'users.html':['users',renderUsers],'settings.html':['settings',renderCompanySettings],'activities.html':['activities',renderActivities]};if(typeof HR_PAGES!=='undefined'&&HR_PAGES.includes(p.replace('.html','')))renderHRPage();const entry=pages[p];if(entry&&guard(entry[0]))entry[1]();});
function renderRFQs(){need();const x=db();const approved=x.requests.filter(r=>r.status==='Approved');const pending=x.rfqs.filter(r=>r.status==='Draft').length;layout('rfqs','Request for Quotations','Create and manage vendor quotation requests',`<div class="stats">${stat('Total RFQs',x.rfqs.length,'ti-file-description')}${stat('Draft',pending,'ti-pencil')}${stat('Sent',x.rfqs.filter(r=>r.status==='Sent').length,'ti-send')}${stat('Responses',x.rfqs.filter(r=>r.status==='Response Received').length,'ti-message-check')}</div><div class="section-card"><div class="section-head"><div><div class="section-title">RFQ List</div><div style="font-size:11px;color:#9CA3AF;margin-top:3px">Request quotations from approved purchase requests</div></div><button class="btn-primary" onclick="openRFQ()"><i class="ti ti-plus"></i> Create RFQ</button></div><div class="filters"><input id="rfq-search" placeholder="Search RFQ, vendor or request" oninput="filterRFQs()"><select id="rfq-status" onchange="filterRFQs()"><option value="">All Statuses</option><option>Draft</option><option>Sent</option><option>Response Received</option><option>Closed</option></select></div><div id="rfq-table">${rfqRows(x.rfqs)}</div></div>`)}
function rfqRows(rows){
  const total=rows.length;
  const pages=Math.max(1,Math.ceil(total/25));
  let page=Number(window.RFQ_PAGE||1);

  if(page<1) page=1;
  if(page>pages) page=pages;
  window.RFQ_PAGE=page;

  const start=(page-1)*25;
  const visible=rows.slice(start,start+25);

  const tableHtml=table(
    ['RFQ No.','Request No.','Vendors','Issue Date','Due Date','Status','Actions'],
    visible.map(r=>`<tr><td><button class="link-btn" onclick="rfqDetails(${r.id})">${esc(r.rfqNo)}</button></td><td>${esc(r.requestNo||'—')}</td><td>${esc((r.vendors||[]).map(v=>v.name).join(', ')||'—')}</td><td>${esc(r.issueDate||'—')}</td><td>${esc(r.dueDate||'—')}</td><td>${status(r.status)}</td><td><button class="btn-sm" onclick="rfqDetails(${r.id})"><i class="ti ti-eye"></i> View</button>${['Sent','Response Received'].includes(r.status)?` <button class="btn-sm" onclick="openQuotation(${r.id})"><i class="ti ti-file-dollar"></i> Add Quotation</button>`:''}${r.status==='Draft'?` <button class="btn-sm" onclick="sendRFQ(${r.id})"><i class="ti ti-send"></i> Send</button>`:''}</td></tr>`).join('')
  );

  if(total<=25) return tableHtml;

  let pageButtons='';

  const addPage=(n)=>{
    pageButtons+=`<button class="pagination-page ${n===page?'active':''}" onclick="changeRFQPage(${n})">${n}</button>`;
  };

  const addDots=()=>{
    pageButtons+=`<span class="pagination-dots">…</span>`;
  };

  if(pages<=5){
    for(let i=1;i<=pages;i++) addPage(i);
  }else if(page<=3){
    addPage(1);
    addPage(2);
    addPage(3);
    addDots();
    addPage(pages);
  }else if(page>=pages-2){
    addPage(1);
    addDots();
    addPage(pages-2);
    addPage(pages-1);
    addPage(pages);
  }else{
    addPage(1);
    addDots();
    addPage(page);
    addDots();
    addPage(pages);
  }

  const from=start+1;
  const to=Math.min(start+25,total);

  return tableHtml+`
    <div class="pagination">
      <div class="pagination-showing">Showing ${from}–${to} of ${total}</div>
      <div class="pagination-controls">
        <button class="pagination-arrow" ${page<=1?'disabled':''} onclick="changeRFQPage(${page-1})">‹</button>
        ${pageButtons}
        <button class="pagination-arrow" ${page>=pages?'disabled':''} onclick="changeRFQPage(${page+1})">›</button>
      </div>
    </div>
  `;
}

function filterRFQs(resetPage=true){
  if(resetPage) window.RFQ_PAGE=1;

  const x=db();
  const q=(document.getElementById('rfq-search')?.value||'').toLowerCase();
  const s=document.getElementById('rfq-status')?.value||'';

  const rows=x.rfqs.filter(r=>
    (!q||(r.rfqNo+' '+r.requestNo+' '+(r.vendors||[]).map(v=>v.name).join(' ')).toLowerCase().includes(q)) &&
    (!s||r.status===s)
  );

  const target=document.getElementById('rfq-table');
  if(target) target.innerHTML=rfqRows(rows);
}

function changeRFQPage(page){
  window.RFQ_PAGE=page;
  filterRFQs(false);
}
function openRFQ(requestId=null){const x=db(),approved=x.requests.filter(r=>r.status==='Approved'&&!(x.rfqs||[]).some(q=>String(q.requestId)===String(r.id)));if(!approved.length){toast('No approved Purchase Request is waiting for an RFQ');return}openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>Create RFQ</h3><small>Request quotations from selected vendors</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="grid2"><label>Purchase Request<select id="rfq-request" onchange="loadRFQRequest()"><option value="">Select approved request</option>${approved.map(r=>`<option value="${r.id}" ${String(requestId)===String(r.id)?'selected':''}>${esc(r.requestNo)} — ${esc(r.department)} — ${money(r.total)}</option>`).join('')}</select></label><label>Quotation Due Date<input id="rfq-due" type="date"></label></div><label>Vendors<select id="rfq-vendors" multiple size="4">${x.vendors.filter(v=>v.status==='Active').map(v=>`<option value="${v.id}">${esc(v.name)} — ${esc(v.category)}</option>`).join('')}</select><small class="hint">Hold Ctrl/Cmd to select multiple vendors.</small></label><label>Notes<textarea id="rfq-notes" rows="3" placeholder="Delivery, warranty, payment terms or other requirements"></textarea></label><div id="rfq-preview" class="detail-note"><b>Select an approved purchase request</b><p>The request items will be included automatically.</p></div></div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="saveRFQ()"><i class="ti ti-device-floppy"></i> Create RFQ</button></div></div></div>`); if(requestId) loadRFQRequest() }
function loadRFQRequest(){const x=db(),r=x.requests.find(a=>a.id==document.getElementById('rfq-request')?.value),p=document.getElementById('rfq-preview');if(!r||!p){return}p.innerHTML=`<b>${esc(r.requestNo)} — ${esc(r.department)}</b>${table(['Product','Qty','Unit','Estimated Rate',purchaseTaxLabel(),'Total'],(r.lineItems||[]).map(i=>`<tr><td>${esc(i.productName)}</td><td>${i.quantity}</td><td>${esc(i.unit||'')}</td><td>${money(i.rate)}</td><td>${i.taxPercent==null?'—':i.taxPercent+'%'}</td><td>${money(i.total)}</td></tr>`).join(''))}<div class="request-summary"><span>Estimated Total</span><strong>${money(r.total)}</strong></div>`}
function saveRFQ(){const x=db(),rid=document.getElementById('rfq-request')?.value,r=x.requests.find(a=>a.id==rid),vids=[...document.getElementById('rfq-vendors').selectedOptions].map(o=>Number(o.value)),vendors=x.vendors.filter(v=>vids.includes(Number(v.id)));if(!r){toast('Select an approved purchase request');return}const existing=(x.rfqs||[]).find(q=>String(q.requestId)===String(r.id));if(existing){toast('An RFQ already exists for '+r.requestNo+' ('+existing.rfqNo+')');return}if(!vendors.length){toast('Select at least one vendor');return}const due=document.getElementById('rfq-due').value;if(!due){toast('Select quotation due date');return}const next=x.rfqs.length?Math.max(...x.rfqs.map(a=>Number(String(a.rfqNo).split('-').pop())||0))+1:1;x.rfqs.unshift({id:Date.now(),rfqNo:'RFQ-2026-'+String(next).padStart(3,'0'),requestId:r.id,requestNo:r.requestNo,department:r.department,issueDate:new Date().toISOString().slice(0,10),dueDate:due,vendors:vendors.map(v=>({id:v.id,name:v.name,email:v.email,contact:v.contact,trn:v.trn||''})),items:r.lineItems||[],estimatedTotal:r.total,notes:document.getElementById('rfq-notes').value.trim(),status:'Draft'});recordActivity(x,'Created','RFQs','RFQ created: RFQ-2026-'+String(next).padStart(3,'0'),'RFQ-2026-'+String(next).padStart(3,'0'));save(x);closeModal();renderRFQs();toast('RFQ created successfully')}
function sendRFQ(id){const x=db(),r=x.rfqs.find(a=>a.id===id);if(r){r.status='Sent';r.sentAt=new Date().toISOString();recordActivity(x,'Sent','RFQs','RFQ '+r.rfqNo+' sent to vendors',r.rfqNo);save(x);renderRFQs();toast('RFQ marked as sent to vendors')}}
function rfqDetails(id){const x=db(),r=x.rfqs.find(a=>a.id===id);if(!r)return;openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>${esc(r.rfqNo)}</h3><small>RFQ details</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="detail-grid"><div><span>Purchase Request</span><b>${esc(r.requestNo)}</b></div><div><span>Issue Date</span><b>${esc(r.issueDate)}</b></div><div><span>Due Date</span><b>${esc(r.dueDate)}</b></div><div><span>Status</span><b>${status(r.status)}</b></div></div><div class="detail-note"><b>Vendors</b><p>${esc((r.vendors||[]).map(v=>v.name).join(', '))}</p></div>${table(['Product','Description','Qty','Unit','Estimated Rate',purchaseTaxLabel(),'Total'],(r.items||[]).map(i=>`<tr><td>${esc(i.productName)}</td><td>${esc(i.description||'—')}</td><td>${i.quantity}</td><td>${esc(i.unit||'')}</td><td>${money(i.rate)}</td><td>${i.taxPercent==null?'—':i.taxPercent+'%'}</td><td>${money(i.total)}</td></tr>`).join(''))}<div class="request-summary"><span>Estimated Total</span><strong>${money(r.estimatedTotal)}</strong></div>${r.notes?`<div class="detail-note"><b>Notes</b><p>${esc(r.notes)}</p></div>`:''}</div><div class="modal-foot"><button class="btn-secondary" onclick="downloadRFQPDF(${r.id})"><i class="ti ti-file-type-pdf"></i> PDF</button><button class="btn-secondary" onclick="closeModal()">Close</button>${r.status==='Draft'?`<button class="btn-primary" onclick="closeModal();sendRFQ(${r.id})"><i class="ti ti-send"></i> Send RFQ</button>`:''}</div></div></div>`)}

function renderQuotations(){need();const x=db();const received=x.quotations.filter(q=>q.status==='Received').length;const draft=x.quotations.filter(q=>q.status==='Draft').length;const total=x.quotations.reduce((a,q)=>a+Number(q.total||0),0);layout('quotations','Vendor Quotations','Record and manage quotations received from vendors',`<div class="stats">${stat('Total Quotations',x.quotations.length,'ti-file-dollar')}${stat('Draft',draft,'ti-pencil')}${stat('Received',received,'ti-check')}${stat('Quoted Value',money(total),'ti-currency-dirham')}</div><div class="section-card"><div class="section-head"><div><div class="section-title">Vendor Quotations</div><div style="font-size:11px;color:#9CA3AF;margin-top:3px">Enter vendor offers against sent RFQs</div></div><button class="btn-primary" onclick="openQuotation()"><i class="ti ti-plus"></i> Add Quotation</button></div><div class="filters"><input id="quotation-search" placeholder="Search quotation, vendor or RFQ" oninput="filterQuotations()"><select id="quotation-status" onchange="filterQuotations()"><option value="">All Statuses</option><option>Draft</option><option>Received</option><option>Under Review</option><option>Selected</option><option>Rejected</option></select></div><div id="quotation-table">${quotationRows(x.quotations)}</div></div>`)}
function quotationPdfReady(x,q){return q.status!=='Rejected'}
function quotationRows(rows){
  const x=db();
  const total=rows.length;
  const pages=Math.max(1,Math.ceil(total/25));
  let page=Number(window.QUOTATION_PAGE||1);

  if(page<1) page=1;
  if(page>pages) page=pages;
  window.QUOTATION_PAGE=page;

  const start=(page-1)*25;
  const visible=rows.slice(start,start+25);

  const tableHtml=table(
    ['Quotation No.','RFQ No.','Vendor','Quote Date','Valid Until','Total','Status','Actions'],
    visible.map(q=>`<tr><td><button class="link-btn" onclick="quotationDetails(${q.id})">${esc(q.quotationNo)}</button></td><td>${esc(q.rfqNo||'—')}</td><td>${esc(q.vendorName||'—')}</td><td>${esc(q.quoteDate||'—')}</td><td>${esc(q.validUntil||'—')}</td><td><b>${money(q.total)}</b></td><td>${status(q.status)}</td><td><button class="btn-sm" onclick="quotationDetails(${q.id})"><i class="ti ti-eye"></i> View</button>${quotationPdfReady(x,q)?` <button class="btn-sm" onclick="downloadQuotationPdf(${q.id})"><i class="ti ti-file-type-pdf"></i> PDF</button>`:''}</td></tr>`).join('')
  );

  if(total<=25) return tableHtml;

  let pageButtons='';

  const addPage=(n)=>{
    pageButtons+=`<button class="pagination-page ${n===page?'active':''}" onclick="changeQuotationPage(${n})">${n}</button>`;
  };

  const addDots=()=>{
    pageButtons+=`<span class="pagination-dots">…</span>`;
  };

  if(pages<=5){
    for(let i=1;i<=pages;i++) addPage(i);
  }else if(page<=3){
    addPage(1);
    addPage(2);
    addPage(3);
    addDots();
    addPage(pages);
  }else if(page>=pages-2){
    addPage(1);
    addDots();
    addPage(pages-2);
    addPage(pages-1);
    addPage(pages);
  }else{
    addPage(1);
    addDots();
    addPage(page);
    addDots();
    addPage(pages);
  }

  const from=start+1;
  const to=Math.min(start+25,total);

  return tableHtml+`
    <div class="pagination">
      <div class="pagination-showing">Showing ${from}–${to} of ${total}</div>
      <div class="pagination-controls">
        <button class="pagination-arrow" ${page<=1?'disabled':''} onclick="changeQuotationPage(${page-1})">‹</button>
        ${pageButtons}
        <button class="pagination-arrow" ${page>=pages?'disabled':''} onclick="changeQuotationPage(${page+1})">›</button>
      </div>
    </div>
  `;
}

function filterQuotations(resetPage=true){
  if(resetPage) window.QUOTATION_PAGE=1;

  const x=db();
  const q=(document.getElementById('quotation-search')?.value||'').toLowerCase();
  const s=document.getElementById('quotation-status')?.value||'';

  const rows=x.quotations.filter(r=>
    (!q||(r.quotationNo+' '+r.rfqNo+' '+r.vendorName).toLowerCase().includes(q)) &&
    (!s||r.status===s)
  );

  const target=document.getElementById('quotation-table');
  if(target) target.innerHTML=quotationRows(rows);
}

function changeQuotationPage(page){
  window.QUOTATION_PAGE=page;
  filterQuotations(false);
}
function openQuotation(rfqId=null, vendorId=null){const x=db(),rfqs=x.rfqs.filter(r=>r.status==='Sent'||r.status==='Response Received');if(!rfqs.length){toast('Send an RFQ before recording a vendor quotation');return}openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>Add Vendor Quotation</h3><small>Record a vendor's commercial offer against an RFQ</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="grid2"><label>RFQ<select id="q-rfq" onchange="loadQuotationRFQ()"><option value="">Select sent RFQ</option>${rfqs.map(r=>`<option value="${r.id}" ${rfqId!=null&&String(rfqId)===String(r.id)?'selected':''}>${esc(r.rfqNo)} — ${esc(r.requestNo)} — ${esc((r.vendors||[]).map(v=>v.name).join(', '))}</option>`).join('')}</select></label><label>Vendor<select id="q-vendor" onchange="loadQuotationVendor()"><option value="">Select vendor</option></select></label><label>Quote Date<input id="q-date" type="date" value="${new Date().toISOString().slice(0,10)}"></label><label>Valid Until<input id="q-valid" type="date"></label></div><div id="q-items"><div class="detail-note"><b>Select an RFQ</b><p>The RFQ items will be loaded here.</p></div></div><div class="grid2"><label>Delivery Time<input id="q-delivery" placeholder="e.g. 7 days"></label><label>Payment Terms<input id="q-payment" placeholder="e.g. 30 days credit"></label></div><label>Notes<textarea id="q-notes" rows="3" placeholder="Warranty, delivery, exclusions, special terms..."></textarea></label><label>Quotation Attachment<input id="q-file" type="file" class="file-input" accept=".pdf"><small class="hint">PDF only, maximum file size 10 MB.</small></label></div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="saveQuotation()"><i class="ti ti-device-floppy"></i> Save Quotation</button></div></div></div>`); if(rfqId!=null){ loadQuotationRFQ(); if(vendorId!=null){ const v=document.getElementById('q-vendor'); if(v) v.value=String(vendorId); loadQuotationVendor(); } } }
function loadQuotationRFQ(){const x=db(),r=x.rfqs.find(a=>a.id==document.getElementById('q-rfq')?.value),v=document.getElementById('q-vendor'),box=document.getElementById('q-items');if(!r||!v)return;v.innerHTML='<option value="">Select vendor</option>'+(r.vendors||[]).map(a=>{const existing=(x.quotations||[]).find(q=>String(q.rfqId)===String(r.id)&&String(q.vendorId)===String(a.id));return `<option value="${a.id}">${esc(a.name)}${existing?' — quotation '+esc(existing.quotationNo)+' already recorded':''}</option>`}).join('');box.innerHTML=`<div class="items-head"><div><b>Quoted Items</b><small>Enter vendor rates, tax and discount for each item</small></div></div><div id="quotation-items">${quotationItemRows(r.items||[])}</div><div class="request-summary"><span>Quoted Total</span><strong id="quotation-total">${money(0)}</strong></div>`;recalcQuotation()}
function quotationItemRows(items){return items.map((i,n)=>`<div class="request-item quotation-item" data-index="${n}"><div class="item-grid"><div><label>Product / Service</label><input class="q-product" value="${esc(i.productName||'')}" readonly></div><div><label>Qty</label><input class="q-qty" type="number" value="${i.quantity||0}" readonly></div><div><label>Unit</label><input class="q-unit" value="${esc(i.unit||'')}" readonly></div><div><label>Quoted Rate</label><input class="q-rate" type="number" min="0" step="0.01" value="0" oninput="recalcQuotation()"></div><div><label>${esc(purchaseTaxLabel())} %</label><input class="q-tax" type="number" min="0" step="0.01" value="${purchaseTaxRate()}" oninput="recalcQuotation()"></div><div><label>Discount %</label><input class="q-discount" type="number" min="0" max="100" step="0.01" value="0" oninput="recalcQuotation()"></div><div class="item-total"><span>Line Total</span><b class="q-line-total">${money(0)}</b></div></div></div>`).join('')}
function loadQuotationVendor(){const rfqId=document.getElementById('q-rfq')?.value,v=document.getElementById('q-vendor')?.value;if(!rfqId||!v)return;const x=db(),r=x.rfqs.find(a=>a.id==rfqId),vendor=(r?.vendors||[]).find(a=>a.id==v);if(vendor)document.getElementById('q-notes').placeholder=`Quotation from ${vendor.name}: warranty, delivery, exclusions...`}
function recalcQuotation(){let total=0;document.querySelectorAll('#quotation-items .quotation-item').forEach(row=>{const qty=Number(row.querySelector('.q-qty').value||0),rate=Number(row.querySelector('.q-rate').value||0),tax=Number(row.querySelector('.q-tax').value||0),discount=Number(row.querySelector('.q-discount').value||0);const subtotal=qty*rate;const line=subtotal+(subtotal*tax/100)-(subtotal*discount/100);total+=line;row.querySelector('.q-line-total').textContent=money(line)});const out=document.getElementById('quotation-total');if(out)out.textContent=money(total)}
async function saveQuotation(){
  const x=db(),rfq=x.rfqs.find(a=>a.id==document.getElementById('q-rfq')?.value),vendor=(rfq?.vendors||[]).find(a=>a.id==document.getElementById('q-vendor')?.value);
  if(!rfq){toast('Select an RFQ');return}
  if(!vendor){toast('Select the vendor');return}

  const duplicate=x.quotations.find(q=>String(q.rfqId)===String(rfq.id)&&String(q.vendorId)===String(vendor.id));
  if(duplicate){toast(vendor.name+' already has quotation '+duplicate.quotationNo+' for this RFQ');return}

  const quoteDate=document.getElementById('q-date').value,validUntil=document.getElementById('q-valid').value;
  if(!quoteDate||!validUntil){toast('Enter quote date and validity date');return}

  const items=[...document.querySelectorAll('#quotation-items .quotation-item')].map((row,i)=>{
    const src=rfq.items[i],qty=Number(row.querySelector('.q-qty').value||0),rate=Number(row.querySelector('.q-rate').value||0),tax=Number(row.querySelector('.q-tax').value||0),discount=Number(row.querySelector('.q-discount').value||0),subtotal=qty*rate,line=subtotal+(subtotal*tax/100)-(subtotal*discount/100);
    return{productId:src.productId,productName:src.productName,description:src.description||'',quantity:qty,unit:src.unit,quotedRate:rate,taxPercent:tax,discountPercent:discount,subtotal,total:line}
  });

  if(items.some(i=>i.quotedRate<=0)){toast('Enter a quoted rate for every item');return}

  const file=document.getElementById('q-file')?.files?.[0];
  let attachment='',attachmentPath='';

  if(file){
    const saveButton=document.querySelector('.modal-foot .btn-primary');
    if(saveButton){
      saveButton.disabled=true;
      saveButton.innerHTML='<i class="ti ti-loader-2"></i> Uploading...';
    }

    try{
      const formData=new FormData();
      formData.append('file',file);

      // Browser-only demo: retain the attachment name without sending the file anywhere.
      const response={ok:true,json:async()=>({name:file.name,attachmentPath:''})};
      const result=await response.json().catch(()=>({}));

      if(!response.ok)throw new Error(result.error||'File upload failed');

      attachment=result.name||file.name;
      attachmentPath=result.attachmentPath||'';
    }catch(error){
      console.error('Quotation attachment upload failed:',error);
      toast(error.message||'File upload failed');
      if(saveButton){
        saveButton.disabled=false;
        saveButton.innerHTML='<i class="ti ti-device-floppy"></i> Save Quotation';
      }
      return;
    }
  }

  const total=items.reduce((a,i)=>a+i.total,0),next=x.quotations.length?Math.max(...x.quotations.map(a=>Number(String(a.quotationNo).split('-').pop())||0))+1:1;

  const quotation={
    id:Date.now(),
    quotationNo:'VQ-2026-'+String(next).padStart(3,'0'),
    rfqId:rfq.id,
    rfqNo:rfq.rfqNo,
    requestNo:rfq.requestNo,
    vendorId:vendor.id,
    vendorName:vendor.name,
    vendorContact:vendor.contact,
    vendorEmail:vendor.email,
    vendorTRN:vendor.trn||'',
    quoteDate,
    validUntil,
    items,
    total,
    deliveryTime:document.getElementById('q-delivery').value.trim(),
    paymentTerms:document.getElementById('q-payment').value.trim(),
    notes:document.getElementById('q-notes').value.trim(),
    attachment,
    attachmentPath,
    status:'Received'
  };

  x.quotations.unshift(quotation);
  rfq.status='Response Received';

  recordActivity(x,'Received','Vendor Quotations','Vendor quotation '+quotation.quotationNo+' recorded for '+rfq.rfqNo,quotation.quotationNo);
  save(x);
  closeModal();
  renderQuotations();
  toast('Vendor quotation recorded successfully');
}
function quotationDetails(id){const x=db(),q=x.quotations.find(a=>a.id===id);if(!q)return;const pdfReady=quotationPdfReady(x,q);openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>${esc(q.quotationNo)}</h3><small>${esc(q.vendorName)} — ${esc(q.rfqNo)}</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="detail-grid"><div><span>Vendor</span><b>${esc(q.vendorName)}</b></div><div><span>Vendor TRN</span><b>${esc(vendorTRN(x,q)||'—')}</b></div><div><span>RFQ</span><b>${esc(q.rfqNo)}</b></div><div><span>Quote Date</span><b>${esc(q.quoteDate)}</b></div><div><span>Valid Until</span><b>${esc(q.validUntil)}</b></div><div><span>Status</span><b>${status(q.status)}</b></div><div><span>Total</span><b>${money(q.total)}</b></div></div>${table(['Product','Qty','Rate','Tax','Discount','Total'],(q.items||[]).map(i=>`<tr><td>${esc(i.productName)}</td><td>${i.quantity}</td><td>${money(i.quotedRate)}</td><td>${i.taxPercent}%</td><td>${i.discountPercent}%</td><td><b>${money(i.total)}</b></td></tr>`).join(''))}<div class="detail-grid"><div><span>Delivery</span><b>${esc(q.deliveryTime||'—')}</b></div><div><span>Payment Terms</span><b>${esc(q.paymentTerms||'—')}</b></div></div>${q.notes?`<div class="detail-note"><b>Notes</b><p>${esc(q.notes)}</p></div>`:''}${q.attachment?`<div class="detail-note"><b>Attachment</b><p>${esc(q.attachment)} ${q.attachmentPath?`<button class="btn-sm" onclick="window.open('/api/quotation-attachments/'+encodeURIComponent('${esc(q.attachmentPath)}'),'_blank')"><i class="ti ti-eye"></i> View Attachment</button>`:''}</p></div>`:''}${pdfReady?`<div class="detail-note"><b>Quotation PDF Available</b><p>This quotation is linked to a sent RFQ and can be downloaded and shared with the vendor before quotation comparison.</p></div>`:''}</div><div class="modal-foot">${pdfReady?`<button class="btn-secondary" onclick="downloadQuotationPdf(${q.id})"><i class="ti ti-file-type-pdf"></i> Quotation PDF</button>`:''}<button class="btn-secondary" onclick="closeModal()">Close</button>${q.status==='Received'?`<button class="btn-primary" onclick="closeModal();location.href='comparison.html'"><i class="ti ti-scale"></i> Compare RFQ</button>`:''}</div></div></div>`) }
function invoiceEligiblePOs(x){return (x.orders||[]).filter(o=>['Sent to Vendor','Partially Received','Completed'].includes(o.status));}
function acceptedQtyForInvoice(x,poId,itemIndex){return (x.receipts||[]).filter(r=>String(r.poId)===String(poId)).reduce((sum,r)=>sum+Number(r.items?.[itemIndex]?.acceptedQty||0),0)}
function receivedValue(x,o){return (o.items||[]).reduce((sum,item,i)=>{const qty=acceptedQtyForInvoice(x,o.id,i);const base=qty*Number(item.rate||item.quotedRate||0);return sum+base+(base*Number(item.taxPercent||0)/100)-(base*Number(item.discountPercent||0)/100)},0)}
function receivedSubtotalValue(x,o){return (o.items||[]).reduce((sum,item,i)=>{const qty=acceptedQtyForInvoice(x,o.id,i);const base=qty*Number(item.rate||item.quotedRate||0);return sum+base-(base*Number(item.discountPercent||0)/100)},0)}
function receivedTaxValue(x,o){return (o.items||[]).reduce((sum,item,i)=>{const qty=acceptedQtyForInvoice(x,o.id,i);const base=qty*Number(item.rate||item.quotedRate||0);const net=base-(base*Number(item.discountPercent||0)/100);return sum+net*Number(item.taxPercent==null?purchaseTaxRate():item.taxPercent)/100},0)}
function invoiceMatch(x,inv){const po=(x.orders||[]).find(o=>String(o.id)===String(inv.poId));if(!po)return {status:'Exception',reason:'Purchase Order not found',po:null,received:0};const received=receivedValue(x,po),amount=Number(inv.amount||0),poTotal=Number(po.total||0),tol=0.01;let status='Matched',reason='PO and accepted GRN value match the invoice';if(received<=tol){status='Exception';reason='No accepted goods are available for this PO';}else if(Math.abs(amount-received)>tol){status='Exception';reason=`Invoice ${money(amount)} differs from accepted GRN value ${money(received)}`;}else if(Math.abs(amount-poTotal)>tol){status='Exception';reason=`Invoice ${money(amount)} differs from PO total ${money(poTotal)}`;}return {status,reason,po,received};}
function renderInvoices(){need();const x=db(),invs=x.invoices||[],unpaid=invs.filter(i=>i.status!=='Paid').length,matched=invs.filter(i=>i.matchStatus==='Matched').length,exceptions=invs.filter(i=>i.matchStatus==='Exception').length,total=invs.reduce((a,i)=>a+Number(i.amount||0),0);layout('invoices','Vendor Invoices','Record vendor invoices and validate them against Purchase Orders and Goods Receipts',`<div class="stats">${stat('Total Invoices',invs.length,'ti-receipt')}${stat('Unpaid',unpaid,'ti-clock')}${stat('3-Way Matched',matched,'ti-circle-check')}${stat('Exceptions',exceptions,'ti-alert-triangle')}</div><div class="section-card"><div class="section-head"><div><div class="section-title">Vendor Invoices</div><div style="font-size:11px;color:#9CA3AF;margin-top:3px">3-way match: Purchase Order vs accepted Goods Receipt vs Vendor Invoice</div></div><button class="btn-primary" onclick="openInvoice()"><i class="ti ti-plus"></i> Add Vendor Invoice</button></div><div class="filters"><input id="invoice-search" placeholder="Search invoice, PO or vendor" oninput="filterInvoices()"><select id="invoice-status" onchange="filterInvoices()"><option value="">All Statuses</option><option>Draft</option><option>Matched</option><option>Exception</option><option>Approved</option><option>Paid</option></select></div><div id="invoice-table">${invoiceRows(invs)}</div></div>`)}
function invoiceRows(rows){
  const total=rows.length;
  const pages=Math.max(1,Math.ceil(total/25));
  let page=Number(window.INVOICE_PAGE||1);

  if(page<1) page=1;
  if(page>pages) page=pages;
  window.INVOICE_PAGE=page;

  const start=(page-1)*25;
  const visible=rows.slice(start,start+25);

  const tableHtml=table(
    ['Invoice No.','PO No.','Vendor','Invoice Date','Due Date','Amount','3-Way Match','Status','Actions'],
    visible.map(i=>`<tr><td><button class="link-btn" onclick="invoiceDetails(${i.id})">${esc(i.invoiceNo)}</button></td><td>${esc(i.poNo||'—')}</td><td>${esc(i.vendorName||'—')}</td><td>${esc(i.invoiceDate||'—')}</td><td>${esc(i.dueDate||'—')}</td><td><b>${money(i.amount)}</b></td><td>${status(i.matchStatus||'Pending')}</td><td>${status(i.status||'Draft')}</td><td><button class="btn-sm" onclick="invoiceDetails(${i.id})"><i class="ti ti-eye"></i> View</button> <button class="btn-sm" onclick="downloadInvoicePdf(${i.id})"><i class="ti ti-file-type-pdf"></i> PDF</button></td></tr>`).join('')
  );

  if(total<=25) return tableHtml;

  let pageButtons='';

  const addPage=(n)=>{
    pageButtons+=`<button class="pagination-page ${n===page?'active':''}" onclick="changeInvoicePage(${n})">${n}</button>`;
  };

  const addDots=()=>{
    pageButtons+=`<span class="pagination-dots">…</span>`;
  };

  if(pages<=5){
    for(let i=1;i<=pages;i++) addPage(i);
  }else if(page<=3){
    addPage(1);
    addPage(2);
    addPage(3);
    addDots();
    addPage(pages);
  }else if(page>=pages-2){
    addPage(1);
    addDots();
    addPage(pages-2);
    addPage(pages-1);
    addPage(pages);
  }else{
    addPage(1);
    addDots();
    addPage(page);
    addDots();
    addPage(pages);
  }

  const from=start+1;
  const to=Math.min(start+25,total);

  return tableHtml+`
    <div class="pagination">
      <div class="pagination-showing">Showing ${from}–${to} of ${total}</div>
      <div class="pagination-controls">
        <button class="pagination-arrow" ${page<=1?'disabled':''} onclick="changeInvoicePage(${page-1})">‹</button>
        ${pageButtons}
        <button class="pagination-arrow" ${page>=pages?'disabled':''} onclick="changeInvoicePage(${page+1})">›</button>
      </div>
    </div>
  `;
}

function filterInvoices(resetPage=true){
  if(resetPage) window.INVOICE_PAGE=1;

  const x=db();
  const q=(document.getElementById('invoice-search')?.value||'').toLowerCase();
  const st=document.getElementById('invoice-status')?.value||'';

  const rows=(x.invoices||[]).filter(i=>
    (!q||(i.invoiceNo+' '+i.poNo+' '+i.vendorName).toLowerCase().includes(q)) &&
    (!st||i.status===st)
  );

  const target=document.getElementById('invoice-table');
  if(target) target.innerHTML=invoiceRows(rows);
}

function changeInvoicePage(page){
  window.INVOICE_PAGE=page;
  filterInvoices(false);
}

function openInvoice(){const x=db(),pos=invoiceEligiblePOs(x);if(!pos.length){toast('No purchase orders are available for invoicing');return}openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>Add Vendor Invoice</h3><small>Enter the supplier invoice and validate it against PO and accepted GRN quantities</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="grid2"><label>Purchase Order<select id="inv-po" onchange="loadInvoicePO()"><option value="">Select PO</option>${pos.map(o=>`<option value="${o.id}">${esc(o.poNo)} — ${esc(o.vendorName)} — ${money(o.total)}</option>`).join('')}</select></label><label>Invoice Number<input id="inv-no" placeholder="Vendor invoice number"></label><label>Invoice Date<input id="inv-date" type="date" value="${new Date().toISOString().slice(0,10)}"></label><label>Due Date<input id="inv-due" type="date"></label><label>Invoice Subtotal (before ${esc(purchaseTaxLabel())})<input id="inv-subtotal" type="number" min="0" step="0.01" oninput="recalcInvoiceTotal()"></label><label>${esc(purchaseTaxLabel())} %<input id="inv-tax" type="number" min="0" step="0.01" value="${purchaseTaxRate()}" oninput="recalcInvoiceTotal()"></label><label>Invoice Total (incl. ${esc(purchaseTaxLabel())})<input id="inv-amount" type="number" min="0" step="0.01" readonly></label><label>Vendor Reference<input id="inv-ref" placeholder="Supplier reference / bill reference"></label></div><div id="invoice-preview"><div class="detail-note"><b>Select a Purchase Order</b><p>The PO, accepted GRN value and 3-way match result will appear here.</p></div></div><label>Notes<textarea id="inv-notes" rows="3" placeholder="Invoice notes or exception reason..."></textarea></label></div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="saveInvoice()"><i class="ti ti-device-floppy"></i> Save Invoice</button></div></div></div>`);loadInvoicePO()}
function loadInvoicePO(){const x=db(),o=x.orders.find(a=>String(a.id)===String(document.getElementById('inv-po')?.value)),box=document.getElementById('invoice-preview');if(!box)return;if(!o){box.innerHTML='<div class="detail-note"><b>Select a Purchase Order</b><p>The PO, accepted GRN value and 3-way match result will appear here.</p></div>';return}const received=receivedValue(x,o),receivedSubtotal=receivedSubtotalValue(x,o),receivedTax=receivedTaxValue(x,o),acceptedItems=(o.items||[]).map((item,i)=>({item,qty:acceptedQtyForInvoice(x,o.id,i)})).filter(a=>a.qty>0);const defaultTax=receivedSubtotal>0?Math.round((receivedTax/receivedSubtotal)*10000)/100:purchaseTaxRate();document.getElementById('inv-subtotal').value=receivedSubtotal.toFixed(2);document.getElementById('inv-tax').value=defaultTax;box.innerHTML=`<div class="detail-grid"><div><span>Vendor</span><b>${esc(o.vendorName)}</b></div><div><span>PO</span><b>${esc(o.poNo)}</b></div><div><span>PO Total</span><b>${money(o.total)}</b></div><div><span>Accepted GRN Value</span><b>${money(received)}</b></div><div><span>${esc(purchaseTaxLabel())}</span><b>${defaultTax}%</b></div></div>${table(['Item','Accepted Qty','Rate','Line Value'],acceptedItems.length?acceptedItems.map(a=>`<tr><td>${esc(a.item.productName)}</td><td>${a.qty} ${esc(a.item.unit||'')}</td><td>${money(a.item.rate||a.item.quotedRate)}</td><td><b>${money(a.qty*Number(a.item.rate||a.item.quotedRate||0))}</b></td></tr>`).join(''):'<tr><td colspan="4">No accepted quantities found.</td></tr>')}<div id="invoice-match-preview" class="request-summary"><span>Invoice Total</span><strong></strong></div>`;recalcInvoiceTotal()}
function recalcInvoiceTotal(){const sub=Number(document.getElementById('inv-subtotal')?.value||0),tax=Number(document.getElementById('inv-tax')?.value||0),amount=Math.max(0,sub+(sub*tax/100)),out=document.getElementById('inv-amount');if(out)out.value=amount.toFixed(2);previewInvoiceMatch()}
function previewInvoiceMatch(){const x=db(),po=x.orders.find(a=>String(a.id)===String(document.getElementById('inv-po')?.value)),out=document.getElementById('invoice-match-preview');if(!po||!out)return;const amount=Number(document.getElementById('inv-amount')?.value||0),received=receivedValue(x,po);let ok=amount>0&&Math.abs(amount-received)<=0.01&&Math.abs(amount-Number(po.total||0))<=0.01;out.innerHTML=`<span>3-Way Match</span><strong class="${ok?'text-success':'text-danger'}">${ok?'Matched':'Exception'} · PO ${money(po.total)} · GRN ${money(received)} · Invoice ${money(amount)}</strong>`}
function saveInvoice(){const x=db(),po=x.orders.find(a=>String(a.id)===String(document.getElementById('inv-po')?.value));if(!po){toast('Select a purchase order');return}const invoiceNo=document.getElementById('inv-no').value.trim(),invoiceDate=document.getElementById('inv-date').value,dueDate=document.getElementById('inv-due').value,subtotal=Number(document.getElementById('inv-subtotal').value||0),taxPercent=Number(document.getElementById('inv-tax').value||0),amount=Number(document.getElementById('inv-amount').value||0);if(!invoiceNo||!invoiceDate||!dueDate||amount<=0){toast('Enter invoice number, dates and a valid amount');return}if((x.invoices||[]).some(i=>String(i.invoiceNo).toLowerCase()===invoiceNo.toLowerCase())){toast('An invoice with this number already exists');return}const nextMatch=invoiceMatch(x,{poId:po.id,amount}),next=(x.invoices||[]).length?Math.max(...x.invoices.map(a=>Number(String(a.id).replace(/\D/g,''))||0))+1:Date.now();x.invoices=x.invoices||[];x.invoices.unshift({id:next,invoiceNo,poId:po.id,poNo:po.poNo,quotationId:po.quotationId,rfqNo:po.rfqNo,requestNo:po.requestNo,vendorId:po.vendorId,vendorName:po.vendorName,vendorEmail:po.vendorEmail,invoiceDate,dueDate,subtotal,taxPercent,taxAmount:amount-subtotal,amount,referenceNo:document.getElementById('inv-ref').value.trim(),notes:document.getElementById('inv-notes').value.trim(),matchStatus:nextMatch.status,matchReason:nextMatch.reason,status:nextMatch.status==='Matched'?'Matched':'Exception',createdAt:new Date().toISOString()});recordActivity(x,'Created','Vendor Invoices','Vendor invoice '+invoiceNo+' recorded','Invoice');save(x);closeModal();renderInvoices();toast(nextMatch.status==='Matched'?'Invoice saved and 3-way matched':'Invoice saved with a 3-way match exception')}
function invoiceDetails(id){const x=db(),i=(x.invoices||[]).find(a=>a.id===id);if(!i)return;const m=invoiceMatch(x,i);openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>${esc(i.invoiceNo)}</h3><small>${esc(i.vendorName)} — ${esc(i.poNo)}</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="detail-grid"><div><span>Invoice No.</span><b>${esc(i.invoiceNo)}</b></div><div><span>Vendor</span><b>${esc(i.vendorName)}</b></div><div><span>Invoice Date</span><b>${esc(i.invoiceDate)}</b></div><div><span>Due Date</span><b>${esc(i.dueDate)}</b></div><div><span>PO Total</span><b>${money(m.po?.total||0)}</b></div><div><span>Accepted GRN Value</span><b>${money(m.received)}</b></div><div><span>Invoice Subtotal</span><b>${money(i.subtotal??i.amount)}</b></div><div><span>${esc(purchaseTaxLabel())}</span><b>${Number(i.taxPercent==null?purchaseTaxRate():i.taxPercent)}%</b></div><div><span>${esc(purchaseTaxLabel())} Amount</span><b>${money(i.taxAmount??Math.max(0,Number(i.amount||0)-Number(i.subtotal??i.amount)))}</b></div><div><span>Invoice Amount</span><b>${money(i.amount)}</b></div><div><span>3-Way Match</span><b>${status(i.matchStatus||m.status)}</b></div><div><span>Status</span><b>${status(i.status)}</b></div><div><span>Reference</span><b>${esc(i.referenceNo||'—')}</b></div></div><div class="detail-note ${i.matchStatus==='Matched'?'':'comparison-warning'}"><b>${i.matchStatus==='Matched'?'3-Way Match Passed':'3-Way Match Exception'}</b><p>${esc(i.matchReason||m.reason)}</p></div>${i.notes?`<div class="detail-note"><b>Notes</b><p>${esc(i.notes)}</p></div>`:''}</div><div class="modal-foot"><button class="btn-secondary" onclick="downloadInvoicePdf(${i.id})"><i class="ti ti-file-type-pdf"></i> PDF</button><button class="btn-secondary" onclick="closeModal()">Close</button>${i.status==='Matched'?`<button class="btn-primary" onclick="approveInvoice(${i.id})"><i class="ti ti-check"></i> Approve Invoice</button>`:''}</div></div></div>`)}
function approveInvoice(id){const x=db(),i=(x.invoices||[]).find(a=>a.id===id);if(!i)return;if(i.matchStatus!=='Matched'){toast('Only 3-way matched invoices can be approved');return}i.status='Approved';i.approvedAt=new Date().toISOString();recordActivity(x,'Approved','Vendor Invoices',i.invoiceNo+' approved',i.invoiceNo);save(x);closeModal();renderInvoices();toast('Vendor invoice approved')}

function setQuotationStatus(id,newStatus){const x=db(),q=x.quotations.find(a=>a.id===id);if(!q)return;q.status=newStatus;recordActivity(x,'Updated','Vendor Quotations',q.quotationNo+' marked as '+newStatus,q.quotationNo);save(x);closeModal();renderQuotations();toast('Quotation marked as '+newStatus)}

function activityRows(rows){
  const total=rows.length;
  const pages=Math.max(1,Math.ceil(total/25));
  let page=Number(window.ACTIVITY_PAGE||1);

  if(page<1) page=1;
  if(page>pages) page=pages;
  window.ACTIVITY_PAGE=page;

  const start=(page-1)*25;
  const visible=rows.slice(start,start+25);

  const tableHtml=table(
    ['Date & Time','User','Role','Module','Action','Details'],
    visible.map(a=>`<tr><td>${esc(new Date(a.createdAt).toLocaleString())}</td><td><b>${esc(a.userName||'Unknown')}</b><br><small>${esc(a.userEmail||'')}</small></td><td>${esc(a.role||'')}</td><td>${esc(a.module||'')}</td><td><span class="badge">${esc(a.action||'')}</span></td><td>${esc(a.details||'')}</td></tr>`).join('')
  );

  if(total<=25) return tableHtml;

  let pageButtons='';

  const addPage=(n)=>{
    pageButtons+=`<button class="pagination-page ${n===page?'active':''}" onclick="changeActivityPage(${n})">${n}</button>`;
  };

  const addDots=()=>{
    pageButtons+=`<span class="pagination-dots">…</span>`;
  };

  if(pages<=5){
    for(let i=1;i<=pages;i++) addPage(i);
  }else if(page<=3){
    addPage(1);
    addPage(2);
    addPage(3);
    addDots();
    addPage(pages);
  }else if(page>=pages-2){
    addPage(1);
    addDots();
    addPage(pages-2);
    addPage(pages-1);
    addPage(pages);
  }else{
    addPage(1);
    addDots();
    addPage(page);
    addDots();
    addPage(pages);
  }

  const from=start+1;
  const to=Math.min(start+25,total);

  return tableHtml+`
    <div class="pagination">
      <div class="pagination-showing">Showing ${from}–${to} of ${total}</div>
      <div class="pagination-controls">
        <button class="pagination-arrow" ${page<=1?'disabled':''} onclick="changeActivityPage(${page-1})">‹</button>
        ${pageButtons}
        <button class="pagination-arrow" ${page>=pages?'disabled':''} onclick="changeActivityPage(${page+1})">›</button>
      </div>
    </div>
  `;
}

function renderActivities(){need();if(!guard('activities'))return;const x=db(),u=currentUser(),rows=(x.activities||[]).filter(a=>u?.role==='Admin'||String(a.userId)===String(u?.id)||(!a.userId&&a.userEmail===u?.email));layout('activities','Activity Log','Track all recorded activity across the purchase management system',`<div class="stats">${stat('Activities',rows.length,'ti-activity')}${stat('Today',rows.filter(a=>new Date(a.createdAt).toDateString()===new Date().toDateString()).length,'ti-calendar-event')}${stat('User',u?.role==='Admin'?'All Users':u?.name,'ti-user')}${stat('Access',u?.role==='Admin'?'All Activities':'My Activities','ti-shield-check')}</div><div class="section-card"><div class="section-head"><div><div class="section-title">${u?.role==='Admin'?'All User Activities':'My Activities'}</div><div style="font-size:11px;color:#9CA3AF;margin-top:3px">${u?.role==='Admin'?'You can review activity performed by every user.':'You can only view activity performed by your own account.'}</div></div></div><div class="filters"><input id="activity-search" placeholder="Search user, module, action or details" oninput="filterActivities()"><select id="activity-module" onchange="filterActivities()"><option value="">All Modules</option>${[...new Set(rows.map(a=>a.module).filter(Boolean))].sort().map(m=>`<option>${esc(m)}</option>`).join('')}</select><select id="activity-action" onchange="filterActivities()"><option value="">All Actions</option>${[...new Set(rows.map(a=>a.action).filter(Boolean))].sort().map(a=>`<option>${esc(a)}</option>`).join('')}</select></div><div id="activity-table">${activityRows(rows)}</div></div>`)}

function filterActivities(resetPage=true){
  if(resetPage) window.ACTIVITY_PAGE=1;

  const x=db();
  const u=currentUser();
  const q=(document.getElementById('activity-search')?.value||'').toLowerCase();
  const m=document.getElementById('activity-module')?.value||'';
  const act=document.getElementById('activity-action')?.value||'';

  let rows=(x.activities||[]).filter(a=>
    u?.role==='Admin' ||
    String(a.userId)===String(u?.id) ||
    (!a.userId&&a.userEmail===u?.email)
  );

  rows=rows.filter(a=>
    (!q||(a.userName+' '+a.userEmail+' '+a.module+' '+a.action+' '+a.details).toLowerCase().includes(q)) &&
    (!m||a.module===m) &&
    (!act||a.action===act)
  );

  const target=document.getElementById('activity-table');
  if(target) target.innerHTML=activityRows(rows);
}

function changeActivityPage(page){
  window.ACTIVITY_PAGE=page;
  filterActivities(false);
}

function renderOrders(){
 need();const x=db(),orders=x.orders||[];const draft=orders.filter(o=>o.status==='Draft').length,approved=orders.filter(o=>o.status==='Approved').length,open=orders.filter(o=>!['Completed','Cancelled'].includes(o.status)).length,total=orders.reduce((a,o)=>a+Number(o.total||0),0);
 layout('orders','Purchase Orders','Create and manage purchase orders from quotations or direct purchases',`<div class="stats">${stat('Total POs',orders.length,'ti-shopping-cart')}${stat('Draft',draft,'ti-pencil')}${stat('Approved',approved,'ti-circle-check')}${stat('Open POs',open,'ti-truck-delivery')}</div><div class="section-card"><div class="section-head"><div><div class="section-title">Purchase Orders</div><div style="font-size:11px;color:#9CA3AF;margin-top:3px">Purchase orders are created from quotations selected in Quotation Comparison</div></div><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn-secondary" onclick="openDirectPO()"><i class="ti ti-plus"></i> Direct PO</button><button class="btn-primary" onclick="openPO()"><i class="ti ti-plus"></i> Create PO</button></div></div><div class="filters"><input id="po-search" placeholder="Search PO, vendor, RFQ or request" oninput="filterOrders()"><select id="po-status" onchange="filterOrders()"><option value="">All Statuses</option><option>Draft</option><option>Approved</option><option>Sent to Vendor</option><option>Partially Received</option><option>Completed</option><option>Cancelled</option></select></div><div id="po-table">${orderRows(orders)}</div></div>`);
}
function orderRows(rows){
  const total=rows.length;
  const pages=Math.max(1,Math.ceil(total/25));
  let page=Number(window.ORDER_PAGE||1);

  if(page<1) page=1;
  if(page>pages) page=pages;
  window.ORDER_PAGE=page;

  const start=(page-1)*25;
  const visible=rows.slice(start,start+25);

  const tableHtml=table(
    ['PO No.','Source','RFQ / Request','Vendor','PO Date','Delivery','Total','Status','Actions'],
    visible.map(o=>`<tr><td><button class="link-btn" onclick="orderDetails(${o.id})">${esc(o.poNo)}</button></td><td>${esc(o.source||'Purchase Request')}</td><td>${esc(o.rfqNo||'—')}<br><small style="color:#9CA3AF">${esc(o.requestNo||'')}</small></td><td>${esc(o.vendorName||'—')}</td><td>${esc(o.poDate||'—')}</td><td>${esc(o.deliveryDate||o.deliveryTime||'—')}</td><td><b>${money(o.total)}</b></td><td>${status(o.status)}</td><td><button class="btn-sm" onclick="orderDetails(${o.id})"><i class="ti ti-eye"></i> View</button> <button class="btn-sm" onclick="downloadPOPdf(${o.id})"><i class="ti ti-file-type-pdf"></i> PDF</button></td></tr>`).join('')
  );

  if(total<=25) return tableHtml;

  let pageButtons='';

  const addPage=(n)=>{
    pageButtons+=`<button class="pagination-page ${n===page?'active':''}" onclick="changeOrderPage(${n})">${n}</button>`;
  };

  const addDots=()=>{
    pageButtons+=`<span class="pagination-dots">…</span>`;
  };

  if(pages<=5){
    for(let i=1;i<=pages;i++) addPage(i);
  }else if(page<=3){
    addPage(1);
    addPage(2);
    addPage(3);
    addDots();
    addPage(pages);
  }else if(page>=pages-2){
    addPage(1);
    addDots();
    addPage(pages-2);
    addPage(pages-1);
    addPage(pages);
  }else{
    addPage(1);
    addDots();
    addPage(page);
    addDots();
    addPage(pages);
  }

  const from=start+1;
  const to=Math.min(start+25,total);

  return tableHtml+`
    <div class="pagination">
      <div class="pagination-showing">Showing ${from}–${to} of ${total}</div>
      <div class="pagination-controls">
        <button class="pagination-arrow" ${page<=1?'disabled':''} onclick="changeOrderPage(${page-1})">‹</button>
        ${pageButtons}
        <button class="pagination-arrow" ${page>=pages?'disabled':''} onclick="changeOrderPage(${page+1})">›</button>
      </div>
    </div>
  `;
}

function filterOrders(resetPage=true){
  if(resetPage) window.ORDER_PAGE=1;

  const x=db();
  const q=(document.getElementById('po-search')?.value||'').toLowerCase();
  const st=document.getElementById('po-status')?.value||'';

  const rows=(x.orders||[]).filter(o=>
    (!q||(o.poNo+' '+o.vendorName+' '+o.rfqNo+' '+o.requestNo).toLowerCase().includes(q)) &&
    (!st||o.status===st)
  );

  const target=document.getElementById('po-table');
  if(target) target.innerHTML=orderRows(rows);
}

function changeOrderPage(page){
  window.ORDER_PAGE=page;
  filterOrders(false);
}

function openPO(){
 openPOFromQuotation();
}
function openPOFromQuotation(){
 const x=db(),selected=(x.quotations||[]).filter(q=>q.status==='Selected').filter(q=>!(x.orders||[]).some(o=>String(o.quotationId)===String(q.id)));
 if(!selected.length){toast('No selected quotations are available for PO creation');return}
 openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>Create Purchase Order</h3><small>Create a PO from a selected vendor quotation</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="grid2"><label>Selected Quotation<select id="po-quotation" onchange="loadPODetails()"><option value="">Select quotation</option>${selected.map(q=>`<option value="${q.id}">${esc(q.quotationNo)} — ${esc(q.vendorName)} — ${money(q.total)}</option>`).join('')}</select></label><label>PO Date<input id="po-date" type="date" value="${new Date().toISOString().slice(0,10)}"></label><label>Expected Delivery Date<input id="po-delivery-date" type="date"></label><label>Delivery Location<input id="po-location" placeholder="e.g. Main Store / Head Office"></label></div><div id="po-preview"><div class="detail-note"><b>Select a quotation</b><p>Vendor and quoted items will be loaded here.</p></div></div><div class="grid2"><label>Shipping / Other Charges<input id="po-shipping" type="number" min="0" step="0.01" value="0" oninput="recalcPO()"></label><label>Additional Discount<input id="po-extra-discount" type="number" min="0" step="0.01" value="0" oninput="recalcPO()"></label></div><label>Terms & Conditions<textarea id="po-terms" rows="16">${esc(defaultPOTerms())}</textarea></label></div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="savePO()"><i class="ti ti-device-floppy"></i> Create Purchase Order</button></div></div></div>`);
 loadPODetails()
}
function directPOItemRow(i=0,item={}){
 const x=db();
 return `<div class="request-item direct-po-item" data-item="${i}"><div class="item-grid"><label>Product / Service<select class="dpo-product" onchange="syncDirectPORate(this)"><option value="">Select product / service</option>${x.products.map(p=>`<option value="${p.id}" data-rate="${p.rate}" data-unit="${esc(p.unit||'Each')}" ${String(item.productId)===String(p.id)?'selected':''}>${esc(p.name)} (${esc(p.sku)})</option>`).join('')}</select></label><label>Description<input class="dpo-desc" value="${esc(item.description||'')}" placeholder="Optional specification"></label><label>Quantity<input class="dpo-qty" type="number" min="0.01" step="0.01" value="${item.quantity||1}" oninput="recalcDirectPO()"></label><label>Unit Price<input class="dpo-rate" type="number" min="0" step="0.01" value="${item.rate||0}" oninput="recalcDirectPO()"></label><label>${esc(purchaseTaxLabel())} %<input class="dpo-tax" type="number" min="0" step="0.01" value="${item.taxPercent==null?purchaseTaxRate():item.taxPercent}" oninput="recalcDirectPO()"></label><label>Discount %<input class="dpo-discount" type="number" min="0" step="0.01" value="${item.discountPercent||0}" oninput="recalcDirectPO()"></label><label>Unit<select class="dpo-unit"><option>Each</option><option>Box</option><option>Pack</option><option>Carton</option><option>Kg</option><option>Liter</option><option>Service</option></select></label><div class="item-total"><span>Total</span><b class="dpo-total">${money(item.total||0)}</b></div></div><button type="button" class="remove-item" onclick="removeDirectPOItem(this)" title="Remove item"><i class="ti ti-trash"></i></button></div>`
}
function openDirectPO(){
 const x=db(),vendors=(x.vendors||[]).filter(v=>v.status!=='Inactive');
 if(!vendors.length){toast('Add an active vendor before creating a direct PO');return}
 openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>Create Direct Purchase Order</h3><small>Create a PO without a Purchase Request, RFQ or quotation</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="grid2"><label>Vendor *<select id="dpo-vendor" onchange="loadDirectPOVendor()"><option value="">Select Vendor</option>${vendors.map(v=>`<option value="${v.id}">${esc(v.name)}</option>`).join('')}</select></label><label>PO Date *<input id="dpo-date" type="date" value="${new Date().toISOString().slice(0,10)}"></label><label>Expected Delivery Date<input id="dpo-delivery-date" type="date"></label><label>Reference<input id="dpo-reference" placeholder="Optional supplier/internal reference"></label><label>Delivery Location<input id="dpo-location" placeholder="e.g. Main Store / Head Office"></label><label>Payment Terms<select id="dpo-payment"><option value="">Select payment terms</option><option>Cash on Delivery</option><option>Advance Payment</option><option>7 Days</option><option>15 Days</option><option>30 Days</option><option>45 Days</option><option>60 Days</option><option>Other</option></select></label><label>Delivery Terms<select id="dpo-delivery-terms"><option value="">Select delivery terms</option><option>Supplier Delivery</option><option>Ex-Works</option><option>FOB</option><option>CIF</option><option>Other</option></select></label></div><div id="dpo-vendor-preview"></div><div class="items-head"><div><b>Items</b><small>Add products or services, quantities and pricing</small></div><button type="button" class="btn-secondary" onclick="addDirectPOItem()"><i class="ti ti-plus"></i> Add Item</button></div><div id="direct-po-items">${directPOItemRow(0,{})}</div><div class="grid2"><label>Shipping / Other Charges<input id="dpo-shipping" type="number" min="0" step="0.01" value="0" oninput="recalcDirectPO()"></label><label>Additional Discount<input id="dpo-extra-discount" type="number" min="0" step="0.01" value="0" oninput="recalcDirectPO()"></label></div><div class="po-totals"><div><span>Subtotal</span><b id="dpo-subtotal">${money(0)}</b></div><div><span>Tax</span><b id="dpo-tax-total">${money(0)}</b></div><div><span>Shipping / Other</span><b id="dpo-shipping-total">${money(0)}</b></div><div><span>Additional / Line Discount</span><b id="dpo-discount-total">${money(0)}</b></div><div class="grand"><span>Grand Total</span><b id="dpo-grand-total">${money(0)}</b></div></div><label>Terms & Conditions<textarea id="dpo-terms" rows="16">${esc(defaultPOTerms())}</textarea></label><label>Notes<textarea id="dpo-notes" rows="3" placeholder="Notes, specifications or instructions for the vendor..."></textarea></label><label>Attachment<input id="dpo-file" type="file" class="file-input" accept=".pdf"><small class="hint">The attachment filename is saved with the PO.</small></label></div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="saveDirectPO()"><i class="ti ti-device-floppy"></i> Create Direct PO</button></div></div></div>`);
 recalcDirectPO()
}
function loadDirectPOVendor(){const x=db(),v=(x.vendors||[]).find(v=>String(v.id)===String(document.getElementById('dpo-vendor')?.value)),box=document.getElementById('dpo-vendor-preview');if(box)box.innerHTML=v?`<div class="detail-note"><b>${esc(v.name)}</b><p>${esc(v.contact||'')} · ${esc(v.email||'')} · ${esc(v.phone||'')}</p></div>`:''}
function addDirectPOItem(){const wrap=document.getElementById('direct-po-items');wrap.insertAdjacentHTML('beforeend',directPOItemRow(wrap.children.length,{}));recalcDirectPO()}
function removeDirectPOItem(btn){const rows=document.querySelectorAll('#direct-po-items .direct-po-item');if(rows.length===1){toast('At least one item is required');return}btn.closest('.direct-po-item').remove();recalcDirectPO()}
function syncDirectPORate(sel){const opt=sel.selectedOptions[0],row=sel.closest('.direct-po-item');if(opt?.dataset.rate&&Number(row.querySelector('.dpo-rate').value)===0)row.querySelector('.dpo-rate').value=opt.dataset.rate;if(opt?.dataset.unit)row.querySelector('.dpo-unit').value=opt.dataset.unit;recalcDirectPO()}
function directPOLineData(){return [...document.querySelectorAll('#direct-po-items .direct-po-item')].map(row=>{const p=row.querySelector('.dpo-product'),opt=p.selectedOptions[0],qty=Number(row.querySelector('.dpo-qty').value||0),rate=Number(row.querySelector('.dpo-rate').value||0),taxPercent=Number(row.querySelector('.dpo-tax').value||0),discountPercent=Number(row.querySelector('.dpo-discount').value||0),base=qty*rate,discount=base*discountPercent/100,tax=(base-discount)*taxPercent/100,total=Math.max(0,base-discount+tax);return {productId:p.value||null,productName:opt?.textContent?.split(' (')[0]||'',description:row.querySelector('.dpo-desc').value.trim(),quantity:qty,rate,unit:row.querySelector('.dpo-unit').value,taxPercent,discountPercent,total,base,discount,tax}})}
function recalcDirectPO(){const items=directPOLineData(),subtotal=items.reduce((a,i)=>a+i.base,0),lineDiscount=items.reduce((a,i)=>a+i.discount,0),tax=items.reduce((a,i)=>a+i.tax,0),shipping=Number(document.getElementById('dpo-shipping')?.value||0),extraDiscount=Number(document.getElementById('dpo-extra-discount')?.value||0),grand=Math.max(0,subtotal-lineDiscount+tax+shipping-extraDiscount);document.querySelectorAll('#direct-po-items .direct-po-item').forEach((row,i)=>{const out=row.querySelector('.dpo-total');if(out)out.textContent=money(items[i]?.total||0)});const set=(id,v)=>{const el=document.getElementById(id);if(el)el.textContent=money(v)};set('dpo-subtotal',subtotal);set('dpo-tax-total',tax);set('dpo-shipping-total',shipping);set('dpo-discount-total',lineDiscount+extraDiscount);set('dpo-grand-total',grand)}
function saveDirectPO(){const x=db(),vendor=(x.vendors||[]).find(v=>String(v.id)===String(document.getElementById('dpo-vendor')?.value)),items=directPOLineData();if(!vendor){toast('Select a vendor');return}if(!items.length||items.some(i=>!i.productId||i.quantity<=0||i.rate<0)){toast('Select a product/service and enter valid quantities and prices');return}const poDate=document.getElementById('dpo-date').value,deliveryDate=document.getElementById('dpo-delivery-date').value;if(!poDate||!deliveryDate){toast('Enter PO date and expected delivery date');return}const subtotal=items.reduce((a,i)=>a+i.base,0),lineDiscount=items.reduce((a,i)=>a+i.discount,0),tax=items.reduce((a,i)=>a+i.tax,0),shipping=Number(document.getElementById('dpo-shipping').value||0),extraDiscount=Number(document.getElementById('dpo-extra-discount').value||0),total=Math.max(0,subtotal-lineDiscount+tax+shipping-extraDiscount),next=(x.orders||[]).length?Math.max(...x.orders.map(a=>Number(String(a.poNo||'').split('-').pop())||0))+1:1,poNo='PO-2026-'+String(next).padStart(3,'0');x.orders=x.orders||[];x.orders.unshift({id:Date.now(),poNo,source:'Direct Purchase',quotationId:null,quotationNo:'',rfqId:null,rfqNo:'',requestNo:'',vendorId:vendor.id,vendorName:vendor.name,vendorContact:vendor.contact||'',vendorEmail:vendor.email||'',vendorTRN:vendor.trn||'',poDate,deliveryDate,deliveryLocation:document.getElementById('dpo-location').value.trim(),referenceNo:document.getElementById('dpo-reference').value.trim(),items,subtotal,shippingCharges:shipping,additionalDiscount:extraDiscount+lineDiscount,tax,total,status:'Draft',paymentTerms:document.getElementById('dpo-payment').value,deliveryTerms:document.getElementById('dpo-delivery-terms').value,deliveryTime:'',terms:document.getElementById('dpo-terms').value.trim(),notes:document.getElementById('dpo-notes').value.trim(),attachment:document.getElementById('dpo-file')?.files[0]?.name||'',createdAt:new Date().toISOString()});recordActivity(x,'Created','Purchase Orders','Direct purchase order created: '+poNo,poNo);save(x);closeModal();renderOrders();toast('Direct Purchase Order created successfully')}

function loadPODetails(){const x=db(),q=x.quotations.find(a=>String(a.id)===String(document.getElementById('po-quotation')?.value)),box=document.getElementById('po-preview');if(!q||!box){if(box)box.innerHTML='<div class="detail-note"><b>Select a quotation</b><p>Vendor and quoted items will be loaded here.</p></div>';return}box.innerHTML=`<div class="detail-grid"><div><span>Vendor</span><b>${esc(q.vendorName)}</b></div><div><span>RFQ</span><b>${esc(q.rfqNo)}</b></div><div><span>Quotation</span><b>${esc(q.quotationNo)}</b></div><div><span>Payment Terms</span><b>${esc(q.paymentTerms||'—')}</b></div></div><div style="margin-top:15px">${table(['Item','Qty','Unit','Rate','Tax','Discount','Line Total'],(q.items||[]).map(i=>`<tr><td>${esc(i.productName)}</td><td>${i.quantity}</td><td>${esc(i.unit||'')}</td><td>${money(i.quotedRate)}</td><td>${Number(i.taxPercent||0)}%</td><td>${Number(i.discountPercent||0)}%</td><td><b>${money(i.total)}</b></td></tr>`).join(''))}</div><div class="request-summary"><span>Quoted Total</span><strong id="po-quoted-total">${money(q.total)}</strong></div><div class="detail-note"><b>Vendor Terms</b><p>${esc(q.deliveryTime||'Delivery not specified')} · ${esc(q.paymentTerms||'Payment terms not specified')}${q.notes?' · '+esc(q.notes):''}</p></div>`;recalcPO()}
function recalcPO(){const x=db(),q=x.quotations.find(a=>String(a.id)===String(document.getElementById('po-quotation')?.value));if(!q)return;const shipping=Number(document.getElementById('po-shipping')?.value||0),discount=Number(document.getElementById('po-extra-discount')?.value||0),total=Math.max(0,Number(q.total||0)+shipping-discount),out=document.getElementById('po-quoted-total');if(out)out.textContent=money(total)}
function savePO(){const x=db(),qid=document.getElementById('po-quotation')?.value,q=x.quotations.find(a=>String(a.id)===String(qid));if(!q){toast('Select a selected quotation');return}if(q.status!=='Selected'){toast('Only selected quotations can become purchase orders');return}if((x.orders||[]).some(o=>String(o.quotationId)===String(q.id))){toast('A purchase order already exists for this quotation');return}const poDate=document.getElementById('po-date').value,deliveryDate=document.getElementById('po-delivery-date').value;if(!poDate||!deliveryDate){toast('Enter PO date and expected delivery date');return}const shipping=Number(document.getElementById('po-shipping').value||0),extraDiscount=Number(document.getElementById('po-extra-discount').value||0),subtotal=Number(q.total||0),total=Math.max(0,subtotal+shipping-extraDiscount),next=(x.orders||[]).length?Math.max(...x.orders.map(a=>Number(String(a.poNo||'').split('-').pop())||0))+1:1;const rfq=x.rfqs.find(r=>String(r.id)===String(q.rfqId)),vendor=vendorRecord(x,q.vendorId);x.orders=x.orders||[];x.orders.unshift({id:Date.now(),poNo:'PO-2026-'+String(next).padStart(3,'0'),quotationId:q.id,quotationNo:q.quotationNo,rfqId:q.rfqId,rfqNo:q.rfqNo,requestNo:q.requestNo,vendorId:q.vendorId,vendorName:q.vendorName,vendorContact:q.vendorContact,vendorEmail:q.vendorEmail,vendorTRN:vendor?.trn||q.vendorTRN||'',poDate,deliveryDate,deliveryLocation:document.getElementById('po-location').value.trim(),items:(q.items||[]).map(i=>({...i,rate:i.quotedRate})),subtotal,shippingCharges:shipping,additionalDiscount:extraDiscount,total,status:'Draft',paymentTerms:q.paymentTerms||'',deliveryTime:q.deliveryTime||'',terms:(document.getElementById('po-terms').value.trim()||defaultPOTerms()),createdAt:new Date().toISOString()});if(rfq)rfq.status='PO Created';recordActivity(x,'Created','Purchase Orders','Purchase order created: '+('PO-2026-'+String(next).padStart(3,'0')),'PO-2026-'+String(next).padStart(3,'0'));save(x);closeModal();renderOrders();toast('Purchase Order created successfully')}
function orderDetails(id){const x=db(),o=(x.orders||[]).find(a=>a.id===id);if(!o)return;openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>${esc(o.poNo)}</h3><small>${esc(o.vendorName)} — ${esc(o.source||'Purchase Request')}</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="detail-grid"><div><span>Vendor</span><b>${esc(o.vendorName)}</b></div><div><span>Vendor TRN</span><b>${esc(vendorTRN(x,o)||'—')}</b></div><div><span>Purchaser TRN</span><b>${esc(companyTaxNumber())}</b></div><div><span>Source</span><b>${esc(o.source||'Purchase Request')}</b></div><div><span>PO Date</span><b>${esc(o.poDate)}</b></div><div><span>Expected Delivery</span><b>${esc(o.deliveryDate)}</b></div><div><span>Status</span><b>${status(o.status)}</b></div><div><span>RFQ</span><b>${esc(o.rfqNo||'—')}</b></div><div><span>Quotation</span><b>${esc(o.quotationNo||'—')}</b></div><div><span>Reference</span><b>${esc(o.referenceNo||'—')}</b></div><div><span>Payment Terms</span><b>${esc(o.paymentTerms||'—')}</b></div><div><span>Delivery Terms</span><b>${esc(o.deliveryTerms||'—')}</b></div><div><span>Delivery Location</span><b>${esc(o.deliveryLocation||'—')}</b></div></div>${table(['Item','Qty','Unit','Rate','Tax','Discount','Total'],(o.items||[]).map(i=>`<tr><td>${esc(i.productName)}${i.description?`<br><small>${esc(i.description)}</small>`:''}</td><td>${i.quantity}</td><td>${esc(i.unit||'')}</td><td>${money(i.rate||i.quotedRate)}</td><td>${Number(i.taxPercent||0)}%</td><td>${Number(i.discountPercent||0)}%</td><td><b>${money(i.total)}</b></td></tr>`).join(''))}<div class="po-totals"><div><span>Subtotal</span><b>${money(o.subtotal)}</b></div><div><span>Tax</span><b>${money(o.tax||0)}</b></div><div><span>Shipping / Other</span><b>${money(o.shippingCharges)}</b></div><div><span>Additional / Line Discount</span><b>${money(o.additionalDiscount)}</b></div><div class="grand"><span>PO Total</span><b>${money(o.total)}</b></div></div>${o.terms?`<div class="detail-note"><b>Notes / Terms & Conditions</b><p>${esc(o.terms)}</p></div>`:''}${o.attachment?`<div class="detail-note"><b>Attachment</b><p>${esc(o.attachment)}</p></div>`:''}</div><div class="modal-foot"><button class="btn-secondary" onclick="downloadPOPdf(${o.id})"><i class="ti ti-file-type-pdf"></i> PDF</button><button class="btn-secondary" onclick="closeModal()">Close</button>${o.status==='Draft'?`<button class="btn-secondary" onclick="updatePOStatus(${o.id},'Cancelled')">Cancel PO</button><button class="btn-primary" onclick="updatePOStatus(${o.id},'Pending Approval')"><i class="ti ti-send"></i> Submit for Approval</button>`:o.status==='Pending Approval'?`${['Admin','Procurement Manager'].includes(currentUser()?.role)?`<button class="btn-secondary" onclick="updatePOStatus(${o.id},'Cancelled')">Reject / Cancel PO</button><button class="btn-primary" onclick="updatePOStatus(${o.id},'Approved')"><i class="ti ti-check"></i> Approve PO</button>`:''}`:o.status==='Approved'?`<button class="btn-primary" onclick="updatePOStatus(${o.id},'Sent to Vendor')"><i class="ti ti-send"></i> Send to Vendor</button>`:''}</div></div></div>`)}
function updatePOStatus(id,newStatus){const u=currentUser();const x=db(),o=(x.orders||[]).find(a=>a.id===id);if(!o)return;if(newStatus==='Approved'&&!['Admin','Procurement Manager'].includes(u?.role)){toast('Only Admin or Procurement Manager can approve purchase orders');return}if(newStatus==='Pending Approval'&&!['Admin','Procurement Staff','Procurement Manager'].includes(u?.role)){toast('Only Admin, Procurement Staff or Procurement Manager can submit purchase orders for approval');return}o.status=newStatus;if(newStatus==='Approved')o.approvedAt=new Date().toISOString();if(newStatus==='Pending Approval')o.submittedAt=new Date().toISOString();if(newStatus==='Sent to Vendor')o.sentAt=new Date().toISOString();recordActivity(x,'Updated','Purchase Orders',o.poNo+' status changed to '+newStatus,o.poNo);save(x);closeModal();renderOrders();toast('Purchase Order '+newStatus.toLowerCase())}

function comparisonGroups(x){
 const map={};
 (x.quotations||[]).forEach(q=>{if(!q.rfqId)return;(map[q.rfqId]??=[]).push(q)});
 return Object.values(map).map(quotes=>({rfqId:quotes[0].rfqId,rfqNo:quotes[0].rfqNo,requestNo:quotes[0].requestNo,quotes:quotes.sort((a,b)=>Number(a.total||0)-Number(b.total||0))})).sort((a,b)=>String(b.rfqNo).localeCompare(String(a.rfqNo)));
}
function renderComparison(){
 need();const x=db(),groups=comparisonGroups(x),comparable=groups.filter(g=>g.quotes.length>=2),awarded=groups.filter(g=>g.quotes.some(q=>q.status==='Selected')).length;
 layout('comparison','Quotation Comparison','Compare vendor offers side-by-side and select the best quotation',`<div class="stats">${stat('RFQs with Quotes',groups.length,'ti-file-description')}${stat('Ready to Compare',comparable.length,'ti-scale')}${stat('Awarded',awarded,'ti-trophy')}${stat('Total Quotations',x.quotations.length,'ti-file-dollar')}</div><div class="section-card"><div class="section-head"><div><div class="section-title">Quotation Comparisons</div><div style="font-size:11px;color:#9CA3AF;margin-top:3px">Quotations are grouped by RFQ. Two or more responses are recommended for comparison.</div></div></div><div class="filters"><input id="comparison-search" placeholder="Search RFQ, request or vendor" oninput="filterComparisons()"><select id="comparison-filter" onchange="filterComparisons()"><option value="">All RFQs</option><option value="ready">Ready to Compare</option><option value="awarded">Awarded</option><option value="single">Single Quote</option></select></div><div id="comparison-list">${comparisonGroupCards(groups)}</div></div>`);
}
function comparisonGroupCards(groups){
  const total=groups.length;
  const pages=Math.max(1,Math.ceil(total/25));
  let page=Number(window.COMPARISON_PAGE||1);

  if(page<1) page=1;
  if(page>pages) page=pages;
  window.COMPARISON_PAGE=page;

  const start=(page-1)*25;
  const visible=groups.slice(start,start+25);

  if(!visible.length){
    return `<div class="empty-state"><i class="ti ti-scale"></i><h3>No quotations to compare</h3><p>Record vendor quotations against an RFQ. They will appear here automatically.</p><a class="btn-primary inline-action" href="quotations.html"><i class="ti ti-plus"></i> Add Vendor Quotation</a></div>`;
  }

  const cards=`<div class="comparison-groups">${visible.map(g=>{
    const selected=g.quotes.find(q=>q.status==='Selected');
    return `<div class="comparison-group" data-search="${esc((g.rfqNo+' '+g.requestNo+' '+g.quotes.map(q=>q.vendorName).join(' ')).toLowerCase())}" data-count="${g.quotes.length}" data-awarded="${selected?'1':'0'}"><div class="comparison-group-head"><div><div class="comparison-rfq">${esc(g.rfqNo||'RFQ')}</div><div class="comparison-meta">${esc(g.requestNo||'')} · ${g.quotes.length} quotation${g.quotes.length===1?'':'s'}</div></div><div class="comparison-head-actions">${selected?`<span class="award-chip"><i class="ti ti-trophy"></i> Awarded to ${esc(selected.vendorName)}</span>`:g.quotes.length>=2?`<span class="ready-chip">Ready to compare</span>`:`<span class="single-chip">Waiting for more quotes</span>`}<button class="btn-sm" onclick="openComparison('${g.rfqId}')"><i class="ti ti-scale"></i> Compare</button></div></div><div class="quote-summary-grid">${g.quotes.slice(0,4).map((q,i)=>`<div class="quote-summary ${q.status==='Selected'?'winner':''}"><div class="quote-vendor">${esc(q.vendorName)}</div><strong>${money(q.total)}</strong><small>${esc(q.deliveryTime||'Delivery not specified')} · ${esc(q.paymentTerms||'Terms not specified')}</small>${q.status==='Selected'?`<span class="mini-winner"><i class="ti ti-check"></i> Selected</span>`:i===0&&g.quotes.length>1&&!selected?`<span class="mini-lowest">Lowest total</span>`:''}</div>`).join('')}</div>${g.quotes.length>4?`<div class="more-quotes">+${g.quotes.length-4} more quotation(s)</div>`:''}</div>`;
  }).join('')}</div>`;

  if(total<=25) return cards;

  let pageButtons='';

  const addPage=(n)=>{
    pageButtons+=`<button class="pagination-page ${n===page?'active':''}" onclick="changeComparisonPage(${n})">${n}</button>`;
  };

  const addDots=()=>{
    pageButtons+=`<span class="pagination-dots">…</span>`;
  };

  if(pages<=5){
    for(let i=1;i<=pages;i++) addPage(i);
  }else if(page<=3){
    addPage(1);
    addPage(2);
    addPage(3);
    addDots();
    addPage(pages);
  }else if(page>=pages-2){
    addPage(1);
    addDots();
    addPage(pages-2);
    addPage(pages-1);
    addPage(pages);
  }else{
    addPage(1);
    addDots();
    addPage(page);
    addDots();
    addPage(pages);
  }

  const from=start+1;
  const to=Math.min(start+25,total);

  return cards+`
    <div class="pagination">
      <div class="pagination-showing">Showing ${from}–${to} of ${total}</div>
      <div class="pagination-controls">
        <button class="pagination-arrow" ${page<=1?'disabled':''} onclick="changeComparisonPage(${page-1})">‹</button>
        ${pageButtons}
        <button class="pagination-arrow" ${page>=pages?'disabled':''} onclick="changeComparisonPage(${page+1})">›</button>
      </div>
    </div>
  `;
}

function filterComparisons(resetPage=true){
  if(resetPage) window.COMPARISON_PAGE=1;

  const x=db();
  const q=(document.getElementById('comparison-search')?.value||'').toLowerCase();
  const f=document.getElementById('comparison-filter')?.value||'';

  const groups=comparisonGroups(x).filter(g=>{
    const hay=(g.rfqNo+' '+g.requestNo+' '+g.quotes.map(a=>a.vendorName).join(' ')).toLowerCase();
    const awarded=g.quotes.some(a=>a.status==='Selected');

    return (!q||hay.includes(q)) &&
      (!f||
        (f==='ready'&&g.quotes.length>=2&&!awarded) ||
        (f==='awarded'&&awarded) ||
        (f==='single'&&g.quotes.length===1)
      );
  });

  const target=document.getElementById('comparison-list');
  if(target) target.innerHTML=comparisonGroupCards(groups);
}

function changeComparisonPage(page){
  window.COMPARISON_PAGE=page;
  filterComparisons(false);
}

function openComparison(rfqId){const x=db(),quotes=x.quotations.filter(q=>String(q.rfqId)===String(rfqId)).sort((a,b)=>Number(a.total||0)-Number(b.total||0));if(!quotes.length)return;const rfq=x.rfqs.find(r=>String(r.id)===String(rfqId)),selected=quotes.find(q=>q.status==='Selected'),items=(rfq?.items||quotes[0].items||[]);const lowest=Math.min(...quotes.map(q=>Number(q.total||0)));openModal(`<div class="modal" id="modal"><div class="modal-box comparison-modal"><div class="modal-head"><div><h3>Quotation Comparison — ${esc(quotes[0].rfqNo||'RFQ')}</h3><small>${esc(quotes[0].requestNo||'')} · Compare ${quotes.length} vendor offer${quotes.length===1?'':'s'}</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="comparison-scroll"><table class="comparison-table"><thead><tr><th class="criteria-col">Criteria</th>${quotes.map(q=>`<th class="vendor-col ${q.status==='Selected'?'selected-col':''}"><div class="vendor-heading"><span>${esc(q.vendorName)}</span><small>${esc(q.quotationNo)}</small>${q.status==='Selected'?`<b><i class="ti ti-trophy"></i> Selected</b>`:''}</div></th>`).join('')}</tr></thead><tbody><tr class="total-row"><td><b>Total Quotation</b></td>${quotes.map(q=>`<td class="${Number(q.total)===lowest&&quotes.length>1?'best-cell':''}"><strong>${money(q.total)}</strong>${Number(q.total)===lowest&&quotes.length>1?'<small>Lowest</small>':''}</td>`).join('')}</tr><tr><td>Delivery Time</td>${quotes.map(q=>`<td>${esc(q.deliveryTime||'—')}</td>`).join('')}</tr><tr><td>Payment Terms</td>${quotes.map(q=>`<td>${esc(q.paymentTerms||'—')}</td>`).join('')}</tr><tr><td>Valid Until</td>${quotes.map(q=>`<td>${esc(q.validUntil||'—')}</td>`).join('')}</tr><tr><td>Status</td>${quotes.map(q=>`<td>${status(q.status)}</td>`).join('')}</tr>${items.map((item,i)=>{const vals=quotes.map(q=>q.items?.[i]);const rates=vals.map(v=>Number(v?.quotedRate||Infinity)),minRate=Math.min(...rates);return `<tr class="item-separator"><td><b>${esc(item.productName||'Item '+(i+1))}</b><small>${item.quantity||vals[0]?.quantity||0} ${esc(item.unit||vals[0]?.unit||'')}</small></td>${vals.map(v=>`<td class="${Number(v?.quotedRate||Infinity)===minRate&&quotes.length>1?'best-cell':''}"><b>${money(v?.quotedRate||0)}</b><small>Tax ${Number(v?.taxPercent||0)}% · Disc. ${Number(v?.discountPercent||0)}%</small><span>${money(v?.total||0)} line total</span></td>`).join('')}</tr>`}).join('')}<tr><td>Notes</td>${quotes.map(q=>`<td class="notes-cell">${esc(q.notes||'—')}</td>`).join('')}</tr></tbody></table></div>${quotes.length<2?`<div class="comparison-warning"><i class="ti ti-alert-circle"></i><div><b>Only one quotation received</b><span>You can still review it, but a competitive comparison normally requires at least two vendor responses.</span></div></div>`:''}</div><div class="modal-foot comparison-foot"><button class="btn-secondary" onclick="closeModal()">Close</button>${!selected?quotes.map(q=>`<button class="btn-primary award-btn" onclick="awardQuotation(${q.id})"><i class="ti ti-trophy"></i> Select ${esc(q.vendorName)}</button>`).join(''):`<button class="btn-secondary" onclick="clearAward('${rfqId}')"><i class="ti ti-refresh"></i> Change Selection</button><button class="btn-primary" onclick="closeModal();location.href='orders.html'"><i class="ti ti-shopping-cart"></i> Create Purchase Order</button>`}</div></div></div>`)}
function awardQuotation(id){const x=db(),winner=x.quotations.find(q=>q.id===id);if(!winner)return;x.quotations.filter(q=>String(q.rfqId)===String(winner.rfqId)).forEach(q=>q.status=q.id===id?'Selected':'Rejected');const rfq=(x.rfqs||[]).find(r=>String(r.id)===String(winner.rfqId));if(rfq){rfq.status='Closed';rfq.completedAt=new Date().toISOString();}const existing=x.comparisons.find(c=>String(c.rfqId)===String(winner.rfqId));const record={id:existing?.id||Date.now(),rfqId:winner.rfqId,rfqNo:winner.rfqNo,requestNo:winner.requestNo,selectedQuotationId:winner.id,selectedQuotationNo:winner.quotationNo,vendorId:winner.vendorId,vendorName:winner.vendorName,total:winner.total,status:'Completed',comparedAt:new Date().toISOString()};if(existing)Object.assign(existing,record);else x.comparisons.unshift(record);recordActivity(x,'Selected','Quotation Comparison',winner.vendorName+' quotation selected for '+winner.rfqNo,winner.quotationNo);save(x);closeModal();renderComparison();toast(winner.vendorName+' quotation selected')}
function clearAward(rfqId){const x=db();x.quotations.filter(q=>String(q.rfqId)===String(rfqId)).forEach(q=>{if(q.status==='Selected'||q.status==='Rejected')q.status='Received'});const rfq=(x.rfqs||[]).find(r=>String(r.id)===String(rfqId));if(rfq){rfq.status='Response Received';delete rfq.completedAt;}x.comparisons=x.comparisons.filter(c=>String(c.rfqId)!==String(rfqId));recordActivity(x,'Cleared','Quotation Comparison','Quotation selection cleared for RFQ '+rfqId,rfqId);save(x);closeModal();renderComparison();toast('Selection cleared. You can choose another quotation.')}

function invoicePaidAmount(x,id){return (x.payments||[]).filter(p=>String(p.invoiceId)===String(id)&&p.status==='Processed').reduce((a,p)=>a+Number(p.amount||0),0)}
function invoiceBalance(x,i){return Math.max(0,Number(i.amount||0)-invoicePaidAmount(x,i.id))}
function paymentEligibleInvoices(x){return (x.invoices||[]).filter(i=>['Approved','Matched','Partially Paid'].includes(i.status)&&invoiceBalance(x,i)>0.01)}
function renderPayments(){need();const x=db(),ps=x.payments||[],is=x.invoices||[],paid=ps.filter(p=>p.status==='Processed').reduce((a,p)=>a+Number(p.amount||0),0),out=is.reduce((a,i)=>a+invoiceBalance(x,i),0),partial=is.filter(i=>{let p=invoicePaidAmount(x,i.id);return p>.01&&p<Number(i.amount||0)-.01}).length;layout('payments','Payments','Record and track vendor payments against approved invoices',`<div class="stats">${stat('Total Payments',ps.length,'ti-credit-card')}${stat('Paid Amount',money(paid),'ti-cash')}${stat('Outstanding',money(out),'ti-clock')}${stat('Partially Paid',partial,'ti-progress-check')}</div><div class="section-card"><div class="section-head"><div><div class="section-title">Vendor Payments</div><div style="font-size:11px;color:#9CA3AF;margin-top:3px">Full and partial payments with automatic invoice and PO completion</div></div><button class="btn-primary" onclick="openPayment()"><i class="ti ti-plus"></i> Record Payment</button></div><div class="filters"><input id="payment-search" placeholder="Search payment, invoice, PO or vendor" oninput="filterPayments()"><select id="payment-status" onchange="filterPayments()"><option value="">All Statuses</option><option>Processed</option><option>Cancelled</option></select></div><div id="payment-table">${paymentRows(ps)}</div></div>`)}
function paymentRows(rows){
  const total=rows.length;
  const pages=Math.max(1,Math.ceil(total/25));
  let page=Number(window.PAYMENT_PAGE||1);

  if(page<1) page=1;
  if(page>pages) page=pages;
  window.PAYMENT_PAGE=page;

  const start=(page-1)*25;
  const visible=rows.slice(start,start+25);

  const tableHtml=table(
    ['Payment No.','Invoice','PO No.','Vendor','Date','Amount','Method','Status','Actions'],
    visible.map(p=>`<tr><td><button class="link-btn" onclick="paymentDetails(${p.id})">${esc(p.paymentNo)}</button></td><td>${esc(p.invoiceNo||'—')}</td><td>${esc(p.poNo||'—')}</td><td>${esc(p.vendorName||'—')}</td><td>${esc(p.paymentDate||'—')}</td><td><b>${money(p.amount)}</b></td><td>${esc(p.method||'—')}</td><td>${status(p.status||'Processed')}</td><td><button class="btn-sm" onclick="paymentDetails(${p.id})"><i class="ti ti-eye"></i> View</button> <button class="btn-sm" onclick="downloadPaymentPdf(${p.id})"><i class="ti ti-file-type-pdf"></i> PDF</button></td></tr>`).join('')
  );

  if(total<=25) return tableHtml;

  let pageButtons='';

  const addPage=(n)=>{
    pageButtons+=`<button class="pagination-page ${n===page?'active':''}" onclick="changePaymentPage(${n})">${n}</button>`;
  };

  const addDots=()=>{
    pageButtons+=`<span class="pagination-dots">…</span>`;
  };

  if(pages<=5){
    for(let i=1;i<=pages;i++) addPage(i);
  }else if(page<=3){
    addPage(1);
    addPage(2);
    addPage(3);
    addDots();
    addPage(pages);
  }else if(page>=pages-2){
    addPage(1);
    addDots();
    addPage(pages-2);
    addPage(pages-1);
    addPage(pages);
  }else{
    addPage(1);
    addDots();
    addPage(page);
    addDots();
    addPage(pages);
  }

  const from=start+1;
  const to=Math.min(start+25,total);

  return tableHtml+`
    <div class="pagination">
      <div class="pagination-showing">Showing ${from}–${to} of ${total}</div>
      <div class="pagination-controls">
        <button class="pagination-arrow" ${page<=1?'disabled':''} onclick="changePaymentPage(${page-1})">‹</button>
        ${pageButtons}
        <button class="pagination-arrow" ${page>=pages?'disabled':''} onclick="changePaymentPage(${page+1})">›</button>
      </div>
    </div>
  `;
}

function filterPayments(resetPage=true){
  if(resetPage) window.PAYMENT_PAGE=1;

  const x=db();
  const q=(document.getElementById('payment-search')?.value||'').toLowerCase();
  const st=document.getElementById('payment-status')?.value||'';

  const rows=(x.payments||[]).filter(p=>
    (!q||(p.paymentNo+' '+p.invoiceNo+' '+p.poNo+' '+p.vendorName).toLowerCase().includes(q)) &&
    (!st||p.status===st)
  );

  const target=document.getElementById('payment-table');
  if(target) target.innerHTML=paymentRows(rows);
}

function changePaymentPage(page){
  window.PAYMENT_PAGE=page;
  filterPayments(false);
}

function openPayment(){const x=db(),es=paymentEligibleInvoices(x);if(!es.length){toast('No approved invoices with an outstanding balance are available');return}openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>Record Vendor Payment</h3><small>Apply a full or partial payment to an approved invoice</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="grid2"><label>Vendor Invoice<select id="pay-invoice" onchange="loadPaymentInvoice()"><option value="">Select invoice</option>${es.map(i=>`<option value="${i.id}">${esc(i.invoiceNo)} — ${esc(i.vendorName)} — Balance ${money(invoiceBalance(x,i))}</option>`).join('')}</select></label><label>Payment Date<input id="pay-date" type="date" value="${new Date().toISOString().slice(0,10)}"></label><label>Payment Amount<input id="pay-amount" type="number" min="0.01" step="0.01" oninput="previewPayment()"></label><label>Payment Method<select id="pay-method"><option>Bank Transfer</option><option>Cheque</option><option>Cash</option><option>Online Transfer</option><option>Card</option></select></label><label>Reference No.<input id="pay-ref" placeholder="Transaction / cheque reference"></label><label>Bank / Account<input id="pay-account" placeholder="Optional account name"></label></div><div id="payment-preview"><div class="detail-note"><b>Select an invoice</b><p>Invoice total, paid amount and outstanding balance will appear here.</p></div></div><label>Notes<textarea id="pay-notes" rows="3" placeholder="Payment notes..."></textarea></div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="savePayment()"><i class="ti ti-check"></i> Process Payment</button></div></div></div>`);loadPaymentInvoice()}
function loadPaymentInvoice(){const x=db(),i=x.invoices.find(a=>String(a.id)===String(document.getElementById('pay-invoice')?.value)),box=document.getElementById('payment-preview');if(!box)return;if(!i){box.innerHTML='<div class="detail-note"><b>Select an invoice</b><p>Invoice total, paid amount and outstanding balance will appear here.</p></div>';return}const p=invoicePaidAmount(x,i.id),b=invoiceBalance(x,i);document.getElementById('pay-amount').value=b.toFixed(2);box.innerHTML=`<div class="detail-grid"><div><span>Vendor</span><b>${esc(i.vendorName)}</b></div><div><span>Invoice</span><b>${esc(i.invoiceNo)}</b></div><div><span>PO</span><b>${esc(i.poNo||'—')}</b></div><div><span>Invoice Total</span><b>${money(i.amount)}</b></div><div><span>Already Paid</span><b>${money(p)}</b></div><div><span>Outstanding</span><b>${money(b)}</b></div></div><div id="payment-balance-preview" class="request-summary"><span>After Payment</span><strong></strong></div>`;previewPayment()}
function previewPayment(){const x=db(),i=x.invoices.find(a=>String(a.id)===String(document.getElementById('pay-invoice')?.value)),o=document.getElementById('payment-balance-preview');if(!i||!o)return;const b=invoiceBalance(x,i),a=Number(document.getElementById('pay-amount')?.value||0),r=Math.max(0,b-a);o.innerHTML=`<span>After Payment</span><strong class="${a>0&&a<=b+.01?'text-success':'text-danger'}">${a>0&&a<=b+.01?(r<=.01?'Invoice will be fully paid':'Remaining '+money(r)):'Enter a valid amount'}</strong>`}
function savePayment(){const x=db(),i=x.invoices.find(a=>String(a.id)===String(document.getElementById('pay-invoice')?.value));if(!i){toast('Select a vendor invoice');return}const b=invoiceBalance(x,i),a=Number(document.getElementById('pay-amount').value||0),d=document.getElementById('pay-date').value,m=document.getElementById('pay-method').value,r=document.getElementById('pay-ref').value.trim();if(!d||a<=0||a>b+.01){toast('Enter a valid payment amount within the outstanding balance');return}if(r&&(x.payments||[]).some(p=>String(p.referenceNo||'').toLowerCase()===r.toLowerCase())){toast('A payment with this reference already exists');return}const n=(x.payments||[]).length?Math.max(...x.payments.map(p=>Number(String(p.paymentNo||'').split('-').pop())||0))+1:1;x.payments=x.payments||[];x.payments.unshift({id:Date.now(),paymentNo:'PAY-2026-'+String(n).padStart(3,'0'),invoiceId:i.id,invoiceNo:i.invoiceNo,poId:i.poId,poNo:i.poNo,vendorId:i.vendorId,vendorName:i.vendorName,paymentDate:d,amount:a,method:m,referenceNo:r,account:document.getElementById('pay-account').value.trim(),notes:document.getElementById('pay-notes').value.trim(),status:'Processed',createdAt:new Date().toISOString()});const total=invoicePaidAmount(x,i.id),full=total>=Number(i.amount||0)-.01;i.status=full?'Paid':'Partially Paid';i.paidAmount=total;i.balance=invoiceBalance(x,i);if(full)i.paidAt=new Date().toISOString();const po=(x.orders||[]).find(o=>String(o.id)===String(i.poId));if(po&&full){po.status='Completed';po.completedAt=new Date().toISOString()}recordActivity(x,'Processed','Payments','Payment '+x.payments[0].paymentNo+' processed for '+money(a),x.payments[0].paymentNo);save(x);closeModal();renderPayments();toast(full?'Payment processed — invoice fully paid':'Payment processed — invoice remains partially paid')}
function paymentDetails(id){const x=db(),p=(x.payments||[]).find(a=>a.id===id),i=p&&(x.invoices||[]).find(a=>String(a.id)===String(p.invoiceId));if(!p)return;openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>${esc(p.paymentNo)}</h3><small>${esc(p.vendorName||'')} — ${esc(p.invoiceNo||'')}</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="detail-grid"><div><span>Payment No.</span><b>${esc(p.paymentNo)}</b></div><div><span>Invoice</span><b>${esc(p.invoiceNo||'—')}</b></div><div><span>PO</span><b>${esc(p.poNo||'—')}</b></div><div><span>Vendor</span><b>${esc(p.vendorName||'—')}</b></div><div><span>Payment Date</span><b>${esc(p.paymentDate||'—')}</b></div><div><span>Amount</span><b>${money(p.amount)}</b></div><div><span>Method</span><b>${esc(p.method||'—')}</b></div><div><span>Reference</span><b>${esc(p.referenceNo||'—')}</b></div><div><span>Invoice Total</span><b>${money(i?.amount||0)}</b></div><div><span>Outstanding</span><b>${money(i?invoiceBalance(x,i):0)}</b></div><div><span>Status</span><b>${status(p.status)}</b></div></div>${p.account?`<div class="detail-note"><b>Bank / Account</b><p>${esc(p.account)}</p></div>`:''}${p.notes?`<div class="detail-note"><b>Notes</b><p>${esc(p.notes)}</p></div>`:''}</div><div class="modal-foot"><button class="btn-secondary" onclick="downloadPaymentPdf(${p.id})"><i class="ti ti-file-type-pdf"></i> PDF</button><button class="btn-secondary" onclick="closeModal()">Close</button></div></div></div>`)}

function renderCompanySettings(){
  if(!guard('settings'))return;
  const c=companySettings();
  const countries=['United Arab Emirates','Pakistan','Saudi Arabia','Qatar','Bahrain','Kuwait','Oman','United Kingdom','United States','Canada','Australia','India','Other'];
  const currencies=[['PKR','Rs','en-PK'],['PKR','₨','en-PK'],['SAR','SAR','en-SA'],['QAR','QAR','en-QA'],['BHD','BHD','en-BH'],['KWD','KWD','en-KW'],['OMR','OMR','en-OM'],['USD','$','en-US'],['EUR','€','de-DE'],['GBP','£','en-GB'],['CAD','CA$','en-CA'],['AUD','A$','en-AU'],['INR','₹','en-IN']];
  layout('settings','Company Settings','Configure company identity, currency and tax rules',`
    <div class="company-settings-page">
      <div class="company-settings-hero">
        <div class="company-settings-hero-icon"><i class="ti ti-building"></i></div>
        <div><h2>Company Configuration</h2><p>These settings personalize the platform for each company and are used across Sales, Procurement, reports and documents.</p></div>
        <div class="company-settings-status"><i class="ti ti-shield-check"></i><span>Company profile</span><b>Configurable</b></div>
      </div>

      <div class="company-settings-grid">
        <section class="company-settings-card company-settings-card-wide">
          <div class="company-settings-card-head"><div class="company-settings-card-icon"><i class="ti ti-building-community"></i></div><div><h3>Company Profile</h3><p>Legal and contact information shown throughout the system.</p></div></div>
          <div class="company-settings-form-grid">
            <label class="company-field"><span>Company / Trading Name <em>*</em></span><input id="co-name" value="${esc(c.name||'')}" placeholder="Company trading name"></label>
            <label class="company-field"><span>Legal Name</span><input id="co-legal" value="${esc(c.legalName||'')}" placeholder="Registered legal name"></label>
            <label class="company-field"><span>Country <em>*</em></span><select id="co-country">${countries.map(v=>`<option ${c.country===v?'selected':''}>${esc(v)}</option>`).join('')}</select></label>
            <label class="company-field"><span>Tax Number Label</span><input id="co-tax-label" value="${esc(c.taxNumberLabel||'Tax Registration Number')}" placeholder="TRN / NTN / GSTIN / VAT Number"></label>
            <label class="company-field"><span>${esc(c.taxNumberLabel||'Tax Registration Number')}</span><input id="co-tax" value="${esc(c.taxNumber||'')}" placeholder="Company tax / registration number"></label>
            <label class="company-field"><span>Phone</span><input id="co-phone" value="${esc(c.phone||'')}" placeholder="+971 ..."></label>
            <label class="company-field"><span>Email</span><input id="co-email" type="email" value="${esc(c.email||'')}" placeholder="accounts@company.com"></label>
            <label class="company-field"><span>Website</span><input id="co-website" value="${esc(c.website||'')}" placeholder="www.company.com"></label>
            <label class="company-field company-field-full"><span>Registered / Billing Address</span><textarea id="co-address" rows="3" placeholder="Full company address">${esc(c.address||'')}</textarea></label>
          </div>
        </section>

        <section class="company-settings-card">
          <div class="company-settings-card-head"><div class="company-settings-card-icon"><i class="ti ti-currency-dirham"></i></div><div><h3>Currency</h3><p>Default currency used for new transactions.</p></div></div>
          <div class="company-settings-form-grid company-settings-form-grid-1">
            <label class="company-field"><span>Currency <em>*</em></span><select id="co-currency">${currencies.map(v=>`<option value="${v[0]}" data-symbol="${v[1]}" data-locale="${v[2]}" ${c.currency===v[0]?'selected':''}>${v[0]} — ${v[1]}</option>`).join('')}</select></label>
            <label class="company-field"><span>Currency Symbol</span><input id="co-symbol" value="${esc(c.currencySymbol||'')}" placeholder="PKR / $ / ₨"></label>
          </div>
          <div class="company-settings-note"><i class="ti ti-info-circle"></i><span>Currency changes affect new transactions and displays. Existing records retain their saved values.</span></div>
        </section>

        <section class="company-settings-card">
          <div class="company-settings-card-head"><div class="company-settings-card-icon"><i class="ti ti-shopping-cart"></i></div><div><h3>Purchase Tax</h3><p>Tax settings for Procurement transactions.</p></div></div>
          <div class="company-settings-form-grid company-settings-form-grid-1">
            <label class="company-field"><span>Enable Purchase Tax</span><select id="co-p-tax-enabled"><option value="true" ${c.purchaseTax?.enabled!==false?'selected':''}>Enabled</option><option value="false" ${c.purchaseTax?.enabled===false?'selected':''}>Disabled</option></select></label>
            <label class="company-field"><span>Tax Type / Label</span><input id="co-p-tax-label" value="${esc(c.purchaseTax?.label||'VAT')}" placeholder="VAT / GST / Sales Tax"></label>
            <label class="company-field"><span>Default Purchase Tax Rate (%)</span><div class="company-input-suffix"><input id="co-p-tax-rate" type="number" min="0" max="100" step="0.01" value="${Number(c.purchaseTax?.rate||0)}"><span>%</span></div></label>
          </div>
        </section>

        <section class="company-settings-card">
          <div class="company-settings-card-head"><div class="company-settings-card-icon"><i class="ti ti-receipt-tax"></i></div><div><h3>Sales Tax</h3><p>Tax settings for Sales transactions.</p></div></div>
          <div class="company-settings-form-grid company-settings-form-grid-1">
            <label class="company-field"><span>Enable Sales Tax</span><select id="co-s-tax-enabled"><option value="true" ${c.salesTax?.enabled!==false?'selected':''}>Enabled</option><option value="false" ${c.salesTax?.enabled===false?'selected':''}>Disabled</option></select></label>
            <label class="company-field"><span>Tax Type / Label</span><input id="co-s-tax-label" value="${esc(c.salesTax?.label||'VAT')}" placeholder="VAT / GST / Sales Tax"></label>
            <label class="company-field"><span>Default Sales Tax Rate (%)</span><div class="company-input-suffix"><input id="co-s-tax-rate" type="number" min="0" max="100" step="0.01" value="${Number(c.salesTax?.rate||0)}"><span>%</span></div></label>
          </div>
        </section>

        <section class="company-settings-card company-settings-card-wide">
          <div class="company-settings-card-head"><div class="company-settings-card-icon"><i class="ti ti-photo"></i></div><div><h3>Company Logo</h3><p>Logo displayed in the application and generated documents.</p></div></div>
          <div class="company-logo-settings">
            <div class="company-logo-preview"><img id="co-logo-preview" src="${esc(c.logo||'logo.png')}" alt="Company logo"></div>
            <div class="company-logo-controls"><label class="company-field"><span>Upload Logo</span><input id="co-logo" type="file" accept="image/png,image/jpeg,image/webp" onchange="previewCompanyLogo(this)"></label><div class="company-help">PNG, JPG or WebP. A transparent PNG is recommended for documents.</div><button class="btn-secondary" type="button" onclick="removeCompanyLogo()"><i class="ti ti-photo-off"></i> Use Default Logo</button></div>
          </div>
        </section>

        <section class="company-settings-card company-settings-card-wide company-settings-save-card">
          <div><h3>Save Company Configuration</h3><p>Review your settings, then save them. The configuration remains local until the backend is connected.</p></div>
          <button class="btn-primary company-save-btn" onclick="saveCompanySettings()"><i class="ti ti-device-floppy"></i> Save Company Settings</button>
        </section>

        <div class="company-settings-warning company-settings-card-wide"><i class="ti ti-alert-circle"></i><div><b>Tax configuration</b><p>Country selection does not automatically determine a legal tax rate. Enter the tax type and rate applicable to the company and its jurisdiction.</p></div></div>
      </div>
    </div>`);
}

async function readCompanyLogo(file){
  if(!file)return '';
  if(!/^image\/(png|jpeg|webp)$/.test(file.type))throw new Error('Please upload a PNG, JPG or WebP image.');
  if(file.size>8*1024*1024)throw new Error('Logo image must be smaller than 8 MB.');
  return await new Promise((resolve,reject)=>{
    const reader=new FileReader();
    reader.onerror=()=>reject(new Error('Unable to read the logo file.'));
    reader.onload=()=>{
      const img=new Image();
      img.onerror=()=>reject(new Error('Unable to process the logo image.'));
      img.onload=()=>{
        const maxW=700,maxH=260,scale=Math.min(1,maxW/img.width,maxH/img.height);
        const canvas=document.createElement('canvas');
        canvas.width=Math.max(1,Math.round(img.width*scale));canvas.height=Math.max(1,Math.round(img.height*scale));
        const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(img,0,0,canvas.width,canvas.height);
        resolve(canvas.toDataURL('image/webp',0.88));
      };
      img.src=reader.result;
    };
    reader.readAsDataURL(file);
  });
}
function previewCompanyLogo(input){const file=input?.files?.[0];if(!file)return;readCompanyLogo(file).then(data=>{const img=document.getElementById('co-logo-preview');if(img){img.src=data;img.setAttribute('data-logo',data);img.removeAttribute('data-removed')}}).catch(e=>toast(e.message||'Unable to preview logo'))}
function removeCompanyLogo(){const img=document.getElementById('co-logo-preview');if(img){img.src='logo.png';img.setAttribute('data-logo','');img.setAttribute('data-removed','true')}const f=document.getElementById('co-logo');if(f)f.value=''}
async function saveCompanySettings(){
  if(!guardAction('settings','edit'))return;
  const x=db(),c=companySettings(),currency=document.getElementById('co-currency'),preview=document.getElementById('co-logo-preview'),file=document.getElementById('co-logo')?.files?.[0];
  const saveButton=document.querySelector('.company-save-btn');if(saveButton){saveButton.disabled=true;saveButton.innerHTML='<i class="ti ti-loader-2"></i> Saving...'}
  try{
    c.name=document.getElementById('co-name').value.trim()||'Company';c.legalName=document.getElementById('co-legal').value.trim()||c.name;c.country=document.getElementById('co-country').value;c.taxNumber=document.getElementById('co-tax').value.trim();c.taxNumberLabel=document.getElementById('co-tax-label').value.trim()||'Tax Registration Number';c.phone=document.getElementById('co-phone').value.trim();c.email=document.getElementById('co-email').value.trim();c.website=document.getElementById('co-website').value.trim();c.address=document.getElementById('co-address').value.trim();c.currency=currency.value;c.currencySymbol=document.getElementById('co-symbol').value.trim()||currency.selectedOptions[0]?.dataset.symbol||currency.value;c.currencyLocale=currency.selectedOptions[0]?.dataset.locale||'en-US';c.purchaseTax={enabled:document.getElementById('co-p-tax-enabled').value==='true',label:document.getElementById('co-p-tax-label').value.trim()||'Tax',rate:Math.max(0,Number(document.getElementById('co-p-tax-rate').value||0))};c.salesTax={enabled:document.getElementById('co-s-tax-enabled').value==='true',label:document.getElementById('co-s-tax-label').value.trim()||'Tax',rate:Math.max(0,Number(document.getElementById('co-s-tax-rate').value||0))};
    if(file)c.logo=await readCompanyLogo(file);else if(preview?.getAttribute('data-removed')==='true')c.logo='';
    recordActivity(x,'Updated','Company Settings','Company configuration updated','Company');
    save(x);await APP_STATE_SAVE;
    toast('Company settings saved');setTimeout(()=>location.reload(),150);
  }catch(e){toast(e.message||'Unable to save company settings');if(saveButton){saveButton.disabled=false;saveButton.innerHTML='<i class="ti ti-device-floppy"></i> Save Company Settings'}}
}
function renderUsers(){if(!guard('users'))return;const x=db(),users=x.users||[],roles=Object.keys(x.roles||{});layout('users','User & Role Management','Manage users, roles and module permissions',`<div class="stats">${stat('Total Users',users.length,'ti-users')}${stat('Active Users',users.filter(u=>u.active!==false).length,'ti-user-check')}${stat('Roles',roles.length,'ti-shield-check')}${stat('Administrators',users.filter(u=>u.role==='Admin').length,'ti-shield') }</div><div class="section-card"><div class="section-head"><div><div class="section-title">System Users</div><div style="font-size:11px;color:#9CA3AF;margin-top:3px">Create users and assign procurement roles</div></div><button class="btn-primary" onclick="openUser()"><i class="ti ti-plus"></i> Add User</button></div>${table(['Name','Email','Role','Manager','Status','Actions'],users.map(u=>`<tr><td><b>${esc(u.name)}</b></td><td>${esc(u.email)}</td><td><span class="badge role-${String(u.role).toLowerCase().replaceAll(' ','-')}">${esc(u.role)}</span></td><td>${esc((users.find(m=>String(m.id)===String(u.managerId))||{}).name||'—')}</td><td>${status(u.active===false?'Inactive':'Active')}</td><td><button class="btn-sm" onclick="openUser('${u.id}')"><i class="ti ti-edit"></i> Edit</button> <button class="btn-sm" onclick="openAdminResetPassword('${u.id}')"><i class="ti ti-key"></i> Reset Password</button> <button class="btn-sm" onclick="toggleUser('${u.id}')">${u.active===false?'Activate':'Deactivate'}</button></td></tr>`).join(''))}</div><div class="section-card"><div class="section-head"><div><div class="section-title">Roles & Permissions</div><div style="font-size:11px;color:#9CA3AF;margin-top:3px">Control which modules each role can access</div></div></div>${roles.map(r=>roleCard(r,x.roles[r])).join('')}</div>`)}
function downloadQuotationPdf(id){const x=db(),q=(x.quotations||[]).find(a=>a.id===id);if(!q)return;if(!quotationPdfReady(x,q)){toast('Quotation PDF is available after the RFQ has been sent and the quotation is not rejected.');return}const c=(x.comparisons||[]).find(c=>String(c.rfqId)===String(q.rfqId)&&String(c.selectedQuotationId)===String(q.id));const rows=(q.items||[]).map(i=>[esc(i.productName),esc(i.quantity),esc(i.unit||'—'),money(i.quotedRate),`${Number(i.taxPercent||0)}%`,`${Number(i.discountPercent||0)}%`,money(i.total)]);downloadPDF(q.quotationNo,`<div class="grid">${pdfField('Quotation No.',q.quotationNo)}${pdfField('RFQ No.',q.rfqNo)}${pdfField('Purchase Request',q.requestNo)}${pdfField('Vendor',q.vendorName)}${pdfField('Vendor TRN',vendorTRN(x,q))}${pdfField('Purchaser TRN',companyTaxNumber())}${pdfField('Quote Date',q.quoteDate)}${pdfField('Valid Until',q.validUntil)}${pdfField('Delivery',q.deliveryTime)}${pdfField('Payment Terms',q.paymentTerms)}${pdfField('Status',q.status)}</div><div class="section"><h3>Quoted Items</h3>${pdfTable(['Product','Qty','Unit','Rate','Tax','Discount','Total'],rows)}</div><div class="total">Quotation Total: ${money(q.total)}</div>${q.notes?`<div class="note"><b>Notes</b><br>${esc(q.notes)}</div>`:''}<div class="note"><b>Quotation Document</b><br>Generated from the vendor quotation for ${esc(q.rfqNo||'RFQ')}${c?.comparedAt?` and comparison completed on ${esc(new Date(c.comparedAt).toLocaleString())}.`:' for vendor sharing before quotation comparison.'}</div>`)}
function downloadRFQPDF(id){const x=db(),r=(x.rfqs||[]).find(a=>a.id===id);if(!r)return;const rows=(r.items||[]).map(i=>[esc(i.productName),esc(i.description||'—'),esc(i.quantity),esc(i.unit||'—'),money(i.rate),`${i.taxPercent==null?'—':Number(i.taxPercent)}%`,money(i.total)]);downloadPDF(r.rfqNo,`<div class="grid">${pdfField('RFQ No.',r.rfqNo)}${pdfField('Purchase Request',r.requestNo)}${pdfField('Purchaser TRN',companyTaxNumber())}${pdfField('Issue Date',r.issueDate)}${pdfField('Due Date',r.dueDate)}${pdfField('Status',r.status)}${pdfField(purchaseTaxLabel(),purchaseTaxRate()+'%')}${pdfField('Vendors',(r.vendors||[]).map(v=>v.name+' — TRN: '+(v.trn||vendorTRN(x,v)||'—')).join(', '))}</div><div class="section"><h3>Requested Items</h3>${pdfTable(['Product','Description','Qty','Unit','Estimated Rate',purchaseTaxLabel(),'Total'],rows)}</div><div class="total">Estimated Total: ${money(r.estimatedTotal)}</div>${r.notes?`<div class="note"><b>Notes</b><br>${esc(r.notes)}</div>`:''}`)}
function downloadPOPdf(id){const x=db(),o=(x.orders||[]).find(a=>a.id===id);if(!o)return;const rows=(o.items||[]).map(i=>[esc(i.productName),esc(i.quantity),esc(i.unit||'—'),money(i.rate||i.quotedRate),`${Number(i.taxPercent||0)}%`,`${Number(i.discountPercent||0)}%`,money(i.total)]);downloadPDF(o.poNo,`<div class="grid">${pdfField('PO No.',o.poNo)}${pdfField('Vendor',o.vendorName)}${pdfField('Purchase TRN',companyTaxNumber())}${pdfField('Vendor TRN',vendorTRN(x,o))}${pdfField('PO Date',o.poDate)}${pdfField('Expected Delivery',o.deliveryDate)}${pdfField('RFQ',o.rfqNo||'—')}${pdfField('Quotation',o.quotationNo||'—')}${pdfField('Delivery Location',o.deliveryLocation||'—')}${pdfField('Payment Terms',o.paymentTerms||'—')}${pdfField('Delivery Terms',o.deliveryTerms||'—')}</div><div class="section"><h3>Order Items</h3>${pdfTable(['Item','Qty','Unit','Rate','Tax','Discount','Total'],rows)}</div><div class="grid">${pdfField('Quotation Total',money(o.subtotal))}${pdfField('Shipping / Other',money(o.shippingCharges))}${pdfField('Additional Discount',money(o.additionalDiscount))}${pdfField('Status',o.status)}</div><div class="total">PO Total: ${money(o.total)}</div>${o.terms?`<div class="note"><b>Terms & Conditions</b><br>${esc(o.terms)}</div>`:''}`,{stamp:true})}
function downloadGRNPdf(id){const x=db(),r=(x.receipts||[]).find(a=>a.id===id);if(!r)return;const rows=(r.items||[]).map(i=>[esc(i.productName),esc(i.orderedQty),esc(i.receivedQty),esc(i.acceptedQty),esc(i.rejectedQty),esc(i.inspection||'—'),esc(i.remark||'—')]);downloadPDF(r.grnNo,`<div class="grid">${pdfField('GRN No.',r.grnNo)}${pdfField('PO No.',r.poNo)}${pdfField('Vendor',r.vendorName)}${pdfField('Vendor TRN',vendorTRN(x,r))}${pdfField('Purchaser TRN',companyTaxNumber())}${pdfField('Receipt Date',r.receivedDate)}${pdfField('Location',r.location)}${pdfField('Received By',r.receivedBy)}${pdfField('Status',r.status)}</div><div class="section"><h3>Goods Received</h3>${pdfTable(['Item','Ordered','Received','Accepted','Rejected','Inspection','Remark'],rows)}</div>${r.notes?`<div class="note"><b>Inspection Notes</b><br>${esc(r.notes)}</div>`:''}`)}
function downloadInvoicePdf(id){const x=db(),i=(x.invoices||[]).find(a=>a.id===id);if(!i)return;const m=invoiceMatch(x,i);downloadPDF(i.invoiceNo,`<div class="grid">${pdfField('Invoice No.',i.invoiceNo)}${pdfField('Vendor',i.vendorName)}${pdfField('Vendor TRN',vendorTRN(x,i))}${pdfField('Purchaser TRN',companyTaxNumber())}${pdfField('Invoice Date',i.invoiceDate)}${pdfField('Due Date',i.dueDate)}${pdfField('PO No.',i.poNo)}${pdfField('PO Total',money(m.po?.total||0))}${pdfField('Accepted GRN Value',money(m.received))}${pdfField('Invoice Subtotal',money(i.subtotal??i.amount))}${pdfField(purchaseTaxLabel(),`${Number(i.taxPercent==null?purchaseTaxRate():i.taxPercent)}%`)}${pdfField(purchaseTaxLabel()+' Amount',money(i.taxAmount??Math.max(0,Number(i.amount||0)-Number(i.subtotal??i.amount))))}${pdfField('Invoice Amount',money(i.amount))}${pdfField('3-Way Match',i.matchStatus||m.status)}${pdfField('Status',i.status)}${pdfField('Reference',i.referenceNo)}</div>${i.notes?`<div class="note"><b>Notes</b><br>${esc(i.notes)}</div>`:''}<div class="total">Invoice Amount: ${money(i.amount)}</div>`)}
function downloadPaymentPdf(id){const x=db(),p=(x.payments||[]).find(a=>a.id===id);if(!p)return;const i=(x.invoices||[]).find(a=>String(a.id)===String(p.invoiceId));downloadPDF(p.paymentNo,`<div class="grid">${pdfField('Payment No.',p.paymentNo)}${pdfField('Invoice No.',p.invoiceNo)}${pdfField('PO No.',p.poNo)}${pdfField('Vendor',p.vendorName)}${pdfField('Vendor TRN',vendorTRN(x,p))}${pdfField('Purchaser TRN',companyTaxNumber())}${pdfField('Payment Date',p.paymentDate)}${pdfField('Amount',money(p.amount))}${pdfField('Payment Method',p.method)}${pdfField('Reference No.',p.referenceNo)}${pdfField('Invoice Total',money(i?.amount||0))}${pdfField('Outstanding Balance',money(i?invoiceBalance(x,i):0))}${pdfField('Status',p.status)}</div>${p.account?`<div class="note"><b>Bank / Account</b><br>${esc(p.account)}</div>`:''}${p.notes?`<div class="note"><b>Notes</b><br>${esc(p.notes)}</div>`:''}<div class="total">Payment Amount: ${money(p.amount)}</div>`)}
function roleCard(role,perms){normalizeRolePermissions(role,perms);const modules=Object.entries(PERMISSION_MODULES).filter(([k])=>perms.permissions?.[k]?.view);const actionCount=Object.values(perms.permissions||{}).reduce((n,p)=>n+Object.values(p||{}).filter(Boolean).length,0);return `<div class="role-permission-card"><div><b>${esc(role)}</b><small>${modules.length} modules · ${actionCount} permissions enabled</small></div><button class="btn-sm" onclick="openRole('${esc(role)}')"><i class="ti ti-settings"></i> Permissions</button><div class="permission-chips">${modules.map(([k,v])=>`<span>${esc(v)}</span>`).join('')}</div></div>`}

function openAdminResetPassword(id){
  const x=db(),u=(x.users||[]).find(a=>String(a.id)===String(id));
  if(!u){toast('User not found');return}
  openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>Reset User Password</h3><small>Administrator password reset for ${esc(u.name||u.email)}</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="detail-note"><b>User</b><p>${esc(u.name||'')} · ${esc(u.email||'')}</p></div><label>New Password<input id="admin-reset-password" type="password" autocomplete="new-password" minlength="8" placeholder="Minimum 8 characters"></label><label>Confirm New Password<input id="admin-reset-password-confirm" type="password" autocomplete="new-password" minlength="8" placeholder="Re-enter new password"></label><div class="detail-note"><b>Administrator action</b><p>This resets the selected user's password without requiring their current password.</p></div></div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="adminResetPassword('${u.id}')"><i class="ti ti-key"></i> Update Password</button></div></div></div>`);
}
async function adminResetPassword(id){
  const password=document.getElementById('admin-reset-password')?.value||'';
  const confirm=document.getElementById('admin-reset-password-confirm')?.value||'';
  if(password.length<8){toast('New password must be at least 8 characters');return}
  if(password!==confirm){toast('Passwords do not match');return}
  try{
    await api(`/users/${id}/password`,{method:'POST',body:JSON.stringify({password,confirmPassword:confirm})});
    closeModal();
    toast('User password updated successfully');
  }catch(error){toast(error.message||'Unable to update password')}
}
function toggleUserManagerField(){const r=document.getElementById('user-role')?.value,w=document.getElementById('user-manager-wrap');if(w)w.style.display=['Salesperson','Sales Representative'].includes(r)?'block':'none'}
function openUser(id){const x=db(),u=id?(x.users||[]).find(a=>String(a.id)===String(id)):null,roles=Object.keys(x.roles||{});if(u?.role==='Admin'&&u.email==='admin@purchase.local'&&currentUser()?.email!==u.email){/* allowed to edit profile */}openModal(`<div class="modal" id="modal"><div class="modal-box request-modal"><div class="modal-head"><div><h3>${u?'Edit User':'Add User'}</h3><small>Create a login and assign a role</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="grid2"><label>Full Name<input id="user-name" value="${esc(u?.name||'')}"></label><label>Email Address<input id="user-email" type="email" value="${esc(u?.email||'')}"></label><label>Password<input id="user-password" type="password" placeholder="${u?'Leave blank to keep current password':'Set password'}"></label><label>Role<select id="user-role" onchange="toggleUserManagerField()">${roles.map(r=>`<option ${u?.role===r?'selected':''}>${esc(r)}</option>`).join('')}</select></label><label id="user-manager-wrap" style="display:${['Salesperson','Sales Representative'].includes(u?.role)?'block':'none'}">Sales Manager<select id="user-manager"><option value="">Select Manager</option>${(x.users||[]).filter(m=>m.active!==false&&m.role==='Sales Manager').map(m=>`<option value="${m.id}" ${String(u?.managerId)===String(m.id)?'selected':''}>${esc(m.name)}</option>`).join('')}</select></label></div><label class="check-line"><input id="user-active" type="checkbox" ${u?.active!==false?'checked':''}> Active user</label></div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="saveUser(&quot;${u?.id||""}&quot;)">Save User</button></div></div></div>`)}
async function saveUser(id){
  const x = db();
  const name = document.getElementById('user-name').value.trim();
  const email = document.getElementById('user-email').value.trim().toLowerCase();
  const pw = document.getElementById('user-password').value;
  const role = document.getElementById('user-role').value;
  const active = document.getElementById('user-active').checked;

  if (!name || !email || (!id && !pw)) {
    toast('Name, email and password are required');
    return;
  }
  if(['Salesperson','Sales Representative'].includes(role) && !document.getElementById('user-manager')?.value){
    toast('Select a Sales Manager for this salesperson');
    return;
  }

  try {
    let savedUser;

    if (id) {
      savedUser = await api(`/users/${id}`, {
        method: 'PUT',
        body: JSON.stringify({ name, email, password: pw, role, managerId:document.getElementById('user-manager')?.value||null, active })
      });
    } else {
      savedUser = await api('/users', {
        method: 'POST',
        body: JSON.stringify({ name, email, password: pw, role, managerId:document.getElementById('user-manager')?.value||null, active })
      });
    }

    const index = x.users.findIndex(u => String(u.id) === String(savedUser.id));
    const cleanUser = {
      id: savedUser.id,
      name: savedUser.name,
      email: savedUser.email,
      role: savedUser.role,
      managerId: savedUser.managerId || null,
      active: savedUser.active
    };

    if (index >= 0) x.users[index] = cleanUser;
    else x.users.unshift(cleanUser);

    recordActivity(x, id ? 'Updated' : 'Created', 'Users',
      (id ? 'User updated: ' : 'User created: ') + name, 'User');
    save(x);
    closeModal();
    renderUsers();
    toast(id ? 'User updated' : 'User created');
  } catch (error) {
    toast(error.message || 'Unable to save user');
  }
}

async function toggleUser(id){
  const x = db();
  const u = (x.users || []).find(a => String(a.id) === String(id));
  if (!u) return;

  if (u.email === 'admin@purchase.local' && u.active !== false) {
    toast('The main admin account cannot be deactivated');
    return;
  }

  const nextActive = u.active === false;

  try {
    const savedUser = await api(`/users/${id}`, {
      method: 'PUT',
      body: JSON.stringify({
        name: u.name,
        email: u.email,
        role: u.role,
        active: nextActive,
        password: ''
      })
    });

    u.active = savedUser.active;
    recordActivity(x, u.active ? 'Activated' : 'Deactivated', 'Users',
      u.name + ' was ' + (u.active ? 'activated' : 'deactivated'), 'User');
    save(x);
    renderUsers();
    toast(u.active ? 'User activated' : 'User deactivated');
  } catch (error) {
    toast(error.message || 'Unable to update user');
  }
}

function openRole(role){const x=db(),perms=normalizeRolePermissions(role,x.roles[role]||{});const rows=Object.entries(PERMISSION_MODULES).map(([module,label])=>{const p=perms.permissions[module]||{};return `<tr><td><b>${esc(label)}</b><small style="display:block;color:#9CA3AF;margin-top:2px">${esc(module)}</small></td>${PERMISSION_ACTIONS.map(action=>`<td style="text-align:center"><input type="checkbox" data-rmodule="${module}" data-action="${action}" ${p[action]?'checked':''} ${action!=='view'&&!p.view?'disabled':''}></td>`).join('')}</tr>`}).join('');openModal(`<div class="modal" id="modal"><div class="modal-box request-modal wide"><div class="modal-head"><div><h3>${esc(role)} Permissions</h3><small>Control View, Create, Edit, Delete, Approve and Export access by module.</small></div><button onclick="closeModal()">×</button></div><div class="modal-body"><div class="permission-toolbar"><button type="button" class="btn-sm" onclick="setAllRolePermissions(true)">Enable All</button><button type="button" class="btn-sm" onclick="setAllRolePermissions(false)">Disable All</button><span class="hint">View controls access; other actions control what the user can do.</span></div><div class="table-wrap"><table class="permission-matrix"><thead><tr><th>Module</th>${PERMISSION_ACTIONS.map(a=>`<th>${PERMISSION_LABELS[a]}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div></div><div class="modal-foot"><button class="btn-secondary" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="saveRole('${esc(role)}')">Save Permissions</button></div></div></div>`);document.querySelectorAll('[data-action="view"]').forEach(el=>el.addEventListener('change',()=>{const m=el.dataset.rmodule;document.querySelectorAll(`[data-rmodule="${m}"]`).forEach(x=>{if(x.dataset.action!=='view'){x.disabled=!el.checked;if(!el.checked)x.checked=false}})}))}
function setAllRolePermissions(enabled){document.querySelectorAll('[data-rmodule]').forEach(el=>{el.checked=enabled;el.disabled=!enabled&&el.dataset.action!=='view'})}
function saveRole(role){const x=db(),p=normalizeRolePermissions(role,x.roles[role]||{});document.querySelectorAll('[data-rmodule]').forEach(el=>{const m=el.dataset.rmodule,a=el.dataset.action;p.permissions[m][a]=el.checked;if(a==='view')p[m]=el.checked});Object.keys(p.permissions).forEach(m=>{if(!p.permissions[m].view)Object.keys(p.permissions[m]).forEach(a=>p.permissions[m][a]=false);p[m]=!!p.permissions[m].view});x.roles[role]=p;recordActivity(x,'Updated','Roles','Permissions updated for role: '+role,'Role');save(x);closeModal();renderUsers();toast('Permissions updated for '+role)}

