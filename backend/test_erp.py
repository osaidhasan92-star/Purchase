from decimal import Decimal
from copy import deepcopy

from sqlalchemy import select, func

from backend.test_app import app, session, patch
from backend.app import db, Document
from backend.erp import JournalEntry, JournalLine, StockBalance, StockMove, Reconciliation


def post(client, headers, path, data=None, expected=200):
    response=client.post('/api/erp'+path,headers=headers,json=data or {})
    assert response.status_code==expected, response.json
    return response.json


def seed(client,headers):
    return post(client,headers,'/seed-demo')


def assert_balanced(app):
    with app.app_context():
        for entry in db.session.scalars(select(JournalEntry)):
            assert sum(l.debit for l in entry.lines)==sum(l.credit for l in entry.lines),entry.number
        stock=db.session.scalar(select(func.coalesce(func.sum(StockBalance.value),0)))
        ledger=db.session.scalar(select(func.coalesce(func.sum(JournalLine.debit-JournalLine.credit),0)).join(JournalEntry).where(JournalEntry.status=='Posted',JournalLine.account=='1200'))
        assert stock==ledger


def test_pakistan_demo_and_average_cost_manufacturing(app):
    client,h=session(app);seed(client,h)
    company=client.get('/api/state').json['state']['company']
    assert company['country']=='Pakistan' and company['currency']=='PKR'
    assert client.get('/settings.html').status_code==410
    bom=client.get('/api/erp/boms').json['boms'][0]
    mo=post(client,h,'/manufacturing',dict(requestKey='make-demo-kit-1',bomId=bom['id'],quantity=2))
    post(client,h,f'/manufacturing/{mo["id"]}/confirm')
    post(client,h,f'/manufacturing/{mo["id"]}/start')
    result=post(client,h,f'/manufacturing/{mo["id"]}/complete')
    assert result['state']=='Done' and Decimal(result['actualCost'])==2600
    stock={p['id']:p for p in client.get('/api/erp/inventory').json['products']}
    assert Decimal(stock['9001']['quantity'])==96
    assert Decimal(stock['9002']['quantity'])==192
    assert Decimal(stock['9003']['quantity'])==2
    assert Decimal(stock['9003']['value'])==2600
    count=len(client.get('/api/erp/entries').json['entries'])
    post(client,h,f'/manufacturing/{mo["id"]}/complete')
    assert len(client.get('/api/erp/entries').json['entries'])==count
    report=client.get('/api/erp/reports').json
    assert Decimal(next(a for a in report['accounts'] if a['code']=='1250')['balance'])==0
    assert Decimal(report['balanceCheck'])==0
    assert_balanced(app)


def test_insufficient_components_roll_back_everything(app):
    client,h=session(app);seed(client,h)
    bom=client.get('/api/erp/boms').json['boms'][0]
    mo=post(client,h,'/manufacturing',dict(requestKey='too-many-kits',bomId=bom['id'],quantity=10000))
    post(client,h,f'/manufacturing/{mo["id"]}/confirm')
    before=client.get('/api/erp/inventory').json
    post(client,h,f'/manufacturing/{mo["id"]}/complete',expected=400)
    assert client.get('/api/erp/inventory').json==before
    assert client.get('/api/erp/manufacturing').json['orders'][0]['state']=='Confirmed'
    assert_balanced(app)


def test_expense_workflow_reimbursement_and_privacy(app):
    client,h=session(app);seed(client,h)
    viewer,vh=session(app,'viewer')
    assert viewer.post('/api/erp/expenses',headers=vh,json={}).status_code==403
    employee,eh=session(app,'seller')
    expense=post(employee,eh,'/expenses',dict(requestKey='employee-travel-1',employee='Sales employee',description='Client visit travel',account='6110',amount=1000,tax=0))
    post(employee,eh,f'/expenses/{expense["id"]}/submit')
    post(employee,eh,f'/expenses/{expense["id"]}/approve',expected=403)
    post(client,h,f'/expenses/{expense["id"]}/approve')
    result=post(client,h,f'/expenses/{expense["id"]}/pay',dict(account='1010'))
    assert result['status']=='Paid'
    count=len(client.get('/api/erp/entries').json['entries'])
    post(client,h,f'/expenses/{expense["id"]}/pay',dict(account='1010'))
    assert len(client.get('/api/erp/entries').json['entries'])==count
    assert viewer.get('/api/erp/entries').status_code==403
    assert_balanced(app)


def test_manual_journal_period_lock_transfer_and_bank_match(app):
    client,h=session(app);seed(client,h)
    post(client,h,'/entries',dict(requestKey='unbalanced-manual',memo='Invalid',lines=[dict(account='1000',debit=100),dict(account='3000',credit=99)]),expected=400)
    entry=post(client,h,'/entries',dict(requestKey='manual-opening-1',memo='Manual journal',date='2026-01-02',lines=[dict(account='1000',debit=100),dict(account='3000',credit=100)]))
    assert entry['status']=='Draft'
    post(client,h,f'/entries/{entry["id"]}/post')
    post(client,h,f'/entries/{entry["id"]}/reverse',dict(date='2026-01-03'))
    transfer=post(client,h,'/transfers',dict(requestKey='transfer-to-cash',fromAccount='1010',toAccount='1000',amount=500,date='2026-01-04'))
    bankline=next(l for l in transfer['lines'] if l['account']=='1010')
    statement=post(client,h,'/bank-statements',dict(requestKey='bank-statement-1',account='1010',amount=-500,date='2026-01-04',description='Cash withdrawal'))
    post(client,h,f'/bank-statements/{statement["id"]}/match',dict(lineId=bankline['id']))
    result=client.get('/api/erp/bank-statements').json
    assert result['statements'][0]['matchedLine']==bankline['id']
    post(client,h,'/period-lock',dict(date='2026-01-31'))
    post(client,h,'/transfers',dict(requestKey='locked-transfer-1',fromAccount='1010',toAccount='1000',amount=20,date='2026-01-20'),expected=400)
    assert_balanced(app)


def test_purchase_receipt_bill_payment_and_sales_delivery_invoice_receipt(app):
    client,h=session(app);seed(client,h)
    state=client.get('/api/state').json['state']
    # Approved purchase -> receipt: goods and accrued liability post together.
    po=dict(id=11,poNo='PO-TEST-11',status='Sent to Vendor',vendorId=9005,vendorName='Pakistan Supplies',total=1000,
            items=[dict(productId=9001,productName='General Panel',quantity=2,rate=500,taxPercent=0,discountPercent=0)])
    receipt=dict(id=12,grnNo='GRN-TEST-12',poId=11,status='Received',receivedDate='2026-02-01',
                 items=[dict(productId=9001,receivedQty=2,acceptedQty=2,rejectedQty=0)])
    r=patch(client,h,dict(orders=[po],receipts=[receipt]));assert r.status_code==200,r.json
    bill=dict(id=13,invoiceNo='BILL-TEST-13',poId=11,vendorId=9005,amount=1000,subtotal=1000,taxAmount=0,
              invoiceDate='2026-02-01',dueDate='2026-03-01',status='Approved')
    r=patch(client,h,dict(invoices=[bill]));assert r.status_code==200,r.json
    bill.update(status='Paid',paidAmount=1000,balance=0)
    payment=dict(id=14,paymentNo='PAY-TEST-14',invoiceId=13,vendorId=9005,amount=1000,method='Bank Transfer',paymentDate='2026-02-02',status='Processed')
    r=patch(client,h,dict(invoices=[bill],payments=[payment]));assert r.status_code==200,r.json
    # Customer order with a stock product: delivery creates COGS at average cost.
    quote=dict(id=15,quotationNo='SQ-TEST-15',customerId=9006,status='Pending Approval',total=1500)
    r=patch(client,h,dict(salesQuotations=[quote]));assert r.status_code==200,r.json
    for stage in ('Approved','Sent','Accepted'):
        quote['status']=stage;r=patch(client,h,dict(salesQuotations=[quote]));assert r.status_code==200,r.json
    order=dict(id=16,orderNo='SO-TEST-16',quotationId=15,customerId=9006,status='Confirmed',total=1500,
               items=[dict(productId=9001,productName='General Panel',quantity=1,rate=1500,total=1500,taxPercent=0,taxAmount=0)])
    delivery=dict(id=17,deliveryNo='DO-TEST-17',orderId=16,customerId=9006,status='Pending',deliveryDate='2026-02-03',items=[dict(productId=9001,deliveredQty=1)])
    r=patch(client,h,dict(salesOrders=[order],deliveries=[delivery]));assert r.status_code==200,r.json
    with app.app_context():assert db.session.scalar(select(StockMove).where(StockMove.source=='deliveries:17:0')) is None
    delivery['status']='Delivered';r=patch(client,h,dict(deliveries=[delivery]));assert r.status_code==200,r.json
    invoice=dict(id=18,invoiceNo='INV-TEST-18',orderId=16,customerId=9006,amount=1500,paidAmount=0,balance=1500,status='Posted',invoiceDate='2026-02-03',dueDate='2026-03-03',items=order['items'])
    r=patch(client,h,dict(customerInvoices=[invoice]));assert r.status_code==200,r.json
    invoice.update(paidAmount=600,balance=900,status='Partially Paid')
    cash=dict(id=19,paymentNo='REC-TEST-19',invoiceId=18,orderId=16,customerId=9006,amount=600,method='Cash',paymentDate='2026-02-04',status='Received')
    r=patch(client,h,dict(customerInvoices=[invoice],customerPayments=[cash]));assert r.status_code==200,r.json
    report=client.get('/api/erp/reports').json
    assert Decimal(report['receivables'])==900 and Decimal(report['payables'])==0
    assert Decimal(report['profit'])==1000
    with app.app_context():assert db.session.query(Reconciliation).count()==2
    # Economic fields of posted source documents cannot be silently rewritten.
    changed=deepcopy(invoice);changed.update(amount=1600,balance=1000)
    assert patch(client,h,dict(customerInvoices=[changed])).status_code==400
    assert_balanced(app)


def test_payroll_approval_and_payment_auto_post_and_cannot_delete(app):
    client,h=session(app)
    payroll=dict(id='salary-test-1',employee='EMP-1 - Demo Employee',month='2026-10',basic=50000,allowances=5000,deductions=2000,netPay=53000,status='Draft')
    r=patch(client,h,dict(payroll=[payroll]),'/api/hr/state');assert r.status_code==200,r.json
    payroll['status']='Approved';r=patch(client,h,dict(payroll=[payroll]),'/api/hr/state');assert r.status_code==200,r.json
    entries=client.get('/api/erp/entries').json['entries']
    entry=next(e for e in entries if e['source']=='payroll:salary-test-1')
    assert sum(Decimal(l['debit']) for l in entry['lines'])==55000
    payroll['status']='Paid';r=patch(client,h,dict(payroll=[payroll]),'/api/hr/state');assert r.status_code==200,r.json
    assert any(e['source']=='payroll:salary-test-1:payment' for e in client.get('/api/erp/entries').json['entries'])
    assert patch(client,h,dict(payroll=[]),'/api/hr/state').status_code==400
    assert_balanced(app)


def test_stock_returns_and_negative_stock_rejected(app):
    client,h=session(app);seed(client,h)
    post(client,h,'/inventory/adjust',dict(requestKey='impossible-stock',productId='9001',quantity=-1000,reason='Scrap'),expected=400)
    result=post(client,h,'/inventory/adjust',dict(requestKey='add-one-panel',productId='9001',quantity=1,unitCost=500,reason='Count adjustment'))
    repeated=post(client,h,'/inventory/adjust',dict(requestKey='add-one-panel',productId='9001',quantity=1,unitCost=500,reason='Count adjustment'))
    assert result['id']==repeated['id']
    assert_balanced(app)


def test_hr_separation_revokes_linked_login(app):
    admin,h=session(app);viewer,_=session(app,'viewer')
    employee=dict(id='emp-linked',employeeId='EMP-L',name='Viewer employee',salary=100,linkedUserId='viewer',status='Active')
    separation=dict(id='sep-linked',employee='EMP-L - Viewer employee',status='Requested',lastWorkingDate='2026-10-26')
    assert patch(admin,h,dict(employees=[employee],separations=[separation]),'/api/hr/state').status_code==200
    separation['status']='Approved'
    assert patch(admin,h,dict(separations=[separation]),'/api/hr/state').status_code==200
    separation['status']='Completed';employee['status']='Separated'
    assert patch(admin,h,dict(employees=[employee],separations=[separation]),'/api/hr/state').status_code==200
    assert viewer.get('/api/auth/me').status_code==401


def test_partial_vendor_billing_cannot_exceed_received_value(app):
    client,h=session(app);seed(client,h)
    po=dict(id=101,poNo='PO-PARTIAL',vendorId=9005,total=100,status='Partially Received',
            items=[dict(productId=9001,quantity=10,rate=10,taxPercent=0,discountPercent=0)])
    receipt=dict(id=102,grnNo='GRN-PARTIAL',poId=101,status='Partially Received',items=[dict(productId=9001,receivedQty=5,acceptedQty=5,rejectedQty=0)])
    assert patch(client,h,dict(orders=[po],receipts=[receipt])).status_code==200
    bill=dict(id=103,invoiceNo='PARTIAL-1',vendorId=9005,poId=101,amount=50,taxAmount=0,status='Matched')
    assert patch(client,h,dict(invoices=[bill])).status_code==200
    extra=dict(bill,id=104,invoiceNo='PARTIAL-2',amount=1)
    assert patch(client,h,dict(invoices=[bill,extra])).status_code==400
    bill['status']='Approved'
    assert patch(client,h,dict(invoices=[bill])).status_code==200
    assert_balanced(app)
