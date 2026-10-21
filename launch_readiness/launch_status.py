"""Load a launch's gates from the database and assess them."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional

from .dashboard import GateView, gate_view
from .launches import get_configuration, get_gates
from .models import Configuration, RequiredGate
from .readiness import Readiness, assess
from .rules_engine import GateRules, required_gates

NOT_IN_RULES = ("No longer in the rules file",)


def current_gate_views(
    conn: sqlite3.Connection,
    launch_id: int,
    today: date,
    rules: Optional[GateRules] = None,
    config: Optional[Configuration] = None,
) -> tuple[list[GateView], list[RequiredGate]]:
    """The launch's current gates as GateViews, plus what the rules require now."""
    config = config or get_configuration(conn, launch_id)
    required = required_gates(config, rules)
    reasons = {r.id: r.reasons for r in required}
    views = [
        gate_view(row, reasons.get(row["gate_key"], NOT_IN_RULES), today)
        for row in get_gates(conn, launch_id)
    ]
    return views, required


def assess_launch(
    conn: sqlite3.Connection, launch_id: int, today: date, rules: Optional[GateRules] = None
) -> Readiness:
    views, required = current_gate_views(conn, launch_id, today, rules)
    return assess(views, required)
