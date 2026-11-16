# ADR-002 — Python repository quality tooling

- **Status:** Accepted
- **Date:** 2026-11-16
- **Decision owners:** Repository maintainers
- **Related Linear issue:** PSI-30
- **Related specification:** [Documentation Conventions & Governance](https://app.notion.com/p/41af741d651181269a91c416143ff47b)

## Context

The repository's first executable reference implementation and test suite are Python. Contributors need a repeatable, low-friction lint and formatting tool that runs locally and can be used in pull-request checks without selecting a platform runtime or product architecture.

## Decision drivers

- One tool should provide both Python linting and formatting.
- It must support the repository's Python 3.11–3.13 matrix.
- It should be installable as a development dependency and run locally without a service.
- The choice must remain limited to repository contributor tooling.

## Options considered

### Option A — Ruff

Use Ruff for linting and formatting Python source. It is a local development tool with a single command-line interface.

### Option B — Separate formatter and linter

Use distinct tools such as Black and Flake8. This is familiar but adds separate dependencies and configuration.

### Option C — Defer

Leave Python lint/format conventions entirely manual. This avoids a tool choice but produces no consistent automated baseline.

## Decision

**Accepted:** Use Ruff for Python repository linting and formatting. Pin its supported major-version range in `requirements-dev.txt`. Run `ruff check scripts tests` in CI. Contributors may run `ruff format scripts tests` locally; formatting is not a CI gate in this initial baseline.

This decision applies only to Python contributor tooling in this repository. It does not select a language, formatter, linter or runtime for the four-product ecosystem.

## Rationale and evidence

Ruff provides both functions with one dependency and supports the repository's supported Python versions. The CI workflow runs the linter alongside the conformance suite. Formatting is available as a deterministic local command without retroactively reformatting the PSI-35/36 implementation.

## Consequences

### Positive

- Contributors share one reproducible lint tool.
- CI catches common Python quality issues on every push and pull request.
- Formatting is available without adding another dependency.

### Negative / trade-offs

- Ruff rules/configuration may need adjustment as the codebase grows.
- Formatting is not yet enforced by CI; a later change can introduce a formatting gate after the existing corpus is normalized.

### Follow-up work

- [ ] Add explicit Ruff configuration if repository-specific rule exceptions become necessary.
- [ ] Consider a formatting CI gate after the current source tree is normalized.

## Security, privacy and operations

Ruff runs locally and in GitHub Actions; it does not require source upload to a third-party service or runtime network access beyond dependency installation.

## Compatibility and migration

Tooling changes affect contributor workflow, not EFS manifest semantics or published factory releases. Pin changes should be reviewed and tested in the Python version matrix.

## References

- [Ruff documentation](https://docs.astral.sh/ruff/)
- [PSI-30 repository skeleton](https://linear.app/getpsi/issue/PSI-30/create-repository-skeleton)

## Change history

| Date | Change | Reason |
| --- | --- | --- |
| 2026-11-16 | Accepted repository-only Ruff baseline | Provide consistent lint/format commands without committing the ecosystem to Python |
