"""Typed CRM tracking registers with exact historical per-record round trips."""

from copy import deepcopy
from decimal import Decimal
from sqlalchemy import select
from .app import db

MARKER = "_relationalCRMRegisters"


class Columns:
    id = db.Column(db.String(64), primary_key=True)
    original_id = db.Column(db.JSON, nullable=False)
    position = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(500), nullable=False, default="", index=True)
    status = db.Column(db.String(80), nullable=False, default="", index=True)
    extras = db.Column(db.JSON, nullable=False, default=dict)


class Company(Columns, db.Model):
    __tablename__ = "crm_company"
    industry = db.Column(db.String(160), nullable=False, default="", index=True)
    contact = db.Column(db.String(160), nullable=False, default="")
    email = db.Column(db.String(254), nullable=False, default="")
    phone = db.Column(db.String(80), nullable=False, default="")


class Quote(Columns, db.Model):
    __tablename__ = "crm_tracking_quote"
    number = db.Column(db.String(100), nullable=False, default="", index=True)
    lead_id = db.Column(db.String(64), index=True)
    amount = db.Column(db.Numeric(20, 2), nullable=False, default=0)
    currency = db.Column(db.String(12), nullable=False, default="PKR", index=True)
    quote_date = db.Column(db.String(40), nullable=False, default="", index=True)
    valid_until = db.Column(db.String(40), nullable=False, default="")
    created_by = db.Column(db.String(64), index=True)
    owner_id = db.Column(db.String(64), index=True)


MODELS = {"companies": Company, "crmQuotes": Quote}
FIELDS = {
    "companies": dict(
        name="name",
        industry="industry",
        contact="contact",
        email="email",
        phone="phone",
        status="status",
    ),
    "crmQuotes": dict(
        quoteNo="number",
        companyName="name",
        leadId="lead_id",
        amount="amount",
        currency="currency",
        quoteDate="quote_date",
        validUntil="valid_until",
        status="status",
        createdBy="created_by",
        ownerId="owner_id",
    ),
}


def record(key, row):
    data = deepcopy(row.extras)
    present = data.pop("_fields", [])
    raw = data.pop("_raw", {})
    result = {**data, "id": row.original_id}
    for field, column in FIELDS[key].items():
        if field in present:
            result[field] = raw[field] if field in raw else getattr(row, column)
    return result


def write_one(key, value, position, row=None):
    if row is None:
        row = MODELS[key](id=str(value["id"]))
        db.session.add(row)
    row.original_id = value["id"]
    row.position = position
    row.extras = {
        **{
            k: deepcopy(v)
            for k, v in value.items()
            if k not in FIELDS[key] and k != "id"
        },
        "_fields": [k for k in FIELDS[key] if k in value],
        "_raw": {
            k: deepcopy(value[k])
            for k in FIELDS[key]
            if k in value
            and (value[k] is None or not isinstance(value[k], str) or k == "amount")
        },
    }
    for field, column in FIELDS[key].items():
        v = value.get(field)
        if field == "amount":
            v = Decimal(str(v or 0))
            if not v.is_finite() or abs(v) >= Decimal("1e18"):
                raise ValueError("CRM quote amount cannot be stored safely")
        elif field in ("leadId", "createdBy", "ownerId"):
            v = str(v) if v is not None else None
        else:
            v = str(v or "")
        setattr(row, column, v)
    return row


def read(key):
    return [
        record(key, r)
        for r in db.session.scalars(select(MODELS[key]).order_by(MODELS[key].position))
    ]


def project(stored):
    if not stored.get(MARKER):
        return stored
    result = dict(stored)
    result.pop(MARKER, None)
    result.update({key: read(key) for key in MODELS})
    return result


def persist(data):
    for key, model in MODELS.items():
        old = {r.id: r for r in db.session.scalars(select(model))}
        seen = set()
        for i, value in enumerate(data.get(key, [])):
            identity = str(value["id"])
            seen.add(identity)
            write_one(key, value, i, old.get(identity))
        for identity, row in old.items():
            if identity not in seen:
                db.session.delete(row)
    return {**{k: v for k, v in data.items() if k not in MODELS}, MARKER: 1}
