"""Native production resources over existing BoM/order/stock/ledger tables."""

from functools import wraps
from decimal import Decimal, localcontext, ROUND_HALF_UP
from flask import Blueprint, g, jsonify, request, make_response, render_template_string
from sqlalchemy import select, func, or_
import re
from .app import db, app_document, body, problem, audit, validate_json
from .permissions import allowed
from .erp import (
    ERPProduct,
    StockBalance,
    BillOfMaterials,
    BOMLine,
    ManufacturingOrder,
    ProductionComponent,
    dec,
    UNIT,
    day,
    lock,
    next_number,
    finish_manufacturing,
)
from .scope import remember
from .trade_store import version
from .trade_service import text
from .finance_api import paged, search_term

bp = Blueprint("production", __name__, url_prefix="/api/production")


class Command(db.Model):
    __tablename__ = "production_command"
    actor_id = db.Column(db.String(64), primary_key=True)
    request_key = db.Column(db.String(100), primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    resource = db.Column(db.String(20), nullable=False)
    identity = db.Column(db.Integer, nullable=False)


def permit(action="view"):
    if not allowed(g.user, app_document().stored_data, "manufacturing", action):
        problem("Manufacturing permission denied: " + action, 403)


def read(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        permit()
        return fn(*a, **kw)

    return wrapper


def get(model, identity):
    if (
        isinstance(identity, bool)
        or not isinstance(identity, (int, str))
        or not re.fullmatch(r"[1-9][0-9]{0,9}", str(identity))
        or int(identity) > 2147483647
    ):
        problem("Production record not found", 404)
    obj = db.session.get(model, int(identity))
    if obj is None:
        problem("Production record not found", 404)
    return obj


def stock(identity):
    if not isinstance(identity, (str, int)) or isinstance(identity, bool):
        problem("Select a stock product")
    p = db.session.get(ERPProduct, str(identity))
    if not p or p.kind != "stock":
        problem("Select a stock-tracked product")
    return p


def bom_record(b):
    p = db.session.get(ERPProduct, b.product_id)
    rows = db.session.execute(
        select(BOMLine, ERPProduct)
        .join(ERPProduct, BOMLine.product_id == ERPProduct.id)
        .where(BOMLine.bom_id == b.id)
        .order_by(BOMLine.id)
    ).all()
    value = dict(
        id=b.id,
        name=b.name,
        productId=b.product_id,
        product=p.name,
        sku=p.sku,
        quantity=str(b.output_quantity),
        conversionCost=str(b.conversion_cost),
        components=[
            dict(
                productId=l.product_id,
                product=p.name,
                sku=p.sku,
                unit=p.unit,
                quantity=str(l.quantity),
            )
            for l, p in rows
        ],
    )
    return {
        **value,
        "version": version(value),
        "actions": (
            ["edit"]
            if allowed(g.user, app_document().stored_data, "manufacturing", "edit")
            else []
        ),
    }


def order_record(o):
    p = db.session.get(ERPProduct, o.product_id)
    b = db.session.get(BillOfMaterials, o.bom_id)
    rows = db.session.execute(
        select(ProductionComponent, ERPProduct, StockBalance)
        .join(ERPProduct, ProductionComponent.product_id == ERPProduct.id)
        .outerjoin(StockBalance, StockBalance.product_id == ERPProduct.id)
        .where(ProductionComponent.order_id == o.id)
        .order_by(ProductionComponent.id)
    ).all()
    components = []
    snapshot = []
    estimate = Decimal(0)
    ready = True
    for line, product, balance in rows:
        qty = balance.quantity if balance else Decimal(0)
        value = balance.value if balance else Decimal(0)
        enough = qty >= line.quantity
        ready = ready and enough
        with localcontext() as context:
            context.prec = 60
            cost = (
                (value * line.quantity / qty).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if qty
                else Decimal(0)
            )
            estimate += cost
        components.append(
            dict(
                productId=line.product_id,
                product=product.name,
                sku=product.sku,
                unit=product.unit,
                quantity=str(line.quantity),
                available=str(qty),
                shortage=str(max(Decimal(0), line.quantity - qty)),
                estimatedCost=str(cost),
            )
        )
        snapshot.append(
            dict(productId=line.product_id, quantity=str(qty), value=str(value))
        )
    value = dict(
        id=o.id,
        number=o.number,
        bomId=o.bom_id,
        productId=o.product_id,
        product=p.name,
        sku=p.sku,
        quantity=str(o.quantity),
        conversionCost=str(o.conversion_cost),
        actualCost=str(o.actual_cost),
        state=o.state,
        date=o.date,
        components=[
            {
                k: v
                for k, v in c.items()
                if k not in ("available", "shortage", "estimatedCost")
            }
            for c in components
        ],
    )
    current = (
        {**value, "availability": snapshot}
        if o.state in ("Draft", "Confirmed", "In Progress")
        else value
    )
    actions = []
    if allowed(g.user, app_document().stored_data, "manufacturing", "approve"):
        actions = {
            "Draft": ["confirm", "cancel"],
            "Confirmed": ["start", "complete"],
            "In Progress": ["complete"],
        }.get(o.state, [])
    return {
        **value,
        "components": components,
        "bomName": b.name,
        "version": version(current),
        "actions": actions,
        "materialsAvailable": ready,
        "estimatedCost": str(estimate + o.conversion_cost),
        "journalHref": (
            "erp.html?view=journals&source=mo:" + str(o.id)
            if o.state == "Done"
            and allowed(g.user, app_document().stored_data, "accounting")
            else None
        ),
        "movementsHref": (
            "erp.html?view=stock-moves&search=mo%3A" + str(o.id) + "%3A"
            if o.state == "Done"
            and allowed(g.user, app_document().stored_data, "inventory")
            else None
        ),
    }


@bp.get("/summary")
@read
def summary():
    groups = db.session.execute(
        select(ManufacturingOrder.state, func.count()).group_by(
            ManufacturingOrder.state
        )
    ).all()
    return jsonify(
        boms=db.session.scalar(select(func.count()).select_from(BillOfMaterials)),
        states={s: n for s, n in groups},
        completedCost=str(
            db.session.scalar(
                select(
                    func.coalesce(func.sum(ManufacturingOrder.actual_cost), 0)
                ).where(ManufacturingOrder.state == "Done")
            )
        ),
        currency="PKR",
    )


@bp.get("/products")
@read
def products():
    p = ERPProduct
    query = select(p.id, p.name, p.sku, p.unit).where(p.kind == "stock")
    term = search_term()
    if term:
        query = query.where(
            or_(
                func.lower(p.name).like(term, escape="\\"),
                func.lower(p.sku).like(term, escape="\\"),
            )
        )
    rows, meta = paged(query, [p.name, p.id])
    return jsonify(
        items=[
            dict(id=r.id, name=r.name + " · " + r.sku, sku=r.sku, unit=r.unit)
            for r in rows
        ],
        **meta
    )


@bp.get("/boms")
@read
def boms():
    b, p = BillOfMaterials, ERPProduct
    count = (
        select(BOMLine.bom_id, func.count().label("components"))
        .group_by(BOMLine.bom_id)
        .subquery()
    )
    query = (
        select(
            b.id,
            b.name,
            b.product_id.label("productId"),
            p.name.label("product"),
            p.sku,
            b.output_quantity.label("quantity"),
            b.conversion_cost.label("conversionCost"),
            count.c.components,
        )
        .join(p, b.product_id == p.id)
        .outerjoin(count, count.c.bom_id == b.id)
    )
    term = search_term()
    if term:
        query = query.where(
            or_(
                *(
                    func.lower(c).like(term, escape="\\")
                    for c in (b.name, p.name, p.sku)
                )
            )
        )
    rows, meta = paged(query, [b.id.desc()])
    return jsonify(
        items=[
            {k: str(v) if isinstance(v, Decimal) else v for k, v in r._mapping.items()}
            for r in rows
        ],
        **meta
    )


@bp.get("/orders")
@read
def orders():
    o, p, b = ManufacturingOrder, ERPProduct, BillOfMaterials
    query = (
        select(
            o.id,
            o.number,
            o.bom_id.label("bomId"),
            b.name.label("bomName"),
            o.product_id.label("productId"),
            p.name.label("product"),
            p.sku,
            o.quantity,
            o.conversion_cost.label("conversionCost"),
            o.actual_cost.label("actualCost"),
            o.state,
            o.date,
        )
        .join(p, o.product_id == p.id)
        .join(b, o.bom_id == b.id)
    )
    term = search_term()
    if term:
        query = query.where(
            or_(
                *(
                    func.lower(c).like(term, escape="\\")
                    for c in (o.number, p.name, p.sku, b.name)
                )
            )
        )
    if request.args.get("state"):
        query = query.where(o.state == request.args["state"])
    start = day(request.args["from"]) if request.args.get("from") else None
    end = day(request.args["to"]) if request.args.get("to") else None
    if start and end and start > end:
        problem("Start date must precede end date")
    if start:
        query = query.where(o.date >= start)
    if end:
        query = query.where(o.date <= end)
    rows, meta = paged(query, [o.id.desc()])
    return jsonify(
        items=[
            {k: str(v) if isinstance(v, Decimal) else v for k, v in r._mapping.items()}
            for r in rows
        ],
        **meta
    )


@bp.get("/boms/<int:identity>")
@read
def bom(identity):
    return jsonify(record=bom_record(get(BillOfMaterials, identity)))


@bp.get("/orders/<int:identity>")
@read
def order(identity):
    return jsonify(record=order_record(get(ManufacturingOrder, identity)))


def check_version(data, expected, field="version"):
    if not data.get(field):
        problem("Current " + field + " is required", 428)
    if data[field] != expected:
        problem("Production record or stock changed. Reload before trying again.", 409)


def components(data, output):
    items = data.get("components")
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        problem("Add 1–100 stock components")
    seen = set()
    result = []
    for item in items:
        if not isinstance(item, dict) or set(item) - {"productId", "quantity"}:
            problem("Invalid component fields")
        p = stock(item.get("productId"))
        if p.id == output or p.id in seen:
            problem("Use distinct components different from the output")
        seen.add(p.id)
        result.append(
            BOMLine(
                product_id=p.id, quantity=dec(item.get("quantity"), UNIT, positive=True)
            )
        )
    return result


@bp.post("/commands/<command>")
def command(command):
    permit()
    data = body()
    validate_json(data)
    fields = {
        "bom": {"name", "productId", "quantity", "conversionCost", "components"},
        "edit-bom": {
            "id",
            "version",
            "name",
            "quantity",
            "conversionCost",
            "components",
        },
        "order": {"bomId", "bomVersion", "quantity", "date"},
        "confirm": {"id", "version"},
        "start": {"id", "version"},
        "complete": {"id", "version"},
        "cancel": {"id", "version"},
    }
    if command not in fields:
        problem("Unknown manufacturing command", 404)
    if set(data) - fields[command] - {"requestKey"}:
        problem("Unknown or immutable production fields")
    permit(
        "create"
        if command in ("bom", "order")
        else "edit" if command == "edit-bom" else "approve"
    )
    key = data.get("requestKey", "")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
        problem("A unique requestKey of 8–100 characters is required")
    fingerprint = version(
        dict(
            command=command,
            data={
                k: v
                for k, v in data.items()
                if k not in ("requestKey", "version", "bomVersion")
            },
        )
    )
    lock()
    receipt = db.session.get(Command, (g.user.id, key))
    if receipt:
        if receipt.fingerprint != fingerprint:
            problem("Request key was used for another command", 409)
        return jsonify(
            record=(
                bom_record(get(BillOfMaterials, receipt.identity))
                if receipt.resource == "boms"
                else order_record(get(ManufacturingOrder, receipt.identity))
            )
        )
    g.scope_creator = g.user.id
    if command in ("bom", "edit-bom"):
        b = get(BillOfMaterials, data.get("id")) if command == "edit-bom" else None
        if b:
            check_version(data, bom_record(b)["version"])
        output = b.product_id if b else stock(data.get("productId")).id
        stock(output)
        lines = components(data, output)
        quantity = dec(data.get("quantity"), UNIT, positive=True)
        cost = dec(data.get("conversionCost", 0))
        if cost < 0:
            problem("Conversion cost cannot be negative")
        if b is None:
            b = BillOfMaterials(
                product_id=output,
                request_key="native:" + version(dict(actor=g.user.id, key=key)),
            )
            db.session.add(b)
        b.name = text(data, "name", limit=160, required=True)
        b.output_quantity = quantity
        b.conversion_cost = cost
        b.lines = lines
        db.session.flush()
        remember(b)
        resource = "boms"
        identity = b.id
    else:
        if command == "order":
            b = get(BillOfMaterials, data.get("bomId"))
            check_version(data, bom_record(b)["version"], "bomVersion")
            if data.get("date") is not None and not isinstance(data["date"], str):
                problem("Use a YYYY-MM-DD production date")
            stock(b.product_id)
            if b.output_quantity <= 0 or b.conversion_cost < 0:
                problem("Review invalid historical BoM quantities/cost")
            for line in b.lines:
                stock(line.product_id)
            quantity = dec(data.get("quantity"), UNIT, positive=True)
            factor = quantity / b.output_quantity
            if not b.lines:
                problem("BoM has no components")
            o = ManufacturingOrder(
                number=next_number("MO"),
                bom_id=b.id,
                product_id=b.product_id,
                quantity=quantity,
                conversion_cost=dec(b.conversion_cost * factor),
                actual_cost=0,
                state="Draft",
                date=day(data.get("date")),
                request_key="native:" + version(dict(actor=g.user.id, key=key)),
                lines=[
                    ProductionComponent(
                        product_id=l.product_id,
                        quantity=dec(l.quantity * factor, UNIT, positive=True),
                    )
                    for l in sorted(b.lines, key=lambda l: l.id)
                ],
            )
            db.session.add(o)
            db.session.flush()
            remember(o)
        else:
            o = get(ManufacturingOrder, data.get("id"))
            check_version(data, order_record(o)["version"])
            transitions = {
                "confirm": ("Draft", "Confirmed"),
                "start": ("Confirmed", "In Progress"),
                "cancel": ("Draft", "Cancelled"),
            }
            if command in transitions:
                before, after = transitions[command]
                if o.state != before:
                    problem("Action unavailable in this manufacturing state", 409)
                o.state = after
            else:
                if o.state not in ("Confirmed", "In Progress"):
                    problem("Confirm an unfinished order before completion", 409)
                finish_manufacturing(o)
        db.session.flush()
        resource = "orders"
        identity = o.id
    audit("Production " + command, dict(resource=resource, recordId=identity))
    db.session.add(
        Command(
            actor_id=g.user.id,
            request_key=key,
            fingerprint=fingerprint,
            resource=resource,
            identity=identity,
        )
    )
    db.session.commit()
    return jsonify(
        record=(
            bom_record(get(BillOfMaterials, identity))
            if resource == "boms"
            else order_record(get(ManufacturingOrder, identity))
        )
    )


@bp.get("/orders/<int:identity>/print")
@read
def print_order(identity):
    permit("export")
    r = order_record(get(ManufacturingOrder, identity))
    response = make_response(
        render_template_string(
            """<!doctype html><html lang="en"><meta charset="utf-8"><title>{{r.number}}</title><style>body{font:14px Arial;margin:36px;color:#172338}table{width:100%;border-collapse:collapse}th,td{padding:10px;text-align:left;border-bottom:1px solid #ddd}@media print{button{display:none}tr{break-inside:avoid}}</style><h1>{{company.get('name','Company')}}</h1><h2>Manufacturing Order {{r.number}}</h2><p>{{r.date}} · {{r.state}} · WH / Stock · PKR</p><p>{{r.product}} · {{r.sku}} · Output {{r.quantity}}</p><p>BoM: {{r.bomName}}</p><table><tr><th>Component</th><th>SKU</th><th>Required quantity</th><th>Unit</th></tr>{% for c in r.components %}<tr><td>{{c.product}}</td><td>{{c.sku}}</td><td>{{c.quantity}}</td><td>{{c.unit}}</td></tr>{% endfor %}</table><p>Conversion cost: PKR {{r.conversionCost}} · Posted actual cost: PKR {{r.actualCost}}</p><p>Component quantities are the order snapshot. Stock availability can change before completion.</p><button onclick="window.print()">Print / Save as PDF</button></html>""",
            r=r,
            company=app_document().stored_data.get("company", {}),
        )
    )
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response
