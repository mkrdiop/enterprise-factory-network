# Enterprise Factory Network

Source repository for the Enterprise Factory ecosystem and EFS v1 shared technical foundation.

PSI-35 implementation: JSON Schema Draft 2020-12 for the normative EFS v1 Factory Manifest. See `schemas/efs/v1/` and `docs/`.

## EFS v1 conformance

PSI-36 adds a language-neutral conformance corpus and deterministic staged validator. See [`docs/psi-36-conformance.md`](docs/psi-36-conformance.md) for the validation architecture, fixture taxonomy, AC-01–AC-15 traceability and scope boundaries. Machine-readable fixture, diagnostic, report and acceptance registries live in `conformance/efs/v1/`. Run the suite with `python -m pip install -r requirements-dev.txt && python -m pytest -q`.
