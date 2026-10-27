"""One creator/direct-manager/Admin rule across every module, including direct IDs."""
from copy import deepcopy
from decimal import Decimal
import io

import pytest
from backend.test_app import app, session, patch, PASSWORD
from backend.permissions import COLLECTIONS, HR_COLLECTIONS
from backend.test_erp import post, assert_balanced


@pytest.fixture
def team(app):
    admin, h = session(app)
    roles = admin.get('/api/state').json['state']['roles']
    # Give this test role all module actions to isolate record scope from module access.
    for permissions in roles['Finance']['permissions'].values():
        for action in permissions:permissions[action] = True
    assert patch(admin,h,dict(roles=roles)).status_code == 200
    users = {}
    clients = {'admin': (admin,h)}
    for name, manager in [('m1',None),('m2',None),('a','m1'),('b','m1'),('c','m2')]:
        response = admin.post('/api/users',headers=h,json=dict(name=name,email=name+'@scope.test',
                     role='Finance',password=PASSWORD,active=True,managerId=users.get(manager)))
        assert response.status_code == 200,response.json
        users[name] = response.json['id']
        client = app.test_client()
        login=client.post('/api/auth/login',json=dict(email=name+'@scope.test',password=PASSWORD))
        assert login.status_code == 200
        clients[name]=(client,{'X-CSRF-Token':login.json['csrfToken']})
    return clients,users


def save(client, headers, changes, path='/api/state'):
    response=patch(client,headers,changes,path)
    assert response.status_code == 200,response.json
    return response


def business_records():
    rows={key:[dict(id=101,name='Private '+key)] for key in COLLECTIONS}
    fields={'requests':'requestNo','rfqs':'rfqNo','quotations':'quotationNo','orders':'poNo',
            'receipts':'grnNo','invoices':'invoiceNo','payments':'paymentNo','salesQuotations':'quotationNo',
            'salesOrders':'orderNo','deliveries':'deliveryNo','customerInvoices':'invoiceNo','customerPayments':'paymentNo'}
    for key,field in fields.items():rows[key][0][field]='PRIVATE-'+key
    rows['products'][0].update(productType='stock',unit='Each')
    rows['salesQuotations'][0]['status']='Draft'
    rows['receipts'][0].update(poId=101,items=[])
    rows['deliveries'][0].update(orderId=101,status='Pending',items=[])
    rows['payments'][0].update(invoiceId=101,status='Draft')
    rows['customerPayments'][0].update(invoiceId=101,status='Draft')
    return rows


def test_all_business_and_hr_collections_are_private(app,team):
    clients,users=team
    a,ah=clients['a'];save(a,ah,business_records())
    hr={key:[dict(id='hr-'+key,name='Private '+key)] for key in HR_COLLECTIONS}
    hr['employees'][0].update(employeeId='EMP-PRIVATE',name='Private Employee',salary=100,status='Active')
    hr['leaves'][0].update(employee='EMP-PRIVATE - Private Employee',**{'from':'2026-11-01','to':'2026-11-02'},status='Pending')
    hr['payroll'][0].update(employee='EMP-PRIVATE - Private Employee',month='2026-11',status='Draft')
    save(a,ah,hr,'/api/hr/state')
    for who in ('a','m1','admin','b','c','m2'):
        client,_=clients[who]
        visible=who in ('a','m1','admin')
        for endpoint,collections in [('/api/state',COLLECTIONS),('/api/hr/state',HR_COLLECTIONS)]:
            data=client.get(endpoint).json['state']
            for key in collections:
                assert len(data[key]) == int(visible),(who,key,data[key])
                if visible:assert data[key][0]['createdBy']==users['a']
    b,bh=clients['b']
    assert patch(b,bh,dict(rfqs=[dict(id=101,rfqNo='STOLEN')])).status_code==403
    forged=dict(id=102,name='Forged',createdBy=users['a'])
    assert patch(b,bh,dict(vendors=[forged])).status_code==403
    # Hidden rows survive an unrelated same-register save by another creator.
    save(b,bh,dict(vendors=[dict(id=102,name='B vendor')]))
    assert len(clients['admin'][0].get('/api/state').json['state']['vendors'])==2
    m,mh=clients['m1'];records=m.get('/api/state').json['state']['rfqs'];records[0]['notes']='Manager reviewed'
    save(m,mh,dict(rfqs=records))
    assert a.get('/api/state').json['state']['rfqs'][0]['createdBy']==users['a']
    records[0]['createdBy']=users['m1']
    assert patch(m,mh,dict(rfqs=records)).status_code==403
    # Cross-team parent references and HR employee links cannot be guessed.
    assert patch(b,bh,dict(leads=[dict(id=102,customerId=101)])).status_code==403
    assert patch(b,bh,dict(attendance=[dict(id='x',employee='EMP-PRIVATE - Private Employee',date='2026-11-01')]),'/api/hr/state').status_code==403
    # Current direct-manager assignment controls historical records immediately.
    admin,h=clients['admin']
    profile=next(u for u in admin.get('/api/users').json['users'] if u['id']==users['a'])
    profile['managerId']=users['m2']
    assert admin.put('/api/users/'+users['a'],headers=h,json=profile).status_code==200
    assert not clients['m1'][0].get('/api/state').json['state']['rfqs']
    assert clients['m2'][0].get('/api/state').json['state']['rfqs']


def test_relational_records_reports_and_direct_actions_are_scoped(app,team):
    clients,users=team;a,ah=clients['a'];m,mh=clients['m1'];b,bh=clients['b']
    save(a,ah,dict(products=[dict(id=1,name='Own raw',productType='stock'),dict(id=2,name='Own finished',productType='stock')]))
    post(a,ah,'/inventory/adjust',dict(requestKey='own-opening-stock',productId=1,quantity=10,unitCost=10,reason='Opening stock'))
    bom=post(a,ah,'/boms',dict(requestKey='own-bom-key',name='Own BoM',productId=2,quantity=1,conversionCost=0,components=[dict(productId=1,quantity=2)]))
    mo=post(a,ah,'/manufacturing',dict(requestKey='own-mo-key',bomId=bom['id'],quantity=2))
    for action in ('confirm','start','complete'):post(m,mh,f'/manufacturing/{mo["id"]}/{action}')
    expense=post(a,ah,'/expenses',dict(requestKey='own-expense-key',description='Private travel',account='6110',amount=12))
    post(a,ah,f'/expenses/{expense["id"]}/submit')
    post(m,mh,f'/expenses/{expense["id"]}/approve')
    post(m,mh,f'/expenses/{expense["id"]}/pay',dict(account='1010'))
    transfer=post(a,ah,'/transfers',dict(requestKey='own-transfer-key',fromAccount='1010',toAccount='1000',amount=5))
    statement=post(a,ah,'/bank-statements',dict(requestKey='own-bank-statement',account='1010',amount=-5,description='Own withdrawal'))
    line=next(l for l in transfer['lines'] if l['account']=='1010')
    post(m,mh,f'/bank-statements/{statement["id"]}/match',dict(lineId=line['id']))
    post(a,ah,'/accounts',dict(code='6199',name='Private account',type='expense'))
    for who in ('a','m1','admin','b','c','m2'):
        client,_=clients[who];visible=who in ('a','m1','admin')
        for endpoint,field in [('/boms','boms'),('/manufacturing','orders'),('/expenses','expenses'),('/entries','entries'),('/bank-statements','statements')]:
            response=client.get('/api/erp'+endpoint)
            assert response.status_code==200,response.json
            assert bool(response.json[field]) is visible,(who,endpoint)
        assert bool(client.get('/api/erp/bank-statements').json['ledger']) is visible
        inv=client.get('/api/erp/inventory').json
        assert bool(inv['products']) is visible and bool(inv['moves']) is visible
        report=client.get('/api/erp/reports').json
        assert bool(report['ledger']) is visible
        assert Decimal(report['profit'])==(88 if visible else 0)
        assert Decimal(report['balanceCheck'])==0
        assert ('6199' in [r['code'] for r in client.get('/api/erp/accounts').json['accounts']]) is visible
        overview=client.get('/api/erp/overview').json
        assert Decimal(overview['inventoryValue'])==(100 if visible else 0)
    for endpoint,data in [(f'/manufacturing/{mo["id"]}/complete',{}),
                          (f'/expenses/{expense["id"]}/approve',{}),
                          (f'/entries/{transfer["id"]}/reverse',{}),
                          (f'/bank-statements/{statement["id"]}/match',dict(lineId=line['id'])),
                          ('/reconcile',dict(debitLine=line['id'],creditLine=line['id'])),
                          ('/manufacturing',dict(requestKey='steal-bom-key',bomId=bom['id'],quantity=1)),
                          ('/inventory/adjust',dict(requestKey='steal-stock-key',productId=1,quantity=1,unitCost=1,reason='Bad'))]:
        post(b,bh,endpoint,data,expected=403)
    # Guessing another user's idempotency key cannot return their object.
    post(b,bh,'/boms',dict(requestKey='own-bom-key'),expected=403)
    post(b,bh,'/transfers',dict(requestKey='own-transfer-key',fromAccount='1010',toAccount='1000',amount=5),expected=403)
    zero=post(a,ah,'/inventory/adjust',dict(requestKey='zero-value-stock-key',productId=2,quantity=1,unitCost=0,reason='Zero-value sample'))
    assert Decimal(zero['value'])==0
    assert any(move['id']==zero['id'] for move in m.get('/api/erp/inventory').json['moves'])
    assert not b.get('/api/erp/inventory').json['moves']
    assert_balanced(app)


def test_attachments_legacy_fail_closed_and_manager_cycles(app,team):
    clients,users=team;a,ah=clients['a'];admin,h=clients['admin']
    response=a.post('/api/attachments',headers=ah,data={'module':'requests','file':(io.BytesIO(b'%PDF-test'),'private.pdf')})
    assert response.status_code==200,response.json
    attachment=response.json['attachmentPath']
    for who in ('a','m1','admin','b','m2'):
        expected=200 if who in ('a','m1','admin') else 403
        assert clients[who][0].get('/api/attachments/'+attachment).status_code==expected
    # Legacy unattributed rows remain Admin-only; role access never publishes them.
    from backend.app import db, Document
    with app.app_context():
        doc=db.session.get(Document,'app');data=deepcopy(doc.data)
        data['vendors']=[dict(id=99,name='Unattributed')];doc.data=data;db.session.commit()
    assert not a.get('/api/state').json['state']['vendors']
    assert admin.get('/api/state').json['state']['vendors']
    runner=app.test_cli_runner()
    args=['assign-legacy-owner','--namespace','app','--collection','vendors','--record-id','99','--creator-email','a@scope.test']
    result=runner.invoke(args=args)
    assert result.exit_code==0,result.output
    assert a.get('/api/state').json['state']['vendors'][0]['createdBy']==users['a']
    assert runner.invoke(args=args).exit_code!=0
    profile=next(u for u in admin.get('/api/users').json['users'] if u['id']==users['m1'])
    profile['managerId']=users['a']
    assert admin.put('/api/users/'+users['m1'],headers=h,json=profile).status_code==400
