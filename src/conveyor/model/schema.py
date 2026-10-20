"""Export the configuration models as JSON Schema 2020-12 documents.

The committed copies under `schemas/` give editors validation and autocomplete for
`agent.yaml` and factory files. Regenerate them with `make schemas`; a test fails if they
drift from the models.
"""

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from conveyor.model.agent import Agent
from conveyor.model.base import ConfigModel
from conveyor.model.factory import Factory

DIALECT = "https://json-schema.org/draft/2020-12/schema"
BASE_URL = "https://raw.githubusercontent.com/ReeceReynolds/Conveyor/main/schemas/"
SCHEMAS: Mapping[str, type[ConfigModel]] = {
    "agent.schema.json": Agent,
    "factory.schema.json": Factory,
}
"""Published schema file names and the model each describes."""


def json_schema(filename: str) -> dict[str, object]:
    """Build the JSON Schema published under `filename`.

    Args:
        filename: A key of `SCHEMAS`.

    Returns:
        The schema, with `$schema` and `$id` set.
    """
    return {"$schema": DIALECT, "$id": BASE_URL + filename, **SCHEMAS[filename].model_json_schema()}


def render_schema(filename: str) -> str:
    """Render the JSON Schema published under `filename` exactly as committed.

    Args:
        filename: A key of `SCHEMAS`.

    Returns:
        Indented JSON with a trailing newline.
    """
    return json.dumps(json_schema(filename), indent=2, ensure_ascii=False) + "\n"


def write_schemas(directory: Path) -> list[Path]:
    """Write every published schema into `directory`.

    Args:
        directory: Destination folder; created if missing.

    Returns:
        The files written.
    """
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename in SCHEMAS:
        path = directory / filename
        path.write_text(render_schema(filename), encoding="utf-8")
        written.append(path)
    return written


def main(argv: Sequence[str] | None = None) -> None:
    """Write the schemas to the directory given as the only argument (default `schemas`).

    Args:
        argv: Command-line arguments, excluding the program name.
    """
    args = sys.argv[1:] if argv is None else argv
    for path in write_schemas(Path(args[0] if args else "schemas")):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
