"""The web pages, through Flask's test client."""

import pytest

from launch_readiness.app import create_app
from launch_readiness.db import get_connection
from launch_readiness.models import Capability, Stage, Surface


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})


@pytest.fixture
def client(app):
    return app.test_client()


def count_launches(app):
    conn = get_connection(app.config["DATABASE"])
    try:
        return conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0]
    finally:
        conn.close()


ATLAS_V21 = {
    "name": "Model Atlas v2.1 — trusted testers",
    "model_version": "Model Atlas v2.1",
    "target_date": "2026-12-15",
    "stage": "trusted_testers",
    "surfaces": ["api", "consumer_app"],
    "capabilities": ["tool_use"],
}


def test_form_shows_every_choice(client):
    html = client.get("/launches/new").get_data(as_text=True)
    for member in [*Stage, *Surface, *Capability]:
        assert f'value="{member.value}"' in html
        assert member.label in html


def test_valid_submission_creates_launch_and_shows_gates(client, app):
    response = client.post("/launches", data=ATLAS_V21)
    assert response.status_code == 302
    assert response.headers["Location"] == "/launches/1"

    html = client.get("/launches/1").get_data(as_text=True)
    assert "Model Atlas v2.1 — trusted testers" in html
    assert "0 of 7 gates done" in html
    assert "Tool-use safety eval" in html
    assert "Tool use is on" in html
    assert "Consumer abuse monitoring &amp; reporting readiness" in html
    assert "Consumer app surface is included" in html
    assert "2026-12-08" in html  # due 7 days before target
    assert "Sandbox security review" not in html
    assert count_launches(app) == 1


def test_invalid_submission_shows_errors_and_keeps_values(client, app):
    bad = {**ATLAS_V21, "surfaces": [], "target_date": "not a date"}
    response = client.post("/launches", data=bad)
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Choose at least one product surface." in html
    assert "Enter the date as YYYY-MM-DD." in html
    assert "fix the 2 problems" in html
    assert 'value="Model Atlas v2.1 — trusted testers"' in html
    assert 'value="tool_use" checked' in html
    assert '<option value="trusted_testers" selected>' in html
    assert count_launches(app) == 0


def test_unknown_launch_is_404(client):
    assert client.get("/launches/999").status_code == 404


def test_home_page_empty_state(client):
    html = client.get("/").get_data(as_text=True)
    assert "No launches yet" in html


def test_home_page_lists_launches(client):
    client.post("/launches", data=ATLAS_V21)
    html = client.get("/").get_data(as_text=True)
    assert "Model Atlas v2.1 — trusted testers" in html
    assert "Trusted testers" in html
    assert 'href="/launches/1"' in html
    assert "No launches yet" not in html


def test_launch_page_shows_no_capabilities(client):
    client.post("/launches", data={**ATLAS_V21, "capabilities": []})
    html = client.get("/launches/1").get_data(as_text=True)
    caps = html.split("<dt>Capabilities</dt>")[1].split("</dd>")[0]
    assert "None" in caps
    assert "Add a capability" in caps
    assert "0 of 6 gates done" in html
