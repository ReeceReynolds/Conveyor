# 0006. UI toolchain: pnpm, Vite, React, TypeScript, Biome and Vitest

- Status: Accepted
- Date: 2026-10-20

## Context

Conveyor ships a local web interface (Factory Overview, Run Detail, Change Set Detail, Agent
Detail) bundled into the Python package. It needs a standard, typed, component-based stack.

## Decision

- **pnpm** (pinned via `packageManager`) with a committed lockfile and a one-day
  `minimumReleaseAge` as a supply-chain cooldown.
- **Vite** for dev server and build; output goes to `src/conveyor/_ui/` so the Python package
  can serve it.
- **React** with **TypeScript** in strict mode (plus `noUncheckedIndexedAccess` and
  `exactOptionalPropertyTypes`).
- **Biome** as the single linter and formatter.
- **Vitest** with jsdom and Testing Library for component tests.
- Added with the first UI feature, as set out in the project overview: **TanStack Router and
  Query**, **shadcn/ui** (with Tailwind CSS), and a **typed client generated from the FastAPI
  OpenAPI schema**.

## Alternatives considered

- **npm / Yarn** — pnpm is faster and stricter about undeclared dependencies.
- **ESLint + Prettier** — two tools and more configuration; Biome covers both.
- **Jest** — Vitest shares Vite's config and transform pipeline.

## Consequences

Contributors need Node 24 and pnpm 11. The UI build must run before `uv build` once the UI is
bundled into releases.
