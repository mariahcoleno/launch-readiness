"""Dashboard logic: overdue flags, team groups, what needs attention.

Plain functions over plain data, with "today" passed in, so they're easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Mapping, Optional

from . import settings
from .models import GateStatus

DONE_STATUSES = frozenset({GateStatus.PASSED, GateStatus.WAIVED})


def is_overdue(status: GateStatus, due_date: Optional[date], today: date) -> bool:
    """Past its due date and not done. A gate due today isn't overdue yet."""
    return due_date is not None and due_date < today and status not in DONE_STATUSES


def is_at_risk(
    status: GateStatus, due_date: Optional[date], today: date, days: Optional[int] = None
) -> bool:
    """Not started and due between today and `days` from now, both ends included.

    Past-due gates are overdue instead, not at risk.
    """
    if days is None:
        days = settings.GATE_AT_RISK_DAYS
    return (
        status is GateStatus.NOT_STARTED
        and due_date is not None
        and today <= due_date <= today + timedelta(days=days)
    )


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
    at_risk: bool = False

    @property
    def has_complete_waiver(self) -> bool:
        return bool((self.waiver_rationale or "").strip() and (self.waived_by or "").strip())

    @property
    def is_done(self) -> bool:
        """Passed, or waived with both a rationale and who approved it."""
        if self.status is GateStatus.PASSED:
            return True
        return self.status is GateStatus.WAIVED and self.has_complete_waiver

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
        if self.at_risk:
            tags.append("At risk")
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
        at_risk=is_at_risk(status, due, today),
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


def severity_order(gate: GateView) -> tuple:
    """Failed, then overdue, then at risk, then the rest; earliest due date first within each."""
    return (not gate.is_failed, not gate.overdue, not gate.at_risk, gate.due_date or date.max, gate.id)


def needs_attention(gates: Iterable[GateView]) -> list[GateView]:
    """Every failed, overdue, at-risk or unassigned gate, worst first."""
    return sorted((g for g in gates if g.attention_tags), key=severity_order)


@dataclass(frozen=True)
class Summary:
    total: int
    done: int
    failed: int
    overdue: int
    at_risk: int
    unassigned: int


def summarize(gates: Iterable[GateView]) -> Summary:
    gates = list(gates)
    return Summary(
        total=len(gates),
        done=sum(g.is_done for g in gates),
        failed=sum(g.is_failed for g in gates),
        overdue=sum(g.overdue for g in gates),
        at_risk=sum(g.at_risk for g in gates),
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
