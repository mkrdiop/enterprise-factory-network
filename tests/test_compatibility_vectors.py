import json
from pathlib import Path

from efs.compatibility import (
    CompatibilityDimension,
    EvidenceReference,
    assess_contract_change,
    assess_governance,
    assess_profile_mapping,
    assess_specification,
)
from efs.versioning import VersionRangeError, evaluate_efs_version_range

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "conformance/efs/v1/compatibility-vectors.json").read_text(encoding="utf-8"))
EVIDENCE = (EvidenceReference("vector-evidence", "https://evidence.example/vector"),)


def test_machine_readable_compatibility_vectors():
    for vector in VECTORS["vectors"]:
        dimension = vector["dimension"]
        if dimension == "specification":
            try:
                evaluator_result = evaluate_efs_version_range(vector["candidateVersion"], vector["range"]) if vector["range"] else None
            except VersionRangeError:
                evaluator_result = None
            result = assess_specification(
                supported_range=vector["range"], consumer_profile_id="consumer-profile",
                range_evaluator_result=evaluator_result, evidence=EVIDENCE if vector["evidence"] else (),
            )
        elif dimension == "factory-release-capability-contract":
            result = assess_contract_change(
                capability_id="capability-1", contract_id="contract-1",
                previous_version=vector["previousVersion"], selected_version=vector["selectedVersion"],
                change_classification=vector["classification"], evidence=EVIDENCE if vector["evidence"] else (),
            )
        elif dimension in ("runtime-execution", "protocol"):
            target = CompatibilityDimension.RUNTIME if dimension == "runtime-execution" else CompatibilityDimension.PROTOCOL
            result = assess_profile_mapping(
                target, subject_profile_id=vector["subjectProfile"], consumer_profile_id=vector["consumerProfile"],
                mapping_id=vector["mapping"], mapping_outcome=vector.get("mappingOutcome"),
                evidence=EVIDENCE if vector["evidence"] else (),
            )
        else:
            result = assess_governance(
                outcome=vector.get("classification"), evidence=EVIDENCE if vector["evidence"] else (),
                authority=vector["authority"], conditions=vector.get("conditions", ()),
            )
        assert result.outcome.value == vector["expected"], vector["id"]
