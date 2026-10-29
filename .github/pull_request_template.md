## What and why

<!-- What does this change do, and why is it needed? Link the issue if there is one. -->

## Checklist

- [ ] PR title is a [Conventional Commit](https://www.conventionalcommits.org/) (it becomes the squash-merge commit)
- [ ] `make check` passes locally
- [ ] Tests cover the change (no network calls; real-model tests are marked `live`)
- [ ] New dependency or architectural decision has an ADR in `docs/adr/`
- [ ] Docs and `AGENTS.md` updated if behaviour, commands or conventions changed
- [ ] If this fixes a mistake a check could have caught, the check is added (lint rule, test or hook)
