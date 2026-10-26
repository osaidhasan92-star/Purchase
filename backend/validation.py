"""Cross-record checks that cannot be trusted to browser forms."""
from collections import defaultdict
from decimal import Decimal


class InvalidBusinessState(ValueError):
    pass


def number(value):
    return Decimal(str(value or 0))


def validate_business(state):
    # Document identifiers are unique per register (vendor invoice numbers per vendor).
    identifiers = {'requests': 'requestNo', 'rfqs': 'rfqNo', 'quotations': 'quotationNo',
                   'orders': 'poNo', 'receipts': 'grnNo', 'invoices': 'invoiceNo',
                   'payments': 'paymentNo', 'salesQuotations': 'quotationNo',
                   'salesOrders': 'orderNo', 'deliveries': 'deliveryNo',
                   'customerInvoices': 'invoiceNo', 'customerPayments': 'paymentNo'}
    for key, field in identifiers.items():
        seen = set()
        for row in state.get(key, []):
            value = str(row.get(field, '')).strip().lower()
            if not value:
                raise InvalidBusinessState(f'{field} is required')
            identity = (str(row.get('vendorId')), value) if key == 'invoices' else value
            if identity in seen:
                raise InvalidBusinessState(f'Duplicate {field}')
            seen.add(identity)

    orders = {str(o['id']): o for o in state.get('salesOrders', [])}
    dispatched = defaultdict(Decimal)
    for delivery in state.get('deliveries', []):
        if delivery.get('status') == 'Cancelled':
            continue
        order = orders.get(str(delivery.get('orderId')))
        if not order or order.get('status') == 'Cancelled':
            raise InvalidBusinessState('Delivery must reference an active sales order')
        ordered = defaultdict(Decimal)
        for line in order.get('items', []):
            ordered[str(line.get('productId'))] += number(line.get('quantity'))
        for line in delivery.get('items', []):
            product = str(line.get('productId'))
            dispatched[(str(order['id']), product)] += number(line.get('deliveredQty'))
            if dispatched[(str(order['id']), product)] > ordered[product]:
                raise InvalidBusinessState('Deliveries exceed ordered quantity')

    # A receipt or payment cannot refer to an unrelated/missing invoice.
    for invoices_key, payments_key, active_status in [('invoices', 'payments', 'Processed'),
                                                       ('customerInvoices', 'customerPayments', 'Received')]:
        invoices = {str(row['id']): row for row in state.get(invoices_key, [])}
        paid = defaultdict(Decimal)
        for payment in state.get(payments_key, []):
            invoice = invoices.get(str(payment.get('invoiceId')))
            if not invoice:
                raise InvalidBusinessState('Payment must reference an existing invoice')
            if payment.get('status') != active_status:
                continue
            amount = number(payment.get('amount'))
            if amount <= 0:
                raise InvalidBusinessState('Payment must be greater than zero')
            paid[str(invoice['id'])] += amount
            if paid[str(invoice['id'])] > number(invoice.get('amount')) + Decimal('0.01'):
                raise InvalidBusinessState('Payments exceed invoice amount')
        for invoice_id, invoice in invoices.items():
            actual = paid[invoice_id]
            if 'paidAmount' in invoice and abs(number(invoice['paidAmount']) - actual) > Decimal('0.01'):
                raise InvalidBusinessState('Invoice paid amount must equal recorded payments')
            if 'balance' in invoice and abs(number(invoice['balance']) - max(Decimal(0), number(invoice.get('amount')) - actual)) > Decimal('0.01'):
                raise InvalidBusinessState('Invoice balance must equal amount less recorded payments')
            if invoice.get('status') == 'Paid' and actual + Decimal('0.01') < number(invoice.get('amount')):
                raise InvalidBusinessState('An unpaid invoice cannot be marked Paid')

    # Enforce receipt conservation and accepted quantity bounds for each PO line.
    purchase_orders = {str(row['id']): row for row in state.get('orders', [])}
    accepted = defaultdict(Decimal)
    for receipt in state.get('receipts', []):
        order = purchase_orders.get(str(receipt.get('poId')))
        if not order:
            raise InvalidBusinessState('Receipt must reference an existing purchase order')
        for index, line in enumerate(receipt.get('items', [])):
            if number(line.get('acceptedQty')) + number(line.get('rejectedQty')) != number(line.get('receivedQty')):
                raise InvalidBusinessState('Accepted plus rejected quantity must equal received quantity')
            if index >= len(order.get('items', [])):
                raise InvalidBusinessState('Receipt contains an unknown purchase order line')
            accepted[(str(order['id']), index)] += number(line.get('acceptedQty'))
            if accepted[(str(order['id']), index)] > number(order['items'][index].get('quantity')):
                raise InvalidBusinessState('Accepted receipts exceed ordered quantity')
