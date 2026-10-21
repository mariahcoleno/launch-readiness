"""Decision pages: recording a decision, the logs, and where decisions show up."""

from datetime import date

import pytest

from launch_readiness.app import create_app
from launch_readiness.db import SCHEMA_VERSION, get_connection, init_db
from launch_readiness.decisions import list_decisions
from launch_readiness.gate_form import GateUpdate
from launch_readiness.launches import get_gates, update_gate
from launch_readiness.models import GateStatus
from launch_readiness.seed import seed_database

TODAY = date(2026, 11, 2)

NO_GO = {"kind": "no_go", "decided_by": "Morgan T. (VP, Product)", "decided_on": "2026-11-02",
         "rationale": "Eval still failing.", "follow_up": "Revisit on 2026-11-09."}
GO_WITH_BLOCKERS = {"kind": "go", "decided_by": "Morgan T. (VP, Product)", "decided_on": "2026-11-02",
                    "rationale": "Accepting the eval risk for trusted testers.",
                    "follow_up": "Fix the eval in v2.1.1.", "acknowledge_blockers": "1"}


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db"), "TODAY": TODAY})
    c = get_connection(app.config["DATABASE"])
    seed_database(c, today=TODAY)
    c.close()
    return app


@pytest.fixture
def conn(app):
    c = get_connection(app.config["DATABASE"])
    yield c
    c.close()


@pytest.fixture
def client(app):
    return app.test_client()


def page(client, url):
    response = client.get(url)
    assert response.status_code == 200, url
    return response.get_data(as_text=True)


def record_section(html):
    return html.split('id="record-heading"')[1].split("<section")[0]


# --- Recording form ---------------------------------------------------------------


def test_form_shows_latest_decision_and_checkbox_when_not_ready(client):
    section = record_section(page(client, "/launches/1/go-no-go"))
    assert "Latest decision: <strong>No-go</strong> · 2026-10-30" in section
    assert 'name="acknowledge_blockers"' in section
    assert "I'm recording Go with 1 gate not done." in section
    assert 'max="2026-11-02"' in section


def test_no_checkbox_when_ready(client, conn):
    for g in get_gates(conn, 2):
        update_gate(conn, g["id"], GateUpdate(GateStatus.PASSED, "P", None, None, None, None))
    section = record_section(page(client, "/launches/2/go-no-go"))
    assert 'name="acknowledge_blockers"' not in section
    assert "No go/no-go decision yet." in section


def test_valid_no_go_redirects_to_log(client):
    response = client.post("/launches/1/decisions", data=NO_GO)
    assert response.status_code == 302
    assert response.headers["Location"] == "/launches/1/decisions"
    log = page(client, "/launches/1/decisions")
    entry = log.split('class="decision-list"')[1].split("</li>")[0]
    assert "No-go" in entry and "Eval still failing." in entry and "Revisit on 2026-11-09." in entry
    assert "Readiness at the time: Not ready: 1 blocker" in entry
    assert "Tool-use safety eval (Safety): Failed · Failed, Overdue" in entry


def test_go_with_blockers_recorded_and_marked(client):
    client.post("/launches/1/decisions", data=GO_WITH_BLOCKERS)
    log = page(client, "/launches/1/decisions")
    assert 'class="decision decision-go-blockers"' in log
    assert "Go with open blockers" in log
    assert "Fix the eval in v2.1.1." in log


@pytest.mark.parametrize("overrides, message", [
    ({"acknowledge_blockers": ""}, "Tick the box to record Go with open blockers."),
    ({"follow_up": ""}, "Say what happens to the open blockers."),
])
def test_go_with_blockers_missing_checkbox_or_follow_up_is_400(client, conn, overrides, message):
    response = client.post("/launches/1/decisions", data={**GO_WITH_BLOCKERS, **overrides})
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert message in html
    assert GO_WITH_BLOCKERS["rationale"] in html  # typed values kept
    assert len(list_decisions(conn, 1)) == 1      # only the seeded No-go


@pytest.mark.parametrize("overrides, message", [
    ({"follow_up": ""}, "Say what happens next."),
    ({"decided_on": "2026-11-03"}, "can&#39;t be dated in the future"),
    ({"kind": ""}, "Choose Go or No-go."),
])
def test_bad_no_go_is_400_and_saves_nothing(client, conn, overrides, message):
    response = client.post("/launches/1/decisions", data={**NO_GO, **overrides})
    assert response.status_code == 400
    assert message in response.get_data(as_text=True)
    assert len(list_decisions(conn, 1)) == 1


def test_go_while_ready_needs_no_follow_up(client, conn):
    for g in get_gates(conn, 2):
        update_gate(conn, g["id"], GateUpdate(GateStatus.PASSED, "P", None, None, None, None))
    response = client.post("/launches/2/decisions", data={
        "kind": "go", "decided_by": "Morgan T.", "rationale": "All gates passed.", "follow_up": ""})
    assert response.status_code == 302
    assert 'class="decision decision-go"' in page(client, "/launches/2/decisions")


# --- Logs -------------------------------------------------------------------------


def test_log_shows_changed_since_banner(client):
    client.post("/launches/1/disable/tool_use", data={
        "decided_by": "Morgan T.", "rationale": "Eval failing.", "follow_up": "Turn back on later."})
    log = page(client, "/launches/1/decisions")
    assert "Things have changed since the latest decision" in log
    assert "Recorded at Not ready: 1 blocker; now Ready." in log
    assert "1 scope change since." in log
    entries = log.split('class="decision-list"')[1]
    assert entries.index("Tool use turned off") < entries.index("No-go")


def test_log_has_no_banner_when_nothing_changed(client):
    assert "Things have changed" not in page(client, "/launches/1/decisions")


def test_empty_log(client):
    assert "No decisions recorded yet." in page(client, "/launches/2/decisions")


def test_all_launches_log_and_filters(client):
    client.post("/launches/2/decisions", data={**NO_GO, "rationale": "v2.2 not ready."})
    everything = page(client, "/decisions")
    assert everything.count('class="decision ') == 2
    assert "Model Atlas v2.1 — trusted testers" in everything
    assert "Model Atlas v2.2 — adding code execution" in everything

    only_v22 = page(client, "/decisions?launch=2")
    assert only_v22.count('class="decision ') == 1 and "v2.2 not ready." in only_v22

    scope = page(client, "/decisions?kind=scope_change")
    assert "No decisions match." in scope
    assert page(client, "/decisions?kind=nonsense").count('class="decision ') == 2


@pytest.mark.parametrize("url", ["/launches/999/decisions"])
def test_unknown_launch_is_404(client, url):
    assert client.get(url).status_code == 404
    assert client.post(url, data=NO_GO).status_code == 404


# --- Where decisions show up ---------------------------------------------------------


def test_dashboard_header_shows_latest_decision(client):
    html = page(client, "/launches/1")
    assert "<strong>No-go</strong> · 2026-10-30 · Morgan T. (VP, Product)" in html
    assert "No go/no-go decision yet" in page(client, "/launches/2")


def test_home_page_decision_column(client):
    html = page(client, "/")
    assert "<th>Decision</th>" in html
    assert 'href="/launches/1/decisions">No-go</a>' in html
    assert "No decision yet" in html


def test_header_links_to_decision_log(client):
    assert 'href="/decisions">Decision log</a>' in page(client, "/")


def test_readiness_never_shown_as_go_or_no_go(client):
    log = page(client, "/launches/1/decisions")
    readiness = log.split("Readiness now:")[1].split("</span>")[0]
    assert "Not ready" in readiness and "go" not in readiness.lower().replace("go-no-go", "")


def test_previous_schema_version_asks_for_reseed(tmp_path):
    path = tmp_path / "old.db"
    old = get_connection(path)
    init_db(old)
    old.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
    old.close()
    response = create_app({"TESTING": True, "DATABASE": str(path)}).test_client().get("/")
    assert response.status_code == 503
