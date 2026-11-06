"""Product-policy snapshots, eligible quantities and financial posting boundaries."""
from sqlalchemy import select
from backend.test_app import app, session
from backend.test_trade_api import masters, purchase, create, action, details, post
from backend.test_credit_api import returned
from backend.app import db
from backend.erp import JournalEntry


def goods(c,h,**policies):
    response=c.post('/api/products',headers=h,json=dict(name='Policy goods',sku='POLICY-GOODS',rate=10,requestKey='policy-product-create',**policies))
    assert response.status_code==200,response.json
    return response.json['record']


def sale(c,h,product,customer,quantity=10):
    quote=create(c,h,'salesQuotations',customerId=customer['id'],items=[dict(productId=product['id'],quantity=quantity,rate=10)])
    for step in ('submit','approve','send','accept'):quote=action(c,h,'salesQuotations',quote,step)
    return create(c,h,'salesOrders',quotationId=quote['id'],parentVersion=quote['version'])


def invoice_payload(order,qty,customer=True):
    return dict(**{'orderId' if customer else 'poId':order['id']},parentVersion=order['version'],dueDate='2027-12-31',items=[dict(lineIndex=0,quantity=qty)],**({} if customer else {'invoiceNo':'POLICY-BILL'}))


def test_goods_default_sales_delivered_policy_caps_drafts_and_rechecks_post(app):
    c,h=session(app);_,v,customer=masters(c,h);p=goods(c,h)
    assert p['salesInvoicePolicy']=='delivered' and p['purchaseBillPolicy']=='received'
    stock=c.get('/api/inventory/products/'+str(p['id'])).json['record']
    assert c.post('/api/inventory/commands/adjust',headers=h,json=dict(productId=p['id'],version=stock['version'],quantity=10,unitCost=10,reason='Policy test stock',requestKey='policy-test-opening')).status_code==200
    order=sale(c,h,p,customer)
    assert order['items'][0]['salesInvoicePolicy']=='delivered'
    post(c,h,'customerInvoices',dict(**invoice_payload(order,1),requestKey='undelivered-invoice'),400)
    line=c.get('/api/trade/salesOrders/'+str(order['id'])).json['context']['lines'][0]
    assert line['billingPolicy']=='delivered' and line['billableRemaining']==0
    delivery=create(c,h,'deliveries',orderId=order['id'],parentVersion=order['version'],items=[dict(lineIndex=0,deliveredQty=4)])
    delivery=action(c,h,'deliveries',delivery,'deliver');order=details(c,'salesOrders',order['id'])
    post(c,h,'customerInvoices',dict(**invoice_payload(order,5),requestKey='excess-delivered-invoice'),400)
    draft=create(c,h,'customerInvoices',**invoice_payload(order,4))
    order=details(c,'salesOrders',order['id'])
    post(c,h,'customerInvoices',dict(**invoice_payload(order,1),requestKey='duplicate-delivered-invoice'),400)
    draft=action(c,h,'customerInvoices',draft,'submit')
    returned(c,h,f'deliveries:{delivery["id"]}:0',1)
    post(c,h,f'customerInvoices/{draft["id"]}/actions/post',dict(version=draft['version'],requestKey='return-invalidates-post'),400)
    with app.app_context():assert db.session.scalar(select(JournalEntry.id).where(JournalEntry.source=='customerInvoices:'+str(draft['id']))) is None
    draft=action(c,h,'customerInvoices',draft,'reset')
    response=c.patch('/api/trade/customerInvoices/'+str(draft['id']),headers=h,json=dict(version=draft['version'],items=[dict(lineIndex=0,quantity=3)],requestKey='resize-policy-draft'))
    assert response.status_code==200,response.json
    draft=action(c,h,'customerInvoices',response.json['record'],'submit')
    assert action(c,h,'customerInvoices',draft,'post')['amount']==30


def test_ordered_sales_policy_allows_pre_delivery_and_product_edits_do_not_rewrite_orders(app):
    c,h=session(app);_,_,customer=masters(c,h);p=goods(c,h,salesInvoicePolicy='ordered')
    order=sale(c,h,p,customer)
    changed=c.patch('/api/products/'+str(p['id']),headers=h,json=dict(version=p['version'],salesInvoicePolicy='delivered'))
    assert changed.status_code==200,changed.json
    invoice=create(c,h,'customerInvoices',**invoice_payload(order,10))
    invoice=action(c,h,'customerInvoices',invoice,'submit');assert action(c,h,'customerInvoices',invoice,'post')['amount']==100
    new_order=sale(c,h,p,customer)
    assert new_order['items'][0]['salesInvoicePolicy']=='delivered'
    post(c,h,'customerInvoices',dict(**invoice_payload(new_order,1),requestKey='new-order-new-policy'),400)


def test_received_purchase_policy_and_ordered_override(app):
    c,h=session(app);_,vendor,_=masters(c,h);p=goods(c,h)
    order=purchase(c,h,p,vendor)
    post(c,h,'invoices',dict(**invoice_payload(order,1,False),requestKey='unreceived-bill-denied'),400)
    create(c,h,'receipts',poId=order['id'],parentVersion=order['version'],items=[dict(lineIndex=0,receivedQty=4,acceptedQty=4,rejectedQty=0)])
    order=details(c,'orders',order['id'])
    post(c,h,'invoices',dict(**invoice_payload(order,5,False),requestKey='over-received-bill'),400)
    bill=create(c,h,'invoices',**invoice_payload(order,4,False));bill=action(c,h,'invoices',bill,'submit');assert action(c,h,'invoices',bill,'post')['amount']==40
    changed=c.patch('/api/products/'+str(p['id']),headers=h,json=dict(version=p['version'],purchaseBillPolicy='ordered'))
    assert changed.status_code==200,changed.json
    order=purchase(c,h,p,vendor)
    payload=invoice_payload(order,20,False);payload['invoiceNo']='ORDERED-PRE-RECEIPT'
    bill=create(c,h,'invoices',**payload);bill=action(c,h,'invoices',bill,'submit');bill=action(c,h,'invoices',bill,'post')
    assert bill['amount']==200 and bill['status']=='Approved'
    payment=create(c,h,'payments',invoiceId=bill['id'],parentVersion=bill['version'],amount=200)
    assert payment['status']=='Processed'


def test_service_defaults_policy_validation_and_client_policy_forgery(app):
    c,h=session(app);_,_,customer=masters(c,h);p=goods(c,h,unit='Service')
    assert p['salesInvoicePolicy']==p['purchaseBillPolicy']=='ordered'
    bad=c.patch('/api/products/'+str(p['id']),headers=h,json=dict(version=p['version'],salesInvoicePolicy='anything'))
    assert bad.status_code==400
    order=sale(c,h,p,customer)
    payload=invoice_payload(order,1);payload['items'][0]['salesInvoicePolicy']='ordered'
    post(c,h,'customerInvoices',dict(**payload,requestKey='forged-line-policy'),400)
    invoice=create(c,h,'customerInvoices',**invoice_payload(order,1))
    assert invoice['status']=='Draft'


def test_mixed_purchase_policies_cannot_use_ordered_lines_to_overbill_received_lines(app):
    c,h=session(app);_,vendor,_=masters(c,h);received_product=goods(c,h)
    response=c.post('/api/products',headers=h,json=dict(name='Ordered-policy goods',sku='POLICY-ORDERED',rate=10,purchaseBillPolicy='ordered',requestKey='mixed-policy-product'))
    assert response.status_code==200,response.json
    ordered_product=response.json['record']
    order=create(c,h,'orders',vendorId=vendor['id'],deliveryDate='2027-12-31',items=[dict(productId=received_product['id'],quantity=10,rate=10),dict(productId=ordered_product['id'],quantity=10,rate=10)])
    for step in ('submit','approve','send'):order=action(c,h,'orders',order,step)
    create(c,h,'receipts',poId=order['id'],parentVersion=order['version'],items=[dict(lineIndex=0,receivedQty=4,acceptedQty=4,rejectedQty=0)])
    response=c.get('/api/trade/orders/'+str(order['id']));order=response.json['record']
    assert [(l['billingPolicy'],l['billableRemaining']) for l in response.json['context']['lines']]==[('received',4),('ordered',10)]
    payload=dict(poId=order['id'],parentVersion=order['version'],invoiceNo='MIXED-POLICY-BILL',dueDate='2027-12-31',items=[dict(lineIndex=0,quantity=5),dict(lineIndex=1,quantity=10)])
    post(c,h,'invoices',dict(**payload,requestKey='mixed-overbill-denied'),400)
    payload['items'][0]['quantity']=4
    bill=create(c,h,'invoices',**payload);bill=action(c,h,'invoices',bill,'submit');bill=action(c,h,'invoices',bill,'post')
    assert bill['amount']==140 and bill['matchStatus']=='Matched'


def test_draft_purchase_line_edits_keep_existing_policy_snapshot(app):
    c,h=session(app);_,vendor,_=masters(c,h);p=goods(c,h)
    order=create(c,h,'orders',vendorId=vendor['id'],deliveryDate='2027-12-31',items=[dict(productId=p['id'],quantity=10,rate=10)])
    changed=c.patch('/api/products/'+str(p['id']),headers=h,json=dict(version=p['version'],purchaseBillPolicy='ordered'))
    assert changed.status_code==200,changed.json
    edited=c.patch('/api/trade/orders/'+str(order['id']),headers=h,json=dict(version=order['version'],items=[dict(productId=p['id'],quantity=10,rate=12)],requestKey='draft-policy-stays'))
    assert edited.status_code==200,edited.json
    order=edited.json['record'];assert order['items'][0]['purchaseBillPolicy']=='received'
    for step in ('submit','approve'):order=action(c,h,'orders',order,step)
    post(c,h,'invoices',dict(**invoice_payload(order,1,False),requestKey='edited-order-no-receipt'),400)
