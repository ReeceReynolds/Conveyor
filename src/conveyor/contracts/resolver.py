"""Resolve contract references such as `contracts.TaskList` to the Pydantic models they name.

Every part of a reference but the last names a module and the last names an attribute of it,
so `contracts.review.Verdict` is `Verdict` in `contracts/review.py`. The top-level module is
looked up in the project root only (`<root>/contracts.py` or `<root>/contracts/`), never
elsewhere on `sys.path`, so a reference cannot silently resolve to an installed package.

Resolving imports the project's code, so each call is isolated (see ADR 0011). While it runs,
the project root is first on `sys.path`, no bytecode is written into the project, and any
module already imported under the same top-level name is set aside. Afterwards every module
loaded from the project root is dropped and `sys.path` and the set-aside modules are restored,
so resolving `contracts.X` for two projects in one process imports each project's own code.

A contract module may import sibling modules from its project root. A sibling whose name is
already imported from elsewhere (a third-party package of the same name, say) resolves to that
module instead, as it would in any Python process, so shared helpers are best kept inside the
contract package.
"""

import importlib
import sys
import threading
from collections.abc import Generator
from contextlib import contextmanager
from importlib.machinery import ModuleSpec, all_suffixes
from pathlib import Path
from types import ModuleType

from pydantic import BaseModel
from pydantic_core import SchemaError

RESERVED_MODULES = frozenset(
    {
        "__main__",
        "annotated_types",
        "conveyor",
        "pydantic",
        "pydantic_core",
        "typing_extensions",
        "typing_inspection",
        *sys.stdlib_module_names,
    }
)
"""Top-level names a contract module may not use.

Resolving sets aside any module already imported under the reference's top-level name, so it
must never be one the standard library, Conveyor or Pydantic relies on while resolving.
"""

# Resolution swaps process-wide import state, so concurrent calls must not interleave.
_LOCK = threading.Lock()


class ContractResolutionError(Exception):
    """Raised when a contract reference does not resolve to a usable Pydantic model.

    `str(error)` names the reference and the reason on one line, ready to report as an `Issue`.

    Attributes:
        ref: The reference that failed to resolve.
        reason: Why it failed.
    """

    def __init__(self, ref: str, reason: str) -> None:
        """Create the error.

        Args:
            ref: The reference that failed to resolve.
            reason: Why it failed, as a lowercase clause.
        """
        self.ref = ref
        self.reason = reason
        super().__init__(f"cannot resolve contract {ref!r}: {reason}")


def resolve_contract(project_root: Path, ref: str) -> type[BaseModel]:
    """Import the Pydantic model a contract reference names, from the project's own modules.

    Args:
        project_root: The folder holding `agents/`, `factories/` and the contract modules.
        ref: A dotted reference such as `contracts.TaskList` or `contracts.review.Verdict`.

    Returns:
        The model class, fully built so its JSON Schema can be generated outside the project.

    Raises:
        ContractResolutionError: If the reference is malformed or names a reserved module, its
            module is not in the project or fails to import, or the attribute is missing or is
            not a Pydantic model class.
    """
    parts = ref.split(".")
    if len(parts) == 1 or not all(part.isidentifier() for part in parts):
        raise ContractResolutionError(ref, "must be a dotted reference like 'contracts.TaskList'")
    top = parts[0]
    if top in RESERVED_MODULES:
        reason = f"module name {top!r} is reserved for the standard library or Conveyor"
        raise ContractResolutionError(ref, reason)
    root = project_root.resolve()
    module_name, _, attribute = ref.rpartition(".")
    if not _in_root(root, top):
        reason = f"no module {top!r} in the project (expected {top}.py or a {top}/ package)"
        raise ContractResolutionError(ref, reason)
    with _LOCK, _isolated_imports(root, top):
        module = _import(ref, module_name)
        if not _from_root(module, root):
            reason = f"module {module_name!r} was imported from outside the project"
            raise ContractResolutionError(ref, reason)
        model = _model(ref, module, attribute)
        # Forward references resolve against the module, which is only importable in here.
        if not model.__pydantic_complete__:
            try:
                model.model_rebuild(raise_errors=True)
            except Exception as error:
                reason = f"{attribute!r} is not fully defined: {first_line(error)}"
                raise ContractResolutionError(ref, reason) from error
    return model


def _import(ref: str, module_name: str) -> ModuleType:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        # Tell "the referenced module does not exist" apart from an import inside it failing.
        if error.name is not None and _within(module_name, error.name):
            reason = f"no module {error.name!r} in the project"
            raise ContractResolutionError(ref, reason) from error
        raise ContractResolutionError(ref, _raised(f"importing {module_name!r}", error)) from error
    except (Exception, SystemExit) as error:
        # Project code is arbitrary: report whatever it raises, even `sys.exit()`.
        raise ContractResolutionError(ref, _raised(f"importing {module_name!r}", error)) from error


def _model(ref: str, module: ModuleType, attribute: str) -> type[BaseModel]:
    try:
        value: object = getattr(module, attribute)
    except AttributeError:
        reason = f"module {module.__name__!r} has no attribute {attribute!r}"
        raise ContractResolutionError(ref, reason) from None
    except Exception as error:
        # A module-level `__getattr__` is project code too.
        raise ContractResolutionError(ref, _raised(f"reading {attribute!r}", error)) from error
    if value is BaseModel:
        reason = f"{attribute!r} is pydantic.BaseModel itself; name a model defined from it"
    elif isinstance(value, type) and issubclass(value, BaseModel):
        return value
    elif isinstance(value, type):
        reason = f"{attribute!r} is a class but not a Pydantic model (it must subclass BaseModel)"
    else:
        reason = f"{attribute!r} is not a class but a value of type {type(value).__name__!r}"
    raise ContractResolutionError(ref, reason)


def _in_root(root: Path, top: str) -> bool:
    """Whether `root` holds a module or package named `top`, without importing anything."""
    if (root / top).is_dir():
        return True
    return any((root / f"{top}{suffix}").is_file() for suffix in all_suffixes())


@contextmanager
def _isolated_imports(root: Path, top: str) -> Generator[None]:
    """Import from `root` first, then drop what was imported from it and restore the rest."""
    saved_path = list(sys.path)
    saved_bytecode = sys.dont_write_bytecode
    set_aside = {name: module for name, module in sys.modules.items() if _within(name, top)}
    for name in set_aside:
        del sys.modules[name]
    before = set(sys.modules)
    # A finder cached for the root may hold a stale listing of its files.
    _forget_finders(root)
    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        for name, module in list(sys.modules.items()):
            if name not in before and (_within(name, top) or _from_root(module, root)):
                del sys.modules[name]
        sys.modules.update(set_aside)
        sys.path[:] = saved_path
        _forget_finders(root)
        sys.dont_write_bytecode = saved_bytecode


def _forget_finders(root: Path) -> None:
    """Drop the import system's cached finders for `root` and the folders inside it."""
    for entry in list(sys.path_importer_cache):
        if Path(entry).is_relative_to(root):
            del sys.path_importer_cache[entry]


def _from_root(module: object, root: Path) -> bool:
    """Whether a module was found through `root` as a `sys.path` entry.

    Checking only that its file is somewhere under `root` would also match a virtual
    environment inside the project, whose packages must stay imported.
    """
    spec: object = getattr(module, "__spec__", None)
    if not isinstance(spec, ModuleSpec):
        return False
    top = spec.name.partition(".")[0]
    locations = [spec.origin] if spec.origin else []
    locations.extend(spec.submodule_search_locations or ())
    for location in locations:
        path = Path(location)
        if not path.is_relative_to(root):
            continue
        first, *rest = path.relative_to(root).parts or ("",)
        # The `contracts/` package folder, or a module file such as `contracts.py`.
        if first == top or (not rest and first.partition(".")[0] == top):
            return True
    return False


def _within(name: str, package: str) -> bool:
    """Whether module `name` is `package` itself or one of its submodules."""
    return name == package or name.startswith(f"{package}.")


def _raised(action: str, error: BaseException) -> str:
    return f"{action} raised {describe(error)}"


def describe(error: BaseException) -> str:
    """Summarise an exception on one line, as its type and the first line of its message.

    Args:
        error: The exception.

    Returns:
        `Type: message`, or just `Type` when the message is empty.
    """
    detail = first_line(error)
    kind = type(error).__name__
    return f"{kind}: {detail}" if detail else kind


def first_line(error: BaseException) -> str:
    """The line of an exception's message that says what went wrong.

    Messages can span lines, which would make an `Issue` span them too. Most put the problem
    first (Pydantic appends a documentation link below it); pydantic-core's `SchemaError`
    nests "Error building ... validator:" lines and puts the cause last.

    Args:
        error: The exception.

    Returns:
        That line, stripped; empty when the message is.
    """
    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[-1] if isinstance(error, SchemaError) else lines[0]
