"""Launching with a capability turned off (temporary database)."""

from datetime import date

import pytest

from launch_readiness import scope_change
from launch_readiness.db import get_connection, init_db
from launch_readiness.decision_form import ScopeChangeInput, parse_scope_change_form
from launch_readiness.launch_status import assess_launch
from launch_readiness.launches import (
    create_launch,
    get_configuration,
    get_gates,
    get_removed_gates,
    get_scope_changes,
)
from launch_readiness.models import Capability, LaunchInput, Stage, Surface
from launch_readiness.rules_engine import gate_diff
from launch_readiness.scope_change import CapabilityNotEnabled, disable_capability, preview_disable
from launch_readiness.seed import seed_database

from .test_gate_diff import SHARED_RULES

TODAY = date(2026, 11, 2)

DECISION = ScopeChangeInput(
    decided_by="Morgan T. (VP, Product)",
    rationale="Tool-use eval won't pass before the trusted-tester date.",
    follow_up="Re-enable tool use for v2.1.1 once the tool-use eval passes.",
)


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def v21(conn):
    return seed_database(conn, today=TODAY)[0]


def statuses(conn, launch_id):
    return {g["gate_key"]: g["status"] for g in get_gates(conn, launch_id)}


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- Doing it -----------------------------------------------------------------


def test_disabling_tool_use_removes_only_its_gate(conn, v21):
    before = statuses(conn, v21)
    disable_capability(conn, v21, Capability.TOOL_USE, DECISION, TODAY)
    after = statuses(conn, v21)
    assert set(before) - set(after) == {"tool_use_safety_eval"}
    assert after == {k: v for k, v in before.items() if k != "tool_use_safety_eval"}


def test_removed_gate_keeps_last_status_and_links_to_decision(conn, v21):
    decision_id = disable_capability(conn, v21, Capability.TOOL_USE, DECISION, TODAY)
    (removed,) = get_removed_gates(conn, v21)
    assert removed["gate_key"] == "tool_use_safety_eval"
    assert removed["status"] == "failed"
    assert removed["removed_at"] == "2026-11-02"
    assert removed["removed_by_decision_id"] == decision_id
    assert removed["follow_up"] == DECISION.follow_up
    assert removed["capability"] == "tool_use"


def test_capability_taken_out_of_configuration(conn, v21):
    disable_capability(conn, v21, Capability.TOOL_USE, DECISION, TODAY)
    assert Capability.TOOL_USE not in get_configuration(conn, v21).capabilities


def test_exactly_one_scope_change_decision_recorded(conn, v21):
    disable_capability(conn, v21, Capability.TOOL_USE, DECISION, TODAY)
    (d,) = get_scope_changes(conn, v21)
    assert (d["kind"], d["decided_by"], d["decided_on"], d["rationale"], d["follow_up"],
            d["capability"]) == (
        "scope_change", DECISION.decided_by, "2026-11-02", DECISION.rationale,
        DECISION.follow_up, "tool_use")
    assert count(conn, "decisions") == 1


def test_v21_becomes_ready(conn, v21):
    assert assess_launch(conn, v21, TODAY).headline == "Not ready: 1 blocker"
    disable_capability(conn, v21, Capability.TOOL_USE, DECISION, TODAY)
    assert assess_launch(conn, v21, TODAY).ready


def test_removed_gates_match_gate_diff(conn, rules):
    data = LaunchInput("All on", "v9", date(2026, 12, 1), Stage.TRUSTED_TESTERS,
                       frozenset({Surface.API}), frozenset(Capability))
    launch_id = create_launch(conn, data)
    for cap in Capability:
        config = get_configuration(conn, launch_id)
        expected = {g.id for g in gate_diff(config, config.with_capability(cap, False), rules).removed}
        before = set(statuses(conn, launch_id))
        disable_capability(conn, launch_id, cap, DECISION, TODAY)
        assert before - set(statuses(conn, launch_id)) == expected


def test_shared_gate_stays_while_another_trigger_is_on(conn):
    data = LaunchInput("Shared", "v1", date(2026, 12, 1), Stage.INTERNAL,
                       frozenset({Surface.API}),
                       frozenset({Capability.MEMORY, Capability.FILE_UPLOADS}))
    launch_id = create_launch(conn, data, SHARED_RULES)

    disable_capability(conn, launch_id, Capability.MEMORY, DECISION, TODAY, SHARED_RULES)
    assert set(statuses(conn, launch_id)) == {"base", "data_review"}
    assert count(conn, "decisions") == 1  # still recorded, even with nothing removed

    disable_capability(conn, launch_id, Capability.FILE_UPLOADS, DECISION, TODAY, SHARED_RULES)
    assert set(statuses(conn, launch_id)) == {"base"}


def test_failure_partway_changes_nothing(conn, v21, monkeypatch):
    def broken(*args):
        raise RuntimeError("disk full")

    monkeypatch.setattr(scope_change, "_mark_gates_removed", broken)
    with pytest.raises(RuntimeError):
        disable_capability(conn, v21, Capability.TOOL_USE, DECISION, TODAY)
    assert Capability.TOOL_USE in get_configuration(conn, v21).capabilities
    assert "tool_use_safety_eval" in statuses(conn, v21)
    assert count(conn, "decisions") == 0


def test_disabling_a_capability_that_is_off_is_refused(conn, v21):
    with pytest.raises(CapabilityNotEnabled):
        disable_capability(conn, v21, Capability.CODE_EXECUTION, DECISION, TODAY)
    with pytest.raises(CapabilityNotEnabled):
        preview_disable(conn, v21, Capability.CODE_EXECUTION, TODAY)
    assert count(conn, "decisions") == 0


# --- Preview ------------------------------------------------------------------


def test_preview_shows_removed_gates_and_verdict_after(conn, v21):
    p = preview_disable(conn, v21, Capability.TOOL_USE, TODAY)
    assert [(g.gate_key, g.status.value) for g in p.removed] == [("tool_use_safety_eval", "failed")]
    assert p.before.headline == "Not ready: 1 blocker"
    assert p.after.ready
    assert p.clears_blockers


def test_preview_changes_nothing(conn, v21):
    before = statuses(conn, v21)
    preview_disable(conn, v21, Capability.TOOL_USE, TODAY)
    assert statuses(conn, v21) == before
    assert count(conn, "decisions") == 0


# --- Form ---------------------------------------------------------------------


def valid_form(**overrides):
    return {**DECISION.__dict__, **overrides}


def test_valid_form():
    decision, errors = parse_scope_change_form(valid_form())
    assert errors == {}
    assert decision == DECISION


@pytest.mark.parametrize("field", ["decided_by", "rationale", "follow_up"])
@pytest.mark.parametrize("value", ["", "   "])
def test_each_field_required(field, value):
    decision, errors = parse_scope_change_form(valid_form(**{field: value}))
    assert decision is None
    assert list(errors) == [field]


@pytest.mark.parametrize(
    "field, limit", [("decided_by", 100), ("rationale", 2000), ("follow_up", 2000)]
)
def test_length_limits(field, limit):
    _, errors = parse_scope_change_form(valid_form(**{field: "x" * (limit + 1)}))
    assert list(errors) == [field]
    _, errors = parse_scope_change_form(valid_form(**{field: "x" * limit}))
    assert errors == {}
