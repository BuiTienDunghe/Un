"""Paired, isolated ChatService evaluation. Default prepares a manifest only.

External systems are fixtures; only --execute may contact a local Ollama.
This is a product continuity check, not BFCL or a model-selection benchmark.
"""
from __future__ import annotations

import argparse
import copy
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import statistics
from time import perf_counter
from types import SimpleNamespace
from urllib.parse import urlparse
import yaml

from app.discord.remind_tool import REMIND_SCHEMA
from app.discord.speaker_context import DISCORD_SPEAKER_SYSTEM_INSTRUCTION, build_discord_speaker_context
from app.llm_clients.ollama_client import OllamaClient
from app.llm_clients.usage import consume_usage, record_usage
from app.services.agent_service import AgentService, AgentTool, core_tools
from app.services.approvals import ApprovalNotice
from app.services.chat_service import ChatService
from app.services.context_budget import context_budget_from_config
from app.services.injection_defense import InjectionDefense
from app.services.model_router import ModelRouter
from app.services.pastes import inline_ceiling
from scripts.eval_state_store import MemoryStore

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = ROOT / "data/benchmarks/tool_state/v1/cases.json"
DEFAULT_MODELS = ["qwen3.5:9b", "lfm3:1.7b", "qwen3.5:2b"]


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(cases):
    app = ROOT / "backend/app"
    files = sorted(set(app.rglob("*.py")) | set((app / "prompts").glob("*.md")) |
                   set((app / "config").glob("*.yaml")) | set((ROOT / "backend/scripts").glob("*.py")))
    return {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in files} | {
        "cases": hashlib.sha256(cases.read_bytes()).hexdigest()}


class FixtureDocuments:
    def __init__(self, documents):
        self.documents = documents
    def retrieve(self, query, top_k, ignored):
        return [{"document_id": key, "version_id": doc["version"], "filename": key + ".txt",
                 "chunk_index": 0, "content": doc["content"], "page": 1, "score": 1.0}
                for key, doc in sorted(self.documents.items())][:top_k]
    def read_chunks(self, ident, start, count):
        doc = self.documents.get(ident)
        if doc is None:
            return None
        return {"document_id": ident, "version_id": doc["version"], "filename": ident + ".txt", "total_chunks": 1,
                "chunks": [{"chunk_index": 0, "content": doc["content"], "page_start": 1, "page_end": 1}] if start == 0 else []}
    def chunks_on_page(self, ident, page, count):
        return self.read_chunks(ident, 0 if page == 1 else 1, count)


class ObservedRouter(ModelRouter):
    def __init__(self, client, config):
        super().__init__({"ollama": client}, {"general": config})
        self.measurements = []
    def _observe(self, kind, messages, schemas, operation):
        row = {"kind": kind, "message_chars": len(encoded(messages)), "schema_chars": len(encoded(schemas))}
        start = perf_counter()
        try:
            result = operation()
            usage = consume_usage()
            record_usage(usage["tokens_in"], usage["tokens_out"])
            row.update(usage, status="ok")
            return result
        except Exception:
            row.update(status="failed", tokens_in=None, tokens_out=None)
            raise
        finally:
            row["latency_ms"] = (perf_counter() - start) * 1000
            self.measurements.append(row)
    def chat(self, mode, messages, options=None):
        return self._observe("chat", messages, [], lambda: super(ObservedRouter, self).chat(mode, messages, options))
    def chat_tools(self, mode, messages, tools):
        return self._observe("tools", messages, tools, lambda: super(ObservedRouter, self).chat_tools(mode, messages, tools))
    def chat_structured(self, mode, messages, schema):
        return self._observe("structured", messages, [schema], lambda: super(ObservedRouter, self).chat_structured(mode, messages, schema))


def grade(answer, steps, expected):
    normalized = " ".join(answer.casefold().split())
    names = [row.get("tool_name") for row in steps or [] if row.get("kind") == "tool_call"]
    failures = []
    if not normalized:
        failures.append("empty_answer")
    for value in expected.get("contains", []):
        if " ".join(value.casefold().split()) not in normalized:
            failures.append("missing:" + value)
    for value in expected.get("excludes", []):
        if " ".join(value.casefold().split()) in normalized:
            failures.append("unexpected:" + value)
    for alternatives in expected.get("contains_any", []):
        if not any(" ".join(value.casefold().split()) in normalized for value in alternatives):
            failures.append("missing_any:" + "|".join(alternatives))
    if expected.get("no_tools") and names:
        failures.append("unnecessary_tools")
    for name in expected.get("required_tools", []):
        if name not in names:
            failures.append("missing_tool:" + name)
    for name, count in expected.get("tool_counts", {}).items():
        if names.count(name) != count:
            failures.append("tool_count:" + name)
    return {"pass": not failures, "failures": failures}


def run_case(case, client, model, enabled, temperature, seed):
    documents = {row["id"]: copy.deepcopy(row) for row in case.get("documents", [])}
    store, fixtures = MemoryStore(documents), FixtureDocuments(documents)
    config = {"provider": "ollama", "name": model, "context": 16384, "temperature": temperature,
              "top_p": 0.9, "seed": seed, "think": False, "keep_alive": "5m"}
    router = ObservedRouter(client, config)
    registry = core_tools()
    actions = []
    def remind(agent, arguments, context):
        if not isinstance(arguments.get("text"), str) or not arguments["text"].strip() or bool(arguments.get("in_minutes")) == bool(arguments.get("at")):
            return "invalid reminder arguments; not scheduled", "BAD_ARGUMENTS", None
        actions.append(copy.deepcopy(arguments))
        return encoded({"status": "scheduled", "reminder_id": "fixture-" + str(len(actions)), **arguments}), None, None
    if case["surface"] == "discord":
        registry.register(AgentTool(REMIND_SCHEMA, remind, state_policy="receipt"), 60)
    if case.get("approval"):
        schema = {"type": "function", "function": {"name": "delete_record", "description": "Xóa hồ sơ; cần người dùng duyệt trước khi chạy.",
            "parameters": {"type": "object", "properties": {"document_id": {"type": "string"}}, "required": ["document_id"]}}}
        def delete_record(agent, arguments, context):
            actions.append(copy.deepcopy(arguments))
            documents.pop(arguments["document_id"], None)
            return "deleted", None, None
        registry.register(AgentTool(schema, delete_record, requires_approval=True, state_policy="receipt"), 70)
    chat = ChatService(store, router, SimpleNamespace(log_request=lambda *a, **k: None), 20, tool_state_enabled=enabled)
    policy = yaml.safe_load((ROOT / "backend/app/config/models.yaml").read_text(encoding="utf-8"))["agent"]
    if policy["max_steps"] != 3:
        raise ValueError("this registered comparison freezes max_steps=3")
    chat.agent_service = AgentService(router, fixtures, SimpleNamespace(health=lambda: {"status": "ok"}),
        max_steps=3, registry=registry, document_reader=fixtures, defense=InjectionDefense(enabled=True),
        tool_result_max_chars=policy["tool_result_max_chars"], read_result_max_chars=policy["read_result_max_chars"],
        turn_budget_seconds=policy["turn_budget_seconds"], final_reserve_seconds=policy["final_reserve_seconds"],
        inline_max_tokens=inline_ceiling(config), context_budget=context_budget_from_config(policy.get("context_budget"), config),
        lookup_check=policy.get("lookup_check", False), read_on_check=policy.get("read_on_check", False),
        read_rest=policy.get("read_rest", False))
    if case.get("approval"):
        chat.agent_service.approvals = SimpleNamespace(request=lambda *args: ApprovalNotice("fixture-approval", "Yêu cầu đang chờ bạn duyệt; chưa xóa hồ sơ."))
    results, previous = [], []
    for index, turn in enumerate(case["turns"]):
        for update in turn.get("update_documents", []):
            if update.get("deleted"):
                documents.pop(update["id"], None)
            else:
                documents[update["id"]] = copy.deepcopy(update)
        before = len(router.measurements)
        start = perf_counter()
        if case["surface"] == "web":
            answer, _, _, _, steps = chat.respond(turn["message"], "case", use_tools=True, user_id="fixture-actor")
        else:
            current = SimpleNamespace(id=str(index), request_text=turn["message"], response_text=None,
                author_id="fixture-actor", author_display_name="Người kiểm tra", reply_to_discord_message_id=None, status="completed")
            speaker = build_discord_speaker_context(previous, current)
            # Same trusted slots as DiscordTurnService, no text matching.
            context = {"guild_id": "fixture-guild", "actor_id": current.author_id, "turn_id": current.id,
                       "_state_anchors": [{"origin": row.id, "index": 2*n+1} for n, row in enumerate(previous)]}
            captured = []
            original = store.add_agent_traces
            store.add_agent_traces = lambda key, ident, rows, **kw: captured.extend(rows)
            answer, _, _, _ = chat.respond_with_context(turn["message"], "case", model_history=speaker.history,
                current_model_message=speaker.current_message, context_system_prompt=DISCORD_SPEAKER_SYSTEM_INSTRUCTION,
                use_tools=True, tool_context=context)
            store.add_agent_traces = original
            steps = captured
            current.response_text = answer
            previous.append(current)
        results.append({"turn": index, "answer": answer, "grade": grade(answer, steps, turn["expect"]),
                        "latency_ms": (perf_counter()-start)*1000, "calls": router.measurements[before:],
                        "tool_calls": [row for row in steps or [] if row.get("kind") == "tool_call"]})
    expected_actions = case.get("expected_actions")
    actions_ok = expected_actions is None or len(actions) == expected_actions
    return {"pass": actions_ok and all(row["grade"]["pass"] for row in results), "turns": results,
            "actions": actions, "envelopes": len(store.states)}


def jobs(cases, models):
    for model in models:
        for temperature, seeds in [(0, [42]), (0.4, [42, 43, 44])]:
            for seed in seeds:
                for index, case in enumerate(cases):
                    for enabled in ([False, True] if index % 2 == 0 else [True, False]):
                        yield {"model": model, "temperature": temperature, "seed": seed, "case_id": case["id"], "enabled": enabled}


def summarize(rows, planned, cases):
    arms, paired = {}, {}
    critical = {case["id"] for case in cases if case.get("critical")}
    for row in rows:
        key = (row["model"], row["temperature"], row["seed"], row["enabled"])
        arms.setdefault(key, []).append(row)
        paired.setdefault(key[:3] + (row["case_id"],), {})[row["enabled"]] = row
    results = []
    for key, group in arms.items():
        turns = [turn for row in group for turn in row.get("turns", [])]
        times = sorted(turn["latency_ms"] for turn in turns)
        calls = [call for turn in turns for call in turn["calls"]]
        results.append({"model": key[0], "temperature": key[1], "seed": key[2], "enabled": key[3],
            "cases": len(group), "passed": sum(row.get("pass", False) for row in group),
            "critical_failures": [row["case_id"] for row in group if row["case_id"] in critical and not row.get("pass", False)],
            "model_calls": len(calls), "message_chars": sum(call["message_chars"] for call in calls),
            "schema_chars": sum(call["schema_chars"] for call in calls),
            "tokens_in_reported": sum(call["tokens_in"] or 0 for call in calls),
            "tokens_in_missing": sum(call["tokens_in"] is None for call in calls),
            "tokens_out_reported": sum(call["tokens_out"] or 0 for call in calls),
            "tokens_out_missing": sum(call["tokens_out"] is None for call in calls),
            "p50_turn_ms": statistics.median(times) if times else None,
            "p95_turn_ms": times[math.ceil(len(times)*0.95)-1] if times else None})
    pairs = []
    for key, variants in paired.items():
        if set(variants) != {False, True}:
            continue
        old, new = variants[False], variants[True]
        pairs.append({"model": key[0], "temperature": key[1], "seed": key[2], "case_id": key[3],
                      "old_pass": old.get("pass", False), "new_pass": new.get("pass", False),
                      "infrastructure_ok": old["status"] == new["status"] == "completed"})
    return {"planned": planned, "completed": sum(row["status"] == "completed" for row in rows),
            "failed": sum(row["status"] == "failed" for row in rows), "arms": results, "pairs": pairs}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="explicitly allow local model inference; never pulls models")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--ollama", default="http://127.0.0.1:11434")
    args = parser.parse_args(argv)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not cases or len({row["id"] for row in cases}) != len(cases):
        raise ValueError("cases must have unique IDs")
    plan = {"version": 1, "files": fingerprint(args.cases), "jobs": list(jobs(cases, args.models)),
            "max_steps": 3, "context": 16384, "think": False, "defense": True,
            "ollama": args.ollama, "fixture": "isolated external tools; real ChatService/AgentService"}
    plan_hash = hashlib.sha256(encoded(plan).encode()).hexdigest()
    manifest_path = args.out / "manifest.json"
    if args.resume:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["plan_hash"] != plan_hash:
            raise ValueError("frozen code/data/options changed; use a new run directory")
    else:
        args.out.mkdir(parents=True, exist_ok=False)
        manifest = {"created_at": datetime.now(UTC).isoformat(), "plan_hash": plan_hash, "plan": plan, "executed": False}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.execute:
        print(encoded({"prepared": True, "inference": False, "jobs": len(plan["jobs"]), "plan_hash": plan_hash}))
        return 0
    endpoint = urlparse(args.ollama)
    if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("this evaluator permits only local Ollama")
    import httpx
    tags = httpx.get(args.ollama.rstrip("/") + "/api/tags", timeout=5).raise_for_status().json()
    digests = {row["name"]: row["digest"] for row in tags.get("models", [])}
    selected = {name: digests[name] for name in args.models}  # fail before inference if a tag is absent
    if manifest.get("models") and manifest["models"] != selected:
        raise ValueError("model digest changed since the previous execution")
    manifest.update(models=selected, executed=True,
        ollama_version=httpx.get(args.ollama.rstrip("/") + "/api/version", timeout=5).raise_for_status().json())
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    result_path = args.out / "results.jsonl"
    latest = {}
    if result_path.exists():
        for line in result_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            latest[row["job_id"]] = row
    by_id = {row["id"]: row for row in cases}
    client = OllamaClient(args.ollama, chat_timeout=90, health_timeout=5, retry_count=0)
    for job in plan["jobs"]:
        ident = hashlib.sha256(encoded(job).encode()).hexdigest()
        if latest.get(ident, {}).get("status") == "completed":
            continue
        row = {"job_id": ident, **job, "started_at": datetime.now(UTC).isoformat()}
        try:
            row.update(run_case(by_id[job["case_id"]], client, job["model"], job["enabled"], job["temperature"], job["seed"]), status="completed")
        except Exception as error:
            row.update(status="failed", pass_result=False, error_type=type(error).__name__)
        row["finished_at"] = datetime.now(UTC).isoformat()
        with result_path.open("a", encoding="utf-8") as stream:
            stream.write(encoded(row) + "\n")
            stream.flush()
        latest[ident] = row
        print(encoded({"job_id": ident, "status": row["status"]}), flush=True)
    summary = summarize(list(latest.values()), len(plan["jobs"]), cases)
    (args.out / "summary.json").write_text(encoded(summary), encoding="utf-8")
    return int(summary["failed"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
