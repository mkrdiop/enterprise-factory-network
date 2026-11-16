"""Independent RFC 8785 cross-language conformance check for PSI-50 vectors."""
import json
import math
from pathlib import Path

import rfc8785

ROOT = Path(__file__).resolve().parent
VECTORS = ROOT / "signatures-v1.json"


def contains_surrogate(value):
    if isinstance(value, str):
        return any(0xD800 <= ord(char) <= 0xDFFF for char in value)
    if isinstance(value, list):
        return any(contains_surrogate(item) for item in value)
    if isinstance(value, dict):
        return any(contains_surrogate(key) or contains_surrogate(item)
                   for key, item in value.items())
    return False


def contains_non_finite(value):
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, list):
        return any(contains_non_finite(item) for item in value)
    if isinstance(value, dict):
        return any(contains_non_finite(item) for item in value.values())
    return False


def main():
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))["jcs_vectors"]
    for vector in vectors:
        if vector["kind"] == "jcs-invalid":
            value = json.loads(vector["raw_json"])
            if vector["expected_failure"] == "EFS_JCS_INVALID_UNICODE":
                assert contains_surrogate(value), vector["id"]
            elif vector["expected_failure"] == "EFS_JCS_INVALID_NUMBER":
                assert contains_non_finite(value), vector["id"]
            else:
                raise AssertionError(f"unknown invalid JCS category: {vector['id']}")
            try:
                rfc8785.dumps(value)
            except (rfc8785.CanonicalizationError, rfc8785.FloatDomainError):
                continue
            raise AssertionError(f"RFC 8785 library accepted invalid vector: {vector['id']}")
        actual = rfc8785.dumps(vector["input"]).decode("utf-8")
        assert actual == vector["expected_canonical"], (
            vector["id"], actual, vector["expected_canonical"]
        )
    print(f"PASS: independent Python RFC 8785 verification ({len(vectors)} edge vectors)")


if __name__ == "__main__":
    main()
