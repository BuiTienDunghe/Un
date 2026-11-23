"""A call's arguments checked against the schema the model was shown, before the tool runs
(agent.validate_arguments, 23/11/2026).

Coding harnesses check a call before running it: pi validates against the tool's schema and turns
"4" into 4 where a number is wanted; opencode returns the schema error to the model with the
arguments it sent. Ún's own tools read their arguments leniently one by one (_bounded,
int(top_k)), so for them this mostly changes the wording of an error. It matters for tools Ún did
not write: an MCP server that refuses a call with a protocol error makes McpClient restart the
process and tells the model the tool is broken and not to call it again, when only a type was
wrong; the file tools behind approval should not put a call with a wrong argument in front of a
person.

Two rules, both from pi and opencode:
- A value of the wrong type is converted when the conversion is exact and loses nothing: "4" or
  4.0 for an integer, "2.5" for a number, "true"/"false" for a boolean, a number for a string,
  a JSON text of an array or object for an array or object, an enum value written in another
  case. Nothing else is guessed: "năm" is not 5.
- A type that cannot be converted, and a required key missing, is refused before the tool runs,
  with a sentence naming each problem and the arguments received, so the model can call again.

Anything this does not understand (anyOf, $ref, formats, bounds, keys the schema does not
declare) is let through as it is: the tool's own checks stay where they were, and this must
never refuse a call the tool would have run correctly. For that reason an enum value that is not
on the list is let through too: an MCP server's list reaches the model cut short
(mcp_tools.MAX_ENUM_VALUES), so a value missing from what was shown may still be the server's.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

WHOLE_TEXT = re.compile(r"[+-]?\d+")
INTEGER_TEXT = re.compile(r"[+-]?\d+(?:\.0+)?")
NUMBER_TEXT = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
# Nested arrays and objects are followed this deep; below it, a value is let through.
MAX_DEPTH = 4
RECEIVED_CHARS = 300
TYPE_NAMES = {
    "string": "chuỗi",
    "integer": "số nguyên",
    "number": "số",
    "boolean": "true hoặc false",
    "array": "danh sách",
    "object": "đối tượng",
    "null": "null",
}


@dataclass
class CheckedArguments:
    """`arguments` to run the tool with (a copy; the model's own are never changed), the problems
    that keep it from running, and the paths of the values converted."""

    arguments: dict[str, Any]
    problems: list[str] = field(default_factory=list)
    coerced: list[str] = field(default_factory=list)


def _matches(value: Any, kind: str) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    if kind == "null":
        return value is None
    return True  # a type this does not know: not this module's to refuse


_NO = object()


def _convert(value: Any, kind: str) -> Any:
    """`value` as `kind` when the conversion is exact, else _NO."""
    if kind == "integer":
        if isinstance(value, float) and math.isfinite(value) and value.is_integer():
            return int(value)
        if isinstance(value, str) and INTEGER_TEXT.fullmatch(value.strip()):
            # Whole digits only, never through float: "12345678901234567890" stays exact.
            return int(value.strip().split(".")[0])
    elif kind == "number":
        text = value.strip() if isinstance(value, str) else None
        if text is not None and WHOLE_TEXT.fullmatch(text):
            return int(text)
        if text is not None and NUMBER_TEXT.fullmatch(text):
            number = float(text)
            if math.isfinite(number):
                return number
    elif kind == "boolean":
        if isinstance(value, str) and value.strip().casefold() in ("true", "false"):
            return value.strip().casefold() == "true"
    elif kind == "string":
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return str(value)
    elif kind in ("array", "object") and isinstance(value, str) and value.strip()[:1] in ("[", "{"):
        try:
            parsed = json.loads(value)
        except ValueError:
            return _NO
        if _matches(parsed, kind):
            return parsed
    return _NO


def _kinds(spec: dict[str, Any]) -> list[str] | None:
    kind = spec.get("type")
    if isinstance(kind, str):
        return [kind]
    if isinstance(kind, list) and kind and all(isinstance(item, str) for item in kind):
        return list(kind)
    return None


def _shown(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 60 else text[:59] + "…"


def _fit(value: Any, spec: Any, path: str, depth: int, problems: list[str], coerced: list[str]) -> Any:
    """`value` checked against one property's schema: the value to use (converted if it had to
    be), with each problem and conversion appended under `path`."""
    if not isinstance(spec, dict) or depth > MAX_DEPTH:
        return value
    kinds = _kinds(spec)
    if kinds is not None and not any(_matches(value, kind) for kind in kinds):
        for kind in kinds:
            converted = _convert(value, kind)
            if converted is not _NO:
                value = converted
                coerced.append(path)
                break
        else:
            wanted = " hoặc ".join(TYPE_NAMES.get(kind, kind) for kind in kinds)
            problems.append(f"`{path}` phải là {wanted}, nhận {_shown(value)}")
            return value
    enum = spec.get("enum")
    if isinstance(enum, list) and isinstance(value, str) and value not in enum:
        # Only a case slip is mended; any other value is the tool's to judge (see the module's note).
        same = [item for item in enum if isinstance(item, str) and item.casefold() == value.strip().casefold()]
        if len(same) == 1:
            value = same[0]
            coerced.append(path)
    if isinstance(value, list) and isinstance(spec.get("items"), dict):
        value = [_fit(item, spec["items"], f"{path}[{index}]", depth + 1, problems, coerced) for index, item in enumerate(value)]
    elif isinstance(value, dict) and isinstance(spec.get("properties"), dict):
        value = _fit_object(value, spec, f"{path}.", depth + 1, problems, coerced)
    return value


def _fit_object(arguments: dict[str, Any], parameters: dict[str, Any], prefix: str, depth: int, problems: list[str], coerced: list[str]) -> dict[str, Any]:
    properties = parameters.get("properties") if isinstance(parameters.get("properties"), dict) else {}
    required = parameters.get("required") if isinstance(parameters.get("required"), list) else []
    fitted = dict(arguments)
    missing = [key for key in required if isinstance(key, str) and fitted.get(key) is None and not _allows_null(properties.get(key))]
    problems.extend(f"thiếu `{prefix}{key}` (bắt buộc)" for key in missing)
    for key, value in arguments.items():
        # An optional key sent as null is the tool's "not given", as it always was.
        if key in properties and key not in missing and not (value is None and key not in required):
            fitted[key] = _fit(value, properties[key], f"{prefix}{key}", depth, problems, coerced)
    return fitted


def _allows_null(spec: Any) -> bool:
    kinds = _kinds(spec) if isinstance(spec, dict) else None
    return kinds is not None and "null" in kinds


def check_arguments(arguments: Any, parameters: Any) -> CheckedArguments:
    """`arguments` against `parameters` (a function schema's "parameters"). A schema that is not
    an object with properties checks nothing; arguments that are not an object are left to the
    tool, which already answers that."""
    if not isinstance(arguments, dict) or not isinstance(parameters, dict) or not isinstance(parameters.get("properties"), dict):
        return CheckedArguments(arguments if isinstance(arguments, dict) else {})
    problems: list[str] = []
    coerced: list[str] = []
    fitted = _fit_object(arguments, parameters, "", 0, problems, coerced)
    return CheckedArguments(fitted, problems, coerced)


def refusal(name: str, checked: CheckedArguments, received: dict[str, Any]) -> str:
    """What the model reads for a call refused before it ran."""
    text = json.dumps(received, ensure_ascii=False, default=str)
    if len(text) > RECEIVED_CHARS:
        text = text[: RECEIVED_CHARS - 1] + "…"
    return (
        f"Tham số của {name} chưa đúng nên chưa chạy: {'; '.join(checked.problems)}. "
        f"Đã nhận: {text}. Gọi lại {name} với tham số đúng theo mô tả công cụ."
    )
