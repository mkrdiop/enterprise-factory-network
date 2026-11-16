"""Field-aware EFS v1 version parsing and Factory release rules.

Normative authority: docs/efs-v1-version-dimensions.md and ADR-010.
Only efsVersion and release.version use SemVer 2.0.0. Contract versions
remain opaque exact strings; build identifiers are external provenance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from functools import total_ordering


class VersionError(ValueError):
    """A version value violates its normative field semantics."""


class VersionDimension(str, Enum):
    EFS_SPECIFICATION = "efsVersion"
    FACTORY_RELEASE = "release.version"
    CAPABILITY_CONTRACT = "capability.contract.version"


_SEMVER = re.compile(
    r"(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:-(?P<pre>(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?",
    re.ASCII,
)


@total_ordering
@dataclass(frozen=True, slots=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()
    exact: str = ""

    @classmethod
    def parse(cls, value: str) -> SemVer:
        if not isinstance(value, str):
            raise VersionError("SemVer value must be a string")
        match = _SEMVER.fullmatch(value)
        if match is None:
            raise VersionError(f"invalid Semantic Versioning 2.0.0 value: {value!r}")
        pre = tuple(match.group("pre").split(".")) if match.group("pre") else ()
        build = tuple(match.group("build").split(".")) if match.group("build") else ()
        return cls(int(match.group("major")), int(match.group("minor")),
                   int(match.group("patch")), pre, build, value)

    def compare_precedence(self, other: SemVer) -> int:
        left_core = (self.major, self.minor, self.patch)
        right_core = (other.major, other.minor, other.patch)
        if left_core != right_core:
            return (left_core > right_core) - (left_core < right_core)
        if not self.prerelease and not other.prerelease:
            return 0
        if not self.prerelease:
            return 1
        if not other.prerelease:
            return -1
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            left_num, right_num = left.isascii() and left.isdigit(), right.isascii() and right.isdigit()
            if left_num and right_num:
                return (int(left) > int(right)) - (int(left) < int(right))
            if left_num != right_num:
                return -1 if left_num else 1
            return (left > right) - (left < right)
        return (len(self.prerelease) > len(other.prerelease)) - (len(self.prerelease) < len(other.prerelease))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SemVer) and self.compare_precedence(other) == 0

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self.compare_precedence(other) < 0

    def __hash__(self) -> int:
        # SemVer precedence deliberately ignores build metadata; equality must
        # therefore have the same hash for labels that differ only by build.
        prerelease_key = tuple(
            (0, int(identifier)) if identifier.isascii() and identifier.isdigit()
            else (1, identifier)
            for identifier in self.prerelease
        )
        return hash((self.major, self.minor, self.patch, prerelease_key))


def parse_field_version(field: VersionDimension | str, value: str) -> SemVer:
    """Parse only the two SemVer-governed EFS v1 fields."""
    try:
        dimension = VersionDimension(field)
    except ValueError as exc:
        raise VersionError(f"field {field!r} is not SemVer-governed by EFS v1") from exc
    if dimension is VersionDimension.CAPABILITY_CONTRACT:
        raise VersionError("capability.contract.version is opaque; SemVer parsing is prohibited")
    return SemVer.parse(value)


def compare_field_versions(
    left_field: VersionDimension | str, left_value: str,
    right_field: VersionDimension | str, right_value: str,
    *, left_publisher_id: str | None = None, left_factory_id: str | None = None,
    right_publisher_id: str | None = None, right_factory_id: str | None = None,
) -> int:
    """Compare only one dimension; Factory releases require identical exact scope."""
    try:
        left_dimension, right_dimension = VersionDimension(left_field), VersionDimension(right_field)
    except ValueError as exc:
        raise VersionError("unsupported version dimension") from exc
    if left_dimension is not right_dimension:
        raise VersionError("cross-dimension version comparison is prohibited")
    if left_dimension is VersionDimension.CAPABILITY_CONTRACT:
        raise VersionError("contract versions support exact equality only, not ordering")
    if left_dimension is VersionDimension.FACTORY_RELEASE:
        left_scope = (left_publisher_id, left_factory_id)
        right_scope = (right_publisher_id, right_factory_id)
        if not all(isinstance(item, str) and item for item in (*left_scope, *right_scope)):
            raise VersionError("Factory release comparison requires complete publisher/Factory scope")
        if left_scope != right_scope:
            raise VersionError("Factory release versions are comparable only within exact publisher/Factory scope")
    return parse_field_version(left_dimension, left_value).compare_precedence(
        parse_field_version(right_dimension, right_value)
    )


def contract_versions_equal(left: str, right: str) -> bool:
    """Return exact, case-sensitive equality for opaque non-empty contract versions."""
    if not isinstance(left, str) or not left or not isinstance(right, str) or not right:
        raise VersionError("contract versions must be non-empty strings")
    return left == right


class ChangeKind(str, Enum):
    BREAKING = "breaking"
    ADDITIVE = "additive"
    FIX = "fix"


class ReleaseChangeError(ValueError):
    """A proposed release version does not satisfy its declared change class."""


def validate_release_transition(previous: str, proposed: str, change: ChangeKind | str) -> None:
    """Validate the minimum SemVer segment required by an explicitly classified change.

    This function does not infer public API changes from arbitrary manifest diffs.
    The caller must supply the reviewed change classification.
    """
    try:
        kind = ChangeKind(change)
    except ValueError as exc:
        raise ReleaseChangeError(f"unknown release change classification: {change!r}") from exc
    old, new = SemVer.parse(previous), SemVer.parse(proposed)
    if new.compare_precedence(old) <= 0:
        raise ReleaseChangeError("proposed release must have strictly greater SemVer precedence")
    if kind is ChangeKind.BREAKING and new.major <= old.major:
        raise ReleaseChangeError("breaking Factory surface change requires a MAJOR increment")
    if kind is ChangeKind.ADDITIVE and (new.major != old.major or new.minor <= old.minor):
        raise ReleaseChangeError("compatible additive change requires a MINOR increment without changing MAJOR")
    if kind is ChangeKind.FIX and (new.major != old.major or new.minor != old.minor or new.patch <= old.patch):
        raise ReleaseChangeError("backward-compatible fix requires a PATCH increment")


@dataclass(frozen=True, slots=True)
class ReleaseCoordinate:
    publisher_id: str
    factory_id: str
    version: str
    digest_profile: str
    digest_algorithm: str
    digest_value: str

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (
            self.publisher_id, self.factory_id, self.version, self.digest_profile,
            self.digest_algorithm, self.digest_value,
        )):
            raise ValueError("release coordinate fields must be non-empty exact strings")
        SemVer.parse(self.version)

    @property
    def factory_scope(self) -> tuple[str, str]:
        return self.publisher_id, self.factory_id

    @property
    def exact_identity(self) -> tuple[str, str, str, str, str, str]:
        return (self.publisher_id, self.factory_id, self.version, self.digest_profile,
                self.digest_algorithm, self.digest_value)


def require_exact_release_selection(candidates: list[ReleaseCoordinate]) -> ReleaseCoordinate:
    """Reject ambiguous equal-precedence labels; never invent a tie-breaker."""
    if not candidates:
        raise VersionError("no release candidates supplied")
    scopes = {item.factory_scope for item in candidates}
    if len(scopes) != 1:
        raise VersionError("release candidates span different publisher/Factory scopes")
    highest = candidates[0]
    for item in candidates[1:]:
        comparison = compare_field_versions(
            VersionDimension.FACTORY_RELEASE, item.version,
            VersionDimension.FACTORY_RELEASE, highest.version,
            left_publisher_id=item.publisher_id, left_factory_id=item.factory_id,
            right_publisher_id=highest.publisher_id, right_factory_id=highest.factory_id,
        )
        if comparison > 0:
            highest = item
    tied = [item for item in candidates if SemVer.parse(item.version).compare_precedence(SemVer.parse(highest.version)) == 0]
    if len(tied) > 1:
        raise VersionError("equal-precedence release labels require explicit exact release selection")
    return highest


def validate_manifest_versions(manifest: dict) -> list[dict[str, str]]:
    """Return stable semantic diagnostics for the two SemVer fields on publication.

    Structural validation remains a separate earlier stage. This function does
    not mutate or normalize the supplied manifest or any stored release.
    """
    diagnostics = []
    for field, path, value in (
        (VersionDimension.EFS_SPECIFICATION, "/efsVersion", manifest.get("efsVersion")),
        (VersionDimension.FACTORY_RELEASE, "/release/version",
         manifest.get("release", {}).get("version") if isinstance(manifest.get("release"), dict) else None),
    ):
        if not isinstance(value, str):
            continue
        try:
            parse_field_version(field, value)
        except VersionError:
            diagnostics.append({
                "code": "EFS_VERSION_SEMVER_INVALID",
                "stage": "profile",
                "path": path,
                "message": f"{path} must be an exact Semantic Versioning 2.0.0 value; no coercion or normalization is permitted.",
            })
    return diagnostics


class VersionRangeError(VersionError):
    """A supported EFS version range violates the EFS v1 range profile."""


def evaluate_efs_version_range(candidate: str, supported_range: str) -> bool:
    """Evaluate an EFS v1 supported range against an exact efsVersion value.

    Range grammar is owned by PSI-48 and implemented here using the PSI-47
    SemVer 2.0.0 parser/comparator. Supported forms:
      *                       any valid SemVer
      MAJOR.x                 one major line
      MAJOR.MINOR.x            one minor line
      VERSION                  exact SemVer precedence
      OP VERSION [OP VERSION]  conjunction of strict comparisons
    OP is one of >, >=, <, <=, =. No coercion, trimming, OR, shorthand
    comparator versions, tilde, caret, hyphen ranges or aliases are accepted.
    """
    if not isinstance(candidate, str):
        raise VersionRangeError("candidate efsVersion must be a string")
    if not isinstance(supported_range, str) or not supported_range:
        raise VersionRangeError("supported EFS version range must be a non-empty string")
    try:
        parsed_candidate = parse_field_version(VersionDimension.EFS_SPECIFICATION, candidate)
    except VersionError as exc:
        raise VersionRangeError(f"invalid candidate efsVersion: {exc}") from exc

    if supported_range == "*":
        return True

    wildcard = re.fullmatch(r"(0|[1-9][0-9]*)\.(?:(0|[1-9][0-9]*)\.)?x", supported_range, re.ASCII)
    if wildcard is not None:
        major = int(wildcard.group(1))
        minor_text = wildcard.group(2)
        if parsed_candidate.major != major:
            return False
        if minor_text is None:
            return True
        return parsed_candidate.minor == int(minor_text)

    # Exact versions and comparator conjunctions use strict full SemVer tokens.
    if " " not in supported_range:
        try:
            bound = parse_field_version(VersionDimension.EFS_SPECIFICATION, supported_range)
        except VersionError as exc:
            raise VersionRangeError(f"invalid supported EFS version range: {supported_range!r}") from exc
        return parsed_candidate.compare_precedence(bound) == 0

    tokens = supported_range.split(" ")
    if any(not token for token in tokens):
        raise VersionRangeError("comparison terms must be separated by exactly one ASCII space")
    for token in tokens:
        match = re.fullmatch(r"(>=|<=|>|<|=)(.+)", token, re.ASCII)
        if match is None:
            raise VersionRangeError(f"invalid comparison term: {token!r}")
        operator, version_text = match.groups()
        try:
            bound = parse_field_version(VersionDimension.EFS_SPECIFICATION, version_text)
        except VersionError as exc:
            raise VersionRangeError(f"invalid SemVer range bound: {version_text!r}") from exc
        comparison = parsed_candidate.compare_precedence(bound)
        matched = {
            ">": comparison > 0,
            ">=": comparison >= 0,
            "<": comparison < 0,
            "<=": comparison <= 0,
            "=": comparison == 0,
        }[operator]
        if not matched:
            return False
    return True
