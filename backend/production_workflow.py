"""Manufacturing component allocation and immutable actual-production snapshots."""

from decimal import Decimal
from flask import g
from sqlalchemy import select, func
from .app import db, problem
from .erp import (
    ERPProduct,
    ManufacturingOrder,
    ProductionComponent,
    UNIT,
    dec,
    next_number,
    check_period,
    stock_move,
    journal_pair,
)


class MaterialReservation(db.Model):
    order_id = db.Column(
        db.Integer, db.ForeignKey("manufacturing_order.id"), primary_key=True
    )
    product_id = db.Column(
        db.String(64), db.ForeignKey("erp_product.id"), primary_key=True
    )
    location = db.Column(db.String(20), primary_key=True)
    quantity = db.Column(db.Numeric(20, 4), nullable=False, default=0)
    __table_args__ = (
        db.Index("ix_material_reservation_product_location", "product_id", "location"),
        db.CheckConstraint("quantity >= 0", name="ck_material_reservation_quantity"),
        db.CheckConstraint(
            "location IN ('Stock', 'Production')",
            name="ck_material_reservation_location",
        ),
    )


class ProductionResult(db.Model):
    order_id = db.Column(
        db.Integer, db.ForeignKey("manufacturing_order.id"), primary_key=True
    )
    parent_id = db.Column(
        db.Integer, db.ForeignKey("manufacturing_order.id"), index=True
    )
    snapshot = db.Column(db.JSON, nullable=False, default=dict)


def held(product_id, location, order_id=None):
    query = select(func.coalesce(func.sum(MaterialReservation.quantity), 0)).where(
        MaterialReservation.product_id == str(product_id),
        MaterialReservation.location == location,
    )
    if order_id is not None:
        query = query.where(MaterialReservation.order_id == order_id)
    return Decimal(str(db.session.scalar(query) or 0))


def free(product_id, location):
    from .warehouse_api import available, quantities

    return (
        available(product_id)
        if location == "Stock"
        else max(
            Decimal(0), quantities(product_id)[location] - held(product_id, location)
        )
    )


def release(order):
    for row in db.session.scalars(
        select(MaterialReservation).where(MaterialReservation.order_id == order.id)
    ):
        row.quantity = 0
    db.session.flush()


def reserve(order):
    release(order)
    if order.state not in ("Confirmed", "In Progress"):
        return
    for line in order.lines:
        need = line.quantity
        for location in ("Production", "Stock"):
            take = min(need, free(line.product_id, location))
            row = db.session.get(
                MaterialReservation, (order.id, line.product_id, location)
            )
            if not row:
                row = MaterialReservation(
                    order_id=order.id, product_id=line.product_id, location=location
                )
                db.session.add(row)
            row.quantity = take
            need -= take
            db.session.flush()


def stage(order):
    from .warehouse_api import ensure_locations, LocationBalance, InternalTransfer

    check_period(order.date)
    reserve(order)
    for line in order.lines:
        row = db.session.get(MaterialReservation, (order.id, line.product_id, "Stock"))
        if not row or row.quantity <= 0:
            continue
        ensure_locations(line.product_id)
        qty = row.quantity
        db.session.get(LocationBalance, (line.product_id, "Stock")).quantity -= qty
        db.session.get(LocationBalance, (line.product_id, "Production")).quantity += qty
        target = db.session.get(
            MaterialReservation, (order.id, line.product_id, "Production")
        )
        target.quantity += qty
        row.quantity = 0
        db.session.add(
            InternalTransfer(
                number=next_number("INT"),
                product_id=line.product_id,
                from_location="Stock",
                to_location="Production",
                quantity=qty,
                date=order.date,
                reason="Materials staged for " + order.number,
                created_by=g.user.id,
            )
        )
    db.session.flush()


def consume(product_id, quantity, order_id):
    """Use this order's allocation, then free stock, never another order's allocation."""
    from .warehouse_api import ensure_locations, LocationBalance

    ensure_locations(product_id)
    capacity = sum(
        (
            held(product_id, loc, order_id) + free(product_id, loc)
            for loc in ("Production", "Stock")
        ),
        Decimal(0),
    )
    if capacity < quantity:
        problem("Insufficient unreserved components for this manufacturing order")
    need = quantity
    for loc in ("Production", "Stock"):
        allocation = db.session.get(
            MaterialReservation, (order_id, str(product_id), loc)
        )
        own = allocation.quantity if allocation else Decimal(0)
        take = min(need, own)
        if allocation:
            allocation.quantity -= take
        db.session.get(LocationBalance, (str(product_id), loc)).quantity -= take
        need -= take
        db.session.flush()
    for loc in ("Production", "Stock"):
        take = min(need, free(product_id, loc))
        db.session.get(LocationBalance, (str(product_id), loc)).quantity -= take
        need -= take
        db.session.flush()


def complete(order, data):
    from .scope import object_creator, remember

    if order.state not in ("Confirmed", "In Progress"):
        problem("Confirm an unfinished order before completion", 409)
    check_period(order.date)
    produced = dec(data.get("producedQuantity", order.quantity), UNIT, positive=True)
    if produced > order.quantity:
        problem("Produced quantity cannot exceed the order remainder")
    ratio = produced / order.quantity
    planned_cost = dec(order.conversion_cost * ratio)
    conversion = dec(data.get("conversionCost", planned_cost))
    if conversion < 0:
        problem("Actual conversion cost cannot be negative")
    actual = data.get("components")
    if actual is not None:
        if not isinstance(actual, list) or len(actual) != len(order.lines):
            problem("Enter actual consumption and scrap for every component")
        mapping = {}
        for item in actual:
            if (
                not isinstance(item, dict)
                or set(item) != {"productId", "quantity", "scrap"}
                or isinstance(item.get("productId"), bool)
                or not isinstance(item.get("productId"), (str, int))
                or str(item["productId"]) in mapping
            ):
                problem("Invalid or duplicate actual component")
            qty, scrap = dec(item["quantity"], UNIT), dec(item["scrap"], UNIT)
            if qty < 0 or scrap < 0:
                problem("Consumption and scrap cannot be negative")
            mapping[str(item["productId"])] = (qty, scrap)
        if set(mapping) != {line.product_id for line in order.lines}:
            problem("Actual components must match this order snapshot")
    else:
        mapping = {
            line.product_id: (dec(line.quantity * ratio, UNIT), Decimal(0))
            for line in order.lines
        }
    if not any(qty > 0 for qty, scrap in mapping.values()):
        problem("Record positive material consumption")
    if produced < order.quantity and not any(
        line.quantity - dec(line.quantity * ratio, UNIT) > 0 for line in order.lines
    ):
        problem(
            "Remaining batch is below material quantity precision; complete the full quantity"
        )
    # Preserve the original plan independently of actual consumption and later BoM edits.
    result = db.session.get(ProductionResult, order.id)
    if not result:
        result = ProductionResult(order_id=order.id, snapshot={})
        db.session.add(result)
    snapshot = dict(result.snapshot or {})
    snapshot.update(
        plannedQuantity=str(order.quantity),
        plannedConversionCost=str(order.conversion_cost),
        producedQuantity=str(produced),
        conversionCost=str(conversion),
        components=[],
    )
    g.scope_creator = object_creator(order) or g.user.id
    g.production_order_id = order.id
    total = Decimal(0)
    scrap_cost = Decimal(0)
    try:
        for index, line in enumerate(sorted(order.lines, key=lambda l: l.id)):
            qty, scrap = mapping[line.product_id]
            snapshot["components"].append(
                dict(
                    productId=line.product_id,
                    product=db.session.get(ERPProduct, line.product_id).name,
                    planned=str(line.quantity),
                    consumed=str(qty),
                    scrap=str(scrap),
                )
            )
            if qty:
                move = stock_move(
                    line.product_id,
                    -qty,
                    f"mo:{order.id}:component:{index}",
                    "Manufacturing Consumption",
                    "1250",
                    value_date=order.date,
                )
                total -= move.value
            if scrap:
                move = stock_move(
                    line.product_id,
                    -scrap,
                    f"mo:{order.id}:scrap:{index}",
                    "Manufacturing Scrap",
                    "5105",
                    value_date=order.date,
                )
                scrap_cost -= move.value
        if conversion:
            journal_pair(
                f"mo:{order.id}:conversion",
                "Accrued actual production conversion cost",
                "1250",
                "2400",
                conversion,
                order.date,
            )
        total += conversion
        stock_move(
            order.product_id,
            produced,
            f"mo:{order.id}:output",
            "Manufacturing Output",
            "1250",
            value_date=order.date,
            total_value=total,
        )
    finally:
        g.pop("production_order_id", None)
    remaining = order.quantity - produced
    release(order)
    if remaining:
        child = ManufacturingOrder(
            number=next_number("MO"),
            bom_id=order.bom_id,
            product_id=order.product_id,
            quantity=remaining,
            conversion_cost=order.conversion_cost - planned_cost,
            actual_cost=0,
            state="Confirmed",
            date=order.date,
            request_key="backorder:" + str(order.id),
            lines=[
                ProductionComponent(
                    product_id=line.product_id,
                    quantity=line.quantity - dec(line.quantity * ratio, UNIT),
                )
                for line in order.lines
            ],
        )
        db.session.add(child)
        db.session.flush()
        remember(child)
        db.session.add(
            ProductionResult(order_id=child.id, parent_id=order.id, snapshot={})
        )
        snapshot["backorderId"] = child.id
        snapshot["backorderNumber"] = child.number
        reserve(child)
    snapshot["scrapCost"] = str(scrap_cost)
    result.snapshot = snapshot
    order.quantity = produced
    order.conversion_cost = conversion
    order.actual_cost = total
    order.state = "Done"
    db.session.flush()


def has_open_obligations(product_id):
    active = ("Draft", "Confirmed", "In Progress")
    output = db.session.scalar(
        select(ManufacturingOrder.id)
        .where(
            ManufacturingOrder.product_id == product_id,
            ManufacturingOrder.state.in_(active),
        )
        .limit(1)
    )
    component = db.session.scalar(
        select(ProductionComponent.id)
        .join(ManufacturingOrder, ManufacturingOrder.id == ProductionComponent.order_id)
        .where(
            ProductionComponent.product_id == product_id,
            ManufacturingOrder.state.in_(active),
        )
        .limit(1)
    )
    return output is not None or component is not None


def initialize():
    """Backfill active orders once, without rewriting or reposting historical completions."""
    for order in db.session.scalars(
        select(ManufacturingOrder)
        .where(ManufacturingOrder.state.in_(("Confirmed", "In Progress")))
        .order_by(ManufacturingOrder.date, ManufacturingOrder.id)
    ):
        if not db.session.scalar(
            select(MaterialReservation.order_id)
            .where(MaterialReservation.order_id == order.id)
            .limit(1)
        ):
            reserve(order)
