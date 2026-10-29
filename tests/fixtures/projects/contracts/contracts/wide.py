"""A model whose JSON Schema holds a number JSON cannot carry exactly."""

from pydantic import BaseModel, Field


class Counter(BaseModel):
    """An int64 bound: valid Pydantic, but beyond what canonical JSON can hold exactly."""

    count: int = Field(ge=0, le=2**63 - 1)
