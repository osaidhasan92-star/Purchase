"""Relational accounting, perpetual inventory, production and expense services.

All service calls participate in the caller's database transaction. Monetary
values use Decimal, and a database row lock serializes stock/sequence changes.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from copy import deepcopy

from flask import g
from sqlalchemy import select, update, func

from .app import db, Document, User, LoginSession, audit
from .permissions import default_roles
from .scope import remember, source_creator
from .validation import InvalidBusinessState

CENT = Decimal('0.01')
UNIT = Decimal('0.0001')


class ERPControl(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    revision = db.Column(db.Integer, nullable=False, default=0)
    lock_date = db.Column(db.String(10))


class ERPCounter(db.Model):
    prefix = db.Column(db.String(20), primary_key=True)
    value = db.Column(db.Integer, nullable=False, default=0)


class Account(db.Model):
    code = db.Column(db.String(20), primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    reconcile = db.Column(db.Boolean, nullable=False, default=False)


class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True, nullable=False)
    source = db.Column(db.String(160), unique=True, nullable=False)
    memo = db.Column(db.String(500), nullable=False)
    date = db.Column(db.String(10), nullable=False, index=True)
    status = db.Column(db.String(12), nullable=False, default='Draft')
    created_by = db.Column(db.String(64), nullable=False)
    reversal_of = db.Column(db.Integer, db.ForeignKey('journal_entry.id'))
    lines = db.relationship('JournalLine', cascade='all, delete-orphan', backref='entry', lazy='selectin')


class JournalLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id'), nullable=False, index=True)
    account = db.Column(db.String(20), db.ForeignKey('account.code'), nullable=False, index=True)
    debit = db.Column(db.Numeric(20, 2), nullable=False, default=0)
    credit = db.Column(db.Numeric(20, 2), nullable=False, default=0)
    partner = db.Column(db.String(100), nullable=False, default='')
    due_date = db.Column(db.String(10))


class Reconciliation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    debit_line = db.Column(db.Integer, db.ForeignKey('journal_line.id'), nullable=False)
    credit_line = db.Column(db.Integer, db.ForeignKey('journal_line.id'), nullable=False)
    amount = db.Column(db.Numeric(20, 2), nullable=False)


class ERPProduct(db.Model):
    id = db.Column(db.String(64), primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    sku = db.Column(db.String(80), nullable=False, default='')
    kind = db.Column(db.String(12), nullable=False, default='stock')
    unit = db.Column(db.String(40), nullable=False, default='Each')


class StockBalance(db.Model):
    product_id = db.Column(db.String(64), db.ForeignKey('erp_product.id'), primary_key=True)
    quantity = db.Column(db.Numeric(20, 4), nullable=False, default=0)
    value = db.Column(db.Numeric(20, 2), nullable=False, default=0)


class StockMove(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True, nullable=False)
    source = db.Column(db.String(160), unique=True, nullable=False)
    product_id = db.Column(db.String(64), db.ForeignKey('erp_product.id'), nullable=False, index=True)
    quantity = db.Column(db.Numeric(20, 4), nullable=False)
    value = db.Column(db.Numeric(20, 2), nullable=False)
    kind = db.Column(db.String(40), nullable=False)
    date = db.Column(db.String(10), nullable=False)
    counterpart = db.Column(db.String(20), db.ForeignKey('account.code'), nullable=False)
    journal_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id'))
    return_of = db.Column(db.Integer, db.ForeignKey('stock_move.id'))


class BillOfMaterials(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    product_id = db.Column(db.String(64), db.ForeignKey('erp_product.id'), nullable=False)
    output_quantity = db.Column(db.Numeric(20, 4), nullable=False)
    conversion_cost = db.Column(db.Numeric(20, 2), nullable=False, default=0)
    request_key = db.Column(db.String(100), unique=True, nullable=False)
    lines = db.relationship('BOMLine', cascade='all, delete-orphan', lazy='selectin')


class BOMLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bom_id = db.Column(db.Integer, db.ForeignKey('bill_of_materials.id'), nullable=False)
    product_id = db.Column(db.String(64), db.ForeignKey('erp_product.id'), nullable=False)
    quantity = db.Column(db.Numeric(20, 4), nullable=False)


class ManufacturingOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True, nullable=False)
    bom_id = db.Column(db.Integer, db.ForeignKey('bill_of_materials.id'), nullable=False)
    product_id = db.Column(db.String(64), db.ForeignKey('erp_product.id'), nullable=False)
    quantity = db.Column(db.Numeric(20, 4), nullable=False)
    conversion_cost = db.Column(db.Numeric(20, 2), nullable=False, default=0)
    actual_cost = db.Column(db.Numeric(20, 2), nullable=False, default=0)
    state = db.Column(db.String(20), nullable=False, default='Draft')
    date = db.Column(db.String(10), nullable=False)
    request_key = db.Column(db.String(100), unique=True, nullable=False)
    lines = db.relationship('ProductionComponent', cascade='all, delete-orphan', lazy='selectin')


class ProductionComponent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('manufacturing_order.id'), nullable=False)
    product_id = db.Column(db.String(64), db.ForeignKey('erp_product.id'), nullable=False)
    quantity = db.Column(db.Numeric(20, 4), nullable=False)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True, nullable=False)
    employee = db.Column(db.String(160), nullable=False)
    owner_id = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(500), nullable=False)
    account = db.Column(db.String(20), db.ForeignKey('account.code'), nullable=False)
    amount = db.Column(db.Numeric(20, 2), nullable=False)
    tax = db.Column(db.Numeric(20, 2), nullable=False, default=0)
    date = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Draft')
    attachment_id = db.Column(db.String(64), db.ForeignKey('attachment.id'))
    request_key = db.Column(db.String(100), unique=True, nullable=False)


class BankStatementLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False)
    description = db.Column(db.String(300), nullable=False)
    account = db.Column(db.String(20), db.ForeignKey('account.code'), nullable=False)
    amount = db.Column(db.Numeric(20, 2), nullable=False)
    matched_line = db.Column(db.Integer, db.ForeignKey('journal_line.id'), unique=True)
    request_key = db.Column(db.String(100), unique=True, nullable=False)


CHART = [
    ('1000', 'Cash on Hand', 'asset', True), ('1010', 'Main Bank', 'asset', True),
    ('1100', 'Accounts Receivable', 'asset', True), ('1200', 'Inventory Valuation', 'asset', False),
    ('1250', 'Production Work in Progress', 'asset', False), ('1300', 'Input Sales Tax — Demo', 'asset', False),
    ('2100', 'Accounts Payable', 'liability', True), ('2105', 'Goods Received Not Invoiced', 'liability', True),
    ('2200', 'Output Sales Tax — Demo', 'liability', False), ('2300', 'Salaries Payable', 'liability', True),
    ('2310', 'Payroll Deductions Payable', 'liability', False), ('2350', 'Employee Reimbursements Payable', 'liability', True),
    ('2400', 'Manufacturing Costs Accrued', 'liability', True),
    ('3000', 'Opening Capital', 'equity', False), ('3100', 'Retained Earnings', 'equity', False),
    ('4100', 'Sales Revenue', 'income', False), ('5100', 'Cost of Goods Sold', 'expense', False),
    ('5105', 'Stock Adjustments and Scrap', 'expense', False), ('6100', 'Salaries and Allowances', 'expense', False),
    ('6105', 'General Operating Expenses', 'expense', False), ('6110', 'Travel and Transport', 'expense', False),
    ('6120', 'Utilities', 'expense', False),
]

COMPANY = dict(name='Pakistan Demo Company', legalName='Pakistan Demo Company', country='Pakistan',
               currency='PKR', currencySymbol='Rs', currencyLocale='en-PK', taxNumberLabel='NTN / STRN',
               purchaseTax={'enabled': True, 'label': 'Sales Tax', 'rate': 0},
               salesTax={'enabled': True, 'label': 'Sales Tax', 'rate': 0})


def dec(value, scale=CENT, positive=False):
    try:
        if isinstance(value, bool):
            raise ValueError()
        result = Decimal(str(value)).quantize(scale, rounding=ROUND_HALF_UP)
        if not result.is_finite() or abs(result) > Decimal('1000000000000') or (positive and result <= 0):
            raise ValueError()
        return result
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidBusinessState('Enter a finite valid amount or quantity')


def day(value=None):
    try:
        return date.fromisoformat(str(value or datetime.now(ZoneInfo('Asia/Karachi')).date().isoformat())).isoformat()
    except ValueError:
        raise InvalidBusinessState('Use a valid YYYY-MM-DD date')


def lock():
    result = db.session.execute(update(ERPControl).where(ERPControl.id == 1).values(revision=ERPControl.revision + 1))
    if result.rowcount != 1:
        raise InvalidBusinessState('Run init-db to initialize ERP tables')


def next_number(prefix):
    counter = db.session.get(ERPCounter, prefix)
    if not counter:
        counter = ERPCounter(prefix=prefix, value=0)
        db.session.add(counter)
    counter.value += 1
    db.session.flush()
    return f'{prefix}-{day()[:4]}-{counter.value:06d}'


def initialize():
    if not db.session.get(ERPControl, 1):
        db.session.add(ERPControl(id=1, revision=0))
    for code, name, kind, reconcile in CHART:
        if not db.session.get(Account, code):
            db.session.add(Account(code=code, name=name, kind=kind, reconcile=reconcile))
    doc = db.session.get(Document, 'app')
    if doc:
        data = deepcopy(doc.data)
        defaults = default_roles()
        for name, role in defaults.items():
            if name not in data['roles']:
                data['roles'][name] = role
            else:
                existing = data['roles'][name]
                for module, permissions in role['permissions'].items():
                    if module not in existing.get('permissions', {}):
                        existing.setdefault('permissions', {})[module] = permissions
                        existing[module] = permissions['view']
        data['company'] = {**COMPANY, **data.get('company', {}), 'country': 'Pakistan', 'currency': 'PKR',
                           'currencySymbol': 'Rs', 'currencyLocale': 'en-PK'}
        doc.data = data
        doc.revision += 1
        sync_products(data)


def check_period(value):
    control = db.session.get(ERPControl, 1)
    if control.lock_date and day(value) <= control.lock_date:
        raise InvalidBusinessState('The accounting period is locked through ' + control.lock_date)


def post_entry(source, memo, lines, value_date=None, draft=False):
    existing = db.session.scalar(select(JournalEntry).where(JournalEntry.source == source))
    if existing:
        return existing
    value_date = day(value_date)
    check_period(value_date)
    normalized = []
    for line in lines:
        code = str(line['account'])
        if not db.session.get(Account, code):
            raise InvalidBusinessState('Unknown account: ' + code)
        debit, credit = dec(line.get('debit', 0)), dec(line.get('credit', 0))
        if debit < 0 or credit < 0 or (debit and credit):
            raise InvalidBusinessState('Journal lines need a positive debit OR credit')
        if debit or credit:
            normalized.append(dict(account=code, debit=debit, credit=credit,
                                   partner=str(line.get('partner', ''))[:100],
                                   due_date=day(line['dueDate']) if line.get('dueDate') else None))
    if len(normalized) < 2 or sum(l['debit'] for l in normalized) != sum(l['credit'] for l in normalized):
        raise InvalidBusinessState('Journal entry debits and credits must balance exactly')
    entry = JournalEntry(number=next_number('JE'), source=source, memo=str(memo)[:500], date=value_date,
                         status='Draft' if draft else 'Posted', created_by=source_creator(source) if getattr(g,'user',None) else 'system')
    entry.lines = [JournalLine(**line) for line in normalized]
    db.session.add(entry)
    db.session.flush()
    if getattr(g,'user',None):remember(entry,entry.created_by)
    audit('Created journal entry', {'number': entry.number, 'source': source, 'status': entry.status})
    return entry


def journal_pair(source, memo, debit, credit, amount, value_date=None, partner=''):
    amount = dec(amount)
    if amount == 0:
        return None
    return post_entry(source, memo, [dict(account=debit, debit=amount, partner=partner),
                                    dict(account=credit, credit=amount, partner=partner)], value_date)


def sync_products(state):
    for item in state.get('products', []):
        pid = str(item['id'])
        product = db.session.get(ERPProduct, pid)
        kind = item.get('productType', 'service' if str(item.get('unit', '')).lower() == 'service' else 'stock')
        if kind not in ('stock', 'service'):
            raise InvalidBusinessState('Product type must be stock or service')
        if not product:
            product = ERPProduct(id=pid, name=str(item.get('name', 'Product')), kind=kind)
            db.session.add(product)
            db.session.flush()
            db.session.add(StockBalance(product_id=pid, quantity=0, value=0))
        elif product.kind != kind and db.session.scalar(select(StockMove.id).where(StockMove.product_id == pid).limit(1)):
            raise InvalidBusinessState('A product with stock history cannot change product type')
        product.name, product.sku, product.unit, product.kind = str(item.get('name', 'Product'))[:160], str(item.get('sku', ''))[:80], str(item.get('unit', 'Each'))[:40], kind
    db.session.flush()


def stock_move(product_id, quantity, source, kind, counterpart, unit_cost=None, value_date=None, total_value=None, return_of=None):
    existing = db.session.scalar(select(StockMove).where(StockMove.source == source))
    if existing:
        return existing
    product = db.session.get(ERPProduct, str(product_id))
    if not product or product.kind != 'stock':
        raise InvalidBusinessState('Select a stock-tracked product')
    check_period(day(value_date))
    quantity = dec(quantity, UNIT)
    if quantity == 0:
        raise InvalidBusinessState('Stock movement quantity cannot be zero')
    balance = db.session.get(StockBalance, product.id)
    available, current_value = dec(balance.quantity, UNIT), dec(balance.value)
    if quantity < 0:
        if available + quantity < 0:
            raise InvalidBusinessState(f'Insufficient stock for {product.name}: available {available}')
        cost = current_value if -quantity == available else dec((-quantity) * current_value / available)
        value = -cost
    else:
        value = dec(total_value) if total_value is not None else dec(quantity * dec(unit_cost or 0, UNIT))
        if value < 0:
            raise InvalidBusinessState('Stock value cannot be negative')
    entry = journal_pair('stock:' + source, f'{kind}: {product.name}',
                         '1200' if quantity > 0 else counterpart,
                         counterpart if quantity > 0 else '1200', abs(value), value_date)
    move = StockMove(number=next_number('STK'), source=source, product_id=product.id, quantity=quantity,
                     value=value, kind=kind, counterpart=counterpart, date=day(value_date),
                     journal_id=entry.id if entry else None, return_of=return_of)
    balance.quantity, balance.value = available + quantity, current_value + value
    db.session.add(move)
    db.session.flush()
    if getattr(g,'user',None):remember(move,source_creator(source))
    audit('Posted stock movement', {'number': move.number, 'productId': product.id, 'quantity': str(quantity)})
    return move


def matched_amount(line):
    return dec(db.session.scalar(select(func.coalesce(func.sum(Reconciliation.amount), 0)).where(
        (Reconciliation.debit_line == line.id) | (Reconciliation.credit_line == line.id))))


def reconcile(debit, credit, amount):
    amount = dec(amount, positive=True)
    if debit.entry.status != 'Posted' or credit.entry.status != 'Posted' or debit.account != credit.account or debit.partner != credit.partner:
        raise InvalidBusinessState('Match posted lines from the same account and partner')
    account = db.session.get(Account, debit.account)
    if not account.reconcile or debit.debit <= 0 or credit.credit <= 0:
        raise InvalidBusinessState('Choose a debit and credit on a reconcilable account')
    if amount > debit.debit - matched_amount(debit) or amount > credit.credit - matched_amount(credit):
        raise InvalidBusinessState('Matching amount exceeds remaining open amount')
    db.session.add(Reconciliation(debit_line=debit.id, credit_line=credit.id, amount=amount))
    db.session.flush()


def auto_reconcile(invoice_source, payment, account):
    invoice = db.session.scalar(select(JournalEntry).where(JournalEntry.source == invoice_source))
    if not invoice:
        return
    debit = next((l for e in (invoice, payment) for l in e.lines if l.account == account and l.debit), None)
    credit = next((l for e in (invoice, payment) for l in e.lines if l.account == account and l.credit), None)
    if debit and credit:
        amount = min(debit.debit - matched_amount(debit), credit.credit - matched_amount(credit))
        if amount > 0:
            reconcile(debit, credit, amount)


def finance_document(row, key, state):
    amount = dec(row.get('amount', 0), positive=True)
    source = f'{key}:{row["id"]}'
    if key in ('customerInvoices', 'invoices'):
        customer = key == 'customerInvoices'
        tax = dec(row.get('taxAmount', sum(Decimal(str(i.get('taxAmount', 0))) for i in row.get('items', []))))
        if tax < 0 or tax > amount:
            raise InvalidBusinessState('Tax amount must be within the invoice amount')
        net = amount - tax
        partner = ('customer:' if customer else 'vendor:') + str(row.get('customerId') if customer else row.get('vendorId'))
        if customer:
            lines = [dict(account='1100', debit=amount, partner=partner, dueDate=row.get('dueDate')),
                     dict(account='4100', credit=net), dict(account='2200', credit=tax)]
        else:
            po = next((p for p in state.get('orders', []) if str(p['id']) == str(row.get('poId'))), None)
            stock_net, service_net = Decimal(0), Decimal(0)
            native_lines = row.get('items') if row.get('items') and all('lineIndex' in i for i in row['items']) else None
            for item in native_lines or (po or {}).get('items', []):
                product = db.session.get(ERPProduct, str(item.get('productId')))
                base = Decimal(str(item.get('subtotal',0))) if native_lines else Decimal(str(item.get('quantity', 0))) * Decimal(str(item.get('rate', item.get('quotedRate', 0)))) * (1 - Decimal(str(item.get('discountPercent', 0))) / 100)
                if product and product.kind == 'stock': stock_net += base
                else: service_net += base
            accrued = net if stock_net and not service_net else dec(net * stock_net / (stock_net + service_net)) if stock_net else Decimal(0)
            lines = [dict(account='2105', debit=accrued), dict(account='6105', debit=net-accrued),
                     dict(account='1300', debit=tax), dict(account='2100', credit=amount, partner=partner, dueDate=row.get('dueDate'))]
        return post_entry(source, str(row.get('invoiceNo', source)), lines, row.get('invoiceDate'))
    customer = key == 'customerPayments'
    partner = ('customer:' if customer else 'vendor:') + str(row.get('customerId') if customer else row.get('vendorId'))
    cash = '1000' if str(row.get('method', '')).lower() == 'cash' else '1010'
    account = '1100' if customer else '2100'
    entry = journal_pair(source, str(row.get('paymentNo', source)), cash if customer else account,
                         account if customer else cash, amount, row.get('paymentDate'), partner)
    auto_reconcile(f'{"customerInvoices" if customer else "invoices"}:{row.get("invoiceId")}', entry, account)
    return entry


def sync_business(previous, current, namespace):
    """Project legacy UI events into immutable relational ledgers in the same transaction."""
    lock()
    if namespace == 'app':
        sync_products(current)
        # Once a document has posted, changing its economic fields needs an explicit reversal.
        for key in ('receipts', 'deliveries', 'invoices', 'customerInvoices', 'payments', 'customerPayments'):
            before = {str(r['id']): r for r in previous.get(key, [])}
            after = {str(r['id']): r for r in current.get(key, [])}
            financial = ('items', 'amount', 'subtotal', 'taxAmount', 'taxPercent', 'poId', 'orderId', 'invoiceId',
                         'vendorId', 'customerId', 'method', 'invoiceDate', 'paymentDate', 'receivedDate', 'deliveryDate')
            for rid, old in before.items():
                posted = db.session.scalar(select(JournalEntry.id).where(JournalEntry.source == f'{key}:{rid}').limit(1))
                moved = db.session.scalar(select(StockMove.id).where(StockMove.source.like(f'{key}:{rid}:%')).limit(1))
                if posted or moved:
                    new = after.get(rid)
                    if not new or any(old.get(field) != new.get(field) for field in financial) or new.get('status') == 'Cancelled':
                        raise InvalidBusinessState('Posted documents are immutable; use returns or reversing entries')
        for key in ('receipts', 'deliveries'):
            before = {str(r['id']): r for r in previous.get(key, [])}
            for row in current.get(key, []):
                if before.get(str(row['id'])) == row or (key == 'deliveries' and row.get('status') != 'Delivered'):
                    continue
                g.scope_creator = row.get('createdBy') or row.get('ownerId') or g.user.id
                order = next((o for o in current.get('orders' if key == 'receipts' else 'salesOrders', []) if str(o['id']) == str(row.get('poId' if key == 'receipts' else 'orderId'))), None)
                for index, line in enumerate(row.get('items', [])):
                    product = db.session.get(ERPProduct, str(line.get('productId')))
                    if not product or product.kind == 'service': continue
                    qty = dec(line.get('acceptedQty' if key == 'receipts' else 'deliveredQty', 0), UNIT)
                    if not qty: continue
                    src = (order or {}).get('items', [])
                    item = src[index] if key == 'receipts' and index < len(src) else {}
                    cost = Decimal(str(item.get('rate', item.get('quotedRate', 0)))) * (1 - Decimal(str(item.get('discountPercent', 0))) / 100)
                    receipt_value = None
                    if key == 'receipts' and row.get('workflowVersion') == 1 and (order or {}).get('workflowVersion') == 1:
                        # Preserve line cents across partial receipts instead of rounding
                        # a discounted unit cost first (which can leave GRNI stranded).
                        sources = [f'receipts:{receipt["id"]}:{index}' for receipt in current.get('receipts', [])
                                   if str(receipt.get('poId')) == str(order['id']) and str(receipt['id']) != str(row['id'])]
                        prior = list(db.session.scalars(select(StockMove).where(StockMove.source.in_(sources)))) if sources else []
                        prior_qty = sum((move.quantity for move in prior), Decimal(0))
                        prior_value = sum((move.value for move in prior), Decimal(0))
                        target = dec(Decimal(str(item['subtotal'])) * (prior_qty + qty) / Decimal(str(item['quantity'])))
                        receipt_value = target - prior_value
                    stock_move(product.id, qty if key == 'receipts' else -qty, f'{key}:{row["id"]}:{index}',
                               'Purchase Receipt' if key == 'receipts' else 'Sales Delivery', '2105' if key == 'receipts' else '5100',
                               cost, row.get('receivedDate' if key == 'receipts' else 'deliveryDate'), total_value=receipt_value)
        for key in ('invoices', 'customerInvoices', 'payments', 'customerPayments'):
            before = {str(r['id']): r for r in previous.get(key, [])}
            for row in current.get(key, []):
                if before.get(str(row['id'])) == row: continue
                if key == 'invoices' and row.get('status') not in ('Approved', 'Partially Paid', 'Paid'): continue
                if key == 'customerInvoices' and row.get('status') not in ('Posted', 'Partially Paid', 'Paid'): continue
                if key == 'payments' and row.get('status') != 'Processed': continue
                if key == 'customerPayments' and row.get('status') != 'Received': continue
                g.scope_creator = row.get('createdBy') or row.get('ownerId') or g.user.id
                finance_document(row, key, current)
    else:
        for collection, fields in [('attendance',('employee','date')),('payroll',('employee','month'))]:
            identities = [(str(r.get('employeeKey') or r.get(fields[0],'')),str(r.get(fields[1],''))) for r in current.get(collection,[])]
            if len(identities) != len(set(identities)):
                raise InvalidBusinessState('Duplicate '+collection+' entry for the same employee and period')
        leaves = [r for r in current.get('leaves',[]) if r.get('status') not in ('Rejected','Cancelled')]
        for index, leave in enumerate(leaves):
            start, end = day(leave.get('from')), day(leave.get('to'))
            if start > end: raise InvalidBusinessState('Leave end date must follow the start date')
            for other in leaves[index+1:]:
                if leave.get('employee') == other.get('employee') and start <= day(other.get('to')) and end >= day(other.get('from')):
                    raise InvalidBusinessState('Employee leave periods cannot overlap')
        old = {str(r['id']): r for r in previous.get('payroll', [])}
        for row in current.get('payroll', []):
            before = old.get(str(row['id']))
            source = 'payroll:' + str(row['id'])
            exists = db.session.scalar(select(JournalEntry).where(JournalEntry.source == source))
            if exists and (not before or any(before.get(k) != row.get(k) for k in ('basic', 'allowances', 'deductions', 'netPay', 'employee', 'month')) or row.get('status') not in ('Approved', 'Paid')):
                raise InvalidBusinessState('Approved payroll cannot be changed; reverse the journal first')
            if before == row or row.get('status') not in ('Approved', 'Paid'): continue
            gross = dec(row.get('basic', 0)) + dec(row.get('allowances', 0))
            deductions, net = dec(row.get('deductions', 0)), dec(row.get('netPay', 0))
            if gross <= 0 or net < 0 or gross - deductions != net:
                raise InvalidBusinessState('Payroll net pay must equal basic plus allowances less deductions')
            g.scope_creator = row.get('createdBy') or row.get('ownerId') or g.user.id
            partner = 'employee:' + str(row.get('employee', ''))
            post_entry(source, 'Payroll ' + str(row.get('month', '')), [dict(account='6100', debit=gross),
                       dict(account='2300', credit=net, partner=partner), dict(account='2310', credit=deductions)], day())
            if row.get('status') == 'Paid' and net:
                payment = journal_pair(source + ':payment', 'Salary payment ' + str(row.get('employee', '')), '2300', '1010', net, partner=partner)
                auto_reconcile(source, payment, '2300')
        for rid, row in old.items():
            if not any(str(r['id']) == rid for r in current.get('payroll', [])) and db.session.scalar(select(JournalEntry.id).where(JournalEntry.source == 'payroll:' + rid)):
                raise InvalidBusinessState('Posted payroll cannot be deleted')
        old_separations = {str(r['id']):r for r in previous.get('separations',[])}
        for separation in current.get('separations',[]):
            if separation.get('status') != 'Completed' or old_separations.get(str(separation['id']),{}).get('status') == 'Completed':
                continue
            employee = next((e for e in current.get('employees',[]) if
                             (separation.get('employeeKey') and str(e['id']) == str(separation['employeeKey'])) or
                             str(e.get('employeeId',''))+' - '+str(e.get('name','')) == separation.get('employee')),None)
            target = db.session.get(User,str(employee.get('linkedUserId'))) if employee and employee.get('linkedUserId') else None
            if target:
                if target.role == 'Admin':
                    raise InvalidBusinessState('Review administrator offboarding in User Management before completing separation')
                target.active = False
                db.session.query(LoginSession).filter_by(user_id=target.id).delete()
                audit('Disabled separated employee account',{'userId':target.id})
    db.session.flush()
    g.pop('scope_creator',None)
