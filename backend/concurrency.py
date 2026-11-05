"""Reviewed native writers: shared legacy gate, stable resources, short posting tail."""

import hashlib
import re
from contextlib import contextmanager
from flask import current_app, g
from sqlalchemy import select, func
from sqlalchemy.exc import OperationalError
from .app import db
from .db_contention import acquire_resource, acquire_payroll_posting, DatabaseBusy
from .erp import ERPControl


def enabled():
    return (
        current_app.config["RESOURCE_CONCURRENCY"]
        and db.session.get_bind().dialect.name == "postgresql"
    )


@contextmanager
def bounded():
    try:
        prior = db.session.scalar(select(func.current_setting("lock_timeout")))
        db.session.execute(
            select(
                func.set_config(
                    "lock_timeout",
                    str(current_app.config["ERP_LOCK_TIMEOUT_MS"]) + "ms",
                    True,
                )
            )
        )
        yield
        db.session.execute(select(func.set_config("lock_timeout", prior, True)))
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", None) in ("55P03", "40P01"):
            db.session.rollback()
            raise DatabaseBusy() from None
        raise


def locks(keys):
    # One namespace for resource identities, separate from actor/key and posting locks.
    with bounded():
        for key in sorted(set(keys)):
            digest = hashlib.sha256(("resource\0" + key).encode()).digest()
            first = int.from_bytes(digest[:4], "big", signed=True)
            second = int.from_bytes(digest[4:8], "big", signed=True)
            if (first, second) == (1346459986, 1):
                first ^= 1  # Reserve the posting-tail key.
            db.session.execute(select(func.pg_advisory_xact_lock(first, second)))


def begin(request_key):
    if not enabled():
        from .erp import lock

        lock()
        from .workflow_keys import revalidate_actor

        revalidate_actor()
        return False
    from .workflow_keys import ready, revalidate_actor

    # Reuse account/session protection and compatibility gate; no target yet.
    acquire_resource(ERPControl, None, request_key)
    ready()
    g.resource_mode = True
    revalidate_actor()
    return True


def tail():
    if not getattr(g, "resource_mode", False) or getattr(g, "posting_tail", False):
        return
    acquire_payroll_posting()
    g.posting_tail = True


def products(identities):
    locks("stock:" + str(i) for i in identities if i is not None)


def inventory(data, command):
    if not begin(data["requestKey"]):
        return False
    from .erp import StockMove

    if command == "return":
        value = data.get("moveId")
        valid = (
            not isinstance(value, bool)
            and isinstance(value, (str, int))
            and re.fullmatch(r"[1-9][0-9]{0,9}", str(value))
        )
        move = db.session.get(StockMove, int(value)) if valid else None
        keys=["movement:" + str(data.get("moveId"))]
        if move and len(move.source.split(':'))==3:
            from .trade_context import Context
            from . import trade_store
            target,identity,_=move.source.split(':')
            if target in ('receipts','deliveries'):
                graph=Context(target,identity,{})
                keys += [f'trade:{k}:{rid}' for k,rid in graph.rows if k in trade_store.MODELS or k=='leads']
        locks(keys)
        identities = [move.product_id] if move else []
    else:
        identities = [data.get("productId")]
    products(identities)
    db.session.expire_all()
    return True


def production(data, command):
    if not begin(data["requestKey"]):
        return False
    from .erp import ManufacturingOrder, BillOfMaterials

    model = BillOfMaterials if command in ("order", "edit-bom") else ManufacturingOrder
    identity = data.get("bomId") if command == "order" else data.get("id")
    if command != "bom":
        locks([model.__tablename__ + ":" + str(identity)])
    root = (
        db.session.get(model, int(identity))
        if command != "bom"
        and not isinstance(identity, bool)
        and isinstance(identity, (str, int))
        and re.fullmatch(r"[1-9][0-9]{0,9}", str(identity))
        else None
    )
    identities = [data.get("productId")]
    if root:
        identities += [root.product_id] + [line.product_id for line in root.lines]
    for line in (
        data.get("components", []) if isinstance(data.get("components"), list) else []
    ):
        if isinstance(line, dict):
            identities.append(line.get("productId"))
    products(identities)
    db.session.expire_all()
    return True


def expense(data):
    if not begin(data["requestKey"]):
        return False
    if data.get("id") is not None:
        locks(["expense:" + str(data["id"])])
    db.session.expire_all()
    return True


def finance(data, command):
    # Period close changes the compatibility gate itself: always an exclusive writer.
    if command == "period-lock" or not enabled():
        from .erp import lock

        lock()
        from .workflow_keys import revalidate_actor

        revalidate_actor()
        return False
    begin(data["requestKey"])
    # Existing matching/reversal rules share journal lines and creator metadata.
    # Serialize this financial portion, while independent stock/workflow preparation runs.
    tail()
    db.session.expire_all()
    return True


def trade(key, identity, data):
    if not begin(data["requestKey"]):
        return None
    from .trade_context import Context
    from . import trade_store as store
    from .trade_service import TradeCommand

    receipt = db.session.get(TradeCommand, (g.user.id, data["requestKey"]))
    effective_key, effective_id = (
        (receipt.resource, receipt.identity) if receipt else (key, identity)
    )
    first = Context(effective_key, effective_id, data)
    # Parent identities are immutable. Ancestor locks protect concurrently inserted
    # siblings too; rebuilding the graph after waiting sees committed new children.
    keys = [
        f"trade:{k}:{rid}" for k, rid in first.rows if k in store.MODELS or k == "leads"
    ]
    locks(keys)
    db.session.expire_all()
    refreshed = Context(effective_key, effective_id, data)
    products(row["id"] for row in refreshed.state["products"])
    db.session.expire_all()
    return Context(effective_key, effective_id, data)
