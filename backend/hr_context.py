"""Targeted HR records and SQL period/overlap checks, independent of company size."""

from copy import deepcopy
from sqlalchemy import select, func, or_, and_
from .app import db, User, problem
from . import hr_store as store
from .workflow_keys import ready, check, replace


class Available:
    def __init__(self, model, local):
        self.model, self.local = model, local

    def __contains__(self, identity):
        return (
            str(identity) in self.local
            or db.session.get(self.model, str(identity)) is not None
        )


class Context:
    def __init__(self, key, identity, data):
        ready()
        self.state = {k: [] for k in store.MODELS}
        self.rows = {}
        self.load(key, identity)
        root = self.state[key][0] if self.state[key] else {}
        for field, target in [
            ("employeeKey", "employees"),
            ("candidateId", "candidates"),
            ("manpowerId", "manpower"),
        ]:
            self.load(target, data.get(field) or root.get(field))
        if (
            key in ("attendance", "leaves", "payroll", "separations")
            and not root.get("employeeKey")
            and root.get("employee")
        ):
            label = (
                func.coalesce(store.Employee.number, "")
                + " - "
                + func.coalesce(store.Employee.name, "")
            )
            for e in db.session.scalars(
                select(store.Employee).where(label == root["employee"]).limit(2)
            ):
                self.accept("employees", e)
        for candidate in self.state["candidates"]:
            self.load("manpower", candidate.get("manpowerId"))
        self.original = deepcopy(self.state)

    def accept(self, key, row):
        token = (key, row.id)
        if token not in self.rows:
            self.rows[token] = row
            self.state[key].append(store.record(key, row))

    def load(self, key, identity):
        if not isinstance(identity, (str, int)) or isinstance(identity, bool):
            return
        if (key, str(identity)) in self.rows:
            return
        row = db.session.get(store.MODELS[key], str(identity))
        if row:
            self.accept(key, row)

    def validate(self):
        for key, values in self.state.items():
            old = {str(v["id"]): v for v in self.original[key]}
            for value in values:
                if old.get(str(value["id"])) == value:
                    continue
                check(key, value)
                if key not in ("attendance", "leaves", "payroll", "separations"):
                    continue
                model = store.MODELS[key]
                employee_id = value.get("employeeKey")
                label = value.get("employee", "")
                who = (
                    or_(
                        model.employee_id == str(employee_id),
                        and_(model.employee_id.is_(None), model.name == label),
                    )
                    if employee_id
                    else model.name == label
                )
                query = select(model.id).where(model.id != str(value["id"]), who)
                if key in ("attendance", "payroll"):
                    query = query.where(
                        model.date
                        == value.get("date" if key == "attendance" else "month")
                    )
                elif key == "leaves":
                    if value.get("status") in ("Rejected", "Cancelled"):
                        continue
                    query = query.where(
                        or_(
                            model.status.is_(None),
                            model.status.notin_(["Rejected", "Cancelled"]),
                        ),
                        model.date <= value["to"],
                        model.end_date >= value["from"],
                    )
                else:
                    if value.get("status") in ("Completed", "Rejected"):
                        continue
                    query = query.where(
                        or_(
                            model.status.is_(None),
                            model.status.notin_(["Completed", "Rejected"]),
                        )
                    )
                if db.session.scalar(query.limit(1)):
                    problem(
                        (
                            "Leave periods overlap"
                            if key == "leaves"
                            else (
                                "An open separation already exists"
                                if key == "separations"
                                else "Duplicate " + key + " for employee and period"
                            )
                        ),
                        409,
                    )

    def persist(self):
        valid = {
            k: Available(m, {str(v["id"]) for v in self.state[k]})
            for k, m in store.MODELS.items()
        }
        valid["user"] = Available(User, set())
        for key, values in self.state.items():
            old = {str(v["id"]): v for v in self.original[key]}
            for value in values:
                identity = str(value["id"])
                if old.get(identity) == value:
                    continue
                row = self.rows.get((key, identity))
                if row is None:
                    position = (
                        db.session.scalar(select(func.min(store.MODELS[key].position)))
                        or 0
                    ) - 1
                    row = store.MODELS[key](id=identity)
                    db.session.add(row)
                else:
                    position = row.position
                store.write_one(
                    key, value, row, position, valid, self.state["employees"]
                )
                db.session.flush()
                replace(key, value)
