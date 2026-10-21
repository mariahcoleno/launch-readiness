"""Launching with a capability turned off: preview the impact, then do it."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .dashboard import GateView
from .decision_form import ScopeChangeInput
from .launch_status import current_gate_views
from .launches import get_configuration
from .models import Capability
from .readiness import Readiness, assess
from .rules_engine import GateRules, gate_diff


class CapabilityNotEnabled(ValueError):
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
                (launch_id, kind, decided_by, decided_on, rationale, follow_up, capability)
            VALUES (?, 'scope_change', ?, ?, ?, ?, ?)
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
