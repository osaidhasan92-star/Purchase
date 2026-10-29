"""Guard isolated fixtures and verify concurrent benchmark economic assertions."""

import pytest
from backend.capacity_probe import distribution, execute, validate_database


def test_capacity_database_guard_preserves_existing_file(tmp_path):
    path = tmp_path / "capacity-probe.sqlite"
    path.write_bytes(b"keep-existing-data")
    with pytest.raises(ValueError, match="already exists"):
        validate_database("sqlite:///" + str(path))
    assert path.read_bytes() == b"keep-existing-data"
    with pytest.raises(ValueError, match="dedicated"):
        validate_database("postgresql+psycopg://unused:unused@localhost/production")
    with pytest.raises(ValueError, match="fresh file"):
        validate_database("sqlite:///:memory:")


def test_capacity_probe_concurrent_payroll_and_replays(tmp_path):
    result = execute(
        "sqlite:///" + str(tmp_path / "capacity-probe.sqlite"), 10, [1, 2], 1
    )
    assert result["passed"], result
    assert result["historicalEmployees"] == 10
    assert [c["newJournals"] for c in result["cases"]] == [2, 4]
    assert result["cases"][-1]["totalPaidPayroll"] == 3
    assert all(c["lockStatementMs"]["count"] > 0 for c in result["cases"])
    assert distribution([1, 2, 3, 4, 5])["p95"] == 5
