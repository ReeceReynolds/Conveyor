"""The agent level of the factory model: one Brief, one set of Capabilities, one Quality Gate.

These models describe `agent.yaml`. They check shape and values only; whether the files they
point to exist is checked by `conveyor.model.checks`.
"""

from typing import Annotated, Self

from pydantic import Field, model_validator

from conveyor.model.base import ConfigModel, RuleViolation, raise_violations
from conveyor.model.types import (
    UNIQUE,
    DottedRef,
    RelativePath,
    SecretName,
    Slug,
    StrictBool,
    StrictFloat,
    StrictInt,
    Token,
    ToolName,
)

OPENROUTER = "openrouter"


class Brief(ConfigModel):
    """What the agent does and what it must produce."""

    instructions: RelativePath = Field(
        description="Path to the instructions file (the prompt), relative to the agent folder.",
        examples=["prompt.md"],
    )
    input: DottedRef = Field(
        description="Dotted reference to the Pydantic model the agent receives.",
        examples=["contracts.TechnicalRequirements"],
    )
    output: DottedRef = Field(
        description="Dotted reference to the Pydantic model the agent must produce.",
        examples=["contracts.TaskList"],
    )


class Routing(ConfigModel):
    """OpenRouter provider routing, to keep eval and baseline runs on the same upstreams."""

    only: Annotated[tuple[Slug, ...], UNIQUE] | None = Field(
        default=None,
        description="Upstream providers OpenRouter may use. Omit to allow any.",
        examples=[["anthropic"]],
    )
    allow_fallbacks: StrictBool = Field(
        default=True,
        description="Whether OpenRouter may fall back to providers outside `only`.",
    )


class ModelProfile(ConfigModel):
    """The model an agent uses and the settings it is called with."""

    provider: Slug = Field(
        description="Model provider, such as 'openrouter', 'anthropic' or 'openai'.",
        examples=[OPENROUTER],
    )
    id: Token = Field(
        description="Model identifier as the provider names it.",
        examples=["anthropic/claude-sonnet"],
    )
    temperature: Annotated[StrictFloat, Field(ge=0, le=2)] | None = Field(
        default=None, description="Sampling temperature. Omit for the provider default."
    )
    top_p: Annotated[StrictFloat, Field(ge=0, le=1)] | None = Field(
        default=None, description="Nucleus sampling probability. Omit for the provider default."
    )
    max_tokens: Annotated[StrictInt, Field(ge=1)] | None = Field(
        default=None, description="Maximum tokens to generate per call."
    )
    routing: Routing | None = Field(
        default=None, description="Provider routing. Only valid when `provider` is 'openrouter'."
    )

    @model_validator(mode="after")
    def _routing_needs_openrouter(self) -> Self:
        if self.routing is not None and self.provider != OPENROUTER:
            message = f"routing is only supported for provider '{OPENROUTER}'"
            raise_violations(
                "ModelProfile",
                [RuleViolation(("routing",), "routing_provider", message, self.provider)],
            )
        return self


class Permissions(ConfigModel):
    """What the runtime lets the agent reach. Anything not declared is unavailable."""

    network: StrictBool = Field(default=False, description="Whether the agent may use the network.")
    secrets: Annotated[tuple[SecretName, ...], UNIQUE] = Field(
        default=(),
        description="Names of environment variables the agent may read. Never their values.",
        examples=[["GITHUB_TOKEN"]],
    )


class Capabilities(ConfigModel):
    """What the agent can use: a model profile and a toolkit."""

    model: ModelProfile = Field(description="The model profile.")
    tools: Annotated[tuple[ToolName, ...], UNIQUE] = Field(
        default=(), description="Tools the agent may call."
    )
    permissions: Permissions = Field(
        default=Permissions(), description="Network and secret access. Denied unless declared."
    )


class QualityGate(ConfigModel):
    """What good looks like: the eval suite and the bar the agent's output must clear."""

    suite: RelativePath = Field(
        description="Path to the eval suite, relative to the agent folder.", examples=["evals"]
    )
    min_pass_rate: Annotated[StrictFloat, Field(ge=0, le=1)] = Field(
        description="Fraction of eval cases that must pass, from 0 to 1."
    )
    repeats: Annotated[StrictInt, Field(ge=1)] = Field(
        default=1, description="How many times each eval case is run."
    )


class Agent(ConfigModel):
    """A reusable worker, versioned as a single unit. Describes `agent.yaml`."""

    name: Slug = Field(
        description="The agent's name. Must match its folder name.", examples=["task-planner"]
    )
    brief: Brief = Field(description="Instructions and contracts.")
    capabilities: Capabilities = Field(description="Model profile and toolkit.")
    quality_gate: QualityGate = Field(description="Eval suite and thresholds.")
