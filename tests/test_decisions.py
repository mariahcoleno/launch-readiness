"""Go / No-go decisions and the decision log (form, temporary database)."""

import json
import sqlite3
from datetime import date, timedelta

import pytest

from launch_readiness.db import get_connection, init_db
from launch_readiness.decision_form import GoNoGoInput, ScopeChangeInput, parse_go_no_go_form
from launch_readiness.decisions import (
    DecisionRefused,
    changes_since,
    latest_go_no_go,
    latest_go_no_go_by_launch,
    list_decisions,
    record_go_no_go,
)
from launch_readiness.gate_form import GateUpdate
from launch_readiness.launch_status import assess_launch
from launch_readiness.launches import get_gates, update_gate
from launch_readiness.models import Capability, DecisionKind, GateStatus
from launch_readiness.scope_change import disable_capability, enable_capability
from launch_readiness.seed import seed_database

TODAY = date(2026, 11, 2)


# --- Form -----------------------------------------------------------------------


def form(**overrides):
    fields = {
        "kind": "go",
        "decided_by": "Morgan T. (VP, Product)",
        "decided_on": "2026-11-02",
        "rationale": "All gates done.",
        "follow_up": "",
    }
    fields.update(overrides)
    return fields


def parse(ready=True, **overrides):
    return parse_go_no_go_form(form(**overrides), TODAY, ready)


def test_go_while_ready_is_accepted_without_follow_up():
    decision, errors = parse()
    assert errors == {}
    assert decision.kind is DecisionKind.GO
    assert decision.follow_up is None
    assert not decision.acknowledged_blockers


def test_no_go_needs_follow_up():
    _, errors = parse(kind="no_go")
    assert errors == {"follow_up": "Say what happens next."}
    decision, errors = parse(kind="no_go", follow_up="Re-run the eval.")
    assert errors == {}
    assert decision.kind is DecisionKind.NO_GO


@pytest.mark.parametrize("ready", [True, False])
def test_no_go_never_needs_the_checkbox(ready):
    decision, errors = parse(ready=ready, kind="no_go", follow_up="Next week.")
    assert errors == {}
    assert not decision.acknowledged_blockers


def test_go_while_not_ready_needs_checkbox_and_follow_up():
    _, errors = parse(ready=False)
    assert set(errors) == {"acknowledge_blockers", "follow_up"}
    assert errors["follow_up"] == "Say what happens to the open blockers."


def test_go_while_not_ready_with_checkbox_but_no_follow_up_is_refused():
    _, errors = parse(ready=False, acknowledge_blockers="1")
    assert errors == {"follow_up": "Say what happens to the open blockers."}


def test_go_while_not_ready_with_follow_up_but_no_checkbox_is_refused():
    _, errors = parse(ready=False, follow_up="Fix the eval in v2.1.1.")
    assert list(errors) == ["acknowledge_blockers"]


@pytest.mark.parametrize("value", ["1", "on", "yes", "true"])
def test_go_while_not_ready_with_both_is_accepted(value):
    decision, errors = parse(ready=False, acknowledge_blockers=value,
                             follow_up="Fix the eval in v2.1.1.")
    assert errors == {}
    assert decision.acknowledged_blockers
    assert decision.follow_up == "Fix the eval in v2.1.1."


def test_checkbox_ignored_when_ready():
    decision, errors = parse(ready=True, acknowledge_blockers="1")
    assert errors == {}
    assert not decision.acknowledged_blockers


@pytest.mark.parametrize("kind", ["", "maybe", "scope_change"])
def test_kind_must_be_go_or_no_go(kind):
    _, errors = parse(kind=kind)
    assert list(errors) == ["kind"]


@pytest.mark.parametrize("field", ["decided_by", "rationale"])
@pytest.mark.parametrize("value", ["", "   "])
def test_decided_by_and_rationale_required(field, value):
    _, errors = parse(**{field: value})
    assert list(errors) == [field]


def test_date_defaults_to_today():
    decision, _ = parse(decided_on="")
    assert decision.decided_on == TODAY


def test_past_date_accepted():
    decision, errors = parse(decided_on="2026-10-30")
    assert errors == {}
    assert decision.decided_on == date(2026, 10, 30)


@pytest.mark.parametrize("value, message", [
    ("2026-11-03", "can't be dated in the future"),
    ("next week", "YYYY-MM-DD"),
    ("2026-02-30", "YYYY-MM-DD"),
])
def test_bad_dates_rejected(value, message):
    _, errors = parse(decided_on=value)
    assert message in errors["decided_on"]


@pytest.mark.parametrize("field, limit", [("decided_by", 100), ("rationale", 2000), ("follow_up", 2000)])
def test_length_limits(field, limit):
    _, errors = parse(**{field: "x" * (limit + 1)})
    assert list(errors) == [field]


# --- Recording ------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def seeded(conn):
    return seed_database(conn, today=TODAY)


@pytest.fixture
def v21(seeded):
    return seeded[0]


@pytest.fixture
def v22(seeded):
    return seeded[1]


def make_ready(conn, launch_id):
    for g in get_gates(conn, launch_id):
        update_gate(conn, g["id"], GateUpdate(GateStatus.PASSED, "Priya N.", None, None, None, None))


NO_GO = GoNoGoInput(DecisionKind.NO_GO, "Morgan T.", TODAY, "Eval failed.", "Re-run next week.")
GO = GoNoGoInput(DecisionKind.GO, "Morgan T.", TODAY, "All gates done.", None)
GO_WITH_BLOCKERS = GoNoGoInput(DecisionKind.GO, "Morgan T.", TODAY, "Accepting the eval risk.",
                               "Fix the eval in v2.1.1.", acknowledged_blockers=True)
OFF = ScopeChangeInput("Morgan T.", "Eval failing.", "Turn back on in v2.1.1.")


def row(conn, decision_id):
    return conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()


def test_no_go_saves_every_field_and_a_snapshot(conn, v21):
    d = row(conn, record_go_no_go(conn, v21, NO_GO, TODAY))
    assert (d["kind"], d["decided_by"], d["decided_on"], d["rationale"], d["follow_up"],
            d["acknowledged_blockers"], d["action"], d["capability"]) == (
        "no_go", "Morgan T.", "2026-11-02", "Eval failed.", "Re-run next week.", 0, None, None)
    snap = json.loads(d["readiness_snapshot"])
    assert snap["headline"] == "Not ready: 1 blocker"
    assert snap["ready"] is False
    assert snap["blockers"] == [{"name": "Tool-use safety eval", "team": "Safety",
                                 "status": "failed", "tags": ["Failed", "Overdue"]}]


def test_go_while_ready_is_not_flagged(conn, v22):
    make_ready(conn, v22)
    d = row(conn, record_go_no_go(conn, v22, GO, TODAY))
    assert d["acknowledged_blockers"] == 0
    assert json.loads(d["readiness_snapshot"])["headline"] == "Ready"
    assert latest_go_no_go(conn, v22).title == "Go"


def test_go_with_blockers_is_flagged(conn, v21):
    record_go_no_go(conn, v21, GO_WITH_BLOCKERS, TODAY)
    latest = latest_go_no_go(conn, v21)
    assert latest.acknowledged_blockers
    assert latest.title == "Go with open blockers"
    assert latest.follow_up == "Fix the eval in v2.1.1."


@pytest.mark.parametrize("decision", [
    GO,  # no acknowledgement, no follow-up
    GoNoGoInput(DecisionKind.GO, "M", TODAY, "R", None, acknowledged_blockers=True),
    GoNoGoInput(DecisionKind.GO, "M", TODAY, "R", "Fix it", acknowledged_blockers=False),
])
def test_go_while_not_ready_refused_without_acknowledgement_and_follow_up(conn, v21, decision):
    with pytest.raises(DecisionRefused):
        record_go_no_go(conn, v21, decision, TODAY)
    assert latest_go_no_go(conn, v21).kind is DecisionKind.NO_GO  # only the seeded one


@pytest.mark.parametrize("sql", [
    "INSERT INTO decisions (launch_id, kind, decided_by, decided_on, rationale) "
    "VALUES (?, 'no_go', 'M', '2026-11-02', 'R')",                      # No-go, no follow-up
    "INSERT INTO decisions (launch_id, kind, decided_by, decided_on, rationale, acknowledged_blockers) "
    "VALUES (?, 'go', 'M', '2026-11-02', 'R', 1)",                       # Go with blockers, no follow-up
    "INSERT INTO decisions (launch_id, kind, decided_by, decided_on, rationale, follow_up, acknowledged_blockers) "
    "VALUES (?, 'no_go', 'M', '2026-11-02', 'R', 'F', 1)",               # checkbox on a No-go
    "INSERT INTO decisions (launch_id, kind, decided_by, decided_on, rationale, action, capability) "
    "VALUES (?, 'go', 'M', '2026-11-02', 'R', 'capability_on', 'memory')",  # Go posing as scope change
])
def test_database_enforces_decision_rules(conn, v21, sql):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (v21,))


def test_scope_changes_save_snapshot_from_before_the_change(conn, v21):
    disable_capability(conn, v21, Capability.TOOL_USE, OFF, TODAY)
    (d,) = [d for d in list_decisions(conn, v21) if d.kind is DecisionKind.SCOPE_CHANGE]
    assert d.snapshot["headline"] == "Not ready: 1 blocker"  # before, not after (Ready)
    enable_capability(conn, v21, Capability.TOOL_USE, ScopeChangeInput("M", "Eval fixed."), TODAY)
    latest_scope = list_decisions(conn, v21, kind="scope_change")[0]
    assert latest_scope.title == "Tool use turned on"
    assert latest_scope.snapshot["headline"] == "Ready"


# --- Can't be changed or deleted -------------------------------------------------


def test_decisions_cannot_be_changed(conn, v21):
    with pytest.raises(sqlite3.IntegrityError, match="cannot be changed"):
        conn.execute("UPDATE decisions SET rationale = 'edited'")


def test_decisions_cannot_be_deleted(conn, v21):
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        conn.execute("DELETE FROM decisions")


def test_launch_with_decisions_cannot_be_deleted(conn, v21):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM launches WHERE id = ?", (v21,))


def test_reseeding_still_clears_decisions(conn, v21):
    record_go_no_go(conn, v21, NO_GO, TODAY)
    seed_database(conn, today=TODAY)
    assert len(list_decisions(conn)) == 1  # just the seeded No-go


# --- Reading ----------------------------------------------------------------------


def test_log_mixes_kinds_newest_first(conn, v21):
    disable_capability(conn, v21, Capability.TOOL_USE, OFF, TODAY)
    record_go_no_go(conn, v21, GO, TODAY)  # Ready after the scope change
    titles = [d.title for d in list_decisions(conn, v21)]
    assert titles == ["Go", "Tool use turned off", "No-go"]


def test_same_day_decisions_in_order_recorded(conn, v22):
    first = record_go_no_go(conn, v22, NO_GO, TODAY)
    second = record_go_no_go(conn, v22, NO_GO, TODAY)
    assert [d.id for d in list_decisions(conn, v22)] == [second, first]


def test_backdated_decision_sorts_by_its_date(conn, v22):
    newer = record_go_no_go(conn, v22, NO_GO, TODAY)
    older = record_go_no_go(conn, v22, GoNoGoInput(DecisionKind.NO_GO, "M", TODAY - timedelta(days=5),
                                                   "R", "F"), TODAY)
    assert [d.id for d in list_decisions(conn, v22)] == [newer, older]
    assert latest_go_no_go(conn, v22).id == newer


def test_latest_go_no_go_ignores_scope_changes(conn, v21):
    disable_capability(conn, v21, Capability.TOOL_USE, OFF, TODAY)
    assert latest_go_no_go(conn, v21).kind is DecisionKind.NO_GO


def test_latest_is_none_without_go_no_go(conn, v22):
    assert latest_go_no_go(conn, v22) is None


def test_latest_by_launch(conn, v21, v22):
    latest = latest_go_no_go_by_launch(conn)
    assert set(latest) == {v21}
    assert latest[v21].title == "No-go"


def test_all_launches_list_and_filters(conn, v21, v22):
    record_go_no_go(conn, v22, NO_GO, TODAY)
    disable_capability(conn, v21, Capability.TOOL_USE, OFF, TODAY)
    everything = list_decisions(conn)
    assert len(everything) == 3
    assert {d.launch_name for d in everything} == {
        "Model Atlas v2.1 — trusted testers", "Model Atlas v2.2 — adding code execution"}
    assert [d.launch_id for d in list_decisions(conn, launch_id=v22)] == [v22]
    assert [d.title for d in list_decisions(conn, kind="scope_change")] == ["Tool use turned off"]
    assert len(list_decisions(conn, kind="no_go")) == 2


# --- Changes since a decision -------------------------------------------------------


def test_nothing_changed_since_decision(conn, v21):
    latest = latest_go_no_go(conn, v21)
    since = changes_since(conn, latest, assess_launch(conn, v21, TODAY))
    assert not since.anything_changed
    assert since.then == since.now == "Not ready: 1 blocker"


def test_readiness_change_is_spotted(conn, v21):
    make_ready(conn, v21)
    since = changes_since(conn, latest_go_no_go(conn, v21), assess_launch(conn, v21, TODAY))
    assert since.readiness_changed
    assert (since.then, since.now) == ("Not ready: 1 blocker", "Ready")


def test_different_blockers_same_count_is_a_change(conn, v21):
    gates = {g["gate_key"]: g for g in get_gates(conn, v21)}
    update_gate(conn, gates["tool_use_safety_eval"]["id"],
                GateUpdate(GateStatus.PASSED, "Dana K.", None, None, None, None))
    update_gate(conn, gates["rollback_plan"]["id"],
                GateUpdate(GateStatus.FAILED, "Ravi S.", None, None, None, None))
    since = changes_since(conn, latest_go_no_go(conn, v21), assess_launch(conn, v21, TODAY))
    assert since.then == since.now == "Not ready: 1 blocker"
    assert since.readiness_changed


def test_scope_changes_since_are_counted(conn, v21):
    decision = latest_go_no_go(conn, v21)
    disable_capability(conn, v21, Capability.TOOL_USE, OFF, TODAY)
    since = changes_since(conn, decision, assess_launch(conn, v21, TODAY))
    assert since.scope_changes_since == 1
    assert since.anything_changed
