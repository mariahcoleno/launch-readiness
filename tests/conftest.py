import pytest

from launch_readiness.models import Capability, Configuration, Stage, Surface
from launch_readiness.rules_engine import load_rules

# Gates every configuration needs, per gate_rules.yaml.
BASELINE = {
    "safety_evals", "frontier_safety_evals", "red_team_signoff",
    "rollback_plan", "monitoring_oncall", "comms",
}


@pytest.fixture(scope="session")
def rules():
    return load_rules()


def make_config(stage=Stage.INTERNAL, surfaces=(Surface.API,), capabilities=()):
    return Configuration("Model Atlas v2.1", stage, frozenset(surfaces), frozenset(capabilities))


@pytest.fixture
def atlas_v21():
    """Seed launch: API + consumer app, tool use on, code execution off, trusted testers."""
    return make_config(
        stage=Stage.TRUSTED_TESTERS,
        surfaces=(Surface.API, Surface.CONSUMER_APP),
        capabilities=(Capability.TOOL_USE,),
    )
