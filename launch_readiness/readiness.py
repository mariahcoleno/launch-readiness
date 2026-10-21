"""Readiness: are all of a launch's required gates done?

The verdict is "Ready" or "Not ready". It reports what the gates say; the
go/no-go decision itself is made and recorded by people.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from .dashboard import GateView, severity_order
from .models import GateStatus, RequiredGate

MISSING_NOTE = "Added to the rules after this launch was created"


@dataclass(frozen=True)
class Blocker:
    name: str
    team: str
    owner: Optional[str]
    status: Optional[GateStatus]  # None when the gate is missing from the launch
    due_date: Optional[date]
    tags: tuple[str, ...]
    gate_id: Optional[int] = None  # None when missing
    note: str = ""

    @property
    def is_missing(self) -> bool:
        return self.gate_id is None


@dataclass(frozen=True)
class Readiness:
    blockers: tuple[Blocker, ...]

    @property
    def ready(self) -> bool:
        return not self.blockers

    @property
    def verdict(self) -> str:
        return "Ready" if self.ready else "Not ready"

    @property
    def headline(self) -> str:
        if self.ready:
            return "Ready"
        n = len(self.blockers)
        return f"Not ready: {n} blocker{'s' if n != 1 else ''}"


def _blocker_for(gate: GateView) -> Blocker:
    tags = list(gate.attention_tags)
    if gate.status is GateStatus.WAIVED and not gate.has_complete_waiver:
        tags.insert(0, "Waiver incomplete")
    return Blocker(
        name=gate.name,
        team=gate.team,
        owner=gate.owner,
        status=gate.status,
        due_date=gate.due_date,
        tags=tuple(tags),
        gate_id=gate.id,
    )


def assess(gates: Iterable[GateView], required: Iterable[RequiredGate]) -> Readiness:
    """Assess a launch from its current gates and what the rules require now.

    Blockers: every current gate that isn't done (failed, overdue, at risk, then the
    rest), followed by any gate the rules require that the launch doesn't have.
    Removed gates should not be passed in; they don't count.
    """
    gates = list(gates)
    have = {g.gate_key for g in gates}
    open_gates = sorted((g for g in gates if not g.is_done), key=severity_order)
    blockers = [_blocker_for(g) for g in open_gates]
    for req in required:
        if req.id not in have:
            blockers.append(
                Blocker(
                    name=req.definition.name,
                    team=req.definition.team,
                    owner=None,
                    status=None,
                    due_date=None,
                    tags=("Missing",),
                    note=MISSING_NOTE,
                )
            )
    return Readiness(tuple(blockers))


def snapshot(readiness: Readiness) -> dict:
    """A plain record of a readiness verdict, saved with each decision."""
    return {
        "headline": readiness.headline,
        "ready": readiness.ready,
        "blockers": [
            {
                "name": b.name,
                "team": b.team,
                "status": b.status.value if b.status else None,
                "tags": list(b.tags),
            }
            for b in readiness.blockers
        ],
    }
