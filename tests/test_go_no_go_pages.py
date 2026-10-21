"""Go/no-go page, disable-capability pages, and dashboard additions. "Today" is fixed."""

from datetime import date

import pytest

from launch_readiness.app import create_app
from launch_readiness.db import get_connection
from launch_readiness.gate_form import GateUpdate
from launch_readiness.launches import get_gates, get_scope_changes, update_gate
from launch_readiness.models import GateStatus
from launch_readiness.seed import seed_database

TODAY = date(2026, 11, 2)

FORM = {
    "decided_by": "Morgan T. (VP, Product)",
    "rationale": "Tool-use eval won't pass before the trusted-tester date.",
    "follow_up": "Re-enable tool use for v2.1.1 once the tool-use eval passes.",
}


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


def section(html, heading_id):
    return html.split(f'id="{heading_id}"')[1].split("<section")[0]


# --- Go/no-go page --------------------------------------------------------------


def test_v21_is_not_ready_with_one_blocker(client):
    html = page(client, "/launches/1/go-no-go")
    assert "Not ready: 1 blocker" in html
    blockers = section(html, "blockers-heading")
    assert "Tool-use safety eval" in blockers
    assert 'class="tag tag-failed">Failed<' in blockers
    assert 'class="tag tag-overdue">Overdue<' in blockers
    assert "Dana K." in blockers
    assert blockers.count('class="blocker-row"') == 1


def test_page_never_calls_the_verdict_go_or_no_go(client):
    html = page(client, "/launches/1/go-no-go")
    panel = html.split('class="verdict-panel')[1].split("</div>")[0]
    assert "No-go" not in panel and "Not ready" in panel


def test_all_passed_launch_is_ready(client, conn):
    for g in get_gates(conn, 2):
        update_gate(conn, g["id"], GateUpdate(GateStatus.PASSED, "Priya N.", None, None, None, None))
    html = page(client, "/launches/2/go-no-go")
    assert 'class="verdict-headline">Ready<' in html
    assert "No blockers." in html


def test_preview_lists_gates_removed_and_verdict_after(client):
    html = page(client, "/launches/1/go-no-go")
    row = html.split('data-capability="tool_use"')[1].split("</tr>")[0]
    assert "Tool-use safety eval" in row and "Failed" in row
    assert 'class="verdict verdict-ready">Ready<' in row
    assert "Clears 1 blocker" in row
    assert 'class="clears-blockers"' in html


def test_disable_page_shows_impact(client):
    html = page(client, "/launches/1/disable/tool_use")
    assert "Launch without tool use" in html
    assert "Tool-use safety eval (Safety)" in html
    assert "Not ready: 1 blocker" in html and ">Ready<" in html
    assert "Turn off tool use and remove 1 gate" in html


def test_valid_confirmation_disables_and_shows_ready(client, conn):
    response = client.post("/launches/1/disable/tool_use", data=FORM)
    assert response.status_code == 302
    assert response.headers["Location"] == "/launches/1/go-no-go"
    html = page(client, "/launches/1/go-no-go")
    assert 'class="verdict-headline">Ready<' in html
    scope = section(html, "scope-heading")
    assert "Tool use turned off" in scope and "2026-11-02" in scope
    assert FORM["decided_by"] in scope and FORM["follow_up"] in scope
    assert "No capabilities are turned on" in html


def test_missing_rationale_is_400_and_changes_nothing(client, conn):
    response = client.post("/launches/1/disable/tool_use", data={**FORM, "rationale": " "})
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Explain why the launch is going ahead" in html
    assert FORM["follow_up"] in html  # typed values kept
    assert get_scope_changes(conn, 1) == []
    assert "tool_use_safety_eval" in {g["gate_key"] for g in get_gates(conn, 1)}


@pytest.mark.parametrize("url", [
    "/launches/1/disable/code_execution",  # not enabled
    "/launches/1/disable/teleportation",   # not a capability
    "/launches/999/disable/tool_use",      # no such launch
    "/launches/999/go-no-go",
])
def test_bad_targets_are_404(client, url):
    assert client.get(url).status_code == 404
    if "disable" in url:
        assert client.post(url, data=FORM).status_code == 404


# --- Dashboard additions ----------------------------------------------------------


def test_dashboard_badge_links_to_go_no_go(client):
    html = page(client, "/launches/1")
    assert 'class="verdict verdict-not-ready"' in html
    assert 'href="/launches/1/go-no-go">Not ready: 1 blocker<' in html


def test_dashboard_shows_at_risk(client):
    html = page(client, "/launches/2")
    assert "1 at risk" in html
    attention = section(html, "attention-heading")
    assert 'class="tag tag-at-risk">At risk<' in attention
    assert "Red-team sign-off" in attention
    assert attention.index("Red-team sign-off") < attention.index("Comms plan")


def test_removed_section_empty_by_default(client):
    html = page(client, "/launches/1")
    assert "Removed by scope change (0)" in html
    assert "No gates have been removed." in html


def test_removed_section_after_scope_change(client):
    client.post("/launches/1/disable/tool_use", data=FORM)
    html = page(client, "/launches/1")
    removed = html.split('id="removed-heading"')[1]
    assert "Removed by scope change (1)" in html
    assert "Tool-use safety eval" in removed
    assert 'class="status status-failed">Failed<' in removed
    assert "2026-11-02" in removed
    assert FORM["follow_up"] in removed
    assert "Tool use turned off by Morgan T." in removed
    # Removed gates don't count: the rest of the page shows 6 gates, all done.
    assert "6 of 6 gates done" in html
    assert 'href="/launches/1/go-no-go">Ready<' in html
    teams = html.split("Gates by team")[1].split('id="removed-heading"')[0]
    assert "Tool-use safety eval" not in teams


def test_removed_gate_cannot_be_edited(client, conn):
    gate_id = next(g["id"] for g in get_gates(conn, 1) if g["gate_key"] == "tool_use_safety_eval")
    client.post("/launches/1/disable/tool_use", data=FORM)
    assert client.get(f"/launches/1/gates/{gate_id}/edit").status_code == 404
