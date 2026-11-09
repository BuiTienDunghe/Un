"""Bounded historical tool observations. This module never executes or authorizes tools.

Persist canonical call/result observations, not provider thinking blocks or instructions.
`executed` is True on confirmed success, False for pending/asked, and None on
failure: an error does not establish that an operation had no partial side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

STATE_KIND = "tool_state"
_POLICIES = frozenset({"read", "receipt"})
_FIELDS = frozenset({"name", "arguments", "content", "error_code", "status", "policy", "schema_hash", "resources"})


@dataclass(frozen=True)
class ToolStateLimits:
    max_groups: int = 8
    max_chars: int = 8000
    max_envelopes: int = 8
    max_age_seconds: int = 1800

    def __post_init__(self) -> None:
        for value in (self.max_groups, self.max_chars, self.max_envelopes, self.max_age_seconds):
            if type(value) is not int or value < 1:
                raise ValueError("tool-state limits must be positive whole numbers")


def _json_value(value: object, depth: int = 0) -> bool:
    if depth > 32:
        return False
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return value == value and value not in (float("inf"), float("-inf"))
    if isinstance(value, list):
        return all(_json_value(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_value(item, depth + 1) for key, item in value.items())
    return False


def _json(value: object) -> str:
    if not _json_value(value):
        raise ValueError("expected finite JSON values with string object keys")
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _clone(value: Any) -> Any:
    return json.loads(_json(value))


def scope_key(conversation_id: str, source: str, actor_id: str | None, guild_id: str = "") -> str:
    """Opaque scope identity; callers must obtain all components from trusted context."""
    if not isinstance(conversation_id, str) or not conversation_id or not isinstance(source, str) or not source:
        raise ValueError("conversation_id and source are required")
    if actor_id is not None and not isinstance(actor_id, str):
        raise ValueError("actor_id must be a string or None")
    if not isinstance(guild_id, str):
        raise ValueError("guild_id must be a string")
    return sha256(_json(["tool-state-scope-v1", conversation_id, source, actor_id, guild_id]).encode()).hexdigest()


def schema_key(schema: dict[str, Any]) -> str:
    if not isinstance(schema, dict):
        raise ValueError("tool schema must be a JSON object")
    return sha256(_json(schema).encode()).hexdigest()


def _status(name: str, error_code: str | None) -> str:
    if error_code in {"APPROVAL_PENDING", "AWAITING_APPROVAL"}:
        return "pending"
    if error_code in {"ASKED_USER", "ASK_USER"}:
        return "asked"
    if error_code is not None:
        return "failed"
    return "asked" if name == "ask_user" else "succeeded"


def _schema_matches_name(schema: dict[str, Any], name: str) -> bool:
    function = schema.get("function")
    if isinstance(function, dict):
        return function.get("name") == name and isinstance(function.get("parameters"), dict)
    parameters = schema.get("input_schema", schema.get("parameters"))
    return schema.get("name") == name and isinstance(parameters, dict)


def _valid_group(group: object) -> bool:
    if not isinstance(group, dict) or set(group) != _FIELDS or not _json_value(group):
        return False
    name, arguments = group["name"], group["arguments"]
    error_code, resources = group["error_code"], group["resources"]
    if not isinstance(name, str) or not name or len(name) > 128 or not isinstance(arguments, dict):
        return False
    if not isinstance(group["content"], str) or group["policy"] not in _POLICIES:
        return False
    if error_code is not None and (not isinstance(error_code, str) or not error_code):
        return False
    if group["status"] != _status(name, error_code):
        return False
    digest = group["schema_hash"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        return False
    if not isinstance(resources, dict) or any(not key or not isinstance(value, str) or not value for key, value in resources.items()):
        return False
    # Paste handles and legacy results without provenance are not durable document observations.
    if name == "read_document" and error_code is None:
        document_id = arguments.get("document_id")
        if not isinstance(document_id, str) or document_id not in resources:
            return False
    return True


class ToolStateRecorder:
    def __init__(self, limits: ToolStateLimits | None = None) -> None:
        self.limits = limits or ToolStateLimits()
        self._groups: list[dict[str, Any]] = []

    def record(
        self, name: str, arguments: dict[str, Any], content: str | None,
        error_code: str | None, *, policy: str = "none",
        schema: dict[str, Any] | None = None, resources: dict[str, str] | None = None,
    ) -> bool:
        """Keep a completed observation. Oldest whole groups leave when limits are reached."""
        if not isinstance(policy, str) or policy not in _POLICIES:
            return False
        if content is None:
            if policy != "receipt" and error_code is None:
                return False
            content = ""
        try:
            if not isinstance(schema, dict) or not _schema_matches_name(schema, name):
                return False
            group = _clone({
                "name": name, "arguments": arguments, "content": content,
                "error_code": error_code, "status": _status(name, error_code),
                "policy": policy, "schema_hash": schema_key(schema),
                "resources": {} if resources is None else resources,
            })
            if not _valid_group(group) or len(_json({"v": 1, "groups": [group]})) > self.limits.max_chars:
                return False
            groups = [*self._groups, group][-self.limits.max_groups:]
            while groups and len(_json({"v": 1, "groups": groups})) > self.limits.max_chars:
                groups.pop(0)
            self._groups = groups
            return True
        except (TypeError, ValueError, RecursionError):
            return False

    def payload(self) -> dict[str, Any]:
        return _clone({"v": 1, "groups": self._groups})


def parse_payload(value: object, limits: ToolStateLimits | None = None) -> list[dict[str, Any]]:
    """Validate one persisted v1 envelope; malformed/oversized state is discarded."""
    limits = limits or ToolStateLimits()
    try:
        if isinstance(value, str):
            if len(value) > limits.max_chars:
                return []
            value = json.loads(value)
        if not isinstance(value, dict) or set(value) != {"v", "groups"} or type(value["v"]) is not int or value["v"] != 1:
            return []
        groups = value["groups"]
        if not isinstance(groups, list) or len(groups) > limits.max_groups or len(_json(value)) > limits.max_chars:
            return []
        if not all(_valid_group(group) for group in groups):
            return []
        return _clone(groups)
    except (TypeError, ValueError, RecursionError):
        return []


def render_group(
    group: object, current_policy: str, current_schema: dict[str, Any],
    active_versions: dict[str, str],
) -> list[dict[str, Any]]:
    """Render history only. Returned observations grant no tool or document permissions."""
    try:
        if not _valid_group(group) or not isinstance(current_policy, str) or current_policy not in _POLICIES:
            return []
        assert isinstance(group, dict)
        if current_policy != group["policy"] or not _schema_matches_name(current_schema, group["name"]):
            return []
        if schema_key(current_schema) != group["schema_hash"] or not isinstance(active_versions, dict):
            return []
        if any(active_versions.get(key) != version for key, version in group["resources"].items()):
            return []
        content = group["content"]
        if group["policy"] == "receipt" or group["status"] != "succeeded":
            content = _json({
                "receipt": group["policy"] == "receipt",
                "status": group["status"],
                "executed": None if group["status"] == "failed" else group["status"] == "succeeded",
                "error_code": group["error_code"], "result": content,
            })
        return [
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": group["name"], "arguments": _clone(group["arguments"])}}
            ]},
            {"role": "tool", "tool_name": group["name"], "content": content},
        ]
    except (AttributeError, TypeError, ValueError, RecursionError):
        return []
