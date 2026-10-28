"""A model that imports but has no JSON Schema."""

from collections.abc import Callable

from pydantic import BaseModel


class Hook(BaseModel):
    """A field holding a callable cannot be expressed as JSON Schema."""

    run: Callable[[], None]
