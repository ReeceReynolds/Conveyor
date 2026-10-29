# Contributing to Conveyor

Thanks for your interest. Conveyor is built in public; issues and pull requests are welcome.

## Getting started

```bash
make install
make check
```

[`AGENTS.md`](AGENTS.md) is the authoritative guide to commands, conventions and the definition
of done. It applies equally to human and agent contributors.

Milestone work is broken into work packages in [`docs/plans/`](docs/plans/README.md); check the
current plan before starting, and target the milestone's branch if your change is one of its
packages. Step-by-step procedures (adding an ADR, a configuration rule or a package, and the
pre-PR checklist) live in [`.claude/skills/`](.claude/skills/); they are plain Markdown and work
for humans and any agent.

## Workflow

1. Open an issue first for anything non-trivial, so the approach can be agreed.
2. Branch from `main` and make focused changes with tests.
3. Run `make check` locally (the pre-commit hooks run a subset on every commit).
4. Open a pull request with a [Conventional Commit](https://www.conventionalcommits.org/)
   title, for example `feat(registry): add structured agent diffs`. PRs are squash-merged and
   the title becomes the commit that drives versioning and the changelog.

## Architecture decisions

Any new dependency or significant design choice needs an Architecture Decision Record. Copy
[`docs/adr/0000-template.md`](docs/adr/0000-template.md) to the next number, fill it in, and
add it to the index in [`docs/adr/README.md`](docs/adr/README.md).

## Code of conduct

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
