"""A sibling module the contract package imports from the project root."""

from typing import Annotated

from pydantic import StringConstraints

type Label = Annotated[str, StringConstraints(min_length=1)]
