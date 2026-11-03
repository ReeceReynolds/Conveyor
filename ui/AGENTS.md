# ui

The local web interface: React + TypeScript built with Vite (ADR 0006). It is bundled into the
Python package and served by `conveyor`.

## Rules

- pnpm only (version pinned by `packageManager` in `package.json`), always via `pnpm -C ui ...`
  from the repository root. Never use npm or Yarn, and never hand-edit `pnpm-lock.yaml`.
  `pnpm-workspace.yaml` sets a one-day `minimumReleaseAge` supply-chain cooldown.
- Biome is the only linter and formatter (`biome.json`). `noExplicitAny`, `noConsole` and
  `noNonNullAssertion` are errors and `biome ci --error-on-warnings` fails on any warning.
- TypeScript is strict, plus `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`,
  `noImplicitOverride`, `noFallthroughCasesInSwitch`, `noUnusedLocals`,
  `noUnusedParameters` and `verbatimModuleSyntax` (`tsconfig.json`). Use `import type` for
  type-only imports. Narrow values instead of asserting them.
- Tests use Vitest with jsdom and Testing Library; name them `<Component>.test.tsx` next to
  the component.
- `vite build` writes to `../src/conveyor/_ui/` (gitignored). Never edit or commit the build
  output; change `src/` and rebuild.

## Commands

| Task | Command |
|---|---|
| Lint, type-check, test and build (what CI runs) | `make ui-check` |
| Format and apply safe fixes | `pnpm -C ui run format` |
| Dev server | `pnpm -C ui run dev` |
| One test file | `pnpm -C ui exec vitest run src/App.test.tsx` |
