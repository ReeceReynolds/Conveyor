# Conveyor

[![CI](https://github.com/ReeceReynolds/Conveyor/actions/workflows/ci.yml/badge.svg)](https://github.com/ReeceReynolds/Conveyor/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

An open-source foundation layer for **harness engineering**: building agent-driven software
factories.

> Humans set the sat nav. Agents drive the route.

Conveyor does not ship agents. It ships the infrastructure to define a factory, build the
specialised agents that work inside it, evaluate each agent against a human-defined quality
bar, version every change, and see exactly how those changes affect what the factory produces.

**Status: pre-alpha.** The repository currently contains the tooling foundation; core
capabilities are being built in public. See the [project overview](docs/project-overview.md)
for the factory model, capabilities, tech stack and scope.

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
