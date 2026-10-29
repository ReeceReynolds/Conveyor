# Conveyor

[![CI](https://github.com/ReeceReynolds/Conveyor/actions/workflows/ci.yml/badge.svg)](https://github.com/ReeceReynolds/Conveyor/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

An open-source foundation layer for **harness engineering**: building agent-driven software
factories.

> Humans set the sat nav. Agents drive the route.

Conveyor does not ship agents. It ships the infrastructure to define a factory, build the
specialised agents that work inside it, evaluate each agent against a human-defined quality
bar, version every change, and see exactly how those changes affect what the factory produces.

**Status: pre-alpha.** Core capabilities are being built in public. See the
[project overview](docs/project-overview.md) for the factory model, capabilities, tech stack and
scope.

## Defining a factory

A factory project holds agent folders, factory files and the contracts agents exchange:

```
agents/<name>/agent.yaml   # Brief, Capabilities and Quality Gate
agents/<name>/prompt.md    # instructions
agents/<name>/evals/       # eval suite
factories/<name>.yaml      # stages, triggers, rework loops and outcome scorers
contracts.py               # Pydantic models named by each Brief's input and output
```

Check them against the factory model; every problem is reported as `file:line:column: field:
message`:

```bash
uv run conveyor validate examples/prd-to-pr
```

`conveyor validate` accepts an agent folder, a factory file or a project directory, and exits
`0` when valid, `1` when there are problems and `2` on a usage error. For agents inside a
project it also resolves each Brief's `input` and `output` (such as `contracts.TaskList`) to a
Pydantic model in the project, which means **validating imports and runs the project's contract
modules**: validate only projects whose code you trust. Editors that understand
JSON Schema can validate and autocomplete these files using [`schemas/`](schemas/); see the
[reference factory](examples/prd-to-pr/) for a complete example.

## Versioning agents

`conveyor agent publish` turns an agent folder into an immutable version. It validates the
agent, snapshots everything that defines it (its `agent.yaml`, instructions, contract schemas
and eval files) and records the snapshot under the sha256 of its canonical form, so the same
content always gets the same ID ([ADR 0013](docs/adr/0013-agent-version-identity.md)). Each
publish also gets a sequence number (`v1`, `v2`, ...), an author, a message and a time.
Versions live in the project's `.conveyor/` folder, which is never committed.

Publish the reference factory's `implementer`, switch its model, check what changed and
publish again:

```console
$ cd examples/prd-to-pr
$ uv run conveyor agent publish implementer -m "initial"
Published implementer v1 (893e1fa01106): first version

$ # edit agents/implementer/agent.yaml: capabilities.model.id: openai/gpt-5
$ uv run conveyor agent diff implementer --working --summary
implementer v1 → working copy: Capabilities changed; model profile changed; model switched (anthropic/claude-sonnet → openai/gpt-5)

$ uv run conveyor agent publish implementer -m "Switch to GPT-5"
Published implementer v2 (7b514a755dad): Capabilities changed; model profile changed; model switched (anthropic/claude-sonnet → openai/gpt-5)

$ uv run conveyor agent diff implementer --summary
implementer v1 → v2: Capabilities changed; model profile changed; model switched (anthropic/claude-sonnet → openai/gpt-5)

$ uv run conveyor agent history implementer
v2  7b514a755dad  2026-10-28 12:05  ada  Switch to GPT-5
v1  893e1fa01106  2026-10-28 12:00  ada  initial
```

Diffs are described in factory-model terms: which block changed (Brief, Capabilities,
Quality Gate), which component inside it and which primitive. Without `--summary`, `diff`
lists every change, with line-by-line diffs of instructions and eval files.

| Command | What it does |
|---|---|
| `conveyor agent publish NAME -m MSG [--author TEXT]` | Validate `agents/NAME/` and publish it as the next version; does nothing if the content is unchanged |
| `conveyor agent history NAME` | List versions, newest first |
| `conveyor agent show NAME[@REF]` | Show a version's metadata, `agent.yaml` and file sizes |
| `conveyor agent diff NAME [FROM] [TO] [--working] [--summary]` | Compare the last two versions, any two, or a version with the folder on disk |

A version is referred to as `latest`, `vN` or at least four hex characters of its content ID.
Every command takes `--project PATH` (default: the current directory). Publishing refuses an
invalid agent and prints its problems as `conveyor validate` does; like `validate`, it imports
the project's contract modules. Commands exit `1` for problems (an invalid agent, an unknown
version, an unreadable registry) and `2` for a usage error. `diff` exits `0` whether or not
there are differences, unless `--exit-code` is given: then, as with `git diff --exit-code`, `1`
means the versions differ and problems exit with `2`.

## Development

Requirements: [uv](https://docs.astral.sh/uv/) ≥ 0.13, Python 3.14, Node 24 and
[pnpm](https://pnpm.io/) 11.

```bash
make install   # Python + UI dependencies and git hooks
make check     # everything CI runs: lint, strict types, tests, UI build
```

Run `make help` for all targets. Contributor and agent guidance lives in
[`CONTRIBUTING.md`](CONTRIBUTING.md) and [`AGENTS.md`](AGENTS.md); design decisions are
recorded in [`docs/adr/`](docs/adr/).

## License

[Apache-2.0](LICENSE)
