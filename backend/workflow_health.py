"""Read-only operational checks for the canonical ledger and derived indexes."""

from sqlalchemy import select, func, or_
from .app import db, Document
from .erp import JournalEntry, JournalLine, StockBalance
from .workflow_keys import ConflictKey, LegacyLink


def report():
    bad = (
        select(JournalEntry.id)
        .outerjoin(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .where(JournalEntry.status == "Posted")
        .group_by(JournalEntry.id)
        .having(
            or_(
                func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0) != 0,
                func.count(JournalLine.id) < 2,
            )
        )
    )
    duplicates = (
        select(ConflictKey.domain, ConflictKey.kind, ConflictKey.token)
        .group_by(ConflictKey.domain, ConflictKey.kind, ConflictKey.token)
        .having(func.count() > 1)
    )
    marker = db.session.get(Document, "workflow_indexes")
    result = dict(
        workflowIndexesReady=bool(marker and marker.stored_data.get("version") == 2),
        unbalancedOrIncompletePostedJournals=db.session.scalar(
            select(func.count()).select_from(bad.subquery())
        ),
        negativeStockBalances=db.session.scalar(
            select(func.count())
            .select_from(StockBalance)
            .where(or_(StockBalance.quantity < 0, StockBalance.value < 0))
        ),
        duplicateWorkflowKeys=db.session.scalar(
            select(func.count()).select_from(duplicates.subquery())
        ),
        historicalUnresolvedTradeLinks=db.session.scalar(
            select(func.count()).select_from(LegacyLink)
        ),
    )
    result["healthy"] = result["workflowIndexesReady"] and not any(
        result[k]
        for k in (
            "unbalancedOrIncompletePostedJournals",
            "negativeStockBalances",
            "duplicateWorkflowKeys",
        )
    )
    return result
