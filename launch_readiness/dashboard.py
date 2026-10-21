"""Dashboard logic: overdue flags, team groups, what needs attention.

Plain functions over plain data, with "today" passed in, so they're easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping, Optional

from .models import GateStatus

DONE_STATUSES = frozenset({GateStatus.PASSED, GateStatus.WAIVED})


def is_overdue(status: GateStatus, due_date: Optional[date], today: date) -> bool:
    """Past its due date and not done. A gate due today isn't overdue yet."""
    return due_date is not None and due_date < today and status not in DONE_STATUSES


@dataclass(frozen=True)
class GateView:
    id: int
    gate_key: str
    name: str
    team: str
    owner: Optional[str]
    status: GateStatus
    due_date: Optional[date]
    notes: Optional[str]
    waiver_rationale: Optional[str]
    waived_by: Optional[str]
    reasons: tuple[str, ...]
    overdue: bool

    @property
    def is_done(self) -> bool:
        return self.status in DONE_STATUSES

    @property
    def is_failed(self) -> bool:
        return self.status is GateStatus.FAILED

    @property
    def is_unassigned(self) -> bool:
        return not self.owner

    @property
    def attention_tags(self) -> list[str]:
        """Why this gate needs attention, if it does."""
        tags = []
        if self.is_failed:
            tags.append("Failed")
        if self.overdue:
            tags.append("Overdue")
        if self.is_unassigned:
            tags.append("Unassigned")
        return tags


def gate_view(row: Mapping, reasons: tuple[str, ...], today: date) -> GateView:
    """Turn a gates table row into a GateView."""
    status = GateStatus(row["status"])
    due = date.fromisoformat(row["due_date"]) if row["due_date"] else None
    return GateView(
        id=row["id"],
        gate_key=row["gate_key"],
        name=row["name"],
        team=row["team"],
        owner=row["owner"],
        status=status,
        due_date=due,
        notes=row["notes"],
        waiver_rationale=row["waiver_rationale"],
        waived_by=row["waived_by"],
        reasons=reasons,
        overdue=is_overdue(status, due, today),
    )


@dataclass(frozen=True)
class TeamGroup:
    team: str
    gates: tuple[GateView, ...]

    @property
    def done_count(self) -> int:
        return sum(g.is_done for g in self.gates)


def group_by_team(gates: Iterable[GateView]) -> list[TeamGroup]:
    """Teams A–Z; gates keep their order (rules-file order) within each team."""
    by_team: dict[str, list[GateView]] = {}
    for gate in gates:
        by_team.setdefault(gate.team, []).append(gate)
    return [TeamGroup(team, tuple(by_team[team])) for team in sorted(by_team, key=str.casefold)]


def needs_attention(gates: Iterable[GateView]) -> list[GateView]:
    """Every failed, overdue or unassigned gate, worst first.

    Failed first, then overdue, then unassigned; earliest due date first within each.
    """
    flagged = [g for g in gates if g.attention_tags]
    return sorted(
        flagged,
        key=lambda g: (not g.is_failed, not g.overdue, g.due_date or date.max, g.id),
    )


@dataclass(frozen=True)
class Summary:
    total: int
    done: int
    failed: int
    overdue: int
    unassigned: int


def summarize(gates: Iterable[GateView]) -> Summary:
    gates = list(gates)
    return Summary(
        total=len(gates),
        done=sum(g.is_done for g in gates),
        failed=sum(g.is_failed for g in gates),
        overdue=sum(g.overdue for g in gates),
        unassigned=sum(g.is_unassigned for g in gates),
    )


def countdown(target: date, today: date) -> str:
    """'12 days away', '1 day away', 'Launch day is today' or 'Launch date passed'."""
    days = (target - today).days
    if days > 1:
        return f"{days} days away"
    if days == 1:
        return "1 day away"
    if days == 0:
        return "Launch day is today"
    return "Launch date passed"
