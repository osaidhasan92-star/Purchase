"""Recovery must retain approval state and attachment bytes, not only ledger rows."""

import sqlite3
import pytest
from sqlalchemy import create_engine, text
from backend.backup_verify import compare, prepare, validate_url


def test_recovery_requires_dedicated_database_names():
    for value, kind in (
        ("postgresql+psycopg://unused@localhost/production", "source"),
        ("sqlite:///:memory:", "source"),
        ("sqlite:///purchase_backup_source.sqlite", "source"),
        ("postgresql+psycopg://unused@localhost/purchase_backup_source", "restore"),
    ):
        with pytest.raises(ValueError, match="isolated"):
            validate_url(value, kind)


def test_recovery_retains_attachments_pending_approvals_and_independent_payment(
    tmp_path,
):
    source = tmp_path / "purchase_backup_source.sqlite"
    target = tmp_path / "purchase_backup_restore.sqlite"
    source_url, target_url = "sqlite:///" + str(source), "sqlite:///" + str(target)
    assert prepare(source_url)["enforcementEnabled"]
    with pytest.raises(ValueError, match="fresh empty"):
        prepare(source_url)
    with sqlite3.connect(source) as left, sqlite3.connect(target) as right:
        left.backup(right)
    engine = create_engine(target_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE attachment SET content = :value"), {"value": b"altered"}
            )
        with pytest.raises(RuntimeError, match="differs"):
            compare(source_url, target_url)
    finally:
        engine.dispose()
    with sqlite3.connect(source) as left, sqlite3.connect(target) as right:
        left.backup(right)
    result = compare(source_url, target_url)
    assert result["match"] and result["attachmentVerified"]
    assert result["selfApprovalBlocked"] and result["duplicateDecisionBlocked"]
    assert (
        result["expensePaidAfterIndependentReview"]
        and result["workflowHealth"]["healthy"]
    )
