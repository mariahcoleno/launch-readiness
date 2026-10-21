"""Check the scope-change form (launching with a capability turned off)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

MAX_NAME_LENGTH = 100
MAX_TEXT_LENGTH = 2000


@dataclass(frozen=True)
class ScopeChangeInput:
    decided_by: str
    rationale: str
    follow_up: str


def parse_scope_change_form(form) -> tuple[Optional[ScopeChangeInput], dict[str, str]]:
    """Return (input, {}) if valid, or (None, errors by field name). All fields required."""
    errors: dict[str, str] = {}
    fields = {k: (form.get(k) or "").strip() for k in ("decided_by", "rationale", "follow_up")}

    if not fields["decided_by"]:
        errors["decided_by"] = "Say who made this decision."
    elif len(fields["decided_by"]) > MAX_NAME_LENGTH:
        errors["decided_by"] = f"Keep this under {MAX_NAME_LENGTH} characters."

    if not fields["rationale"]:
        errors["rationale"] = "Explain why the launch is going ahead without this capability."
    elif len(fields["rationale"]) > MAX_TEXT_LENGTH:
        errors["rationale"] = f"Keep the rationale under {MAX_TEXT_LENGTH} characters."

    if not fields["follow_up"]:
        errors["follow_up"] = "Describe the follow-up, e.g. when to turn it back on."
    elif len(fields["follow_up"]) > MAX_TEXT_LENGTH:
        errors["follow_up"] = f"Keep the follow-up under {MAX_TEXT_LENGTH} characters."

    if errors:
        return None, errors
    return ScopeChangeInput(**fields), {}
