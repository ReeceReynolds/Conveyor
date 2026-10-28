# 0013. Agent version identity: canonical snapshots hashed with RFC 8785

- Status: Accepted
- Date: 2026-10-28

## Context

Every later capability keys off agent versions: runs pin them, change sets are diffs between
them, and eval baselines compare them. A version needs an ID that depends only on what the
agent *is*, so that the same agent gets the same ID on every machine and operating system, and
any change that could alter its behaviour gets a new one. That needs three decisions: what is
part of an agent's identity, how it is written down as bytes, and what the ID means.

The hard part is the bytes. JSON objects have no key order, and Pydantic's JSON Schemas keep
field declaration order, so serialising "the same" schema can give different text. Numbers
can be written many ways (`1`, `1.0`, `1e0`). Text files checked out on Windows usually have
CRLF line endings, and some editors add a byte order mark.

## Decision

**An agent version is an `AgentSnapshot`** (`conveyor.registry`), a frozen model holding:

| Part | Content |
|---|---|
| `format` | The version of the canonical form, currently `1` |
| `agent` | The parsed `agent.yaml` (an `Agent`), including the file names it refers to |
| `instructions` | The text of the instructions file |
| `input_schema`, `output_schema` | The JSON Schemas of the Brief's contracts, as resolved ([ADR 0011](0011-contract-resolution.md)) |
| `eval_files` | Every file of the eval suite: POSIX path relative to the suite, sha256 and text, sorted by path |

Not part of identity: where the agent folder is, the YAML's comments, formatting and key
order (only the parsed model counts), the Python source of the contracts (only their schemas
count), file timestamps and permissions, line endings, a leading byte order mark, and tooling
files in the eval suite: names starting with `.` (`.gitkeep`, `.DS_Store`, `.pytest_cache/`),
`__pycache__/` folders and `*.pyc` files. Who published a version, when and why are recorded
by the registry alongside the version, not in it. The agent's name is part of identity.

**Reading files is strict.** Instructions and eval files must be regular UTF-8 text files.
CRLF becomes LF and a leading byte order mark is dropped, so a Windows checkout hashes the
same as a Linux one. Symbolic links are refused rather than followed: a link would bring
content from outside the agent folder into its identity, and Git on Windows checks links out
as small text files, so one commit would hash two ways.

**The canonical form is RFC 8785, the JSON Canonicalization Scheme (JCS)**, applied to the
snapshot's JSON (`model_dump(mode="json")`) with the
[`rfc8785`](https://pypi.org/project/rfc8785/) package. JCS sorts object keys by UTF-16 code
unit, removes insignificant whitespace, writes strings with minimal escaping and numbers as
ECMAScript does (`0.0` and `0` are both `0`), and outputs UTF-8. Values JSON cannot carry
exactly (NaN, infinities, integers beyond ±(2⁵³−1)) are rejected when the snapshot is built,
so every snapshot has a canonical form. `snapshot_from_bytes` reads it back and refuses bytes
that are not exactly canonical.

**The content ID is the sha256 of the canonical bytes**, as 64 lowercase hex characters, and
`short_id` is its first 12 (48 bits) for display.

**Content IDs identify content, not versions.** Reverting an agent to earlier content
produces that content's old ID again, but it is a new version: the storage layer
([ADR 0012](0012-storage.md)) gives each publish a sequence number (`v1`, `v2`, ...) and a
parent, and several versions can share a content ID. Publishing content identical to the
latest version is a no-op.

**`format` versions the canonical form.** Any change to what a snapshot contains or how it is
serialised (a new `agent.yaml` field, even an optional one, since it serialises as `null`; a
new snapshot part; a different normalisation) changes every ID and bumps `format`, and a test pins the ID of a fixture agent so that such a change cannot
happen unnoticed. Snapshots of different formats are never compared by ID.

## Alternatives considered

- **`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`**
  — no dependency, and stable within one Python version. But it is defined by CPython's
  behaviour rather than a specification: float formatting (`repr`) and key ordering (code
  points, not UTF-16 units) differ from what any other language would produce, so a TypeScript
  UI or a Go tool could not recompute an ID. It also writes `0.0` and `0` differently, so a
  schema's `"minimum": 0` and `0.0` would hash differently despite meaning the same.
- **Hashing the agent folder as files (a Git tree hash)** — simple, but the YAML's comments
  and formatting would count, contract schemas live outside the folder, and line endings and
  tooling files would leak in.
- **Hashing each part separately (a Merkle tree)** — would let diffs skip unchanged parts, but
  snapshots are small (kilobytes), so one hash over one document is simpler and enough.
- **Other JCS implementations** — `canonicaljson` implements Matrix's canonical JSON, not
  RFC 8785; `jcs` has had no release since 2022. `rfc8785` is maintained by Trail of Bits,
  Apache-2.0, pure Python with no runtime dependencies, and typed (`py.typed`).

## Consequences

The same agent hashes the same on Linux, macOS and Windows, and IDs can be recomputed from a
stored snapshot in any language with a JCS library. Conveyor gains one small runtime
dependency. Diffs (`diff_snapshots`) compare snapshots as JSON values, so a change is reported
exactly when the content ID changes. Adding a field to `agent.yaml` now also means extending the
diff and its wording, deciding whether to bump `format`, and updating the pinned fixture ID; a
test listing every snapshot field fails until that is done.
