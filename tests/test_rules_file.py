"""The rules file loads, and mistakes in it give clear errors."""

import pytest

from launch_readiness.models import Stage
from launch_readiness.rules_engine import RulesError, load_rules, parse_rules


def gate(**fields):
    base = {"id": "g1", "name": "Gate one", "team": "Team", "required": "always"}
    base.update(fields)
    return {k: v for k, v in base.items() if v is not None}


def parse_one(g):
    return parse_rules({"gates": [g]})


def test_shipped_rules_file_loads():
    rules = load_rules()
    assert len(rules.gate_ids) == 15
    assert rules.definition("capacity_signoff").team == "Infrastructure"


def test_valid_conditions_parse():
    rules = parse_one(
        gate(
            required=None,
            required_when={"capabilities": ["memory"], "stage_at_least": "ga"},
        )
    )
    rule = rules.rules[0]
    assert rule.stage_at_least is Stage.GA
    assert not rule.always


@pytest.mark.parametrize(
    "bad_gate, message",
    [
        (gate(id=None), "'id' is missing"),
        (gate(name=""), "'name' is missing"),
        (gate(team=None), "'team' is missing"),
        (gate(id="Bad Id"), "id must be lowercase"),
        (gate(owner="Sam"), "unknown field(s) 'owner'"),
        (gate(required="sometimes"), "'required' can only be 'always'"),
        (gate(required=None), "needs 'required: always' or a 'required_when'"),
        (gate(required_when={"capabilities": ["memory"]}), "not both"),
        (gate(required=None, required_when={}), "at least one condition"),
        (gate(required=None, required_when={"capability": ["memory"]}), "unknown condition(s) 'capability'"),
        (gate(required=None, required_when={"capabilities": ["code_exec"]}), "'code_exec' is not a valid value for capabilities"),
        (gate(required=None, required_when={"capabilities": "memory"}), "must be a non-empty list"),
        (gate(required=None, required_when={"surfaces": ["mobile"]}), "'mobile' is not a valid value for surfaces"),
        (gate(required=None, required_when={"stage_at_least": "beta"}), "'beta' is not a valid value for stage_at_least"),
    ],
)
def test_bad_gate_gives_clear_error(bad_gate, message):
    with pytest.raises(RulesError) as exc:
        parse_one(bad_gate)
    assert message in str(exc.value)


def test_error_names_the_gate():
    with pytest.raises(RulesError, match=r"gate #1 \('g1'\)"):
        parse_one(gate(team=""))


def test_duplicate_ids_rejected():
    with pytest.raises(RulesError, match="'g1' is used more than once"):
        parse_rules({"gates": [gate(), gate()]})


@pytest.mark.parametrize("data", [None, [], {"gates": []}, {"gates": [gate()], "extra": 1}])
def test_bad_top_level_rejected(data):
    with pytest.raises(RulesError):
        parse_rules(data)


def test_invalid_yaml_rejected(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("gates:\n  - id: g1\n    name: [unclosed\n")
    with pytest.raises(RulesError, match="not valid YAML"):
        load_rules(path)


def test_rules_file_on_disk_round_trip(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "gates:\n"
        "  - id: g1\n    name: Gate one\n    team: Team\n    required: always\n"
        "  - id: g2\n    name: Gate two\n    team: Team\n"
        "    required_when:\n      surfaces: [enterprise]\n"
    )
    assert load_rules(path).gate_ids == ["g1", "g2"]
