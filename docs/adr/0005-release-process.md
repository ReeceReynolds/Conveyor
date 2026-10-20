# 0005. Releases: SemVer, Conventional Commits, release-please and PyPI Trusted Publishing

- Status: Accepted
- Date: 2026-10-20

## Context

Releases should be predictable, have readable history, and not depend on long-lived secrets
that could leak.

## Decision

- **Semantic Versioning.** While pre-1.0, a `feat` bumps the minor version and anything else
  bumps the patch.
- **Conventional Commits** for commit messages and PR titles, enforced by a commit-msg hook and
  a PR-title check. PRs are squash-merged.
- **release-please** maintains a release PR that bumps the version in `pyproject.toml` and
  writes `CHANGELOG.md`. Merging it tags a GitHub release.
- On release, CI builds the sdist and wheel with `uv build` and publishes to PyPI via
  **Trusted Publishing** (OIDC) from a protected `pypi` environment. No API tokens are stored.

## Alternatives considered

- **semantic-release** — publishes on every merge, with less control over release timing.
- **Manual releases with a PyPI token** — error-prone and relies on a long-lived secret.

## Consequences

Versions and the changelog are never edited by hand. A one-time Trusted Publisher
configuration on PyPI is required before the first release.
