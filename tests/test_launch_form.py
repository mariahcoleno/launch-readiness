"""Checking the "New launch" form, with no database or web server."""

from datetime import date

import pytest
from werkzeug.datastructures import MultiDict

from launch_readiness.launch_form import parse_launch_form
from launch_readiness.models import Capability, Stage, Surface


def valid_form(**overrides):
    fields = {
        "name": "Model Atlas v2.1 — trusted testers",
        "model_version": "Model Atlas v2.1",
        "target_date": "2026-12-15",
        "stage": "trusted_testers",
        "surfaces": ["api", "consumer_app"],
        "capabilities": ["tool_use"],
    }
    fields.update(overrides)
    form = MultiDict()
    for key, value in fields.items():
        for v in value if isinstance(value, list) else [value]:
            form.add(key, v)
    return form


def test_valid_form_becomes_launch_input():
    data, errors = parse_launch_form(valid_form())
    assert errors == {}
    assert data.name == "Model Atlas v2.1 — trusted testers"
    assert data.model_version == "Model Atlas v2.1"
    assert data.target_date == date(2026, 12, 15)
    assert data.stage is Stage.TRUSTED_TESTERS
    assert data.surfaces == {Surface.API, Surface.CONSUMER_APP}
    assert data.capabilities == {Capability.TOOL_USE}


def test_no_capabilities_is_fine():
    data, errors = parse_launch_form(valid_form(capabilities=[]))
    assert errors == {}
    assert data.capabilities == frozenset()


def test_whitespace_is_trimmed():
    data, _ = parse_launch_form(valid_form(name="  Atlas  ", model_version=" v2.1 "))
    assert data.name == "Atlas"
    assert data.model_version == "v2.1"


def test_past_target_date_is_allowed():
    data, errors = parse_launch_form(valid_form(target_date="2020-01-01"))
    assert errors == {}


def test_works_with_a_plain_dict():
    form = dict(valid_form().lists())
    form = {k: (v if k in ("surfaces", "capabilities") else v[0]) for k, v in form.items()}
    data, errors = parse_launch_form(form)
    assert errors == {}
    assert data.surfaces == {Surface.API, Surface.CONSUMER_APP}


@pytest.mark.parametrize(
    "overrides, field, message",
    [
        ({"name": ""}, "name", "Enter a launch name"),
        ({"name": "   "}, "name", "Enter a launch name"),
        ({"name": "x" * 201}, "name", "under 200 characters"),
        ({"model_version": ""}, "model_version", "Enter a model version"),
        ({"model_version": "v" * 101}, "model_version", "under 100 characters"),
        ({"target_date": ""}, "target_date", "Enter a target date"),
        ({"target_date": "15/12/2026"}, "target_date", "YYYY-MM-DD"),
        ({"target_date": "2026-02-30"}, "target_date", "YYYY-MM-DD"),
        ({"stage": ""}, "stage", "Choose a rollout stage"),
        ({"stage": "beta"}, "stage", "'beta' is not a rollout stage"),
        ({"surfaces": []}, "surfaces", "at least one product surface"),
        ({"surfaces": ["api", "mobile"]}, "surfaces", "Unknown surface: mobile"),
        ({"capabilities": ["code_exec"]}, "capabilities", "Unknown capability: code_exec"),
    ],
)
def test_each_problem_gets_its_own_message(overrides, field, message):
    data, errors = parse_launch_form(valid_form(**overrides))
    assert data is None
    assert list(errors) == [field]
    assert message in errors[field]


def test_all_problems_reported_together():
    data, errors = parse_launch_form(MultiDict())
    assert data is None
    assert set(errors) == {"name", "model_version", "target_date", "stage", "surfaces"}
