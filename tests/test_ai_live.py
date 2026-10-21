"""One real call to Claude. Skipped unless you opt in, so normal test runs cost nothing.

Run with:  RUN_LIVE_AI_TESTS=1 ANTHROPIC_API_KEY=... .venv/bin/pytest tests/test_ai_live.py
"""

import os
from datetime import date

import pytest

from launch_readiness.ai_summary import draft_summary, is_configured, make_client
from launch_readiness.db import get_connection, get_readonly_connection, init_db
from launch_readiness.seed import seed_database
from launch_readiness.status_report import build_status_report

pytestmark = pytest.mark.skipif(
    not (os.environ.get("RUN_LIVE_AI_TESTS") == "1" and is_configured()),
    reason="live AI test: set RUN_LIVE_AI_TESTS=1 and ANTHROPIC_API_KEY to run",
)

TODAY = date(2026, 11, 2)


def test_live_draft_for_seeded_v21(tmp_path):
    path = tmp_path / "live.db"
    c = get_connection(path)
    init_db(c)
    seed_database(c, today=TODAY)
    c.close()
    ro = get_readonly_connection(path)
    report = build_status_report(ro, 1, TODAY)
    ro.close()

    draft = draft_summary(report, make_client())
    assert draft.status
    assert any("Tool-use" in item or "tool-use" in item for item in draft.blockers_and_risks)
