# PSI-53 / PSI-54 conformance vectors v1.1

The packages are language- and transport-neutral semantic oracles.

- PSI-53: exact PSI-52 action/resource compatibility, multi-check publication, all-check permit composition, deny/indeterminate outcomes, trust-required versus trust-not-required, evidence freshness, obligations, commit-generation changes and external-effect durable intent/outcome.
- PSI-54: legal/illegal lifecycle transitions, scoped idempotency, replay of the original accepted or rejected result, fingerprint conflict, cross-scope key isolation and atomic revision-1 publication event.

## Execute the reference oracle

From the repository root:

```sh
python tests/conformance/run_psi_53_54_vectors.py
```

Expected result: 24/24 vectors (14 PSI-53 + 10 PSI-54).

## Independent implementation requirements

A conforming implementation MUST validate each package against its adjacent JSON Schema (Draft 2020-12), execute every vector and compare both result and stable reason code, and keep PSI-52 policy-v1 PDP vectors as a separate mandatory suite. These vectors do not replace integration tests for route bypass, PostgreSQL transactional outbox, trust/revocation races, commit compare-and-swap, PSI-45 execution hand-off, crash/retry/reconciliation or Registry/Runtime parity.

PSI-53 external effects are not claimed to be atomic with a local database. A durable intent must precede dispatch; an uncertain outcome is indeterminate and reconciled using the same operation/idempotency identity. PSI-45 remains authoritative for execution lifecycle.

PSI-54 idempotency lookup is scoped by tenant, authenticated principal, canonical exact release coordinate (publisher, Factory, version and digest) and operation. It occurs before current-state/revision validation and returns the stored original result, reason and response reference.
