"""Contracts for the fixture project's agents."""

from pydantic import BaseModel


class In(BaseModel):
    """What the agents receive."""

    text: str


class Out(BaseModel):
    """What the agents produce."""

    text: str
