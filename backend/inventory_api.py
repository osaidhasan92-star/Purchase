"""Native, bounded inventory reads and atomic versioned stock commands."""

from functools import wraps
from decimal import Decimal, ROUND_HALF_UP
import re
from flask import Blueprint, g, jsonify, request
from sqlalchemy import select, func, or_
from .app import db, app_document, body, problem, audit, validate_json
from .permissions import allowed
from .erp import (
    ERPProduct,
    StockBalance,
    StockMove,
    dec,
    UNIT,
    CENT,
    day,
    lock,
    stock_move,
)
from .trade_store import version
from .trade_service import text
from .finance_api import paging, paged, search_term, source_link

bp = Blueprint("inventory_resources", __name__, url_prefix="/api/inventory")


class Command(db.Model):
    __tablename__ = "inventory_command"
    actor_id = db.Column(db.String(64), primary_key=True)
    request_key = db.Column(db.String(100), primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    movement_id = db.Column(
        db.Integer, db.ForeignKey("stock_move.id"), nullable=False, index=True
    )
    reason = db.Column(db.String(300), nullable=False)


def permit(action="view"):
    if not allowed(g.user, app_document().stored_data, "inventory", action):
        problem("Inventory permission denied: " + action, 403)


def read(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        permit()
        return fn(*a, **kw)

    return wrapped


def product_record(p, b):
    qty = b.quantity if b else Decimal(0)
    value = b.value if b else Decimal(0)
    result = dict(
        id=p.id,
        name=p.name,
        sku=p.sku,
        type=p.kind,
        unit=p.unit,
        quantity=str(qty),
        value=str(value),
        averageCost=str(dec(value / qty)) if qty else "0.00",
    )
    return {**result, "version": version(result)}


def product(identity):
    p = db.session.get(ERPProduct, str(identity))
    if not p:
        problem("Product not found", 404)
    return p, db.session.get(StockBalance, p.id)


def returned(original):
    values = db.session.execute(
        select(
            func.coalesce(func.sum(func.abs(StockMove.quantity)), 0),
            func.coalesce(func.sum(StockMove.value), 0),
        ).where(StockMove.return_of == original.id)
    ).one()
    return Decimal(str(values[0])), Decimal(str(values[1]))


def movement_record(m, detail=False):
    p, b = product(m.product_id)
    qty, value = returned(m)
    result = dict(
        id=m.id,
        number=m.number,
        date=m.date,
        productId=m.product_id,
        product=p.name,
        sku=p.sku,
        unit=p.unit,
        quantity=str(m.quantity),
        value=str(m.value),
        kind=m.kind,
        source=m.source,
        journalId=m.journal_id,
        returnOf=m.return_of,
        returnedQuantity=str(qty),
        returnRemaining=str(max(Decimal(0), abs(m.quantity) - qty)),
    )
    state = dict(**result, balanceVersion=product_record(p, b)["version"])
    result.update(
        version=version(state),
        canReturn=m.kind in ("Purchase Receipt", "Sales Delivery")
        and qty < abs(m.quantity)
        and allowed(g.user, app_document().stored_data, "inventory", "approve"),
    )
    if detail:
        receipt = db.session.scalar(
            select(Command).where(Command.movement_id == m.id).limit(1)
        )
        result.update(
            reason=receipt.reason if receipt else None,
            sourceLink=source_link(m.source),
            journalHref=(
                "erp.html?view=journals&source=stock:" + m.source
                if m.journal_id
                and allowed(g.user, app_document().stored_data, "accounting")
                else None
            ),
        )
    return result


def get_move(identity):
    if (
        isinstance(identity, bool)
        or not isinstance(identity, int)
        or not 0 < identity < 2147483648
    ):
        problem("Stock movement not found", 404)
    m = db.session.get(StockMove, identity)
    if not m:
        problem("Stock movement not found", 404)
    return m


@bp.get("/summary")
@read
def summary():
    count = db.session.scalar(
        select(func.count()).select_from(ERPProduct).where(ERPProduct.kind == "stock")
    )
    value = db.session.scalar(
        select(func.coalesce(func.sum(StockBalance.value), 0))
        .join(ERPProduct)
        .where(ERPProduct.kind == "stock")
    )
    moves = db.session.scalar(select(func.count()).select_from(StockMove))
    return jsonify(
        warehouse="WH / Stock",
        currency="PKR",
        stockProducts=count,
        inventoryValue=str(value),
        movements=moves,
    )


@bp.get("/products")
@read
def products():
    query = select(ERPProduct, StockBalance).outerjoin(StockBalance)
    p = ERPProduct
    term = search_term()
    if term:
        query = query.where(
            or_(
                func.lower(p.name).like(term, escape="\\"),
                func.lower(p.sku).like(term, escape="\\"),
            )
        )
    kind = request.args.get("type")
    if kind:
        if kind not in ("stock", "service"):
            problem("Invalid product type")
        query = query.where(p.kind == kind)
    rows, meta = paged(query, [p.name, p.id])
    return jsonify(items=[product_record(p, b) for p, b in rows], **meta)


@bp.get("/products/<identity>")
@read
def details(identity):
    return jsonify(record=product_record(*product(identity)))


def movement_query():
    m, p = StockMove, ERPProduct
    query = select(
        m.id,
        m.number,
        m.date,
        m.product_id.label("productId"),
        p.name.label("product"),
        p.sku,
        p.unit,
        m.quantity,
        m.value,
        m.kind,
        m.source,
        m.journal_id.label("journalId"),
        m.return_of.label("returnOf"),
    ).join(p)
    term = search_term()
    if term:
        query = query.where(
            or_(
                *(
                    func.lower(c).like(term, escape="\\")
                    for c in (p.name, p.sku, m.number, m.kind, m.source)
                )
            )
        )
    if request.args.get("productId"):
        query = query.where(m.product_id == request.args["productId"])
    if request.args.get("kind"):
        query = query.where(m.kind == request.args["kind"])
    start = day(request.args["from"]) if request.args.get("from") else None
    end = day(request.args["to"]) if request.args.get("to") else None
    if start and end and start > end:
        problem("Start date must precede end date")
    if start:
        query = query.where(m.date >= start)
    if end:
        query = query.where(m.date <= end)
    return query


def header(row):
    v = dict(row._mapping)
    for field in ("quantity", "value"):
        v[field] = str(v[field])
    return v


@bp.get("/movements")
@read
def movements():
    rows, meta = paged(movement_query(), [StockMove.id.desc()])
    return jsonify(items=[header(r) for r in rows], **meta)


@bp.get("/movements/<int:identity>")
@read
def move_detail(identity):
    return jsonify(record=movement_record(get_move(identity), True))


def check_version(data, expected):
    if not data.get("version"):
        problem("Current record version is required", 428)
    if data["version"] != expected:
        problem("Stock changed. Reload the record before trying again.", 409)


@bp.post("/commands/<command>")
def command(command):
    permit()
    permit("approve")
    data = body()
    validate_json(data)
    fields = {
        "adjust": {"productId", "quantity", "unitCost", "date", "reason", "version"},
        "scrap": {"productId", "quantity", "date", "reason", "version"},
        "return": {"moveId", "quantity", "date", "reason", "version"},
    }
    if command not in fields:
        problem("Unknown stock command", 404)
    if set(data) - fields[command] - {"requestKey"}:
        problem("Unknown or immutable inventory fields")
    key = data.get("requestKey", "")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
        problem("A unique requestKey of 8–100 characters is required")
    fingerprint = version(
        dict(
            command=command,
            data={k: v for k, v in data.items() if k not in ("version", "requestKey")},
        )
    )
    lock()
    receipt = db.session.get(Command, (g.user.id, key))
    if receipt:
        if receipt.fingerprint != fingerprint:
            problem("Request key was already used for another command", 409)
        return jsonify(record=movement_record(get_move(receipt.movement_id), True))
    if data.get("date") is not None and not isinstance(data["date"], str):
        problem("Date must use YYYY-MM-DD")
    date = day(data.get("date"))
    reason = text(data, "reason", limit=300, required=True)
    quantity = dec(data.get("quantity"), UNIT)
    source = "native:" + version(dict(actor=g.user.id, key=key))
    if command in ("adjust", "scrap"):
        identity = data.get("productId")
        if not isinstance(identity, (str, int)) or isinstance(identity, bool):
            problem("Select a stock product")
        p, b = product(identity)
        if p.kind != "stock" or b is None:
            problem("Choose a stock-tracked product with a valid balance")
        check_version(data, product_record(p, b)["version"])
        cost = dec(data.get("unitCost", 0), UNIT)
        if cost < 0:
            problem("Incoming unit cost cannot be negative")
        if command == "scrap":
            if quantity <= 0:
                problem("Scrap quantity must be positive")
            quantity = -quantity
        g.scope_creator = g.user.id
        m = stock_move(
            p.id,
            quantity,
            "adjust:" + source,
            "Scrap" if command == "scrap" else "Stock Adjustment",
            "5105",
            cost,
            date,
        )
    else:
        identity = data.get("moveId")
        if (
            isinstance(identity, bool)
            or not isinstance(identity, (str, int))
            or not re.fullmatch(r"[1-9][0-9]{0,9}", str(identity))
        ):
            problem("Invalid original movement")
        original = get_move(int(identity))
        check_version(data, movement_record(original)["version"])
        if original.kind not in ("Purchase Receipt", "Sales Delivery"):
            problem("Return a purchase receipt or delivered sale")
        prior, prior_value = returned(original)
        if quantity <= 0 or quantity + prior > abs(original.quantity):
            problem("Return quantity exceeds the remaining original quantity")
        from .scope import object_creator

        g.scope_creator = object_creator(original) or g.user.id
        incoming = original.quantity < 0
        total_value = None
        if incoming:
            # Allocate original delivery cents cumulatively, including the final residual.
            target = (
                abs(original.value) * (prior + quantity) / abs(original.quantity)
            ).quantize(CENT, rounding=ROUND_HALF_UP)
            total_value = target - prior_value
            if total_value < 0:
                problem("Historical return valuation requires accounting review")
        m = stock_move(
            original.product_id,
            quantity if incoming else -quantity,
            "return:" + source,
            "Customer Return" if incoming else "Vendor Return",
            original.counterpart,
            0,
            date,
            total_value=total_value,
            return_of=original.id,
        )
    db.session.add(
        Command(
            actor_id=g.user.id,
            request_key=key,
            fingerprint=fingerprint,
            movement_id=m.id,
            reason=reason,
        )
    )
    audit("Inventory " + command, dict(movementId=m.id, reason=reason))
    db.session.commit()
    return jsonify(record=movement_record(get_move(m.id), True))


@bp.get("/movements/export")
@read
def export():
    permit("export")
    import csv, io
    from flask import make_response

    rows, meta = paged(movement_query(), [StockMove.id.desc()])
    fields = ["number", "date", "product", "sku", "kind", "quantity", "value", "source"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(fields)
    for row in rows:
        v = header(row)
        cells = []
        for field in fields:
            cell = str(v.get(field, ""))
            if cell.lstrip().startswith(("=", "+", "-", "@")):
                cell = "'" + cell
            cells.append(cell)
        writer.writerow(cells)
    response = make_response(buf.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="stock-movements-page-{meta["page"]}.csv"'
    )
    return response
