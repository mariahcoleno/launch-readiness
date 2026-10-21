"""Recording and reading decisions: Go, No-go, and scope changes.

Decisions are permanent: the database refuses to change or delete them.
Each one saves a snapshot of what the gates said at that moment.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .decision_form import GoNoGoInput
from .launch_status import assess_launch
from .models import LABELS, DecisionKind
from .readiness import Readiness, snapshot


class DecisionRefused(ValueError):
    """The decision breaks a rule, e.g. Go while Not ready without acknowledgement."""


def snapshot_json(readiness: Readiness) -> str:
    return json.dumps(snapshot(readiness))


@dataclass(frozen=True)
class DecisionView:
    id: int
    launch_id: int
    launch_name: Optional[str]
    kind: DecisionKind
    action: Optional[str]
    capability: Optional[str]
    decided_by: str
    decided_on: date
    rationale: str
    follow_up: Optional[str]
    acknowledged_blockers: bool
    snapshot: Optional[dict]

    @property
    def is_go_no_go(self) -> bool:
        return self.kind in (DecisionKind.GO, DecisionKind.NO_GO)

    @property
    def title(self) -> str:
        if self.kind is DecisionKind.GO:
            return "Go with open blockers" if self.acknowledged_blockers else "Go"
        if self.kind is DecisionKind.NO_GO:
            return "No-go"
        direction = "on" if self.action == "capability_on" else "off"
        return f"{LABELS.get(self.capability, self.capability)} turned {direction}"

    @property
    def css_class(self) -> str:
        if self.kind is DecisionKind.GO:
            return "decision-go-blockers" if self.acknowledged_blockers else "decision-go"
        if self.kind is DecisionKind.NO_GO:
            return "decision-no-go"
        return "decision-scope"

    @property
    def snapshot_headline(self) -> Optional[str]:
        return self.snapshot["headline"] if self.snapshot else None


def _view(row: sqlite3.Row) -> DecisionView:
    keys = row.keys()
    return DecisionView(
        id=row["id"],
        launch_id=row["launch_id"],
        launch_name=row["launch_name"] if "launch_name" in keys else None,
        kind=DecisionKind(row["kind"]),
        action=row["action"],
        capability=row["capability"],
        decided_by=row["decided_by"],
        decided_on=date.fromisoformat(row["decided_on"]),
        rationale=row["rationale"],
        follow_up=row["follow_up"],
        acknowledged_blockers=bool(row["acknowledged_blockers"]),
        snapshot=json.loads(row["readiness_snapshot"]) if row["readiness_snapshot"] else None,
    )


def record_go_no_go(
    conn: sqlite3.Connection, launch_id: int, decision: GoNoGoInput, today: date
) -> int:
    """Save a Go or No-go decision with a snapshot of readiness right now."""
    readiness = assess_launch(conn, launch_id, today)
    go_with_blockers = decision.kind is DecisionKind.GO and not readiness.ready
    if go_with_blockers and not (decision.acknowledged_blockers and decision.follow_up):
        raise DecisionRefused("Go while Not ready needs acknowledgement and a follow-up.")
    with conn:
        cur = conn.execute(
            """
            INSERT INTO decisions
                (launch_id, kind, decided_by, decided_on, rationale, follow_up,
                 readiness_snapshot, acknowledged_blockers)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (launch_id, decision.kind.value, decision.decided_by, decision.decided_on.isoformat(),
             decision.rationale, decision.follow_up, snapshot_json(readiness),
             int(go_with_blockers)),
        )
    return cur.lastrowid


_SELECT = """
    SELECT d.*, l.name AS launch_name
      FROM decisions d JOIN launches l ON l.id = d.launch_id
"""
_NEWEST_FIRST = " ORDER BY d.decided_on DESC, d.id DESC"


def list_decisions(
    conn: sqlite3.Connection, launch_id: Optional[int] = None, kind: Optional[str] = None
) -> list[DecisionView]:
    """Decisions newest first (by decision date, then the order recorded)."""
    where, args = [], []
    if launch_id is not None:
        where.append("d.launch_id = ?")
        args.append(launch_id)
    if kind:
        where.append("d.kind = ?")
        args.append(kind)
    sql = _SELECT + (" WHERE " + " AND ".join(where) if where else "") + _NEWEST_FIRST
    return [_view(r) for r in conn.execute(sql, args).fetchall()]


def latest_go_no_go(conn: sqlite3.Connection, launch_id: int) -> Optional[DecisionView]:
    row = conn.execute(
        _SELECT + " WHERE d.launch_id = ? AND d.kind IN ('go', 'no_go')" + _NEWEST_FIRST + " LIMIT 1",
        (launch_id,),
    ).fetchone()
    return _view(row) if row else None


def latest_go_no_go_by_launch(conn: sqlite3.Connection) -> dict[int, DecisionView]:
    """Each launch's latest Go or No-go, for the home page."""
    latest: dict[int, DecisionView] = {}
    for d in list_decisions(conn):
        if d.is_go_no_go and d.launch_id not in latest:
            latest[d.launch_id] = d
    return latest


@dataclass(frozen=True)
class SinceDecision:
    """What has changed since a decision was recorded."""

    then: Optional[str]           # readiness headline at the decision
    now: str                      # readiness headline now
    readiness_changed: bool
    scope_changes_since: int

    @property
    def anything_changed(self) -> bool:
        return self.readiness_changed or self.scope_changes_since > 0


def _blocker_names(snap: Optional[dict]) -> list[str]:
    return sorted(b["name"] for b in (snap or {}).get("blockers", []))


def changes_since(
    conn: sqlite3.Connection, decision: DecisionView, current: Readiness
) -> SinceDecision:
    """Compare readiness now with the decision's snapshot, and count later scope changes."""
    now_snap = snapshot(current)
    changed = decision.snapshot is not None and (
        decision.snapshot["headline"] != now_snap["headline"]
        or _blocker_names(decision.snapshot) != _blocker_names(now_snap)
    )
    later = conn.execute(
        "SELECT COUNT(*) FROM decisions WHERE launch_id = ? AND kind = 'scope_change' AND id > ?",
        (decision.launch_id, decision.id),
    ).fetchone()[0]
    return SinceDecision(
        then=decision.snapshot_headline,
        now=current.headline,
        readiness_changed=changed,
        scope_changes_since=later,
    )
