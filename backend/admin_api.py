"""Bounded Administration resources and versioned account/configuration commands."""

from copy import deepcopy
from datetime import date, timedelta
from functools import wraps
import re
import secrets
from flask import Blueprint, g, jsonify, request
from sqlalchemy import select, func, or_
from sqlalchemy.orm import aliased
from werkzeug.security import generate_password_hash, check_password_hash
from .app import (
    db,
    User,
    LoginSession,
    Audit,
    app_document,
    require_admin,
    body,
    problem,
    audit,
    check_password,
    validate_json,
    validate_company,
)
from .permissions import allowed, MODULES, ACTIONS
from .erp import lock, day
from .trade_store import version
from .finance_api import paged, search_term
from .trade_service import text

bp = Blueprint("administration", __name__, url_prefix="/api/administration")


class Command(db.Model):
    __tablename__ = "administration_command"
    actor_id = db.Column(db.String(64), primary_key=True)
    request_key = db.Column(db.String(100), primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    resource = db.Column(db.String(20), nullable=False)
    identity = db.Column(db.String(80), nullable=False)


def admin(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        require_admin()
        return fn(*a, **kw)

    return wrapped


def user_record(u):
    value = u.public()
    # A credential reset invalidates stale edits, without disclosing the hash.
    return {**value, "version": version([value, u.password_hash])}


def user(identity):
    if not isinstance(identity, str):
        problem("User not found", 404)
    u = db.session.get(User, identity)
    if not u:
        problem("User not found", 404)
    return u


def role_record(name):
    value = app_document().stored_data.get("roles", {}).get(name)
    if value is None:
        problem("Role not found", 404)
    return dict(
        name=name,
        permissions={
            m: {
                a: (
                    True
                    if name == "Admin"
                    else value.get("permissions", {}).get(m, {}).get(a) is True
                )
                for a in ACTIONS
            }
            for m in MODULES
        },
        version=version(value),
    )


def company_record():
    value = deepcopy(app_document().stored_data.get("company", {}))
    return dict(values=value, version=version(value))


@bp.get("/summary")
@admin
def summary():
    return jsonify(
        users=db.session.scalar(select(func.count()).select_from(User)),
        active=db.session.scalar(
            select(func.count()).select_from(User).where(User.active.is_(True))
        ),
        admins=db.session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "Admin", User.active.is_(True))
        ),
        roles=len(app_document().stored_data["roles"]),
    )


@bp.get("/users")
@admin
def users():
    manager = aliased(User)
    q = select(User, manager.name.label("managerName")).outerjoin(
        manager, User.manager_id == manager.id
    )
    term = search_term()
    if term:
        q = q.where(
            or_(
                *(
                    func.lower(c).like(term, escape="\\")
                    for c in (User.name, User.email, User.role)
                )
            )
        )
    if request.args.get("active"):
        if request.args["active"] not in ("true", "false"):
            problem("Invalid active filter")
        q = q.where(User.active.is_(request.args["active"] == "true"))
    if request.args.get("role"):
        q = q.where(User.role == request.args["role"])
    rows, meta = paged(q, [User.name, User.id])
    return jsonify(
        items=[{**user_record(r[0]), "managerName": r[1]} for r in rows], **meta
    )


@bp.get("/users/<identity>")
@admin
def detail(identity):
    return jsonify(record=user_record(user(identity)))


@bp.get("/managers")
@admin
def managers():
    q = select(User.id, User.name, User.email).where(User.active.is_(True))
    if request.args.get("exclude"):
        q = q.where(User.id != request.args["exclude"])
    term = search_term()
    if term:
        q = q.where(
            or_(
                func.lower(User.name).like(term, escape="\\"),
                func.lower(User.email).like(term, escape="\\"),
            )
        )
    rows, meta = paged(q, [User.name, User.id])
    return jsonify(items=[dict(r._mapping) for r in rows], **meta)


@bp.get("/roles")
@admin
def roles():
    state = app_document().stored_data
    return jsonify(
        items=[dict(name=n, version=version(v)) for n, v in state["roles"].items()],
        modules=MODULES,
        actions=ACTIONS,
    )


@bp.get("/roles/<name>")
@admin
def role(name):
    return jsonify(record=role_record(name))


@bp.get("/company")
@admin
def company():
    return jsonify(record=company_record())


@bp.get("/activities")
def activities():
    if not allowed(g.user, app_document().stored_data, "activities"):
        problem("Activity permission required", 403)
    q = select(Audit, User.name.label("actor")).outerjoin(
        User, Audit.actor_id == User.id
    )
    if g.user.role != "Admin":
        q = q.where(Audit.actor_id == g.user.id)
    term = search_term()
    if term:
        q = q.where(
            or_(
                *(
                    func.lower(c).like(term, escape="\\")
                    for c in (Audit.action, Audit.actor_id, User.name)
                )
            )
        )
    if request.args.get("action"):
        q = q.where(Audit.action == request.args["action"])
    start = day(request.args["from"]) if request.args.get("from") else None
    end = day(request.args["to"]) if request.args.get("to") else None
    if start and end and start > end:
        problem("Start date must precede end date")
    if start:
        q = q.where(Audit.at >= start)
    if end and end != date.max.isoformat():
        q = q.where(
            Audit.at < (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        )
    rows, meta = paged(q, [Audit.id.desc()])
    return jsonify(
        items=[
            dict(
                id=a.id,
                actorId=a.actor_id,
                actor=name or a.actor_id,
                action=a.action,
                details=a.details,
                at=a.at,
            )
            for a, name in rows
        ],
        **meta
    )


def check_version(data, expected):
    if not data.get("version"):
        problem("Current version is required", 428)
    if data["version"] != expected:
        problem("Record changed. Reload before trying again.", 409)


def save_user(u, d):
    name = text(d, "name", limit=160, required=True)
    email = text(d, "email", limit=254, required=True).lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        problem("A valid email is required")
    role = d.get("role")
    if not isinstance(role, str) or role not in app_document().stored_data["roles"]:
        problem("Unknown role")
    active = d.get("active", True)
    if not isinstance(active, bool):
        problem("active must be boolean")
    manager_id = d.get("managerId") or None
    if manager_id:
        if not isinstance(manager_id, str):
            problem("Select an active manager")
        parent = db.session.get(User, manager_id)
        seen = {u.id} if u else set()
        if not parent or not parent.active:
            problem("Select an active manager")
        while parent:
            if parent.id in seen:
                problem("Manager assignments cannot contain a cycle")
            seen.add(parent.id)
            parent = (
                db.session.get(User, parent.manager_id) if parent.manager_id else None
            )
    if role in ("Salesperson", "Sales Representative") and not manager_id:
        problem("A team manager is required")
    if u and u.id == g.user.id and (not active or role != "Admin"):
        problem("You cannot disable or demote your own administrator account")
    duplicate = db.session.scalar(
        select(User.id).where(func.lower(User.email) == email)
    )
    if duplicate and (not u or duplicate != u.id):
        problem("Email is already in use", 409)
    if u is None:
        check_password(d.get("password"))
        u = User(
            id="user-" + secrets.token_hex(12),
            password_hash=generate_password_hash(d["password"]),
        )
        db.session.add(u)
    u.name, u.email, u.role, u.manager_id, u.active = (
        name,
        email,
        role,
        manager_id,
        active,
    )
    db.session.flush()
    return u


@bp.post("/commands/<kind>")
@admin
def command(kind):
    fields = {
        "create-user": {"name", "email", "role", "managerId", "active", "password"},
        "edit-user": {"id", "version", "name", "email", "role", "managerId", "active"},
        "password": {"id", "version", "password", "confirmPassword"},
        "role": {"name", "version", "permissions"},
        "company": {
            "version",
            "name",
            "legalName",
            "address",
            "phone",
            "email",
            "taxNumber",
        },
    }
    if kind not in fields:
        problem("Unknown Administration command", 404)
    d = body()
    if set(d) - fields[kind] - {"requestKey"}:
        problem("Unknown or immutable Administration fields")
    validate_json(
        {k: v for k, v in d.items() if k not in ("password", "confirmPassword")}
    )
    key = d.get("requestKey", "")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
        problem("A unique requestKey of 8–100 characters is required")
    if kind in ("create-user", "password"):
        check_password(d.get("password"))
        if kind == "password" and d["password"] != d.get("confirmPassword"):
            problem("Passwords must match")
    # Secrets never enter command receipts, state, public profiles or audit details.
    fingerprint = version(
        dict(
            kind=kind,
            data={
                k: v
                for k, v in d.items()
                if k not in ("requestKey", "version", "password", "confirmPassword")
            },
        )
    )
    lock()
    receipt = db.session.get(Command, (g.user.id, key))
    if receipt:
        if receipt.fingerprint != fingerprint:
            problem("Request key was used for another command", 409)
        result = resolve(receipt.resource, receipt.identity)
        if kind in ("create-user", "password") and not check_password_hash(
            user(receipt.identity).password_hash, d["password"]
        ):
            problem("Credential changed; use a new request key", 409)
        return jsonify(
            record=result,
            signInRequired=receipt.resource == "users"
            and receipt.identity == g.user.id,
        )
    self_changed = False
    if kind in ("create-user", "edit-user", "password"):
        u = None if kind == "create-user" else user(d.get("id"))
        if u:
            check_version(d, user_record(u)["version"])
        if kind == "password":
            u.password_hash = generate_password_hash(d["password"])
        else:
            u = save_user(u, d)
        if kind != "create-user":
            db.session.query(LoginSession).filter_by(user_id=u.id).delete()
        resource, identity = "users", u.id
        self_changed = u.id == g.user.id
    elif kind == "role":
        name = d.get("name")
        if not isinstance(name, str):
            problem("Select a role")
        if name == "Admin":
            problem("Admin permissions are fixed")
        current = role_record(name)
        check_version(d, current["version"])
        permissions = d.get("permissions")
        if not isinstance(permissions, dict) or set(permissions) != set(MODULES):
            problem("Supply all configured modules")
        cleaned = {}
        for m, values in permissions.items():
            if (
                not isinstance(values, dict)
                or set(values) != set(ACTIONS)
                or any(not isinstance(v, bool) for v in values.values())
            ):
                problem("Permissions must be boolean actions")
            cleaned[m] = {a: values[a] if values["view"] else False for a in ACTIONS}
        doc = app_document()
        state = deepcopy(doc.stored_data)
        old = deepcopy(state["roles"][name])
        old.update(permissions=cleaned)
        old.update({m: v["view"] for m, v in cleaned.items()})
        state["roles"][name] = old
        doc.stored_data = state
        doc.revision += 1
        db.session.query(LoginSession).filter(
            LoginSession.user_id.in_(select(User.id).where(User.role == name))
        ).delete(synchronize_session=False)
        resource, identity = "roles", name
    else:
        check_version(d, company_record()["version"])
        doc = app_document()
        state = deepcopy(doc.stored_data)
        value = deepcopy(state.get("company", {}))
        for f in fields[kind] - {"version"}:
            v = d.get(f, "")
            if not isinstance(v, str) or len(v) > 500:
                problem("Company fields must be text up to 500 characters")
            value[f] = v.strip()
        if not value["name"]:
            problem("Company name is required")
        value.update(
            country="Pakistan",
            currency="PKR",
            currencySymbol="Rs",
            currencyLocale="en-PK",
        )
        validate_company(value)
        state["company"] = value
        doc.stored_data = state
        doc.revision += 1
        resource, identity = "company", "company"
    db.session.add(
        Command(
            actor_id=g.user.id,
            request_key=key,
            fingerprint=fingerprint,
            resource=resource,
            identity=identity,
        )
    )
    audit("Administration " + kind, {"resource": resource, "id": identity})
    db.session.commit()
    return jsonify(record=resolve(resource, identity), signInRequired=self_changed)


def resolve(resource, identity):
    return (
        user_record(user(identity))
        if resource == "users"
        else role_record(identity) if resource == "roles" else company_record()
    )
