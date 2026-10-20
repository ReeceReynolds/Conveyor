"""Conveyor: a foundation layer for building agent-driven software factories."""

from importlib.metadata import version

__all__ = ["__version__"]

__version__: str = version("conveyor-harness")
