"""Permission-filtered ERP overview using SQL totals, without register projections."""

from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Blueprint, g, jsonify
from sqlalchemy import select, func
from .app import db, app_document
from .permissions import allowed
from .erp import StockBalance, ManufacturingOrder, Expense, JournalEntry, StockMove
from .finance_api import summary_values, report_totals
from .expense_api import scope as expense_scope
from .master_store import MODELS as masters, MARKER as master_marker
from .trade_store import MODELS as trades, MARKER as trade_marker
from .crm_register_store import MODELS as registers, MARKER as register_marker
from .erp import BankStatementLine, BillOfMaterials

bp = Blueprint("overview", __name__, url_prefix="/api/overview")


@bp.get("/summary")
def summary():
    state = app_document().stored_data
    result = {"currency": "PKR", "warehouse": "WH / Stock", "canSeed": False}
    if allowed(g.user, state, "inventory"):
        result["inventoryValue"] = str(
            db.session.scalar(select(func.coalesce(func.sum(StockBalance.value), 0)))
        )
    if allowed(g.user, state, "manufacturing"):
        result["openProduction"] = db.session.scalar(
            select(func.count())
            .select_from(ManufacturingOrder)
            .where(ManufacturingOrder.state.in_(["Draft", "Confirmed", "In Progress"]))
        )
    if allowed(g.user, state, "expenses"):
        result["pendingExpenses"] = db.session.scalar(
            select(func.count())
            .select_from(Expense)
            .where(expense_scope(), Expense.status.in_(["Submitted", "Approved"]))
        )
    if allowed(g.user, state, "accounting"):
        end = datetime.now(ZoneInfo("Asia/Karachi")).date().isoformat()
        financial = summary_values(report_totals(None, end), None, end)
        result.update(
            {k: financial[k] for k in ("cashBank", "receivables", "payables", "profit")}
        )
    if g.user.role == "Admin":
        result["canSeed"] = can_seed()
    return jsonify(result)


def can_seed():
    if not all(
        app_document().stored_data.get(m)
        for m in (master_marker, trade_marker, register_marker)
    ):
        return False
    models = (
        list(masters.values())
        + list(trades.values())
        + list(registers.values())
        + [
            JournalEntry,
            StockMove,
            Expense,
            BankStatementLine,
            BillOfMaterials,
            ManufacturingOrder,
        ]
    )
    return not any(db.session.scalar(select(m.id).limit(1)) for m in models)
