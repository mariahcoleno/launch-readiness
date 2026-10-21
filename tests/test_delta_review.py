"""Turning a capability on: the delta review (temporary database)."""

from datetime import date

import pytest

from launch_readiness import scope_change
from launch_readiness.db import get_connection, init_db
from launch_readiness.decision_form import ScopeChangeInput, parse_scope_change_form
from launch_readiness.gate_form import GateUpdate
from launch_readiness.launch_status import assess_launch
from launch_readiness.launches import (
    create_launch,
    get_configuration,
    get_gates,
    get_removed_gates,
    get_scope_changes,
    update_gate,
)
from launch_readiness.models import Capability, GateStatus, LaunchInput, Stage, Surface
from launch_readiness.rules_engine import gate_diff
from launch_readiness.scope_change import (
    CapabilityAlreadyEnabled,
    disable_capability,
    enable_capability,
    preview_enable,
    restore_note,
)
from launch_readiness.seed import seed_database

from .test_gate_diff import SHARED_RULES

TODAY = date(2026, 11, 2)
ON = ScopeChangeInput("Morgan T. (VP, Product)", "Sandbox ready; adding code execution for v2.2.")
OFF = ScopeChangeInput("Morgan T. (VP, Product)", "Tool-use eval failing.",
                       "Re-enable tool use once the eval passes.")


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


def gates_by_key(conn, launch_id):
    return {g["gate_key"]: g for g in get_gates(conn, launch_id)}


def snapshot(conn, launch_id):
    return {k: tuple(g) for k, g in gates_by_key(conn, launch_id).items()}


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- Adding new gates ---------------------------------------------------------


def test_v22_code_execution_adds_only_sandbox_review(conn, v22):
    before = snapshot(conn, v22)
    enable_capability(conn, v22, Capability.CODE_EXECUTION, ON, TODAY)
    after = snapshot(conn, v22)
    assert set(after) - set(before) == {"sandbox_security_review"}
    assert {k: v for k, v in after.items() if k in before} == before  # others untouched


def test_new_gate_starts_not_started_unassigned_and_due_by_the_usual_rule(conn, v22):
    decision_id = enable_capability(conn, v22, Capability.CODE_EXECUTION, ON, TODAY)
    g = gates_by_key(conn, v22)["sandbox_security_review"]
    assert g["status"] == "not_started"
    assert g["owner"] is None
    assert g["due_date"] == "2026-11-25"  # v2.2 target 2026-12-02 minus 7 days
    assert g["team"] == "Security"
    assert g["added_by_decision_id"] == decision_id


def test_configuration_now_includes_capability(conn, v22):
    enable_capability(conn, v22, Capability.CODE_EXECUTION, ON, TODAY)
    assert Capability.CODE_EXECUTION in get_configuration(conn, v22).capabilities


def test_one_capability_on_decision_recorded(conn, v22):
    enable_capability(conn, v22, Capability.CODE_EXECUTION, ON, TODAY)
    (d,) = get_scope_changes(conn, v22)
    assert (d["kind"], d["action"], d["capability"], d["decided_by"], d["decided_on"],
            d["rationale"], d["follow_up"]) == (
        "scope_change", "capability_on", "code_execution", ON.decided_by, "2026-11-02",
        ON.rationale, None)


def test_turning_capabilities_on_one_by_one_matches_gate_diff(conn, rules):
    data = LaunchInput("None on", "v9", date(2026, 12, 1), Stage.TRUSTED_TESTERS,
                       frozenset({Surface.API}), frozenset())
    launch_id = create_launch(conn, data)
    for cap in Capability:
        config = get_configuration(conn, launch_id)
        expected = {g.id for g in gate_diff(config, config.with_capability(cap, True), rules).added}
        before = set(gates_by_key(conn, launch_id))
        enable_capability(conn, launch_id, cap, ON, TODAY)
        assert set(gates_by_key(conn, launch_id)) - before == expected


def test_shared_gate_already_covered_adds_nothing_but_records_decision(conn):
    data = LaunchInput("Shared", "v1", date(2026, 12, 1), Stage.INTERNAL,
                       frozenset({Surface.API}), frozenset({Capability.FILE_UPLOADS}))
    launch_id = create_launch(conn, data, SHARED_RULES)
    preview = preview_enable(conn, launch_id, Capability.MEMORY, TODAY, SHARED_RULES)
    assert preview.added == ()
    enable_capability(conn, launch_id, Capability.MEMORY, ON, TODAY, SHARED_RULES)
    assert set(gates_by_key(conn, launch_id)) == {"base", "data_review"}
    assert count(conn, "decisions") == 1


def test_enabling_a_capability_that_is_on_is_refused(conn, v21):
    with pytest.raises(CapabilityAlreadyEnabled):
        enable_capability(conn, v21, Capability.TOOL_USE, ON, TODAY)
    with pytest.raises(CapabilityAlreadyEnabled):
        preview_enable(conn, v21, Capability.TOOL_USE, TODAY)
    assert count(conn, "decisions") == 0


def test_failure_partway_changes_nothing(conn, v22, monkeypatch):
    def broken(*args):
        raise RuntimeError("disk full")

    monkeypatch.setattr(scope_change, "_add_gates", broken)
    before = snapshot(conn, v22)
    with pytest.raises(RuntimeError):
        enable_capability(conn, v22, Capability.CODE_EXECUTION, ON, TODAY)
    assert snapshot(conn, v22) == before
    assert Capability.CODE_EXECUTION not in get_configuration(conn, v22).capabilities
    assert count(conn, "decisions") == 0


# --- Restoring removed gates ----------------------------------------------------


def test_round_trip_restores_the_same_row(conn, v21):
    original = gates_by_key(conn, v21)["tool_use_safety_eval"]
    disable_capability(conn, v21, Capability.TOOL_USE, OFF, TODAY)
    enable_capability(conn, v21, Capability.TOOL_USE, ON, TODAY)
    restored = gates_by_key(conn, v21)["tool_use_safety_eval"]
    assert restored["id"] == original["id"]
    assert conn.execute(
        "SELECT COUNT(*) FROM gates WHERE launch_id = ? AND gate_key = 'tool_use_safety_eval'",
        (v21,),
    ).fetchone()[0] == 1
    assert restored["removed_at"] is None and restored["removed_by_decision_id"] is None


def test_restored_gate_reset_to_not_started_keeping_owner_and_notes(conn, v21):
    original = gates_by_key(conn, v21)["tool_use_safety_eval"]
    disable_capability(conn, v21, Capability.TOOL_USE, OFF, TODAY)
    decision_id = enable_capability(conn, v21, Capability.TOOL_USE, ON, TODAY)
    g = gates_by_key(conn, v21)["tool_use_safety_eval"]
    assert g["status"] == "not_started"
    assert g["owner"] == "Dana K."
    assert g["notes"].startswith(original["notes"] + "\n")
    assert g["notes"].endswith(
        "2026-11-02: Restored when tool use was turned back on. Previous status: Failed.")
    assert g["due_date"] == "2026-11-07"  # usual rule from the target date, not the old date
    assert g["added_by_decision_id"] == decision_id


def test_restoring_a_waived_gate_records_the_waiver_and_clears_it(conn, v21):
    g = gates_by_key(conn, v21)["tool_use_safety_eval"]
    update_gate(conn, g["id"], GateUpdate(GateStatus.WAIVED, "Dana K.", None, None,
                                          "Covered by the v2.0 eval.", "Morgan T."))
    disable_capability(conn, v21, Capability.TOOL_USE, OFF, TODAY)
    enable_capability(conn, v21, Capability.TOOL_USE, ON, TODAY)
    g = gates_by_key(conn, v21)["tool_use_safety_eval"]
    assert g["status"] == "not_started"
    assert g["waiver_rationale"] is None and g["waived_by"] is None
    assert g["notes"] == (
        "2026-11-02: Restored when tool use was turned back on. Previous status: Waived. "
        'Previous waiver by Morgan T.: "Covered by the v2.0 eval."')


def test_restored_gate_leaves_removed_section_and_history_has_both(conn, v21):
    disable_capability(conn, v21, Capability.TOOL_USE, OFF, TODAY)
    assert len(get_removed_gates(conn, v21)) == 1
    enable_capability(conn, v21, Capability.TOOL_USE, ON, TODAY)
    assert get_removed_gates(conn, v21) == []
    assert [d["action"] for d in get_scope_changes(conn, v21)] == ["capability_on", "capability_off"]


def test_restored_gate_blocks_readiness_again(conn, v21):
    disable_capability(conn, v21, Capability.TOOL_USE, OFF, TODAY)
    assert assess_launch(conn, v21, TODAY).ready
    enable_capability(conn, v21, Capability.TOOL_USE, ON, TODAY)
    assert assess_launch(conn, v21, TODAY).headline == "Not ready: 1 blocker"


def test_restore_note_without_waiver():
    row = {"status": "passed", "waiver_rationale": None, "waived_by": None}
    assert restore_note(TODAY, Capability.WEB_BROWSING, row) == (
        "2026-11-02: Restored when web browsing was turned back on. Previous status: Passed.")


# --- Preview ------------------------------------------------------------------


def test_preview_lists_only_new_gates_with_reasons_and_due_date(conn, v22):
    p = preview_enable(conn, v22, Capability.CODE_EXECUTION, TODAY)
    (g,) = p.added
    assert g.id == "sandbox_security_review"
    assert g.reasons == ("Code execution is on",)
    assert g.due_date == date(2026, 11, 25)
    assert not g.restoring


def test_preview_marks_restored_gates_with_last_status(conn, v21):
    disable_capability(conn, v21, Capability.TOOL_USE, OFF, TODAY)
    (g,) = preview_enable(conn, v21, Capability.TOOL_USE, TODAY).added
    assert g.restoring
    assert g.previous_status is GateStatus.FAILED
    assert g.previous["removed_at"] == "2026-11-02"


def test_preview_readiness_before_and_after(conn, v21):
    disable_capability(conn, v21, Capability.TOOL_USE, OFF, TODAY)
    p = preview_enable(conn, v21, Capability.TOOL_USE, TODAY)
    assert p.before.ready
    assert p.after.headline == "Not ready: 1 blocker"


def test_preview_changes_nothing(conn, v22):
    before = snapshot(conn, v22)
    preview_enable(conn, v22, Capability.CODE_EXECUTION, TODAY)
    assert snapshot(conn, v22) == before
    assert count(conn, "decisions") == 0


# --- Form -----------------------------------------------------------------------


def test_follow_up_optional_when_turning_on():
    decision, errors = parse_scope_change_form(
        {"decided_by": "A", "rationale": "B", "follow_up": " "}, follow_up_required=False)
    assert errors == {}
    assert decision.follow_up is None


def test_follow_up_still_required_when_turning_off():
    _, errors = parse_scope_change_form({"decided_by": "A", "rationale": "B", "follow_up": ""})
    assert list(errors) == ["follow_up"]


@pytest.mark.parametrize("field", ["decided_by", "rationale"])
def test_decided_by_and_rationale_required_when_turning_on(field):
    form = {"decided_by": "A", "rationale": "B", field: ""}
    _, errors = parse_scope_change_form(form, follow_up_required=False)
    assert list(errors) == [field]


def test_follow_up_length_limit_when_turning_on():
    _, errors = parse_scope_change_form(
        {"decided_by": "A", "rationale": "B", "follow_up": "x" * 2001}, follow_up_required=False)
    assert list(errors) == ["follow_up"]


# --- Database rules ---------------------------------------------------------------


def test_scope_change_must_say_which_way(conn, v21):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO decisions (launch_id, kind, decided_by, decided_on, rationale, capability) "
            "VALUES (?, 'scope_change', 'A', '2026-11-02', 'B', 'tool_use')", (v21,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO decisions (launch_id, kind, decided_by, decided_on, rationale, action) "
            "VALUES (?, 'scope_change', 'A', '2026-11-02', 'B', 'capability_on')", (v21,))
