"""Saving and loading launches. No web code here."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Optional

from . import settings
from .gate_form import GateUpdate
from .models import Capability, Configuration, LaunchInput, Stage, Surface
from .rules_engine import GateRules, required_gates


def gate_due_date(target_date: date, days_before: Optional[int] = None) -> date:
    """When new gates are due: a set number of days before the target date."""
    if days_before is None:
        days_before = settings.GATE_DUE_DAYS_BEFORE_LAUNCH
    return target_date - timedelta(days=days_before)


def create_launch(
    conn: sqlite3.Connection, data: LaunchInput, rules: Optional[GateRules] = None
) -> int:
    """Save a launch, its surfaces and capabilities, and its required gates.

    Everything is saved in one transaction: if any part fails, nothing is saved.
    Gate names and teams are copied from the rules, so later edits to the rules
    file don't change existing launches.
    """
    gates = required_gates(data.configuration(), rules)
    due = gate_due_date(data.target_date).isoformat()

    with conn:  # commits on success, rolls back on any error
        cur = conn.execute(
            "INSERT INTO launches (name, model_version, target_date, stage) VALUES (?, ?, ?, ?)",
            (data.name, data.model_version, data.target_date.isoformat(), data.stage.value),
        )
        launch_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO launch_features (launch_id, kind, name) VALUES (?, ?, ?)",
            [(launch_id, "surface", s.value) for s in sorted(data.surfaces, key=_order)]
            + [(launch_id, "capability", c.value) for c in sorted(data.capabilities, key=_order)],
        )
        for gate in gates:
            conn.execute(
                "INSERT INTO gates (launch_id, gate_key, name, team, due_date) "
                "VALUES (?, ?, ?, ?, ?)",
                (launch_id, gate.id, gate.definition.name, gate.definition.team, due),
            )
    return launch_id


def _order(member) -> int:
    return list(type(member)).index(member)


def get_launch(conn: sqlite3.Connection, launch_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM launches WHERE id = ?", (launch_id,)).fetchone()


def get_configuration(conn: sqlite3.Connection, launch_id: int) -> Optional[Configuration]:
    """Rebuild a launch's configuration from the database."""
    launch = get_launch(conn, launch_id)
    if launch is None:
        return None
    rows = conn.execute(
        "SELECT kind, name FROM launch_features WHERE launch_id = ?", (launch_id,)
    ).fetchall()
    return Configuration(
        model_version=launch["model_version"],
        stage=Stage(launch["stage"]),
        surfaces=frozenset(Surface(r["name"]) for r in rows if r["kind"] == "surface"),
        capabilities=frozenset(Capability(r["name"]) for r in rows if r["kind"] == "capability"),
    )


def get_gates(conn: sqlite3.Connection, launch_id: int) -> list[sqlite3.Row]:
    """A launch's current gates (not removed), in the order they were created."""
    return conn.execute(
        "SELECT * FROM gates WHERE launch_id = ? AND removed_at IS NULL ORDER BY id",
        (launch_id,),
    ).fetchall()


def get_gate(conn: sqlite3.Connection, launch_id: int, gate_id: int) -> Optional[sqlite3.Row]:
    """A current gate, only if it belongs to this launch."""
    return conn.execute(
        "SELECT * FROM gates WHERE id = ? AND launch_id = ? AND removed_at IS NULL",
        (gate_id, launch_id),
    ).fetchone()


def update_gate(conn: sqlite3.Connection, gate_id: int, update: GateUpdate) -> None:
    with conn:
        conn.execute(
            """
            UPDATE gates
               SET status = ?, owner = ?, due_date = ?, notes = ?,
                   waiver_rationale = ?, waived_by = ?
             WHERE id = ? AND removed_at IS NULL
            """,
            (
                update.status.value,
                update.owner,
                update.due_date.isoformat() if update.due_date else None,
                update.notes,
                update.waiver_rationale,
                update.waived_by,
                gate_id,
            ),
        )


def get_removed_gates(conn: sqlite3.Connection, launch_id: int) -> list[sqlite3.Row]:
    """Gates removed by a scope change, with that decision's details. Newest first."""
    return conn.execute(
        """
        SELECT g.*, d.follow_up, d.decided_by, d.capability, d.decided_on
          FROM gates g
          LEFT JOIN decisions d ON d.id = g.removed_by_decision_id
         WHERE g.launch_id = ? AND g.removed_at IS NOT NULL
         ORDER BY g.removed_at DESC, g.id
        """,
        (launch_id,),
    ).fetchall()


def get_gate_additions(conn: sqlite3.Connection, launch_id: int) -> dict[int, sqlite3.Row]:
    """For current gates added by a scope change: gate id -> that decision."""
    rows = conn.execute(
        """
        SELECT g.id AS gate_id, d.capability, d.decided_on, d.decided_by
          FROM gates g JOIN decisions d ON d.id = g.added_by_decision_id
         WHERE g.launch_id = ? AND g.removed_at IS NULL
        """,
        (launch_id,),
    ).fetchall()
    return {r["gate_id"]: r for r in rows}


def get_scope_changes(conn: sqlite3.Connection, launch_id: int) -> list[sqlite3.Row]:
    """Scope-change decisions for a launch, newest first."""
    return conn.execute(
        """
        SELECT * FROM decisions
         WHERE launch_id = ? AND kind = 'scope_change'
         ORDER BY decided_on DESC, id DESC
        """,
        (launch_id,),
    ).fetchall()


def list_launches(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All launches, newest first, with how many current gates each has."""
    return conn.execute(
        """
        SELECT l.*,
               (SELECT COUNT(*) FROM gates g
                 WHERE g.launch_id = l.id AND g.removed_at IS NULL) AS gate_count
          FROM launches l
         ORDER BY l.created_at DESC, l.id DESC
        """
    ).fetchall()
