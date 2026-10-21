"""The launch facts gathered for the AI summary (no AI involved)."""

import json
import sqlite3
from datetime import date

import pytest

from launch_readiness.db import get_connection, get_readonly_connection, init_db
from launch_readiness.decision_form import ScopeChangeInput
from launch_readiness.models import Capability
from launch_readiness.scope_change import disable_capability
from launch_readiness.seed import seed_database
from launch_readiness.status_report import build_status_report

TODAY = date(2026, 11, 2)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    c = get_connection(path)
    init_db(c)
    seed_database(c, today=TODAY)
    c.close()
    return path


@pytest.fixture
def ro(db_path):
    c = get_readonly_connection(db_path)
    yield c
    c.close()


def dump_all(path):
    c = get_connection(path)
    try:
        return {t: [tuple(r) for r in c.execute(f"SELECT * FROM {t} ORDER BY rowid")]
                for t in ("launches", "launch_features", "gates", "decisions")}
    finally:
        c.close()


def test_v21_facts(ro):
    r = build_status_report(ro, 1, TODAY)
    assert r["launch"]["name"] == "Model Atlas v2.1 — trusted testers"
    assert r["launch"]["stage"] == "Trusted testers"
    assert r["launch"]["surfaces"] == ["API", "Consumer app"]
    assert r["launch"]["capabilities"] == ["Tool use"]
    assert r["launch"]["countdown"] == "12 days away"
    assert r["readiness"]["headline"] == "Not ready: 1 blocker"
    (blocker,) = r["readiness"]["blockers"]
    assert blocker["name"] == "Tool-use safety eval"
    (attention,) = r["needs_attention"]
    assert attention == {"gate": "Tool-use safety eval", "team": "Safety", "owner": "Dana K.",
                         "status": "Failed", "due_date": "2026-10-31", "flags": ["Failed", "Overdue"]}
    latest = r["latest_go_no_go_decision"]
    assert (latest["decision"], latest["decided_on"], latest["decided_by"]) == (
        "No-go", "2026-10-30", "Morgan T. (VP, Product)")
    assert latest["follow_up"].startswith("Re-run the eval")
    (waived,) = r["waived_gates"]
    assert waived["gate"] == "Comms plan" and waived["waived_by"] == "Morgan T. (VP, Product)"
    assert {"team": "Safety", "done": 2, "total": 3} in r["teams"]


def test_v22_facts(ro):
    r = build_status_report(ro, 2, TODAY)
    assert r["latest_go_no_go_decision"] is None
    flags = {a["gate"]: a["flags"] for a in r["needs_attention"]}
    assert flags["Red-team sign-off"] == ["At risk"]
    assert flags["Comms plan"] == ["Unassigned"]


def test_scope_change_shows_removed_gate_not_blocker(db_path):
    c = get_connection(db_path)
    disable_capability(c, 1, Capability.TOOL_USE,
                       ScopeChangeInput("Morgan T.", "Eval failing.", "Turn back on in v2.1.1."), TODAY)
    c.close()
    ro = get_readonly_connection(db_path)
    r = build_status_report(ro, 1, TODAY)
    ro.close()
    assert r["readiness"]["headline"] == "Ready"
    assert r["removed_gates"] == [{"gate": "Tool-use safety eval", "last_status": "Failed",
                                   "removed_on": "2026-11-02", "follow_up": "Turn back on in v2.1.1."}]
    assert all(b["name"] != "Tool-use safety eval" for b in r["readiness"]["blockers"])
    (scope,) = r["recent_scope_changes"]
    assert scope["decision"] == "Tool use turned off"


def test_same_output_every_time(ro):
    assert json.dumps(build_status_report(ro, 1, TODAY)) == json.dumps(build_status_report(ro, 1, TODAY))


def test_unknown_launch(ro):
    assert build_status_report(ro, 999, TODAY) is None


def test_gathering_writes_nothing(db_path, ro):
    before = dump_all(db_path)
    build_status_report(ro, 1, TODAY)
    build_status_report(ro, 2, TODAY)
    assert dump_all(db_path) == before


def test_read_only_connection_refuses_writes(ro):
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ro.execute("UPDATE gates SET status = 'passed'")
