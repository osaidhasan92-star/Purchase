"""Fail-closed approval routing; decisions and business commands commit together."""
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import select, or_, and_, func
from .app import db, User, app_document, audit, body, problem, utcnow
from .permissions import allowed, COLLECTIONS
from .erp import lock, dec, UNIT

bp = Blueprint('approvals', __name__, url_prefix='/api/approvals')


class Approval(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fingerprint = db.Column(db.String(64), unique=True, nullable=False)
    requester_id = db.Column(db.String(64), nullable=False, index=True)
    creator_id = db.Column(db.String(64), nullable=False)
    module = db.Column(db.String(40), nullable=False)
    amount = db.Column(db.Numeric(20, 2), nullable=False)
    path = db.Column(db.String(300), nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    source = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(20), nullable=False, default='Pending', index=True)
    reason = db.Column(db.String(1000))
    decided_by = db.Column(db.String(64))
    created_at = db.Column(db.String(40), nullable=False, default=utcnow)
    decided_at = db.Column(db.String(40))


class ApprovalLimit(db.Model):
    user_id = db.Column(db.String(64), db.ForeignKey('user.id'), primary_key=True)
    module = db.Column(db.String(40), primary_key=True)
    amount = db.Column(db.Numeric(20, 2), nullable=False)


def money(value):
    try:
        if isinstance(value, bool): raise ValueError()
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) > Decimal('1000000000000'): raise ValueError()
        return abs(number).quantize(Decimal('.01'), rounding=ROUND_CEILING)
    except (InvalidOperation, ValueError, TypeError):
        problem('Cannot determine the PKR approval value; correct the source record')


def limit(user, module):
    if not hasattr(g, 'approval_limit_values'):
        g.approval_limit_values = {(r.user_id, r.module): r.amount for r in db.session.scalars(select(ApprovalLimit))}
    explicit = g.approval_limit_values.get((user.id, module))
    if explicit is not None: return explicit
    # Finite defaults, always combined with existing module approval permission.
    if user.role == 'Admin': return Decimal('10000000')
    if user.role == 'Finance': return Decimal('1000000')
    if 'Manager' in user.role: return Decimal('100000')
    return Decimal('-1')


def eligible(user, row):
    if not hasattr(g, 'approval_permissions'):
        g.approval_permissions = app_document().stored_data
    state = g.approval_permissions
    return (user.active and user.id not in (row.creator_id, row.requester_id)
            and allowed(user, state, row.module, 'approve')
            and limit(user, row.module) >= row.amount)


def serialize(row):
    if not hasattr(g, 'approval_users'):
        g.approval_users = db.session.scalars(select(User).where(User.active.is_(True))).all()
    approvers = [dict(id=u.id, name=u.name) for u in g.approval_users if eligible(u, row)]
    return dict(id=row.id, module=row.module, amount=str(row.amount), currency='PKR',
                requesterId=row.requester_id, creatorId=row.creator_id, path=row.path,
                payload=row.payload, source=row.source, status=row.status, reason=row.reason,
                decidedBy=row.decided_by, createdAt=row.created_at, decidedAt=row.decided_at,
                approvers=approvers, canDecide=row.status == 'Pending' and eligible(g.user, row),
                blocked=not approvers and row.status == 'Pending')


def descriptor():
    """Value and ownership come from SQL records, never browser totals."""
    args = request.view_args or {}
    endpoint = request.endpoint or ''
    data = body()
    command = args.get('command', args.get('action'))
    from .scope import object_creator
    if endpoint == 'trade.command':
        from .trade_api import scoped
        from .trade_store import record
        from .trade_service import action_permission
        key = args['key']
        if not args.get('identity'):
            if key not in ('payments', 'customerPayments'): return None
            return COLLECTIONS[key], money(data.get('amount')), getattr(g, 'approval_execution', None).creator_id if getattr(g, 'approval_execution', None) else g.user.id
        row = record(key, scoped(key, args['identity']))
        g.approval_source = row
        if action_permission(key, command, row) != 'approve': return None
        amount = row.get('total', row.get('amount'))
        if amount is None and key == 'comparisons':
            q = record('quotations', scoped('quotations', row.get('selectedQuotationId')))
            amount = q.get('total')
        # Unpriced requisitions carry no spending authority; order approval follows later.
        if amount is None and key == 'requests': amount = 0
        return COLLECTIONS[key], money(amount), row.get('createdBy') or row.get('ownerId')
    if endpoint == 'expenses.command' and command in ('approve', 'reject', 'pay'):
        from .expense_api import get
        e = get(data.get('id'))
        g.approval_source = dict(number=e.number, employee=e.employee, description=e.description, date=e.date, amount=str(e.amount), tax=str(e.tax))
        return 'expenses', money(e.amount + e.tax), e.owner_id
    if endpoint == 'finance.command':
        from .finance_api import get, identity_int
        from .erp import JournalEntry
        if command in ('post', 'reverse'):
            e = get(JournalEntry, identity_int(data, 'id'))
            g.approval_source = dict(number=e.number, memo=e.memo, date=e.date, lines=[dict(account=l.account, debit=str(l.debit), credit=str(l.credit)) for l in e.lines])
            return 'accounting', money(sum(l.debit for l in e.lines)), e.created_by
        if command in ('match-bank', 'reconcile'):
            from .erp import BankStatementLine, JournalLine
            item = get(BankStatementLine, identity_int(data, 'id')) if command == 'match-bank' else get(JournalLine, identity_int(data, 'debitLine'))
            value = item.amount if command == 'match-bank' else data.get('amount')
            return 'accounting', money(value), object_creator(item)
        if command == 'period-lock': return 'accounting', Decimal(0), getattr(g, 'approval_execution', None).creator_id if getattr(g, 'approval_execution', None) else g.user.id
        if command == 'transfer': return 'accounting', money(data.get('amount')), getattr(g, 'approval_execution', None).creator_id if getattr(g, 'approval_execution', None) else g.user.id
    if endpoint == 'inventory_resources.command':
        from .inventory_api import product, get_move
        if command in ('adjust', 'scrap'):
            p, balance = product(data.get('productId'))
            g.approval_source = dict(product=p.name, currentQuantity=str(balance.quantity) if balance else '0', reason=data.get('reason'))
            quantity = dec(data.get('quantity'), UNIT)
            cost = dec(data.get('unitCost', 0), UNIT) if command == 'adjust' and quantity > 0 else (balance.value / balance.quantity if balance and balance.quantity else Decimal(0))
            return 'inventory', money(quantity * cost), getattr(g, 'approval_execution', None).creator_id if getattr(g, 'approval_execution', None) else g.user.id
        if command == 'return':
            m = get_move(data.get('moveId'))
            return 'inventory', money(m.value * dec(data.get('quantity'), UNIT) / abs(m.quantity)), object_creator(m)
    if endpoint == 'warehouse.command' and command == 'transfer':
        from .erp import StockBalance
        balance = db.session.get(StockBalance, str(data.get('productId')))
        if balance is None: problem('Stock balance not found', 404)
        value = dec(data.get('quantity'), UNIT) * balance.value / balance.quantity if balance.quantity else Decimal(0)
        return 'inventory', money(value), getattr(g, 'approval_execution', None).creator_id if getattr(g, 'approval_execution', None) else g.user.id
    if endpoint == 'credits.command' and command in ('post', 'refund', 'apply'):
        from .credit_api import get
        note = get(data.get('id'))
        g.approval_source = dict(number=note.number, kind=note.kind, invoiceId=note.invoice_id, reason=note.reason)
        return 'accounting', money(note.amount), note.created_by
    if endpoint == 'hr_resources.command' and command in ('approve', 'pay', 'reject', 'complete'):
        from .hr_api import scoped
        from .hr_store import record
        key = args['key']
        row = record(key, scoped(key, args['identity']))
        g.approval_source = row
        from .permissions import HR_COLLECTIONS
        return HR_COLLECTIONS[key], money(row.get('netPay', 0)), row.get('createdBy') or row.get('ownerId')
    if endpoint == 'production.command' and command in ('confirm', 'complete'):
        from .production_api import get
        from .erp import ManufacturingOrder, StockBalance
        order = get(ManufacturingOrder, data.get('id'))
        g.approval_source = dict(number=order.number, quantity=str(order.quantity), productId=order.product_id, date=order.date)
        value = max(order.conversion_cost, money_quantity(data.get('conversionCost', order.conversion_cost)))
        actual = data.get('components') or []
        if not isinstance(actual, list) or any(not isinstance(item, dict) for item in actual): problem('Invalid actual components')
        for line in order.lines:
            b = db.session.get(StockBalance, line.product_id)
            quantity = max([line.quantity] + [dec(item.get('quantity', 0), UNIT) + dec(item.get('scrap', 0), UNIT) for item in actual if str(item.get('productId')) == line.product_id])
            if b and b.quantity: value += money(quantity * b.value / b.quantity)
        return 'manufacturing', money(value), object_creator(order)
    return None


def money_quantity(value):
    try:
        if isinstance(value, bool): raise ValueError()
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) > Decimal('1000000000000'): raise ValueError()
        return number
    except (InvalidOperation, ValueError, TypeError): problem('Invalid approval quantity or cost')


def install(app):
    @app.before_request
    def approval_gate():
        if not app.config.get('APPROVAL_CONTROLS', True): return
        if request.method == 'PATCH' and request.path in ('/api/state', '/api/hr/state'):
            from .permissions import HR_COLLECTIONS
            sensitive = (set(COLLECTIONS) - {'vendors', 'products', 'customers', 'companies', 'leads', 'reminders', 'crmQuotes'}) if request.path == '/api/state' else set(HR_COLLECTIONS)
            if set(body().get('changes', {})) & sensitive:
                problem('Use native workflows with approval controls', 410)
        if request.method != 'POST': return
        endpoint = request.endpoint or ''
        if endpoint not in ('trade.command', 'expenses.command', 'finance.command', 'inventory_resources.command', 'credits.command', 'hr_resources.command', 'production.command', 'warehouse.command'):
            # Retire financial write adapters so they cannot bypass this gate.
            if request.path.startswith('/api/erp/') and endpoint != 'erp.company_profile':
                problem('Use the native workflow APIs; legacy ERP writes are retired', 410)
            return
        lock()
        from .workflow_keys import revalidate_actor
        revalidate_actor()
        target = descriptor()
        if target is None: return
        module, amount, creator = target
        if not creator: problem('Attribute the source creator before requesting approval', 409)
        if not (allowed(g.user, app_document().stored_data, module, 'approve') or allowed(g.user, app_document().stored_data, module, 'create')):
            problem('Module access required', 403)
        data = body()
        from .app import validate_json
        validate_json(data)
        if not isinstance(data.get('requestKey'), str) or not 8 <= len(data['requestKey']) <= 100:
            problem('A unique requestKey is required')
        execution = getattr(g, 'approval_execution', None)
        if execution is not None:
            if (execution.path != request.path or execution.payload != data or execution.module != module
                    or execution.creator_id != str(creator) or execution.amount != amount or not eligible(g.user, execution)):
                problem('Approval authority or source value changed; submit a new request', 409)
            execution.status = 'Approved'
            execution.decided_by = g.user.id
            execution.decided_at = utcnow()
            audit('Approval approved', dict(approvalId=execution.id, module=module, amount=str(amount), reason=execution.reason))
            return
        fingerprint = hashlib.sha256(json.dumps([g.user.id, request.path, data], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        row = db.session.scalar(select(Approval).where(Approval.fingerprint == fingerprint))
        if row is None:
            row = Approval(fingerprint=fingerprint, requester_id=g.user.id, creator_id=str(creator), module=module,
                           amount=amount, path=request.path, payload=data, source=getattr(g, 'approval_source', {}), status='Pending')
            db.session.add(row)
            db.session.flush()
            audit('Approval requested', dict(approvalId=row.id, module=module, amount=str(amount)))
            db.session.commit()
        return jsonify(error='Approval required. Open Pending Approvals to review the request.', approval=serialize(row)), 409


    app.extensions['approval_gate'] = approval_gate

    @app.after_request
    def submit_to_inbox(response):
        if not app.config.get('APPROVAL_CONTROLS', True) or response.status_code != 200 or getattr(g, 'approval_execution', None) is not None:
            return response
        args = request.view_args or {}
        endpoint = request.endpoint or ''
        result = response.get_json(silent=True) or {}
        record = result.get('record')
        if not isinstance(record, dict): return response
        target = None
        if endpoint == 'trade.command' and (args.get('action') == 'submit' or (args.get('identity') is None and args.get('key') == 'requests')) and record.get('status') == 'Pending Approval':
            key = args['key']
            if key in ('requests', 'orders', 'salesQuotations', 'invoices', 'customerInvoices'):
                target = '/api/trade/' + key + '/' + str(record['id']) + '/actions/' + ('post' if key in ('invoices', 'customerInvoices') else 'approve')
        elif endpoint in ('expenses.command', 'credits.command') and args.get('action', args.get('command')) == 'submit' and record.get('status') in ('Submitted', 'Pending Review'):
            target = '/api/' + ('expenses' if endpoint == 'expenses.command' else 'credits') + '/commands/' + ('approve' if endpoint == 'expenses.command' else 'post')
        elif endpoint == 'hr_resources.command' and record.get('status') in ('Draft', 'Pending', 'Requested') and args.get('identity') is None and args.get('key') in ('payroll', 'leaves', 'manpower', 'separations'):
            target = '/api/hr/records/' + args['key'] + '/' + str(record['id']) + '/actions/approve'
        elif endpoint == 'production.command' and args.get('command') == 'order' and record.get('state') == 'Draft':
            target = '/api/production/commands/confirm'
        if target:
            payload = dict(version=record['version'], requestKey='approval-auto-' + hashlib.sha256((target + record['version']).encode()).hexdigest()[:50])
            if '/commands/' in target: payload['id'] = record['id']
            # The submission has already committed. Queuing cannot change its result.
            # An unattributed legacy record remains visible for manual remediation.
            from werkzeug.exceptions import HTTPException
            try:
                with app.test_request_context(target, method='POST', json=payload):
                    queued = approval_gate()
                if queued is not None:
                    value = app.make_response(queued).get_json()
                    if value and value.get('approval'):
                        result['approvalRequested'] = value['approval']['id']
                        response.set_data(app.json.dumps(result))
            except HTTPException:
                db.session.rollback()
        return response


@bp.get('')
def inbox():
    page = max(1, request.args.get('page', 1, type=int))
    size = min(100, max(1, request.args.get('pageSize', 25, type=int)))
    conditions = [or_(Approval.requester_id == g.user.id, Approval.creator_id == g.user.id)]
    if g.user.role == 'Admin':
        visible = True
    else:
        from .permissions import MODULES
        for module in MODULES:
            if allowed(g.user, app_document().stored_data, module, 'approve'):
                conditions.append(and_(Approval.module == module, Approval.amount <= limit(g.user, module)))
        visible = or_(*conditions)
    status = request.args.get('status', '')
    if status and status not in ('Pending', 'Approved', 'Rejected'): problem('Unknown approval status')
    query = select(Approval).where(visible)
    if status: query = query.where(Approval.status == status)
    total = db.session.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.session.scalars(query.order_by(Approval.id.desc()).offset((page-1)*size).limit(size)).all()
    return jsonify(items=[serialize(r) for r in rows], total=total, page=page, pageSize=size)



@bp.route('/limits', methods=['GET', 'PUT'])
def limits():
    if g.user.role != 'Admin': problem('Administrator access required', 403)
    if request.method == 'PUT':
        data = body()
        if set(data) != {'userId', 'module', 'amount'}: problem('Choose userId, module and amount')
        from .permissions import MODULES
        if data['module'] not in MODULES or not db.session.get(User, data['userId']): problem('Unknown user or module')
        amount = money_quantity(data['amount'])
        if amount < 0 or amount != amount.quantize(Decimal('.01')): problem('Use a non-negative PKR amount with at most two decimals')
        lock()
        from .workflow_keys import revalidate_actor
        revalidate_actor()
        if g.user.role != 'Admin': problem('Administrator access required', 403)
        row = db.session.get(ApprovalLimit, (data['userId'], data['module']))
        if row is None:
            row = ApprovalLimit(user_id=data['userId'], module=data['module'], amount=amount)
            db.session.add(row)
        row.amount = amount
        audit('Approval limit changed', dict(userId=row.user_id, module=row.module, amount=str(amount)))
        db.session.commit()
    from .permissions import MODULES
    return jsonify(defaults={'Manager': '100000.00', 'Finance': '1000000.00', 'Admin': '10000000.00'},
                   modules=list(MODULES), users=[dict(id=u.id, name=u.name, role=u.role) for u in db.session.scalars(select(User))],
                   items=[dict(userId=r.user_id, module=r.module, amount=str(r.amount)) for r in db.session.scalars(select(ApprovalLimit))])


@bp.post('/<int:identity>/<decision>')
def decide(identity, decision):
    if decision not in ('approve', 'reject'): problem('Unknown approval decision', 404)
    data = body()
    reason = data.get('reason')
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000: problem('A decision reason of 1–1000 characters is required')
    lock()
    from .workflow_keys import revalidate_actor
    revalidate_actor()
    row = db.session.scalar(select(Approval).where(Approval.id == identity).with_for_update())
    if row is None: problem('Approval not found', 404)
    if not eligible(g.user, row): problem('A different authorized approver within their PKR limit is required', 403)
    if row.status != 'Pending': problem('This request has already been decided', 409)
    row.reason = reason.strip()
    if decision == 'reject':
        row.status, row.decided_by, row.decided_at = 'Rejected', g.user.id, utcnow()
        audit('Approval rejected', dict(approvalId=row.id, reason=row.reason, module=row.module, amount=str(row.amount)))
        db.session.commit()
        return jsonify(record=serialize(row))
    # Dispatch the original immutable command as the approver; its permissions,
    # scope, version and business checks still run. Same app context/transaction.
    g.approval_execution = row
    try:
        with current_app.test_request_context(row.path, method='POST', json=row.payload):
            gate_result = current_app.extensions['approval_gate']()
            if gate_result is not None:
                db.session.rollback()
                return gate_result
            response = current_app.make_response(current_app.view_functions[request.endpoint](**request.view_args))
        if response.status_code >= 400 or row.status != 'Approved':
            db.session.rollback()
            return response if response.status_code >= 400 else (jsonify(error='Command did not consume approval'), 409)
        return jsonify(record=serialize(row), result=response.get_json())
    except Exception:
        db.session.rollback()
        raise
    finally:
        g.pop('approval_execution', None)
