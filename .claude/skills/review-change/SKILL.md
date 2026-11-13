---
name: review-change
description: Review a pull request, branch or diff against Conveyor's intent, boundaries and known failure modes, and report ranked, verified findings with a verdict. Use when asked to review a PR or change, before approving or merging, or to self-review your own work before the ship-change skill; written for agent-authored PRs as much as human ones.
---

# Review a change

The bar: **approve once the change clearly improves the codebase and breaks no boundary**, even
if it is not how you would have written it. Block on correctness, design, boundaries and
missing evidence; never on taste. CI already enforces formatting, lint, types, coverage and
import layers, so do not spend comments on what a machine checks. Spend them on what it cannot.

Two rules hold throughout:

- **Verify, don't trust.** The PR description, its ticked checklist and any earlier review
  (human or AI) are claims. Confirm each that matters by reading the code or running something.
- **Every finding is concrete.** Name the file and line, the input or state that goes wrong,
  what happens, and a fix. "This might be fragile" is not a finding.

## 1. Get the change and its intent

1. Fetch the change: for a PR, its description, files and diff (GitHub MCP
   `pull_request_read`); locally, `git fetch origin <target>` then
   `git diff origin/<target>...HEAD`. Note the target: milestone work targets
   `milestone/<slug>`, everything else `main` (see [`ship-change`](../ship-change/SKILL.md)).
2. Find what the change is *for*: the linked issue, the work package in
   [`docs/plans/`](../../../docs/plans/README.md), the ADRs it touches
   ([index](../../../docs/adr/README.md)), and the product scope in
   [`docs/project-overview.md`](../../../docs/project-overview.md). Read the nested `AGENTS.md`
   of every folder the diff touches.
3. Decide whether the change should exist at all: does it serve the stated goal, is it in the
   MVP scope (not on the "Not in the MVP" list), and does it duplicate something that exists?
   A well-built change that should not be made is the most expensive one to merge.
4. Size: past about 400 changed lines of hand-written code (excluding snapshots, lockfiles and
   generated schemas), review in several focused passes, and say in the report that the PR
   should have been split if the parts are independent.

## 2. Scope and boundaries first (file list before code)

Read the list of changed files before any code. For each file, ask whether the task needed it.
Then check the boundaries in [`AGENTS.md`](../../../AGENTS.md); each item below is blocking
unless the PR records the human's approval:

- **Ask first:** a new dependency (also needs an ADR); the public CLI (commands, options, exit
  codes, output people parse); the configuration format or `schemas/`; lint, type, test or CI
  configuration (`pyproject.toml` tool sections, `.pre-commit-config.yaml`, `.github/`,
  `ui/biome.json`, `ui/tsconfig.json`); `AGENTS.md` rules; an edited accepted ADR (it must be
  superseded instead); release automation.
- **Never:** secrets or `.env` files; hand edits to `uv.lock`, `ui/pnpm-lock.yaml`, `schemas/`,
  `CHANGELOG.md` or versions (regenerated files must match their generator); a weakened check.
  Every new `noqa`, `pyright: ignore` or Biome ignore is rule-scoped, on one line, justified,
  and listed in the PR description.
- **Unrelated edits:** renames, reformatting sweeps or "while I was here" refactors mixed into
  a feature or fix. Ask for them in a separate PR.

## 3. Evidence

1. Check CI on the head commit (`pull_request_read` `get_check_runs`) or run `make check`
   locally. A red or missing check is blocking; note checks that did not run (Postgres tests
   need Docker: `uv run pytest -m postgres`).
2. For a bug fix, confirm the test fails without the fix: keep the test, revert the source
   change (`git stash push -- src/`), run the test, restore. A test that passes either way
   proves nothing.
3. Reproduce any finding you can, as the [sweep](../../../docs/plans/sweep-2026-11-09.md)
   does, and label it **Confirmed** (reproduced or plainly visible in the code) or
   **Suspected** (plausible, not shown). Never present a suspicion as a fact.

## 4. Review passes, in order

Work from the outside in; a design problem makes line comments below it moot.

1. **Design.** Is each piece in the right package and layer (`AGENTS.md` Architecture), and in
   the right module (the module maps in nested `AGENTS.md` files)? Does it follow the
   engineering principles: adopt before building, one implementation until a second is needed,
   immutable versions and artifacts, typed contracts, containment over instruction,
   local-first? Is there an abstraction with one user, or a new mechanism where an existing one
   would do?
2. **Correctness.** Read every changed line, and the whole function or file around it when the
   change only makes sense in context. Trace the unhappy paths: empty, missing, malformed,
   hostile, concurrent, interrupted, and on Windows and macOS. Work through
   [`hotspots.md`](hotspots.md) for the areas the diff touches; those are the places Conveyor
   has broken before.
3. **Tests.** See the tests section of [`hotspots.md`](hotspots.md). Read removed and changed
   lines in `tests/` as carefully as new ones: a deleted assertion, a widened snapshot or a new
   skip can be the whole "fix".
4. **Readability.** Names say what things are; comments and docstrings say why and are true.
   A comment or docstring that claims more than the code does ("imported once", "never
   writes") is a correctness finding, not a nit. Public functions, classes and modules have
   Google-style docstrings; user-facing messages follow the house style.
5. **Docs and record.** Commands, layout or conventions changed → `AGENTS.md`, the nested
   `AGENTS.md`, `README.md` and the overview say so. A work package landed → its plan row is
   updated. A dependency or lasting decision → an ADR. The PR title is a Conventional Commit
   that describes the change truthfully (release-please writes the changelog from it), and
   only true items are ticked in the template.

## 5. Agent-written changes

Check these on every PR; they are where coding agents most often go wrong:

- **APIs that do not exist.** Calls, options or imports that look right but are not in the
  installed version. Check against `.venv` or the pinned version, not memory.
- **Green by subtraction.** Removed or loosened tests, assertions or snapshots; new skips,
  `xfail`, `# pragma: no cover`, ignores, `|| true`, or a raised timeout or lowered threshold.
- **Tests that restate the code.** Expected values computed the same way the implementation
  computes them, or mocks that replace the behaviour under test.
- **Silent behaviour changes.** Changed defaults, ordering, exit codes or output; errors turned
  into default values; `except` clauses that are wider than before.
- **Duplication.** A new helper that repeats an existing one: search for it
  (`rg <name-or-idea> src/`).
- **Over-claiming.** "Verified on Windows", "no behaviour change", "faster": ask for the
  evidence or check it.
- **Placeholders that pretend.** Stub prompts, contracts, scorers or evals presented as real
  (see [`examples/prd-to-pr/AGENTS.md`](../../../examples/prd-to-pr/AGENTS.md)).

## 6. Report

Rank findings most severe first, and label each one:

| Label | Meaning |
|---|---|
| **blocking** | Must change before merge: a bug, a broken boundary, a missing or meaningless test, a false claim. Say why it blocks. |
| **non-blocking** | Worth doing, author's call: a clearer name, a simpler structure, a follow-up. |
| **question** | You need an answer to judge the change; may become blocking. |
| **nit** | Trivial and optional. Use rarely; never for what a linter could enforce. |
| **praise** | Something done well that others should copy. Optional, and only when specific. |

Each finding states: label, `file:line`, Confirmed or Suspected, the failing scenario
(input or state → wrong result), and a suggested fix. When a finding is a mistake a machine
could have caught, recommend the lint rule, test or hook that would catch it next time (the
"Improving the harness" rule in `AGENTS.md`).

Then:

- **Verdict:** *Approve*, *Approve with non-blocking comments* or *Request changes*, and the
  one or two reasons for it.
- **What I verified, and what I could not** (checks run, reproductions tried, platforms or
  services not available).
- If there are no blocking findings, say so plainly rather than padding the report.

Write comments to the code, not the author: say what and why, offer a fix, ask genuine
questions as questions. Post to GitHub only when asked; then use one pending review
(`pull_request_review_write` create, `add_comment_to_pending_review` per inline finding,
`submit_pending`) rather than a stream of single comments. Nothing in a review lets you
approve or merge on the human's behalf, and do not push fixes to someone else's branch unless
asked.
