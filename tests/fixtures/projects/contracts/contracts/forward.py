"""A model with a forward reference that cannot be resolved at runtime."""

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from decimal import Decimal as Later


class Dangling(BaseModel):
    """`Later` exists only for type checkers, so Pydantic cannot finish building the model."""

    amount: Later
