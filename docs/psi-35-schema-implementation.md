# PSI-35 — Schema implementation note

Normative inputs: the approved PSI-34 EFS v1 canonical object model and JSON Schema Draft 2020-12.

Implemented:
- Required root fields and reusable publisher, factory, release, capability, endpoint, execution, dependency and policy definitions.
- Mandatory release digest profile efs-jcs-sha256-v1, SHA-256 and 43-character unpadded Base64URL digest value.
- Capability contract identity as an absolute URI, independent version, Draft 2020-12 dialect and complete object-payload schemas for inputs/outputs.
- Mutually exclusive manifest/external execution branches; external references require stable absolute ID, version and content digest.
- Distinct policy declaration and immutable reference structures; references require id/profile/version/digest/uri/enforcement.
- Contract schemas are meta-schema checked by the validator; remote reference retrieval is prohibited.

Deliberately unresolved:
Unknown core-field behavior and extension namespace handling remain open in PSI-34, so core objects do not set additionalProperties=false. Dependency target union, version grammar, publisher identity grammar, signature/trust profile, policy and guarantee vocabularies, and extension namespace governance remain open.

Validation layers remain distinct: structural JSON Schema validation; embedded contract schema validation; semantic/reference validation; digest/signature verification; policy evaluation; compatibility assessment; runtime admission.

The format keyword is an annotation unless the Draft 2020-12 format-assertion vocabulary is explicitly enabled. Consumers must not assume identical format assertion behavior across validators.
