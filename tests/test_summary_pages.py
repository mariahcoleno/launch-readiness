"""The summary page, with a fake Claude client (no network)."""

from datetime import date

import pytest

from launch_readiness.app import create_app
from launch_readiness.db import get_connection
from launch_readiness.seed import seed_database

from .fake_claude import FakeClient, api_errors, response

TODAY = date(2026, 11, 2)


@pytest.fixture
def fake():
    return FakeClient()


@pytest.fixture
def app(tmp_path, fake):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db"), "TODAY": TODAY})
    app.config["AI_CLIENT_FACTORY"] = lambda: fake
    c = get_connection(app.config["DATABASE"])
    seed_database(c, today=TODAY)
    c.close()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")


@pytest.fixture
def without_key(monkeypatch, app):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def must_not_be_called():
        raise AssertionError("Claude client created without an API key")

    app.config["AI_CLIENT_FACTORY"] = must_not_be_called


def dump_all(app):
    c = get_connection(app.config["DATABASE"])
    try:
        return {t: [tuple(r) for r in c.execute(f"SELECT * FROM {t} ORDER BY rowid")]
                for t in ("launches", "launch_features", "gates", "decisions")}
    finally:
        c.close()


# --- Not configured -----------------------------------------------------------------


def test_page_without_key_says_not_configured(client, without_key):
    html = client.get("/launches/1/summary").get_data(as_text=True)
    assert "AI status summary isn&#39;t configured. Set ANTHROPIC_API_KEY" in html
    assert "Generate draft" not in html
    assert "Not ready: 1 blocker" in html  # the rest of the page still works


def test_post_without_key_is_refused_without_creating_a_client(client, without_key):
    response_ = client.post("/launches/1/summary")
    assert response_.status_code == 503
    assert "isn&#39;t configured" in response_.get_data(as_text=True)


def test_blank_key_counts_as_not_configured(client, monkeypatch, without_key):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  ")
    assert client.post("/launches/1/summary").status_code == 503


# --- Configured ---------------------------------------------------------------------


def test_opening_the_page_never_calls_claude(client, fake, with_key):
    html = client.get("/launches/1/summary").get_data(as_text=True)
    assert "Generate draft" in html
    assert fake.messages.calls == []


def test_generate_makes_one_call_and_shows_draft(client, fake, with_key):
    response_ = client.post("/launches/1/summary")
    html = response_.get_data(as_text=True)
    assert response_.status_code == 200
    assert len(fake.messages.calls) == 1
    assert "<strong>DRAFT</strong>, written by Claude (claude-opus-5-5) at " in html
    assert "Review and edit before sending. It doesn't change any gate or decision." in html
    assert "Tool-use safety eval (Safety, Dana K.) failed and is overdue." in html
    assert "Regenerate draft" in html and "Copy as text" in html
    assert 'id="draft-text"' in html


def test_data_sent_is_the_launch_report(client, fake, with_key):
    client.post("/launches/1/summary")
    user = fake.messages.calls[0]["messages"][0]["content"]
    assert "Model Atlas v2.1" in user
    assert "Not ready: 1 blocker" in user
    assert "Model Atlas v2.2" not in user  # only this launch


def test_readiness_and_decision_come_from_the_app_not_the_ai(client, fake, with_key):
    fake.messages.result = response({
        "status": "Ready! Go decided.", "blockers_and_risks": [], "decisions": ["Go"], "next_steps": []})
    html = client.post("/launches/1/summary").get_data(as_text=True)
    facts = html.split('class="facts"')[1].split("</section>")[0]
    assert "Not ready: 1 blocker" in facts
    assert "<strong>No-go</strong> · 2026-10-30" in facts
    assert "Ready! Go decided." in html  # the draft is shown as the AI wrote it, inside the draft box


def test_generating_changes_nothing_in_the_database(client, app, with_key):
    before = dump_all(app)
    client.post("/launches/1/summary")
    client.post("/launches/2/summary")
    assert dump_all(app) == before


def test_refusal_shows_declined_and_stops(client, fake, with_key):
    fake.messages.result = response(stop_reason="refusal", text="")
    response_ = client.post("/launches/1/summary")
    assert response_.status_code == 502
    assert "Claude declined to draft this summary." in response_.get_data(as_text=True)
    assert len(fake.messages.calls) == 1


@pytest.mark.parametrize("error, message, code", api_errors())
def test_errors_show_message_and_status(client, fake, with_key, error, message, code):
    fake.messages.error = error
    response_ = client.post("/launches/1/summary")
    html = response_.get_data(as_text=True)
    assert response_.status_code == code
    assert message.replace("'", "&#39;") in html
    assert "Generate draft" in html  # can try again


def test_unknown_launch_is_404(client, fake, with_key):
    assert client.get("/launches/999/summary").status_code == 404
    assert client.post("/launches/999/summary").status_code == 404
    assert fake.messages.calls == []


def test_links_from_dashboard_and_go_no_go(client):
    assert 'href="/launches/1/summary">Draft status update' in client.get("/launches/1").get_data(as_text=True)
    assert 'href="/launches/1/summary">Draft status update' in client.get("/launches/1/go-no-go").get_data(as_text=True)
