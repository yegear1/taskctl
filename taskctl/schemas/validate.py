"""Stdlib validator for the JSON Schema subset published under taskctl/schemas."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

_SCHEMA_ROOT = Path(__file__).resolve().parent

_ANNOTATION_KEYS = {
    "$schema",
    "$id",
    "$comment",
    "title",
    "description",
    "examples",
    "default",
}

_CONSTRAINT_KEYS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "enum",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
}


class ContractValidationError(ValueError):
    """Raised when an instance violates a published taskctl payload schema."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def load_schema(name: str) -> dict[str, Any]:
    """Load a schema document by versioned stem, such as ``v1/webhook-event``."""
    relative = name.strip().lstrip("/")
    if not relative.endswith(".schema.json"):
        relative = f"{relative}.schema.json"
    path = (_SCHEMA_ROOT / relative).resolve()
    if _SCHEMA_ROOT not in path.parents:
        raise ValueError(f"Schema path escapes the schema package: {name}")
    if not path.is_file():
        raise FileNotFoundError(f"Schema not found: {relative}")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Schema root must be an object: {relative}")
    return loaded


def validate_instance(instance: Any, schema: Mapping[str, Any]) -> None:
    """Validate ``instance`` against ``schema``. Raise ContractValidationError on failure."""
    errors: list[str] = []
    _validate(instance, schema, "$", errors)
    if errors:
        raise ContractValidationError(errors)


def _validate(instance: Any, schema: Mapping[str, Any], pointer: str, errors: list[str]) -> None:
    unknown = [
        key
        for key in schema
        if key not in _ANNOTATION_KEYS
        and key not in _CONSTRAINT_KEYS
        and not key.startswith("x-")
    ]
    if unknown:
        errors.append(f"{pointer}: unsupported schema keywords {sorted(unknown)}")
        return

    if "type" in schema and not _matches_type(instance, schema["type"]):
        errors.append(f"{pointer}: expected type {schema['type']}")
        return

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{pointer}: {instance!r} is not one of {schema['enum']}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < int(schema["minLength"]):
            errors.append(f"{pointer}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(instance) > int(schema["maxLength"]):
            errors.append(f"{pointer}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and re.search(str(schema["pattern"]), instance) is None:
            errors.append(f"{pointer}: does not match pattern {schema['pattern']}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{pointer}: below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{pointer}: above maximum {schema['maximum']}")

    if isinstance(instance, dict):
        _validate_object(instance, schema, pointer, errors)


def _validate_object(
    instance: dict[str, Any],
    schema: Mapping[str, Any],
    pointer: str,
    errors: list[str],
) -> None:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        errors.append(f"{pointer}: schema properties must be an object")
        return

    required = schema.get("required", [])
    if not isinstance(required, list):
        errors.append(f"{pointer}: schema required must be an array")
        return
    for key in required:
        if key not in instance:
            errors.append(f"{pointer}: missing required property {key}")

    additional = schema.get("additionalProperties", True)
    for key, value in instance.items():
        child = f"{pointer}.{key}"
        if key in properties:
            property_schema = properties[key]
            if isinstance(property_schema, dict):
                _validate(value, property_schema, child, errors)
            else:
                errors.append(f"{child}: property schema must be an object")
            continue
        if additional is False:
            errors.append(f"{pointer}: additional property {key} is not allowed")
        elif isinstance(additional, dict):
            _validate(value, additional, child, errors)


def _matches_type(instance: Any, expected: Any) -> bool:
    if not isinstance(expected, str):
        return False
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return (isinstance(instance, int) or isinstance(instance, float)) and not isinstance(instance, bool)
    if expected == "null":
        return instance is None
    return False
