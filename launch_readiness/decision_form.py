"""Check the decision forms: scope changes, and Go / No-go decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from .models import DecisionKind

MAX_NAME_LENGTH = 100
MAX_TEXT_LENGTH = 2000


@dataclass(frozen=True)
class ScopeChangeInput:
    decided_by: str
    rationale: str
    follow_up: Optional[str] = None


def parse_scope_change_form(
    form, follow_up_required: bool = True
) -> tuple[Optional[ScopeChangeInput], dict[str, str]]:
    """Return (input, {}) if valid, or (None, errors by field name).

    Decided-by and rationale are always required. The follow-up is required when
    turning a capability off, optional when turning one on.
    """
    errors: dict[str, str] = {}
    fields = {k: (form.get(k) or "").strip() for k in ("decided_by", "rationale", "follow_up")}

    if not fields["decided_by"]:
        errors["decided_by"] = "Say who made this decision."
    elif len(fields["decided_by"]) > MAX_NAME_LENGTH:
        errors["decided_by"] = f"Keep this under {MAX_NAME_LENGTH} characters."

    if not fields["rationale"]:
        errors["rationale"] = (
            "Explain why the launch is going ahead without this capability."
            if follow_up_required
            else "Explain why this capability is being added."
        )
    elif len(fields["rationale"]) > MAX_TEXT_LENGTH:
        errors["rationale"] = f"Keep the rationale under {MAX_TEXT_LENGTH} characters."

    if not fields["follow_up"]:
        if follow_up_required:
            errors["follow_up"] = "Describe the follow-up, e.g. when to turn it back on."
    elif len(fields["follow_up"]) > MAX_TEXT_LENGTH:
        errors["follow_up"] = f"Keep the follow-up under {MAX_TEXT_LENGTH} characters."

    if errors:
        return None, errors
    return (
        ScopeChangeInput(
            decided_by=fields["decided_by"],
            rationale=fields["rationale"],
            follow_up=fields["follow_up"] or None,
        ),
        {},
    )


# --- Go / No-go decisions -------------------------------------------------------


@dataclass(frozen=True)
class GoNoGoInput:
    kind: DecisionKind
    decided_by: str
    decided_on: date
    rationale: str
    follow_up: Optional[str]
    acknowledged_blockers: bool = False


CHECKED = {"1", "on", "yes", "true"}


def parse_go_no_go_form(
    form, today: date, launch_ready: bool
) -> tuple[Optional[GoNoGoInput], dict[str, str]]:
    """Return (input, {}) if valid, or (None, errors by field name).

    The follow-up is required for No-go, and for Go while the launch is Not ready
    (along with the acknowledgement checkbox). It's optional only for Go when Ready.
    """
    errors: dict[str, str] = {}

    kind = None
    raw_kind = (form.get("kind") or "").strip()
    if raw_kind not in (DecisionKind.GO.value, DecisionKind.NO_GO.value):
        errors["kind"] = "Choose Go or No-go."
    else:
        kind = DecisionKind(raw_kind)

    decided_by = (form.get("decided_by") or "").strip()
    if not decided_by:
        errors["decided_by"] = "Say who made this decision."
    elif len(decided_by) > MAX_NAME_LENGTH:
        errors["decided_by"] = f"Keep this under {MAX_NAME_LENGTH} characters."

    decided_on = today
    raw_date = (form.get("decided_on") or "").strip()
    if raw_date:
        try:
            decided_on = date.fromisoformat(raw_date)
        except ValueError:
            errors["decided_on"] = "Enter the date as YYYY-MM-DD."
        else:
            if decided_on > today:
                errors["decided_on"] = "A decision can't be dated in the future."

    rationale = (form.get("rationale") or "").strip()
    if not rationale:
        errors["rationale"] = "Explain the decision."
    elif len(rationale) > MAX_TEXT_LENGTH:
        errors["rationale"] = f"Keep the rationale under {MAX_TEXT_LENGTH} characters."

    go_with_blockers = kind is DecisionKind.GO and not launch_ready
    acknowledged = (form.get("acknowledge_blockers") or "").strip().lower() in CHECKED
    if go_with_blockers and not acknowledged:
        errors["acknowledge_blockers"] = (
            "This launch is Not ready. Tick the box to record Go with open blockers."
        )

    follow_up = (form.get("follow_up") or "").strip()
    if not follow_up:
        if kind is DecisionKind.NO_GO:
            errors["follow_up"] = "Say what happens next."
        elif go_with_blockers:
            errors["follow_up"] = "Say what happens to the open blockers."
    elif len(follow_up) > MAX_TEXT_LENGTH:
        errors["follow_up"] = f"Keep the follow-up under {MAX_TEXT_LENGTH} characters."

    if errors:
        return None, errors
    return (
        GoNoGoInput(
            kind=kind,
            decided_by=decided_by,
            decided_on=decided_on,
            rationale=rationale,
            follow_up=follow_up or None,
            acknowledged_blockers=go_with_blockers,
        ),
        {},
    )
