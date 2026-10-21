"""The sample data and the `flask seed` command."""

from datetime import date

import pytest

from launch_readiness.app import create_app
from launch_readiness.dashboard import gate_view, needs_attention
from launch_readiness.db import get_connection
from launch_readiness.launches import create_launch, get_configuration, get_gates, list_launches
from launch_readiness.models import Capability, Configuration, Stage, Surface
from launch_readiness.seed import seed_database

from .test_gate_editing import ATLAS

TODAY = date(2026, 11, 2)

EXPECTED_CONFIG = Configuration(
    "Model Atlas v2.1",
    Stage.TRUSTED_TESTERS,
    frozenset({Surface.API, Surface.CONSUMER_APP}),
    frozenset({Capability.TOOL_USE}),
)


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def seeded(conn):
    return seed_database(conn, today=TODAY)


def views(conn, launch_id):
    return [gate_view(g, (), TODAY) for g in get_gates(conn, launch_id)]


def test_creates_exactly_two_launches_with_expected_configs(conn, seeded):
    v21, v22 = seeded
    assert len(list_launches(conn)) == 2
    assert get_configuration(conn, v21) == EXPECTED_CONFIG
    v22_config = get_configuration(conn, v22)
    assert v22_config.model_version == "Model Atlas v2.2"
    assert Capability.CODE_EXECUTION not in v22_config.capabilities
    assert v22_config.capabilities == EXPECTED_CONFIG.capabilities


def test_v21_has_exactly_one_blocker(conn, seeded):
    gates = {g.gate_key: g for g in views(conn, seeded[0])}
    statuses = sorted(g.status.value for g in gates.values())
    assert statuses == ["failed", "passed", "passed", "passed", "passed", "passed", "waived"]
    assert gates["tool_use_safety_eval"].status.value == "failed"
    assert [g.gate_key for g in needs_attention(gates.values())] == ["tool_use_safety_eval"]


def test_v21_blocker_is_overdue_on_seed_day(conn, seeded):
    gates = {g.gate_key: g for g in views(conn, seeded[0])}
    assert gates["tool_use_safety_eval"].overdue
    assert sum(g.overdue for g in gates.values()) == 1


def test_comms_waiver_has_rationale_and_approver(conn, seeded):
    comms = next(g for g in views(conn, seeded[0]) if g.gate_key == "comms")
    assert comms.status.value == "waived"
    assert comms.waiver_rationale.startswith("Trusted-tester release only")
    assert comms.waived_by == "Morgan T. (VP, Product)"


def test_every_waived_gate_has_rationale_and_approver(conn, seeded):
    for launch_id in seeded:
        for g in views(conn, launch_id):
            if g.status.value == "waived":
                assert g.waiver_rationale and g.waived_by


def test_v22_mostly_in_progress_with_comms_unassigned(conn, seeded):
    gates = {g.gate_key: g for g in views(conn, seeded[1])}
    assert sum(g.status.value == "in_progress" for g in gates.values()) == 4
    assert gates["comms"].is_unassigned
    assert not any(g.overdue for g in gates.values())


def test_dates_are_relative_to_seed_day(conn, seeded):
    launches = {l["model_version"]: l for l in list_launches(conn)}
    assert launches["Model Atlas v2.1"]["target_date"] == "2026-11-14"  # +12 days
    assert launches["Model Atlas v2.2"]["target_date"] == "2026-12-02"  # +30 days


def test_seeding_replaces_existing_data(conn, seeded):
    create_launch(conn, ATLAS)
    assert len(list_launches(conn)) == 3
    seed_database(conn, today=TODAY)
    assert len(list_launches(conn)) == 2


# --- The command --------------------------------------------------------------


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "app.db")})


def count_launches(app):
    c = get_connection(app.config["DATABASE"])
    try:
        return c.execute("SELECT COUNT(*) FROM launches").fetchone()[0]
    finally:
        c.close()


def test_seed_command_with_yes(app):
    result = app.test_cli_runner().invoke(args=["seed", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Loaded 2 sample launches." in result.output
    assert count_launches(app) == 2


def test_seed_command_asks_first_and_does_nothing_if_declined(app):
    c = get_connection(app.config["DATABASE"])
    create_launch(c, ATLAS)
    c.close()
    result = app.test_cli_runner().invoke(args=["seed"], input="n\n")
    assert result.exit_code != 0
    assert "This deletes all launches" in result.output
    assert count_launches(app) == 1


def test_seed_command_confirmed(app):
    result = app.test_cli_runner().invoke(args=["seed"], input="y\n")
    assert result.exit_code == 0, result.output
    assert count_launches(app) == 2
