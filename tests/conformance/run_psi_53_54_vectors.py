"""Independent reference oracle for PSI-53/54 v1.1 conformance vectors."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/"tests"/"conformance"
ALLOWED={
 "publisher.read":{"publisher"},"publisher.manage":{"publisher"},"publisher.key.manage":{"publisher"},
 "factory.discover":{"factory"},"factory.read":{"factory"},"factory.register":{"factory"},"factory.publish":{"factory"},
 "release.read":{"release"},"release.publish":{"release"},"release.suspend":{"release"},"release.deprecate":{"release"},"release.revoke":{"release"},"release.archive":{"release"},
 "capability.invoke":{"capability"},"registry.policy.read":{"registry"},"registry.policy.manage":{"registry"}
}
COORD={
 "publisher":{"publisher_id"},"factory":{"publisher_id","factory_id"},
 "release":{"publisher_id","factory_id","release_version"},
 "capability":{"publisher_id","factory_id","release_version","capability_id"},
 "registry":{"registry_id"},"execution_target":{"execution_target_id"}
}
LEGAL={
 ("published","suspended"),("published","deprecated"),("published","revoked"),
 ("suspended","published"),("suspended","deprecated"),("suspended","revoked"),
 ("deprecated","revoked"),("deprecated","archived"),("revoked","archived")
}
def dt(value): return datetime.fromisoformat(value)

def psi53(data):
 if not data["principal"]["authenticated"]: return "rejected","AUTHN_REQUIRED"
 checks=data["checks"]
 if not checks: return "rejected","ACTION_UNMAPPED"
 for check in checks:
  action=check["action"]; resource=check["resource"]; kind=resource["type"]
  if action not in ALLOWED: return "rejected","ACTION_UNMAPPED"
  if kind not in ALLOWED[action]: return "indeterminate","INDETERMINATE_INVALID_ACTION_RESOURCE_PAIR"
  if not resource["id"] or not COORD[kind].issubset(resource["coordinates"]):
   return "indeterminate","INDETERMINATE_INVALID_ACTION_RESOURCE_PAIR"
  policy=check["policy"]
  if policy["policy_profile"]!="efs-policy-v1" or not policy.get("digest_verified") or not all(policy.get(k) for k in ("policy_id","policy_version","digest")):
   return "indeterminate","PDP_INDETERMINATE"
 if any(c["pdp_outcome"]=="deny" for c in checks): return "rejected","POLICY_DENIED"
 if any(c["pdp_outcome"]=="indeterminate" for c in checks): return "indeterminate","PDP_INDETERMINATE"
 if any(c["pdp_outcome"]!="permit" for c in checks): return "indeterminate","PDP_INDETERMINATE"
 for check in checks:
  fulfilled={item["obligation_id"] for item in check["fulfillment_evidence"] if item["fulfilled"] and item["evidence_ref"]}
  required={item["id"] for item in check["obligations"]}
  if required-fulfilled or (required and not check["obligations_fulfilled"]):
   return "rejected","OBLIGATION_UNFULFILLED"
 trust=data["trust"]
 if trust["required"]:
  signers=trust["required_signers"]
  if not signers: return "rejected","TRUST_UNAVAILABLE"
  for signer in signers:
   if signer["algorithm"]!="Ed25519" or signer["usage"]!="efs-release-signing": return "rejected","TRUST_UNAVAILABLE"
   if signer["crypto_status"]=="invalid": return "rejected","SIGNATURE_INVALID"
   if signer["crypto_status"]!="valid": return "rejected","TRUST_UNAVAILABLE"
   if signer["status"]=="untrusted": return "rejected","KEY_NOT_TRUSTED"
   if signer["status"]=="revoked": return "rejected","KEY_REVOKED"
   if signer["status"]!="trusted": return "rejected","TRUST_UNAVAILABLE"
   evidence=signer["evidence"]
   if evidence is None: return "rejected","TRUST_UNAVAILABLE"
   if evidence["publisher_id"]!=signer["publisher_id"] or evidence["key_id"]!=signer["key_id"]:
    return "rejected","TRUST_UNAVAILABLE"
   if evidence["version"]>data["commit"]["evidence_versions"].get("trust",0):
    return "rejected","EVIDENCE_STALE"
   if evidence["status"]=="revoked": return "rejected","KEY_REVOKED"
   if evidence["status"]!="trusted": return "rejected","KEY_NOT_TRUSTED"
   now=dt(data["commit"]["at"]); observed=dt(evidence["observed_at"])
   age=(now-observed).total_seconds()
   if age<0 or age>data["commit"]["max_evidence_age_seconds"] or now>=dt(evidence["expires_at"]):
    return "rejected","EVIDENCE_STALE"
 lifecycle=data["lifecycle"]
 if lifecycle["required"] and lifecycle["state"] not in ("published","deprecated"):
  return "rejected","RELEASE_NOT_ADMISSIBLE"
 commit_data=data["commit"]
 if commit_data["evidence_versions"]!=commit_data["current_evidence_versions"]:
  return "rejected","AUTHORIZATION_REVISION_CHANGED"
 if not commit_data["audit_outbox_available"]: return "rejected","AUDIT_DURABILITY_FAILURE"
 side=commit_data["side_effect"]
 if commit_data["operation_kind"]=="external_effect":
  state=commit_data["execution_state"]
  required_intent=(side["intent_durable"] and side["idempotency_key"] and side["operation_id"] and side["intent_record_id"] and side["audit_record_id"] and side["payload_fingerprint"] and state is not None and state["persisted_with_intent"] and state["revision_cas"] and state["initial_state"]=="requested" and state["initial_revision"]==1 and state["invocation_id"]==side["operation_id"] and state["initial_event_id"] and side["payload_fingerprint"].startswith("sha256:") and len(side["payload_fingerprint"])==50)
  if not required_intent: return "rejected","EXECUTION_INTENT_NOT_DURABLE"
  if side["dispatch_attempted"] and side["outcome_recorded"] and (not side["outcome_ref"] or state["current_state"] not in ("succeeded","failed") or state["current_revision"]<2):
   return "indeterminate","EXECUTION_OUTCOME_UNKNOWN"
  if side["dispatch_attempted"] and not side["outcome_recorded"]:
   return "indeterminate","EXECUTION_OUTCOME_UNKNOWN"
 return "enforced","PERMIT_ENFORCED"

def psi54(data):
 if data["scope"]["operation"]!=data["operation"]: return "rejected","IDEMPOTENCY_CONFLICT"
 lookup=data["idempotency_lookup"]
 # Scope is derived after authentication. Lookup precedes state and revision reads.
 if lookup["status"]=="same_fingerprint":
  record=lookup["record"]
  if record is None or record["scope"]!=data["scope"] or record["request_fingerprint"]!=data["request_fingerprint"]:
   return "rejected","IDEMPOTENCY_CONFLICT"
  return record["original_result"],record["original_reason"]
 if lookup["status"]=="different_fingerprint": return "rejected","IDEMPOTENCY_CONFLICT"
 if data["operation"]=="initial_publication":
  event=data["publication"]
  coordinate=event["coordinate_snapshot"]
  digest=event["digest_snapshot"]
  valid=(
   data["from"] is None and data["to"]=="published" and
   event["authoring_request_validated"] and event["coordinate_exact"] and
   event["digest_verified"] and event["signature_verified"] and bool(event["actor_id"]) and
   event["event_type"]=="factory_release.published" and event["event_id"] and event["action"]=="release.publish" and event["revision"]==1 and
   event["from_state"] is None and bool(event["authorization_decision_ref"]) and
   event["release_inserted"] and event["event_inserted"] and
   event["audit_outbox_inserted"] and event["same_database_transaction"] and
   all(coordinate.get(k) for k in ("publisher_id","factory_id","release_version")) and
   digest["profile_id"]=="efs-jcs-sha256-v1" and digest["algorithm"]=="SHA-256" and
   len(digest["value"])==43 and
   event["authorization_actions"]==["factory.register","factory.publish","release.publish"]
  )
  return ("accepted","PUBLICATION_ACCEPTED") if valid else ("rejected","PUBLICATION_INVALID")
 if (data["from"],data["to"]) not in LEGAL: return "rejected","ILLEGAL_TRANSITION"
 if not data["authorized"]: return "rejected","AUTHORIZATION_DENIED"
 if not data["reason_present"]: return "rejected","REASON_REQUIRED"
 if data["to"]=="revoked" and not data["evidence_present"]: return "rejected","REVOCATION_EVIDENCE_REQUIRED"
 if not data["preconditions_met"]: return "rejected","PRECONDITION_FAILED"
 if not data["expected_revision_matches"]: return "rejected","STALE_REVISION"
 return "accepted","TRANSITION_ACCEPTED"

def execute(filename, oracle):
 document=json.loads((DATA/filename).read_text(encoding="utf-8"))
 failures=0
 for vector in document["vectors"]:
  actual=oracle(vector["input"])
  expected=(vector["expected"]["result"],vector["expected"]["reason"])
  if actual!=expected:
   failures+=1
   print(f"FAIL {vector['id']}: expected {expected}, got {actual}")
 passed=len(document["vectors"])-failures
 print(f"{document['vector_set']}: {passed}/{len(document['vectors'])} passed")
 return failures,len(document["vectors"])

def main():
 f53,n53=execute("psi-53-enforcement-v1.json",psi53)
 f54,n54=execute("psi-54-lifecycle-v1.json",psi54)
 print(f"Total: {n53+n54-f53-f54}/{n53+n54} passed")
 return 1 if f53+f54 else 0

if __name__=="__main__": sys.exit(main())
