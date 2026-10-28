"""Small indexed conflict keys; legacy duplicates remain readable for correction."""

from sqlalchemy import select, delete, Index
from .app import db, Document, problem
from .trade_store import version


class ConflictKey(db.Model):
    __tablename__ = "workflow_conflict_key"
    domain = db.Column(db.String(40), primary_key=True)
    kind = db.Column(db.String(20), primary_key=True)
    record_id = db.Column(db.String(64), primary_key=True)
    token = db.Column(db.String(64), nullable=False, index=True)
    __table_args__ = (db.Index("ix_workflow_key_record", "domain", "record_id"),)


class LegacyLink(db.Model):
    __tablename__ = "workflow_legacy_link"
    domain = db.Column(db.String(40), primary_key=True)
    field = db.Column(db.String(40), primary_key=True)
    record_id = db.Column(db.String(64), primary_key=True)
    parent_domain = db.Column(db.String(40), nullable=False)
    parent_id = db.Column(db.String(64), nullable=False)
    __table_args__ = (
        db.Index("ix_workflow_legacy_parent", "parent_domain", "parent_id", "domain"),
        db.Index("ix_workflow_legacy_record", "domain", "record_id"),
    )


def links(key, row):
    from .trade_store import REFERENCES

    expected = row.extras.get("_tradeMeta", {}).get("unresolved", {})
    existing = {
        r.field: r
        for r in db.session.scalars(
            select(LegacyLink).where(
                LegacyLink.domain == key, LegacyLink.record_id == row.id
            )
        )
    }
    for field, value in expected.items():
        if field not in REFERENCES[key]:
            continue
        link = existing.pop(field, None)
        if link is None:
            link = LegacyLink(domain=key, field=field, record_id=row.id)
            db.session.add(link)
        link.parent_domain = REFERENCES[key][field]
        link.parent_id = str(value)
    for link in existing.values():
        db.session.delete(link)


NUMBER_REGISTERS = {
    "requests",
    "rfqs",
    "quotations",
    "orders",
    "receipts",
    "invoices",
    "payments",
    "salesQuotations",
    "salesOrders",
    "deliveries",
    "customerInvoices",
    "customerPayments",
}


def tokens(key, value):
    from .trade_store import SPECS

    result = {}
    if key in NUMBER_REGISTERS:
        raw = str(value.get(SPECS[key][1], "")).strip().lower()
        if raw:
            result["number"] = version(
                [str(value.get("vendorId")) if key == "invoices" else "", raw]
            )
    if key in ("payments", "customerPayments"):
        raw = str(value.get("referenceNo", "")).casefold()
        if raw:
            result["reference"] = version(raw)
    if key == "employees":
        if value.get("employeeId"):
            result["number"] = version(str(value["employeeId"]).casefold())
        if value.get("candidateId"):
            result["candidate"] = version(str(value["candidateId"]))
    return result


def replace(key, value):
    identity = str(value["id"])
    expected = tokens(key, value)
    rows = {
        r.kind: r
        for r in db.session.scalars(
            select(ConflictKey).where(
                ConflictKey.domain == key, ConflictKey.record_id == identity
            )
        )
    }
    for kind, token in expected.items():
        row = rows.pop(kind, None)
        if row is None:
            db.session.add(
                ConflictKey(domain=key, kind=kind, record_id=identity, token=token)
            )
        else:
            row.token = token
    for row in rows.values():
        db.session.delete(row)


def remove(key, identity):
    db.session.execute(
        delete(LegacyLink).where(
            LegacyLink.domain == key, LegacyLink.record_id == str(identity)
        )
    )
    db.session.execute(
        delete(ConflictKey).where(
            ConflictKey.domain == key, ConflictKey.record_id == str(identity)
        )
    )


def number_taken(key, value):
    token = tokens(key, value).get("number")
    return bool(
        token
        and db.session.scalar(
            select(ConflictKey.record_id)
            .where(
                ConflictKey.domain == key,
                ConflictKey.kind == "number",
                ConflictKey.token == token,
            )
            .limit(1)
        )
    )


def check(key, value):
    for kind, token in tokens(key, value).items():
        if db.session.scalar(
            select(ConflictKey.record_id)
            .where(
                ConflictKey.domain == key,
                ConflictKey.kind == kind,
                ConflictKey.token == token,
                ConflictKey.record_id != str(value["id"]),
            )
            .limit(1)
        ):
            problem(
                "Duplicate "
                + (
                    "employee ID"
                    if key == "employees" and kind == "number"
                    else (
                        "candidate onboarding"
                        if kind == "candidate"
                        else (
                            "payment reference"
                            if kind == "reference"
                            else "document number"
                        )
                    )
                ),
                409,
            )


def initialize():
    """One-time backfill uses narrow headers, never whole business projections."""
    from . import trade_store as trade, hr_store as hr

    marker = db.session.get(Document, "workflow_indexes")
    if marker and marker.stored_data.get("version") == 2:
        return
    db.session.execute(delete(ConflictKey))
    db.session.execute(delete(LegacyLink))
    for key, model in trade.MODELS.items():
        for rid, extras in db.session.execute(
            select(model.id, model.extras["_tradeMeta"]["unresolved"])
        ):
            for field, value in (extras or {}).items():
                if field in trade.REFERENCES[key]:
                    db.session.add(
                        LegacyLink(
                            domain=key,
                            field=field,
                            record_id=rid,
                            parent_domain=trade.REFERENCES[key][field],
                            parent_id=str(value),
                        )
                    )
    for key, model in hr.MODELS.items():
        for field in ("name", "position"):
            name = (
                "ix_workflow_"
                + model.__tablename__
                + "_"
                + ("label" if field == "name" else "position")
            )
            index = next((i for i in model.__table__.indexes if i.name == name), None)
            if index is None:
                index = Index(name, getattr(model, field))
            index.create(bind=db.session.connection(), checkfirst=True)
    for key in NUMBER_REGISTERS:
        model = trade.MODELS[key]
        cols = [model.id, model.number]
        if key == "invoices":
            cols.extend(
                [model.vendor_id, model.extras["_tradeMeta"]["unresolved"]["vendorId"]]
            )
        if key in ("payments", "customerPayments"):
            cols.append(model.extras["referenceNo"])
        for row in db.session.execute(select(*cols)):
            value = {"id": row[0], trade.SPECS[key][1]: row[1]}
            if key == "invoices":
                value["vendorId"] = row[2] if row[2] is not None else row[3]
            if key in ("payments", "customerPayments"):
                value["referenceNo"] = row[2] or ""
            replace(key, value)
    for e in db.session.execute(
        select(hr.Employee.id, hr.Employee.number, hr.Employee.extras["candidateId"])
    ):
        replace("employees", dict(id=e[0], employeeId=e[1], candidateId=e[2]))
    if not marker:
        marker = Document(
            name="workflow_indexes", stored_data={"version": 2}, revision=1
        )
        db.session.add(marker)
    else:
        marker.stored_data = {"version": 2}


def revalidate_actor():
    """A command waiting for the ERP lock must not use a revoked session/old role."""
    import time
    from flask import g
    from .app import LoginSession

    session = db.session.get(
        LoginSession, g.login_session.token_hash, populate_existing=True
    )
    db.session.refresh(g.user)
    from .app import app_document

    db.session.refresh(app_document())
    if not session or session.expires <= time.time() or not g.user.active:
        problem("Please sign in again", 401)


def ready():
    marker = db.session.get(Document, "workflow_indexes")
    if not marker or marker.stored_data.get("version") != 2:
        problem("Run init-db and migrate-storage to initialize workflow indexes", 503)
