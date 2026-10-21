"""Gather a launch's facts into plain data for the status summary.

Only reads. Uses the same functions as the dashboard, go/no-go page and decision
log, so the summary sees exactly what people see in the app.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional

from .dashboard import countdown, group_by_team, needs_attention
from .decisions import latest_go_no_go, list_decisions
from .launch_status import current_gate_views
from .launches import get_configuration, get_launch, get_removed_gates
from .models import LABELS, Capability, GateStatus, Surface
from .readiness import assess, snapshot

MAX_SCOPE_CHANGES = 5


def _decision(d) -> dict:
    return {
        "decision": d.title,
        "decided_on": d.decided_on.isoformat(),
        "decided_by": d.decided_by,
        "rationale": d.rationale,
        "follow_up": d.follow_up,
    }


def build_status_report(conn: sqlite3.Connection, launch_id: int, today: date) -> Optional[dict]:
    """Everything the summary may use about one launch, or None if it doesn't exist."""
    launch = get_launch(conn, launch_id)
    if launch is None:
        return None
    config = get_configuration(conn, launch_id)
    gates, required = current_gate_views(conn, launch_id, today, config=config)
    readiness = assess(gates, required)
    latest = latest_go_no_go(conn, launch_id)
    scope = [d for d in list_decisions(conn, launch_id=launch_id, kind="scope_change")]

    return {
        "today": today.isoformat(),
        "launch": {
            "name": launch["name"],
            "model_version": launch["model_version"],
            "stage": LABELS[launch["stage"]],
            "surfaces": [s.label for s in Surface if s in config.surfaces],
            "capabilities": [c.label for c in Capability if c in config.capabilities],
            "target_date": launch["target_date"],
            "countdown": countdown(date.fromisoformat(launch["target_date"]), today),
        },
        # Readiness comes from the app's rules, not from the AI.
        "readiness": snapshot(readiness),
        "needs_attention": [
            {
                "gate": g.name,
                "team": g.team,
                "owner": g.owner or "Unassigned",
                "status": g.status.label,
                "due_date": g.due_date.isoformat() if g.due_date else None,
                "flags": g.attention_tags,
            }
            for g in needs_attention(gates)
        ],
        "teams": [
            {"team": t.team, "done": t.done_count, "total": len(t.gates)}
            for t in group_by_team(gates)
        ],
        "waived_gates": [
            {"gate": g.name, "waived_by": g.waived_by, "rationale": g.waiver_rationale}
            for g in gates
            if g.status is GateStatus.WAIVED
        ],
        "removed_gates": [
            {
                "gate": r["name"],
                "last_status": LABELS[r["status"]],
                "removed_on": r["removed_at"][:10],
                "follow_up": r["follow_up"],
            }
            for r in get_removed_gates(conn, launch_id)
        ],
        "latest_go_no_go_decision": _decision(latest) if latest else None,
        "recent_scope_changes": [_decision(d) for d in scope[:MAX_SCOPE_CHANGES]],
        # Free text typed by people. Passed as data only.
        "gate_notes": [{"gate": g.name, "notes": g.notes} for g in gates if g.notes],
    }
