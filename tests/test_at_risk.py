"""At-risk gates: not started and due within GATE_AT_RISK_DAYS (no database)."""

from datetime import timedelta

import pytest

from launch_readiness import settings
from launch_readiness.dashboard import is_at_risk, needs_attention, summarize
from launch_readiness.models import GateStatus

from .test_dashboard import TODAY, YESTERDAY, gate


def days(n):
    return TODAY + timedelta(days=n)


def test_setting_is_three_days():
    assert settings.GATE_AT_RISK_DAYS == 3


@pytest.mark.parametrize("n", [0, 1, 3])
def test_not_started_and_due_within_three_days_is_at_risk(n):
    assert is_at_risk(GateStatus.NOT_STARTED, days(n), TODAY)


def test_due_in_four_days_is_not_at_risk():
    assert not is_at_risk(GateStatus.NOT_STARTED, days(4), TODAY)


def test_past_due_is_overdue_not_at_risk():
    g = gate(due=YESTERDAY)
    assert g.overdue and not g.at_risk
    assert g.attention_tags == ["Overdue"]


@pytest.mark.parametrize(
    "status", [GateStatus.IN_PROGRESS, GateStatus.PASSED, GateStatus.FAILED, GateStatus.WAIVED]
)
def test_only_not_started_gates_are_at_risk(status):
    assert not is_at_risk(status, days(1), TODAY)


def test_no_due_date_is_not_at_risk():
    assert not is_at_risk(GateStatus.NOT_STARTED, None, TODAY)


def test_setting_moves_the_cutoff(monkeypatch):
    assert not is_at_risk(GateStatus.NOT_STARTED, days(5), TODAY)
    monkeypatch.setattr(settings, "GATE_AT_RISK_DAYS", 5)
    assert is_at_risk(GateStatus.NOT_STARTED, days(5), TODAY)
    assert gate(due=days(5)).at_risk


def test_gate_view_tags_at_risk():
    g = gate(due=days(2))
    assert g.at_risk
    assert g.attention_tags == ["At risk"]


def test_needs_attention_lists_at_risk_after_overdue():
    at_risk = gate("At risk one", due=days(1))
    overdue = gate("Overdue one", due=YESTERDAY)
    failed = gate("Failed one", status="failed")
    unassigned = gate("Unassigned one", owner=None)
    listed = needs_attention([unassigned, at_risk, overdue, failed])
    assert [g.name for g in listed] == ["Failed one", "Overdue one", "At risk one", "Unassigned one"]


def test_summary_counts_at_risk():
    s = summarize([gate(due=days(0)), gate(due=days(3)), gate(due=days(4)), gate(due=YESTERDAY)])
    assert s.at_risk == 2
    assert s.overdue == 1
