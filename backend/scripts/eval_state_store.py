"""Disposable per-case storage for evaluators, never the production adapter."""
import copy
import json
from time import monotonic

from app.services.tool_state import ToolStateLimits


class MemoryStore:
    def __init__(self, documents=None, *, clock=monotonic):
        self.messages, self.states = [], []
        self.documents = documents if documents is not None else {}
        self.clock = clock
    def conversation_exists(self, key):
        return key == "case"
    def get_messages(self, key, limit):
        return [{k: row[k] for k in ("role", "content")} for row in self.messages[-limit:]]
    def get_agent_history(self, key, limit):
        return copy.deepcopy(self.messages[-limit:])
    def add_message(self, key, role, content, *args):
        ident = len(self.messages) + 1
        self.messages.append({"message_id": ident, "role": role, "content": content})
        return ident
    def add_agent_traces(self, *args, **kwargs):
        pass
    def save_tool_state(self, key, ident, scope, payload, origin=None):
        limits = ToolStateLimits()
        if not payload.get("groups") or len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) > limits.max_chars:
            return
        self.states = [row for row in self.states if row["message_id"] != ident and
                       self.clock() - row["created_at"] <= limits.max_age_seconds]
        self.states.append({"message_id": ident, "scope": scope, "origin": origin,
                            "payload": copy.deepcopy(payload), "created_at": self.clock()})
        self.states = self.states[-limits.max_envelopes:]
    def load_tool_states(self, key, scope, *, message_ids=None, origins=None):
        return [copy.deepcopy(row) for row in reversed(self.states) if row["scope"] == scope and
                self.clock() - row["created_at"] <= ToolStateLimits().max_age_seconds and
                (row["message_id"] in (message_ids or []) or row["origin"] in (origins or []))]
    def state_document_versions(self, ids):
        return {ident: doc["version"] for ident, doc in self.documents.items() if ident in ids}
