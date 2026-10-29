"""Canonical Sales/Purchasing headers, lines and RFQ vendor relationships.

Known domain fields are typed columns. Extension JSON preserves historical/custom
attributes, field presence and original ID types; no whole-register JSON is kept.
Legacy dangling references are retained explicitly, never fabricated as parents.
New resource commands reject dangling references.
"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from sqlalchemy import select, func
from .app import db

MARKER = "_relationalTrade"
# Dependency order also controls migration insertion/deletion.
SPECS = {
    "requests": ("purchase_request", "requestNo", "date", None, {}),
    "rfqs": ("rfq", "rfqNo", "issueDate", None, {"requestId": "requests"}),
    "quotations": (
        "vendor_quotation",
        "quotationNo",
        "quoteDate",
        "vendors",
        {"rfqId": "rfqs"},
    ),
    "comparisons": (
        "comparison",
        "selectedQuotationNo",
        "comparedAt",
        "vendors",
        {"rfqId": "rfqs", "selectedQuotationId": "quotations"},
    ),
    "orders": (
        "purchase_order",
        "poNo",
        "poDate",
        "vendors",
        {"quotationId": "quotations", "rfqId": "rfqs"},
    ),
    "receipts": (
        "goods_receipt",
        "grnNo",
        "receivedDate",
        "vendors",
        {"poId": "orders", "quotationId": "quotations"},
    ),
    "invoices": (
        "vendor_bill",
        "invoiceNo",
        "invoiceDate",
        "vendors",
        {"poId": "orders", "quotationId": "quotations"},
    ),
    "payments": (
        "vendor_payment",
        "paymentNo",
        "paymentDate",
        "vendors",
        {"invoiceId": "invoices", "poId": "orders"},
    ),
    "salesQuotations": (
        "sales_quotation",
        "quotationNo",
        "quotationDate",
        "customers",
        {"leadId": "leads"},
    ),
    "salesOrders": (
        "sales_order",
        "orderNo",
        "orderDate",
        "customers",
        {"quotationId": "salesQuotations", "leadId": "leads"},
    ),
    "deliveries": (
        "delivery",
        "deliveryNo",
        "deliveryDate",
        "customers",
        {"orderId": "salesOrders", "quotationId": "salesQuotations"},
    ),
    "customerInvoices": (
        "customer_invoice",
        "invoiceNo",
        "invoiceDate",
        "customers",
        {
            "orderId": "salesOrders",
            "quotationId": "salesQuotations",
            "deliveryId": "deliveries",
        },
    ),
    "customerPayments": (
        "customer_payment",
        "paymentNo",
        "paymentDate",
        "customers",
        {"invoiceId": "customerInvoices", "orderId": "salesOrders"},
    ),
}
TABLES = {key: "trade_" + spec[0] for key, spec in SPECS.items()}
SOURCE_LINES = {
    "rfqs": ("requests", "requestId", "lineItems"),
    "quotations": ("rfqs", "rfqId", "items"),
    "orders": ("quotations", "quotationId", "items"),
    "receipts": ("orders", "poId", "items"),
    "invoices": ("orders", "poId", "items"),
    "salesOrders": ("salesQuotations", "quotationId", "items"),
    "deliveries": ("salesOrders", "orderId", "items"),
    "customerInvoices": ("salesOrders", "orderId", "items"),
}

NUMBERS = (
    "total",
    "amount",
    "subtotal",
    "taxAmount",
    "taxPercent",
    "paidAmount",
    "balance",
    "shippingCharges",
    "additionalDiscount",
    "estimatedTotal",
)
LINE_NUMBERS = (
    "quantity",
    "rate",
    "quotedRate",
    "taxPercent",
    "discountPercent",
    "subtotal",
    "discountAmount",
    "taxAmount",
    "tax",
    "total",
    "orderedQty",
    "remainingQty",
    "receivedQty",
    "acceptedQty",
    "rejectedQty",
    "deliveredQty",
)
COMMON = {
    "status": "status",
    "createdBy": "created_by",
    "ownerId": "owner_id",
    "managerId": "manager_id",
    "notes": "notes",
    "dueDate": "due_date",
    "department": "department",
    "requester": "requester",
}
MODELS, LINE_MODELS, FIELDS, REFERENCES = {}, {}, {}, {}


def snake(value):
    return "".join("_" + c.lower() if c.isupper() else c for c in value)


class HeaderColumns:
    id = db.Column(db.String(64), primary_key=True)
    original_id = db.Column(db.JSON, nullable=False)
    position = db.Column(db.Integer, nullable=False, index=True)
    number = db.Column(db.String(160), index=True)
    document_date = db.Column(db.String(40), index=True)
    status = db.Column(db.String(80), index=True)
    created_by = db.Column(db.String(64), index=True)
    owner_id = db.Column(db.String(64), index=True)
    manager_id = db.Column(db.String(64))
    partner_name = db.Column(db.String(160), index=True)
    search_text = db.Column(db.Text, nullable=False, default="")
    department = db.Column(db.String(160), index=True)
    requester = db.Column(db.String(160))
    notes = db.Column(db.Text)
    due_date = db.Column(db.String(40), index=True)
    record_version = db.Column(db.String(64), nullable=False)
    extras = db.Column(db.JSON, nullable=False, default=dict)


for key, (table, number, date, partner, relations) in SPECS.items():
    fields = dict(COMMON)
    if number:
        fields[number] = "number"
    fields[date] = "document_date"
    refs = dict(relations)
    if partner:
        refs["customerId" if partner == "customers" else "vendorId"] = partner
        fields["customerName" if partner == "customers" else "vendorName"] = (
            "partner_name"
        )
    fields.update({field: snake(field) for field in (*NUMBERS, *refs)})
    attrs = {"__tablename__": TABLES[key]}
    for field in NUMBERS:
        attrs[snake(field)] = db.Column(db.Numeric(38, 18))
    for field, target in refs.items():
        target_table = TABLES.get(
            target,
            {
                "customers": "master_customer",
                "vendors": "master_vendor",
                "leads": "crm_lead",
            }.get(target),
        )
        attrs[snake(field)] = db.Column(
            db.String(64),
            db.ForeignKey(target_table + ".id", ondelete="RESTRICT"),
            index=True,
        )
    name = "Trade" + "".join(part.title() for part in table.split("_"))
    MODELS[key] = type(name, (HeaderColumns, db.Model), attrs)
    FIELDS[key], REFERENCES[key] = fields, refs
    # Every line belongs to a real header and has a stable ordinal (not a product-key join).
    line_attrs = {
        "__tablename__": TABLES[key] + "_line",
        "id": db.Column(db.Integer, primary_key=True),
        "header_id": db.Column(
            db.String(64),
            db.ForeignKey(TABLES[key] + ".id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        "slot": db.Column(db.String(20), nullable=False),
        "position": db.Column(db.Integer, nullable=False),
        "product_id": db.Column(
            db.String(64),
            db.ForeignKey("master_product.id", ondelete="RESTRICT"),
            index=True,
        ),
        "product_name": db.Column(db.String(160)),
        "description": db.Column(db.Text),
        "unit": db.Column(db.String(40)),
        "extras": db.Column(db.JSON, nullable=False),
        "__table_args__": (db.UniqueConstraint("header_id", "slot", "position"),),
    }
    if key in SOURCE_LINES:
        source_key = SOURCE_LINES[key][0]
        line_attrs["source_line_id"] = db.Column(
            db.Integer,
            db.ForeignKey(TABLES[source_key] + "_line.id", ondelete="RESTRICT"),
            index=True,
        )
    for field in LINE_NUMBERS:
        line_attrs[snake(field)] = db.Column(db.Numeric(38, 18))
    LINE_MODELS[key] = type(name + "Line", (db.Model,), line_attrs)
    MODELS[key].lines = db.relationship(
        LINE_MODELS[key],
        cascade="all, delete-orphan",
        order_by=(LINE_MODELS[key].slot, LINE_MODELS[key].position),
        lazy="select",
    )


class RFQVendor(db.Model):
    __tablename__ = "trade_rfq_vendor"
    id = db.Column(db.Integer, primary_key=True)
    rfq_id = db.Column(
        db.String(64),
        db.ForeignKey("trade_rfq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vendor_id = db.Column(
        db.String(64),
        db.ForeignKey("master_vendor.id", ondelete="RESTRICT"),
        index=True,
    )
    position = db.Column(db.Integer, nullable=False)
    snapshot = db.Column(db.JSON, nullable=False)
    __table_args__ = (db.UniqueConstraint("rfq_id", "position"),)


MODELS["rfqs"].vendors = db.relationship(
    RFQVendor, cascade="all, delete-orphan", order_by=RFQVendor.position, lazy="select"
)
LINE_FIELDS = {
    **{k: snake(k) for k in LINE_NUMBERS},
    "productId": "product_id",
    "productName": "product_name",
    "description": "description",
    "unit": "unit",
}


def version(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def encode(value, fields, references, available):
    extras = {k: deepcopy(v) for k, v in value.items() if k not in fields}
    meta = {"present": [k for k in fields if k in value], "types": {}, "unresolved": {}}
    columns = {}
    for field, column in fields.items():
        v = value.get(field)
        if v is None:
            columns[column] = None
            continue
        meta["types"][field] = (
            "int"
            if isinstance(v, int) and not isinstance(v, bool)
            else "float" if isinstance(v, float) else "string"
        )
        if field in references:
            target = references[field]
            if str(v) in available.get(target, set()):
                columns[column] = str(v)
            else:
                columns[column] = None
                meta["unresolved"][field] = deepcopy(v)
        else:
            columns[column] = (
                str(v) if field in ("createdBy", "ownerId", "managerId") else v
            )
    extras["_tradeMeta"] = meta
    return columns, extras


def decode(row, fields):
    extras = deepcopy(row.extras)
    meta = extras.pop("_tradeMeta")
    result = extras
    for field in meta["present"]:
        if field in meta["unresolved"]:
            value = meta["unresolved"][field]
        else:
            value = getattr(row, fields[field])
            if value is not None:
                if meta["types"].get(field) == "int":
                    value = int(value)
                elif meta["types"].get(field) == "float" or isinstance(value, Decimal):
                    value = float(value)
        result[field] = value
    return result


def record(key, row, with_lines=True):
    result = decode(row, FIELDS[key])
    slots = result.pop("_tradeSlots", [])
    has_vendors = result.pop("_tradeVendors", False)
    result["id"] = row.original_id
    if with_lines:
        for slot in slots:
            result[slot] = []
        for line in row.lines:
            if line.slot in slots:
                result[line.slot].append(decode(line, LINE_FIELDS))
        if has_vendors:
            result["vendors"] = [deepcopy(v.snapshot) for v in row.vendors]
    return result


def read(key):
    from sqlalchemy.orm import selectinload

    query = (
        select(MODELS[key])
        .options(selectinload(MODELS[key].lines))
        .order_by(MODELS[key].position, MODELS[key].id)
    )
    if key == "rfqs":
        query = query.options(selectinload(MODELS[key].vendors))
    return [record(key, row) for row in db.session.scalars(query)]


def available_ids(data):
    return {
        key: {str(v["id"]) for v in data.get(key, [])}
        for key in (*SPECS, "customers", "vendors", "products", "leads")
    }


def assign_header(key, value, row, available):
    columns, extras = encode(value, FIELDS[key], REFERENCES[key], available)
    slots = [
        field for field in ("items", "lineItems") if isinstance(value.get(field), list)
    ]
    for slot in slots:
        extras.pop(slot, None)
    extras.pop("id", None)
    extras["_tradeSlots"] = slots
    extras["_tradeVendors"] = key == "rfqs" and isinstance(value.get("vendors"), list)
    if extras["_tradeVendors"]:
        extras.pop("vendors", None)
    row.original_id = value["id"]
    row.record_version = version(value)
    for column, item in columns.items():
        setattr(row, column, item)
    row.extras = extras
    row.search_text = " ".join(
        str(value.get(k, "") or "")
        for k in (
            SPECS[key][1],
            "customerName",
            "vendorName",
            "requester",
            "department",
            "requestNo",
            "rfqNo",
            "poNo",
            "orderNo",
            "invoiceNo",
            "referenceNo",
        )
    ).casefold()


def assign_lines(key, value, row, available):
    slots = row.extras["_tradeSlots"]
    # Reuse existing rows by ordinal; avoid delete/insert collisions in PostgreSQL.
    existing = {(line.slot, line.position): line for line in row.lines}
    new = []
    for slot in slots:
        for position, item in enumerate(value[slot]):
            if not isinstance(item, dict):
                raise ValueError("Trade lines must be objects")
            line = existing.pop((slot, position), None) or LINE_MODELS[key](
                slot=slot, position=position
            )
            columns, extras = encode(
                item, LINE_FIELDS, {"productId": "products"}, available
            )
            for column, field_value in columns.items():
                setattr(line, column, field_value)
            line.extras = extras
            if key in SOURCE_LINES:
                source_key, source_field, source_slot = SOURCE_LINES[key]
                parent_id = getattr(row, FIELDS[key][source_field], None)
                source_model = LINE_MODELS[source_key]
                source_index = item.get("lineIndex", position)
                source_line = (
                    db.session.scalar(
                        select(source_model).where(
                            source_model.header_id == parent_id,
                            source_model.slot == source_slot,
                            source_model.position == source_index,
                        )
                    )
                    if parent_id
                    else None
                )
                if source_line and str(
                    decode(source_line, LINE_FIELDS).get("productId")
                ) != str(item.get("productId")):
                    source_line = None
                line.source_line_id = source_line.id if source_line else None
            new.append(line)
    row.lines = new
    if key == "rfqs":
        old = {v.position: v for v in row.vendors}
        vendors = []
        for position, snapshot in enumerate(
            value.get("vendors", []) if row.extras["_tradeVendors"] else []
        ):
            v = old.get(position) or RFQVendor(position=position)
            v.vendor_id = (
                str(snapshot.get("id"))
                if str(snapshot.get("id")) in available.get("vendors", set())
                else None
            )
            v.snapshot = deepcopy(snapshot)
            vendors.append(v)
        row.vendors = vendors


def persist(data):
    """Write differences only; exact legacy register order is retained."""
    available = available_ids(data)
    pending = []
    removed = []
    # Insert headers first so valid forward/cross references can use actual foreign keys.
    for key, model in MODELS.items():
        existing = {row.id: row for row in db.session.scalars(select(model))}
        for position, value in enumerate(data.get(key, [])):
            row = existing.pop(str(value["id"]), None)
            if row is None:
                row = model(
                    id=str(value["id"]),
                    original_id=value["id"],
                    position=position,
                    record_version=version(value),
                    extras={},
                    search_text="",
                )
                db.session.add(row)
                db.session.flush()  # FK targets in this dependency order now exist.
            changed = row.record_version != version(value) or not row.extras.get(
                "_tradeMeta"
            )
            if changed:
                assign_header(key, value, row, available)
                pending.append((key, value, row))
            row.position = position
        removed.extend(existing.values())
        db.session.flush()
    for key, value, row in pending:
        assign_lines(key, value, row, available)
        from .workflow_keys import replace, links

        replace(key, value)
        links(key, row)
    db.session.flush()
    for row in reversed(removed):
        from .workflow_keys import remove

        key = next(k for k, m in MODELS.items() if isinstance(row, m))
        remove(key, row.id)
        db.session.delete(row)
    return {**{k: v for k, v in data.items() if k not in SPECS}, MARKER: 1}


def project(stored):
    if not stored.get(MARKER):
        return stored
    data = {k: v for k, v in stored.items() if k != MARKER}
    data.update({key: read(key) for key in SPECS})
    return data
