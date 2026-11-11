"""Independent, amount-limited approvals around existing atomic business commands."""

from copy import deepcopy
from decimal import Decimal
import re
import time
from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import select, or_, inspect
from .app import db, User, app_document, body, problem, audit, validate_json
from .permissions import allowed, COLLECTIONS, HR_COLLECTIONS
from .trade_store import version
from .erp import dec, lock, StockBalance, StockMove

bp = Blueprint("approvals", __name__, url_prefix="/api/approvals")


class ApprovalPolicy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    limits = db.Column(db.JSON, nullable=False, default=dict)


class ApprovalRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    submitted_by = db.Column(
        db.String(64), db.ForeignKey("user.id"), nullable=False, index=True
    )
    owner_id = db.Column(db.String(64), nullable=False)
    assigned_to = db.Column(db.String(64), db.ForeignKey("user.id"), index=True)
    module = db.Column(db.String(64), nullable=False)
    resource = db.Column(db.String(64), nullable=False)
    target = db.Column(db.String(100), nullable=False)
    operation = db.Column(db.String(64), nullable=False)
    label = db.Column(db.String(200), nullable=False)
    endpoint = db.Column(db.String(100), nullable=False)
    arguments = db.Column(db.JSON, nullable=False)
    review = db.Column(db.JSON, nullable=False, default=dict)
    payload = db.Column(db.JSON, nullable=False)
    amount = db.Column(db.Numeric(20, 2), nullable=False)
    mode = db.Column(db.String(20), nullable=False)
    beneficiaries = db.Column(db.JSON, nullable=False, default=list)
    source_version = db.Column(db.String(64))
    fingerprint = db.Column(db.String(64), nullable=False, index=True)
    request_key = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Pending", index=True)
    last_routed = db.Column(db.Float, nullable=False, default=0, index=True)
    created_at = db.Column(db.Float, nullable=False, default=time.time)
    decided_by = db.Column(db.String(64), db.ForeignKey("user.id"))
    decided_at = db.Column(db.Float)
    reason = db.Column(db.String(500))
    result = db.Column(db.JSON)
    __table_args__ = (
        db.UniqueConstraint("submitted_by", "request_key"),
        db.Index(
            "ix_approval_source_state", "resource", "target", "status", "source_version"
        ),
        db.Index("ix_approval_inbox", "assigned_to", "status", "id"),
        db.CheckConstraint("amount >= 0", name="ck_approval_amount"),
    )


def enabled():
    return current_app.config.get("APPROVAL_CONTROLS_ENABLED", True)


def ready():
    if not inspect(db.engine).has_table("approval_request"):
        problem(
            "Run flask --app backend.app migrate-storage to enable approval controls",
            503,
        )


def policy():
    if not hasattr(g, "approval_limits"):
        row = db.session.get(ApprovalPolicy, 1)
        g.approval_limits = deepcopy(row.limits if row else {})
    values = g.approval_limits
    return dict(
        limits=values,
        version=version(values),
        currency="PKR",
        independent=True,
        enabled=enabled(),
    )


def cap(user):
    value = policy()["limits"].get(user.role)
    return Decimal(value) if value is not None else None


def creator(obj):
    from .scope import object_creator

    value = getattr(obj, "created_by", None) or object_creator(obj)
    if not value:
        problem(
            "Historical record needs reviewed creator attribution before approval", 409
        )
    return str(value)


def descriptor(endpoint, args, data):
    """Read current authoritative amounts and enforce the original source scope."""
    result = None
    if endpoint == "trade.command":
        from .trade_api import scoped
        from . import trade_store as store
        from .trade_service import action_permission

        key = args["key"]
        action = args.get("action")
        if key not in store.MODELS:
            return None
        if args.get("identity") and action:
            row = scoped(key, args["identity"])
            value = store.record(key, row)
            if action_permission(key, action, value) != "approve":
                return None
            result = dict(
                module=COLLECTIONS[key],
                resource=key,
                target=str(row.id),
                owner=str(value.get("createdBy") or creator(row)),
                amount=dec(
                    value.get(
                        "amount", value.get("total", value.get("estimatedTotal", 0))
                    )
                ),
                label=(row.number or key) + " · " + action,
                mode="record",
                review={
                    k: v
                    for k, v in value.items()
                    if k
                    in (
                        "items",
                        "lineItems",
                        "customerName",
                        "vendorName",
                        "requester",
                        "department",
                        "notes",
                        "date",
                        "closeReason",
                    )
                },
            )
            if key in ("invoices", "customerInvoices") and action in (
                "post",
                "approve",
            ):
                result["extra"] = "accounting"
        elif key in ("payments", "customerPayments") and not args.get("identity"):
            invoice_row = scoped(
                "invoices" if key == "payments" else "customerInvoices",
                data.get("invoiceId"),
            )
            result = dict(
                module=COLLECTIONS[key],
                resource=key,
                target=str(data.get("invoiceId")),
                owner=g.user.id,
                amount=dec(data.get("amount"), positive=True),
                label="Payment · "
                + str(invoice_row.number)
                + " · "
                + str(invoice_row.partner_name or ""),
                mode="immediate",
                extra="accounting",
            )
    elif endpoint == "expenses.command" and args.get("action") in (
        "approve",
        "reject",
        "pay",
    ):
        from .expense_api import get

        row = get(data.get("id"))
        result = dict(
            module="expenses",
            resource="expenses",
            target=str(row.id),
            owner=row.owner_id,
            amount=dec(row.amount + row.tax),
            label=row.number + " · " + args["action"],
            review=dict(
                employee=row.employee,
                description=row.description,
                date=row.date,
                account=row.account,
                tax=str(row.tax),
                **(
                    {"attachmentHref": "/api/attachments/" + row.attachment_id}
                    if row.attachment_id
                    else {}
                )
            ),
            mode="record",
        )
        if args["action"] == "pay":
            result["extra"] = "accounting"
            result["mode"] = "immediate"
    elif endpoint == "hr_resources.command" and args.get("action"):
        from .hr_api import scoped, action_permission
        from . import hr_store as store

        key = args["key"]
        action = args["action"]
        if action_permission(key, action) != "approve":
            return None
        row = scoped(key, args["identity"])
        value = store.record(key, row)
        result = dict(
            module=HR_COLLECTIONS[key],
            resource="hr:" + key,
            target=str(row.id),
            owner=str(value.get("createdBy") or creator(row)),
            amount=dec(
                value.get("netPay", 0)
                if action == "pay"
                else Decimal(str(value.get("basic", 0)))
                + Decimal(str(value.get("allowances", 0)))
            ),
            label=key + " #" + str(row.id) + " · " + action,
            review={
                k: v
                for k, v in value.items()
                if k
                in (
                    "employee",
                    "name",
                    "month",
                    "basic",
                    "allowances",
                    "deductions",
                    "netPay",
                    "fromDate",
                    "toDate",
                    "reason",
                    "department",
                    "position",
                )
            },
            mode="record",
        )
        employee = db.session.get(store.Employee, str(value.get("employeeKey")))
        if key == "payroll" and action == "pay":
            result["extra"] = "accounting"
            result["mode"] = "immediate"
        result["beneficiaries"] = (
            [employee.linked_user_id] if employee and employee.linked_user_id else []
        )
    elif endpoint == "inventory_resources.command":
        command = args["command"]
        if command not in ("adjust", "scrap", "return"):
            return None
        from .inventory_api import product, get_move

        qty = abs(dec(data.get("quantity"), Decimal(".0001")))
        if command == "return":
            original = get_move(data.get("moveId"))
            p, b = product(original.product_id)
            cost = (
                (
                    abs(original.value / original.quantity)
                    if original.quantity
                    else Decimal(0)
                )
                if original.kind == "Sales Delivery"
                else (b.value / b.quantity if b and b.quantity else Decimal(0))
            )
        else:
            p, b = product(str(data.get("productId")))
            cost = (
                Decimal(str(data.get("unitCost", 0)))
                if command == "adjust" and Decimal(str(data.get("quantity", 0))) > 0
                else (b.value / b.quantity if b and b.quantity else Decimal(0))
            )
        result = dict(
            module="inventory",
            resource="inventory",
            target=str(p.id),
            owner=g.user.id,
            amount=dec(qty * cost),
            label=command.title() + " · " + p.name,
            review=dict(
                product=p.name,
                unit=p.unit,
                **(
                    dict(sourceMove=original.number, sourceKind=original.kind)
                    if command == "return"
                    else {}
                )
            ),
            mode="immediate",
        )
    elif endpoint == "production.command" and args.get("command") in (
        "confirm",
        "stage",
        "start",
        "complete",
        "cancel",
    ):
        from .production_api import get, order_record
        from .erp import ManufacturingOrder

        row = get(ManufacturingOrder, data.get("id"))
        record = order_record(row)
        amount = Decimal(record["estimatedCost"])
        if args["command"] == "complete" and data.get("components") is not None:
            amount = Decimal(str(data.get("conversionCost", row.conversion_cost)))
            for line in data["components"]:
                b = db.session.get(StockBalance, str(line.get("productId")))
                amount += (
                    Decimal(str(line.get("quantity", 0)))
                    + Decimal(str(line.get("scrap", 0)))
                ) * (b.value / b.quantity if b and b.quantity else Decimal(0))
        result = dict(
            module="manufacturing",
            resource="manufacturing",
            target=str(row.id),
            owner=creator(row),
            amount=dec(amount),
            label=row.number + " · " + args["command"],
            review=dict(
                product=record["product"],
                date=row.date,
                plannedQuantity=str(row.quantity),
                plannedComponents=record["components"],
            ),
            mode="immediate" if args["command"] == "complete" else "record",
        )
    elif endpoint == "finance.command" and args.get("command") in (
        "post",
        "reverse",
        "transfer",
        "reconcile",
        "match-bank",
        "period-lock",
    ):
        from .finance_api import get
        from .erp import JournalEntry, BankStatementLine

        command = args["command"]
        owner = g.user.id
        amount = dec(data.get("amount", 0))
        mode = "immediate"
        if command in ("post", "reverse"):
            row = get(JournalEntry, data.get("id"))
            owner = creator(row)
            amount = dec(sum(l.debit for l in row.lines))
            mode = "record"
        elif command == "match-bank":
            row = get(BankStatementLine, data.get("id"))
            owner = creator(row)
            amount = abs(row.amount)
            mode = "record"
        review = {}
        if command in ("post", "reverse"):
            review = dict(
                memo=row.memo,
                date=row.date,
                lines=[
                    dict(
                        account=line.account,
                        debit=str(line.debit),
                        credit=str(line.credit),
                        partner=line.partner,
                    )
                    for line in row.lines
                ],
            )
        result = dict(
            review=review,
            module="accounting",
            resource="accounting",
            target=str(data.get("id", "new")),
            owner=owner,
            amount=amount,
            label="Finance · " + command,
            mode=mode,
        )
    elif endpoint == "credits.command" and args.get("command") in (
        "post",
        "refund",
        "apply",
    ):
        from .credit_api import get, invoice, resource, record as credit_record

        row = get(data.get("id"))
        inv = invoice(row.kind, row.invoice_id)
        result = dict(
            module="accounting",
            resource="credits",
            target=str(row.id),
            owner=creator(row),
            amount=dec(row.amount if args["command"] == "post" else data.get("amount")),
            label=row.number + " · " + args["command"],
            review={
                k: v
                for k, v in credit_record(row).items()
                if k
                in (
                    "kind",
                    "invoiceNumber",
                    "partner",
                    "date",
                    "reason",
                    "lines",
                    "remaining",
                    "tax",
                )
            },
            mode="record" if args["command"] == "post" else "immediate",
            extra=COLLECTIONS[resource(row.kind)],
        )
    elif endpoint == "warehouse.command" and args.get("command") == "transfer":
        from .inventory_api import product

        p, b = product(str(data.get("productId")))
        qty = abs(dec(data.get("quantity"), Decimal(".0001")))
        result = dict(
            module="inventory",
            resource="warehouse",
            target=str(p.id),
            owner=g.user.id,
            amount=dec(qty * b.value / b.quantity if b and b.quantity else 0),
            label="Internal transfer · " + p.name,
            review=dict(product=p.name, unit=p.unit),
            mode="immediate",
        )
    if result:
        if not db.session.get(User, str(result["owner"])):
            problem(
                "Historical record needs reviewed creator attribution before approval",
                409,
            )
        result.update(
            operation=args.get("action") or args.get("command") or "create",
            endpoint=endpoint,
            arguments=args,
            beneficiaries=result.get("beneficiaries", []),
        )
        if result["amount"] < 0:
            problem("Approval amount cannot be negative")
        if not allowed(g.user, app_document().stored_data, result["module"]):
            problem("Source module access required", 403)
    return result


def can_review(user, desc, requester=None):
    if (
        not user
        or not user.active
        or user.id in (desc["owner"], requester)
        or user.id in desc.get("beneficiaries", [])
    ):
        return False
    state = app_document().stored_data
    ceiling = cap(user)
    if ceiling is None or ceiling < desc["amount"]:
        return False
    if not allowed(user, state, desc["module"], "approve") or not allowed(
        user, state, desc["module"]
    ):
        return False
    if desc.get("extra") and not allowed(user, state, desc["extra"], "approve"):
        return False
    if desc["mode"] == "immediate" and not allowed(
        user, state, desc["module"], "create"
    ):
        return False
    # Evaluate the same scoped readers as the business endpoint, under the candidate.
    original = g.user
    try:
        g.user = user
        descriptor(desc["endpoint"], desc["arguments"], desc.get("payload", {}))
        return True
    except Exception as error:
        from werkzeug.exceptions import HTTPException

        if isinstance(error, HTTPException):
            return False
        raise
    finally:
        g.user = original


def route(desc, requester):
    owner = db.session.get(User, requester)
    chain = []
    seen = set()
    while owner and owner.manager_id and owner.manager_id not in seen:
        seen.add(owner.manager_id)
        owner = db.session.get(User, owner.manager_id)
        if owner:
            chain.append(owner)
    # All candidates still need original source scope; there is no blanket manager access.
    state = app_document().stored_data
    roles = [
        role
        for role, value in policy()["limits"].items()
        if Decimal(value) >= desc["amount"]
        and (
            role == "Admin"
            or state.get("roles", {})
            .get(role, {})
            .get("permissions", {})
            .get(desc["module"], {})
            .get("approve")
            is True
        )
    ]
    eligible = select(User).where(
        User.active.is_(True),
        User.role.in_(roles),
        User.id.not_in([desc["owner"], requester] + desc.get("beneficiaries", [])),
    )
    candidates = (
        chain
        + list(
            db.session.scalars(
                eligible.where(User.role != "Admin").order_by(User.id).limit(100)
            )
        )
        + list(
            db.session.scalars(
                eligible.where(User.role == "Admin").order_by(User.id).limit(10)
            )
        )
    )
    seen = set()
    for user in candidates:
        if user.id not in seen and can_review(user, desc, requester):
            return user.id
        seen.add(user.id)
    return None


def row_desc(row):
    desc = descriptor(row.endpoint, row.arguments, row.payload)
    if not desc:
        problem("Approval operation is no longer supported", 409)
    desc["owner"] = row.owner_id
    desc["beneficiaries"] = list(set(desc.get("beneficiaries", []) + row.beneficiaries))
    desc["payload"] = row.payload
    return desc


def queue(desc, payload, submitter=None):
    if sensitive(payload) or sensitive(desc.get("review", {})):
        problem("Credentials cannot be stored in approval requests")
    submitter = submitter or g.user.id
    key = payload.get("requestKey")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
        problem("A unique requestKey is required")
    fingerprint = version(
        [
            desc["endpoint"],
            desc["arguments"],
            {k: v for k, v in payload.items() if k != "requestKey"},
        ]
    )
    prior = db.session.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.submitted_by == submitter,
            ApprovalRequest.request_key == key,
        )
    )
    if prior:
        if prior.fingerprint != fingerprint:
            problem("Approval request key was used for a different operation", 409)
        return prior
    duplicate = db.session.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.fingerprint == fingerprint,
            ApprovalRequest.status == "Pending",
            ApprovalRequest.owner_id == desc["owner"],
        )
    )
    if duplicate:
        return duplicate
    desc["payload"] = payload
    row = ApprovalRequest(
        submitted_by=submitter,
        owner_id=desc["owner"],
        module=desc["module"],
        resource=desc["resource"],
        target=desc["target"],
        operation=desc["operation"],
        label=desc["label"],
        endpoint=desc["endpoint"],
        arguments=desc["arguments"],
        payload=deepcopy(payload),
        review=review_snapshot(desc.get("review", {}), payload),
        amount=desc["amount"],
        mode=desc["mode"],
        beneficiaries=desc["beneficiaries"],
        source_version=payload.get("version"),
        fingerprint=fingerprint,
        request_key=key,
        status="Pending",
        assigned_to=route(desc, submitter),
    )
    db.session.add(row)
    db.session.flush()
    audit(
        "Approval requested",
        dict(
            approvalId=row.id,
            resource=row.resource,
            target=row.target,
            amount=str(row.amount),
            assignedTo=row.assigned_to,
        ),
    )
    return row


def display(row):
    requester = db.session.get(User, row.submitted_by)
    assigned = db.session.get(User, row.assigned_to) if row.assigned_to else None
    value = dict(
        id=row.id,
        label=row.label,
        module=row.module,
        resource=row.resource,
        target=row.target,
        operation=row.operation,
        amount=str(row.amount),
        currency="PKR",
        requester=requester.name if requester else row.submitted_by,
        assignedTo=assigned.name if assigned else None,
        status=row.status,
        reason=row.reason,
        details=row.review,
        createdAt=row.created_at,
        decidedAt=row.decided_at,
        decidedBy=row.decided_by,
    )
    value["version"] = version(value)
    value["canDecide"] = False
    if row.status == "Pending" and (
        row.assigned_to == g.user.id or g.user.role == "Admin"
    ):
        try:
            value["canDecide"] = can_review(g.user, row_desc(row), row.submitted_by)
        except Exception as error:
            from werkzeug.exceptions import HTTPException

            if not isinstance(error, HTTPException):
                raise
    return value


def intercept():
    if (
        not enabled()
        or request.method not in ("POST", "PATCH", "DELETE")
        or request.path.startswith("/api/approvals/")
        or not getattr(g, "user", None)
    ):
        return
    # Removed transports cannot bypass new controls. Maintenance imports are offline operations.
    if (
        request.path.startswith("/api/erp/")
        or request.path
        in ("/api/state", "/api/hr/state", "/api/import", "/api/admin/import")
        or (
            request.path.startswith("/api/admin/commands/")
            and (request.view_args or {}).get("kind") in ("seed", "import", "demo")
        )
    ):
        problem("Use native workflows with independent approval controls", 410)
    endpoints = {
        "trade.command",
        "expenses.command",
        "hr_resources.command",
        "inventory_resources.command",
        "production.command",
        "finance.command",
        "credits.command",
        "warehouse.command",
    }
    if request.endpoint not in endpoints or not controlled(
        request.endpoint, request.view_args or {}
    ):
        return
    data = body()
    validate_json(data)
    # These are workflow payloads only, never login/account/password commands.
    if (
        request.endpoint == "hr_resources.command"
        and (request.view_args or {}).get("action") == "login"
    ):
        return
    ready()
    lock()
    from .workflow_keys import revalidate_actor

    revalidate_actor()
    reason = data.pop("approvalReason", None)
    if reason is not None and (
        not isinstance(reason, str) or not reason.strip() or len(reason) > 500
    ):
        problem("Record a decision reason (1–500 characters)")
    request._cached_json = (data, data)
    desc = descriptor(request.endpoint, request.view_args or {}, data)
    if not desc:
        return
    if sensitive(data):
        problem("Credentials cannot be stored in approval requests")
    action = desc["operation"]
    if action in ("reject", "reset", "clear"):
        if not isinstance(reason, str) or not reason.strip():
            problem("Use Pending Approvals to record a decision reason")
        pending_rows = list(
            db.session.scalars(
                select(ApprovalRequest).where(
                    ApprovalRequest.resource == desc["resource"],
                    ApprovalRequest.target == desc["target"],
                    ApprovalRequest.status == "Pending",
                )
            )
        )
        if not pending_rows:
            item = queue(desc, data, desc["owner"])
            if item.status != "Pending":
                db.session.commit()
                return (
                    jsonify(
                        approvalPending=True,
                        approval=display(item),
                        message="This request is already " + item.status.lower(),
                    ),
                    202,
                )
            pending_rows = [item]
        for pending in pending_rows:
            pending.status = "Rejected"
            pending.reason = reason.strip()
            pending.decided_by = g.user.id
            pending.decided_at = time.time()
            pending.assigned_to = g.user.id
        audit(
            "Approval rejection/review",
            dict(resource=desc["resource"], target=desc["target"], reason=reason[:500]),
        )
        return
    desc["payload"] = data
    if desc["mode"] == "record" and can_review(g.user, desc):
        row = queue(desc, data, desc["owner"])
        if row.status != "Pending":
            db.session.commit()
            return (
                jsonify(
                    approvalPending=True,
                    approval=display(row),
                    message="This request is already " + row.status.lower(),
                ),
                202,
            )
        if row.assigned_to != g.user.id:
            audit(
                "Approval assigned",
                dict(approvalId=row.id, previous=row.assigned_to, assignedTo=g.user.id),
            )
        row.assigned_to = g.user.id
        if reason is None:
            db.session.commit()
            return (
                jsonify(
                    approvalPending=True,
                    approval=display(row),
                    message="Record your decision reason in Pending Approvals before execution",
                ),
                202,
            )
        row.status = "Approved"
        row.decided_by = g.user.id
        row.decided_at = time.time()
        row.reason = reason.strip()
        audit(
            "Approval approved",
            dict(
                approvalId=row.id,
                amount=str(desc["amount"]),
                reason=row.reason,
                limit=str(cap(g.user)),
                policyVersion=policy()["version"],
            ),
        )
        return
    # A submitter may request review but does not gain approval permission.
    state = app_document().stored_data
    if not any(
        allowed(g.user, state, desc["module"], a) for a in ("create", "edit", "approve")
    ):
        problem("Permission to request this operation is required", 403)
    row = queue(desc, data)
    db.session.commit()
    return (
        jsonify(
            approvalPending=True,
            approval=display(row),
            message="Submitted for independent approval. No business changes posted.",
        ),
        202,
    )


@bp.get("/policy")
def get_policy():
    ready()
    if g.user.role != "Admin":
        problem("Administrator access required", 403)
    return jsonify(**policy(), roles=list(app_document().stored_data.get("roles", {})))


@bp.post("/policy")
def save_policy():
    ready()
    if g.user.role != "Admin":
        problem("Administrator access required", 403)
    data = body()
    validate_json(data)
    lock()
    if set(data) - {"limits", "version", "reason"}:
        problem("Unknown approval policy fields")
    if data.get("version") != policy()["version"]:
        problem("Approval policy changed; reload", 409)
    values = data.get("limits")
    roles = app_document().stored_data.get("roles", {})
    if not isinstance(values, dict) or set(values) - set(roles):
        problem("Choose known roles")
    cleaned = {}
    for role, amount in values.items():
        amount = dec(amount)
        if amount < 0:
            problem("Approval limits cannot be negative")
        cleaned[role] = str(amount)
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        problem("Record a policy change reason")
    row = db.session.get(ApprovalPolicy, 1)
    if not row:
        row = ApprovalPolicy(id=1)
        db.session.add(row)
    before = deepcopy(row.limits or {})
    row.limits = cleaned
    g.approval_limits = cleaned
    audit("Approval policy changed", dict(before=before, after=cleaned, reason=reason))
    db.session.flush()
    from sqlalchemy import update

    db.session.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.status == "Pending")
        .values(last_routed=0)
    )
    reroute_pending()
    db.session.commit()
    return jsonify(**policy())


@bp.get("/requests")
def requests():
    ready()
    from .finance_api import paged

    condition = inbox_scope()
    query = select(ApprovalRequest).where(condition)
    if request.args.get("id"):
        query = query.where(ApprovalRequest.id == request.args["id"])
    status = request.args.get("status", "Pending")
    if status:
        query = query.where(ApprovalRequest.status == status)
    rows, meta = paged(query, [ApprovalRequest.id.desc()])
    return jsonify(items=[display(r[0]) for r in rows], enabled=enabled(), **meta)


@bp.post("/requests/<int:identity>/<action>")
def decide(identity, action):
    ready()
    data = body()
    validate_json(data)
    lock()
    from .workflow_keys import revalidate_actor

    revalidate_actor()
    row = db.session.get(ApprovalRequest, identity)
    if not row or (row.assigned_to != g.user.id and g.user.role != "Admin"):
        problem("Approval not found", 404)
    if data.get("version") != display(row)["version"]:
        problem("Approval changed; reload", 409)
    if row.status != "Pending":
        problem("Approval already decided", 409)
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        problem("Record a decision reason")
    desc = row_desc(row)
    if not can_review(g.user, desc, row.submitted_by):
        problem(
            "Independent approver, source access and sufficient PKR limit required", 403
        )
    if action not in ("approve", "reject"):
        problem("Unknown approval decision", 404)
    row.decided_by = g.user.id
    row.decided_at = time.time()
    row.reason = reason.strip()
    if action == "reject":
        row.status = "Rejected"
        audit("Approval rejected", dict(approvalId=row.id, reason=row.reason))
        rejection = rejection_command(row)
        if rejection:
            endpoint, arguments, payload = rejection
            request._cached_json = (payload, payload)
            result = current_app.make_response(
                current_app.view_functions[endpoint](**arguments)
            )
            if result.status_code >= 400:
                db.session.rollback()
                return result
        db.session.commit()
        return jsonify(approval=display(row))
    requester = db.session.get(User, row.submitted_by)
    if row.mode == "immediate" and (not requester or not requester.active):
        problem("Requester account is no longer active; reject this request", 409)
    row.status = "Approved"
    row.amount = desc["amount"]
    audit(
        "Approval approved",
        dict(
            approvalId=row.id,
            reason=row.reason,
            amount=str(row.amount),
            requester=row.submitted_by,
            limit=str(cap(g.user)),
            policyVersion=policy()["version"],
        ),
    )
    # Execute the original versioned/idempotent command in this transaction as reviewer.
    payload = deepcopy(row.payload)
    payload["requestKey"] = "approval-execute-" + version(
        [row.id, g.user.id, row.fingerprint]
    )
    request._cached_json = (payload, payload)
    g.approval_requester_id = row.submitted_by
    result = current_app.view_functions[row.endpoint](**row.arguments)
    response = current_app.make_response(result)
    if response.status_code >= 400:
        db.session.rollback()
        return response
    # Original command commits approval decision and economic effects together.
    row.result = response.get_json()
    db.session.commit()
    return jsonify(approval=display(row), result=response.get_json())


@bp.post("/refresh")
def refresh():
    """Discover review-state documents in bounded SQL batches and refresh routing."""
    ready()
    lock()
    from sqlalchemy import cast, String, exists
    from . import trade_store as trade, hr_store as hr
    from .trade_api import visibility

    state = app_document().stored_data
    added = 0
    blocked = 0

    def unseen(resource, model):
        return ~exists(
            select(ApprovalRequest.id).where(
                ApprovalRequest.resource == resource,
                ApprovalRequest.target == cast(model.id, String),
                (
                    or_(
                        ApprovalRequest.status == "Pending",
                        (ApprovalRequest.status == "Rejected")
                        & (ApprovalRequest.source_version == model.record_version),
                    )
                    if hasattr(model, "record_version")
                    else ApprovalRequest.status.in_(("Pending", "Rejected"))
                ),
            )
        )

    def enqueue(endpoint, args, payload):
        nonlocal added, blocked
        try:
            desc = descriptor(endpoint, args, payload)
            if not desc:
                return
            desc["payload"] = payload
            queue(desc, payload, desc["owner"])
            added += 1
        except Exception as error:
            from werkzeug.exceptions import HTTPException

            if isinstance(error, HTTPException) and error.code in (403, 404, 409):
                blocked += 1
            else:
                raise

    for key in (
        "requests",
        "orders",
        "salesQuotations",
        "invoices",
        "customerInvoices",
    ):
        if not allowed(g.user, state, COLLECTIONS[key]):
            continue
        model = trade.MODELS[key]
        for row in db.session.scalars(
            select(model)
            .where(
                model.status == "Pending Approval", visibility(key), unseen(key, model)
            )
            .order_by(model.id)
            .limit(100)
        ):
            action = "post" if key in ("invoices", "customerInvoices") else "approve"
            enqueue(
                "trade.command",
                dict(key=key, identity=str(row.id), action=action),
                dict(
                    version=row.record_version,
                    requestKey="approval-discover-"
                    + version([key, row.id, row.record_version, action]),
                ),
            )
    from .expense_api import scope as expense_scope, record as expense_record
    from .erp import Expense, ManufacturingOrder, JournalEntry

    if allowed(g.user, state, "expenses"):
        for row in db.session.scalars(
            select(Expense)
            .where(
                Expense.status == "Submitted",
                expense_scope(),
                unseen("expenses", Expense),
            )
            .order_by(Expense.id)
            .limit(100)
        ):
            v = expense_record(row)["version"]
            enqueue(
                "expenses.command",
                dict(action="approve"),
                dict(
                    id=row.id,
                    version=v,
                    requestKey="approval-discover-" + version(["expense", row.id, v]),
                ),
            )
    from .hr_api import visibility as hr_visibility, output as hr_output

    for key, status in (
        ("manpower", "Pending"),
        ("leaves", "Pending"),
        ("payroll", "Draft"),
        ("separations", "Requested"),
    ):
        if not allowed(g.user, state, HR_COLLECTIONS[key]):
            continue
        model = hr.MODELS[key]
        resource = "hr:" + key
        for row in db.session.scalars(
            select(model)
            .where(model.status == status, hr_visibility(key), unseen(resource, model))
            .order_by(model.id)
            .limit(100)
        ):
            v = hr_output(key, row)["version"]
            enqueue(
                "hr_resources.command",
                dict(key=key, identity=str(row.id), action="approve"),
                dict(
                    version=v,
                    requestKey="approval-discover-" + version([resource, row.id, v]),
                ),
            )
    from .production_api import order_record

    if allowed(g.user, state, "manufacturing"):
        for row in db.session.scalars(
            select(ManufacturingOrder)
            .where(
                ManufacturingOrder.state == "Draft",
                unseen("manufacturing", ManufacturingOrder),
            )
            .order_by(ManufacturingOrder.id)
            .limit(100)
        ):
            v = order_record(row)["version"]
            enqueue(
                "production.command",
                dict(command="confirm"),
                dict(
                    id=row.id,
                    version=v,
                    requestKey="approval-discover-" + version(["mo", row.id, v]),
                ),
            )
    from .credit_api import CreditNote, record as credit_record, get as credit_get

    if allowed(g.user, state, "accounting"):
        for row in db.session.scalars(
            select(CreditNote)
            .where(CreditNote.status == "Pending Review", unseen("credits", CreditNote))
            .order_by(CreditNote.id)
            .limit(100)
        ):
            # Credit source scopes remain mandatory even during discovery.
            try:
                credit_get(row.id)
            except Exception as error:
                from werkzeug.exceptions import HTTPException

                if isinstance(error, HTTPException):
                    continue
                raise
            v = credit_record(row)["version"]
            enqueue(
                "credits.command",
                dict(command="post"),
                dict(
                    id=row.id,
                    version=v,
                    requestKey="approval-discover-" + version(["credit", row.id, v]),
                ),
            )
        from .finance_api import entry_record

        for row in db.session.scalars(
            select(JournalEntry)
            .where(
                JournalEntry.status == "Draft",
                JournalEntry.source.like("manual:%"),
                unseen("accounting", JournalEntry),
            )
            .order_by(JournalEntry.id)
            .limit(100)
        ):
            v = entry_record(row)["version"]
            enqueue(
                "finance.command",
                dict(command="post"),
                dict(
                    id=row.id,
                    version=v,
                    requestKey="approval-discover-" + version(["journal", row.id, v]),
                ),
            )
    reroute_pending()
    db.session.commit()
    return jsonify(discovered=added, blocked=blocked, batchLimit=100)


def reroute_pending():
    condition = (
        True
        if g.user.role == "Admin"
        else or_(
            ApprovalRequest.submitted_by == g.user.id,
            ApprovalRequest.assigned_to == g.user.id,
        )
    )
    for row in db.session.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.status == "Pending", condition)
        .order_by(ApprovalRequest.last_routed, ApprovalRequest.id)
        .limit(100)
    ):
        row.last_routed = time.time()
        try:
            desc = row_desc(row)
            assigned = (
                db.session.get(User, row.assigned_to) if row.assigned_to else None
            )
            if not can_review(assigned, desc, row.submitted_by):
                row.assigned_to = route(desc, row.submitted_by)
        except Exception as error:
            from werkzeug.exceptions import HTTPException

            if isinstance(error, HTTPException):
                row.assigned_to = None
            else:
                raise
    db.session.flush()


def rejection_command(row):
    if row.mode != "record":
        return None
    args = deepcopy(row.arguments)
    operation = None
    if row.endpoint == "trade.command":
        key = args["key"]
        if args.get("action") == "approve":
            operation = (
                "cancel"
                if key == "orders"
                else "reject" if key in ("requests", "salesQuotations") else None
            )
        elif args.get("action") in ("post", "approve") and key in (
            "invoices",
            "customerInvoices",
        ):
            operation = "reset"
        if operation:
            args["action"] = operation
    elif row.endpoint == "expenses.command" and args.get("action") == "approve":
        operation = "reject"
        args["action"] = operation
    elif row.endpoint == "hr_resources.command" and args.get("action") == "approve":
        from .hr_api import TRANSITIONS

        if "reject" in TRANSITIONS.get(args["key"], {}):
            operation = "reject"
            args["action"] = operation
    elif row.endpoint == "credits.command" and args.get("command") == "post":
        operation = "reset"
        args["command"] = operation
    elif row.endpoint == "production.command" and args.get("command") == "confirm":
        operation = "cancel"
        args["command"] = operation
    if not operation:
        return None
    payload = {
        key: value for key, value in row.payload.items() if key in ("id", "version")
    }
    payload["requestKey"] = "approval-reject-" + str(row.id)
    return row.endpoint, args, payload


def sensitive(value):
    if isinstance(value, dict):
        return any(
            any(word in key.lower() for word in ("password", "secret", "token", "csrf"))
            or sensitive(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(sensitive(item) for item in value)
    return False


def inbox_scope():
    if g.user.role == "Admin":
        return True
    from sqlalchemy import cast, String, and_
    from . import trade_store as trade, hr_store as hr
    from .trade_api import visibility
    from .hr_api import visibility as hr_visibility
    from .expense_api import scope
    from .erp import Expense
    from .credit_api import CreditNote

    state = app_document().stored_data
    conditions = []
    for key, model in trade.MODELS.items():
        if not allowed(g.user, state, COLLECTIONS[key]):
            continue
        if key in ("payments", "customerPayments"):
            parent = "invoices" if key == "payments" else "customerInvoices"
            if not allowed(g.user, state, COLLECTIONS[parent]):
                continue
            source = trade.MODELS[parent]
            conditions.append(
                and_(
                    ApprovalRequest.resource == key,
                    ApprovalRequest.target.in_(
                        select(source.id).where(visibility(parent))
                    ),
                )
            )
        else:
            conditions.append(
                and_(
                    ApprovalRequest.resource == key,
                    ApprovalRequest.target.in_(select(model.id).where(visibility(key))),
                )
            )
    for key, model in hr.MODELS.items():
        if allowed(g.user, state, HR_COLLECTIONS[key]):
            conditions.append(
                and_(
                    ApprovalRequest.resource == "hr:" + key,
                    ApprovalRequest.target.in_(
                        select(model.id).where(hr_visibility(key))
                    ),
                )
            )
    if allowed(g.user, state, "expenses"):
        conditions.append(
            and_(
                ApprovalRequest.resource == "expenses",
                ApprovalRequest.target.in_(
                    select(cast(Expense.id, String)).where(scope())
                ),
            )
        )
    for resource, module in (
        ("inventory", "inventory"),
        ("warehouse", "inventory"),
        ("manufacturing", "manufacturing"),
        ("accounting", "accounting"),
    ):
        if allowed(g.user, state, module):
            conditions.append(ApprovalRequest.resource == resource)
    if allowed(g.user, state, "accounting"):
        for kind, key in (("customer", "customerInvoices"), ("vendor", "invoices")):
            if allowed(g.user, state, COLLECTIONS[key]):
                model = trade.MODELS[key]
                conditions.append(
                    and_(
                        ApprovalRequest.resource == "credits",
                        ApprovalRequest.target.in_(
                            select(cast(CreditNote.id, String)).where(
                                CreditNote.kind == kind,
                                CreditNote.invoice_id.in_(
                                    select(model.id).where(visibility(key))
                                ),
                            )
                        ),
                    )
                )
    return or_(
        and_(ApprovalRequest.submitted_by == g.user.id, or_(*conditions)),
        and_(
            ApprovalRequest.assigned_to == g.user.id,
            ApprovalRequest.module.in_(
                [
                    module
                    for module in state.get("roles", {})
                    .get(g.user.role, {})
                    .get("permissions", {})
                    if allowed(g.user, state, module, "approve")
                ]
            ),
            ApprovalRequest.amount <= cap(g.user) if cap(g.user) is not None else False,
            or_(*conditions),
        ),
    )


def controlled(endpoint, args):
    """Leave draft editing and approved-order fulfillment on their resource-lock paths."""
    if endpoint == "trade.command":
        return (
            not args.get("identity")
            and args.get("key") in ("payments", "customerPayments")
        ) or args.get("action") in (
            "approve",
            "post",
            "close",
            "award",
            "clear",
            "reject",
            "reset",
        )
    if endpoint == "hr_resources.command":
        return args.get("action") in (
            "approve",
            "pay",
            "select",
            "offer",
            "reject",
            "complete",
        )
    if endpoint == "expenses.command":
        return args.get("action") in ("approve", "reject", "pay")
    if endpoint == "inventory_resources.command":
        return args.get("command") in ("adjust", "scrap", "return")
    if endpoint == "production.command":
        return args.get("command") in (
            "confirm",
            "stage",
            "start",
            "complete",
            "cancel",
        )
    if endpoint == "finance.command":
        return args.get("command") in (
            "post",
            "reverse",
            "transfer",
            "reconcile",
            "match-bank",
            "period-lock",
        )
    if endpoint == "credits.command":
        return args.get("command") in ("post", "refund", "apply")
    return endpoint == "warehouse.command" and args.get("command") == "transfer"


def review_snapshot(source, payload):
    """Store human-readable supporting facts separately from immutable command inputs."""
    from .erp import ERPProduct

    def clean(value):
        if isinstance(value, list):
            return [clean(v) for v in value]
        if not isinstance(value, dict):
            return value
        result = {
            key: clean(item)
            for key, item in value.items()
            if key
            not in (
                "id",
                "requestKey",
                "version",
                "parentVersion",
                "moveId",
                "invoiceId",
                "productId",
                "lineIndex",
                "returnId",
            )
        }
        if value.get("productId") is not None:
            product = db.session.get(ERPProduct, str(value["productId"]))
            if product:
                result.update(product=product.name, sku=product.sku)
        return result

    return clean({**deepcopy(source), **deepcopy(payload)})
