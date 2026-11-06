"""Independent approvals, limits, atomic execution, stale requests and bypass guards."""
from decimal import Decimal
from sqlalchemy import select, func
from werkzeug.security import generate_password_hash
from backend.test_app import app, session, PASSWORD
from backend.app import db, User, Audit
from backend.erp import JournalEntry, Expense
from backend.approval_api import Approval


def enable(app):
    with app.app_context():
        for uid, role in [('finance', 'Finance'), ('otheradmin', 'Admin')]:
            db.session.add(User(id=uid,name=uid,email=uid+'@example.test',role=role,active=True,password_hash=generate_password_hash(PASSWORD)))
        db.session.commit()
    app.config['APPROVAL_CONTROLS'] = True


def transfer(c,h,key='approval-transfer',amount='100'):
    r=c.post('/api/finance/commands/transfer',headers=h,json=dict(requestKey=key,fromAccount='1000',toAccount='1010',amount=amount,date='2026-11-06'))
    assert r.status_code==409,r.json
    return r.json['approval']


def decide(c,h,row,action='approve',expected=200,reason='Reviewed source and supporting evidence'):
    r=c.post(f"/api/approvals/{row['id']}/{action}",headers=h,json=dict(reason=reason))
    assert r.status_code==expected,r.json
    return r


def test_limits_self_approval_execute_once_and_audit(app):
    enable(app)
    c,h=session(app);f,fh=session(app,'finance')
    row=transfer(c,h,amount='1000001')
    assert not any(u['id']=='finance' for u in row['approvers'])
    decide(c,h,row,expected=403)
    decide(f,fh,row,expected=403)
    assert f.put('/api/approvals/limits',headers=fh,json={}).status_code==403
    r=c.put('/api/approvals/limits',headers=h,json=dict(userId='finance',module='accounting',amount='1000001'))
    assert r.status_code==200,r.json
    decide(f,fh,row,reason='',expected=400)
    result=decide(f,fh,row).json
    assert result['record']['status']=='Approved'
    decide(f,fh,row,expected=409)
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(JournalEntry))==1
        event=db.session.scalar(select(Audit).where(Audit.action=='Approval approved'))
        assert event.actor_id=='finance' and event.details['reason'].startswith('Reviewed')
    repeat=transfer(c,h,amount='1000001')
    assert repeat['id']==row['id'] and repeat['status']=='Approved'


def test_rejection_no_posting_csrf_and_privacy(app):
    enable(app);c,h=session(app);f,fh=session(app,'finance');v,vh=session(app,'viewer')
    row=transfer(c,h)
    assert c.post('/api/approvals/'+str(row['id'])+'/approve',json=dict(reason='x')).status_code==403
    assert v.get('/api/approvals').json['items']==[]
    decide(v,vh,row,'reject',403)
    decide(f,fh,row,'reject')
    decide(f,fh,row,expected=409)
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(JournalEntry))==0
        assert db.session.get(Approval,row['id']).reason
    assert c.post('/api/erp/transfers',headers=h,json={}).status_code==410
    assert c.patch('/api/state',headers=h,json=dict(changes={'orders':[]})).status_code==410


def test_expense_independence_and_stale_version_rollback(app):
    c,h=session(app)
    claim=c.post('/api/expenses/commands/create',headers=h,json=dict(description='Travel',amount='100',date='2026-11-06',requestKey='expense-create')).json['record']
    claim=c.post('/api/expenses/commands/submit',headers=h,json=dict(id=claim['id'],version=claim['version'],requestKey='expense-submit')).json['record']
    enable(app);f,fh=session(app,'finance')
    payload=dict(id=claim['id'],version=claim['version'],requestKey='expense-approve')
    r=c.post('/api/expenses/commands/approve',headers=h,json=payload)
    assert r.status_code==409,r.json
    row=r.json['approval'];decide(c,h,row,expected=403)
    with app.app_context():
        e=db.session.get(Expense,claim['id']);e.description='Changed after request';db.session.commit()
    decide(f,fh,row,expected=409)
    with app.app_context():
        assert db.session.get(Approval,row['id']).status=='Pending'
        assert db.session.scalar(select(func.count()).select_from(JournalEntry))==0
        assert not db.session.scalar(select(Audit).where(Audit.action=='Approval approved'))
    claim=c.get('/api/expenses/claims/'+str(claim['id'])).json['record']
    r=c.post('/api/expenses/commands/approve',headers=h,json={**payload,'version':claim['version'],'requestKey':'expense-new-version'})
    decide(f,fh,r.json['approval'])
    assert c.get('/api/expenses/claims/'+str(claim['id'])).json['record']['status']=='Approved'


def test_limit_validation_and_permission_revocation(app):
    enable(app);c,h=session(app);f,fh=session(app,'finance')
    for invalid in ['NaN','Infinity','-1',True,'1.001']:
        r=c.put('/api/approvals/limits',headers=h,json=dict(userId='finance',module='accounting',amount=invalid))
        assert r.status_code==400,r.json
    row=transfer(c,h)
    with app.app_context():
        u=db.session.get(User,'finance');u.role='Viewer';db.session.commit()
    decide(f,fh,row,expected=403)


def test_submission_routes_expense_and_independent_finance_executes(app):
    enable(app);c,h=session(app);f,fh=session(app,'finance')
    claim=c.post('/api/expenses/commands/create',headers=h,json=dict(description='Auto route',amount=500,date='2026-11-06',requestKey='auto-expense-create')).json['record']
    r=c.post('/api/expenses/commands/submit',headers=h,json=dict(id=claim['id'],version=claim['version'],requestKey='auto-expense-submit'))
    assert r.status_code==200,r.json
    assert r.json['approvalRequested']
    inbox=f.get('/api/approvals').json['items']
    assert len(inbox)==1 and inbox[0]['canDecide']
    decide(f,fh,inbox[0])
    assert c.get('/api/expenses/claims/'+str(claim['id'])).json['record']['status']=='Approved'


def test_inventory_value_is_authoritative_and_execution_is_independent(app):
    from backend.test_inventory_api import make_product, product
    c,h=session(app);p=make_product(c,h)
    enable(app);a,ah=session(app,'otheradmin')
    r=c.post('/api/inventory/commands/adjust',headers=h,json=dict(productId=p,version=product(c,p)['version'],quantity=10,unitCost=12,reason='Stock count',requestKey='approval-stock-adjust'))
    assert r.status_code==409,r.json
    row=r.json['approval'];assert Decimal(row['amount'])==120
    assert Decimal(product(c,p)['quantity'])==0
    decide(c,h,row,expected=403)
    decide(a,ah,row)
    assert Decimal(product(c,p)['quantity'])==10


def test_purchase_order_and_bill_route_with_real_totals(app):
    from backend.test_trade_api import masters, create, details, purchase
    c,h=session(app);p,v,_=masters(c,h)
    po=purchase(c,h,p,v)
    # Existing already-approved orders still require independent authority to close;
    # a fresh draft PO submission is routed before any spending authorization.
    draft=create(c,h,'orders',deliveryDate='2027-12-31',vendorId=v['id'],items=[dict(productId=p['id'],quantity=2,rate=50)])
    enable(app);a,ah=session(app,'otheradmin')
    r=c.post('/api/trade/orders/'+str(draft['id'])+'/actions/submit',headers=h,json=dict(version=draft['version'],requestKey='approval-po-submit'))
    assert r.status_code==200,r.json
    rows=a.get('/api/approvals').json['items'];row=next(x for x in rows if x['id']==r.json['approvalRequested'])
    assert Decimal(row['amount'])==100
    decide(a,ah,row)
    assert details(c,'orders',draft['id'])['status']=='Approved'


def test_payroll_and_manufacturing_route_on_creation(app):
    from backend.test_hr_api import employee, payroll
    from backend.test_production_api import setup, order
    c,h=session(app);e=employee(c,h);raw,second,output,bom=setup(c,h)
    enable(app);a,ah=session(app,'otheradmin')
    pay=payroll(c,h,e)
    rows=a.get('/api/approvals').json['items'];row=next(x for x in rows if x['module']=='hr_payroll')
    assert Decimal(row['amount'])==10400
    decide(a,ah,row)
    mo=order(c,h,bom)
    rows=a.get('/api/approvals').json['items'];row=next(x for x in rows if x['module']=='manufacturing')
    # No materials stocked, so original completion/confirmation checks still apply.
    assert row['creatorId']=='admin' and row['canDecide']
    decide(c,h,row,expected=403)


def test_concurrent_decisions_create_only_one_posting(app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    enable(app);c,h=session(app);row=transfer(c,h,key='concurrent-approval')
    f,fh=session(app,'finance');a,ah=session(app,'otheradmin');barrier=Barrier(2)
    def run(client,headers):
        barrier.wait(timeout=10)
        return client.post('/api/approvals/'+str(row['id'])+'/approve',headers=headers,json=dict(reason='Concurrent independent review')).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda pair:run(*pair),[(f,fh),(a,ah)]))
    assert sorted(results)==[200,409]
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(JournalEntry))==1


def test_manual_journal_posting_uses_full_debit_value(app):
    c,h=session(app)
    r=c.post('/api/finance/commands/journal',headers=h,json=dict(requestKey='approval-journal-create',memo='Manual accrual',date='2026-11-06',lines=[dict(account='6105',debit='250',credit=0),dict(account='2100',debit=0,credit='250')]))
    assert r.status_code==200,r.json
    entry=r.json['record'];enable(app);f,fh=session(app,'finance')
    r=c.post('/api/finance/commands/post',headers=h,json=dict(id=entry['id'],version=entry['version'],requestKey='approval-journal-post'))
    assert r.status_code==409,r.json
    row=r.json['approval'];assert Decimal(row['amount'])==250
    decide(f,fh,row)
    with app.app_context():assert db.session.get(JournalEntry,entry['id']).status=='Posted'


def test_credit_and_refund_require_independent_authority(app):
    from backend.test_credit_api import setup_sale, returned, draft, step
    c,h,p,po,bill,so,delivery,inv=setup_sale(app,pay=330)
    move=returned(c,h,f"deliveries:{delivery['id']}:0",1)
    note=step(c,h,draft(c,h,'customer',inv,move,1),'submit')
    enable(app);a,ah=session(app,'otheradmin')
    r=c.post('/api/credits/commands/post',headers=h,json=dict(id=note['id'],version=note['version'],requestKey='approval-credit-post'))
    assert r.status_code==409,r.json
    row=r.json['approval'];assert Decimal(row['amount'])>0
    posted=decide(a,ah,row).json['result']['record']
    assert posted['status']=='Posted'
    r=c.post('/api/credits/commands/refund',headers=h,json=dict(id=posted['id'],version=posted['version'],requestKey='approval-credit-refund',amount=33,date=move['date'],account='1010'))
    assert r.status_code==409,r.json
    decide(c,h,r.json['approval'],expected=403)
    decide(a,ah,r.json['approval'])


def test_manufacturing_actual_cost_cannot_bypass_limit(app):
    from backend.test_production_api import setup, order
    from backend.test_inventory_api import adjust
    c,h=session(app);raw,second,output,bom=setup(c,h)
    adjust(c,h,raw,10,10);adjust(c,h,second,10,3)
    enable(app);a,ah=session(app,'otheradmin')
    mo=order(c,h,bom)
    row=next(x for x in a.get('/api/approvals').json['items'] if x['module']=='manufacturing')
    confirmed=decide(a,ah,row).json['result']['record']
    assert confirmed['state']=='Confirmed'
    r=c.post('/api/production/commands/complete',headers=h,json=dict(id=confirmed['id'],version=confirmed['version'],requestKey='approval-production-complete',conversionCost=20000000))
    assert r.status_code==409,r.json
    assert Decimal(r.json['approval']['amount'])>=20000000
    assert r.json['approval']['blocked']
    decide(a,ah,r.json['approval'],expected=403)


def test_stock_approval_uses_posting_quantity_precision(app):
    from backend.test_inventory_api import make_product, product
    c,h=session(app);p=make_product(c,h);enable(app)
    r=c.post('/api/inventory/commands/adjust',headers=h,json=dict(productId=p,version=product(c,p)['version'],quantity='0.10005',unitCost='1000000',reason='Precision boundary',requestKey='approval-stock-rounding'))
    assert r.status_code==409,r.json
    assert Decimal(r.json['approval']['amount'])==Decimal('100100.00')
