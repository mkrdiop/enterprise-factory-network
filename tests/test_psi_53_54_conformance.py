"""Schema and semantic conformance checks for PSI-53 and PSI-54."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
VECTOR_DIR = ROOT / "tests" / "conformance"


def test_psi53_vectors_validate_and_execute() -> None:
    schema = json.loads((SCHEMA_DIR / "psi-53-enforcement-v1.schema.json").read_text())
    vectors = json.loads((VECTOR_DIR / "psi-53-enforcement-v1.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(vectors)


def test_psi54_vectors_validate_and_execute() -> None:
    schema = json.loads((SCHEMA_DIR / "psi-54-lifecycle-v1.schema.json").read_text())
    vectors = json.loads((VECTOR_DIR / "psi-54-lifecycle-v1.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(vectors)


def test_psi53_psi54_reference_oracle() -> None:
    runner = VECTOR_DIR / "run_psi_53_54_vectors.py"
    subprocess.run([sys.executable, str(runner)], cwd=ROOT, check=True)
