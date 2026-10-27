"""Department access, shared operational handoffs and private CRM/HR/expenses."""
from decimal import Decimal
import io
import pytest
from backend.test_app import app, session, patch, PASSWORD
from backend.test_erp import post, seed, assert_balanced


@pytest.fixture
def department(app):
    admin,h=session(app)
    users={};clients={'admin':(admin,h)}
    definitions=[('manager','Sales Manager',None),('other-manager','Sales Manager',None),
                 ('a','Salesperson','manager'),('b','Salesperson','manager'),
                 ('c','Salesperson','other-manager'),('crm','CRM Manager',None),
                 ('finance','Finance',None),('procurement','Procurement Staff',None),
                 ('production','Manufacturing Manager',None)]
    for name,role,manager in definitions:
        response=admin.post('/api/users',headers=h,json=dict(name=name,email=name+'@department.test',
                    role=role,password=PASSWORD,active=True,managerId=users.get(manager)))
        assert response.status_code==200,response.json
        users[name]=response.json['id']
        client=app.test_client();login=client.post('/api/auth/login',json=dict(email=name+'@department.test',password=PASSWORD))
        assert login.status_code==200
        clients[name]=(client,{'X-CSRF-Token':login.json['csrfToken']})
    return clients,users


def save(client,headers,changes,path='/api/state'):
    response=patch(client,headers,changes,path)
    assert response.status_code==200,response.json


def test_shared_masters_finance_and_production_handoffs(app,department):
    clients,users=department;admin,h=clients['admin'];seed(admin,h)
    # Shared master records remain usable when another department created them.
    for who in ('a','b','c','crm','finance'):
        data=clients[who][0].get('/api/state').json['state']
        assert data['customers']
    for who in ('a','procurement','production'):
        assert clients[who][0].get('/api/state').json['state']['products']
    procurement,ph=clients['procurement']
    assert procurement.get('/api/state').json['state']['vendors']
    # Procurement posts a stock adjustment; production can use the same warehouse.
    # Default Procurement Staff cannot approve inventory adjustments; permissions still apply.
    assert procurement.post('/api/erp/inventory/adjust',headers=ph,json={}).status_code==403
    production,mh=clients['production']
    bom=production.get('/api/erp/boms').json['boms'][0]
    order=post(production,mh,'/manufacturing',dict(requestKey='department-kits',bomId=bom['id'],quantity=2))
    for action in ('confirm','start','complete'):post(production,mh,f'/manufacturing/{order["id"]}/{action}')
    # A second authorized production user can see and advance another creator's order.
    assert admin.get('/api/erp/manufacturing').json['orders'][0]['state']=='Done'
    finance,_=clients['finance']
    report=finance.get('/api/erp/reports').json
    assert Decimal(report['cashBank'])==275000
    assert Decimal(report['balanceCheck'])==0
    assert any(e['source'].startswith('mo:') or e['source'].startswith('stock:mo:') for e in finance.get('/api/erp/entries').json['entries'])
    inv=procurement.get('/api/erp/inventory').json
    assert Decimal(next(p['quantity'] for p in inv['products'] if p['id']=='9003'))==2
    assert Decimal(procurement.get('/api/erp/overview').json['inventoryValue'])==60200
    assert clients['a'][0].get('/api/erp/entries').status_code==403
    assert production.get('/api/erp/reports').status_code==403
    roles=admin.get('/api/state').json['state']['roles']
    roles['Viewer']['accounting']=True;roles['Viewer']['permissions']['accounting']['view']=True
    save(admin,h,dict(roles=roles))
    reader,rh=session(app,'viewer')
    assert Decimal(reader.get('/api/erp/reports').json['cashBank'])==275000
    assert reader.get('/api/erp/bank-statements').status_code==200
    assert reader.post('/api/erp/bank-statements',headers=rh,json={}).status_code==403
    assert_balanced(app)


def test_private_crm_assignment_sales_team_and_finance_access(app,department):
    clients,users=department;crm,ch=clients['crm']
    save(crm,ch,dict(customers=[dict(id=1,name='Shared CRM customer',status='Active')],
                    leads=[dict(id=1,customerId=1,customerName='Shared CRM customer',ownerId=users['a'])]))
    for who in ('crm','a','manager','admin'):
        assert clients[who][0].get('/api/state').json['state']['leads'],who
    for who in ('b','c','other-manager','finance','procurement'):
        assert not clients[who][0].get('/api/state').json['state']['leads'],who
    # Customer shared across teams; private opportunity is not.
    assert clients['c'][0].get('/api/state').json['state']['customers']
    a,ah=clients['a'];quote=dict(id=2,quotationNo='SQ-DEPARTMENT',leadId=1,customerId=1,status='Draft')
    save(a,ah,dict(salesQuotations=[quote]))
    for who in ('a','b','manager','crm','admin'):
        assert clients[who][0].get('/api/state').json['state']['salesQuotations'],who
    assert not clients['c'][0].get('/api/state').json['state']['salesQuotations']
    # A guessed private lead ID cannot be edited by an unrelated colleague.
    assert patch(clients['b'][0],clients['b'][1],dict(leads=[dict(id=1,customerId=1)])).status_code==403
    forged=dict(id=3,name='Forged',createdBy=users['crm'])
    assert patch(a,ah,dict(customers=[forged])).status_code==403
    save(a,ah,dict(salesOrders=[dict(id=4,orderNo='SO-DEPARTMENT',quotationId=2,customerId=1,status='Draft')]))
    admin,h=clients['admin']
    save(admin,h,dict(customerInvoices=[dict(id=5,invoiceNo='INV-DEPARTMENT',orderId=4,amount=100,status='Posted')]))
    finance,fh=clients['finance']
    assert finance.get('/api/state').json['state']['customerInvoices']
    assert finance.get('/api/state').json['state']['salesOrders']
    assert Decimal(finance.get('/api/erp/reports').json['receivables'])==100
    assert not clients['c'][0].get('/api/state').json['state']['salesOrders']
    # Same-team colleague can progress the quotation without reading the private CRM lead.
    rows=clients['b'][0].get('/api/state').json['state']['salesQuotations'];rows[0]['status']='Pending Approval'
    save(clients['b'][0],clients['b'][1],dict(salesQuotations=rows))
    assert crm.get('/api/state').json['state']['leads'][0]['stage']=='Quotation Pending Approval'
    # CRM can explicitly reassign its lead across sales teams; unrelated users still cannot.
    lead=crm.get('/api/state').json['state']['leads'][0];lead['ownerId']=users['c']
    save(crm,ch,dict(leads=[lead]))
    assert clients['c'][0].get('/api/state').json['state']['leads']
    assert not a.get('/api/state').json['state']['leads']
    assert lead['createdBy']==users['crm']


def test_purchasing_handoff_hr_privacy_and_expense_reimbursement(app,department):
    clients,users=department;admin,h=clients['admin'];proc,ph=clients['procurement']
    # Procurement can act on requests and RFQs created by another authorized department user.
    save(admin,h,dict(requests=[dict(id=11,requestNo='REQ-SHARED')],rfqs=[dict(id=12,rfqNo='RFQ-SHARED',requestId=11)]))
    data=proc.get('/api/state').json['state'];assert data['requests'] and data['rfqs']
    data['rfqs'][0]['notes']='Procurement follow-up';save(proc,ph,dict(rfqs=data['rfqs']))
    assert admin.get('/api/state').json['state']['rfqs'][0]['createdBy']=='admin'
    # HR can see company employees; Finance and normal sales users cannot see salary records.
    save(admin,h,dict(employees=[dict(id='employee-a',employeeId='EMP-A',name='Employee A',salary=1000,linkedUserId=users['a']),
                                dict(id='employee-b',employeeId='EMP-B',name='Employee B',salary=2000,linkedUserId=users['b'])],
                      payroll=[dict(id='pay-a',employee='EMP-A - Employee A',month='2026-10',status='Draft'),
                               dict(id='pay-b',employee='EMP-B - Employee B',month='2026-10',status='Draft')]),'/api/hr/state')
    hr,hh=session(app,'hr')
    assert len(hr.get('/api/hr/state').json['state']['employees'])==2
    assert not clients['finance'][0].get('/api/hr/state').json['state']['payroll']
    # Grant self-service read access, without granting HR administration.
    roles=admin.get('/api/state').json['state']['roles']
    for module in ('hr_employees','hr_payroll'):
        roles['Salesperson'][module]=True;roles['Salesperson']['permissions'][module]['view']=True
    roles['Sales Manager']['permissions']['expenses']['approve']=True
    save(admin,h,dict(roles=roles))
    for who,employee in [('a','employee-a'),('b','employee-b')]:
        data=clients[who][0].get('/api/hr/state').json['state']
        assert [e['id'] for e in data['employees']]==[employee]
        assert len(data['payroll'])==1
        data['employees'][0]['salary']=999999
        assert patch(clients[who][0],clients[who][1],dict(employees=data['employees']),'/api/hr/state').status_code==403
    a,ah=clients['a'];claim=post(a,ah,'/expenses',dict(requestKey='department-expense',account='6110',description='Employee travel',amount=25))
    post(a,ah,f'/expenses/{claim["id"]}/submit')
    assert not clients['b'][0].get('/api/erp/expenses').json['expenses']
    manager,mh=clients['manager'];assert manager.get('/api/erp/expenses').json['expenses']
    post(manager,mh,f'/expenses/{claim["id"]}/approve')
    post(manager,mh,f'/expenses/{claim["id"]}/pay',dict(account='1010'),expected=403)
    finance,fh=clients['finance'];assert finance.get('/api/erp/expenses').json['expenses']
    post(finance,fh,f'/expenses/{claim["id"]}/pay',dict(account='1010'))
    assert a.get('/api/erp/expenses').json['expenses'][0]['status']=='Paid'
    assert_balanced(app)


def test_attachments_follow_department_and_expense_privacy(app,department):
    clients,users=department;proc,ph=clients['procurement'];a,ah=clients['a']
    response=proc.post('/api/attachments',headers=ph,data={'module':'quotations','file':(io.BytesIO(b'%PDF-supplier'),'supplier.pdf')})
    assert response.status_code==200
    supplier=response.json['attachmentPath']
    assert clients['admin'][0].get('/api/attachments/'+supplier).status_code==200
    assert a.get('/api/attachments/'+supplier).status_code==403
    response=a.post('/api/attachments',headers=ah,data={'module':'expenses','file':(io.BytesIO(b'%PDF-receipt'),'receipt.pdf')})
    receipt=response.json['attachmentPath']
    for who in ('a','manager','finance','admin'):
        assert clients[who][0].get('/api/attachments/'+receipt).status_code==200
    for who in ('b','c','procurement'):
        assert clients[who][0].get('/api/attachments/'+receipt).status_code==403
