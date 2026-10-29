"""Cross-module demo scenarios on an isolated database, with independently calculated totals."""
from decimal import Decimal

from backend.test_app import app, session, patch
from backend.test_erp import (
    post, assert_balanced,
    test_purchase_receipt_bill_payment_and_sales_delivery_invoice_receipt as simulate_trade,
)


def test_complete_demo_business_day(app):
    # Starts with the actual seeded company; purchases panels, pays vendor,
    # delivers/invoices a customer, and collects the first PKR 600.
    simulate_trade(app)
    client, headers = session(app)
    state = client.get('/api/state').json['state']
    invoice = state['customerInvoices'][0]
    invoice.update(paidAmount=1500, balance=0, status='Paid')
    payment = dict(id=20, paymentNo='REC-DEMO-FINAL', invoiceId=18, orderId=16,
                   customerId=9006, amount=900, method='Cash',
                   paymentDate='2026-02-05', status='Received')
    result = patch(client, headers, dict(customerInvoices=[invoice],
                   customerPayments=state['customerPayments'] + [payment]))
    assert result.status_code == 200, result.json

    bom = client.get('/api/erp/boms').json['boms'][0]
    mo = post(client, headers, '/manufacturing', dict(requestKey='day-kits', bomId=bom['id'], quantity=2))
    for action in ('confirm', 'start', 'complete'):
        post(client, headers, f'/manufacturing/{mo["id"]}/{action}')

    claim = post(client, headers, '/expenses', dict(requestKey='day-travel', employee='Demo employee',
                 description='Client demonstration travel', account='6110', amount=1250, tax=0))
    for action in ('submit', 'approve', 'pay'):
        post(client, headers, f'/expenses/{claim["id"]}/{action}', dict(account='1010'))

    payroll = dict(id='day-payroll', employee='EMP-DEMO - Demo Employee', month='2026-10',
                   basic=50000, allowances=5000, deductions=2000, netPay=53000, status='Draft')
    for status in ('Draft', 'Approved', 'Paid'):
        payroll['status'] = status
        response = patch(client, headers, dict(payroll=[payroll]), '/api/hr/state')
        assert response.status_code == 200, response.json

    transfer = post(client, headers, '/transfers', dict(requestKey='day-cash-transfer',
                    fromAccount='1010', toAccount='1000', amount=5000, date='2026-10-26'))
    bank_line = next(line for line in transfer['lines'] if line['account']=='1010')
    statement = post(client, headers, '/bank-statements', dict(requestKey='day-statement',
                     account='1010', amount=-5000, date='2026-10-26', description='Demo cash withdrawal'))
    post(client, headers, f'/bank-statements/{statement["id"]}/match', dict(lineId=bank_line['id']))

    stock = {row['id']: row for row in client.get('/api/erp/inventory').json['products']}
    assert Decimal(stock['9001']['quantity']) == 97
    assert Decimal(stock['9002']['quantity']) == 192
    assert Decimal(stock['9003']['quantity']) == 2
    assert sum(Decimal(row['value']) for row in stock.values()) == 60700
    report = client.get('/api/erp/reports').json
    balances = {a['code']: Decimal(a['balance']) for a in report['accounts']}
    assert balances['1000'] == 31500
    assert balances['1010'] == 189750
    assert balances['1250'] == 0
    assert Decimal(report['cashBank']) == 221250
    assert Decimal(report['receivables']) == 0
    assert Decimal(report['payables']) == 0
    assert Decimal(report['profit']) == -55250
    assert Decimal(report['balanceCheck']) == 0
    assert_balanced(app)
    # A fresh authenticated session sees the same persisted results.
    second, _ = session(app)
    assert second.get('/api/erp/reports').json == report


def test_customer_and_vendor_stock_returns(app):
    simulate_trade(app)
    client, headers = session(app)
    moves = client.get('/api/erp/inventory').json['moves']
    delivery = next(m for m in moves if m['kind']=='Sales Delivery')
    receipt = next(m for m in moves if m['kind']=='Purchase Receipt')
    returned = post(client, headers, '/inventory/return', dict(requestKey='customer-return',
                    moveId=delivery['id'], quantity=1))
    assert Decimal(returned['quantity']) == 1
    repeated = post(client, headers, '/inventory/return', dict(requestKey='customer-return',
                    moveId=delivery['id'], quantity=1))
    assert returned['id'] == repeated['id']
    post(client, headers, '/inventory/return', dict(requestKey='excess-customer-return',
         moveId=delivery['id'], quantity=1), expected=400)
    post(client, headers, '/inventory/return', dict(requestKey='vendor-return',
         moveId=receipt['id'], quantity=2))
    post(client, headers, '/inventory/return', dict(requestKey='excess-vendor-return',
         moveId=receipt['id'], quantity=1), expected=400)
    panel = next(p for p in client.get('/api/erp/inventory').json['products'] if p['id']=='9001')
    assert Decimal(panel['quantity']) == 100
    assert Decimal(panel['value']) == 50000
    # Stock returns are distinct from commercial credit notes: the invoice stays open.
    assert Decimal(client.get('/api/erp/reports').json['receivables']) == 900
    assert_balanced(app)
