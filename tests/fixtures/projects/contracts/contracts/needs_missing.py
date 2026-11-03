"""A contract module whose own import of an uninstalled package fails."""

import importlib

importlib.import_module("not_installed_anywhere")
