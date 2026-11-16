# Contributing

## Scope and source of truth

This repository contains the shared EFS contract foundation and its executable evidence. Keep product-specific UI, tenant configuration, credentials and runtime implementation details outside the portable manifest and shared contract unless an approved specification change explicitly brings them in.

Use the governance boundary:

- Notion is authoritative for human-readable specifications and durable architecture decisions.
- Linear is authoritative for delivery status, dependencies and acceptance progress.
- Git is authoritative for executable schemas, fixtures, tests, validators, CI and the version-controlled ADR index.
- The artifact registry will own immutable published release packages when implemented.

## Development setup

Use Python 3.11, 3.12 or 3.13.

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check scripts tests
```

To format Python files:

```bash
python -m ruff format scripts tests
```

To validate a manifest:

```bash
python scripts/validate_manifest.py fixtures/valid/manifest-minimal.json
python scripts/validate_manifest.py fixtures/valid/manifest-minimal.json --json
```

## Branch and pull-request workflow

1. Create a focused branch from the current `main` branch. Use `<area>/<short-description>` or the Linear issue's generated branch name.
2. Keep each pull request scoped to a coherent issue or tightly related set of changes.
3. Link the relevant Linear issue(s) in the pull-request description.
4. Explain the behavior changed, compatibility/security implications, and any intentionally deferred work.
5. Add or update fixtures and tests for normative or validator behavior changes.
6. Do not modify the normative schema to make a fixture pass unless the change is supported by an approved specification/ADR decision.
7. Wait for required CI checks to pass before merge. Do not bypass failing checks; correct the change or document a justified, reviewed exception.
8. Update the relevant Notion specification and Linear acceptance evidence when the change affects a decision or requirement.

## Required checks

The GitHub Actions workflow `.github/workflows/efs-schema.yml` runs on pushes and pull requests. It tests Python 3.11, 3.12 and 3.13, runs Ruff lint checks, executes the complete pytest suite and conformance-catalog tests, and performs representative CLI validation.

Run the equivalent checks locally:

```bash
python -m ruff check scripts tests
python -m pytest -q
python -m pytest tests/test_conformance_catalog.py -q
python scripts/validate_manifest.py fixtures/valid/manifest-minimal.json --json
python scripts/validate_manifest.py fixtures/valid/manifest-external-execution.json
python scripts/validate_manifest.py fixtures/boundary/manifest-offset-datetime.json
```

## Architecture decisions

Record material architectural choices in `docs/adr/` using `ADR-TEMPLATE.md`. Assign sequential identifiers (ADR-001, ADR-002, ...). Decision status is one of Proposed, Accepted, Rejected or Superseded. Keep candidate choices Proposed until there is explicit approval and evidence. If an accepted decision changes, create a successor ADR and mark the previous record Superseded; do not rewrite decision history.

The ADR decision lifecycle is distinct from the Notion document lifecycle (Draft, Proposed, Approved, Superseded).

## Schema, fixtures and compatibility

- EFS v1 uses JSON Schema Draft 2020-12.
- Preserve the approved PSI-34 object semantics and PSI-35 schema behavior.
- Keep conformance fixtures language-neutral and catalogue every fixture.
- Reject unrestricted remote schema retrieval; do not add network-dependent validation.
- Do not claim that structural conformance verifies release digests, signatures, trust, policies, dependencies, compatibility or runtime admission.
- Unknown core fields, extension namespace governance and other explicitly open matters remain open until decided through the appropriate ADR/specification process.

## Changelog and releases

Record user-visible or contract-relevant changes in `CHANGELOG.md`. The current changelog structure is a proposed repository convention, not a published release policy. Do not create release tags or imply immutable artifact publication until the release/versioning ADR and artifact registry process are approved.
