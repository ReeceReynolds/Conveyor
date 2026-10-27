"""Shared base model and validation helpers for configuration models."""

from collections.abc import Sequence
from typing import LiteralString, NamedTuple, NoReturn

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

type Loc = tuple[str | int, ...]
"""A location inside a document: mapping keys and sequence indexes, outermost first."""


class ConfigModel(BaseModel):
    """Base for every configuration model: immutable and strict about unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RuleViolation(NamedTuple):
    """A rule broken by an otherwise well-typed value.

    Attributes:
        loc: Where the violation is, relative to the value being validated.
        error_type: A short machine-readable name for the rule.
        message: A human-readable explanation.
        value: The offending input.
    """

    loc: Loc
    error_type: LiteralString
    message: str
    value: object


def custom_error(error_type: LiteralString, message: str) -> PydanticCustomError:
    """Build a pydantic error whose message is already formatted.

    Pydantic treats messages as templates; passing ours as context keeps any braces in user
    input from being interpreted.

    Args:
        error_type: A short machine-readable name for the rule.
        message: The complete, human-readable message.

    Returns:
        The error, ready to raise from a validator.
    """
    return PydanticCustomError(error_type, "{detail}", {"detail": message})


def raise_violations(title: str, violations: Sequence[RuleViolation]) -> NoReturn:
    """Raise every violation at once as a single pydantic `ValidationError`.

    Raised from inside a validator, pydantic prefixes each `loc` with the validator's own
    location, so callers get a precise path for every problem rather than just the first.

    Args:
        title: The name of the model or type being validated.
        violations: The problems found; must not be empty.

    Raises:
        ValidationError: Always.
    """
    details: list[InitErrorDetails] = [
        {
            "type": custom_error(v.error_type, v.message),
            "loc": v.loc,
            "input": v.value,
        }
        for v in violations
    ]
    raise ValidationError.from_exception_data(title, details)
