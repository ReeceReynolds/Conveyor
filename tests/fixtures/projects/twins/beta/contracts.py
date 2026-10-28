"""Beta's contracts. Alpha defines a different `Shared` under the same module name."""

from pydantic import BaseModel
from shared_fields import ORIGIN


class Shared(BaseModel):
    """Beta's version of the contract."""

    beta_only: int
    origin: str = ORIGIN
