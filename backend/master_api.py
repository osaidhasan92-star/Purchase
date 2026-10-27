"""Bounded, record-level relational APIs for shared product/vendor masters."""

from copy import deepcopy
import json
import math
import re
import secrets
import time
from flask import Blueprint, g, jsonify, request
from sqlalchemy import select, func, update
from .app import db, Document, app_document, body, problem, audit, utcnow, digest
from .permissions import allowed
from .erp import lock, dec, sync_products, next_number
from .master_store import MODELS, FIELDS, MARKER, record, page as sql_page, write_one

bp = Blueprint("master_records", __name__, url_prefix="/api")


class MasterRequest(db.Model):
    __tablename__ = "master_request"
    resource = db.Column(db.String(20), primary_key=True)
    actor = db.Column(db.String(64), primary_key=True)
    request_key = db.Column(db.String(100), primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    identity = db.Column(db.String(64), nullable=False)


def configuration():
    return app_document().stored_data


def permit(key, action="view"):
    module = "sales_customers" if key == "customers" else key
    if not allowed(g.user, configuration(), module, action):
        problem(module + " " + action + " permission required", 403)
    if not configuration().get(MARKER):
        problem(
            "Run flask --app backend.app migrate-storage before using this screen", 503
        )


def version(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")))


def output(value):
    return {**value, "version": version(value)}


def paging(key):
    permit(key)
    try:
        number, size = int(request.args.get("page", "1")), int(
            request.args.get("pageSize", "25")
        )
    except ValueError:
        problem("Page and pageSize must be integers")
    if number < 1 or not 1 <= size <= 100:
        problem("Page must be positive; pageSize must be 1–100")
    search = request.args.get("search", "").strip()
    if len(search) > 160:
        problem("Search is too long")
    items, total = sql_page(key, number, size, search)
    return jsonify(
        items=[output(value) for value in items],
        total=total,
        page=number,
        pageSize=size,
    )


def values(key, data, previous=None):
    if set(data) - set(FIELDS[key]) - {"version", "requestKey"}:
        problem("Unknown " + key + " fields")
    source = {**(previous or {}), **data}
    result = {}
    limits = dict(
        name=160,
        category=100,
        contact=160,
        phone=80,
        email=254,
        trn=100,
        sku=80,
        unit=40,
    )
    for field in FIELDS[key]:
        if field in ("rate",):
            value = source.get(field, 0)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1e12
            ):
                problem("Rate must be a finite non-negative number")
            result[field] = float(dec(value))
        else:
            value = source.get(
                field,
                (
                    "Active"
                    if field == "status"
                    else (
                        "Each"
                        if field == "unit"
                        else "stock" if field == "productType" else ""
                    )
                ),
            )
            if not isinstance(value, str) or len(value.strip()) > limits.get(field, 40):
                problem("Invalid " + field)
            result[field] = value.strip()
    if not result["name"]:
        problem("Name is required")
    if key == "vendors":
        if result["status"] not in ("Active", "Inactive"):
            problem("Invalid vendor status")
        if result["email"] and not re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+", result["email"]
        ):
            problem("Enter a valid email address")
    else:
        if result["productType"] not in ("stock", "service"):
            problem("Product type must be stock or service")
        if not result["unit"]:
            problem("Unit is required")
    return result


def save_record(key, identity, normalize):
    """A native save touches one SQL master and metadata, never the aggregate lists."""
    permit(key, "create" if identity is None else "edit")
    data = body()
    lock()
    doc = app_document()
    db.session.refresh(doc)
    model = MODELS[key]
    row = db.session.get(model, str(identity)) if identity is not None else None
    old = record(key, row) if row else None
    if old and key in ("leads", "reminders"):
        from .permissions import in_scope

        if not in_scope(g.user, old, key, doc.data):
            problem("Record not found", 404)
    if identity is not None:
        if old is None:
            problem("Record not found", 404)
        if not data.get("version"):
            problem("Record version is required", 428)
        if data["version"] != version(old):
            problem("This record changed. Reload before saving.", 409)
    normalized = normalize(data, old)
    if identity is None:
        request_key = data.get("requestKey", "")
        if not isinstance(request_key, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{8,100}", request_key
        ):
            problem("A unique requestKey is required")
        fingerprint = version(normalized)
        receipt = db.session.get(MasterRequest, (key, g.user.id, request_key))
        if receipt:
            if receipt.fingerprint != fingerprint:
                problem("This request key was already used with different details", 409)
            existing = db.session.get(model, receipt.identity)
            if not existing:
                problem(
                    "The record created by this request is no longer available", 409
                )
            return record(key, existing), doc.revision
        # Existing customer API request keys survive the migration as per-record metadata.
        prior = db.session.scalar(
            select(model)
            .where(
                model.extras["creationRequestKey"].as_string() == request_key,
                model.extras["createdBy"].as_string() == g.user.id,
            )
            .limit(1)
        )
        if prior:
            value = record(key, prior)
            if any(value.get(k) != v for k, v in normalized.items()):
                problem("This request key was already used with different details", 409)
            return value, doc.revision
        identity = int(time.time() * 1000) * 1000 + secrets.randbelow(1000)
        while db.session.get(model, str(identity)):
            identity += 1
        changed = {
            **normalized,
            "id": identity,
            "createdBy": g.user.id,
            "createdAt": utcnow(),
            "creationRequestKey": request_key,
        }
        if key == "customers":
            code = next_number("CUS")
            while db.session.scalar(
                select(model.id).where(model.code == code).limit(1)
            ):
                code = next_number("CUS")
            changed.update(code=code, ownerId=g.user.id, managerId=g.user.manager_id)
        position = (
            (db.session.scalar(select(func.min(model.position))) or 0) - 1
            if key in ("leads", "reminders")
            else (db.session.scalar(select(func.max(model.position))) or 0) + 1
        )
        db.session.add(
            MasterRequest(
                resource=key,
                actor=g.user.id,
                request_key=request_key,
                fingerprint=fingerprint,
                identity=str(identity),
            )
        )
    else:
        changed = {**old, **normalized}
        position = row.position
    if key in ("leads", "reminders"):
        from .app import merge_collection
        from .permissions import in_scope

        state = doc.data
        if old and not in_scope(g.user, old, key, state):
            problem("Record not found", 404)
        changed = merge_collection(key, [changed], [old] if old else [], state, key)[0]
    write_one(key, changed, position, row)
    if key == "products":
        sync_products({"products": [changed]})
    result = db.session.execute(
        update(Document)
        .where(Document.name == "app", Document.revision == doc.revision)
        .values(revision=doc.revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        problem("Another user saved newer data. Reload before trying again.", 409)
    audit(("Updated " if old else "Created ") + key, {"recordId": identity})
    revision = doc.revision + 1
    db.session.commit()
    return record(key, db.session.get(model, str(identity))), revision


@bp.get("/vendors")
@bp.get("/products")
def list_records():
    return paging(request.path.rsplit("/", 1)[-1])


@bp.get("/vendors/<identity>")
@bp.get("/products/<identity>")
def details(identity):
    key = request.path.split("/")[-2]
    permit(key)
    row = db.session.get(MODELS[key], identity)
    if row is None:
        problem("Record not found", 404)
    return jsonify(record=output(record(key, row)))


@bp.route("/vendors", methods=["POST"])
@bp.route("/vendors/<identity>", methods=["PATCH"])
@bp.route("/products", methods=["POST"])
@bp.route("/products/<identity>", methods=["PATCH"])
def save(identity=None):
    key = request.path.split("/")[2]
    value, revision = save_record(
        key, identity, lambda data, old: values(key, data, old)
    )
    return jsonify(record=output(value), revision=revision)
