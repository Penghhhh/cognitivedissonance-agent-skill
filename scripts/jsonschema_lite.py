"""A small, dependency-free JSON Schema validator.

Why this exists
---------------
The published schemas in ``schemas/`` must be the single source of truth for what
the engine accepts and emits. Without a validator they are documentation that can
silently drift from the code, which is exactly the failure mode of the v0.1
proposal (it listed six schema files and never checked a single instance against
any of them).

The repository therefore ships this validator rather than depending on
``jsonschema``: the skill has to run on a bare Python interpreter with no network
and no ``pip install`` step, because a reviewer reproducing Study 1 should not
have to build an environment first.

Supported keyword subset
------------------------
``$ref`` (local ``#/...`` only), ``$defs``, ``type`` (string or list), ``enum``,
``const``, ``required``, ``properties``, ``additionalProperties``,
``propertyNames``, ``minProperties``, ``maxProperties``, ``items``,
``minItems``, ``maxItems``, ``uniqueItems``, ``minimum``, ``maximum``,
``exclusiveMinimum``, ``exclusiveMaximum``, ``multipleOf``, ``minLength``,
``maxLength``, ``pattern``, ``allOf``, ``anyOf``, ``oneOf``, ``not``.

Ignored on purpose: ``format`` (assertion-free by default in draft 2020-12),
``title``, ``description``, ``default``, ``examples``, ``$schema``, ``$id``.
Anything else raises ``UnsupportedKeywordError`` so an unsupported assertion can
never be mistaken for a passing one.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

__all__ = [
    "UnsupportedKeywordError",
    "validate",
    "is_valid",
    "ValidationError",
]


class UnsupportedKeywordError(Exception):
    """Raised when a schema uses a keyword this validator does not implement."""


class ValidationError(Exception):
    """Raised by :func:`validate_or_raise`; carries the full error list."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors) if errors else "validation failed")
        self.errors = errors


# Keywords that carry no assertion and are therefore skipped when encountered.
_ANNOTATION_KEYWORDS = {
    "$schema", "$id", "$anchor", "$comment", "title", "description",
    "default", "examples", "deprecated", "readOnly", "writeOnly", "format",
    "contentMediaType", "contentEncoding",
}

_KNOWN_KEYWORDS = _ANNOTATION_KEYWORDS | {
    "$ref", "$defs", "definitions", "type", "enum", "const", "required",
    "properties", "patternProperties", "additionalProperties", "propertyNames",
    "minProperties", "maxProperties", "items", "prefixItems", "minItems",
    "maxItems", "uniqueItems", "contains", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength",
    "maxLength", "pattern", "allOf", "anyOf", "oneOf", "not", "if", "then",
    "else", "dependencies", "dependentRequired", "dependentSchemas",
}

# Keywords we recognise but deliberately do not implement. They raise, rather
# than being skipped, because silently ignoring an assertion is worse than
# refusing to validate.
_UNIMPLEMENTED_KEYWORDS = _KNOWN_KEYWORDS - _ANNOTATION_KEYWORDS - {
    "$ref", "$defs", "type", "enum", "const", "required", "properties",
    "additionalProperties", "propertyNames", "minProperties", "maxProperties",
    "items", "minItems", "maxItems", "uniqueItems", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength",
    "maxLength", "pattern", "allOf", "anyOf", "oneOf", "not",
}

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _pointer(doc: Any, ref: str) -> Any:
    """Resolve a local JSON pointer of the form ``#/a/b/0``."""
    if not ref.startswith("#"):
        raise UnsupportedKeywordError(f"only local $ref is supported, got {ref!r}")
    node = doc
    for raw in ref[2:].split("/"):
        if raw == "":
            continue
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, dict):
            if token not in node:
                raise UnsupportedKeywordError(f"unresolvable $ref {ref!r}")
            node = node[token]
        else:
            raise UnsupportedKeywordError(f"unresolvable $ref {ref!r}")
    return node


def _describe(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return f"string({value[:40]!r})"
    if isinstance(value, list):
        return f"array(len={len(value)})"
    if isinstance(value, dict):
        return f"object(keys={sorted(value)[:6]})"
    return type(value).__name__


def _check_keywords(schema: dict, errors: list[str], path: str) -> None:
    for keyword in schema:
        if keyword not in _KNOWN_KEYWORDS:
            raise UnsupportedKeywordError(f"unknown schema keyword {keyword!r} at {path or '<root>'}")
        if keyword in _UNIMPLEMENTED_KEYWORDS:
            raise UnsupportedKeywordError(
                f"keyword {keyword!r} is recognised but not implemented by jsonschema_lite "
                f"(at {path or '<root>'}); refusing to validate rather than skip the assertion"
            )


def _type_matches(value: Any, type_spec: Any) -> bool:
    names = type_spec if isinstance(type_spec, list) else [type_spec]
    for name in names:
        check = _TYPE_CHECKS.get(name)
        if check is None:
            raise UnsupportedKeywordError(f"unknown type {name!r}")
        if check(value):
            return True
    return False


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _validate(schema: Any, value: Any, root: Any, path: str, errors: list[str]) -> None:
    if schema is True or schema == {}:
        return
    if schema is False:
        errors.append(f"{path or '<root>'}: schema is False, no value is valid")
        return
    if not isinstance(schema, dict):
        raise UnsupportedKeywordError(f"schema at {path or '<root>'} must be an object or boolean")

    _check_keywords(schema, errors, path)

    if "$ref" in schema:
        target = _pointer(root, schema["$ref"])
        _validate(target, value, root, path, errors)
        # A sibling of $ref is legal in 2020-12; keep validating the rest.

    if "type" in schema and not _type_matches(value, schema["type"]):
        expected = schema["type"]
        errors.append(f"{path or '<root>'}: expected type {expected}, got {_describe(value)}")
        return  # type is wrong; further assertions would produce noise

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path or '<root>'}: expected const {schema['const']!r}, got {value!r}")

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path or '<root>'}: {value!r} is not one of {schema['enum']}")

    for combinator in ("allOf",):
        for sub in schema.get(combinator, []):
            _validate(sub, value, root, path, errors)

    if "anyOf" in schema:
        if not any(is_valid(sub, value, root) for sub in schema["anyOf"]):
            errors.append(f"{path or '<root>'}: value matches none of the anyOf branches")

    if "oneOf" in schema:
        matches = sum(1 for sub in schema["oneOf"] if is_valid(sub, value, root))
        if matches != 1:
            errors.append(f"{path or '<root>'}: expected exactly one oneOf branch to match, {matches} matched")

    if "not" in schema and is_valid(schema["not"], value, root):
        errors.append(f"{path or '<root>'}: value matches a schema it must not match")

    if isinstance(value, dict):
        _validate_object(schema, value, root, path, errors)
    elif isinstance(value, list):
        _validate_array(schema, value, root, path, errors)
    elif isinstance(value, str):
        _validate_string(schema, value, path, errors)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _validate_number(schema, value, path, errors)


def _validate_object(schema: dict, value: dict, root: Any, path: str, errors: list[str]) -> None:
    for key in schema.get("required", []):
        if key not in value:
            errors.append(f"{path or '<root>'}: missing required property {key!r}")

    props = schema.get("properties", {})
    for key, sub in props.items():
        if key in value:
            _validate(sub, value[key], root, f"{path}/{key}", errors)

    if "propertyNames" in schema:
        for key in value:
            _validate(schema["propertyNames"], key, root, f"{path}/<name:{key}>", errors)

    if len(value) < schema.get("minProperties", 0):
        errors.append(f"{path or '<root>'}: expected at least {schema['minProperties']} properties, got {len(value)}")
    if "maxProperties" in schema and len(value) > schema["maxProperties"]:
        errors.append(f"{path or '<root>'}: expected at most {schema['maxProperties']} properties, got {len(value)}")

    if "additionalProperties" in schema:
        extra = [k for k in value if k not in props]
        rule = schema["additionalProperties"]
        if rule is False:
            for key in extra:
                errors.append(f"{path or '<root>'}: unexpected property {key!r}")
        elif isinstance(rule, dict):
            for key in extra:
                _validate(rule, value[key], root, f"{path}/{key}", errors)


def _validate_array(schema: dict, value: list, root: Any, path: str, errors: list[str]) -> None:
    if "items" in schema:
        for index, item in enumerate(value):
            _validate(schema["items"], item, root, f"{path}/{index}", errors)
    if len(value) < schema.get("minItems", 0):
        errors.append(f"{path or '<root>'}: expected at least {schema['minItems']} items, got {len(value)}")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        errors.append(f"{path or '<root>'}: expected at most {schema['maxItems']} items, got {len(value)}")
    if schema.get("uniqueItems"):
        seen: set[str] = set()
        for item in value:
            key = _canonical(item)
            if key in seen:
                errors.append(f"{path or '<root>'}: duplicate item {key[:60]}")
            seen.add(key)


def _validate_string(schema: dict, value: str, path: str, errors: list[str]) -> None:
    if len(value) < schema.get("minLength", 0):
        errors.append(f"{path or '<root>'}: shorter than minLength {schema['minLength']}")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        errors.append(f"{path or '<root>'}: longer than maxLength {schema['maxLength']}")
    if "pattern" in schema and re.search(schema["pattern"], value) is None:
        errors.append(f"{path or '<root>'}: {value[:60]!r} does not match pattern {schema['pattern']!r}")


def _validate_number(schema: dict, value: float, path: str, errors: list[str]) -> None:
    if "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path or '<root>'}: {value} < minimum {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        errors.append(f"{path or '<root>'}: {value} > maximum {schema['maximum']}")
    if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
        errors.append(f"{path or '<root>'}: {value} <= exclusiveMinimum {schema['exclusiveMinimum']}")
    if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
        errors.append(f"{path or '<root>'}: {value} >= exclusiveMaximum {schema['exclusiveMaximum']}")
    if "multipleOf" in schema:
        factor = schema["multipleOf"]
        if factor > 0 and not math.isclose(value / factor, round(value / factor), rel_tol=1e-9, abs_tol=1e-9):
            errors.append(f"{path or '<root>'}: {value} is not a multiple of {factor}")


def validate(schema: dict, instance: Any) -> list[str]:
    """Return a list of human-readable error strings; empty means valid."""
    errors: list[str] = []
    _validate(schema, instance, schema, "", errors)
    return errors


def is_valid(schema: dict, instance: Any, root: Any | None = None) -> bool:
    """Boolean form. ``root`` lets a nested call keep the outer document's ``$defs``."""
    errors: list[str] = []
    _validate(schema, instance, root if root is not None else schema, "", errors)
    return not errors


def validate_or_raise(schema: dict, instance: Any, what: str = "instance") -> None:
    errors = validate(schema, instance)
    if errors:
        raise ValidationError([f"{what}: {e}" for e in errors])
