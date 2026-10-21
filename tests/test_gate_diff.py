"""Turning capabilities on or off adds or removes only the right gates."""

from launch_readiness.models import Capability, Surface
from launch_readiness.rules_engine import gate_diff, parse_rules, required_gates

from .conftest import make_config


def ids(gates):
    return {g.id for g in gates}


def test_enabling_code_execution_adds_only_sandbox_review(rules, atlas_v21):
    """The v2.2 delta review: only the new gate shows up."""
    v22 = atlas_v21.with_capability(Capability.CODE_EXECUTION, True)
    diff = gate_diff(atlas_v21, v22, rules)
    assert ids(diff.added) == {"sandbox_security_review"}
    assert diff.removed == ()
    assert diff.added[0].reasons == ("Code execution is on",)


def test_disabling_a_capability_removes_only_its_gates(rules, atlas_v21):
    without_tools = atlas_v21.with_capability(Capability.TOOL_USE, False)
    diff = gate_diff(atlas_v21, without_tools, rules)
    assert ids(diff.removed) == {"tool_use_safety_eval"}
    assert diff.added == ()


def test_each_capability_toggle_is_symmetric(rules, atlas_v21):
    for cap in Capability:
        if cap in atlas_v21.capabilities:
            continue
        on = atlas_v21.with_capability(cap, True)
        forward = gate_diff(atlas_v21, on, rules)
        back = gate_diff(on, atlas_v21, rules)
        assert ids(forward.added) == ids(back.removed)
        assert forward.removed == () and back.added == ()


def test_no_change_gives_empty_diff(rules, atlas_v21):
    assert gate_diff(atlas_v21, atlas_v21, rules).is_empty


def test_enabling_an_already_enabled_capability_changes_nothing(rules, atlas_v21):
    same = atlas_v21.with_capability(Capability.TOOL_USE, True)
    assert gate_diff(atlas_v21, same, rules).is_empty


# --- Gates with more than one trigger (sample rules, not the shipped file) ----

SHARED_RULES = parse_rules(
    {
        "gates": [
            {"id": "base", "name": "Base", "team": "A", "required": "always"},
            {
                "id": "data_review",
                "name": "Data review",
                "team": "Privacy",
                "required_when": {
                    "capabilities": ["memory", "file_uploads"],
                    "surfaces": ["enterprise"],
                },
            },
        ]
    }
)


def test_shared_gate_listed_once_with_all_reasons():
    config = make_config(
        surfaces=[Surface.ENTERPRISE],
        capabilities=[Capability.MEMORY, Capability.FILE_UPLOADS],
    )
    gates = required_gates(config, SHARED_RULES)
    assert [g.id for g in gates] == ["base", "data_review"]
    assert gates[1].reasons == (
        "File uploads is on",
        "Memory is on",
        "Enterprise surface is included",
    )


def test_shared_gate_stays_while_another_trigger_is_on():
    both = make_config(capabilities=[Capability.MEMORY, Capability.FILE_UPLOADS])
    memory_off = both.with_capability(Capability.MEMORY, False)
    assert gate_diff(both, memory_off, SHARED_RULES).is_empty


def test_shared_gate_removed_when_last_trigger_turns_off():
    one = make_config(capabilities=[Capability.MEMORY])
    none = one.with_capability(Capability.MEMORY, False)
    diff = gate_diff(one, none, SHARED_RULES)
    assert ids(diff.removed) == {"data_review"}
