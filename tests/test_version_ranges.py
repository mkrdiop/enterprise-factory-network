import json
from pathlib import Path

import pytest

from efs.versioning import VersionRangeError, evaluate_efs_version_range

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "conformance/efs/v1/version-range-vectors.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("candidate", "expression", "expected"),
    [
        ("1.2.3", "*", True),
        ("1.2.3-alpha", "*", True),
        ("1.2.3", "1.x", True),
        ("1.9.0", "1.x", True),
        ("2.0.0", "1.x", False),
        ("1.2.3", "1.2.x", True),
        ("1.3.0", "1.2.x", False),
        ("1.2.3", "1.2.3", True),
        ("1.2.3+build.8", "1.2.3+build.7", True),
        ("1.2.3-alpha", ">=1.2.3-alpha <1.2.3", True),
        ("1.2.3", ">=1.0.0 <2.0.0", True),
        ("2.0.0", ">=1.0.0 <2.0.0", False),
        ("1.0.0", ">1.0.0 <=2.0.0", False),
        ("1.0.1", ">1.0.0 <=2.0.0", True),
        ("1.5.0", ">=1.0.0 <=1.5.0", True),
    ],
)
def test_efs_supported_range_vectors(candidate, expression, expected):
    assert evaluate_efs_version_range(candidate, expression) is expected


@pytest.mark.parametrize(
    "expression",
    [
        "",
        " ",
        "1",
        "1.2",
        "01.x",
        "1.X",
        ">=1 <2",
        ">= 1.0.0",
        ">=1.0.0  <2.0.0",
        ">=1.0.0 || <2.0.0",
        "^1.0.0",
        "~1.0.0",
        "1.0.0 - 2.0.0",
        ">=1.0.0, <2.0.0",
        ">=1.0.0\n<2.0.0",
        ">=v1.0.0",
    ],
)
def test_unsupported_range_syntax_fails_closed(expression):
    with pytest.raises(VersionRangeError):
        evaluate_efs_version_range("1.2.3", expression)


def test_candidate_must_be_strict_efs_semver():
    for candidate in ("v1.2.3", "1.2", "01.2.3", "1.2.3 "):
        with pytest.raises(VersionRangeError):
            evaluate_efs_version_range(candidate, "*")


def test_empty_or_non_string_inputs_fail_closed():
    for candidate, expression in ((None, "*"), ("1.2.3", None), ("1.2.3", "")):
        with pytest.raises(VersionRangeError):
            evaluate_efs_version_range(candidate, expression)


def test_machine_readable_supported_range_vectors():
    for vector in VECTORS["vectors"]:
        if "error" in vector:
            with pytest.raises(VersionRangeError):
                evaluate_efs_version_range(vector["candidate"], vector["range"])
        else:
            assert evaluate_efs_version_range(vector["candidate"], vector["range"]) is vector["expected"], vector["id"]
