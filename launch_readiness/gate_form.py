"""Check the "Edit gate" form and turn it into a GateUpdate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from .models import GateStatus

MAX_OWNER_LENGTH = 100
MAX_NOTES_LENGTH = 2000


@dataclass(frozen=True)
class GateUpdate:
    status: GateStatus
    owner: Optional[str]
    due_date: Optional[date]
    notes: Optional[str]
    waiver_rationale: Optional[str]
    waived_by: Optional[str]


def _text(form, key: str) -> str:
    return (form.get(key) or "").strip()


def parse_gate_form(form) -> tuple[Optional[GateUpdate], dict[str, str]]:
    """Return (update, {}) if valid, or (None, errors by field name).

    A waived gate needs a rationale and who waived it. Any other status clears both.
    """
    errors: dict[str, str] = {}

    status = None
    raw_status = _text(form, "status")
    try:
        status = GateStatus(raw_status)
    except ValueError:
        errors["status"] = "Choose a status." if not raw_status else f"'{raw_status}' is not a status."

    owner = _text(form, "owner")
    if len(owner) > MAX_OWNER_LENGTH:
        errors["owner"] = f"Keep the owner under {MAX_OWNER_LENGTH} characters."

    due_date = None
    raw_due = _text(form, "due_date")
    if raw_due:
        try:
            due_date = date.fromisoformat(raw_due)
        except ValueError:
            errors["due_date"] = "Enter the date as YYYY-MM-DD, or leave it blank."

    notes = _text(form, "notes")
    if len(notes) > MAX_NOTES_LENGTH:
        errors["notes"] = f"Keep notes under {MAX_NOTES_LENGTH} characters."

    rationale = _text(form, "waiver_rationale")
    waived_by = _text(form, "waived_by")
    if status is GateStatus.WAIVED:
        if not rationale:
            errors["waiver_rationale"] = "A waived gate needs a waiver rationale."
        elif len(rationale) > MAX_NOTES_LENGTH:
            errors["waiver_rationale"] = f"Keep the rationale under {MAX_NOTES_LENGTH} characters."
        if not waived_by:
            errors["waived_by"] = "Say who approved the waiver."
        elif len(waived_by) > MAX_OWNER_LENGTH:
            errors["waived_by"] = f"Keep this under {MAX_OWNER_LENGTH} characters."
    else:
        rationale = waived_by = ""

    if errors:
        return None, errors
    return (
        GateUpdate(
            status=status,
            owner=owner or None,
            due_date=due_date,
            notes=notes or None,
            waiver_rationale=rationale or None,
            waived_by=waived_by or None,
        ),
        {},
    )
