# PSI-53 / PSI-54 conformance vectors

The vector sets are language- and transport-neutral inputs for independent implementations.

- PSI-53 enforcement: `psi-53-enforcement-v1.json` against `../../schemas/psi-53-enforcement-v1.schema.json`
- PSI-54 lifecycle: `psi-54-lifecycle-v1.json` against `../../schemas/psi-54-lifecycle-v1.schema.json`

## Run the reference oracle

From the repository root:

```sh
python tests/conformance/run_psi_53_54_vectors.py
```

The oracle uses only the Python standard library and checks the exact expected decision/reason for every vector. Expected result: 42/42 passing (20 PSI-53 + 22 PSI-54).

## Independent implementation requirements

A conforming implementation MUST:
1. validate each vector document against its adjacent JSON Schema (Draft 2020-12);
2. execute every vector against its own PEP/lifecycle implementation and compare both result and stable reason code;
3. preserve all PSI-52 policy-v1 vectors as a separate mandatory PDP suite;
4. reject unknown vector kinds, missing required fields and unknown fields;
5. add integration tests for route bypass, transactional outbox, evidence freshness/revocation races, PostgreSQL compare-and-swap and Registry/Runtime parity.

The reference oracle is a small semantic baseline, not a substitute for the production PEP, persistence, concurrency or security integration suite.
