# Review hot spots

Where Conveyor has broken before, or where an ADR makes a promise the code must keep. Each line
is a question to ask of a diff that touches the area. Most came from the
[pre-M3 sweep](../../../docs/plans/sweep-2026-11-09.md) (F-xx) and the milestone 2 review
([plan](../../../docs/plans/milestone-2-agent-registry.md)). When a new class of bug turns up in
a review, add it here, or better, add the check that catches it.

## Input that a person or a hostile file controls

- YAML: does the change keep the loader's guards (duplicate keys, tags, merge keys, alias
  expansion cap, nesting depth, F-04) and keep ruamel.yaml inside `loader.py` (ADR 0009)? Are
  non-string keys handled (F-13)?
- Text: is anything split with `str.splitlines()` where `"\n"` is meant (U+2028, form feed and
  lone CR split too, F-10)? Can control characters reach the terminal (F-11)?
- Paths: what happens with `.`, `..`, absolute paths, symlinks or a linked `agents/` folder, an
  unreadable folder, names that differ only in case, and non-ASCII names in NFC and NFD form
  (F-12, S-1, S-3)?
- Contract modules are user code: does an exception, `SystemExit` or side effect at import,
  attribute access, `model_rebuild` or schema generation get reported as an issue rather than
  ending the process (ADR 0011, F-09, F-14)? Are imports isolated and done once per run (F-01)?

## Errors and messages

- Every problem a person can cause becomes a positioned `Issue` (`file:line:column`), never a
  traceback. Messages are lowercase, specific and quote the offending value
  ([`src/conveyor/model/AGENTS.md`](../../../src/conveyor/model/AGENTS.md)).
- Exceptions are specific and none is swallowed; a new `except` is no wider than it must be.
- Exit codes keep their meaning: "problems found" is not the same as a crash.

## Version identity and the registry

- Does anything new feed the snapshot or its content hash? Then it must be canonical and the same
  on every OS (ADR 0013): ordering, line endings, Unicode normalisation, case. A change here
  changes every version ID, so it needs explicit approval.
- Versions, runs and artifacts are immutable: nothing updates or deletes a stored version.
- Diffs are described in factory-model terms (blocks, components, primitives), and one change
  reads as one change in the summary.
- Author and message are printable and safe to show in `history` and `show`.

## Storage

- A schema change comes with an Alembic migration, tested on SQLite and Postgres
  (`uv run pytest -m postgres`).
- Concurrency: is the change safe with several processes and threads opening or publishing to
  the same store at once (`test_registry_concurrency.py`, F-05)? Is a write between storing an
  object and committing its row safe if the process dies there?
- Read-only commands must leave every file byte-identical, `-wal` files included (ADR 0015, F-08).
- sqlalchemy and alembic stay inside `conveyor.storage`.

## Performance that grows with the project

- Is there a query, import or serialisation per agent, per version or per file where one would do
  (F-01, F-06, F-07)?
- Is any algorithm quadratic in file size or line count (F-02)? Try the change on 1,000 agents or
  100,000 lines in your head.
- CLI start-up: heavy modules (registry, storage, SQLAlchemy) are imported inside the commands
  that need them, never at module level of `cli.py` (F-03).

## Security and containment

- Permissions and secrets are enforced by the runtime and sandbox, never by prompt text. A change
  that widens an agent's tools, paths, network or secrets is called out explicitly.
- No credential in agent definitions, snapshots, logs, traces, error messages or test fixtures.
- Untrusted text (issue or PR bodies, YAML values, model output) is never interpolated into a
  shell command, a SQL string or another agent's instructions.
- GitHub Actions: pinned to a full commit SHA with a version comment, least-privilege
  `permissions:`, no untrusted `${{ }}` expansion in `run:` steps, no `pull_request_target`
  checkout of PR code (zizmor checks some of this, not all).

## Tests

- New or changed behaviour has a test, and a bug fix's test fails without the fix.
- Tests assert behaviour through the public surface, not private helpers or the implementation's
  own arithmetic.
- Structured output uses inline-snapshot, and a changed snapshot is a change in behaviour that
  needs a reason: review its diff line by line.
- Parsers, round trips and the stage graph get a Hypothesis property where examples would miss
  cases.
- Deterministic: no network (`enable_socket` only with a reason), no dependence on order or
  shared state, temporary files under `tmp_path`, no wall-clock or locale assumptions
  ([`tests/AGENTS.md`](../../../tests/AGENTS.md)).
- Claims in docs or ADRs that the change relies on have a test. The sweep's test gaps (G-1 to
  G-7) are the known missing ones.

## UI

- Strict TypeScript without assertions or `any`; `import type` for types; tests next to the
  component; no edits to the build output ([`ui/AGENTS.md`](../../../ui/AGENTS.md)).
