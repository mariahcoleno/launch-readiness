"""Delta review pages, and their effect on the dashboard and go/no-go page."""

from datetime import date

import pytest

from launch_readiness.app import create_app
from launch_readiness.db import SCHEMA_VERSION, get_connection, init_db
from launch_readiness.launches import get_gates, get_scope_changes
from launch_readiness.models import Capability
from launch_readiness.seed import seed_database

TODAY = date(2026, 11, 2)
ON = {"decided_by": "Morgan T. (VP, Product)", "rationale": "Sandbox ready for v2.2.", "follow_up": ""}
OFF = {"decided_by": "Morgan T. (VP, Product)", "rationale": "Tool-use eval failing.",
       "follow_up": "Re-enable tool use once the eval passes."}


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


def test_go_no_go_lists_every_capability_that_is_off(client):
    html = page(client, "/launches/2/go-no-go")
    add = html.split('id="add-heading"')[1].split("<section")[0]
    for cap in Capability:
        if cap is Capability.TOOL_USE:
            assert f'data-add-capability="{cap.value}"' not in add
        else:
            assert f'data-add-capability="{cap.value}"' in add
    row = add.split('data-add-capability="code_execution"')[1].split("</tr>")[0]
    assert "Sandbox security review" in row
    assert "Not ready: 7 blockers" in row


def test_review_page_shows_only_the_new_gate(client, conn):
    html = page(client, "/launches/2/enable/code_execution")
    new = html.split('id="new-heading"')[1].split("</section>")[0]
    assert "New gates (1)" in html
    assert "Sandbox security review" in new
    assert "Code execution is on" in new
    assert "2026-11-25" in new
    for g in get_gates(conn, 2):  # none of the existing gates are listed
        assert g["name"] not in new
    assert "Not ready: 6 blockers" in html and "Not ready: 7 blockers" in html
    assert "Turn on code execution and add 1 gate" in html


def test_valid_confirmation_adds_gate_and_shows_it_on_dashboard(client):
    response = client.post("/launches/2/enable/code_execution", data=ON)
    assert response.status_code == 302
    assert response.headers["Location"] == "/launches/2"
    html = page(client, "/launches/2")
    assert "Sandbox security review" in html
    assert "Added when code execution was turned on (2026-11-02)" in html
    assert 'href="/launches/2/go-no-go">Not ready: 7 blockers<' in html
    caps = html.split("<dt>Capabilities</dt>")[1].split("</dd>")[0]
    assert "Code execution" in caps


def test_missing_rationale_is_400_and_changes_nothing(client, conn):
    response = client.post("/launches/2/enable/code_execution", data={**ON, "rationale": ""})
    assert response.status_code == 400
    assert "Explain why this capability is being added." in response.get_data(as_text=True)
    assert get_scope_changes(conn, 2) == []
    assert "sandbox_security_review" not in {g["gate_key"] for g in get_gates(conn, 2)}


@pytest.mark.parametrize("url", [
    "/launches/1/enable/tool_use",        # already on
    "/launches/1/enable/teleportation",   # not a capability
    "/launches/999/enable/code_execution",
])
def test_bad_targets_are_404(client, url):
    assert client.get(url).status_code == 404
    assert client.post(url, data=ON).status_code == 404


def test_round_trip_through_the_pages(client):
    client.post("/launches/1/disable/tool_use", data=OFF)
    review = page(client, "/launches/1/enable/tool_use")
    assert "Previously removed on 2026-11-02" in review
    assert "Failed" in review and "still owned by Dana K." in review

    client.post("/launches/1/enable/tool_use", data={**ON, "rationale": "Eval fixed."})
    dash = page(client, "/launches/1")
    assert "Removed by scope change (0)" in dash
    assert "Restored when tool use was turned back on. Previous status: Failed." in dash
    assert "Added when tool use was turned on (2026-11-02)" in dash

    scope = page(client, "/launches/1/go-no-go").split('id="scope-heading"')[1]
    assert "Tool use turned on" in scope and "Tool use turned off" in scope
    assert scope.index("turned on") < scope.index("turned off")  # newest first


def test_dashboard_has_add_capability_link(client):
    html = page(client, "/launches/2")
    assert 'href="/launches/2/go-no-go#add-heading">Add a capability<' in html


def test_previous_schema_version_asks_for_reseed(tmp_path):
    path = tmp_path / "old.db"
    old = get_connection(path)
    init_db(old)
    old.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
    old.close()
    response = create_app({"TESTING": True, "DATABASE": str(path)}).test_client().get("/")
    assert response.status_code == 503
