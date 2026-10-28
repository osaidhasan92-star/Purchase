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
