"""Database-unique normalized workflow tokens; preserve blocked legacy duplicates."""

from flask import g
from sqlalchemy import select, delete
from .app import db, Document, problem


class Reservation(db.Model):
    __tablename__ = "workflow_reservation"
    domain = db.Column(db.String(40), primary_key=True)
    kind = db.Column(db.String(20), primary_key=True)
    token = db.Column(db.String(64), primary_key=True)
    record_id = db.Column(
        db.String(64)
    )  # NULL explicitly blocks historical duplicates.


def insert():
    if db.session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert


def reserve(domain, identity, expected):
    for kind, token in sorted(expected.items()):
        row = db.session.get(Reservation, (domain, kind, token))
        if row is not None and row.record_id == identity:
            continue
        if getattr(g, "resource_mode", False):
            from .concurrency import tail

            tail()  # Counter/claims/creator metadata always follow one ordering.
        statement = insert()(Reservation).values(
            domain=domain, kind=kind, token=token, record_id=identity
        )
        db.session.execute(
            statement.on_conflict_do_nothing(index_elements=["domain", "kind", "token"])
        )
        row = db.session.get(Reservation, (domain, kind, token), populate_existing=True)
        if row.record_id != identity:
            problem(
                "Normalized number or reference is already reserved; review duplicate history",
                409,
            )


def synchronize(domain, affected):
    from .workflow_keys import ConflictKey

    db.session.flush()
    for kind, token in affected:
        owners = db.session.scalars(
            select(ConflictKey.record_id).where(
                ConflictKey.domain == domain,
                ConflictKey.kind == kind,
                ConflictKey.token == token,
            )
        ).all()
        if not owners:
            db.session.execute(
                delete(Reservation).where(
                    Reservation.domain == domain,
                    Reservation.kind == kind,
                    Reservation.token == token,
                )
            )
            continue
        owner = owners[0] if len(owners) == 1 else None
        statement = insert()(Reservation).values(
            domain=domain, kind=kind, token=token, record_id=owner
        )
        db.session.execute(
            statement.on_conflict_do_update(
                index_elements=["domain", "kind", "token"], set_={"record_id": owner}
            )
        )


def initialize(rebuild=False):
    marker = db.session.get(Document, "workflow_reservations")
    if marker and marker.stored_data.get("version") == 1 and not rebuild:
        return
    from .workflow_keys import ConflictKey

    db.session.flush()
    db.session.execute(delete(Reservation))
    groups = {}
    for domain, kind, token, identity in db.session.execute(
        select(
            ConflictKey.domain,
            ConflictKey.kind,
            ConflictKey.token,
            ConflictKey.record_id,
        )
    ):
        key = (domain, kind, token)
        groups[key] = identity if key not in groups else None
    if groups:
        db.session.execute(
            Reservation.__table__.insert(),
            [
                dict(domain=d, kind=k, token=t, record_id=v)
                for (d, k, t), v in groups.items()
            ],
        )
    if marker is None:
        db.session.add(
            Document(
                name="workflow_reservations", stored_data={"version": 1}, revision=1
            )
        )
    else:
        marker.stored_data = {"version": 1}
