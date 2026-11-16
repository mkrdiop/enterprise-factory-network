# Architecture Decision Records

This directory is the version-controlled index and record set for material technical and architectural decisions in the Enterprise Factory ecosystem.

## Decision status

- **Proposed** — a coherent option or recommendation awaiting explicit approval.
- **Accepted** — explicitly approved and supported by the recorded rationale/evidence.
- **Rejected** — considered and explicitly declined.
- **Superseded** — replaced by a successor ADR; retain the historical record and link the successor.

This decision lifecycle is distinct from the Notion document lifecycle (Draft, Proposed, Approved, Superseded). An ADR document may be Proposed while its decision is Proposed.

## Index

| ADR | Decision | Status | Related work |
| --- | --- | --- | --- |
| [ADR-001](ADR-001-efs-v1-release-digest-profile.md) | EFS v1 release digest profile | Accepted | PSI-34, PSI-35 |
| [ADR-002](ADR-002-python-repository-quality-tooling.md) | Python repository lint/format tooling | Accepted | PSI-30 |
| ADR-003 | Publisher namespace and issuer/trust model | Proposed | PSI-37, PSI-50 |
| ADR-004 | Registry persistence and immutable artifact storage | Proposed | Registry / artifact workstream |
| ADR-005 | Execution orchestration and messaging | Proposed | PSI-44, PSI-45 |
| ADR-006 | Execution isolation and workload packaging | Proposed | Runtime security workstream |
| ADR-007 | Tenant isolation and authorization model | Proposed | Runtime governance workstream |
| ADR-008 | Protocol profiles and adapter conformance | Proposed | PSI-56, PSI-58 |
| ADR-009 | Unknown core fields and extension namespace governance | Proposed | PSI-34 follow-through |

The Proposed entries are a decision inventory only. They do not select a technology or protocol. Create a separate ADR file when an item is ready for substantive evaluation; keep its status Proposed until approved.

## Authoring

1. Copy [ADR-TEMPLATE.md](ADR-TEMPLATE.md).
2. Assign the next sequential identifier; do not reuse identifiers.
3. Include at least two credible options where alternatives exist, plus a defer option.
4. Record security, operational and compatibility consequences.
5. Link related Linear issues and the controlling Notion specification.
6. Update this index in the same pull request.
7. Never rewrite an Accepted decision to hide a change; create a successor ADR and mark the earlier record Superseded.

## Related governance

- [Documentation Conventions & Governance](https://app.notion.com/p/41af741d651181269a91c416143ff47b)
- [EFS v1 Requirements Baseline](https://app.notion.com/p/41af741d651181ee87d5e868b6167d54)
- [EFS v1 Canonical Factory Manifest Object Model](https://app.notion.com/p/41af741d651181ac9488d932f13051f0)
