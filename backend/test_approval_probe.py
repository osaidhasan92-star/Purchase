"""Load checks include independent decisions, expected denials and conserved posting."""

from backend.approval_probe import execute


def test_approval_enabled_baseline_retains_independence_and_conservation(tmp_path):
    result = execute(
        "sqlite:///" + str(tmp_path / "capacity-probe.sqlite"),
        rows=10,
        workers=[1, 2],
        iterations=1,
    )
    assert result["passed"], result
    assert result["approvalEnforcement"] is True
    assert [case["completedWorkflows"] for case in result["cases"]] == [1, 2]
    assert [case["newJournals"] for case in result["cases"]] == [2, 4]
    assert all(case["unexpectedFailures"] == [] for case in result["cases"])
