# tests

pytest suite for `src/conveyor`. One `test_<area>.py` per area; `test_repository.py` checks
the repository itself (docs, links, `AGENTS.md` files, skills, hooks, import-linter layers).

## Layout and fixtures

- `fixtures/agents/` and `fixtures/factories/`: one YAML file per case, named `valid-*.yaml`
  or `invalid-<rule>.yaml`. Tests glob `invalid-*.yaml`, so a new file is picked up
  automatically and its issues land in the snapshot.
- `fixtures/projects/<name>/`: whole projects (`agents/`, `factories/`) for folder checks and
  `conveyor validate`.
- `conftest.py`: `in_fixtures` runs a test from `fixtures/` so reported paths are short and
  stable; `example` is the `examples/prd-to-pr` reference factory, which must stay valid.
- Build throwaway projects under `tmp_path`; never write into the repository.
- CLI tests use Typer's `CliRunner`, not subprocesses.

## Snapshots and properties

- Reported issues and other structured output are asserted with inline-snapshot:
  `assert result == snapshot(...)`. Create or update values with
  `uv run pytest --inline-snapshot=fix` (or `=create`), then review the diff. Never edit a
  snapshot by hand to make a test pass.
- Hypothesis covers parsers, round trips (model → YAML → model) and the stage-graph rules
  (`test_properties.py`). Build strategies from parts, as that file does, rather than
  `from_regex` for nested data; a test keeps them in step with the real patterns.

## Determinism

- No network: pytest-socket disables sockets for every test (Unix sockets are allowed). A test
  that genuinely needs one, such as a future testcontainers test, opts in with
  `@pytest.mark.enable_socket`. Tests that call real model providers are marked
  `@pytest.mark.live`; they are deselected by default and run nightly under a spend cap.
- Model interactions use Pydantic AI's `TestModel` or recorded cassettes.
- Every test has a 60-second timeout (pytest-timeout).
- Order is random on every run (pytest-randomly), so tests must not depend on each other or on
  shared state. pytest prints `Using --randomly-seed=<n>` at the top; reproduce a failing order
  with `uv run pytest -p randomly --randomly-seed=<n>`, and confirm a suspected order problem
  with `-p no:randomly`.
- Coverage is branch coverage with a 90% floor (`make test`); `make quick` skips it.
