"""Dashboard logic, with no database or web server. "Today" is fixed."""

from datetime import date, timedelta

import pytest

from launch_readiness.dashboard import (
    countdown,
    gate_view,
    group_by_team,
    is_overdue,
    needs_attention,
    summarize,
)
from launch_readiness.models import GateStatus

TODAY = date(2026, 11, 2)
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)
LATER = TODAY + timedelta(days=10)  # far enough out not to be at risk

_next_id = iter(range(1, 10_000))


def gate(name="Gate", team="Safety", status="not_started", owner="Priya N.", due=LATER, **extra):
    row = {
        "id": next(_next_id),
        "gate_key": name.lower().replace(" ", "_"),
        "name": name,
        "team": team,
        "owner": owner,
        "status": status,
        "due_date": due.isoformat() if due else None,
        "notes": None,
        "waiver_rationale": extra.get("waiver_rationale"),
        "waived_by": extra.get("waived_by"),
    }
    return gate_view(row, ("Always required",), TODAY)


# --- Overdue ------------------------------------------------------------------


@pytest.mark.parametrize("status", [GateStatus.NOT_STARTED, GateStatus.IN_PROGRESS, GateStatus.FAILED])
def test_unfinished_gate_past_due_is_overdue(status):
    assert is_overdue(status, YESTERDAY, TODAY)


@pytest.mark.parametrize("status", [GateStatus.PASSED, GateStatus.WAIVED])
def test_done_gate_is_never_overdue(status):
    assert not is_overdue(status, YESTERDAY, TODAY)


def test_gate_due_today_is_not_overdue_yet():
    assert not is_overdue(GateStatus.NOT_STARTED, TODAY, TODAY)


def test_gate_with_no_due_date_is_never_overdue():
    assert not is_overdue(GateStatus.NOT_STARTED, None, TODAY)


def test_gate_view_sets_overdue_from_row():
    assert gate(due=YESTERDAY).overdue
    assert not gate(due=YESTERDAY, status="passed").overdue


# --- Team groups ----------------------------------------------------------------


def test_teams_sorted_a_to_z_and_gates_keep_their_order():
    gates = [
        gate("Safety evals", team="Safety"),
        gate("Rollback plan", team="Infrastructure"),
        gate("Red-team sign-off", team="Safety", status="passed"),
        gate("Comms plan", team="Communications"),
        gate("Monitoring", team="Infrastructure", status="waived",
             waiver_rationale="x", waived_by="y"),
    ]
    groups = group_by_team(gates)
    assert [g.team for g in groups] == ["Communications", "Infrastructure", "Safety"]
    assert [g.name for g in groups[2].gates] == ["Safety evals", "Red-team sign-off"]
    assert [g.done_count for g in groups] == [0, 1, 1]


def test_team_sort_ignores_case():
    groups = group_by_team([gate(team="trust & Safety"), gate(team="Legal")])
    assert [g.team for g in groups] == ["Legal", "trust & Safety"]


# --- Needs attention --------------------------------------------------------------


def test_needs_attention_lists_failed_overdue_and_unassigned_only():
    failed = gate("Failed one", status="failed")
    overdue = gate("Overdue one", due=YESTERDAY)
    unassigned = gate("Unassigned one", owner=None)
    fine = gate("Fine one")
    passed = gate("Passed one", status="passed", due=YESTERDAY)
    listed = needs_attention([fine, unassigned, passed, overdue, failed])
    assert [g.name for g in listed] == ["Failed one", "Overdue one", "Unassigned one"]


def test_blank_owner_counts_as_unassigned():
    assert gate(owner="").is_unassigned
    assert gate(owner="").attention_tags == ["Unassigned"]


def test_a_gate_with_several_problems_is_listed_once_with_every_tag():
    bad = gate("Bad", status="failed", due=YESTERDAY, owner=None)
    listed = needs_attention([bad])
    assert len(listed) == 1
    assert listed[0].attention_tags == ["Failed", "Overdue", "Unassigned"]


def test_needs_attention_earliest_due_first_within_a_kind():
    later = gate("Later", status="failed", due=TOMORROW)
    earlier = gate("Earlier", status="failed", due=TOMORROW + timedelta(days=-5))
    assert [g.name for g in needs_attention([later, earlier])] == ["Earlier", "Later"]


def test_nothing_needs_attention():
    assert needs_attention([gate(), gate(status="passed")]) == []


# --- Summary ----------------------------------------------------------------------


def test_summary_counts():
    gates = [
        gate(status="passed"),
        gate(status="waived", waiver_rationale="x", waived_by="y"),
        gate(status="failed", due=YESTERDAY),
        gate(status="in_progress", owner=None),
        gate(),
    ]
    s = summarize(gates)
    assert (s.total, s.done, s.failed, s.overdue, s.unassigned) == (5, 2, 1, 1, 1)


# --- Countdown --------------------------------------------------------------------


@pytest.mark.parametrize(
    "days, text",
    [
        (12, "12 days away"),
        (2, "2 days away"),
        (1, "1 day away"),
        (0, "Launch day is today"),
        (-1, "Launch date passed"),
        (-30, "Launch date passed"),
    ],
)
def test_countdown(days, text):
    assert countdown(TODAY + timedelta(days=days), TODAY) == text
