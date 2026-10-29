"""Versioned HR workflows. All postings and offboarding share one SQL transaction."""

from copy import deepcopy
from datetime import date
import re
import secrets
from flask import (
    Blueprint,
    g,
    jsonify,
    request,
    render_template_string,
    make_response,
    current_app,
)
from sqlalchemy import select, or_, func, update
from werkzeug.security import generate_password_hash, check_password_hash
from .app import (
    db,
    Document,
    User,
    body,
    app_document,
    problem,
    audit,
    utcnow,
    validate_json,
    check_password,
)
from .permissions import HR_COLLECTIONS, allowed
from .erp import lock, sync_business
from .trade_service import number, text, on_date
from . import hr_store as store

bp = Blueprint("hr_resources", __name__, url_prefix="/api/hr")
FIELDS = {
    "employees": {
        "employeeId",
        "name",
        "department",
        "designation",
        "manager",
        "joiningDate",
        "salary",
        "email",
        "candidateId",
    },
    "manpower": {
        "department",
        "position",
        "requestType",
        "count",
        "reason",
        "requestedBy",
    },
    "candidates": {"name", "position", "contact", "manpowerId"},
    "attendance": {"employeeKey", "date", "attendanceStatus"},
    "leaves": {"employeeKey", "leaveType", "from", "to", "reason"},
    "payroll": {"employeeKey", "month", "basic", "allowances", "deductions"},
    "separations": {"employeeKey", "lastWorkingDate", "reason", "finalSettlement"},
}
TRANSITIONS = {
    "manpower": {"approve": ("Pending", "Approved"), "reject": ("Pending", "Rejected")},
    "candidates": {
        "shortlist": ("Applied", "Shortlisted"),
        "interview": ("Shortlisted", "Interview Scheduled"),
        "select": ("Interview Scheduled", "Selected"),
        "offer": ("Selected", "Offer Issued"),
        "reject": (
            (
                "Applied",
                "Shortlisted",
                "Interview Scheduled",
                "Selected",
                "Offer Issued",
            ),
            "Rejected",
        ),
    },
    "leaves": {
        "approve": ("Pending", "Approved"),
        "reject": ("Pending", "Rejected"),
        "cancel": ("Pending", "Cancelled"),
    },
    "payroll": {"approve": ("Draft", "Approved"), "pay": ("Approved", "Paid")},
    "separations": {
        "approve": ("Requested", "Approved"),
        "reject": ("Requested", "Rejected"),
        "complete": ("Approved", "Completed"),
    },
}


class Command(db.Model):
    __tablename__ = "hr_command"
    actor_id = db.Column(db.String(64), primary_key=True)
    request_key = db.Column(db.String(100), primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    resource = db.Column(db.String(30), nullable=False)
    identity = db.Column(db.String(64), nullable=False)


def permit(key, action="view"):
    if key not in store.MODELS:
        problem("Unknown HR register", 404)
    if not allowed(g.user, app_document().stored_data, HR_COLLECTIONS[key], action):
        problem("HR permission denied: " + action, 403)


def require_migrated():
    doc = db.session.get(Document, "hr")
    if not doc or not doc.stored_data.get(store.MARKER):
        problem("Run flask --app backend.app migrate-storage before opening HR", 503)
    return doc


def visibility(key):
    from .scope import hr_access

    if hr_access(g.user, app_document().stored_data):
        return True
    actors = select(User.id).where(
        or_(User.id == g.user.id, User.manager_id == g.user.id)
    )
    model = store.MODELS[key]
    if key in ("manpower", "candidates"):
        return model.created_by.in_(actors)
    if key == "employees":
        return model.linked_user_id.in_(actors)
    return model.employee_id.in_(
        select(store.Employee.id).where(store.Employee.linked_user_id.in_(actors))
    )


def scoped(key, identity):
    permit(key)
    require_migrated()
    model = store.MODELS[key]
    row = db.session.scalar(
        select(model).where(model.id == str(identity), visibility(key))
    )
    if row is None:
        problem("HR record not found", 404)
    return row


def action_permission(key, action):
    if action == "login":
        return "edit"
    return "edit" if action in ("cancel", "shortlist", "interview") else "approve"


def editable(key, value):
    return (
        stage(key, value)
        in {
            "employees": ("Active",),
            "manpower": ("Pending",),
            "candidates": ("Applied", "Shortlisted", "Interview Scheduled"),
            "attendance": ("Recorded",),
            "leaves": ("Pending",),
            "payroll": ("Draft",),
            "separations": ("Requested",),
        }[key]
    )


def actions(key, value):
    state = app_document().stored_data
    result = []
    if editable(key, value) and allowed(g.user, state, HR_COLLECTIONS[key], "edit"):
        result.append("edit")
    for action, (origins, target) in TRANSITIONS.get(key, {}).items():
        if isinstance(origins, str):
            origins = (origins,)
        if stage(key, value) in origins and allowed(
            g.user, state, HR_COLLECTIONS[key], action_permission(key, action)
        ):
            result.append(action)
    if (
        key == "employees"
        and value.get("status") == "Active"
        and not value.get("linkedUserId")
        and g.user.role == "Admin"
    ):
        result.append("login")
    return result


def output(key, row):
    value = store.record(key, row)
    return {**value, "version": row.record_version, "actions": actions(key, value)}


def paging():
    try:
        page = int(request.args.get("page", 1))
        size = int(request.args.get("pageSize", 25))
    except ValueError:
        problem("Pagination must use integers")
    if page < 1 or not 1 <= size <= 100:
        problem("pageSize must be 1–100")
    return page, size


def query_for(key):
    permit(key)
    require_migrated()
    model = store.MODELS[key]
    query = select(model).where(visibility(key))
    search = request.args.get("search", "").strip().casefold()
    if len(search) > 160:
        problem("Search is too long")
    if search:
        query = query.where(
            model.search_text.like(
                "%"
                + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%",
                escape="\\",
            )
        )
    if request.args.get("status"):
        statuses = request.args["status"].split("|")
        if len(statuses) > 12 or any(len(s) > 80 for s in statuses):
            problem("Invalid status filter")
        query = query.where(
            or_(model.status.in_(statuses), model.stage.in_(statuses))
            if key == "candidates"
            else model.status.in_(statuses)
        )
    if request.args.get("employeeKey") and hasattr(model, "employee_id"):
        query = query.where(model.employee_id == request.args["employeeKey"])
    return query


@bp.get("/records/<key>")
def listing(key):
    query = query_for(key)
    page, size = paging()
    model = store.MODELS[key]
    total = db.session.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.session.scalars(
        query.order_by(model.position, model.id).offset((page - 1) * size).limit(size)
    )
    return jsonify(
        items=[output(key, r) for r in rows], total=total, page=page, pageSize=size
    )


@bp.get("/records/<key>/<identity>")
def details(key, identity):
    return jsonify(record=output(key, scoped(key, identity)))


@bp.get("/employee-options/<key>")
def employee_options(key):
    # Limited non-salary selector for authorized HR transactions; no employee-view grant needed.
    permit(key)
    require_migrated()
    page, size = paging()
    if key not in ("attendance", "leaves", "payroll", "separations"):
        problem("No employee selector for this register", 404)
    model = store.Employee
    query = select(model).where(model.status == "Active", visibility("employees"))
    term = request.args.get("search", "").strip().casefold()
    if len(term) > 160:
        problem("Search too long")
    if term:
        query = query.where(
            (
                func.lower(
                    func.coalesce(model.number, "")
                    + " "
                    + func.coalesce(model.name, "")
                )
            ).like(
                "%"
                + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%",
                escape="\\",
            )
        )
    rows = db.session.scalars(
        query.order_by(model.name, model.id).offset((page - 1) * size).limit(size)
    )
    items = []
    for row in rows:
        value = store.record("employees", row)
        item = dict(
            id=value["id"],
            name=str(value.get("employeeId", "")) + " - " + str(value.get("name", "")),
        )
        if key == "payroll":
            item["salary"] = value.get("salary", 0)
        items.append(item)
    return jsonify(items=items)


def find(state, key, identity):
    row = next((r for r in state.get(key, []) if str(r["id"]) == str(identity)), None)
    if row is None:
        problem("Referenced HR record not found", 404)
    return row


def employee_for(state, row):
    matches = [
        e
        for e in state["employees"]
        if (row.get("employeeKey") and str(e["id"]) == str(row["employeeKey"]))
        or (
            not row.get("employeeKey")
            and str(e.get("employeeId", "")) + " - " + str(e.get("name", ""))
            == row.get("employee")
        )
    ]
    if len(matches) != 1:
        problem("Employee reference needs review before this action", 409)
    return matches[0]


def stage(key, value):
    return (
        value.get("stage", value.get("status"))
        if key == "candidates"
        else value.get("status")
    )


def normalize(key, data, row, state, creating):
    permitted = (
        FIELDS[key]
        if creating
        else FIELDS[key] - {"employeeKey", "candidateId", "manpowerId"}
    )
    if set(data) - permitted - {"requestKey", "version"}:
        problem("Unknown or immutable HR fields")
    for field in permitted:
        if field not in data:
            continue
        if field in ("salary", "basic", "allowances", "deductions", "finalSettlement"):
            row[field] = float(number(data.get(field, 0), field))
        elif field in ("joiningDate", "date", "from", "to", "lastWorkingDate"):
            row[field] = on_date(data, field, required=True)
        elif field == "count":
            value = number(data.get(field, 0), field)
            if data.get(field) != int(value) or not 1 <= value <= 10000:
                problem("Headcount must be an integer from 1 to 10000")
            row[field] = int(value)
        elif field in ("employeeKey", "manpowerId", "candidateId"):
            item = data[field]
            if (
                not isinstance(item, (str, int))
                or isinstance(item, bool)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(item))
            ):
                problem("Invalid HR reference")
            row[field] = item
        else:
            row[field] = text(
                data,
                field,
                limit=(
                    4000
                    if field == "reason"
                    else (
                        80
                        if field == "employeeId"
                        else (
                            160
                            if field
                            in (
                                "name",
                                "department",
                                "designation",
                                "manager",
                                "position",
                                "requestedBy",
                            )
                            else 254
                        )
                    )
                ),
            )
    required = {
        "employees": ("employeeId", "name", "department", "designation", "joiningDate"),
        "manpower": ("department", "position", "count", "reason", "requestedBy"),
        "candidates": ("name", "position", "contact"),
        "attendance": ("date", "attendanceStatus"),
        "leaves": ("from", "to", "reason", "leaveType"),
        "payroll": ("month",),
        "separations": ("lastWorkingDate", "reason"),
    }[key]
    if any(not row.get(f) for f in required):
        problem("Complete all required HR fields")
    if key in ("attendance", "leaves", "payroll", "separations"):
        if not row.get("employeeKey") and not creating:
            row["employeeKey"] = employee_for(state, row)["id"]
        employee = (
            scoped("employees", row.get("employeeKey"))
            if allowed(g.user, app_document().stored_data, "hr_employees")
            else None
        )
        if employee is None:
            employee = db.session.scalar(
                select(store.Employee).where(
                    store.Employee.id == str(row.get("employeeKey")),
                    visibility("employees"),
                )
            )
        if employee is None:
            problem("Employee not found", 404)
        emp = find(state, "employees", employee.id)
        if emp.get("status") != "Active":
            problem("Choose an active employee")
        row["employeeKey"] = emp["id"]
        row["employee"] = (
            str(emp.get("employeeId", "")) + " - " + str(emp.get("name", ""))
        )
    if key == "employees":
        if any(
            str(e.get("employeeId", "")).casefold() == row["employeeId"].casefold()
            and str(e["id"]) != str(row["id"])
            for e in state["employees"]
        ):
            problem("Employee ID is already assigned", 409)
    if key == "attendance" and row["attendanceStatus"] not in (
        "Present",
        "Absent",
        "Late",
        "Half Day",
        "Work From Home",
    ):
        problem("Invalid attendance status")
    if key == "manpower" and row.get("requestType", "New Position") not in (
        "New Position",
        "Replacement",
    ):
        problem("Invalid request type")
    if key == "leaves":
        if row["leaveType"] not in ("Annual", "Sick", "Casual", "Unpaid"):
            problem("Invalid leave type")
        start = date.fromisoformat(on_date(row, "from"))
        end = date.fromisoformat(on_date(row, "to"))
        if end < start:
            problem("Leave end must follow its start")
        row["days"] = (end - start).days + 1
    if key == "payroll":
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", row["month"]):
            problem("Payroll month must be YYYY-MM")
        try:
            date.fromisoformat(row["month"] + "-01")
        except ValueError:
            problem("Enter a valid payroll month")
        for f in ("basic", "allowances", "deductions"):
            row.setdefault(f, 0)
        from decimal import Decimal

        gross = Decimal(str(row["basic"])) + Decimal(str(row["allowances"]))
        net = gross - Decimal(str(row["deductions"]))
        if gross <= 0 or net < 0:
            problem("Positive gross pay is required; deductions cannot exceed gross")
        row["netPay"] = float(net)
    if key == "candidates" and row.get("manpowerId"):
        req = scoped("manpower", row["manpowerId"])
        if req.status != "Approved":
            problem("Recruitment requires an approved manpower request")


def validate_state(state):
    def employee_identity(row):
        if row.get("employeeKey"):
            return str(row["employeeKey"])
        match = next(
            (
                e
                for e in state["employees"]
                if str(e.get("employeeId", "")) + " - " + str(e.get("name", ""))
                == row.get("employee")
            ),
            None,
        )
        return str(match["id"]) if match else str(row.get("employee"))

    for key, period in [("attendance", "date"), ("payroll", "month")]:
        seen = set()
        for r in state[key]:
            identity = (employee_identity(r), r.get(period))
            if identity in seen:
                problem("Duplicate " + key + " for employee and period", 409)
            seen.add(identity)
    leaves = [
        r for r in state["leaves"] if r.get("status") not in ("Rejected", "Cancelled")
    ]
    for i, r in enumerate(leaves):
        for other in leaves[i + 1 :]:
            if (
                employee_identity(r) == employee_identity(other)
                and r.get("from", "") <= other.get("to", "")
                and r.get("to", "") >= other.get("from", "")
            ):
                problem("Leave periods overlap", 409)
    for r in state["separations"]:
        if r.get("status") in ("Completed", "Rejected"):
            continue
        if (
            sum(
                employee_identity(o) == employee_identity(r)
                and o.get("status") not in ("Completed", "Rejected")
                for o in state["separations"]
            )
            > 1
        ):
            problem("An open separation already exists", 409)


@bp.post("/records/<key>")
@bp.patch("/records/<key>/<identity>")
@bp.post("/records/<key>/<identity>/actions/<action>")
def command(key, identity=None, action=None):
    permit(key)
    data = body()
    if action != "login":
        validate_json(data)
    request_key = data.get("requestKey", "")
    if not isinstance(request_key, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{8,100}", request_key
    ):
        problem("A unique requestKey is required")
    permission = (
        "create"
        if identity is None
        else action_permission(key, action) if action else "edit"
    )
    permit(key, permission)
    if action == "login" and g.user.role != "Admin":
        problem("Only administrators create login accounts", 403)
    # Never persist a password or its deterministic fingerprint in domain metadata/receipts.
    fingerprint = store.version(
        dict(
            key=key,
            identity=identity,
            action=action,
            data={
                k: v
                for k, v in data.items()
                if k not in ("version", "requestKey", "password")
            },
        )
    )
    resource_path = False
    if (
        key in ("manpower", "candidates", "attendance", "leaves", "payroll")
        and current_app.config["HR_RESOURCE_LOCKING"]
    ):
        from .db_contention import acquire_resource
        from .hr_context import resource_references

        resource_path = acquire_resource(
            store.MODELS[key],
            identity,
            request_key,
            lambda target: resource_references(key, target, data, identity is None),
        )
    else:
        lock()
    from .workflow_keys import revalidate_actor

    revalidate_actor()
    permit(key)
    permit(key, permission)
    if action == "login" and g.user.role != "Admin":
        problem("Only administrators create login accounts", 403)
    doc = require_migrated()
    db.session.refresh(doc)
    from .hr_context import Context

    context = Context(key, identity, data)
    original = context.original
    state = context.state
    row = find(state, key, identity) if identity is not None else None
    if identity is not None and row is None:
        problem("HR record not found", 404)
    if row is not None:
        scoped(key, identity)
    receipt = db.session.get(Command, (g.user.id, request_key))
    if receipt:
        if receipt.fingerprint != fingerprint:
            problem("Request key has already been used", 409)
        replay = scoped(key, receipt.identity)
        if action == "login":
            check_password(data.get("password"))
            account = (
                db.session.get(User, replay.linked_user_id)
                if replay.linked_user_id
                else None
            )
            if not account or not check_password_hash(
                account.password_hash, data["password"]
            ):
                problem("Credential changed; use a new request key", 409)
        return jsonify(record=output(key, replay))
    if row is not None:
        if not data.get("version"):
            problem("Record version is required", 428)
        if data["version"] != store.version(row):
            problem("Record changed. Reload before saving.", 409)
    if identity is None:
        row = dict(
            id="hr-" + secrets.token_hex(12),
            createdBy=g.user.id,
            createdAt=utcnow(),
            workflowVersion=1,
        )
        row["status"] = {
            "employees": "Active",
            "manpower": "Pending",
            "candidates": "Applied",
            "attendance": "Recorded",
            "leaves": "Pending",
            "payroll": "Draft",
            "separations": "Requested",
        }[key]
        if key == "candidates":
            row["stage"] = "Applied"
        normalize(key, data, row, state, True)
        if key == "employees" and row.get("candidateId"):
            permit("candidates", "approve")
            candidate = scoped("candidates", row["candidateId"])
            value = find(state, "candidates", candidate.id)
            if stage("candidates", value) != "Offer Issued":
                problem("Issue an offer before onboarding")
            if any(
                str(e.get("candidateId")) == str(candidate.id)
                for e in state["employees"]
            ):
                problem("Candidate is already onboarded", 409)
            value.update(status="Hired", stage="Hired", employeeKey=row["id"])
        state[key].insert(0, row)
    elif action == "login":
        if (
            key != "employees"
            or row.get("linkedUserId")
            or row.get("status") != "Active"
        ):
            problem("An active unlinked employee is required")
        if set(data) - {"requestKey", "version", "email", "role", "password"}:
            problem("Unknown account fields")
        email = text(data, "email", required=True).lower()
        role = text(data, "role", required=True)
        password = data.get("password")
        check_password(password)
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            problem("Enter a valid login email")
        if role not in app_document().stored_data["roles"]:
            problem("Unknown system role")
        if db.session.scalar(select(User).where(User.email == email)):
            problem("Login email already exists", 409)
        user = User(
            id="user-" + secrets.token_hex(12),
            name=row["name"],
            email=email,
            role=role,
            active=True,
            password_hash=generate_password_hash(password),
        )
        db.session.add(user)
        db.session.flush()
        row.update(linkedUserId=user.id, loginEmail=email, accountStatus="Active")
    elif action:
        if set(data) - {"version", "requestKey"}:
            problem("Action does not accept editable fields")
        transition = TRANSITIONS.get(key, {}).get(action)
        if not transition:
            problem("Unknown HR action", 404)
        origins, target = transition
        if isinstance(origins, str):
            origins = (origins,)
        if stage(key, row) not in origins:
            problem("Action is unavailable in this status", 409)
        if key in ("payroll", "separations"):
            employee = employee_for(state, row)
            if (
                key == "payroll"
                and action == "approve"
                and employee.get("status") != "Active"
            ):
                problem("Cannot approve payroll for a separated employee")
            if key == "separations" and action == "complete":
                employee.update(
                    status="Separated",
                    separationDate=row["lastWorkingDate"],
                    accountStatus=(
                        "Disabled" if employee.get("linkedUserId") else "No login"
                    ),
                )
        row.update(status=target, updatedAt=utcnow())
        row[action + "At"] = utcnow()
        row[action + "By"] = g.user.id
        if key == "candidates":
            row["stage"] = target
    else:
        if not editable(key, row):
            problem("Only editable HR records may change", 409)
        normalize(key, data, row, state, False)
    # Live leave actions must retain the date validation previously performed by
    # the global economic adapter. Reject/cancel remain available for bad history.
    if key == "leaves" and row.get("status") not in ("Rejected", "Cancelled"):
        if action == "approve":
            employee_for(state, row)
        start = on_date(row, "from")
        end = on_date(row, "to")
        if end < start:
            problem("Leave end must follow its start")
    validate_state(state)
    context.validate()
    context.persist()
    if resource_path and key == "payroll":
        from .erp import sync_payroll

        if row.get("status") in ("Approved", "Paid"):
            from .db_contention import acquire_payroll_posting

            acquire_payroll_posting()
        # Post before the shared HR metadata update: all financial resource writes
        # take the posting mutex first, then the brief HR revision-row lock.
        sync_payroll(original, state)
    revision_update = update(Document).where(Document.name == "hr")
    if resource_path:
        # A brief metadata-row update preserves legacy revision semantics without
        # holding the global exclusive lock throughout independent record work.
        revision_update = revision_update.values(revision=Document.revision + 1)
    else:
        revision_update = revision_update.where(
            Document.revision == doc.revision
        ).values(revision=doc.revision + 1)
    result = db.session.execute(
        revision_update.execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        problem("Another user saved newer records", 409)
    if not resource_path:
        sync_business(original, state, "hr")
    # Manpower, candidate, attendance and leave commands have no economic/account effects.
    # Calling the legacy economic adapter here would upgrade the shared gate and
    # reintroduce global serialization (or a lock-upgrade deadlock).
    db.session.add(
        Command(
            actor_id=g.user.id,
            request_key=request_key,
            fingerprint=fingerprint,
            resource=key,
            identity=str(row["id"]),
        )
    )
    audit(
        "HR " + (action or ("create" if identity is None else "edit")),
        dict(resource=key, recordId=row["id"]),
    )
    db.session.commit()
    return jsonify(record=output(key, scoped(key, row["id"])))


@bp.get("/summary")
def summary():
    require_migrated()
    state = app_document().stored_data
    if not any(allowed(g.user, state, m) for m in HR_COLLECTIONS.values()):
        problem("No HR access", 403)
    result = []
    for key, model in store.MODELS.items():
        if not allowed(g.user, state, HR_COLLECTIONS[key]):
            continue
        groups = db.session.execute(
            select(model.status, func.count())
            .where(visibility(key))
            .group_by(model.status)
        ).all()
        result.append(
            dict(
                key=key,
                count=sum(n for _, n in groups),
                statuses={s or "Unspecified": n for s, n in groups},
            )
        )
    paid = 0
    if allowed(g.user, state, "hr_payroll"):
        paid = float(
            db.session.scalar(
                select(func.coalesce(func.sum(store.Payroll.net_pay), 0)).where(
                    visibility("payroll"), store.Payroll.status == "Paid"
                )
            )
            or 0
        )
    return jsonify(registers=result, paidPayroll=paid, currency="PKR")


@bp.get("/records/payroll/<identity>/print")
def payslip(identity):
    permit("payroll", "export")
    row = scoped("payroll", identity)
    value = store.record("payroll", row)
    if value.get("status") not in ("Approved", "Paid"):
        problem("Approve payroll before printing a payslip", 409)
    response = make_response(
        render_template_string(
            """<!doctype html><html lang="en"><meta charset="utf-8"><title>Payslip — {{r.month}}</title><style>body{font:16px Arial;margin:40px;color:#172338}table{border-collapse:collapse;width:100%;max-width:700px}th,td{padding:14px;text-align:left;border-bottom:1px solid #ddd}@media print{button{display:none}}</style><h1>{{company.get('name','Company')}}</h1><h2>Salary Payslip · PKR</h2><p>{{r.employee}} · {{r.month}} · {{r.status}}</p><table>{% for field,label in [('basic','Basic salary'),('allowances','Allowances'),('deductions','Deductions'),('netPay','Net pay')] %}<tr><th>{{label}}</th><td>{{'%.2f'|format(r.get(field,0))}}</td></tr>{% endfor %}</table><p>Payment recorded: {{r.get('payAt',r.get('paidAt','Pending'))}}</p><p>This record does not initiate a bank transfer.</p><button onclick="window.print()">Print / Save as PDF</button></html>""",
            r=value,
            company=app_document().stored_data.get("company", {}),
        )
    )
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


@bp.get("/records/<key>/export")
def export(key):
    import csv, io

    permit(key, "export")
    query = query_for(key)
    page, size = paging()
    if key not in ("attendance", "payroll"):
        problem("Export unavailable", 404)
    fields = (
        ["employee", "date", "attendanceStatus"]
        if key == "attendance"
        else [
            "employee",
            "month",
            "basic",
            "allowances",
            "deductions",
            "netPay",
            "status",
        ]
    )
    model = store.MODELS[key]
    rows = db.session.scalars(
        query.order_by(model.position, model.id).offset((page - 1) * size).limit(size)
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(fields)
    for row in rows:
        value = store.record(key, row)
        cells = []
        for field in fields:
            cell = str(value.get(field, ""))
            if cell.lstrip().startswith(("=", "+", "-", "@")):
                cell = "'" + cell
            cells.append(cell)
        writer.writerow(cells)
    response = make_response(buf.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="hr-{key}-page-{page}.csv"'
    )
    return response
