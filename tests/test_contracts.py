"""Contract resolution and JSON Schema export, using the fixture projects and the example."""

import itertools
import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from inline_snapshot import snapshot
from pydantic import BaseModel, JsonValue, ValidationError
from pydantic_core import SchemaError

from conveyor.contracts import (
    ContractResolutionError,
    contract_schema,
    resolve_contract,
    resolve_contract_schemas,
)
from conveyor.contracts.resolver import RESERVED_MODULES, describe, first_line
from conveyor.contracts.schema import DIALECT, inexact_value
from conveyor.model import load_agent_file
from conveyor.registry.canonical import CanonicalFormError, canonical_json

FIXTURES = Path(__file__).parent / "fixtures" / "projects"
PROJECT = FIXTURES / "contracts"
ALPHA = FIXTURES / "twins" / "alpha"
BETA = FIXTURES / "twins" / "beta"


@pytest.fixture(autouse=True)
def import_state_is_restored() -> Iterator[None]:
    """Every test must leave `sys.path` and the fixture projects' modules as it found them."""
    path = list(sys.path)
    modules = set(sys.modules)
    yield
    assert sys.path == path
    leaked = {
        name
        for name in set(sys.modules) - modules
        if name.partition(".")[0] in {"contracts", "contract_helpers", "shared_fields", "here"}
    }
    assert not leaked


def _reason(root: Path, ref: str) -> str:
    with pytest.raises(ContractResolutionError) as caught:
        resolve_contract(root, ref)
    assert caught.value.ref == ref
    assert str(caught.value) == f"cannot resolve contract {ref!r}: {caught.value.reason}"
    return caught.value.reason


def test_resolves_package_attribute_with_sibling_import() -> None:
    model = resolve_contract(PROJECT, "contracts.Good")

    assert issubclass(model, BaseModel)
    assert model.__name__ == "Good"
    assert model.model_validate({"label": "x"}).model_dump() == {"label": "x"}


def test_resolves_deeper_dotted_modules() -> None:
    model = resolve_contract(PROJECT, "contracts.review.Verdict")

    assert model.__name__ == "Verdict"
    assert model.__module__ == "contracts.review"


def test_resolves_a_relative_project_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURES)

    assert resolve_contract(Path("contracts"), "contracts.Good").__name__ == "Good"


def test_every_failure_is_reported_precisely() -> None:
    refs = [
        "TaskList",
        "contracts..Good",
        "os.PathLike",
        "conveyor.model.Agent",
        "schemas.Request",
        "contracts.Absent",
        "contracts.missing.Thing",
        "contracts.review.Verdict.extra",
        "contracts.NotAModel",
        "contracts.value",
        "contracts.BaseModel",
        "contracts.broken.Anything",
        "contracts.needs_missing.Thing",
        "contracts.forward.Dangling",
    ]

    assert {ref: _reason(PROJECT, ref) for ref in refs} == snapshot(
        {
            "TaskList": "must be a dotted reference like 'contracts.TaskList'",
            "contracts..Good": "must be a dotted reference like 'contracts.TaskList'",
            "os.PathLike": "module name 'os' is reserved for the standard library or Conveyor",
            "conveyor.model.Agent": (
                "module name 'conveyor' is reserved for the standard library or Conveyor"
            ),
            "schemas.Request": (
                "no module 'schemas' in the project (expected schemas.py or a schemas/ package)"
            ),
            "contracts.Absent": "module 'contracts' has no attribute 'Absent'",
            "contracts.missing.Thing": "no module 'contracts.missing' in the project",
            "contracts.review.Verdict.extra": "no module 'contracts.review.Verdict' in the project",
            "contracts.NotAModel": (
                "'NotAModel' is a class but not a Pydantic model (it must subclass BaseModel)"
            ),
            "contracts.value": "'value' is not a class but a value of type 'int'",
            "contracts.BaseModel": (
                "'BaseModel' is pydantic.BaseModel itself; name a model defined from it"
            ),
            "contracts.broken.Anything": (
                "importing 'contracts.broken' raised RuntimeError: database not configured"
            ),
            "contracts.needs_missing.Thing": (
                "importing 'contracts.needs_missing' raised ModuleNotFoundError: "
                "No module named 'not_installed_anywhere'"
            ),
            "contracts.forward.Dangling": (
                "'Dangling' is not fully defined: name 'Later' is not defined"
            ),
        }
    )


def test_module_found_outside_the_project_is_rejected(tmp_path: Path) -> None:
    # `here` exists in the project but is a namespace package whose code lives elsewhere.
    (tmp_path / "project" / "here").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "here").mkdir(parents=True)
    (elsewhere / "here" / "__init__.py").write_text("from pydantic import BaseModel as Model\n")
    sys.path.append(str(elsewhere))
    try:
        reason = _reason(tmp_path / "project", "here.Model")
    finally:
        sys.path.remove(str(elsewhere))

    assert reason == "module 'here' was imported from outside the project"


def test_errors_raised_by_project_code_are_reported(tmp_path: Path) -> None:
    (tmp_path / "contracts.py").write_text("def __getattr__(name):\n    raise LookupError\n")
    (tmp_path / "syntax.py").write_text("class (\n")

    assert _reason(tmp_path, "contracts.Anything") == "reading 'Anything' raised LookupError"
    assert _reason(tmp_path, "syntax.Model").startswith("importing 'syntax' raised SyntaxError: ")


def test_sys_exit_in_project_code_is_reported(tmp_path: Path) -> None:
    (tmp_path / "contracts.py").write_text("import sys\nsys.exit(3)\n")

    assert _reason(tmp_path, "contracts.X") == "importing 'contracts' raised SystemExit: 3"


def test_projects_are_isolated_from_each_other() -> None:
    alpha = resolve_contract(ALPHA, "contracts.Shared")
    beta = resolve_contract(BETA, "contracts.Shared")
    alpha_again = resolve_contract(ALPHA, "contracts.Shared")

    assert set(alpha.model_fields) == {"alpha_only", "origin"}
    assert set(beta.model_fields) == {"beta_only", "origin"}
    # Each project's sibling module was imported from its own root, not reused from the other.
    assert alpha.model_fields["origin"].default == "alpha"
    assert beta.model_fields["origin"].default == "beta"
    # Resolving again re-imports the module rather than reusing the first import.
    assert alpha_again is not alpha
    assert alpha_again.model_json_schema() == alpha.model_json_schema()
    assert "contracts" not in sys.modules
    assert str(ALPHA) not in sys.path
    assert str(BETA) not in sys.path


def test_modules_already_imported_under_the_same_name_are_restored(tmp_path: Path) -> None:
    (tmp_path / "contracts.py").write_text(
        "from pydantic import BaseModel\nclass A(BaseModel): ...\n"
    )
    sentinel = type(sys)("contracts")
    sub = type(sys)("contracts.sub")
    sys.modules["contracts"] = sentinel
    sys.modules["contracts.sub"] = sub
    try:
        resolve_contract(tmp_path, "contracts.A")

        assert sys.modules["contracts"] is sentinel
        assert sys.modules["contracts.sub"] is sub
    finally:
        del sys.modules["contracts"], sys.modules["contracts.sub"]


def test_packages_merely_stored_in_the_project_stay_imported(tmp_path: Path) -> None:
    # Like a virtual environment inside the project: on `sys.path`, but not the project root.
    site = tmp_path / ".venv" / "site-packages"
    site.mkdir(parents=True)
    (site / "vendored_dep.py").write_text("VALUE = 1\n")
    (tmp_path / "contracts.py").write_text(
        "import sys, types\n"
        "import vendored_dep\n"
        "sys.modules['specless_dep'] = types.ModuleType('specless_dep')\n"
        "from pydantic import BaseModel\n"
        "class A(BaseModel): ...\n"
    )
    sys.path.append(str(site))
    try:
        resolve_contract(tmp_path, "contracts.A")

        assert "vendored_dep" in sys.modules
        assert "specless_dep" in sys.modules
    finally:
        sys.path.remove(str(site))
        del sys.modules["vendored_dep"], sys.modules["specless_dep"]


def test_edits_between_resolutions_are_seen(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts.py"
    contracts.write_text("from pydantic import BaseModel\nclass A(BaseModel):\n    one: int\n")
    first = resolve_contract(tmp_path, "contracts.A")
    (tmp_path / "contracts.py").unlink()
    package = tmp_path / "contracts"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from pydantic import BaseModel\nclass A(BaseModel):\n    two: int\n"
    )
    second = resolve_contract(tmp_path, "contracts.A")

    assert set(first.model_fields) == {"one"}
    assert set(second.model_fields) == {"two"}


def test_no_bytecode_is_written_into_the_project(tmp_path: Path) -> None:
    (tmp_path / "contracts.py").write_text(
        "from pydantic import BaseModel\nclass A(BaseModel): ...\n"
    )

    resolve_contract(tmp_path, "contracts.A")

    assert not (tmp_path / "__pycache__").exists()


def test_reserved_modules_cover_what_the_resolver_needs() -> None:
    assert {"conveyor", "pydantic", "pydantic_core", "json", "typing"} <= RESERVED_MODULES


# Identifiers and junk, with names that exist in the fixture project common enough to resolve.
_parts = st.sampled_from(
    ["contracts", "review", "Good", "Verdict", "broken", "value", "os"]
) | st.text(st.characters(codec="utf-8", exclude_categories=("Cs",)), max_size=6)


@given(st.lists(_parts, max_size=4).map(".".join))
def test_arbitrary_refs_resolve_or_raise_resolution_error(ref: str) -> None:
    outcome: type[BaseModel] | ContractResolutionError
    try:
        outcome = resolve_contract(PROJECT, ref)
    except ContractResolutionError as error:
        outcome = error

    if isinstance(outcome, ContractResolutionError):
        assert outcome.ref == ref
        assert "\n" not in str(outcome)
    else:
        assert issubclass(outcome, BaseModel)
    assert str(PROJECT) not in sys.path
    assert not any(name.partition(".")[0] == "contracts" for name in sys.modules)


def test_schema_is_draft_2020_12_with_nested_defs() -> None:
    schema = contract_schema(resolve_contract(PROJECT, "contracts.review.Verdict"))

    assert schema == snapshot(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "Finding": {
                    "description": "A nested model, published under `$defs`.",
                    "properties": {"message": {"title": "Message", "type": "string"}},
                    "required": ["message"],
                    "title": "Finding",
                    "type": "object",
                }
            },
            "description": "A contract with a nested model.",
            "properties": {
                "decision": {"enum": ["approve", "reject"], "title": "Decision", "type": "string"},
                "findings": {
                    "default": [],
                    "items": {"$ref": "#/$defs/Finding"},
                    "title": "Findings",
                    "type": "array",
                },
            },
            "required": ["decision"],
            "title": "Verdict",
            "type": "object",
        }
    )


def test_schema_is_deterministic_and_a_fresh_copy() -> None:
    model = resolve_contract(PROJECT, "contracts.review.Verdict")
    first = contract_schema(model)
    first["title"] = "mutated"
    second = contract_schema(model)

    assert second["title"] == "Verdict"
    assert json.dumps(second) == json.dumps(contract_schema(model))
    assert next(iter(second)) == "$schema"
    assert second["$schema"] == DIALECT


def test_model_without_json_schema_is_a_resolution_error() -> None:
    model = resolve_contract(PROJECT, "contracts.hooks.Hook")

    with pytest.raises(ContractResolutionError) as caught:
        contract_schema(model)

    assert str(caught.value) == snapshot(
        "cannot resolve contract 'contracts.hooks.Hook': no JSON Schema can be generated for "
        "it: PydanticInvalidForJsonSchema: Cannot generate a JsonSchema for "
        "core_schema.CallableSchema"
    )


def test_schema_with_a_value_json_cannot_carry_is_a_resolution_error() -> None:
    with pytest.raises(ContractResolutionError) as caught:
        resolve_contract_schemas(PROJECT, ["contracts.wide.Counter"])

    assert str(caught.value) == snapshot(
        "cannot resolve contract 'contracts.wide.Counter': its JSON Schema has a value JSON "
        "cannot carry exactly: integer 9223372036854775807 exceeds 2**53 - 1 at "
        "/properties/count/maximum"
    )


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ({"a": [1, 2**53 - 1, -(2**53 - 1), 1e20, True, None, "x"]}, None),
        ({"a": [0, 2**53]}, "integer 9007199254740992 exceeds 2**53 - 1 at /a/1"),
        (-(2**53), "integer -9007199254740992 exceeds 2**53 - 1"),
        ({"x": {"y": float("nan")}}, "nan is not a JSON number at /x/y"),
        ([float("-inf")], "-inf is not a JSON number at /0"),
        ({"a/b~c": 2**60}, "integer 1152921504606846976 exceeds 2**53 - 1 at /a~1b~0c"),
        ({"k": "\ud800"}, "string has a lone surrogate at /k"),
        ({"\ud800": 1}, "string has a lone surrogate"),
    ],
)
def test_inexact_value_names_the_value_and_its_pointer(
    value: JsonValue, problem: str | None
) -> None:
    assert inexact_value(value) == problem


_JSON = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**60), max_value=2**60)
    | st.floats()
    | st.text(alphabet=st.characters(min_codepoint=0xD7F0, max_codepoint=0xE010)),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=3), children, max_size=4)
    ),
    max_leaves=12,
)


@given(_JSON)
def test_inexact_value_agrees_with_the_registrys_canonical_form(value: JsonValue) -> None:
    # The check exists so `validate` refuses exactly what content IDs cannot be computed for.
    try:
        canonical_json(value)
    except CanonicalFormError:
        assert inexact_value(value) is not None
    else:
        assert inexact_value(value) is None


def test_resolve_contract_schemas_dedupes_and_keeps_order() -> None:
    schemas = resolve_contract_schemas(
        PROJECT, ["contracts.review.Verdict", "contracts.Good", "contracts.review.Verdict"]
    )

    assert list(schemas) == ["contracts.review.Verdict", "contracts.Good"]
    assert schemas["contracts.Good"]["title"] == "Good"


def test_resolve_contract_schemas_reports_the_ref_as_written() -> None:
    with pytest.raises(ContractResolutionError) as caught:
        resolve_contract_schemas(PROJECT, ["contracts.Good", "contracts.hooks.Hook"])

    assert caught.value.ref == "contracts.hooks.Hook"
    assert caught.value.reason.startswith("no JSON Schema can be generated for it: ")


def test_error_summaries_are_one_line() -> None:
    nested = (
        "Error building validator:\n  SchemaError: regex parse error\nlook-around is unsupported"
    )

    assert describe(ValueError("first\nsecond")) == "ValueError: first"
    assert describe(KeyError()) == "KeyError"
    assert first_line(ValueError("  \n")) == ""
    assert first_line(SchemaError(nested)) == "look-around is unsupported"


# The order agents run in prd-to-pr, each handing its output to the next.
CHAIN = ["requirements-analyst", "task-planner", "implementer", "code-reviewer"]


def test_example_agents_chain_their_contracts(example: Path) -> None:
    briefs = [load_agent_file(example / "agents" / name / "agent.yaml").brief for name in CHAIN]

    assert [brief.input for brief in briefs] == [
        "contracts.PRD",
        "contracts.TechnicalRequirements",
        "contracts.TaskList",
        "contracts.CodeChanges",
    ]
    for upstream, downstream in itertools.pairwise(briefs):
        assert upstream.output == downstream.input
    assert briefs[-1].output == "contracts.ReviewVerdict"

    schemas = resolve_contract_schemas(
        example, [ref for brief in briefs for ref in (brief.input, brief.output)]
    )
    assert len(schemas) == 5
    for schema in schemas.values():
        assert schema["additionalProperties"] is False


SHA = "0" * 40
TASK = {
    "id": "TASK-1",
    "title": "Add the endpoint",
    "description": "Add GET /export in api/export.py.",
    "acceptance_criteria": ["returns CSV"],
    "requirements": ["REQ-1"],
}
CHANGE = {"path": "api/export.py", "kind": "added", "summary": "New endpoint."}
MAJOR = {"severity": "major", "path": "api/export.py", "line": 3, "message": "No auth check."}


def _example_error(example: Path, name: str, data: object) -> str | None:
    """Validate `data` against an example contract; return the first error message, if any."""
    model = resolve_contract(example, f"contracts.{name}")
    try:
        model.model_validate(data)
    except ValidationError as error:
        return error.errors()[0]["msg"]
    return None


@pytest.mark.parametrize(
    ("name", "data", "error"),
    [
        ("TaskList", {"tasks": [TASK, {**TASK, "id": "TASK-2", "depends_on": ["TASK-1"]}]}, None),
        ("TaskList", {"tasks": [TASK, TASK]}, "Value error, duplicate task id 'TASK-1'"),
        (
            "TaskList",
            {"tasks": [{**TASK, "depends_on": ["TASK-2"]}, {**TASK, "id": "TASK-2"}]},
            "Value error, task 'TASK-1' depends on 'TASK-2', which is not listed before it",
        ),
        ("TaskList", {"tasks": [{**TASK, "id": "task one"}]}, "String should match pattern"),
        ("TaskList", {"tasks": [TASK], "notes": "x"}, "Extra inputs are not permitted"),
        (
            "CodeChanges",
            {
                "branch": "feat/export",
                "base_commit": SHA,
                "head_commit": SHA,
                "summary": "Adds export.",
                "files": [CHANGE, CHANGE],
                "tasks_completed": ["TASK-1"],
            },
            "Value error, file 'api/export.py' is listed more than once",
        ),
        ("ReviewVerdict", {"decision": "approve", "summary": "Good."}, None),
        (
            "ReviewVerdict",
            {"decision": "reject", "summary": "Bad.", "findings": [MAJOR]},
            None,
        ),
        (
            "ReviewVerdict",
            {"decision": "reject", "summary": "Meh.", "findings": [{**MAJOR, "severity": "nit"}]},
            "Value error, a rejection must include at least one 'blocker' or 'major' finding",
        ),
        (
            "ReviewVerdict",
            {"decision": "approve", "summary": "Fine.", "findings": [MAJOR]},
            "Value error, an approval cannot include 'blocker' or 'major' findings",
        ),
        (
            "ReviewVerdict",
            {"decision": "approve", "summary": "Fine.", "findings": [{**MAJOR, "path": None}]},
            "Value error, a finding with a line must also give its path",
        ),
        ("PRD", {"title": "  ", "problem": "p", "goals": ["g"]}, "String should have at least"),
    ],
)
def test_example_contracts_enforce_their_rules(
    example: Path, name: str, data: object, error: str | None
) -> None:
    message = _example_error(example, name, data)

    if error is None:
        assert message is None
    else:
        assert message is not None
        assert message.startswith(error)


@pytest.mark.parametrize(
    ("path", "valid"),
    [
        ("api/export.py", True),
        (".github/workflows/ci.yml", True),
        ("..hidden/x", True),
        ("a/...", True),
        ("/etc/passwd", False),
        ("../outside", False),
        ("a/../../b", False),
        ("a/./b", False),
        ("a//b", False),
        ("a\\b", False),
        ("", False),
    ],
)
def test_example_repo_paths_stay_inside_the_repository(
    example: Path, path: str, valid: bool
) -> None:
    message = _example_error(example, "FileChange", {**CHANGE, "path": path})

    assert (message is None) == valid
