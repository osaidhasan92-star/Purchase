"""One-warehouse locations, stock reservations and order-linked backorders."""

from decimal import Decimal
import re
from flask import Blueprint, g, jsonify, request
from sqlalchemy import select, func, update, and_, or_
from .app import db, Document, app_document, body, problem, audit, validate_json
from .permissions import allowed
from .erp import (
    StockBalance,
    ERPProduct,
    StockMove,
    dec,
    UNIT,
    day,
    lock,
    next_number,
    check_period,
)
from . import trade_store as store
from .trade_store import version

bp = Blueprint("warehouse", __name__, url_prefix="/api/warehouse")
LOCATIONS = ("Stock", "Production", "Returns")


class LocationBalance(db.Model):
    product_id = db.Column(
        db.String(64), db.ForeignKey("erp_product.id"), primary_key=True
    )
    location = db.Column(db.String(20), primary_key=True)
    quantity = db.Column(db.Numeric(20, 4), nullable=False, default=0)


class Reservation(db.Model):
    order_id = db.Column(db.String(64), primary_key=True)
    line_index = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.String(64), db.ForeignKey("erp_product.id"), nullable=False, index=True
    )
    quantity = db.Column(db.Numeric(20, 4), nullable=False, default=0)
    required = db.Column(db.Numeric(20, 4), nullable=False, default=0)


class Backorder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True, nullable=False)
    kind = db.Column(db.String(12), nullable=False)
    order_id = db.Column(db.String(64), nullable=False, index=True)
    line_index = db.Column(db.Integer, nullable=False)
    product_id = db.Column(
        db.String(64), db.ForeignKey("erp_product.id"), nullable=False
    )
    origin_document = db.Column(db.String(64))
    quantity = db.Column(db.Numeric(20, 4), nullable=False)
    status = db.Column(db.String(30), nullable=False)
    __table_args__ = (db.UniqueConstraint("kind", "order_id", "line_index"),)


class InternalTransfer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True, nullable=False)
    product_id = db.Column(
        db.String(64), db.ForeignKey("erp_product.id"), nullable=False
    )
    from_location = db.Column(db.String(20), nullable=False)
    to_location = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Numeric(20, 4), nullable=False)
    date = db.Column(db.String(10), nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    created_by = db.Column(db.String(64), nullable=False)


class Command(db.Model):
    __tablename__ = "warehouse_command"
    actor_id = db.Column(db.String(64), primary_key=True)
    request_key = db.Column(db.String(100), primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    result = db.Column(db.JSON, nullable=False)


def quantities(product_id):
    rows = db.session.execute(
        select(LocationBalance.location, LocationBalance.quantity).where(
            LocationBalance.product_id == str(product_id)
        )
    ).all()
    if not rows:
        balance = db.session.get(StockBalance, str(product_id))
        return dict(
            Stock=balance.quantity if balance else Decimal(0),
            Production=Decimal(0),
            Returns=Decimal(0),
        )
    return {name: dict(rows).get(name, Decimal(0)) for name in LOCATIONS}


def ensure_locations(product_id):
    if not db.session.scalar(
        select(LocationBalance.product_id)
        .where(LocationBalance.product_id == str(product_id))
        .limit(1)
    ):
        values = quantities(product_id)
        for location in LOCATIONS:
            db.session.add(
                LocationBalance(
                    product_id=str(product_id),
                    location=location,
                    quantity=values[location],
                )
            )
        db.session.flush()


def reserved(product_id):
    from .production_workflow import held

    return held(product_id, "Stock") + Decimal(
        str(
            db.session.scalar(
                select(func.coalesce(func.sum(Reservation.quantity), 0)).where(
                    Reservation.product_id == str(product_id)
                )
            )
            or 0
        )
    )


def line_reservation(order_id, index):
    row = db.session.get(Reservation, (str(order_id), index))
    return row.quantity if row else Decimal(0)


def available(product_id):
    return max(Decimal(0), quantities(product_id)["Stock"] - reserved(product_id))


def stock_state(product_id):
    from .production_workflow import held

    values = quantities(product_id)
    result = dict(
        productId=str(product_id),
        locations={k: str(v) for k, v in values.items()},
        reserved=str(reserved(product_id)),
        available=str(available(product_id)),
        productionReserved=str(held(product_id, "Production")),
    )
    return {**result, "version": version(result)}


def reserve_order(state, order):
    from .trade_service import dispatched

    cancelled = order.get("status") in ("Cancelled", "Closed")
    total = Decimal(0)
    demand = Decimal(0)
    for index, line in enumerate(order.get("items", [])):
        product = db.session.get(ERPProduct, str(line.get("productId")))
        if not product or product.kind != "stock":
            continue
        need = (
            max(
                Decimal(0),
                Decimal(str(line["quantity"])) - dispatched(state, order, index),
            )
            if not cancelled
            else Decimal(0)
        )
        row = db.session.get(Reservation, (str(order["id"]), index))
        own = row.quantity if row else Decimal(0)
        qty = min(
            need,
            max(
                Decimal(0),
                quantities(product.id)["Stock"] - (reserved(product.id) - own),
            ),
        )
        if order.get("reservationPaused"):
            qty = Decimal(0)
        if row:
            row.quantity = qty
            row.required = need
        else:
            db.session.add(
                Reservation(
                    order_id=str(order["id"]),
                    line_index=index,
                    product_id=product.id,
                    quantity=qty,
                    required=need,
                )
            )
        db.session.flush()
        total += qty
        demand += need
    order["reservedQuantity"] = float(total)
    order["reservationStatus"] = (
        "Released"
        if cancelled
        else (
            "Not Required"
            if demand == 0
            else (
                "Reserved"
                if total >= demand
                else "Partially Available" if total else "Waiting Stock"
            )
        )
    )


def dispatch_available(state, order, index):
    from .trade_service import dispatched

    if order.get("fulfillmentClosed"):
        return Decimal(0)
    line = order["items"][index]
    product = db.session.get(ERPProduct, str(line.get("productId")))
    remaining = max(
        Decimal(0),
        Decimal(str(line["quantity"])) - dispatched(state, order, index, True),
    )
    if not product or product.kind != "stock":
        return remaining
    pending = dispatched(state, order, index, True) - dispatched(state, order, index)
    return max(
        Decimal(0), min(remaining, line_reservation(order["id"], index) - pending)
    )


def change_locations(product_id, quantity, source, kind):
    """Called once inside the same transaction as the immutable stock ledger."""
    ensure_locations(product_id)
    if quantity > 0:
        location = "Returns" if kind == "Customer Return" else "Stock"
        db.session.get(
            LocationBalance, (str(product_id), location)
        ).quantity += quantity
        return
    need = -quantity
    if kind in ("Manufacturing Consumption", "Manufacturing Scrap") and g.get(
        "production_order_id"
    ):
        from .production_workflow import consume

        consume(product_id, need, g.production_order_id)
        return
    if source.startswith("deliveries:"):
        _, identity, position = source.split(":")
        delivery = db.session.get(store.MODELS["deliveries"], identity)
        if delivery:
            value = store.record("deliveries", delivery)
            line = value["items"][int(position)]
            index = int(line.get("lineIndex", position))
            row = db.session.get(Reservation, (str(value["orderId"]), index))
            if row is None or row.quantity < need:
                if value.get("workflowVersion") == 1 or available(product_id) < need:
                    problem(
                        "Check stock availability before validating this delivery", 409
                    )
            if quantities(product_id)["Stock"] < need:
                problem("Insufficient Stock-location quantity")
            if row:
                row.quantity -= need
            db.session.get(LocationBalance, (str(product_id), "Stock")).quantity -= need
            return
    from .production_workflow import held as production_held

    locations = (
        ("Production", "Stock") if kind == "Manufacturing Consumption" else ("Stock",)
    )
    if (
        sum(
            (
                quantities(product_id)[name]
                - (
                    reserved(product_id)
                    if name == "Stock"
                    else production_held(product_id, name)
                )
                for name in locations
            ),
            Decimal(0),
        )
        < need
    ):
        problem("Insufficient unreserved stock in the eligible locations")
    for location in locations:
        row = db.session.get(LocationBalance, (str(product_id), location))
        take = min(
            need,
            max(
                Decimal(0),
                row.quantity
                - (
                    reserved(product_id)
                    if location == "Stock"
                    else production_held(product_id, location)
                ),
            ),
        )
        row.quantity -= take
        need -= take
        if need <= 0:
            break


def backorders(state, key, order, origin=None):
    from .trade_service import dispatched, received

    customer = key == "salesOrders"
    kind = "sales" if customer else "purchase"
    activity = any(
        str(d.get("orderId" if customer else "poId")) == str(order["id"])
        and (
            d.get("status") == "Delivered"
            if customer
            else any(
                Decimal(str(i.get("receivedQty", 0))) > 0 for i in d.get("items", [])
            )
        )
        for d in state.get("deliveries" if customer else "receipts", [])
    )
    for index, line in enumerate(order.get("items", [])):
        remaining = max(
            Decimal(0),
            Decimal(str(line["quantity"]))
            - (
                dispatched(state, order, index)
                if customer
                else received(state, order, index)
            ),
        )
        row = db.session.scalar(
            select(Backorder).where(
                Backorder.kind == kind,
                Backorder.order_id == str(order["id"]),
                Backorder.line_index == index,
            )
        )
        if not row and (not activity or remaining <= 0):
            continue
        if not row:
            row = Backorder(
                number=next_number("BO-S" if customer else "BO-P"),
                kind=kind,
                order_id=str(order["id"]),
                line_index=index,
                product_id=str(line["productId"]),
                origin_document=str(origin) if origin else None,
                quantity=remaining,
                status="Waiting",
            )
            db.session.add(row)
        row.quantity = Decimal(0) if order.get("fulfillmentClosed") else remaining
        product = db.session.get(ERPProduct, str(line["productId"]))
        ready = (
            (
                remaining
                if product and product.kind == "service"
                else line_reservation(order["id"], index)
            )
            if customer
            else Decimal(0)
        )
        row.status = (
            "Cancelled"
            if order.get("status") in ("Cancelled", "Closed")
            else (
                "Done"
                if remaining == 0
                else (
                    "Ready"
                    if customer and ready >= remaining
                    else (
                        "Partially Available"
                        if ready > 0
                        else "Waiting Stock" if customer else "Waiting Receipt"
                    )
                )
            )
        )
    db.session.flush()


def refresh(state, key, row):
    if key in ("salesOrders", "deliveries", "customerInvoices", "customerPayments"):
        identity = row["id"] if key == "salesOrders" else row.get("orderId")
        order = next(
            (o for o in state.get("salesOrders", []) if str(o["id"]) == str(identity)),
            None,
        )
        if order:
            reserve_order(state, order)
            backorders(
                state, "salesOrders", order, row["id"] if key == "deliveries" else None
            )
    elif key in ("orders", "receipts", "invoices", "payments"):
        identity = row["id"] if key == "orders" else row.get("poId")
        order = next(
            (o for o in state.get("orders", []) if str(o["id"]) == str(identity)), None
        )
        if order:
            backorders(state, "orders", order, row["id"] if key == "receipts" else None)


def initialize_warehouse():
    from .trade_context import Context

    for identity in db.session.scalars(select(StockBalance.product_id)):
        ensure_locations(identity)
    for key in ("salesOrders", "orders"):
        model = store.MODELS[key]
        for identity in db.session.scalars(
            select(model.id).order_by(model.document_date, model.id)
        ):
            context = Context(key, identity, {})
            row = next(o for o in context.state[key] if str(o["id"]) == str(identity))
            if all(
                db.session.get(ERPProduct, str(line.get("productId")))
                and Decimal(str(line.get("quantity", 0))) > 0
                for line in row.get("items", [])
            ):
                refresh(context.state, key, row)
                context.persist()


def permit(action="view"):
    if not allowed(g.user, app_document().stored_data, "inventory", action):
        problem("Inventory permission denied: " + action, 403)


@bp.get("/<area>")
def listing(area):
    permit()
    from .finance_api import paged
    from .trade_api import visibility

    sales_model = store.MODELS["salesOrders"]
    purchase_model = store.MODELS["orders"]
    sales_ids = (
        select(sales_model.id).where(visibility("salesOrders"))
        if allowed(g.user, app_document().stored_data, "sales_orders")
        else select(sales_model.id).where(False)
    )
    purchase_ids = (
        select(purchase_model.id).where(visibility("orders"))
        if allowed(g.user, app_document().stored_data, "orders")
        else select(purchase_model.id).where(False)
    )

    if area == "locations":
        query = select(ERPProduct).where(ERPProduct.kind == "stock")
        rows, meta = paged(query, [ERPProduct.name, ERPProduct.id])
        return jsonify(
            items=[dict(stock_state(r[0].id), name=r[0].name) for r in rows], **meta
        )
    if area == "reservations":
        query = select(Reservation).where(
            Reservation.required > 0, Reservation.order_id.in_(sales_ids)
        )
        rows, meta = paged(query, [Reservation.order_id, Reservation.line_index])
        items = []
        for r in rows:
            row = r[0]
            order = db.session.get(store.MODELS["salesOrders"], row.order_id)
            product = db.session.get(ERPProduct, row.product_id)
            items.append(
                dict(
                    orderId=row.order_id,
                    orderNumber=order.number if order else row.order_id,
                    lineIndex=row.line_index,
                    product=product.name,
                    quantity=str(row.quantity),
                    required=str(row.required),
                )
            )
        return jsonify(items=items, **meta)
    if area == "backorders":
        query = select(Backorder).where(
            Backorder.status.not_in(("Done", "Cancelled")),
            or_(
                and_(Backorder.kind == "sales", Backorder.order_id.in_(sales_ids)),
                and_(
                    Backorder.kind == "purchase", Backorder.order_id.in_(purchase_ids)
                ),
            ),
        )
        rows, meta = paged(query, [Backorder.id.desc()])
        items = []
        for r in rows:
            row = r[0]
            order = db.session.get(
                store.MODELS["salesOrders" if row.kind == "sales" else "orders"],
                row.order_id,
            )
            items.append(
                dict(
                    id=row.id,
                    number=row.number,
                    kind=row.kind,
                    orderId=row.order_id,
                    orderNumber=order.number if order else row.order_id,
                    originDocument=row.origin_document,
                    originNumber=(
                        db.session.get(
                            store.MODELS[
                                "deliveries" if row.kind == "sales" else "receipts"
                            ],
                            row.origin_document,
                        ).number
                        if row.origin_document
                        and db.session.get(
                            store.MODELS[
                                "deliveries" if row.kind == "sales" else "receipts"
                            ],
                            row.origin_document,
                        )
                        and allowed(
                            g.user,
                            app_document().stored_data,
                            "sales_deliveries" if row.kind == "sales" else "receipts",
                        )
                        else None
                    ),
                    product=db.session.get(ERPProduct, row.product_id).name,
                    quantity=str(row.quantity),
                    status=row.status,
                )
            )
        return jsonify(items=items, **meta)
    if area == "transfers":
        rows, meta = paged(select(InternalTransfer), [InternalTransfer.id.desc()])
        return jsonify(
            items=[
                dict(
                    id=r[0].id,
                    number=r[0].number,
                    product=db.session.get(ERPProduct, r[0].product_id).name,
                    fromLocation=r[0].from_location,
                    toLocation=r[0].to_location,
                    quantity=str(r[0].quantity),
                    date=r[0].date,
                    reason=r[0].reason,
                )
                for r in rows
            ],
            **meta
        )
    problem("Unknown warehouse register", 404)


@bp.post("/commands/<command>")
def command(command):
    permit("approve")
    data = body()
    validate_json(data)
    fields = {
        "transfer": {
            "productId",
            "fromLocation",
            "toLocation",
            "quantity",
            "date",
            "reason",
            "version",
        },
        "reserve": {"orderId"},
        "release": {"orderId"},
    }
    if command not in fields or set(data) - fields[command] - {"requestKey"}:
        problem("Unknown warehouse command/fields")
    token = data.get("requestKey", "")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", token):
        problem("A unique requestKey is required")
    fingerprint = version(
        dict(
            command=command,
            data={k: v for k, v in data.items() if k not in ("requestKey", "version")},
        )
    )
    lock()
    from .workflow_keys import revalidate_actor

    revalidate_actor()
    permit("approve")
    if command in ("reserve", "release"):
        from .trade_api import scoped

        scoped("salesOrders", str(data.get("orderId")))
    receipt = db.session.get(Command, (g.user.id, token))
    if receipt:
        if receipt.fingerprint != fingerprint:
            problem("Request key already used", 409)
        return jsonify(record=receipt.result)
    if command == "transfer":
        permit("create")
        identity = str(data.get("productId"))
        product = db.session.get(ERPProduct, identity)
        if not product or product.kind != "stock":
            problem("Choose a stock product")
        if data.get("version") != stock_state(identity)["version"]:
            problem("Stock or reservations changed; reload", 409)
        from .production_workflow import held as production_held

        source, target = data.get("fromLocation"), data.get("toLocation")
        if source not in LOCATIONS or target not in LOCATIONS or source == target:
            problem("Choose different internal locations")
        qty = dec(data.get("quantity"), UNIT, positive=True)
        date = day(data.get("date"))
        check_period(date)
        reason = data.get("reason", "")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 300:
            problem("Enter a transfer reason")
        if qty > (
            available(identity)
            if source == "Stock"
            else quantities(identity)[source] - production_held(identity, source)
        ):
            problem("Transfer exceeds unreserved source-location stock")
        ensure_locations(identity)
        db.session.get(LocationBalance, (identity, source)).quantity -= qty
        db.session.get(LocationBalance, (identity, target)).quantity += qty
        transfer = InternalTransfer(
            number=next_number("INT"),
            product_id=identity,
            from_location=source,
            to_location=target,
            quantity=qty,
            date=date,
            reason=reason.strip(),
            created_by=g.user.id,
        )
        db.session.add(transfer)
        db.session.flush()
        result = dict(id=transfer.id, number=transfer.number, status="Done")
    else:
        from .trade_context import Context

        identity = str(data.get("orderId"))
        from .trade_api import scoped

        scoped("salesOrders", identity)
        order = db.session.get(store.MODELS["salesOrders"], identity)
        if not order:
            problem("Sales order not found", 404)
        if order.status not in ("Confirmed", "Partially Delivered"):
            problem("Sales order is not open for reservations", 409)
        context = Context("salesOrders", identity, {})
        row = next(v for v in context.state["salesOrders"] if str(v["id"]) == identity)
        row["reservationPaused"] = command == "release"
        refresh(context.state, "salesOrders", row)
        context.persist()
        result = dict(
            orderId=identity,
            status=row["reservationStatus"],
            reservedQuantity=row["reservedQuantity"],
        )
        db.session.execute(
            update(Document)
            .where(Document.name == "app")
            .values(revision=Document.revision + 1)
        )
    db.session.add(
        Command(
            actor_id=g.user.id,
            request_key=token,
            fingerprint=fingerprint,
            result=result,
        )
    )
    audit("Warehouse " + command, result)
    db.session.commit()
    return jsonify(record=result)


def annotate_backorder(key, values):
    if key not in ("deliveries", "receipts"):
        return
    kind = "sales" if key == "deliveries" else "purchase"
    identity = values.get("orderId" if key == "deliveries" else "poId")
    numbers = list(
        db.session.scalars(
            select(Backorder.number).where(
                Backorder.kind == kind,
                Backorder.order_id == str(identity),
                Backorder.status.not_in(("Done", "Cancelled")),
            )
        )
    )
    if numbers:
        values["backorderReference"] = ", ".join(numbers)


def refresh_persist(key, row):
    customer = key in (
        "salesOrders",
        "deliveries",
        "customerInvoices",
        "customerPayments",
    )
    if key not in (
        "salesOrders",
        "deliveries",
        "customerInvoices",
        "customerPayments",
        "orders",
        "receipts",
        "invoices",
        "payments",
    ):
        return
    target = "salesOrders" if customer else "orders"
    identity = (
        row["id"] if key == target else row.get("orderId" if customer else "poId")
    )
    if identity is None:
        return
    from .trade_context import Context

    graph = Context(target, str(identity), {})
    order = next(o for o in graph.state[target] if str(o["id"]) == str(identity))
    refresh(graph.state, key, row)
    graph.persist()
