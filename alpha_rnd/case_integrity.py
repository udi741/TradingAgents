import hashlib
import json


def _canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def seal_case(artifact: dict) -> dict:
    protected = sorted(key for key in artifact if key != "case_integrity")
    payload = {key: artifact[key] for key in protected}
    artifact["case_integrity"] = {
        "schema_version": 1,
        "algorithm": "sha256",
        "hash": hashlib.sha256(_canonical(payload)).hexdigest(),
        "covers": protected,
    }
    return artifact


def verify_case(artifact) -> bool:
    if not isinstance(artifact, dict):
        return False
    integrity = artifact.get("case_integrity")
    if not isinstance(integrity, dict) or integrity.get("schema_version") != 1:
        return False
    if integrity.get("algorithm") != "sha256":
        return False
    protected = sorted(
        key for key in artifact if key != "case_integrity"
    )
    if integrity.get("covers") != protected:
        return False
    payload = {key: artifact[key] for key in protected}
    return integrity.get("hash") == hashlib.sha256(_canonical(payload)).hexdigest()
