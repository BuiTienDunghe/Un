"""Synthetic fixed-call overhead, not model intelligence or real response speed."""
import argparse
import json
from pathlib import Path
import statistics
from time import perf_counter
from types import SimpleNamespace
from uuid import uuid4

from loguru import logger
from sqlalchemy import delete, event, select, func
from app.llm_clients.ollama_client import OllamaClient
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import AgentTrace, AgentTraceSummary, Conversation
from app.services.agent_service import AgentService
from app.services.chat_service import ChatService
from app.stores.postgres_auxiliary_store import PostgresAuxiliaryStore
from scripts.tool_state_eval import ObservedRouter
from tests.database_support import validate_postgres_test_url


class ScriptedClient(OllamaClient):
    def __init__(self):
        self.round = 0
    def chat_tools(self, **kwargs):
        self.round += 1
        if self.round % 2:
            arguments = {"expression": str((self.round+1)//2) + "+1"}
            call = {"name": "calculate", "arguments": arguments}
            return {"content": "", "tool_calls": [call], "raw_tool_calls": [{"function": call}]}
        return {"content": "done", "tool_calls": [], "raw_tool_calls": []}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    engine = create_postgres_engine(validate_postgres_test_url(args.database))
    sessions = create_session_factory(engine)
    store = PostgresAuxiliaryStore(sessions)
    prefix = "state-bench-" + uuid4().hex
    rows = []
    sql = []
    logger.remove()
    def query(_conn, _cursor, statement, _parameters, _context, _many):
        sql.append(statement.split(None, 1)[0])
    event.listen(engine, "before_cursor_execute", query)
    try:
        # Alternate arm order to reduce the connection/filesystem warmup bias.
        for repeat in range(6):
            for enabled in ([False, True] if repeat % 2 == 0 else [True, False]):
                key = prefix + "-" + str(repeat) + "-" + str(enabled)
                store.create_conversation(key)
                config = {"provider": "ollama", "name": "scripted-no-inference", "context": 16384, "think": False}
                router = ObservedRouter(ScriptedClient(), config)
                chat = ChatService(store, router, SimpleNamespace(log_request=lambda *a, **k: None), 20, tool_state_enabled=enabled)
                chat.agent_service = AgentService(router, None, None, max_steps=3)
                for turn in range(12):
                    sql.clear()
                    before = len(router.measurements)
                    start = perf_counter()
                    answer, *_ = chat.respond("calculate the requested expression", key, use_tools=True)
                    elapsed = (perf_counter()-start)*1000
                    assert answer == "done"
                    calls = router.measurements[before:]
                    assert len(calls) == 2
                    rows.append({"enabled": enabled, "repeat": repeat, "turn": turn, "latency_ms": elapsed,
                        "sql_statements": len(sql), "model_calls": len(calls),
                        "message_chars": sum(row["message_chars"] for row in calls),
                        "schema_chars": sum(row["schema_chars"] for row in calls)})
                with sessions() as session:
                    count = session.scalar(select(func.count()).select_from(AgentTrace).where(
                        AgentTrace.conversation_id == key, AgentTrace.kind == "tool_state"))
                assert count == (8 if enabled else 0)
        summary = {}
        for enabled in [False, True]:
            group = [row for row in rows if row["enabled"] is enabled]
            times = sorted(row["latency_ms"] for row in group)
            summary[str(enabled)] = {"turns": len(group), "p50_ms": statistics.median(times),
                "p95_ms": times[int(len(times)*0.95)], "model_calls": sum(row["model_calls"] for row in group),
                "message_chars": sum(row["message_chars"] for row in group),
                "schema_chars": sum(row["schema_chars"] for row in group),
                "median_sql_statements": statistics.median(row["sql_statements"] for row in group)}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"scope": "synthetic scripted client, real PostgreSQL; not model quality or inference latency",
            "summary": summary, "rows": rows}, indent=2), encoding="utf-8")
        print(json.dumps(summary))
    finally:
        event.remove(engine, "before_cursor_execute", query)
        with sessions.begin() as session:
            session.execute(delete(Conversation).where(Conversation.id.startswith(prefix)))
            session.execute(delete(AgentTraceSummary).where(AgentTraceSummary.conversation_id.startswith(prefix)))
        engine.dispose()


if __name__ == "__main__":
    main()
