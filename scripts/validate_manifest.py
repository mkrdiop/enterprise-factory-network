#!/usr/bin/env python3
import argparse, json
from pathlib import Path
from urllib.parse import urlparse
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

def reject_duplicate_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError(f"duplicate JSON object member: {key}")
        result[key] = value
    return result

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_members)

def check_local_refs(value, path="$"):
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            parsed = urlparse(ref)
            if parsed.scheme in ("http","https") and parsed.netloc:
                raise ValueError(f"{path}: remote $ref prohibited; bundle and pin the resource")
            if ref.startswith("//"): raise ValueError(f"{path}: network-path $ref prohibited")
        for key, child in value.items(): check_local_refs(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value): check_local_refs(child, f"{path}/{index}")

def validate(manifest_path, schema_path):
    manifest, schema = load(manifest_path), load(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=lambda e:list(map(str,e.absolute_path)))
    if errors: return [f"{'/'.join(map(str,e.absolute_path)) or '$'}: {e.message}" for e in errors]
    for i, capability in enumerate(manifest["capabilities"]):
        contract = capability["contract"]
        for direction in ("inputs","outputs"):
            payload_schema = contract[direction]
            try:
                Draft202012Validator.check_schema(payload_schema)
                if payload_schema.get("type") != "object": raise ValueError("top-level payload schema must declare type=object")
                check_local_refs(payload_schema, f"capabilities/{i}/contract/{direction}")
            except (SchemaError,ValueError) as exc:
                return [f"capabilities/{i}/contract/{direction}: {exc}"]
        for j, error in enumerate(contract["errors"]):
            if "schema" in error:
                try:
                    Draft202012Validator.check_schema(error["schema"])
                    check_local_refs(error["schema"], f"capabilities/{i}/contract/errors/{j}/schema")
                except (SchemaError,ValueError) as exc:
                    return [f"capabilities/{i}/contract/errors/{j}/schema: {exc}"]
    return []

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("manifest",type=Path)
    parser.add_argument("--schema",type=Path,default=Path(__file__).resolve().parents[1]/"schemas/efs/v1/factory-manifest.schema.json")
    args=parser.parse_args()
    try: errors=validate(args.manifest,args.schema)
    except (ValueError,json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}"); raise SystemExit(1)
    if errors:
        print("INVALID"); print("\n".join("- "+e for e in errors)); raise SystemExit(1)
    print("STRUCTURALLY VALID (EFS v1 Draft 2020-12)")
    print("Semantic/reference, digest/signature, policy, compatibility and runtime admission remain separate.")
if __name__=="__main__": main()
