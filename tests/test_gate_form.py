"""Checking the "Edit gate" form, with no database or web server."""

from datetime import date

import pytest

from launch_readiness.gate_form import parse_gate_form
from launch_readiness.models import GateStatus


def form(**overrides):
    fields = {
        "status": "in_progress",
        "owner": "Priya N.",
        "due_date": "2026-11-20",
        "notes": "Halfway through the eval suite.",
        "waiver_rationale": "",
        "waived_by": "",
    }
    fields.update(overrides)
    return fields


WAIVER = {"status": "waived", "waiver_rationale": "Internal-only release.", "waived_by": "Morgan T."}


def test_valid_edit():
    update, errors = parse_gate_form(form())
    assert errors == {}
    assert update.status is GateStatus.IN_PROGRESS
    assert update.owner == "Priya N."
    assert update.due_date == date(2026, 11, 20)
    assert update.notes == "Halfway through the eval suite."
    assert update.waiver_rationale is None and update.waived_by is None


@pytest.mark.parametrize("status", ["not_started", "in_progress", "passed", "failed"])
def test_every_non_waived_status_is_accepted(status):
    update, errors = parse_gate_form(form(status=status))
    assert errors == {}
    assert update.status is GateStatus(status)


def test_waived_with_rationale_and_approver_is_accepted():
    update, errors = parse_gate_form(form(**WAIVER))
    assert errors == {}
    assert update.status is GateStatus.WAIVED
    assert update.waiver_rationale == "Internal-only release."
    assert update.waived_by == "Morgan T."


@pytest.mark.parametrize("rationale", ["", "   "])
def test_waived_without_rationale_is_rejected(rationale):
    update, errors = parse_gate_form(form(**{**WAIVER, "waiver_rationale": rationale}))
    assert update is None
    assert errors == {"waiver_rationale": "A waived gate needs a waiver rationale."}


@pytest.mark.parametrize("approver", ["", "   "])
def test_waived_without_approver_is_rejected(approver):
    update, errors = parse_gate_form(form(**{**WAIVER, "waived_by": approver}))
    assert update is None
    assert errors == {"waived_by": "Say who approved the waiver."}


def test_waived_with_neither_reports_both():
    _, errors = parse_gate_form(form(status="waived"))
    assert set(errors) == {"waiver_rationale", "waived_by"}


def test_leaving_waived_clears_rationale_and_approver():
    update, errors = parse_gate_form(form(**{**WAIVER, "status": "passed"}))
    assert errors == {}
    assert update.waiver_rationale is None
    assert update.waived_by is None


def test_blank_owner_notes_and_due_date_become_empty():
    update, errors = parse_gate_form(form(owner="  ", notes="", due_date=""))
    assert errors == {}
    assert update.owner is None and update.notes is None and update.due_date is None


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"status": ""}, "status"),
        ({"status": "done"}, "status"),
        ({"due_date": "next week"}, "due_date"),
        ({"due_date": "2026-02-30"}, "due_date"),
        ({"owner": "x" * 101}, "owner"),
        ({"notes": "x" * 2001}, "notes"),
        ({**WAIVER, "waiver_rationale": "x" * 2001}, "waiver_rationale"),
        ({**WAIVER, "waived_by": "x" * 101}, "waived_by"),
    ],
)
def test_bad_values_rejected(overrides, field):
    update, errors = parse_gate_form(form(**overrides))
    assert update is None
    assert list(errors) == [field]
