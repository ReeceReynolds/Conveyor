"""The committed JSON Schemas must match the models."""

import json
from pathlib import Path

import pytest

from conveyor.model.schema import DIALECT, SCHEMAS, json_schema, main, render_schema, write_schemas

SCHEMA_DIR = Path(__file__).parents[1] / "schemas"


@pytest.mark.parametrize("filename", sorted(SCHEMAS))
def test_committed_schema_matches_model(filename: str) -> None:
    committed = (SCHEMA_DIR / filename).read_text(encoding="utf-8")

    assert committed == render_schema(filename), f"{filename} is stale: run `make schemas`"


@pytest.mark.parametrize("filename", sorted(SCHEMAS))
def test_schema_is_draft_2020_12_and_strict(filename: str) -> None:
    schema = json_schema(filename)

    assert schema["$schema"] == DIALECT
    assert str(schema["$id"]).endswith(f"/schemas/{filename}")
    assert schema["additionalProperties"] is False


def test_schema_publishes_value_constraints() -> None:
    schema = json.loads(render_schema("factory.schema.json"))
    factory = schema["properties"]
    stage_kinds = factory["stages"]["items"]["oneOf"]

    assert factory["stages"]["minItems"] == 1
    assert factory["name"]["pattern"] == "^[a-z0-9]+(?:-[a-z0-9]+)*$"
    assert {kind["$ref"] for kind in stage_kinds} == {
        "#/$defs/AgentStage",
        "#/$defs/OperationStage",
        "#/$defs/HumanGateStage",
    }
    assert schema["$defs"]["Outcome"]["properties"]["scorers"]["uniqueItems"] is True


def test_write_schemas_and_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    written = write_schemas(tmp_path / "out")
    main([str(tmp_path / "cli")])

    assert sorted(path.name for path in written) == sorted(SCHEMAS)
    assert sorted(path.name for path in (tmp_path / "cli").iterdir()) == sorted(SCHEMAS)
    assert capsys.readouterr().out.count("wrote ") == len(SCHEMAS)
