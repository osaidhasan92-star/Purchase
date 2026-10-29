import pytest

from backend.validation import InvalidBusinessState, validate_business


def test_overpayment_and_fabricated_paid_status_are_rejected():
    invoice = {'id': 1, 'invoiceNo': 'INV-1', 'amount': 100, 'paidAmount': 0, 'balance': 100, 'status': 'Posted'}
    validate_business({'customerInvoices': [invoice]})
    with pytest.raises(InvalidBusinessState, match='Payments exceed'):
        validate_business({'customerInvoices': [invoice], 'customerPayments': [
            {'id': 1, 'paymentNo': 'REC-1', 'invoiceId': 1, 'status': 'Received', 'amount': 101}]})
    with pytest.raises(InvalidBusinessState, match='paid amount'):
        validate_business({'customerInvoices': [{**invoice, 'paidAmount': 100, 'balance': 0, 'status': 'Paid'}]})


def test_pending_and_completed_deliveries_cannot_exceed_order():
    order = {'id': 1, 'orderNo': 'SO-1', 'status': 'Confirmed', 'items': [{'productId': 1, 'quantity': 10}]}
    delivery = {'id': 1, 'deliveryNo': 'DO-1', 'orderId': 1, 'status': 'Pending', 'items': [{'productId': 1, 'deliveredQty': 8}]}
    validate_business({'salesOrders': [order], 'deliveries': [delivery]})
    with pytest.raises(InvalidBusinessState, match='exceed ordered'):
        validate_business({'salesOrders': [order], 'deliveries': [delivery,
            {**delivery, 'id': 2, 'deliveryNo': 'DO-2', 'status': 'Delivered'}]})


def test_receipt_conservation_and_cumulative_quantity():
    order = {'id': 1, 'poNo': 'PO-1', 'items': [{'productId': 1, 'quantity': 10}]}
    receipt = {'id': 1, 'grnNo': 'GRN-1', 'poId': 1, 'items': [{'receivedQty': 7, 'acceptedQty': 7, 'rejectedQty': 0}]}
    validate_business({'orders': [order], 'receipts': [receipt]})
    with pytest.raises(InvalidBusinessState, match='exceed ordered'):
        validate_business({'orders': [order], 'receipts': [receipt, {**receipt, 'id': 2, 'grnNo': 'GRN-2'}]})
    with pytest.raises(InvalidBusinessState, match='must equal'):
        validate_business({'orders': [order], 'receipts': [{**receipt, 'items': [{'receivedQty': 7, 'acceptedQty': 6, 'rejectedQty': 0}]}]})


def test_vendor_invoice_number_is_unique_within_vendor():
    validate_business({'invoices': [{'id': 1, 'vendorId': 1, 'invoiceNo': '100', 'amount': 10},
                                    {'id': 2, 'vendorId': 2, 'invoiceNo': '100', 'amount': 10}]})
    with pytest.raises(InvalidBusinessState, match='Duplicate'):
        validate_business({'invoices': [{'id': 1, 'vendorId': 1, 'invoiceNo': '100', 'amount': 10},
                                        {'id': 2, 'vendorId': 1, 'invoiceNo': '100', 'amount': 10}]})
