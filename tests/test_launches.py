"""Saving and loading launches (temporary database, no web server)."""

from datetime import date

import pytest

from launch_readiness import launches as launches_module
from launch_readiness import settings
from launch_readiness.db import get_connection, init_db
from launch_readiness.launches import (
    create_launch,
    gate_due_date,
    get_configuration,
    get_gates,
    list_launches,
)
from launch_readiness.models import Capability, LaunchInput, Stage, Surface
from launch_readiness.rules_engine import required_gates

from .conftest import BASELINE


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    init_db(c)
    yield c
    c.close()


def atlas_v21(**overrides):
    fields = dict(
        name="Model Atlas v2.1 — trusted testers",
        model_version="Model Atlas v2.1",
        target_date=date(2026, 12, 15),
        stage=Stage.TRUSTED_TESTERS,
        surfaces=frozenset({Surface.API, Surface.CONSUMER_APP}),
        capabilities=frozenset({Capability.TOOL_USE}),
    )
    fields.update(overrides)
    return LaunchInput(**fields)


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_atlas_v21_gets_exactly_its_required_gates(conn, rules):
    data = atlas_v21()
    launch_id = create_launch(conn, data, rules)
    saved = [g["gate_key"] for g in get_gates(conn, launch_id)]
    expected = [g.id for g in required_gates(data.configuration(), rules)]
    assert saved == expected
    assert set(saved) == BASELINE | {"tool_use_safety_eval", "consumer_abuse_readiness"}


def test_new_gates_start_not_started_and_unassigned(conn, rules):
    launch_id = create_launch(conn, atlas_v21(), rules)
    for gate in get_gates(conn, launch_id):
        assert gate["status"] == "not_started"
        assert gate["owner"] is None
        assert gate["removed_at"] is None


def test_gate_name_and_team_copied_from_rules(conn, rules):
    launch_id = create_launch(conn, atlas_v21(), rules)
    for gate in get_gates(conn, launch_id):
        definition = rules.definition(gate["gate_key"])
        assert (gate["name"], gate["team"]) == (definition.name, definition.team)


def test_gates_due_seven_days_before_target_date(conn, rules):
    assert settings.GATE_DUE_DAYS_BEFORE_LAUNCH == 7
    launch_id = create_launch(conn, atlas_v21(target_date=date(2026, 12, 15)), rules)
    due_dates = {g["due_date"] for g in get_gates(conn, launch_id)}
    assert due_dates == {"2026-12-08"}


def test_due_date_follows_the_setting(conn, rules, monkeypatch):
    monkeypatch.setattr(settings, "GATE_DUE_DAYS_BEFORE_LAUNCH", 14)
    launch_id = create_launch(conn, atlas_v21(target_date=date(2026, 12, 15)), rules)
    assert {g["due_date"] for g in get_gates(conn, launch_id)} == {"2026-12-01"}


def test_due_date_crosses_month_and_year_boundaries():
    assert gate_due_date(date(2027, 1, 3)) == date(2026, 12, 27)
    assert gate_due_date(date(2026, 3, 5), days_before=7) == date(2026, 2, 26)


def test_configuration_round_trips(conn, rules):
    data = atlas_v21()
    launch_id = create_launch(conn, data, rules)
    assert get_configuration(conn, launch_id) == data.configuration()


def test_limited_ga_enterprise_code_execution_gets_extra_gates(conn, rules):
    data = atlas_v21(
        stage=Stage.LIMITED_GA,
        surfaces=frozenset({Surface.ENTERPRISE}),
        capabilities=frozenset({Capability.CODE_EXECUTION}),
    )
    launch_id = create_launch(conn, data, rules)
    saved = {g["gate_key"] for g in get_gates(conn, launch_id)}
    assert saved == BASELINE | {
        "sandbox_security_review",
        "data_governance_privacy",
        "capacity_signoff",
        "legal_policy_review",
    }


def test_failure_partway_saves_nothing(conn, rules, monkeypatch):
    """If a gate can't be saved, the launch and its features aren't saved either."""
    real = launches_module.required_gates

    def duplicate_a_gate(config, rules=None):
        gates = real(config, rules)
        return gates + [gates[0]]  # second insert breaks UNIQUE(launch_id, gate_key)

    monkeypatch.setattr(launches_module, "required_gates", duplicate_a_gate)
    with pytest.raises(Exception):
        create_launch(conn, atlas_v21(), rules)
    assert count(conn, "launches") == 0
    assert count(conn, "launch_features") == 0
    assert count(conn, "gates") == 0


def test_list_launches_newest_first_with_gate_counts(conn, rules):
    first = create_launch(conn, atlas_v21(name="First"), rules)
    second = create_launch(
        conn, atlas_v21(name="Second", capabilities=frozenset(Capability)), rules
    )
    rows = list_launches(conn)
    assert [r["id"] for r in rows] == [second, first]
    assert rows[0]["gate_count"] == 12  # 6 baseline + 5 capabilities + consumer app
    assert rows[1]["gate_count"] == 8


def test_unknown_launch_has_no_configuration(conn):
    assert get_configuration(conn, 999) is None
