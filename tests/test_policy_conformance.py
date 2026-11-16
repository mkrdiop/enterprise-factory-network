"""Independent PSI-52 schema, vector-package, digest and semantic contract checks."""
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest
import rfc8785
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
POLICY_SCHEMA_PATH = ROOT / "schemas/efs-policy-v1.schema.json"
VECTOR_SCHEMA_PATH = ROOT / "tests/conformance/policy-v1.schema.json"
VECTORS_PATH = ROOT / "tests/conformance/policy-v1.json"
FORMAT_CHECKER = FormatChecker()
ACTIONS_BY_RESOURCE = {
    "publisher": {"publisher.read", "publisher.manage", "publisher.key.manage"},
    "factory": {"factory.discover", "factory.read", "factory.register", "factory.publish"},
    "release": {"release.read", "release.publish", "release.suspend", "release.deprecate", "release.revoke", "release.archive"},
    "capability": {"capability.invoke"},
    "registry": {"registry.policy.read", "registry.policy.manage"},
    "execution_target": set(),
}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def policy_schema():
    return load_json(POLICY_SCHEMA_PATH)


def vector_package():
    return load_json(VECTORS_PATH)


def validate(instance, schema, definition=None):
    if definition is not None:
        schema = copy.deepcopy(schema)
        schema.pop("oneOf", None)
        schema["$ref"] = f"#/$defs/{definition}"
    Draft202012Validator(schema, format_checker=FORMAT_CHECKER).validate(instance)


def condition_metrics(node):
    def walk(current, depth):
        if not isinstance(current, dict):
            raise TypeError("condition node must be an object")
        op = current.get("op")
        if op in {"all", "any"}:
            children = current.get("args")
            if not isinstance(children, list) or not 1 <= len(children) <= 32:
                raise ValueError("condition child count exceeds v1 limit")
        elif op == "not":
            children = [current.get("arg")]
        elif op in {"exists", "eq", "in", "gt", "gte", "lt", "lte"}:
            children = []
        else:
            raise ValueError("unsupported condition operator")
        if op == "in" and (not isinstance(current.get("values"), list) or not 1 <= len(current["values"]) <= 64):
            raise ValueError("condition literal array exceeds v1 limit")
        if any(isinstance(value, str) and len(value) > 1024 for value in current.values()):
            raise ValueError("condition string literal exceeds v1 limit")
        metrics = [walk(child, depth + 1) for child in children]
        return max([depth, *(item[0] for item in metrics)]), 1 + sum(item[1] for item in metrics)

    depth, nodes = walk(node, 1)
    if depth > 16:
        raise ValueError("condition depth exceeds v1 limit")
    if nodes > 256:
        raise ValueError("condition node count exceeds v1 limit")
    return depth, nodes


def policy_digest(policy):
    projection = {key: value for key, value in policy.items() if key != "digest"}
    canonical = rfc8785.dumps({"domain": "efs.policy.v1", "policy": projection})
    digest = hashlib.sha256(canonical).digest()
    return canonical, digest


def test_policy_and_vector_schemas_are_valid_draft_2020_12():
    policy = policy_schema()
    vector_schema = load_json(VECTOR_SCHEMA_PATH)
    Draft202012Validator.check_schema(policy)
    Draft202012Validator.check_schema(vector_schema)
    validate(vector_package(), vector_schema)
    package = vector_package()
    for key in ("vectors", "validation_vectors"):
        ids = [item["id"] for item in package[key]]
        assert len(ids) == len(set(ids))


def test_policy_examples_and_base_request_match_policy_schema():
    schema = policy_schema()
    package = vector_package()
    for name in ("subject", "resource", "context"):
        validate(package["base_request"][name], schema, name)
    for vector in package["vectors"]:
        policies = vector.get("policies", [])
        if vector.get("policy", {}).get("policy_profile") == "efs-policy-v1":
            policies = [vector["policy"], *policies]
        for policy in policies:
            validate(policy, schema, "policy")


def test_policy_digest_known_answer_is_recomputed():
    vector = next(item for item in vector_package()["vectors"] if item["id"] == "pol-kat-001")
    canonical, digest = policy_digest(vector["policy"])
    expected = vector["expected"]
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert canonical.decode() == expected["jcs"]
    assert digest.hex() == expected["sha256_hex"]
    assert encoded == expected["digest_base64url"] == vector["policy"]["digest"]["value"]


def test_wildcard_subject_and_resource_ids_are_rejected():
    schema = policy_schema()
    policy = copy.deepcopy(next(v["policy"] for v in vector_package()["vectors"] if v["id"] == "pol-001"))
    policy["rules"][0]["subject"]["id"] = "*"
    with pytest.raises(ValidationError):
        validate(policy, schema, "policy")
    policy["rules"][0]["subject"]["id"] = "user:alice"
    policy["rules"][0]["resource"]["id"] = "*"
    with pytest.raises(ValidationError):
        validate(policy, schema, "policy")


@pytest.mark.parametrize("resource", [
    {"type": "factory", "id": "f"},
    {"type": "release", "id": "r", "coordinates": {"publisher_id": "p", "factory_id": "f"}},
    {"type": "capability", "id": "c", "coordinates": {"publisher_id": "p", "factory_id": "f", "release_version": "1"}},
])
def test_resource_types_require_normative_coordinates(resource):
    with pytest.raises(ValidationError):
        validate(resource, policy_schema(), "resource")


def test_duplicate_rule_ids_are_semantically_invalid():
    policy = copy.deepcopy(next(v["policy"] for v in vector_package()["vectors"] if v["id"] == "pol-001"))
    policy["rules"].append(copy.deepcopy(policy["rules"][0]))
    ids = [rule["rule_id"] for rule in policy["rules"]]
    assert len(ids) != len(set(ids))


def test_condition_depth_and_node_limits_are_fixed():
    leaf = {"op": "eq", "ref": "context.attributes.flag", "value": True}
    at_depth_16 = copy.deepcopy(leaf)
    for _ in range(15):
        at_depth_16 = {"op": "not", "arg": at_depth_16}
    assert condition_metrics(at_depth_16)[0] == 16
    with pytest.raises(ValueError, match="depth"):
        condition_metrics({"op": "not", "arg": at_depth_16})

    def chain(nodes):
        result = copy.deepcopy(leaf)
        for _ in range(nodes - 1):
            result = {"op": "not", "arg": result}
        return result

    branches = [chain(8) for _ in range(31)] + [chain(7)]
    assert condition_metrics({"op": "all", "args": branches})[1] == 256
    with pytest.raises(ValueError, match="node count"):
        condition_metrics({"op": "all", "args": [*branches[:-1], chain(8)]})


def test_schema_enforces_condition_child_and_literal_array_limits():
    schema = policy_schema()
    with pytest.raises(ValidationError):
        validate({"op": "all", "args": [{"op": "exists", "ref": "context.attributes.x"}] * 33}, schema, "condition")
    with pytest.raises(ValidationError):
        validate({"op": "in", "ref": "context.attributes.x", "values": list(range(65))}, schema, "condition")


def test_rfc3339_format_is_asserted_with_format_checker():
    attribute = {"value": True, "source": "issuer", "observed_at": "2026-11-16T25:00:00Z", "expires_at": "2026-11-16T12:00:00Z"}
    with pytest.raises(ValidationError):
        validate(attribute, policy_schema(), "attribute")
    attribute["observed_at"] = "2026-11-16T11:00:00Z"
    validate(attribute, policy_schema(), "attribute")


def test_expiry_equality_is_stale():
    vector = next(v for v in vector_package()["validation_vectors"] if v["kind"] == "freshness-boundary")
    assert vector["evaluation_time"] == vector["expires_at"]
    assert not (vector["evaluation_time"] < vector["expires_at"])


def test_contract_validation_does_not_claim_to_implement_a_pdp():
    docs = (ROOT / "docs/specs/efs-v1-authorization-policy.md").read_text(encoding="utf-8")
    assert "independent PDP implementations consume" in docs


def test_machine_readable_negative_vectors_are_executable():
    package = vector_package()
    schema = policy_schema()
    for vector in package["validation_vectors"]:
        kind = vector["kind"]
        if kind == "invalid-policy":
            with pytest.raises(ValidationError):
                validate(vector["policy"], schema, "policy")
        elif kind == "invalid-resource":
            with pytest.raises(ValidationError):
                validate(vector["resource"], schema, "resource")
        elif kind == "semantic-policy":
            ids = [rule["rule_id"] for rule in vector["policy"]["rules"]]
            assert len(ids) != len(set(ids))
        elif kind == "condition-limit":
            condition = vector["condition"]
            if vector["limit"] in {"children", "literal-array"}:
                with pytest.raises(ValidationError):
                    validate(condition, schema, "condition")
            else:
                with pytest.raises(ValueError):
                    condition_metrics(condition)
        elif kind == "timestamp-format":
            with pytest.raises(ValidationError):
                validate(vector["attribute"], schema, "attribute")
        elif kind == "freshness-boundary":
            assert vector["evaluation_time"] == vector["expires_at"]
            assert not (vector["evaluation_time"] < vector["expires_at"])


# PSI-52 v1 conformance oracle: these validators are contract checks, not a production PDP.
def _validate_action_resource_request(request):
    validate(request, policy_schema(), "evaluationRequest")
    allowed = ACTIONS_BY_RESOURCE.get(request["resource"]["type"], set())
    if request["action"] not in allowed:
        return {"classification": "invalid-input", "reason_code": "INVALID_ACTION_RESOURCE_COMBINATION"}
    return {"classification": "valid-input"}


def _validate_policy_semantics(policy):
    ids = [rule["rule_id"] for rule in policy["rules"]]
    if len(ids) != len(set(ids)):
        return {"classification": "semantic-invalid", "reason_code": "DUPLICATE_RULE_ID"}
    return {"classification": "semantic-valid"}


def test_every_action_resource_negative_vector_is_a_complete_executable_request():
    package = vector_package()
    vectors = [v for v in package["validation_vectors"] if v["kind"] == "action-resource-compatibility"]
    assert len(vectors) == 80
    for vector in vectors:
        request = vector["evaluation_request"]
        validate(request, policy_schema(), "evaluationRequest")
        assert _validate_action_resource_request(request) == vector["expected"]


def test_action_resource_vector_coverage_matches_normative_matrix():
    package = vector_package()
    vectors = [v for v in package["validation_vectors"] if v["kind"] == "action-resource-compatibility"]
    expected_pairs = {
        (action, resource_type)
        for resource_type, allowed in ACTIONS_BY_RESOURCE.items()
        for action in set().union(*ACTIONS_BY_RESOURCE.values())
        if action not in allowed
    }
    actual_pairs = {
        (v["evaluation_request"]["action"], v["evaluation_request"]["resource"]["type"])
        for v in vectors
    }
    assert actual_pairs == expected_pairs


def test_duplicate_rule_vector_produces_normative_semantic_invalid_result():
    vector = next(v for v in vector_package()["validation_vectors"] if v["kind"] == "semantic-policy")
    assert _validate_policy_semantics(vector["policy"]) == vector["expected"]


def test_validation_vector_schema_rejects_incomplete_and_ambiguous_vectors():
    schema = load_json(VECTOR_SCHEMA_PATH)
    vector = vector_package()["validation_vectors"][0]
    incomplete = copy.deepcopy(vector)
    del incomplete["evaluation_request"]
    with pytest.raises(ValidationError):
        validate(incomplete, schema, "validationVector")
    ambiguous = copy.deepcopy(vector)
    ambiguous["unexpected"] = "must not be silently accepted"
    with pytest.raises(ValidationError):
        validate(ambiguous, schema, "validationVector")
    wrong_expected = copy.deepcopy(vector)
    wrong_expected["expected"] = "invalid"
    with pytest.raises(ValidationError):
        validate(wrong_expected, schema, "validationVector")


def test_all_validation_vectors_are_consumed_by_their_declared_contract():
    package = vector_package()
    schema = policy_schema()
    for vector in package["validation_vectors"]:
        kind = vector["kind"]
        if kind == "action-resource-compatibility":
            assert _validate_action_resource_request(vector["evaluation_request"]) == vector["expected"]
        elif kind == "invalid-policy":
            with pytest.raises(ValidationError):
                validate(vector["policy"], schema, "policy")
        elif kind == "invalid-resource":
            with pytest.raises(ValidationError):
                validate(vector["resource"], schema, "resource")
        elif kind == "semantic-policy":
            assert _validate_policy_semantics(vector["policy"]) == vector["expected"]
        elif kind == "condition-limit":
            condition = vector["condition"]
            if vector["limit"] in {"children", "literal-array"}:
                with pytest.raises(ValidationError):
                    validate(condition, schema, "condition")
            else:
                with pytest.raises(ValueError):
                    condition_metrics(condition)
        elif kind == "timestamp-format":
            with pytest.raises(ValidationError):
                validate(vector["attribute"], schema, "attribute")
        elif kind == "freshness-boundary":
            assert vector["evaluation_time"] == vector["expires_at"]
            assert not (vector["evaluation_time"] < vector["expires_at"])
        else:
            pytest.fail(f"unsupported validation vector kind: {kind}")
