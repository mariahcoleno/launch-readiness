"""The shipped rules file produces exactly the expected gates.

These tests are the written spec for gate_rules.yaml: if you change the rules,
update the expectations here too.
"""

import pytest

from launch_readiness.models import Capability, Configuration, Stage, Surface
from launch_readiness.rules_engine import required_gates

from .conftest import BASELINE, make_config


def ids(gates):
    return [g.id for g in gates]


def test_baseline_config_gets_only_always_required_gates(rules):
    gates = required_gates(make_config(), rules)
    assert set(ids(gates)) == BASELINE


@pytest.mark.parametrize(
    "capability, expected_gate",
    [
        (Capability.TOOL_USE, "tool_use_safety_eval"),
        (Capability.CODE_EXECUTION, "sandbox_security_review"),
        (Capability.WEB_BROWSING, "browsing_safety_review"),
        (Capability.FILE_UPLOADS, "file_handling_review"),
        (Capability.MEMORY, "memory_privacy_review"),
    ],
)
def test_each_capability_adds_exactly_its_gate(rules, capability, expected_gate):
    gates = required_gates(make_config(capabilities=[capability]), rules)
    assert set(ids(gates)) == BASELINE | {expected_gate}


@pytest.mark.parametrize(
    "surface, expected_extra",
    [
        (Surface.API, set()),
        (Surface.CONSUMER_APP, {"consumer_abuse_readiness"}),
        (Surface.ENTERPRISE, {"data_governance_privacy"}),
    ],
)
def test_each_surface_adds_exactly_its_gates(rules, surface, expected_extra):
    gates = required_gates(make_config(surfaces=[surface]), rules)
    assert set(ids(gates)) == BASELINE | expected_extra


@pytest.mark.parametrize(
    "stage, expected_extra",
    [
        (Stage.INTERNAL, set()),
        (Stage.TRUSTED_TESTERS, set()),
        (Stage.LIMITED_GA, {"capacity_signoff"}),
        (Stage.GA, {"capacity_signoff"}),
    ],
)
def test_capacity_signoff_from_limited_ga_onward(rules, stage, expected_extra):
    gates = required_gates(make_config(stage=stage), rules)
    assert set(ids(gates)) == BASELINE | expected_extra


def test_everything_on_at_ga_gets_every_gate_once(rules):
    config = make_config(stage=Stage.GA, surfaces=list(Surface), capabilities=list(Capability))
    gate_ids = ids(required_gates(config, rules))
    assert len(gate_ids) == len(set(gate_ids)), "no duplicates"
    assert set(gate_ids) == set(rules.gate_ids)


def test_atlas_v21_seed_config(rules, atlas_v21):
    gates = required_gates(atlas_v21, rules)
    assert set(ids(gates)) == BASELINE | {"tool_use_safety_eval", "consumer_abuse_readiness"}


def test_output_follows_rules_file_order(rules):
    config = make_config(stage=Stage.GA, surfaces=list(Surface), capabilities=list(Capability))
    assert ids(required_gates(config, rules)) == rules.gate_ids


def test_every_capability_has_at_least_one_gate(rules):
    """Otherwise disabling it in the go/no-go view would do nothing."""
    base = set(ids(required_gates(make_config(), rules)))
    for cap in Capability:
        with_cap = set(ids(required_gates(make_config(capabilities=[cap]), rules)))
        assert with_cap - base, f"{cap.value} has no gate"


def test_reasons_explain_why_each_gate_applies(rules):
    config = make_config(
        stage=Stage.LIMITED_GA,
        surfaces=[Surface.CONSUMER_APP],
        capabilities=[Capability.CODE_EXECUTION],
    )
    reasons = {g.id: g.reasons for g in required_gates(config, rules)}
    assert reasons["safety_evals"] == ("Always required",)
    assert reasons["sandbox_security_review"] == ("Code execution is on",)
    assert reasons["consumer_abuse_readiness"] == ("Consumer app surface is included",)
    assert reasons["capacity_signoff"] == ("Stage is limited GA or later",)


def test_gates_carry_name_and_team(rules):
    gates = {g.id: g for g in required_gates(make_config(surfaces=[Surface.CONSUMER_APP]), rules)}
    gate = gates["consumer_abuse_readiness"].definition
    assert gate.name == "Consumer abuse monitoring & reporting readiness"
    assert gate.team == "Trust & Safety"


# --- Configuration validation -------------------------------------------------


def test_configuration_needs_a_surface():
    with pytest.raises(ValueError, match="at least one product surface"):
        Configuration("v1", Stage.INTERNAL, frozenset())


def test_configuration_rejects_unknown_capability():
    with pytest.raises(TypeError, match="Unknown capability"):
        Configuration("v1", Stage.INTERNAL, {Surface.API}, {"code_execution"})


def test_stages_are_ordered():
    assert Stage.INTERNAL < Stage.TRUSTED_TESTERS < Stage.LIMITED_GA < Stage.GA
    assert Stage.GA >= Stage.LIMITED_GA
