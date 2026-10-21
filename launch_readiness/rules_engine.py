"""Gate rules engine: given a configuration, which gates does it need?

Rules are read from gate_rules.yaml. This module has no database or web code,
so it can be tested on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import yaml

from .models import Capability, Configuration, GateDefinition, RequiredGate, Stage, Surface

DEFAULT_RULES_PATH = Path(__file__).with_name("gate_rules.yaml")

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_GATE_KEYS = {"id", "name", "team", "description", "required", "required_when"}
_CONDITION_KEYS = {"capabilities", "surfaces", "stage_at_least"}

class RulesError(ValueError):
    """The rules file is invalid. The message says which gate and field."""


@dataclass(frozen=True)
class GateRule:
    definition: GateDefinition
    always: bool = False
    capabilities: frozenset[Capability] = frozenset()
    surfaces: frozenset[Surface] = frozenset()
    stage_at_least: Optional[Stage] = None

    def reasons_for(self, config: Configuration) -> tuple[str, ...]:
        """Why this gate applies to the config. Empty means it doesn't apply."""
        if self.always:
            return ("Always required",)
        reasons = []
        for cap in Capability:  # enum order keeps reasons stable
            if cap in self.capabilities and cap in config.capabilities:
                reasons.append(f"{cap.label} is on")
        for surface in Surface:
            if surface in self.surfaces and surface in config.surfaces:
                reasons.append(f"{surface.label} surface is included")
        if self.stage_at_least is not None and config.stage >= self.stage_at_least:
            reasons.append(f"Stage is {_mid_sentence(self.stage_at_least.label)} or later")
        return tuple(reasons)


@dataclass(frozen=True)
class GateRules:
    rules: tuple[GateRule, ...]

    def definition(self, gate_id: str) -> GateDefinition:
        for rule in self.rules:
            if rule.definition.id == gate_id:
                return rule.definition
        raise KeyError(gate_id)

    @property
    def gate_ids(self) -> list[str]:
        return [r.definition.id for r in self.rules]


@dataclass(frozen=True)
class GateDiff:
    """Gates gained and lost when moving from one configuration to another."""

    added: tuple[RequiredGate, ...]
    removed: tuple[RequiredGate, ...]

    @property
    def is_empty(self) -> bool:
        return not self.added and not self.removed


def _mid_sentence(label: str) -> str:
    """'Limited GA' -> 'limited GA', but leave all-caps words like 'GA' alone."""
    first, _, rest = label.partition(" ")
    if not first.isupper():
        first = first.lower()
    return f"{first} {rest}".strip()


# --- Loading -----------------------------------------------------------------


def load_rules(path: Union[str, Path, None] = None) -> GateRules:
    """Read and validate a rules file. Raises RulesError with a clear message."""
    path = Path(path) if path is not None else DEFAULT_RULES_PATH
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RulesError(f"{path.name} is not valid YAML: {exc}") from exc
    return parse_rules(data, source=path.name)


def parse_rules(data: object, source: str = "rules") -> GateRules:
    if not isinstance(data, dict) or set(data) != {"gates"}:
        raise RulesError(f"{source}: the file must contain a single top-level 'gates:' list.")
    gates = data["gates"]
    if not isinstance(gates, list) or not gates:
        raise RulesError(f"{source}: 'gates' must be a non-empty list.")

    rules: list[GateRule] = []
    seen: set[str] = set()
    for index, raw in enumerate(gates, start=1):
        rule = _parse_gate(raw, f"{source}, gate #{index}")
        if rule.definition.id in seen:
            raise RulesError(f"{source}: gate id '{rule.definition.id}' is used more than once.")
        seen.add(rule.definition.id)
        rules.append(rule)
    return GateRules(tuple(rules))


def _parse_gate(raw: object, where: str) -> GateRule:
    if not isinstance(raw, dict):
        raise RulesError(f"{where}: each gate must be a set of 'key: value' lines.")

    gate_id = raw.get("id")
    if isinstance(gate_id, str):
        where = f"{where} ('{gate_id}')"

    unknown = set(raw) - _GATE_KEYS
    if unknown:
        raise RulesError(
            f"{where}: unknown field(s) {_fmt(unknown)}. Allowed: {_fmt(_GATE_KEYS)}."
        )

    for key in ("id", "name", "team"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RulesError(f"{where}: '{key}' is missing or empty.")
    if not _ID_PATTERN.match(gate_id):
        raise RulesError(
            f"{where}: id must be lowercase letters, numbers and underscores, "
            f"starting with a letter."
        )
    description = raw.get("description", "") or ""
    if not isinstance(description, str):
        raise RulesError(f"{where}: 'description' must be text.")

    definition = GateDefinition(
        id=gate_id, name=raw["name"].strip(), team=raw["team"].strip(),
        description=description.strip(),
    )

    has_required = "required" in raw
    has_when = "required_when" in raw
    if has_required and has_when:
        raise RulesError(f"{where}: use either 'required: always' or 'required_when', not both.")
    if not has_required and not has_when:
        raise RulesError(f"{where}: needs 'required: always' or a 'required_when' section.")

    if has_required:
        if raw["required"] != "always":
            raise RulesError(f"{where}: 'required' can only be 'always'.")
        return GateRule(definition, always=True)

    return _parse_conditions(definition, raw["required_when"], where)


def _parse_conditions(definition: GateDefinition, when: object, where: str) -> GateRule:
    if not isinstance(when, dict) or not when:
        raise RulesError(f"{where}: 'required_when' needs at least one condition.")
    unknown = set(when) - _CONDITION_KEYS
    if unknown:
        raise RulesError(
            f"{where}: unknown condition(s) {_fmt(unknown)}. Allowed: {_fmt(_CONDITION_KEYS)}."
        )

    capabilities = _parse_enum_list(when.get("capabilities"), Capability, "capabilities", where)
    surfaces = _parse_enum_list(when.get("surfaces"), Surface, "surfaces", where)

    stage = None
    if "stage_at_least" in when:
        stage = _parse_enum(when["stage_at_least"], Stage, "stage_at_least", where)

    return GateRule(definition, capabilities=capabilities, surfaces=surfaces, stage_at_least=stage)


def _parse_enum_list(values, enum_cls, field_name, where):
    if values is None:
        return frozenset()
    if not isinstance(values, list) or not values:
        raise RulesError(f"{where}: '{field_name}' must be a non-empty list, like [a, b].")
    return frozenset(_parse_enum(v, enum_cls, field_name, where) for v in values)


def _parse_enum(value, enum_cls, field_name, where):
    allowed = [m.value for m in enum_cls]
    if value not in allowed:
        raise RulesError(
            f"{where}: '{value}' is not a valid value for {field_name}. "
            f"Allowed: {', '.join(allowed)}."
        )
    return enum_cls(value)


def _fmt(keys) -> str:
    return ", ".join(f"'{k}'" for k in sorted(keys))


# --- Evaluating --------------------------------------------------------------


def required_gates(config: Configuration, rules: Optional[GateRules] = None) -> list[RequiredGate]:
    """The gates this configuration needs, in rules-file order, each listed once."""
    rules = rules if rules is not None else load_rules()
    result = []
    for rule in rules.rules:
        reasons = rule.reasons_for(config)
        if reasons:
            result.append(RequiredGate(rule.definition, reasons))
    return result


def gate_diff(
    old: Configuration, new: Configuration, rules: Optional[GateRules] = None
) -> GateDiff:
    """Which gates the new configuration adds and which it no longer needs.

    A gate with several triggers stays as long as any trigger is still on.
    """
    rules = rules if rules is not None else load_rules()
    before = {g.id: g for g in required_gates(old, rules)}
    after = {g.id: g for g in required_gates(new, rules)}
    added = tuple(g for gid, g in after.items() if gid not in before)
    removed = tuple(g for gid, g in before.items() if gid not in after)
    return GateDiff(added=added, removed=removed)
