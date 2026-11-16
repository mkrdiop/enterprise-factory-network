# Enterprise Factory Network

Source repository for the Enterprise Factory ecosystem and the shared Enterprise Factory Specification (EFS) v1 technical foundation.

The repository owns executable contracts and implementation evidence: JSON Schema, language-neutral fixtures, reference validators, tests and CI. Human-readable requirements, architecture decisions and governance records are maintained in the [Enterprise Factory Engineering Hub](https://app.notion.com/p/41af741d651181238ffbe4614c38daea).

## Current baseline

- **EFS requirements:** [EFS v1 Requirements Baseline](https://app.notion.com/p/41af741d651181ee87d5e868b6167d54) — approved requirements and scope boundary.
- **Canonical object model:** [EFS v1 Canonical Factory Manifest Object Model](https://app.notion.com/p/41af741d651181ac9488d932f13051f0) — approved PSI-34 model.
- **Normative schema:** `schemas/efs/v1/factory-manifest.schema.json` — JSON Schema Draft 2020-12.
- **Version dimensions:** [EFS v1 version-dimension model](docs/efs-v1-version-dimensions.md) and [ADR-010](docs/adr/ADR-010-efs-v1-version-dimension-model.md) — PSI-46 normative authority.
- **Conformance:** [PSI-36 implementation and acceptance traceability](docs/psi-36-conformance.md); language-neutral fixtures and machine-readable registries live under `fixtures/` and `conformance/efs/v1/`.
- **Architecture decisions:** [ADR index](docs/adr/README.md) and [ADR template](docs/adr/ADR-TEMPLATE.md).

A passing conformance result covers parsing, structural validation, embedded-schema validation and the currently profiled EFS v1 invariants. It does not imply digest/signature verification, external reference retrieval, policy evaluation, dependency resolution, compatibility or runtime authorization.

## Prerequisites

- Git
- Python 3.11, 3.12 or 3.13
- pip

## Clean-checkout setup

```bash
git clone https://github.com/mkrdiop/enterprise-factory-network.git
cd enterprise-factory-network
python -m venv .venv
# Activate the virtual environment for your shell.
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Validate a manifest with the reference validator:

```bash
python scripts/validate_manifest.py fixtures/valid/manifest-minimal.json
python scripts/validate_manifest.py fixtures/valid/manifest-minimal.json --json
```

Run the repository linter:

```bash
python -m ruff check scripts tests
```

Format Python source locally:

```bash
python -m ruff format scripts tests
```

## Repository map

| Path | Responsibility |
| --- | --- |
| `schemas/efs/v1/` | Normative EFS v1 JSON Schema |
| `fixtures/` | Language-neutral valid, invalid, boundary, extension and adversarial inputs |
| `conformance/efs/v1/` | Machine-readable fixture, diagnostic, report and acceptance registries |
| `scripts/` | Reference validation tooling |
| `tests/` | Schema, validator and conformance-catalog tests |
| `docs/adr/` | Version-controlled architecture decisions and decision index |
| `docs/` | Implementation and conformance documentation |
| `.github/workflows/` | Pull-request and push quality gates |

The EFS contract artifacts are independent of product UI and runtime implementation. Factory Studio, Factory Connect, Factory Runtime and Enterprise Factory Network consume the shared contract; they do not redefine it.

## Contribution

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Repository workflow and changelog conventions are documented there and in [CHANGELOG.md](CHANGELOG.md). Architectural choices must be recorded in an ADR; a Proposed ADR is not an accepted technology decision.

## Governance

- **Notion:** specifications, glossary, ADR context, architecture and implementation plans.
- **Linear:** tasks, priorities, milestones, cycles, progress and acceptance tracking.
- **Git:** source code, canonical JSON Schema, fixtures, tests, CI and version-controlled ADR artifacts.
- **Artifact registry:** immutable published releases and artifacts, when implemented.
