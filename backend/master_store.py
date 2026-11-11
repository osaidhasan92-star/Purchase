"""Canonical, indexed relational master data with a legacy read adapter.

The aggregate contains only a migration marker after migration. Extra legacy
attributes are preserved per record, never as a second authoritative collection.
"""

from copy import deepcopy
from sqlalchemy import select, func, or_
from .app import db

MARKER = "_relationalMasters"


class MasterColumns:
    id = db.Column(db.String(64), primary_key=True)
    original_id = db.Column(db.JSON, nullable=False)
    position = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(160), nullable=False, index=True)
    search_name = db.Column(db.String(160), nullable=False, index=True)
    category = db.Column(db.String(100), nullable=False, default="", index=True)
    extras = db.Column(db.JSON, nullable=False, default=dict)


class PartnerColumns:
    contact = db.Column(db.String(160), nullable=False, default="")
    phone = db.Column(db.String(80), nullable=False, default="")
    email = db.Column(db.String(254), nullable=False, default="")
    status = db.Column(db.String(40), nullable=False, default="Active", index=True)


class Customer(MasterColumns, PartnerColumns, db.Model):
    __tablename__ = "master_customer"
    code = db.Column(db.String(80), nullable=False, default="", index=True)
    payment_terms = db.Column(db.String(40), nullable=False, default="Cash")
    credit_limit = db.Column(db.Numeric(20, 2), nullable=False, default=0)
    address = db.Column(db.Text, nullable=False, default="")


class Vendor(MasterColumns, PartnerColumns, db.Model):
    __tablename__ = "master_vendor"
    trn = db.Column(db.String(100), nullable=False, default="", index=True)


class Product(MasterColumns, db.Model):
    __tablename__ = "master_product"
    sku = db.Column(db.String(80), nullable=False, default="", index=True)
    unit = db.Column(db.String(40), nullable=False, default="Each")
    rate = db.Column(db.Numeric(20, 2), nullable=False, default=0)
    product_type = db.Column(db.String(12), nullable=False, default="stock")


class Lead(MasterColumns, db.Model):
    __tablename__ = "crm_lead"
    customer_id = db.Column(db.String(64), index=True)
    contact = db.Column(db.String(160), nullable=False, default="")
    email = db.Column(db.String(254), nullable=False, default="")
    stage = db.Column(db.String(80), nullable=False, default="New", index=True)
    value = db.Column(db.Numeric(20, 2), nullable=False, default=0)
    currency = db.Column(db.String(12), nullable=False, default="PKR")
    source = db.Column(db.String(160), nullable=False, default="")
    expected_close = db.Column(db.String(10), nullable=False, default="", index=True)
    status = db.Column(db.String(40), nullable=False, default="Active", index=True)
    notes = db.Column(db.Text, nullable=False, default="")
    owner_id = db.Column(db.String(64), index=True)
    created_by = db.Column(db.String(64), index=True)


class Reminder(MasterColumns, db.Model):
    __tablename__ = "crm_reminder"
    lead_id = db.Column(db.String(64), index=True)
    reminder_type = db.Column(db.String(40), nullable=False, default="Call")
    due_date = db.Column(db.String(10), nullable=False, default="", index=True)
    notes = db.Column(db.Text, nullable=False, default="")
    done = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_by = db.Column(db.String(64), index=True)


MODELS = {
    "customers": Customer,
    "vendors": Vendor,
    "products": Product,
    "leads": Lead,
    "reminders": Reminder,
}
COMMON = dict(name="name", category="category")
PARTNER = dict(contact="contact", phone="phone", email="email", status="status")
FIELDS = {
    "customers": {
        **COMMON,
        **PARTNER,
        "code": "code",
        "paymentTerms": "payment_terms",
        "creditLimit": "credit_limit",
        "address": "address",
    },
    "vendors": {**COMMON, **PARTNER, "trn": "trn"},
    "products": {
        **COMMON,
        "sku": "sku",
        "unit": "unit",
        "rate": "rate",
        "productType": "product_type",
    },
    "leads": dict(
        customerId="customer_id",
        customerName="name",
        contact="contact",
        email="email",
        stage="stage",
        value="value",
        currency="currency",
        source="source",
        expectedClose="expected_close",
        status="status",
        notes="notes",
        ownerId="owner_id",
        createdBy="created_by",
    ),
    "reminders": dict(
        leadId="lead_id",
        leadName="name",
        type="reminder_type",
        dueDate="due_date",
        notes="notes",
        done="done",
        createdBy="created_by",
    ),
}
DEFAULTS = dict(
    name="",
    category="",
    contact="",
    phone="",
    email="",
    status="Active",
    code="",
    paymentTerms="Cash",
    creditLimit=0,
    address="",
    trn="",
    sku="",
    unit="Each",
    rate=0,
    customerId=None,
    customerName="",
    stage="New",
    value=0,
    currency="PKR",
    source="",
    expectedClose="",
    notes="",
    ownerId=None,
    createdBy=None,
    leadId=None,
    leadName="",
    type="Call",
    dueDate="",
    done=False,
)


def record(key, row):
    """Round-trip original field presence/types for old clients and version hashes."""
    extras = deepcopy(row.extras)
    present = extras.pop("_fields", list(FIELDS[key]))
    numeric_ids = extras.pop("_numericIds", [])
    null_fields = extras.pop("_nullFields", [])
    result = {**extras, "id": row.original_id}
    for field, column in FIELDS[key].items():
        if field in present:
            value = getattr(row, column)
            if field in numeric_ids and value is not None:
                value = int(value)
            result[field] = (
                None
                if field in null_fields
                else (
                    float(value) if field in ("rate", "creditLimit", "value") else value
                )
            )
    return result


def read(key):
    return [
        record(key, row)
        for row in db.session.scalars(
            select(MODELS[key]).order_by(MODELS[key].position)
        )
    ]


def write_one(key, value, position, row=None):
    if row is None:
        row = MODELS[key](id=str(value["id"]))
        db.session.add(row)
    row.original_id, row.position = value["id"], position
    row.name = str(
        value.get("name", value.get("customerName", value.get("leadName", "")))
    )
    row.category = str(value.get("category", ""))
    row.search_name = row.name.casefold()
    row.extras = {
        **{
            k: deepcopy(v)
            for k, v in value.items()
            if k not in FIELDS[key] and k != "id"
        },
        "_fields": [k for k in FIELDS[key] if k in value],
        "_numericIds": [
            k for k in ("customerId", "leadId") if isinstance(value.get(k), int)
        ],
        "_nullFields": [k for k in FIELDS[key] if k in value and value[k] is None],
    }
    for field, column in FIELDS[key].items():
        default = (
            ("service" if str(value.get("unit", "")).lower() == "service" else "stock")
            if field == "productType"
            else DEFAULTS[field]
        )
        item = (
            value.get(field, default)
            if value.get(field, default) is not None
            else default
        )
        if (
            field in ("customerId", "leadId", "ownerId", "createdBy")
            and item is not None
        ):
            item = str(item)
        setattr(row, column, item)
    return row


def write(key, records):
    existing = {row.id: row for row in db.session.scalars(select(MODELS[key]))}
    for position, value in enumerate(records):
        write_one(key, value, position, existing.pop(str(value["id"]), None))
    for row in existing.values():
        db.session.delete(row)


def project(stored):
    if not stored.get(MARKER):
        return stored
    result = dict(stored)
    result.pop(MARKER, None)
    result.update({key: read(key) for key in MODELS})
    return result


def persist(data):
    for key in MODELS:
        write(key, data.get(key, []))
    return {
        **{key: value for key, value in data.items() if key not in MODELS},
        MARKER: 1,
    }


def page(key, number, size, search):
    model = MODELS[key]
    columns = [model.search_name, model.category]
    columns += (
        [model.sku] if key == "products" else [model.contact, model.email, model.phone]
    )
    columns += (
        [model.code] if key == "customers" else [model.trn] if key == "vendors" else []
    )
    query = select(model)
    if search:
        # Bound values + escaped wildcards: user input is literal text, never SQL syntax.
        term = (
            "%"
            + search.casefold()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            + "%"
        )
        query = query.where(
            or_(*(column.ilike(term, escape="\\") for column in columns))
        )
    total = db.session.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.session.scalars(
        query.order_by(model.search_name, model.id)
        .offset((number - 1) * size)
        .limit(size)
    )
    return [record(key, row) for row in rows], total
