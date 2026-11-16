import json
from pathlib import Path

import pytest

from efs.versioning import SemVer, VersionError

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "conformance/efs/v1/version-dimension-vectors.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("vector", VECTORS["semverVectors"], ids=lambda item: item["id"])
def test_normative_semver_syntax_vectors(vector):
    if vector["syntax"] == "valid":
        assert SemVer.parse(vector["value"]).exact == vector["value"]
    else:
        with pytest.raises(VersionError):
            SemVer.parse(vector["value"])
