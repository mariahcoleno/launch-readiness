"""Readiness verdict and blockers (no database)."""

from datetime import timedelta

import pytest

from launch_readiness.models import GateDefinition, RequiredGate
from launch_readiness.readiness import MISSING_NOTE, assess

from .test_dashboard import TODAY, YESTERDAY, gate


def required_for(gates, extra=()):
    """What the rules require: the gates the launch has, plus any extra."""
    reqs = [RequiredGate(GateDefinition(g.gate_key, g.name, g.team), ("Always required",)) for g in gates]
    return reqs + [RequiredGate(GateDefinition(k, n, t), ("Always required",)) for k, n, t in extra]


def check(gates, extra=()):
    return assess(gates, required_for(gates, extra))


def waived(name="Waived", rationale="Trusted testers only.", by="Morgan T."):
    return gate(name, status="waived", waiver_rationale=rationale, waived_by=by)


def test_all_passed_is_ready():
    r = check([gate("A", status="passed"), gate("B", status="passed")])
    assert r.ready
    assert r.verdict == "Ready"
    assert r.headline == "Ready"
    assert r.blockers == ()


def test_passed_plus_complete_waiver_is_ready():
    assert check([gate("A", status="passed"), waived()]).ready


@pytest.mark.parametrize(
    "rationale, by", [(None, "Morgan T."), ("  ", "Morgan T."), ("Reason", None), ("Reason", "")]
)
def test_incomplete_waiver_is_a_blocker(rationale, by):
    r = check([gate("A", status="passed"), waived("W", rationale, by)])
    assert not r.ready
    assert [b.name for b in r.blockers] == ["W"]
    assert r.blockers[0].tags[0] == "Waiver incomplete"


@pytest.mark.parametrize("status", ["not_started", "in_progress", "failed"])
def test_any_unfinished_gate_makes_it_not_ready(status):
    r = check([gate("A", status="passed"), gate("B", status=status)])
    assert r.verdict == "Not ready"
    assert r.headline == "Not ready: 1 blocker"
    assert [b.name for b in r.blockers] == ["B"]


def test_headline_plural():
    r = check([gate("A"), gate("B")])
    assert r.headline == "Not ready: 2 blockers"


def test_verdict_never_says_go_or_no_go():
    for r in (check([gate("A", status="passed")]), check([gate("A")])):
        assert "go" not in r.headline.lower()


def test_blockers_ordered_failed_overdue_at_risk_then_rest():
    rest_late = gate("Rest late", status="in_progress", due=TODAY + timedelta(days=20))
    rest_soon = gate("Rest soon", status="in_progress", due=TODAY + timedelta(days=8))
    at_risk = gate("At risk", due=TODAY + timedelta(days=1))
    overdue = gate("Overdue", status="in_progress", due=YESTERDAY)
    failed = gate("Failed", status="failed", due=TODAY + timedelta(days=30))
    r = check([rest_late, at_risk, rest_soon, overdue, failed, gate("Done", status="passed")])
    assert [b.name for b in r.blockers] == ["Failed", "Overdue", "At risk", "Rest soon", "Rest late"]


def test_blocker_carries_gate_details():
    g = gate("Tool-use safety eval", status="failed", owner="Dana K.", due=YESTERDAY)
    (b,) = check([g]).blockers
    assert (b.name, b.team, b.owner, b.due_date, b.gate_id) == (
        "Tool-use safety eval", "Safety", "Dana K.", YESTERDAY, g.id)
    assert b.tags == ("Failed", "Overdue")
    assert not b.is_missing


def test_gate_required_by_rules_but_missing_is_a_blocker():
    gates = [gate("A", status="passed")]
    r = check(gates, extra=[("legal_policy_review", "Legal & policy review", "Legal")])
    assert not r.ready
    (b,) = r.blockers
    assert b.is_missing
    assert (b.name, b.team, b.status, b.tags, b.note) == (
        "Legal & policy review", "Legal", None, ("Missing",), MISSING_NOTE)


def test_gates_not_passed_in_dont_count():
    """Removed gates aren't passed to assess(), so a removed failed gate can't block."""
    kept = [gate("A", status="passed")]
    assert assess(kept, required_for(kept)).ready
