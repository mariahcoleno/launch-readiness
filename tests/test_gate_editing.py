"""Saving gate edits, and the dashboard and edit pages. "Today" is fixed."""

import sqlite3
from datetime import date

import pytest

from launch_readiness.app import create_app
from launch_readiness.db import get_connection
from launch_readiness.gate_form import GateUpdate
from launch_readiness.launches import create_launch, get_gate, get_gates, update_gate
from launch_readiness.models import Capability, GateStatus, LaunchInput, Stage, Surface

TODAY = date(2026, 11, 2)

ATLAS = LaunchInput(
    name="Model Atlas v2.1 — trusted testers",
    model_version="Model Atlas v2.1",
    target_date=date(2026, 11, 14),  # 12 days after TODAY; gates due 2026-11-07
    stage=Stage.TRUSTED_TESTERS,
    surfaces=frozenset({Surface.API, Surface.CONSUMER_APP}),
    capabilities=frozenset({Capability.TOOL_USE}),
)


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db"), "TODAY": TODAY})


@pytest.fixture
def conn(app):
    c = get_connection(app.config["DATABASE"])
    yield c
    c.close()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def launch_id(conn):
    return create_launch(conn, ATLAS)


def gate_by_key(conn, launch_id, key):
    return next(g for g in get_gates(conn, launch_id) if g["gate_key"] == key)


def set_gate(conn, launch_id, key, **fields):
    defaults = dict(status=GateStatus.PASSED, owner="Priya N.", due_date=date(2026, 11, 7),
                    notes=None, waiver_rationale=None, waived_by=None)
    defaults.update(fields)
    update_gate(conn, gate_by_key(conn, launch_id, key)["id"], GateUpdate(**defaults))


# --- Saving -------------------------------------------------------------------


def test_update_gate_saves_every_field(conn, launch_id):
    set_gate(conn, launch_id, "comms", status=GateStatus.WAIVED, owner="Leo M.",
             due_date=date(2026, 11, 1), notes="No announcement.",
             waiver_rationale="Trusted testers only.", waived_by="Morgan T.")
    row = gate_by_key(conn, launch_id, "comms")
    assert (row["status"], row["owner"], row["due_date"], row["notes"],
            row["waiver_rationale"], row["waived_by"]) == (
        "waived", "Leo M.", "2026-11-01", "No announcement.", "Trusted testers only.", "Morgan T.")


@pytest.mark.parametrize(
    "rationale, waived_by",
    [(None, "Morgan T."), ("  ", "Morgan T."), ("Reason", None), ("Reason", " ")],
)
def test_database_rejects_waiver_missing_rationale_or_approver(conn, launch_id, rationale, waived_by):
    gate_id = gate_by_key(conn, launch_id, "comms")["id"]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE gates SET status = 'waived', waiver_rationale = ?, waived_by = ? WHERE id = ?",
            (rationale, waived_by, gate_id),
        )


def test_database_rejects_waiver_fields_on_a_non_waived_gate(conn, launch_id):
    gate_id = gate_by_key(conn, launch_id, "comms")["id"]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE gates SET status = 'passed', waiver_rationale = 'old reason' WHERE id = ?",
            (gate_id,),
        )


def test_gate_from_another_launch_is_not_found(conn, launch_id):
    other = create_launch(conn, ATLAS)
    gate_id = get_gates(conn, other)[0]["id"]
    assert get_gate(conn, launch_id, gate_id) is None
    assert get_gate(conn, other, gate_id) is not None


def test_removed_gate_is_not_found(conn, launch_id):
    gate_id = gate_by_key(conn, launch_id, "comms")["id"]
    with conn:
        conn.execute("UPDATE gates SET removed_at = datetime('now') WHERE id = ?", (gate_id,))
    assert get_gate(conn, launch_id, gate_id) is None


# --- Dashboard page -----------------------------------------------------------


def test_dashboard_header_shows_target_date_and_countdown(client, launch_id):
    html = client.get(f"/launches/{launch_id}").get_data(as_text=True)
    assert "2026-11-14" in html
    assert "12 days away" in html


def test_dashboard_shows_launch_date_passed(client, app, conn):
    late = create_launch(conn, LaunchInput(**{**ATLAS.__dict__, "target_date": date(2026, 10, 1)}))
    html = client.get(f"/launches/{late}").get_data(as_text=True)
    assert "Launch date passed" in html


def test_dashboard_groups_by_team_a_to_z(client, launch_id):
    html = client.get(f"/launches/{launch_id}").get_data(as_text=True)
    teams = ["Communications", "Infrastructure", "Safety", "Trust &amp; Safety"]
    positions = [html.index(f">{team} <span class=\"team-count\">") for team in teams]
    assert positions == sorted(positions)


def test_dashboard_status_labels_and_tags(client, conn, launch_id):
    set_gate(conn, launch_id, "safety_evals", status=GateStatus.PASSED)
    set_gate(conn, launch_id, "tool_use_safety_eval", status=GateStatus.FAILED,
             owner="Dana K.", due_date=date(2026, 10, 31))
    html = client.get(f"/launches/{launch_id}").get_data(as_text=True)
    assert 'class="status status-passed">Passed<' in html
    assert 'class="status status-failed">Failed<' in html
    assert html.count('class="tag tag-overdue">Overdue<') == 2  # attention table + team table
    assert "1 of 7 gates done" in html
    assert "1 failed" in html and "1 overdue" in html


def test_needs_attention_section(client, conn, launch_id):
    for key in ("safety_evals", "red_team_signoff", "rollback_plan", "monitoring_oncall",
                "consumer_abuse_readiness"):
        set_gate(conn, launch_id, key)
    set_gate(conn, launch_id, "tool_use_safety_eval", status=GateStatus.FAILED,
             owner="Dana K.", due_date=date(2026, 10, 31))
    set_gate(conn, launch_id, "comms", status=GateStatus.IN_PROGRESS, owner=None)
    html = client.get(f"/launches/{launch_id}").get_data(as_text=True)
    attention = html.split('id="attention-heading"')[1].split("Gates by team")[0]
    assert "Needs attention (2)" in html
    assert "Tool-use safety eval" in attention and "Dana K." in attention
    assert "2026-10-31" in attention and "Safety" in attention
    assert "Comms plan" in attention and "Unassigned" in attention
    assert attention.index("Tool-use safety eval") < attention.index("Comms plan")
    assert "Rollback plan" not in attention


def test_needs_attention_empty_state(client, conn, launch_id):
    for gate in get_gates(conn, launch_id):
        set_gate(conn, launch_id, gate["gate_key"])
    html = client.get(f"/launches/{launch_id}").get_data(as_text=True)
    assert "Nothing needs attention" in html
    assert "7 of 7 gates done" in html


def test_new_launch_gates_all_show_as_unassigned(client, launch_id):
    html = client.get(f"/launches/{launch_id}").get_data(as_text=True)
    assert "Needs attention (7)" in html
    assert "7 unassigned" in html


def test_waiver_shown_on_dashboard(client, conn, launch_id):
    set_gate(conn, launch_id, "comms", status=GateStatus.WAIVED, owner="Leo M.",
             waiver_rationale="Trusted testers only.", waived_by="Morgan T. (VP, Product)")
    html = client.get(f"/launches/{launch_id}").get_data(as_text=True)
    assert "Waived by Morgan T. (VP, Product): Trusted testers only." in html


# --- Edit page ----------------------------------------------------------------


def edit_url(launch_id, gate_id):
    return f"/launches/{launch_id}/gates/{gate_id}/edit"


def test_edit_page_shows_current_values(client, conn, launch_id):
    set_gate(conn, launch_id, "rollback_plan", status=GateStatus.IN_PROGRESS,
             owner="Ravi S.", notes="Rehearsal booked.")
    gate = gate_by_key(conn, launch_id, "rollback_plan")
    html = client.get(edit_url(launch_id, gate["id"])).get_data(as_text=True)
    assert '<option value="in_progress" selected>' in html
    assert 'value="Ravi S."' in html
    assert 'value="2026-11-07"' in html
    assert "Rehearsal booked." in html


def test_valid_edit_redirects_and_dashboard_shows_it(client, conn, launch_id):
    gate = gate_by_key(conn, launch_id, "rollback_plan")
    response = client.post(edit_url(launch_id, gate["id"]), data={
        "status": "passed", "owner": "Ravi S.", "due_date": "2026-11-07", "notes": "Rehearsed.",
    })
    assert response.status_code == 302
    assert response.headers["Location"] == f"/launches/{launch_id}"
    html = client.get(f"/launches/{launch_id}").get_data(as_text=True)
    assert "1 of 7 gates done" in html
    assert "Rehearsed." in html


def test_waiver_without_rationale_or_approver_shows_errors_and_changes_nothing(client, conn, launch_id):
    gate = gate_by_key(conn, launch_id, "comms")
    response = client.post(edit_url(launch_id, gate["id"]), data={
        "status": "waived", "owner": "Leo M.", "due_date": "2026-11-07",
        "notes": "Typed notes", "waiver_rationale": "", "waived_by": "",
    })
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "A waived gate needs a waiver rationale." in html
    assert "Say who approved the waiver." in html
    assert 'value="Leo M."' in html and "Typed notes" in html
    assert gate_by_key(conn, launch_id, "comms")["status"] == "not_started"


def test_changing_away_from_waived_clears_waiver_on_page(client, conn, launch_id):
    set_gate(conn, launch_id, "comms", status=GateStatus.WAIVED, owner="Leo M.",
             waiver_rationale="Trusted testers only.", waived_by="Morgan T.")
    gate = gate_by_key(conn, launch_id, "comms")
    client.post(edit_url(launch_id, gate["id"]), data={
        "status": "in_progress", "owner": "Leo M.", "due_date": "2026-11-07",
        "waiver_rationale": "Trusted testers only.", "waived_by": "Morgan T.",
    })
    row = gate_by_key(conn, launch_id, "comms")
    assert row["status"] == "in_progress"
    assert row["waiver_rationale"] is None and row["waived_by"] is None


def test_edit_wrong_launch_gate_pair_is_404(client, conn, launch_id):
    other = create_launch(conn, ATLAS)
    other_gate = get_gates(conn, other)[0]["id"]
    assert client.get(edit_url(launch_id, other_gate)).status_code == 404
    assert client.post(edit_url(launch_id, other_gate), data={"status": "passed"}).status_code == 404
    assert client.get(edit_url(999, 1)).status_code == 404
