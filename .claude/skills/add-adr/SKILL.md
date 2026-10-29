---
name: add-adr
description: Record an architecture decision as a numbered ADR in docs/adr/. Use when adding a dependency, adopting a tool, or making a design decision with lasting consequences, or when a skill or AGENTS.md says an ADR is needed.
---

# Add an architecture decision record

ADRs live in `docs/adr/NNNN-short-title.md` and are listed in `docs/adr/README.md`
(see ADR 0001). Numbers are shared with work happening on other branches, so pick the number
from every branch, not just yours.

## 1. Find the next free number

Milestone branches reserve numbers before they reach `main`. Check every remote branch:

```bash
git fetch --quiet --prune origin '+refs/heads/*:refs/remotes/origin/*'
for ref in $(git for-each-ref --format='%(refname:short)' refs/remotes/origin/); do
  echo "$ref: $(git ls-tree --name-only "$ref" docs/adr/ | grep -o '^docs/adr/[0-9]\{4\}' | cut -d/ -f3 | tr '\n' ' ')"
done
```

Do not add `--depth` to that fetch: in a full clone it makes the repository shallow and cuts
the local history.

Use one more than the highest number on any branch (gaps are allowed; duplicates are not, and
`tests/test_repository.py` fails on them). Also check `docs/plans/` for numbers a milestone
has reserved but not yet written.

## 2. Write it

1. Copy the template: `cp docs/adr/0000-template.md docs/adr/NNNN-short-title.md`.
2. Fill in every section: Status (`Proposed` while under review, `Accepted` once agreed),
   Date (today, `YYYY-MM-DD`), Context, Decision, Alternatives considered, Consequences.
   Write the decision plainly; name versions and tools exactly.
3. Never rewrite an accepted ADR. To change a decision, write a new ADR and set the old one's
   status to `Superseded by [NNNN](NNNN-title.md)` (ask the human first).

## 3. Index and link it

1. Add a row to the table in `docs/adr/README.md`: `| [NNNN](NNNN-short-title.md) | Decision | Status |`.
   Remove the topic from the "Still to be recorded" list if it was there.
2. If the decision changes a convention, command or layout, update `AGENTS.md` (or the nested
   `AGENTS.md` it affects) and any doc that describes the old behaviour, linking the ADR.

## 4. Check

```bash
uv run pytest tests/test_repository.py   # index, numbering and links
make quick
```
