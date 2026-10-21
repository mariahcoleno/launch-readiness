"""Check the "New launch" form and turn it into a LaunchInput."""

from __future__ import annotations

from datetime import date
from typing import Optional

from .models import Capability, LaunchInput, Stage, Surface

MAX_NAME_LENGTH = 200
MAX_VERSION_LENGTH = 100


def _getlist(form, key: str) -> list[str]:
    """Works with Flask's form object and with a plain dict (in tests)."""
    if hasattr(form, "getlist"):
        return form.getlist(key)
    value = form.get(key, [])
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


def parse_launch_form(form) -> tuple[Optional[LaunchInput], dict[str, str]]:
    """Return (launch, {}) if the form is valid, or (None, errors by field name)."""
    errors: dict[str, str] = {}

    name = (form.get("name") or "").strip()
    if not name:
        errors["name"] = "Enter a launch name."
    elif len(name) > MAX_NAME_LENGTH:
        errors["name"] = f"Keep the name under {MAX_NAME_LENGTH} characters."

    version = (form.get("model_version") or "").strip()
    if not version:
        errors["model_version"] = "Enter a model version."
    elif len(version) > MAX_VERSION_LENGTH:
        errors["model_version"] = f"Keep the version under {MAX_VERSION_LENGTH} characters."

    target_date = None
    raw_date = (form.get("target_date") or "").strip()
    if not raw_date:
        errors["target_date"] = "Enter a target date."
    else:
        try:
            target_date = date.fromisoformat(raw_date)
        except ValueError:
            errors["target_date"] = "Enter the date as YYYY-MM-DD."

    stage = None
    raw_stage = (form.get("stage") or "").strip()
    if not raw_stage:
        errors["stage"] = "Choose a rollout stage."
    else:
        try:
            stage = Stage(raw_stage)
        except ValueError:
            errors["stage"] = f"'{raw_stage}' is not a rollout stage."

    surfaces, bad = _parse_choices(_getlist(form, "surfaces"), Surface)
    if bad:
        errors["surfaces"] = f"Unknown surface: {', '.join(bad)}."
    elif not surfaces:
        errors["surfaces"] = "Choose at least one product surface."

    capabilities, bad = _parse_choices(_getlist(form, "capabilities"), Capability)
    if bad:
        errors["capabilities"] = f"Unknown capability: {', '.join(bad)}."

    if errors:
        return None, errors
    return (
        LaunchInput(
            name=name,
            model_version=version,
            target_date=target_date,
            stage=stage,
            surfaces=surfaces,
            capabilities=capabilities,
        ),
        {},
    )


def _parse_choices(values, enum_cls):
    allowed = {m.value for m in enum_cls}
    bad = sorted({v for v in values if v not in allowed})
    good = frozenset(enum_cls(v) for v in values if v in allowed)
    return good, bad
