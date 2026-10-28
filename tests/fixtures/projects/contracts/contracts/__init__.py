"""Contracts for the resolution fixture project: one of each thing a reference can name."""

from contract_helpers import Label
from pydantic import BaseModel


class Good(BaseModel):
    """A contract that resolves; its field type comes from a sibling module in the project."""

    label: Label


class NotAModel:
    """A class that is not a Pydantic model."""


value = 3
