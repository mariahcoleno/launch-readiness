"""Core types: what a launch configuration is, and what a gate is."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Stage(Enum):
    """Rollout stages, in order. Later stages compare as greater."""

    INTERNAL = "internal"
    TRUSTED_TESTERS = "trusted_testers"
    LIMITED_GA = "limited_ga"
    GA = "ga"

    @property
    def rank(self) -> int:
        return list(Stage).index(self)

    def __ge__(self, other: Stage) -> bool:
        return self.rank >= other.rank

    def __gt__(self, other: Stage) -> bool:
        return self.rank > other.rank

    def __le__(self, other: Stage) -> bool:
        return self.rank <= other.rank

    def __lt__(self, other: Stage) -> bool:
        return self.rank < other.rank


class Surface(Enum):
    API = "api"
    CONSUMER_APP = "consumer_app"
    ENTERPRISE = "enterprise"


class Capability(Enum):
    TOOL_USE = "tool_use"
    CODE_EXECUTION = "code_execution"
    WEB_BROWSING = "web_browsing"
    FILE_UPLOADS = "file_uploads"
    MEMORY = "memory"


class GateStatus(Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    WAIVED = "waived"


class DecisionKind(Enum):
    GO = "go"
    NO_GO = "no_go"
    SCOPE_CHANGE = "scope_change"


@dataclass(frozen=True)
class Configuration:
    """What is being launched: model version, stage, surfaces and capabilities."""

    model_version: str
    stage: Stage
    surfaces: frozenset[Surface]
    capabilities: frozenset[Capability] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        # Accept any iterable for convenience, store as frozensets.
        object.__setattr__(self, "surfaces", frozenset(self.surfaces))
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        if not isinstance(self.stage, Stage):
            raise TypeError(f"stage must be a Stage, got {self.stage!r}")
        if not self.surfaces:
            raise ValueError("A configuration needs at least one product surface.")
        for s in self.surfaces:
            if not isinstance(s, Surface):
                raise TypeError(f"Unknown surface: {s!r}")
        for c in self.capabilities:
            if not isinstance(c, Capability):
                raise TypeError(f"Unknown capability: {c!r}")

    def with_capability(self, capability: Capability, enabled: bool) -> Configuration:
        """Return a copy with one capability turned on or off."""
        caps = set(self.capabilities)
        if enabled:
            caps.add(capability)
        else:
            caps.discard(capability)
        return Configuration(self.model_version, self.stage, self.surfaces, frozenset(caps))


@dataclass(frozen=True)
class GateDefinition:
    """A gate as written in the rules file."""

    id: str
    name: str
    team: str
    description: str = ""


@dataclass(frozen=True)
class RequiredGate:
    """A gate a specific configuration needs, and why."""

    definition: GateDefinition
    reasons: tuple[str, ...]

    @property
    def id(self) -> str:
        return self.definition.id
