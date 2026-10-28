"""A contract in a submodule, referenced as `contracts.review.Verdict`."""

from typing import Literal

from pydantic import BaseModel


class Finding(BaseModel):
    """A nested model, published under `$defs`."""

    message: str


class Verdict(BaseModel):
    """A contract with a nested model."""

    decision: Literal["approve", "reject"]
    findings: list[Finding] = []
