"""Customer SQL pagination and record-level writes with legacy order details."""

from copy import deepcopy
import json
import math
import re
from flask import Blueprint, g, jsonify, request
from .app import db, app_document, problem, digest
from .permissions import COLLECTIONS, HR_COLLECTIONS, allowed, in_scope
from .erp import dec

bp = Blueprint("customer_records", __name__, url_prefix="/api")
FIELDS = (
    "name",
    "contact",
    "phone",
    "email",
    "category",
    "paymentTerms",
    "creditLimit",
    "status",
    "address",
)


def permit(action):
    from .master_api import permit as master_permit

    master_permit("customers", action)


def version(record):
    return digest(json.dumps(record, sort_keys=True, separators=(",", ":")))


def output(record):
    result = {key: str(record.get(key) or "") for key in FIELDS if key != "creditLimit"}
    result.update(
        paymentTerms=result["paymentTerms"] or "Cash",
        status=result["status"] or "Active",
        creditLimit=record.get("creditLimit") or 0,
        id=record["id"],
        code=str(record.get("code") or ""),
        createdBy=record.get("createdBy"),
        version=version(record),
    )
    return result


def values(data, previous=None):
    if set(data) - set(FIELDS) - {"version", "requestKey"}:
        problem("Unknown customer fields")
    if previous:
        data = {**{key: previous[key] for key in FIELDS if key in previous}, **data}
    result = {}
    limits = {
        "name": 160,
        "contact": 160,
        "phone": 80,
        "email": 254,
        "category": 100,
        "address": 1000,
    }
    for key, limit in limits.items():
        value = data.get(key, "")
        if not isinstance(value, str) or len(value.strip()) > limit:
            problem("Invalid customer " + key)
        result[key] = value.strip()
    if not result["name"]:
        problem("Customer name is required")
    if result["email"] and not re.fullmatch(
        r"[^\s@]+@[^\s@]+\.[^\s@]+", result["email"]
    ):
        problem("Enter a valid email address")
    result["paymentTerms"] = data.get("paymentTerms", "Cash")
    result["status"] = data.get("status", "Active")
    if result["paymentTerms"] not in ("Cash", "15 Days", "30 Days", "45 Days"):
        problem("Invalid payment terms")
    if result["status"] not in ("Active", "Inactive"):
        problem("Invalid customer status")
    credit = data.get("creditLimit", 0)
    if (
        isinstance(credit, bool)
        or not isinstance(credit, (int, float))
        or not math.isfinite(credit)
        or not 0 <= credit <= 1e12
    ):
        problem("Credit limit must be a finite non-negative number")
    result["creditLimit"] = float(dec(credit))
    return result


@bp.get("/ui/bootstrap")
def bootstrap():
    state = app_document().stored_data
    # No business collections or employee/payroll data on the modern screen.
    compact = {key: [] for key in COLLECTIONS}
    compact.update(
        company=deepcopy(state.get("company", {})),
        roles=deepcopy(state["roles"]),
        users=[g.user.public()],
        activities=[],
    )
    return jsonify(
        user=g.user.public(),
        csrfToken=g.login_session.csrf,
        state=compact,
        hr={key: [] for key in HR_COLLECTIONS},
    )


@bp.get("/customers")
def customers():
    permit("view")
    try:
        page = int(request.args.get("page", "1"))
        size = int(request.args.get("pageSize", "25"))
    except ValueError:
        problem("Page and pageSize must be integers")
    if page < 1 or not 1 <= size <= 100:
        problem("Page must be positive; pageSize must be 1–100")
    search = request.args.get("search", "").strip().casefold()
    if len(search) > 160:
        problem("Search is too long")
    from .master_store import MARKER, page as sql_page

    if app_document().stored_data.get(MARKER):
        rows, total = sql_page("customers", page, size, search)
    else:
        problem(
            "Run flask --app backend.app migrate-storage before using this screen", 503
        )
    return jsonify(
        items=[output(r) for r in rows], total=total, page=page, pageSize=size
    )


@bp.get("/customers/<identity>")
def customer_details(identity):
    permit("view")
    from sqlalchemy import select, func
    from .master_store import Customer, record as master_record
    from .trade_store import MODELS
    from .trade_api import visibility

    customer = db.session.get(Customer, identity)
    if customer is None:
        problem("Customer not found", 404)
    state = app_document().stored_data
    total = 0
    orders = []
    if allowed(g.user, state, "sales_orders"):
        model = MODELS["salesOrders"]
        query = select(model).where(
            model.customer_id == identity, visibility("salesOrders")
        )
        total = db.session.scalar(select(func.count()).select_from(query.subquery()))
        for row in db.session.scalars(
            query.order_by(model.document_date.desc(), model.id.desc()).limit(25)
        ):
            orders.append(
                dict(
                    id=row.original_id,
                    orderNo=row.number,
                    orderDate=row.document_date,
                    total=float(row.total or 0),
                    status=row.status,
                )
            )
    return jsonify(
        customer=output(master_record("customers", customer)),
        orderTotal=total,
        orders=orders,
    )


@bp.route("/customers", methods=["POST"])
@bp.route("/customers/<identity>", methods=["PATCH"])
def save_customer(identity=None):
    from .master_api import save_record

    value, revision = save_record("customers", identity, values)
    return jsonify(customer=output(value), revision=revision)
