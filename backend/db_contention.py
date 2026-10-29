"""Bounded ERP lock acquisition; a busy transaction rolls back before HTTP retry."""

from flask import current_app
from sqlalchemy import select, update, func
from sqlalchemy.exc import OperationalError


class DatabaseBusy(Exception):
    pass


def acquire():
    from .app import db
    from .erp import ERPControl
    from .validation import InvalidBusinessState

    postgres = db.session.get_bind().dialect.name == "postgresql"
    prior = None
    try:
        if postgres:
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
        result = db.session.execute(
            update(ERPControl)
            .where(ERPControl.id == 1)
            .values(revision=ERPControl.revision + 1)
        )
        if result.rowcount != 1:
            raise InvalidBusinessState("Run init-db to initialize ERP tables")
        if postgres:
            db.session.execute(select(func.set_config("lock_timeout", prior, True)))
    except OperationalError as error:
        original = error.orig
        state = getattr(original, "sqlstate", None)
        sqlite_code = getattr(original, "sqlite_errorcode", 0) or 0
        # Recognize only contention, not connectivity, schema or arbitrary SQL errors.
        if state in ("55P03", "40P01") or sqlite_code & 255 in (5, 6):
            db.session.rollback()
            raise DatabaseBusy() from None
        raise


def acquire_resource(model, identity, request_key):
    """PostgreSQL: shared global gate, actor/key mutex, target row lock.

    Shared ERPControl row locks conflict with every existing global UPDATE writer.
    They are held until commit/rollback, so this path cannot race bulk adapters or
    economic writers. Only explicitly reviewed non-economic commands use this path.
    """
    import hashlib
    from flask import g
    from .app import db, User, LoginSession
    from .erp import ERPControl
    from .validation import InvalidBusinessState

    if db.session.get_bind().dialect.name != "postgresql":
        acquire()
        return False
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
        control = db.session.scalar(
            select(ERPControl.id).where(ERPControl.id == 1).with_for_update(read=True)
        )
        if control is None:
            raise InvalidBusinessState("Run init-db to initialize ERP tables")
        # Stable signed bigint; a hash collision only serializes unrelated requests.
        token = int.from_bytes(
            hashlib.sha256((str(g.user.id) + "\0" + request_key).encode()).digest()[:8],
            "big",
            signed=True,
        )
        db.session.execute(select(func.pg_advisory_xact_lock(token)))
        if identity is not None:
            db.session.scalar(
                select(model)
                .where(model.id == str(identity))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        # Legacy account/session endpoints do not all take the ERP lock. Protect
        # the acting account and session until this command commits as well.
        db.session.scalar(
            select(User)
            .where(User.id == g.user.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        db.session.scalar(
            select(LoginSession)
            .where(LoginSession.token_hash == g.login_session.token_hash)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        db.session.execute(select(func.set_config("lock_timeout", prior, True)))
        return True
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", None) in ("55P03", "40P01"):
            db.session.rollback()
            raise DatabaseBusy() from None
        raise
