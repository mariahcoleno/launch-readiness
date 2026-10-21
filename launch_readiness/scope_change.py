"""Turning a capability off or on for a launch: preview the impact, then do it."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .dashboard import GateView
from .decision_form import ScopeChangeInput
from .launch_status import current_gate_views
from .launches import gate_due_date, get_configuration, get_launch
from .models import LABELS, Capability, GateDefinition, GateStatus
from .readiness import Readiness, assess
from .rules_engine import GateRules, gate_diff


class CapabilityNotEnabled(ValueError):
    pass


class CapabilityAlreadyEnabled(ValueError):
    pass


@dataclass(frozen=True)
class DisablePreview:
    capability: Capability
    removed: tuple[GateView, ...]  # the launch's gates that would be removed
    before: Readiness
    after: Readiness

    @property
    def clears_blockers(self) -> bool:
        return len(self.after.blockers) < len(self.before.blockers)


def preview_disable(
    conn: sqlite3.Connection,
    launch_id: int,
    capability: Capability,
    today: date,
    rules: Optional[GateRules] = None,
) -> DisablePreview:
    """What turning a capability off would remove, and the verdict before and after."""
    config = get_configuration(conn, launch_id)
    if config is None or capability not in config.capabilities:
        raise CapabilityNotEnabled(capability.value)
    new_config = config.with_capability(capability, False)
    removed_keys = {g.id for g in gate_diff(config, new_config, rules).removed}

    views, required = current_gate_views(conn, launch_id, today, rules, config)
    _, required_after = current_gate_views(conn, launch_id, today, rules, new_config)
    kept = [v for v in views if v.gate_key not in removed_keys]
    return DisablePreview(
        capability=capability,
        removed=tuple(v for v in views if v.gate_key in removed_keys),
        before=assess(views, required),
        after=assess(kept, required_after),
    )


def disable_capability(
    conn: sqlite3.Connection,
    launch_id: int,
    capability: Capability,
    decision: ScopeChangeInput,
    today: date,
    rules: Optional[GateRules] = None,
) -> int:
    """Turn a capability off, remove only the gates it alone required, and record why.

    All in one transaction. Removed gates keep their last status and are linked to
    the scope-change decision. Returns the decision id.
    """
    config = get_configuration(conn, launch_id)
    if config is None or capability not in config.capabilities:
        raise CapabilityNotEnabled(capability.value)
    diff = gate_diff(config, config.with_capability(capability, False), rules)
    removed_keys = [g.id for g in diff.removed]

    with conn:  # commits on success, rolls back on any error
        cur = conn.execute(
            """
            INSERT INTO decisions
                (launch_id, kind, decided_by, decided_on, rationale, follow_up, action, capability)
            VALUES (?, 'scope_change', ?, ?, ?, ?, 'capability_off', ?)
            """,
            (launch_id, decision.decided_by, today.isoformat(), decision.rationale,
             decision.follow_up, capability.value),
        )
        decision_id = cur.lastrowid
        conn.execute(
            "DELETE FROM launch_features WHERE launch_id = ? AND kind = 'capability' AND name = ?",
            (launch_id, capability.value),
        )
        _mark_gates_removed(conn, launch_id, removed_keys, decision_id, today)
    return decision_id


def _mark_gates_removed(conn, launch_id, gate_keys, decision_id, today) -> None:
    conn.executemany(
        """
        UPDATE gates SET removed_at = ?, removed_by_decision_id = ?
         WHERE launch_id = ? AND gate_key = ? AND removed_at IS NULL
        """,
        [(today.isoformat(), decision_id, launch_id, key) for key in gate_keys],
    )


# --- Turning a capability on (the delta review) --------------------------------


@dataclass(frozen=True)
class NewGate:
    """A gate that turning a capability on would add, or restore if it was removed."""

    definition: GateDefinition
    reasons: tuple[str, ...]
    due_date: date
    previous: Optional[sqlite3.Row] = None  # the removed row, when restoring

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def restoring(self) -> bool:
        return self.previous is not None

    @property
    def previous_status(self) -> Optional[GateStatus]:
        return GateStatus(self.previous["status"]) if self.previous else None


@dataclass(frozen=True)
class EnablePreview:
    capability: Capability
    added: tuple[NewGate, ...]
    before: Readiness
    after: Readiness


def _removed_rows(conn, launch_id) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM gates WHERE launch_id = ? AND removed_at IS NOT NULL", (launch_id,)
    ).fetchall()
    return {r["gate_key"]: r for r in rows}


def preview_enable(
    conn: sqlite3.Connection,
    launch_id: int,
    capability: Capability,
    today: date,
    rules: Optional[GateRules] = None,
) -> EnablePreview:
    """Only the gates turning this capability on would add, and the verdict before and after."""
    config = get_configuration(conn, launch_id)
    if config is None:
        raise CapabilityNotEnabled(capability.value)
    if capability in config.capabilities:
        raise CapabilityAlreadyEnabled(capability.value)
    new_config = config.with_capability(capability, True)
    diff = gate_diff(config, new_config, rules)

    views, required = current_gate_views(conn, launch_id, today, rules, config)
    _, required_after = current_gate_views(conn, launch_id, today, rules, new_config)
    current_keys = {v.gate_key for v in views}
    removed = _removed_rows(conn, launch_id)
    due = gate_due_date(date.fromisoformat(get_launch(conn, launch_id)["target_date"]))

    added = tuple(
        NewGate(g.definition, g.reasons, due, removed.get(g.id))
        for g in diff.added
        if g.id not in current_keys  # already there (only if the rules file changed)
    )
    after_views = views + [_view_of(new, today) for new in added]
    return EnablePreview(
        capability=capability,
        added=added,
        before=assess(views, required),
        after=assess(after_views, required_after),
    )


def _view_of(new: NewGate, today: date) -> GateView:
    """How a new or restored gate will look once added: not started."""
    from .dashboard import gate_view

    row = {
        "id": 0, "gate_key": new.id, "name": new.definition.name, "team": new.definition.team,
        "owner": new.previous["owner"] if new.previous else None,
        "status": GateStatus.NOT_STARTED.value, "due_date": new.due_date.isoformat(),
        "notes": None, "waiver_rationale": None, "waived_by": None,
    }
    return gate_view(row, new.reasons, today)


def restore_note(today: date, capability: Capability, previous: sqlite3.Row) -> str:
    """The line added to a restored gate's notes."""
    status = GateStatus(previous["status"])
    note = (
        f"{today.isoformat()}: Restored when {capability.label.lower()} was turned back on. "
        f"Previous status: {status.label}."
    )
    if status is GateStatus.WAIVED and previous["waiver_rationale"]:
        note += f' Previous waiver by {previous["waived_by"]}: "{previous["waiver_rationale"]}"'
    return note


def enable_capability(
    conn: sqlite3.Connection,
    launch_id: int,
    capability: Capability,
    decision: ScopeChangeInput,
    today: date,
    rules: Optional[GateRules] = None,
) -> int:
    """Turn a capability on, add only the gates it newly requires, and record why.

    New gates start not started and unassigned, due by the usual rule. Gates removed
    by an earlier scope change are restored instead of duplicated: reset to not
    started, waiver cleared, owner and notes kept, plus a note recording the restore.
    All in one transaction. Returns the decision id.
    """
    preview = preview_enable(conn, launch_id, capability, today, rules)

    with conn:  # commits on success, rolls back on any error
        cur = conn.execute(
            """
            INSERT INTO decisions
                (launch_id, kind, decided_by, decided_on, rationale, follow_up, action, capability)
            VALUES (?, 'scope_change', ?, ?, ?, ?, 'capability_on', ?)
            """,
            (launch_id, decision.decided_by, today.isoformat(), decision.rationale,
             decision.follow_up, capability.value),
        )
        decision_id = cur.lastrowid
        conn.execute(
            "INSERT INTO launch_features (launch_id, kind, name) VALUES (?, 'capability', ?)",
            (launch_id, capability.value),
        )
        _add_gates(conn, launch_id, preview.added, decision_id, capability, today)
    return decision_id


def _add_gates(conn, launch_id, gates, decision_id, capability, today) -> None:
    for new in gates:
        if new.restoring:
            old = new.previous
            line = restore_note(today, capability, old)
            notes = f"{old['notes']}\n{line}" if old["notes"] else line
            conn.execute(
                """
                UPDATE gates
                   SET status = 'not_started', waiver_rationale = NULL, waived_by = NULL,
                       name = ?, team = ?, due_date = ?, notes = ?,
                       removed_at = NULL, removed_by_decision_id = NULL,
                       added_by_decision_id = ?
                 WHERE id = ?
                """,
                (new.definition.name, new.definition.team, new.due_date.isoformat(), notes,
                 decision_id, old["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO gates (launch_id, gate_key, name, team, due_date, added_by_decision_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (launch_id, new.id, new.definition.name, new.definition.team,
                 new.due_date.isoformat(), decision_id),
            )
