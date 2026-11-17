from pathlib import Path

import pytest

from efs.versioning import (
    ChangeKind,
    ReleaseChangeError,
    ReleaseCoordinate,
    SemVer,
    VersionDimension,
    VersionError,
    compare_field_versions,
    contract_versions_equal,
    parse_field_version,
    require_exact_release_selection,
    validate_manifest_versions,
    validate_release_transition,
)
from registry.publication_service import (
    ManifestValidationError,
    RegistryPublicationService,
)


@pytest.mark.parametrize("value", ["0.0.0", "1.2.3", "1.2.3-alpha", "1.2.3-alpha.1",
                                    "1.2.3+build.7", "1.2.3-alpha+build.7"])
def test_semver_valid_vectors(value):
    assert SemVer.parse(value).exact == value


@pytest.mark.parametrize("value", ["v1.2.3", "1.2", "1", "01.2.3", "1.02.3",
                                    "1.2.03", "1.2.3-01", " 1.2.3", "1.2.3 ",
                                    "1.2.3-", "1.2.3+", "1.2.3-α", "1.2.3+bad..x"])
def test_semver_invalid_vectors(value):
    with pytest.raises(VersionError):
        SemVer.parse(value)


def test_semver_precedence_and_build_metadata():
    ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
               "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
    assert [SemVer.parse(value) for value in ordered] == sorted(SemVer.parse(value) for value in ordered)
    assert SemVer.parse("1.2.3+build.7") == SemVer.parse("1.2.3+build.8")
    assert SemVer.parse("1.2.3+build.7").exact != SemVer.parse("1.2.3+build.8").exact
    assert hash(SemVer.parse("1.2.3+build.7")) == hash(SemVer.parse("1.2.3+build.8"))


def test_semver_only_applies_to_two_canonical_fields():
    assert parse_field_version(VersionDimension.EFS_SPECIFICATION, "1.0.0").major == 1
    assert parse_field_version("release.version", "2.0.0").major == 2
    for field in ("capability.contract.version", "buildVersion", "execution.profile.version", "protocol.version"):
        with pytest.raises(VersionError):
            parse_field_version(field, "1.0.0")


def test_contract_versions_are_exact_opaque_values():
    assert contract_versions_equal("2026-Q4", "2026-Q4")
    assert not contract_versions_equal("V1", "v1")
    with pytest.raises(VersionError):
        contract_versions_equal("", "")


def test_cross_dimension_and_factory_scope_comparisons_rejected():
    with pytest.raises(VersionError, match="cross-dimension"):
        compare_field_versions("efsVersion", "1.0.0", "release.version", "1.0.0")
    with pytest.raises(VersionError, match="exact publisher/Factory"):
        compare_field_versions("release.version", "1.0.0", "release.version", "2.0.0",
                               left_publisher_id="urn:acme", left_factory_id="f",
                               right_publisher_id="urn:other", right_factory_id="f")
    assert compare_field_versions("release.version", "1.0.0", "release.version", "2.0.0",
                                  left_publisher_id="urn:acme", left_factory_id="f",
                                  right_publisher_id="urn:acme", right_factory_id="f") < 0


def test_release_change_classification_requires_correct_segment():
    validate_release_transition("1.2.3", "2.0.0", ChangeKind.BREAKING)
    validate_release_transition("1.2.3", "1.3.0", ChangeKind.ADDITIVE)
    validate_release_transition("1.2.3", "1.2.4", ChangeKind.FIX)
    for old, new, kind in [("1.2.3", "1.2.4", ChangeKind.BREAKING),
                           ("1.2.3", "2.0.0", ChangeKind.ADDITIVE),
                           ("1.2.3", "1.3.0", ChangeKind.FIX),
                           ("1.2.3", "1.2.3", ChangeKind.FIX)]:
        with pytest.raises(ReleaseChangeError):
            validate_release_transition(old, new, kind)


def test_release_coordinate_keeps_version_and_digest_separate():
    a = ReleaseCoordinate("urn:acme", "factory", "1.2.3", "efs-jcs-sha256-v1", "SHA-256", "a" * 64)
    b = ReleaseCoordinate("urn:acme", "factory", "1.2.3", "efs-jcs-sha256-v1", "SHA-256", "b" * 64)
    assert a.version == b.version
    assert a.exact_identity != b.exact_identity


def test_equal_precedence_labels_require_exact_selection():
    values = [ReleaseCoordinate("urn:acme", "f", v, "p", "SHA-256", d * 64)
              for v, d in [("1.2.3+build.7", "a"), ("1.2.3+build.8", "b")]]
    assert SemVer.parse(values[0].version).compare_precedence(SemVer.parse(values[1].version)) == 0
    assert require_exact_release_selection(values, values[0]) is values[0]
    assert require_exact_release_selection(values, values[1]) is values[1]


def test_release_selection_never_compares_different_factories():
    values = [ReleaseCoordinate("urn:acme", "f1", "1.0.0", "p", "SHA-256", "a"),
              ReleaseCoordinate("urn:acme", "f2", "2.0.0", "p", "SHA-256", "b")]
    assert require_exact_release_selection(values, values[1]) is values[1]


def test_release_selection_requires_explicit_requested_coordinate():
    candidate = ReleaseCoordinate("urn:acme", "f", "1.0.0", "p", "SHA-256", "a")
    with pytest.raises(TypeError):
        require_exact_release_selection([candidate])
    with pytest.raises(VersionError, match="explicit exact requested"):
        require_exact_release_selection([candidate], None)


def test_release_selection_returns_only_exact_requested_candidate():
    older = ReleaseCoordinate("urn:acme", "f", "1.0.0", "p", "SHA-256", "a")
    newer = ReleaseCoordinate("urn:acme", "f", "2.0.0", "p", "SHA-256", "b")
    assert require_exact_release_selection([newer, older], older) is older
    assert require_exact_release_selection([older, newer], older) is older


def test_release_selection_rejects_missing_coordinate_without_fallback():
    requested = ReleaseCoordinate("urn:acme", "f", "1.5.0", "p", "SHA-256", "c")
    candidates = [
        ReleaseCoordinate("urn:acme", "f", "1.0.0", "p", "SHA-256", "a"),
        ReleaseCoordinate("urn:acme", "f", "2.0.0", "p", "SHA-256", "b"),
    ]
    with pytest.raises(VersionError, match="does not match any candidate"):
        require_exact_release_selection(candidates, requested)


def test_release_selection_rejects_ambiguous_exact_matches():
    candidate = ReleaseCoordinate("urn:acme", "f", "1.0.0", "p", "SHA-256", "a")
    with pytest.raises(VersionError, match="ambiguous exact"):
        require_exact_release_selection([candidate, candidate], candidate)


@pytest.mark.parametrize("field,value", [
    ("publisher_id", "urn:other"),
    ("factory_id", "other-factory"),
    ("version", "1.0.1"),
    ("digest_profile", "other-profile"),
    ("digest_algorithm", "SHA-512"),
    ("digest_value", "b"),
])
def test_release_selection_does_not_confuse_any_exact_identity_dimension(field, value):
    requested = ReleaseCoordinate("urn:acme", "factory", "1.0.0", "p", "SHA-256", "a")
    fields = ("publisher_id", "factory_id", "version", "digest_profile",
              "digest_algorithm", "digest_value")
    mismatched = ReleaseCoordinate(*(
        value if name == field else getattr(requested, name) for name in fields
    ))
    with pytest.raises(VersionError, match="does not match any candidate"):
        require_exact_release_selection([mismatched], requested)


def test_release_selection_does_not_use_higher_precedence_as_policy():
    requested = ReleaseCoordinate("urn:acme", "f", "1.0.0", "p", "SHA-256", "a")
    higher = ReleaseCoordinate("urn:acme", "f", "9.0.0", "p", "SHA-256", "b")
    assert require_exact_release_selection([higher, requested], requested) is requested


def test_release_selection_candidate_order_cannot_change_result():
    requested = ReleaseCoordinate("urn:acme", "f", "1.0.0", "p", "SHA-256", "a")
    other = ReleaseCoordinate("urn:acme", "f", "2.0.0", "p", "SHA-256", "b")
    assert require_exact_release_selection([requested, other], requested) == require_exact_release_selection(
        [other, requested], requested
    )


def test_release_selection_does_not_fallback_after_digest_mismatch():
    requested = ReleaseCoordinate("urn:acme", "f", "1.0.0", "p", "SHA-256", "a")
    same_version_wrong_digest = ReleaseCoordinate("urn:acme", "f", "1.0.0", "p", "SHA-256", "b")
    higher_version = ReleaseCoordinate("urn:acme", "f", "2.0.0", "p", "SHA-256", "c")
    with pytest.raises(VersionError, match="does not match any candidate"):
        require_exact_release_selection([same_version_wrong_digest, higher_version], requested)


def test_manifest_semver_validation_is_field_aware_and_non_mutating():
    manifest = {
        "efsVersion": "1.0.0",
        "release": {"version": "v1.2.3"},
        "capabilities": [{"contract": {"version": "2026-Q4"}}],
    }
    diagnostics = validate_manifest_versions(manifest)
    assert [item["path"] for item in diagnostics] == ["/release/version"]
    assert manifest["release"]["version"] == "v1.2.3"
    manifest["release"]["version"] = "1.2.3"
    manifest["efsVersion"] = "1.0"
    diagnostics = validate_manifest_versions(manifest)
    assert [item["path"] for item in diagnostics] == ["/efsVersion"]


def test_registry_publication_rejects_non_semver_release_before_storage():
    root = Path(__file__).resolve().parents[1]
    raw = (root / "fixtures/valid/manifest-minimal.json").read_bytes().replace(
        b'"version":"1.2.0"', b'"version":"v1.2.0"'
    )
    service = RegistryPublicationService(None, None, None, root / "schemas/efs/v1/factory-manifest.schema.json")
    with pytest.raises(ManifestValidationError) as exc_info:
        service._validate(raw)
    diagnostic = next(item for item in exc_info.value.report["diagnostics"]
                      if item["code"] == "EFS_VERSION_SEMVER_INVALID")
    assert diagnostic["path"] == "/release/version"
