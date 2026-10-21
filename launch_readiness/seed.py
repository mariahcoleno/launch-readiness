"""Sample launches for demos. All names, models and people are fictional.

Dates are given as days from today, so the demo looks the same whenever it's run.
Gates not listed under a launch keep their defaults (not started, unassigned,
due GATE_DUE_DAYS_BEFORE_LAUNCH days before the target date).
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from .db import reset_db
from .gate_form import parse_gate_form
from .launch_form import parse_launch_form
from .launches import create_launch, get_gates, update_gate

SAMPLE_LAUNCHES = [
    {
        # Mostly ready, one blocker: the tool-use safety eval failed and is overdue.
        "name": "Model Atlas v2.1 — trusted testers",
        "model_version": "Model Atlas v2.1",
        "target_in_days": 12,
        "stage": "trusted_testers",
        "surfaces": ["api", "consumer_app"],
        "capabilities": ["tool_use"],
        "gates": {
            "safety_evals": {
                "status": "passed", "owner": "Priya N.",
                "notes": "All categories within thresholds on eval suite v14.",
            },
            "red_team_signoff": {
                "status": "passed", "owner": "Sam O.",
                "notes": "Two-week red-team exercise complete; no open high-severity findings.",
            },
            "rollback_plan": {
                "status": "passed", "owner": "Ravi S.",
                "notes": "Rollback to v2.0 rehearsed in staging.",
            },
            "monitoring_oncall": {
                "status": "passed", "owner": "Jo W.",
                "notes": "Dashboards live; on-call rotation staffed for launch week.",
            },
            "comms": {
                "status": "waived", "owner": "Leo M.",
                "waiver_rationale": "Trusted-tester release only; no public announcement. "
                                    "Testers are briefed directly by the program team.",
                "waived_by": "Morgan T. (VP, Product)",
            },
            "tool_use_safety_eval": {
                "status": "failed", "owner": "Dana K.", "due_in_days": -2,
                "notes": "Unsafe tool-call rate 2.4% vs 1.0% threshold. Fix in training; re-run planned.",
            },
            "consumer_abuse_readiness": {
                "status": "passed", "owner": "Alex P.",
                "notes": "Reporting flow and review queue tested end to end.",
            },
        },
    },
    {
        # Same configuration as v2.1, code execution still off. Feature 5 turns it on
        # to show the delta review.
        "name": "Model Atlas v2.2 — adding code execution",
        "model_version": "Model Atlas v2.2",
        "target_in_days": 30,
        "stage": "trusted_testers",
        "surfaces": ["api", "consumer_app"],
        "capabilities": ["tool_use"],
        "gates": {
            "safety_evals": {"status": "in_progress", "owner": "Priya N."},
            "red_team_signoff": {  # at risk: not started, due in 2 days
                "status": "not_started", "owner": "Sam O.", "due_in_days": 2,
                "notes": "Kickoff waiting on the red-team test environment.",
            },
            "rollback_plan": {
                "status": "passed", "owner": "Ravi S.",
                "notes": "Reuses the v2.1 rollback plan.",
            },
            "monitoring_oncall": {"status": "in_progress", "owner": "Jo W."},
            "comms": {"status": "not_started"},  # left unassigned on purpose
            "tool_use_safety_eval": {"status": "in_progress", "owner": "Dana K."},
            "consumer_abuse_readiness": {"status": "in_progress", "owner": "Alex P."},
        },
    },
]


def seed_database(conn: sqlite3.Connection, today: date | None = None) -> list[int]:
    """Delete everything and load the sample launches. Returns the new launch ids.

    Uses the same form checks and save functions as the web app, so sample data
    follows the same rules as real data.
    """
    today = today or date.today()
    reset_db(conn)
    return [_load_launch(conn, sample, today) for sample in SAMPLE_LAUNCHES]


def _load_launch(conn: sqlite3.Connection, sample: dict, today: date) -> int:
    target = today + timedelta(days=sample["target_in_days"])
    launch_input, errors = parse_launch_form(
        {
            "name": sample["name"],
            "model_version": sample["model_version"],
            "target_date": target.isoformat(),
            "stage": sample["stage"],
            "surfaces": sample["surfaces"],
            "capabilities": sample["capabilities"],
        }
    )
    if errors:
        raise ValueError(f"Sample launch '{sample['name']}' is invalid: {errors}")
    launch_id = create_launch(conn, launch_input)

    gates = {g["gate_key"]: g for g in get_gates(conn, launch_id)}
    unknown = set(sample["gates"]) - set(gates)
    if unknown:
        raise ValueError(f"Sample launch '{sample['name']}' lists gates it doesn't need: {unknown}")

    for key, fields in sample["gates"].items():
        gate = gates[key]
        due = gate["due_date"]
        if "due_in_days" in fields:
            due = (today + timedelta(days=fields["due_in_days"])).isoformat()
        update, errors = parse_gate_form({**fields, "due_date": due})
        if errors:
            raise ValueError(f"Sample gate '{key}' is invalid: {errors}")
        update_gate(conn, gate["id"], update)
    return launch_id
