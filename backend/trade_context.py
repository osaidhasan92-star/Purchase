"""An isolated SQL-loaded workflow graph; masters never expand to unrelated orders."""

from copy import deepcopy
from collections import deque
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from .app import db, app_document
from . import trade_store as trade, master_store as master
from .crm_register_store import Company, record as company_record
from .workflow_keys import replace, check, ready, links, LegacyLink


# Only workflow relationships expand in reverse; product/party/lead masters are terminals.
class Context:
    def __init__(self, key, identity, data):
        ready()
        self.state = {k: [] for k in (*trade.MODELS, *master.MODELS, "companies")}
        self.state.update(
            {
                k: deepcopy(v)
                for k, v in app_document().stored_data.items()
                if k in ("roles", "company")
            }
        )
        self.rows = {}
        self.seen = set()
        self.queue = deque()
        self.load(key, identity)
        refs = dict(trade.REFERENCES.get(key, {}))
        refs.update(
            productId="products",
            customerId="customers",
            vendorId="vendors",
            leadId="leads",
        )
        for field, target in refs.items():
            self.load(target, data.get(field))
        for item in (
            data.get("items", []) if isinstance(data.get("items"), list) else []
        ):
            if isinstance(item, dict):
                self.load("products", item.get("productId"))
        for vendor in (
            data.get("vendorIds", []) if isinstance(data.get("vendorIds"), list) else []
        ):
            self.load("vendors", vendor)
        while self.queue:
            resource, value = self.queue.popleft()
            if resource in trade.MODELS:
                for field, target in trade.REFERENCES[resource].items():
                    self.load(target, value.get(field))
                for child, relations in trade.REFERENCES.items():
                    model = trade.MODELS[child]
                    conditions = []
                    for field, target in relations.items():
                        if target != resource:
                            continue
                        column = getattr(model, trade.FIELDS[child][field])
                        historical = select(LegacyLink.record_id).where(
                            LegacyLink.domain == child,
                            LegacyLink.field == field,
                            LegacyLink.parent_domain == resource,
                            LegacyLink.parent_id == str(value["id"]),
                        )
                        conditions.append(
                            or_(column == str(value["id"]), model.id.in_(historical))
                        )
                    if conditions:
                        for row in db.session.scalars(
                            self.query(child).where(or_(*conditions))
                        ):
                            self.accept(child, row)
                for slot in ("items", "lineItems"):
                    for item in (
                        value.get(slot, []) if isinstance(value.get(slot), list) else []
                    ):
                        self.load("products", item.get("productId"))
                for v in (
                    value.get("vendors", [])
                    if isinstance(value.get("vendors"), list)
                    else []
                ):
                    self.load("vendors", v.get("id"))
            elif resource == "leads":
                self.load("customers", value.get("customerId"))
                self.load("companies", value.get("companyId"))
                self.load("salesQuotations", value.get("quotationId"))
        for k, values in self.state.items():
            if isinstance(values, list):
                values.sort(
                    key=lambda v: (self.rows[(k, str(v["id"]))].position, str(v["id"]))
                )
        self.original = deepcopy(self.state)

    def query(self, key):
        model = trade.MODELS[key]
        q = select(model).options(selectinload(model.lines))
        if key == "rfqs":
            q = q.options(selectinload(model.vendors))
        return q

    def accept(self, key, row):
        token = (key, row.id)
        if token in self.rows:
            return
        self.rows[token] = row
        self.seen.add(token)
        value = (
            trade.record(key, row)
            if key in trade.MODELS
            else (
                master.record(key, row)
                if key in master.MODELS
                else company_record("companies", row)
            )
        )
        self.state[key].append(value)
        self.queue.append((key, value))

    def load(self, key, identity):
        if identity in (None, ""):
            return
        if not isinstance(identity, (str, int)) or isinstance(identity, bool):
            return
        token = (key, str(identity))
        if token in self.seen:
            return
        self.seen.add(token)
        row = (
            db.session.scalar(
                self.query(key).where(trade.MODELS[key].id == str(identity))
            )
            if key in trade.MODELS
            else db.session.get(master.MODELS.get(key, Company), str(identity))
        )
        if row:
            self.accept(key, row)

    def persist(self):
        available = trade.available_ids(self.state)
        pending = []
        for key, model in trade.MODELS.items():
            before = {str(v["id"]): v for v in self.original[key]}
            for value in self.state[key]:
                identity = str(value["id"])
                if before.get(identity) == value:
                    continue
                check(key, value)
                row = self.rows.get((key, identity))
                if row is None:
                    row = model(
                        id=identity,
                        position=(
                            db.session.scalar(select(func.min(model.position))) or 0
                        )
                        - 1,
                        original_id=value["id"],
                        record_version=trade.version(value),
                        extras={},
                        search_text="",
                    )
                    db.session.add(row)
                trade.assign_header(key, value, row, available)
                db.session.flush()
                pending.append((key, value, row))
        for key, value, row in pending:
            trade.assign_lines(key, value, row, available)
            replace(key, value)
            links(key, row)
        for value in self.state["leads"]:
            old = next(
                (v for v in self.original["leads"] if str(v["id"]) == str(value["id"])),
                None,
            )
            if old != value:
                row = self.rows[("leads", str(value["id"]))]
                master.write_one("leads", value, row.position, row)
        db.session.flush()
