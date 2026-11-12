"""Milestone 3's runtime dependencies and the import-linter contracts that confine them.

Each import runs in a fresh interpreter, so its side effects (registered warning filters,
patched modules, opened sockets) cannot leak into the rest of the suite, and so a module the
test process has already imported is still checked.
"""

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

# Each dependency Milestone 3 adds (ADRs 0018, 0020 and 0022): its top-level module and the
# submodules Conveyor will load (model providers, the Harness tools and its Docker sandbox).
NEW_DEPENDENCY_MODULES = (
    "dbos",
    "pydantic_ai",
    "pydantic_ai.models.openai",
    "pydantic_ai.models.anthropic",
    "pydantic_ai.providers.openrouter",
    "pydantic_ai_harness",
    "pydantic_ai_harness.shell",
    "pydantic_ai_harness.filesystem",
    "pydantic_ai_harness.docker_sandbox",
    "opentelemetry.sdk.trace",
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
)

# The forbidden contracts of ADR 0023: contract id to the modules it confines.
CONFINING_CONTRACTS = {
    "dbos-in-engine": ["dbos"],
    "agents-in-runtime-and-sandbox": ["pydantic_ai", "pydantic_ai_harness"],
    "telemetry-in-observability": ["opentelemetry"],
}

# Replaces every way to open a network socket or resolve a name with a recorder, imports the
# module named on the command line, and prints the attempts and any import error as JSON. Unix
# sockets stay allowed, as in the suite (`--allow-unix-socket`): `socketpair` is local, and
# asyncio needs it to create an event loop. Exits non-zero if anything was recorded.
_SOCKET_PROBE = """\
import _socket
import importlib
import json
import socket
import sys

attempts = []


def _record(name):
    def refuse(*args, **kwargs):
        attempts.append(name)
        raise OSError(f"{name} called during import")
    return refuse


def _is_unix(args, kwargs):
    family = args[0] if args else kwargs.get("family", -1)
    return family == socket.AF_UNIX


class _RecordingSocket(socket.socket):
    def __init__(self, *args, **kwargs):
        if not _is_unix(args, kwargs):
            attempts.append("socket.socket")
            raise OSError("socket.socket created during import")
        super().__init__(*args, **kwargs)


_raw_socket = _socket.socket


class _RecordingRawSocket(_raw_socket):
    # socket.socket.__init__ calls `_socket.socket.__init__(self, ...)` by name, so this must
    # delegate to the original class explicitly rather than through super().
    def __init__(self, *args, **kwargs):
        if not _is_unix(args, kwargs):
            attempts.append("_socket.socket")
            raise OSError("_socket.socket created during import")
        _raw_socket.__init__(self, *args, **kwargs)


socket.socket = _RecordingSocket
_socket.socket = _RecordingRawSocket
for _name in ("create_connection", "getaddrinfo", "gethostbyname"):
    setattr(socket, _name, _record(_name))

error = None
try:
    importlib.import_module(sys.argv[1])
except Exception as exc:
    error = repr(exc)
print(json.dumps({"attempts": attempts, "error": error}))
sys.exit(1 if attempts or error else 0)
"""


def _pyproject_text() -> str:
    return (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def _contracts() -> list[dict[str, object]]:
    config = tomllib.loads(_pyproject_text())
    contracts: list[dict[str, object]] = config["tool"]["importlinter"]["contracts"]
    return contracts


@pytest.mark.parametrize("module", NEW_DEPENDENCY_MODULES)
def test_dependency_imports_without_warnings(module: str) -> None:
    # `-W error` matches the suite's `filterwarnings = error`: a deprecation or resource warning
    # raised at import fails here, naming the module, rather than in whichever test imports it.
    result = subprocess.run(  # noqa: S603 -- runs this interpreter on a fixed module name
        [sys.executable, "-W", "error", "-c", f"import {module}"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"`import {module}` failed or warned under -W error:\n{result.stderr}\n"
        "Fix the cause or pin a version that imports cleanly; do not silence the warning "
        "globally in pyproject.toml."
    )


@pytest.mark.parametrize("module", NEW_DEPENDENCY_MODULES)
def test_dependency_import_opens_no_socket(module: str) -> None:
    result = subprocess.run(  # noqa: S603 -- runs this interpreter on a fixed script
        [sys.executable, "-c", _SOCKET_PROBE, module],
        capture_output=True,
        text=True,
        check=False,
    )

    lines = result.stdout.splitlines()
    report: dict[str, object] = json.loads(lines[-1]) if lines else {}
    assert result.returncode == 0, (
        f"`import {module}` tried to use the network (attempts: {report.get('attempts')}; "
        f"import error: {report.get('error')}). Conveyor must import its dependencies offline; "
        f"defer the call to when it is used.\n{result.stderr}"
    )


@pytest.mark.parametrize(("contract_id", "modules"), CONFINING_CONTRACTS.items())
def test_confining_contract_is_configured(contract_id: str, modules: list[str]) -> None:
    contracts = {str(contract["id"]): contract for contract in _contracts()}

    assert contract_id in contracts, (
        f"pyproject.toml has no import-linter contract with id {contract_id!r}. Restore it "
        "(ADR 0023)."
    )
    contract = contracts[contract_id]
    assert contract["type"] == "forbidden"
    assert contract["source_modules"] == ["conveyor.*"]
    assert contract["forbidden_modules"] == modules


def test_import_contracts_are_kept() -> None:
    lint_imports = shutil.which("lint-imports", path=str(Path(sys.executable).parent))
    assert lint_imports is not None, "lint-imports is not installed; run `make install`."

    result = subprocess.run(  # noqa: S603 -- runs the installed import-linter
        [lint_imports, "--no-cache"], cwd=ROOT, capture_output=True, text=True, check=False
    )

    output = " ".join(result.stdout.split())
    assert result.returncode == 0, f"`uv run lint-imports` failed:\n{result.stdout}"
    names = {str(contract["id"]): str(contract["name"]) for contract in _contracts()}
    for contract_id in CONFINING_CONTRACTS:
        assert f"{names[contract_id]} KEPT" in output, (
            f"lint-imports did not report contract {contract_id!r} as kept:\n{result.stdout}"
        )


def test_docker_tests_are_excluded_by_default() -> None:
    config = tomllib.loads(_pyproject_text())
    options: dict[str, list[str]] = config["tool"]["pytest"]["ini_options"]

    assert any(marker.startswith("docker:") for marker in options["markers"])
    selection = options["addopts"][options["addopts"].index("-m") + 1]
    assert "not docker" in selection, (
        "Tests marked `docker` need a Docker daemon and must be deselected by default: add "
        "`and not docker` to the `-m` expression in [tool.pytest.ini_options] addopts."
    )
