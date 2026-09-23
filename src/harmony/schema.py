"""Frozen JSON-Schema contract for the canonical analysis document (step 20).

The single source of truth is ``schemas/harmony-analysis.schema.json`` at the
repository root. This module loads it once, checks it against the draft
2020-12 metaschema, and validates analysis payloads against it. The web API's
versioned analysis endpoint (spec §22) refuses to serve a payload that fails
this contract.
"""
from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path

import jsonschema

# Canonical analysis schema version. Bump on any change to the frozen file:
# additive changes → minor, breaking changes → major (docs/JSON_SCHEMA.md).
# 1.1.0 (2026-09-22): optional chord.human_corrected (correction provenance);
# voicing.extensions enum widened to the full emitted interval set {1,2,3,5,
# 6,8,9,10,11} — the v1.0 enum was narrower than what voicing.py can emit.
SCHEMA_VERSION = (1, 1, 0)
SCHEMA_VERSION_STRING = ".".join(str(p) for p in SCHEMA_VERSION)

#: Layout when running from a source checkout (repo root two levels up from src/harmony).
_REPO_SCHEMA = Path(__file__).resolve().parent.parent.parent / "schemas" / "harmony-analysis.schema.json"
#: Layout when installed as a wheel (schemas force-included under the package).
_WHEEL_SCHEMA = Path(__file__).resolve().parent / "schemas" / "harmony-analysis.schema.json"


def schema_path() -> Path:
    for candidate in (_WHEEL_SCHEMA, _REPO_SCHEMA):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "harmony-analysis.schema.json not found next to the package or in the repo layout"
    )


@lru_cache(maxsize=1)
def load_schema() -> dict:
    """Load and self-check the frozen schema (metaschema-validated, cached)."""
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=1)
def get_validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(load_schema())


_LOCK = threading.Lock()  # jsonschema validators are not documented thread-safe


def validate_payload(payload) -> list[str]:
    """Validate an analysis payload; return human-readable errors ([] = valid)."""
    validator = get_validator()
    with _LOCK:
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    out: list[str] = []
    for err in errors:
        path = "$"
        for part in err.absolute_path:
            path += f".{part}" if isinstance(part, str) else f"[{part}]"
        out.append(f"{path}: {err.message}")
    return out


def assert_valid(payload) -> None:
    """Raise jsonschema.ValidationError if the payload violates the contract."""
    with _LOCK:
        jsonschema.validate(payload, load_schema())
