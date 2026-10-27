"""Canonical HR tables, indexed links and an exact legacy read projection."""

from copy import deepcopy
from decimal import Decimal
from sqlalchemy import select
from .app import db
from .trade_store import version

MARKER = "_relationalHR"
COMMON = dict(status="status", createdBy="created_by")
SPECS = {
    "employees": dict(
        employeeId="number",
        name="name",
        department="department",
        designation="designation",
        manager="manager",
        joiningDate="date",
        salary="salary",
        linkedUserId="linked_user_id",
        **COMMON
    ),
    "manpower": dict(
        department="department",
        position="name",
        count="headcount",
        requestedBy="requester",
        **COMMON
    ),
    "candidates": dict(
        name="name",
        position="position_name",
        contact="contact",
        stage="stage",
        manpowerId="manpower_id",
        **COMMON
    ),
    "attendance": dict(
        employeeKey="employee_id",
        employee="name",
        date="date",
        attendanceStatus="stage",
        **COMMON
    ),
    "leaves": dict(
        employeeKey="employee_id",
        employee="name",
        leaveType="stage",
        **{"from": "date", "to": "end_date"},
        days="headcount",
        **COMMON
    ),
    "payroll": dict(
        employeeKey="employee_id",
        employee="name",
        month="date",
        basic="basic",
        allowances="allowances",
        deductions="deductions",
        netPay="net_pay",
        **COMMON
    ),
    "separations": dict(
        employeeKey="employee_id",
        employee="name",
        lastWorkingDate="date",
        finalSettlement="settlement",
        **COMMON
    ),
}
NUMBERS = {
    "salary",
    "basic",
    "allowances",
    "deductions",
    "netPay",
    "finalSettlement",
    "count",
    "days",
}


class Columns:
    id = db.Column(db.String(64), primary_key=True)
    original_id = db.Column(db.JSON, nullable=False)
    position = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(80), index=True)
    created_by = db.Column(db.String(64), index=True)
    name = db.Column(db.Text)
    date = db.Column(db.String(10), index=True)
    search_text = db.Column(db.Text, nullable=False)
    record_version = db.Column(db.String(64), nullable=False)
    extras = db.Column(db.JSON, nullable=False)


class Employee(Columns, db.Model):
    __tablename__ = "hr_employee"
    number = db.Column(db.String(80), index=True)
    department = db.Column(db.String(160), index=True)
    designation = db.Column(db.String(160))
    manager = db.Column(db.String(160))
    salary = db.Column(db.Numeric(38, 18))
    linked_user_id = db.Column(db.String(64), db.ForeignKey("user.id"), index=True)


class Manpower(Columns, db.Model):
    __tablename__ = "hr_manpower"
    department = db.Column(db.String(160), index=True)
    headcount = db.Column(db.Numeric(38, 18))
    requester = db.Column(db.String(160))


class Candidate(Columns, db.Model):
    __tablename__ = "hr_candidate"
    position_name = db.Column(db.String(160))
    contact = db.Column(db.String(254))
    stage = db.Column(db.String(80), index=True)
    manpower_id = db.Column(db.String(64), db.ForeignKey("hr_manpower.id"), index=True)


class EmployeeLink:
    @db.declared_attr
    def employee_id(cls):
        return db.Column(db.String(64), db.ForeignKey("hr_employee.id"), index=True)


class Attendance(Columns, EmployeeLink, db.Model):
    __tablename__ = "hr_attendance"
    stage = db.Column(db.String(80), index=True)


class Leave(Columns, EmployeeLink, db.Model):
    __tablename__ = "hr_leave"
    stage = db.Column(db.String(80))
    end_date = db.Column(db.String(10), index=True)
    headcount = db.Column(db.Numeric(38, 18))


class Payroll(Columns, EmployeeLink, db.Model):
    __tablename__ = "hr_payroll"
    basic = db.Column(db.Numeric(38, 18))
    allowances = db.Column(db.Numeric(38, 18))
    deductions = db.Column(db.Numeric(38, 18))
    net_pay = db.Column(db.Numeric(38, 18))


class Separation(Columns, EmployeeLink, db.Model):
    __tablename__ = "hr_separation"
    settlement = db.Column(db.Numeric(38, 18))


MODELS = dict(
    employees=Employee,
    manpower=Manpower,
    candidates=Candidate,
    attendance=Attendance,
    leaves=Leave,
    payroll=Payroll,
    separations=Separation,
)
LINKS = {"linkedUserId": "user", "employeeKey": "employees", "manpowerId": "manpower"}


def record(key, row):
    extras = deepcopy(row.extras)
    meta = extras.pop("_hrMeta", {})
    result = {**extras, "id": row.original_id}
    for field, column in SPECS[key].items():
        if field not in meta.get("present", []):
            continue
        value = getattr(row, column)
        if field in meta.get("unresolved", {}):
            value = meta["unresolved"][field]
        elif field in meta.get("null", []):
            value = None
        elif field in meta.get("strings", []) and value is not None:
            value = str(value) if field not in NUMBERS else meta["strings"][field]
        elif field in NUMBERS and value is not None:
            value = int(value) if field in meta.get("ints", []) else float(value)
        elif field in meta.get("ints", []) and value is not None:
            value = int(value)
        result[field] = value
    return result


def read(key):
    return [
        record(key, r)
        for r in db.session.scalars(
            select(MODELS[key]).order_by(MODELS[key].position, MODELS[key].id)
        )
    ]


def persist(data):
    from .app import User

    existing = {
        key: {r.id: r for r in db.session.scalars(select(model))}
        for key, model in MODELS.items()
    }
    valid = {key: {str(r["id"]) for r in data.get(key, [])} for key in MODELS}
    valid["user"] = set(db.session.scalars(select(User.id)))
    for key, model in MODELS.items():
        for pos, value in enumerate(data.get(key, [])):
            row = existing[key].pop(str(value["id"]), None)
            if row and row.record_version == version(value):
                row.position = pos
                continue
            if row is None:
                row = model(id=str(value["id"]))
                db.session.add(row)
            row.original_id = value["id"]
            row.position = pos
            row.record_version = version(value)
            row.search_text = " ".join(
                str(v) for v in value.values() if isinstance(v, (str, int, float))
            ).casefold()
            meta = dict(
                present=[f for f in SPECS[key] if f in value],
                null=[],
                ints=[],
                strings={},
                unresolved={},
            )
            for field, column in SPECS[key].items():
                item = value.get(field)
                if (
                    field in NUMBERS
                    and isinstance(item, int)
                    and not isinstance(item, bool)
                ):
                    meta["ints"].append(field)
                if item is None:
                    meta["null"].append(field)
                if field in LINKS and item is not None:
                    if str(item) not in valid[LINKS[field]]:
                        meta["unresolved"][field] = item
                        item = None
                    else:
                        if isinstance(item, int):
                            meta["ints"].append(field)
                        item = str(item)
                if field in NUMBERS and item is not None:
                    if isinstance(item, str):
                        meta["strings"][field] = item
                    item = Decimal(str(item))
                    if not item.is_finite():
                        raise ValueError("Non-finite HR number")
                setattr(row, column, item)
            if (
                key in ("attendance", "leaves", "payroll", "separations")
                and not row.employee_id
                and not value.get("employeeKey")
            ):
                matches = [
                    e
                    for e in data.get("employees", [])
                    if str(e.get("employeeId", "")) + " - " + str(e.get("name", ""))
                    == value.get("employee")
                ]
                if len(matches) == 1:
                    row.employee_id = str(matches[0]["id"])
            row.extras = {
                **{
                    k: deepcopy(v)
                    for k, v in value.items()
                    if k not in SPECS[key] and k != "id"
                },
                "_hrMeta": meta,
            }
        db.session.flush()
    # Delete children before referenced rows. Historical imports preserve unresolved links explicitly.
    for key in reversed(MODELS):
        for row in existing[key].values():
            db.session.delete(row)
        db.session.flush()
    return {**{k: v for k, v in data.items() if k not in MODELS}, MARKER: 1}


def project(stored):
    if not stored.get(MARKER):
        return stored
    return {
        **{k: v for k, v in stored.items() if k != MARKER},
        **{k: read(k) for k in MODELS},
    }


def migrate(doc):
    if doc.stored_data.get(MARKER):
        return False
    original = deepcopy(doc.data)
    stored = persist(original)
    db.session.flush()
    for key in MODELS:
        if read(key) != original.get(key, []):
            raise ValueError(
                "Migration stopped: " + key + " could not round-trip exactly"
            )
    doc.stored_data = stored
    doc.revision += 1
    return True
