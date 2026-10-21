"""Core types: what a launch configuration is, and what a gate is."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

# Human-readable names, shared by the web pages and the rules engine.
LABELS = {
    "internal": "Internal",
    "trusted_testers": "Trusted testers",
    "limited_ga": "Limited GA",
    "ga": "GA",
    "api": "API",
    "consumer_app": "Consumer app",
    "enterprise": "Enterprise",
    "tool_use": "Tool use",
    "code_execution": "Code execution",
    "web_browsing": "Web browsing",
    "file_uploads": "File uploads",
    "memory": "Memory",
    "not_started": "Not started",
    "in_progress": "In progress",
    "passed": "Passed",
    "failed": "Failed",
    "waived": "Waived",
    "go": "Go",
    "no_go": "No-go",
    "scope_change": "Scope change",
}


class LabeledEnum(Enum):
    @property
    def label(self) -> str:
        return LABELS[self.value]


class Stage(LabeledEnum):
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


class Surface(LabeledEnum):
    API = "api"
    CONSUMER_APP = "consumer_app"
    ENTERPRISE = "enterprise"


class Capability(LabeledEnum):
    TOOL_USE = "tool_use"
    CODE_EXECUTION = "code_execution"
    WEB_BROWSING = "web_browsing"
    FILE_UPLOADS = "file_uploads"
    MEMORY = "memory"


class GateStatus(LabeledEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    WAIVED = "waived"


class DecisionKind(LabeledEnum):
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


@dataclass(frozen=True)
class LaunchInput:
    """A new launch, as entered on the form and already checked."""

    name: str
    model_version: str
    target_date: date
    stage: Stage
    surfaces: frozenset[Surface]
    capabilities: frozenset[Capability]

    def configuration(self) -> Configuration:
        return Configuration(self.model_version, self.stage, self.surfaces, self.capabilities)
