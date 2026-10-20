"""The factory model: typed configuration for agents and factories, and how to load it.

Agents are made of three blocks (Brief, Capabilities, Quality Gate) and described by
`agent.yaml`. Factories place agents, operations and human gates into ordered stages and are
described by a factory file. Every model is immutable and rejects unknown fields.
"""

from conveyor.model.agent import (
    Agent,
    Brief,
    Capabilities,
    ModelProfile,
    Permissions,
    QualityGate,
    Routing,
)
from conveyor.model.errors import ConfigError, Issue
from conveyor.model.factory import (
    AgentStage,
    Factory,
    HumanGateStage,
    HumanReview,
    HumanReviewScorer,
    OnReject,
    OperationStage,
    Outcome,
    Scorer,
    Stage,
    Trigger,
)
from conveyor.model.loader import dump_yaml, load_agent_file, load_factory_file
from conveyor.model.validate import NothingToValidateError, ValidationReport, validate_path

__all__ = [
    "Agent",
    "AgentStage",
    "Brief",
    "Capabilities",
    "ConfigError",
    "Factory",
    "HumanGateStage",
    "HumanReview",
    "HumanReviewScorer",
    "Issue",
    "ModelProfile",
    "NothingToValidateError",
    "OnReject",
    "OperationStage",
    "Outcome",
    "Permissions",
    "QualityGate",
    "Routing",
    "Scorer",
    "Stage",
    "Trigger",
    "ValidationReport",
    "dump_yaml",
    "load_agent_file",
    "load_factory_file",
    "validate_path",
]
