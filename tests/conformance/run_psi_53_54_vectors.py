#!/usr/bin/env python3
"""Dependency-free reference oracle for PSI-53 and PSI-54 conformance vectors.

Run from any directory:
    python tests/conformance/run_psi_53_54_vectors.py

This checks the transport-neutral enforcement/lifecycle decision vectors. It is
not a replacement for PSI-52 PDP conformance or PostgreSQL integration tests.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFORMANCE = ROOT / "tests" / "conformance"


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def psi53_decide(data: dict) -> tuple[str, str]:
    if not data["authenticated"]:
        return "rejected", "AUTHN_REQUIRED"
    if not data["action_mapped"]:
        return "rejected", "ACTION_UNMAPPED"
    if not data["resource_exact"]:
        return "rejected", "RESOURCE_COORDINATES_INVALID"
    if data["pdp_outcome"] == "deny":
        return "rejected", "POLICY_DENIED"
    if data["pdp_outcome"] == "indeterminate":
        return "rejected", "PDP_INDETERMINATE"
    if not data["obligations_satisfied"]:
        return "rejected", "OBLIGATION_UNFULFILLED"
    trust = data["trust_status"]
    if trust == "unavailable":
        return "rejected", "TRUST_UNAVAILABLE"
    if trust == "untrusted":
        return "rejected", "KEY_NOT_TRUSTED"
    if trust == "revoked":
        return "rejected", "KEY_REVOKED"
    if trust not in ("trusted", "not_required"):
        return "rejected", "TRUST_UNAVAILABLE"
    release = data["release_state"]
    if release not in ("not_release_operation", "published", "deprecated"):
        return "rejected", "RELEASE_NOT_ADMISSIBLE"
    commit = instant(data["commit_time"])
    bound = data["max_evidence_age_seconds"]
    for item in data["evidence"]:
        age = (commit - instant(item["observed_at"])).total_seconds()
        if age < 0 or age > bound or commit >= instant(item["expires_at"]):
            return "rejected", "EVIDENCE_STALE"
    if data["evidence_changed_before_commit"]:
        return "rejected", "AUTHORIZATION_REVISION_CHANGED"
    if not data["audit_outbox_available"]:
        return "rejected", "AUDIT_DURABILITY_FAILURE"
    return "enforced", "PERMIT_ENFORCED"


LEGAL = {
    ("published", "suspended"),
    ("published", "deprecated"),
    ("published", "revoked"),
    ("suspended", "published"),
    ("suspended", "deprecated"),
    ("suspended", "revoked"),
    ("deprecated", "revoked"),
    ("deprecated", "archived"),
    ("revoked", "archived"),
}


def psi54_decide(data: dict) -> tuple[str, str]:
    transition = (data["from"], data["to"])
    if transition not in LEGAL:
        return "rejected", "ILLEGAL_TRANSITION"
    if data["idempotency_replay"] == "same_request":
        return "accepted", "IDEMPOTENT_REPLAY"
    if data["idempotency_replay"] == "different_request":
        return "rejected", "IDEMPOTENCY_CONFLICT"
    if not data["authorized"]:
        return "rejected", "AUTHORIZATION_DENIED"
    if not data["reason_present"]:
        return "rejected", "REASON_REQUIRED"
    if data["to"] == "revoked" and not data["evidence_present"]:
        return "rejected", "REVOCATION_EVIDENCE_REQUIRED"
    if not data["preconditions_met"]:
        return "rejected", "PRECONDITION_FAILED"
    if not data["expected_revision_matches"]:
        return "rejected", "STALE_REVISION"
    return "accepted", "TRANSITION_ACCEPTED"


def load(name: str) -> dict:
    with (CONFORMANCE / name).open(encoding="utf-8") as stream:
        return json.load(stream)


def check_psi53() -> int:
    document = load("psi-53-enforcement-v1.json")
    assert document["vector_set"] == "psi-53-enforcement-v1"
    assert document["version"] == "1.0.0"
    failures = 0
    for vector in document["vectors"]:
        actual = psi53_decide(vector["input"])
        expected = (vector["expected"]["result"], vector["expected"]["reason"])
        if actual != expected:
            failures += 1
            print(f"FAIL {vector['id']}: expected {expected}, got {actual}")
    print(f"PSI-53: {len(document['vectors']) - failures}/{len(document['vectors'])} vectors passed")
    return failures


def check_psi54() -> int:
    document = load("psi-54-lifecycle-v1.json")
    assert document["vector_set"] == "psi-54-lifecycle-v1"
    assert document["version"] == "1.0.0"
    assert document["states"] == ["published", "suspended", "deprecated", "revoked", "archived"]
    declared = {(item["from"], item["to"]) for item in document["legal_transitions"]}
    assert declared == LEGAL, "declared legal transition table differs from reference contract"
    failures = 0
    for vector in document["vectors"]:
        actual = psi54_decide(vector["input"])
        expected = (vector["expected"]["result"], vector["expected"]["reason"])
        if actual != expected:
            failures += 1
            print(f"FAIL {vector['id']}: expected {expected}, got {actual}")
    print(f"PSI-54: {len(document['vectors']) - failures}/{len(document['vectors'])} vectors passed")
    return failures


def main() -> int:
    failures = check_psi53() + check_psi54()
    total = len(load("psi-53-enforcement-v1.json")["vectors"]) + len(load("psi-54-lifecycle-v1.json")["vectors"])
    print(f"Total: {total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
