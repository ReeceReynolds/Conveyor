"""Alpha's contracts. Beta defines a different `Shared` under the same module name."""

from pydantic import BaseModel
from shared_fields import ORIGIN


class Shared(BaseModel):
    """Alpha's version of the contract."""

    alpha_only: str
    origin: str = ORIGIN
