"""Replay bounded observations; loading history never dispatches a tool."""
import json

from app.services.tool_state import ToolStateLimits, parse_payload, render_group, scope_key


def history_budget(messages, schemas, guide, window):
    """Conservative character allowance shared by chat and evaluation adapters."""
    base_chars = len(json.dumps(messages, ensure_ascii=False))
    schema_chars = len(json.dumps(schemas, ensure_ascii=False))
    return {"base_chars": base_chars, "schema_chars": schema_chars,
            "room": max(0, int(window) * 2 - base_chars - schema_chars - len(guide) - 4096)}


def continuity_scope(conversation_id, user_id, context):
    context = context or {}
    epoch = context.get("_memory_epoch")
    if epoch is not None:
        conversation_id = f"{conversation_id}:memory-epoch:{epoch}"
    if context.get("guild_id"):
        if not context.get("actor_id"):
            return None
        return scope_key(conversation_id, "discord", str(context["actor_id"]), str(context["guild_id"]))
    return scope_key(conversation_id, "web", str(user_id or "local"))


def restore_history(store, conversation_id, scope, messages, prefix, history_rows, context, registry, max_chars, allowed_names=None):
    """Select newest complete groups, then insert at their original answer slots."""
    limits = ToolStateLimits()
    stats = {"groups": 0, "chars": 0, "dropped": 0}
    if scope is None or max_chars <= 0:
        return messages, stats
    anchors = {}
    ids = []
    origins = []
    if (context or {}).get("guild_id"):
        for row in (context or {}).get("_state_anchors", []):
            if isinstance(row, dict) and isinstance(row.get("index"), int):
                anchors[str(row.get("origin"))] = row["index"]
                origins.append(str(row.get("origin")))
    else:
        for index, row in enumerate(history_rows):
            if row.get("role") == "assistant" and isinstance(row.get("message_id"), int):
                anchors[row["message_id"]] = index
                ids.append(row["message_id"])
    records = store.load_tool_states(conversation_id, scope, message_ids=ids, origins=origins)
    candidates = []
    dependencies = set()
    for record in records:
        anchor = record.get("origin") if origins else record.get("message_id")
        if anchor not in anchors:
            continue
        index = anchors[anchor]
        if index < 0 or prefix + index >= len(messages) or messages[prefix+index].get("role") != "assistant":
            continue
        groups = parse_payload(record.get("payload"), limits)
        for position, group in enumerate(groups):
            dependencies.update(group.get("resources", {}))
            candidates.append((index, position, group))
    versions = store.state_document_versions(dependencies) if dependencies else {}
    selected = []
    seen = set()
    for index, position, group in sorted(candidates, key=lambda row: (row[0], row[1]), reverse=True):
        if (index, position) in seen:
            continue
        seen.add((index, position))
        tool = registry.get(group.get("name"))
        if tool is None or (allowed_names is not None and tool.name not in allowed_names):
            stats["dropped"] += 1
            continue
        pair = render_group(group, tool.state_policy, tool.schema, versions)
        if not pair:
            stats["dropped"] += 1
            continue
        size = len(json.dumps(pair, ensure_ascii=False, separators=(",", ":")))
        if stats["groups"] >= limits.max_groups or stats["chars"] + size > min(max_chars, limits.max_chars):
            stats["dropped"] += 1
            continue
        stats["groups"] += 1
        stats["chars"] += size
        if tool.state_policy == "receipt":
            pair[-1]["_tool_state_receipt"] = True
        selected.append((index, position, pair))
    slots = {}
    for index, position, pair in sorted(selected, key=lambda row: (row[0], row[1])):
        slots.setdefault(prefix+index, []).extend(pair)
    expanded = []
    for index, message in enumerate(messages):
        expanded.extend(slots.get(index, []))
        expanded.append(message)
    return expanded, stats
