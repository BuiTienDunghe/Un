"""Agent Eval v0: the agent's own exam (ticket 06, spec "Mốc 2").

Runs each task of data/benchmarks/agent_eval/<version>/ through the REAL
AgentService.run() and the REAL general model (ModelRouter built from the
active model version), with three fake backends behind the agent's Protocols:
document retrieval replayed from a fixture, one fixed fake Discord guild, and a
system-status snapshot. It measures tool choice, arguments, use of the results,
stopping and the final answer. It does NOT measure retrieval quality, persona,
memory context or the SSE path: those have their own evals or none yet.

    cd backend
    python -m scripts.agent_eval                                  # shipped sampling (0.4, no seed)
    python -m scripts.agent_eval --temperature 0 --seed 42        # repeatable, for before/after
    python -m scripts.agent_eval --tasks doc-01,hist-01,hist-07   # a subset
    python -m scripts.agent_eval --probe --temperature 0 --seed 42  # a citable baseline
    python -m scripts.agent_eval --temperature 0 --seed 42 --unload-between-tasks  # each task as if run alone

Each run writes data/evaluation/results/agent_eval/<run_id>/ (gitignored):
manifest.json, task_results.jsonl, events.jsonl, summary.json. The agent's
tools never reach a database or Qdrant; the model is the only service called.
`--probe` adds the API's own startup probes (Ollama, Qdrant, Postgres) so the
manifest records `verified: true`, and refuses to run when the general model is
not the verified pointer. Run with PYTHONUTF8=1 on a cp1252 console.

Temperature and seed overrides live in this process only: the router gets a
copy of the resolved general config; models.yaml and model_versions.yaml are
never touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter, sleep
from types import SimpleNamespace
from typing import Any

from annotated_types import MaxLen

from app.llm_clients.usage import consume_usage
from app.schemas.chat_schema import ChatRequest
from app.discord.schema import DiscordTurnEnqueueRequest
from app.discord import agent_tools
from app.services.agent_service import AGENT_GUIDE, FINAL_RESERVE_SECONDS, READ_RESULT_MAX_CHARS, TURN_BUDGET_SECONDS, AgentService, core_tools
from app.discord.history_service import _SAFE_LEXEME, DiscordHistoryHit
from app.discord.speaker_context import DISCORD_SPEAKER_SYSTEM_INSTRUCTION, attributed_user_content
from app.services.injection_defense import InjectionDefense
from app.services.pastes import CHARS_PER_TOKEN, INLINE_FIXED_TOKENS, INLINE_MAX_TOKENS
from app.utils.vi_tokenizer import tokenize_vietnamese
from scripts.agent_eval_grader import GRADER_VERSION, grade, summarize, tool_calls
from scripts.agent_eval_scorecard import render, scorecard

BACKEND = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND.parent
DATASET_DIR = PROJECT_ROOT / "data" / "benchmarks" / "agent_eval" / "v0"
RESULTS_DIR = PROJECT_ROOT / "data" / "evaluation" / "results" / "agent_eval"
SYSTEM_PROMPT_PATH = BACKEND / "app" / "prompts" / "general_system.md"

# Hashed in this order; README.md and retrieval_manifest.json describe the data
# and never move the hash.
DATA_FILES = ("dataset.json", "tasks.jsonl", "retrieval.jsonl", "documents.jsonl")
CATEGORIES = ("documents", "history", "status", "no_tool")
SURFACES = ("web", "discord")
# pending = a real-corpus question whose retrieval is not recorded yet
# (scripts.agent_eval_record_retrieval); the runner refuses to replay it.
RETRIEVAL_SOURCES = ("handwritten", "recorded", "pending")
NO_SEED = "không seed"


def _max_length(request: type, field: str) -> int:
    return next(item.max_length for item in request.model_fields[field].metadata if isinstance(item, MaxLen))


# The API refuses a longer message before the agent runs (422), so the eval does
# too (ticket 20, v0.3). Read from the request schemas, so a changed limit moves
# the eval with it.
INPUT_MAX_CHARS = {
    "web": _max_length(ChatRequest, "message"),
    "discord": _max_length(DiscordTurnEnqueueRequest, "message"),
}
# Settings refuses to exist without a PostgreSQL URL; this run opens no
# database, so a placeholder satisfies the validator and is never dialled.
PLACEHOLDER_DATABASE_URL = "postgresql+psycopg://agent-eval@unused/none"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── dataset ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Dataset:
    version: str
    sha256: str
    path: Path
    tasks: list[dict[str, Any]]
    guild: dict[str, Any]
    status_snapshots: dict[str, dict[str, Any]]
    retrieval: dict[str, dict[str, Any]]
    # Whole documents (v0.3, ticket 20 #1): what a read past the 400-character
    # preview returns. Every recorded chunk is one of these, verbatim.
    documents: dict[str, dict[str, Any]]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_dataset(directory: Path) -> Dataset:
    """Read and cross-check one dataset version; refuses a malformed one
    before any model call is paid for."""
    digest = hashlib.sha256()
    for name in DATA_FILES:
        # autocrlf checks these out as CRLF on Windows; hash the LF bytes git
        # stores so the same commit gives the same hash on every machine.
        data = (directory / name).read_bytes().replace(b"\r\n", b"\n")
        digest.update(name.encode() + b"\0" + data + b"\0")
    meta = json.loads((directory / "dataset.json").read_text(encoding="utf-8"))
    tasks = _read_jsonl(directory / "tasks.jsonl")
    retrieval = {fixture["task_id"]: fixture for fixture in _read_jsonl(directory / "retrieval.jsonl")}
    snapshots = meta["status_snapshots"]

    problems: list[str] = []
    ids = [task["id"] for task in tasks]
    problems += [f"id trùng: {task_id}" for task_id in sorted({i for i in ids if ids.count(i) > 1})]
    for task in tasks:
        if task.get("category") not in CATEGORIES:
            problems.append(f"{task['id']}: category {task.get('category')!r}")
        if task.get("surface", "web") not in SURFACES:
            problems.append(f"{task['id']}: surface {task.get('surface')!r}")
        if task.get("surface") == "discord" and not task.get("speaker"):
            problems.append(f"{task['id']}: discord cần speaker")
        if task.get("status_snapshot", "healthy") not in snapshots:
            problems.append(f"{task['id']}: không có snapshot {task.get('status_snapshot')!r}")
        if not task.get("expect"):
            problems.append(f"{task['id']}: thiếu expect")
    problems += [f"retrieval cho bài không tồn tại: {task_id}" for task_id in retrieval if task_id not in ids]
    problems += [f"{task_id}: source {f.get('source')!r}" for task_id, f in retrieval.items() if f.get("source") not in RETRIEVAL_SOURCES]
    documents = {document["document_id"]: document for document in _read_jsonl(directory / "documents.jsonl")}
    for document_id, document in documents.items():
        if [chunk["chunk_index"] for chunk in document["chunks"]] != list(range(len(document["chunks"]))):
            problems.append(f"{document_id}: chunk_index phải liên tục từ 0")
    # A readable chunk must be the document's own chunk, so reading it back
    # shows the agent the same text the search did.
    for task_id, fixture in retrieval.items():
        for chunk in fixture["chunks"]:
            if "document_id" not in chunk:
                continue
            document = documents.get(chunk["document_id"])
            chunks = document["chunks"] if document else []
            index = chunk.get("chunk_index")
            if not (isinstance(index, int) and 0 <= index < len(chunks) and chunks[index]["content"] == chunk["content"]):
                problems.append(f"{task_id}: đoạn {chunk['document_id']}#{index} không trùng documents.jsonl")
    if problems:
        raise ValueError(f"dataset {directory} hỏng: " + "; ".join(problems))
    return Dataset(
        version=str(meta["version"]),
        sha256=digest.hexdigest(),
        path=directory,
        tasks=tasks,
        guild=meta["guild"],
        status_snapshots=snapshots,
        retrieval=retrieval,
        documents=documents,
    )


# ── fake backends (the agent's Protocols, agent_service.py) ──────────────


class ReplayRetrieval:
    """One task's recorded (or hand-written) chunks, returned for ANY query:
    the model never repeats the recorded query verbatim, and what it asked is
    already in its tool_call step. Fixture order is rank order."""

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunks = chunks

    def retrieve(self, query: str, top_k: int, document_id: str | list[str] | None = None) -> list[dict[str, object]]:
        return [dict(chunk) for chunk in self.chunks[:top_k]]


class FixtureDocuments:
    """read_document over the dataset's whole documents (documents.jsonl), the way
    ChunkInspectionService serves the active version: by chunk_index from a start, or
    the chunks whose page range covers a page (none, for a document without pages)."""

    def __init__(self, documents: dict[str, dict[str, Any]]) -> None:
        self.documents = documents

    def _slice(self, document_id: str, chunks: list[dict[str, Any]]) -> dict[str, object] | None:
        document = self.documents.get(document_id)
        if document is None:
            return None
        return {
            "document_id": document_id,
            "filename": document["filename"],
            "total_chunks": len(document["chunks"]),
            "chunks": [dict(chunk) for chunk in chunks],
        }

    def read_chunks(self, document_id: str, from_chunk: int, n: int) -> dict[str, object] | None:
        chunks = (self.documents.get(document_id) or {}).get("chunks", [])
        return self._slice(document_id, [chunk for chunk in chunks if chunk["chunk_index"] >= from_chunk][: max(1, n)])

    def chunks_on_page(self, document_id: str, page: int, n: int) -> dict[str, object] | None:
        def covers(chunk: dict[str, Any]) -> bool:
            start, end = chunk.get("page_start"), chunk.get("page_end")
            return start is not None and start <= page and (end if end is not None else start) >= page

        chunks = (self.documents.get(document_id) or {}).get("chunks", [])
        return self._slice(document_id, [chunk for chunk in chunks if covers(chunk)][: max(1, n)])


class SnapshotStatus:
    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = snapshot

    def health(self) -> dict[str, object]:
        return json.loads(json.dumps(self.snapshot))


def _lexemes(text: str) -> set[str]:
    # The real search's lexemes (discord_history_service._or_query_text).
    return {cleaned for token in tokenize_vietnamese(text) if (cleaned := _SAFE_LEXEME.sub("", token))}


class FixtureHistory:
    """The fixed fake guild, searched the way DiscordHistoryService does it:
    OR of Vietnamese lexemes, densest match first; `recent` = the latest N in
    chronological order. `days` counts back from the fixture's own `now`, not
    the wall clock, so a task means the same thing next year."""

    def __init__(self, guild: dict[str, Any]) -> None:
        self.guild_id = str(guild["guild_id"])
        self.now = datetime.fromisoformat(guild["now"])
        self.hits = [
            DiscordHistoryHit(
                discord_message_id=str(message["id"]),
                channel_id=str(message["channel_id"]),
                thread_id=None,
                author_id=str(message["author_id"]),
                author_display_name=str(message["author_display_name"]),
                is_bot=bool(message.get("is_bot", False)),
                content=str(message["content"]),
                sent_at=datetime.fromisoformat(message["sent_at"]),
                link=f"https://discord.com/channels/{self.guild_id}/{message['channel_id']}/{message['id']}",
            )
            for message in guild["messages"]
        ]
        self._tokens = {hit.discord_message_id: _lexemes(hit.content) for hit in self.hits}

    def search(self, *, guild_id: str, query: str, author_id: str | None = None, days: int | None = None, limit: int = 5) -> list[object]:
        if guild_id != self.guild_id:
            return []
        wanted = _lexemes(query)
        scored = []
        for hit in self.hits:
            if author_id and hit.author_id != author_id:
                continue
            if days is not None and hit.sent_at < self.now - timedelta(days=days):
                continue
            score = len(wanted & self._tokens[hit.discord_message_id])
            if score:
                scored.append((score, hit.sent_at, hit))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [hit for _, _, hit in scored[:limit]]

    def recent(self, *, guild_id: str, limit: int = 20, author_id: str | None = None) -> list[object]:
        if guild_id != self.guild_id:
            return []
        hits = sorted((hit for hit in self.hits if not author_id or hit.author_id == author_id), key=lambda hit: hit.sent_at)
        return hits[-limit:]


# ── the router seam ──────────────────────────────────────────────────────


class UsageRecordingRouter:
    """Delegates to the real router and reads token usage after EVERY call.
    The usage ContextVar keeps only the last call (llm_clients/usage.py), so a
    three-round answer would otherwise report its final round alone. `chat`
    is wrapped too: an exhausted tool budget answers through it."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.rounds: list[dict[str, Any]] = []

    def _call(self, kind: str, call: Any) -> Any:
        consume_usage()  # a value left by an earlier failed call must not leak in
        started = perf_counter()
        try:
            return call()
        finally:
            self.rounds.append({"call": kind, **consume_usage(), "latency_ms": int((perf_counter() - started) * 1000)})

    def chat_tools(self, mode: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
        return self._call("chat_tools", lambda: self.inner.chat_tools(mode, messages, tools))

    def chat(self, mode: str, messages: list[dict[str, Any]], options: dict[str, Any] | None = None) -> tuple[str, str]:
        return self._call("chat", lambda: self.inner.chat(mode, messages, options))

    def take(self) -> list[dict[str, Any]]:
        rounds, self.rounds = self.rounds, []
        return rounds


def override_general(models: dict[str, dict[str, Any]], *, temperature: float | None = None, seed: int | None = None) -> dict[str, dict[str, Any]]:
    """A copy of the resolved models with the eval's sampling on `general`.
    Resolved.flat_models() is cached and shared, so it is never edited."""
    copied = {role: dict(config) for role, config in models.items()}
    if temperature is not None:
        copied["general"]["temperature"] = temperature
    if seed is not None:
        copied["general"]["seed"] = seed
    return copied


# ── one run ──────────────────────────────────────────────────────────────


def build_messages(task: dict[str, Any], system_prompt: str) -> list[dict[str, Any]]:
    """The messages chat_service.respond_with_context hands the agent: system
    prompt, the Discord context block on a guild turn, history, the user turn
    (speaker-labelled on Discord, exactly as discord_speaker_context does it)."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if task.get("surface") == "discord":
        messages.append({"role": "system", "content": DISCORD_SPEAKER_SYSTEM_INSTRUCTION})
    messages.extend(task.get("history") or [])
    content = task["input"]
    if task.get("surface") == "discord":
        speaker = task["speaker"]
        turn = SimpleNamespace(
            request_text=task["input"],
            response_text=None,
            author_id=speaker["author_id"],
            author_display_name=speaker["name"],
            reply_to_discord_message_id=None,
        )
        content = attributed_user_content(turn, current_speaker=True)
    messages.append({"role": "user", "content": content})
    return messages


def _sum(values: list[int | None]) -> int | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _aggregates(results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = sorted(result["latency_ms"] for result in results)
    tokens_in = [result["tokens_in"] for result in results if result["tokens_in"] is not None]
    tokens_out = [result["tokens_out"] for result in results if result["tokens_out"] is not None]
    return {
        "latency_ms": {
            "mean": round(statistics.fmean(latencies)) if latencies else None,
            "p50": round(statistics.median(latencies)) if latencies else None,
            "max": latencies[-1] if latencies else None,
        },
        "tokens_in_total": sum(tokens_in) if tokens_in else None,
        "tokens_out_total": sum(tokens_out) if tokens_out else None,
        "mean_tool_calls": round(statistics.fmean(len(r["tool_calls"]) for r in results), 2) if results else None,
        "budget_exhausted": sum(1 for result in results if result["budget_exhausted"]),
    }


def run_eval(
    dataset: Dataset,
    router: Any,
    *,
    out_dir: Path,
    agent_config: dict[str, float],
    defense: InjectionDefense,
    system_prompt: str,
    run_meta: dict[str, Any],
    task_ids: list[str] | None = None,
    progress: Any = print,
    reloader: Any = None,
) -> dict[str, Any]:
    """Run the tasks, grade them, write the four artifacts; returns the summary.

    Lines are appended task by task, so a run that dies half-way still leaves
    a readable manifest and every finished task on disk. With a reloader
    (--unload-between-tasks) the general model is unloaded and loaded again
    before every task, the first included; the load's time is the task's
    reload_ms, kept out of its latency_ms."""
    tasks = dataset.tasks
    if task_ids:
        unknown = sorted(set(task_ids) - {task["id"] for task in tasks})
        if unknown:
            raise ValueError(f"không có bài: {', '.join(unknown)}")
        tasks = [task for task in tasks if task["id"] in task_ids]
    # Replaying an empty pending fixture would turn a lookup into a "not found"
    # task without anyone noticing.
    pending = [task["id"] for task in tasks if dataset.retrieval.get(task["id"], {}).get("source") == "pending"]
    if pending:
        raise ValueError(f"chưa ghi truy xuất cho: {', '.join(pending)} (chạy scripts.agent_eval_record_retrieval)")
    out_dir.mkdir(parents=True, exist_ok=False)
    max_steps = int(agent_config["max_steps"])
    tool_result_max_chars = int(agent_config["tool_result_max_chars"])
    read_result_max_chars = int(agent_config.get("read_result_max_chars", READ_RESULT_MAX_CHARS))
    turn_budget_seconds = float(agent_config.get("turn_budget_seconds", TURN_BUDGET_SECONDS))
    final_reserve_seconds = float(agent_config.get("final_reserve_seconds", FINAL_RESERVE_SECONDS))
    history = FixtureHistory(dataset.guild)
    # The tools as the API offers them: the core's, plus app.discord's search_history
    # plugged in with the fixture guild (ticket 22, C4). The manifest's hash and the
    # grader's schemas are read off the very registry the agents run with.
    registry = core_tools()
    agent_tools.register(registry, history)
    manifest = {
        **run_meta,
        "max_steps": max_steps,
        "tool_result_max_chars": tool_result_max_chars,
        "read_result_max_chars": read_result_max_chars,
        "input_max_chars": INPUT_MAX_CHARS,
        # N1 (ticket 20's arbitration round): a last-message paste under this estimate reaches the model whole.
        "paste_inline": {"max_tokens": INLINE_MAX_TOKENS, "fixed_tokens": INLINE_FIXED_TOKENS, "chars_per_token": CHARS_PER_TOKEN},
        "turn_budget_seconds": turn_budget_seconds,
        "final_reserve_seconds": final_reserve_seconds,
        "injection_defense": defense.enabled,
        # The guide as the model reads it, i.e. AFTER the defense appended its rule.
        "agent_guide_sha256": _sha256(defense.agent_guide(AGENT_GUIDE)),
        "system_prompt_sha256": _sha256(system_prompt),
        "discord_context_sha256": _sha256(DISCORD_SPEAKER_SYSTEM_INSTRUCTION),
        "tools_sha256": _sha256(json.dumps(registry.schemas(), ensure_ascii=False, sort_keys=True)),
        "dataset": {
            "version": dataset.version,
            "sha256": dataset.sha256,
            "path": str(dataset.path),
            "tasks_run": [task["id"] for task in tasks],
        },
        "grader_version": GRADER_VERSION,
        # Without it, a task's answer can depend on the task run just before it
        # (ticket 20 #3-D, 28/10), so only runs that agree here compare task by task.
        "unload_between_tasks": reloader is not None,
        "started_at": datetime.now(UTC).isoformat(),
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    recording = UsageRecordingRouter(router)
    documents = FixtureDocuments(dataset.documents)
    schemas = {tool["function"]["name"]: tool["function"]["parameters"] for tool in registry.schemas()}
    results: list[dict[str, Any]] = []
    for task in tasks:
        retrieval = dataset.retrieval.get(task["id"], {})
        agent = AgentService(
            recording,
            ReplayRetrieval(retrieval.get("chunks", [])),
            SnapshotStatus(dataset.status_snapshots[task.get("status_snapshot", "healthy")]),
            max_steps=max_steps,
            tool_result_max_chars=tool_result_max_chars,
            defense=defense,
            turn_budget_seconds=turn_budget_seconds,
            final_reserve_seconds=final_reserve_seconds,
            document_reader=documents,
            read_result_max_chars=read_result_max_chars,
            registry=registry,
        )
        tool_context = {"guild_id": history.guild_id} if task.get("surface") == "discord" else None
        answer: str | None = None
        model: str | None = None
        steps: list[dict[str, object]] = []
        error: str | None = None
        reload_ms = reloader.reload() if reloader is not None else None
        started = perf_counter()
        limit = INPUT_MAX_CHARS[task.get("surface", "web")]
        if len(task["input"]) > limit:
            error = f"INPUT_TOO_LONG: {len(task['input'])} > {limit} ký tự, API từ chối trước khi agent chạy"
        else:
            try:
                answer, model, steps = agent.run(build_messages(task, system_prompt), tool_context=tool_context)
            except Exception as exc:  # one broken task must not cost the others
                error = f"{type(exc).__name__}: {exc}"
        latency_ms = int((perf_counter() - started) * 1000)
        rounds = recording.take()
        graded = grade(task["expect"], steps, answer, schemas, error)
        result = {
            "task_id": task["id"],
            "category": task["category"],
            "surface": task.get("surface", "web"),
            "passed": graded["passed"],
            "answer": answer,
            "model": model,
            "error": error,
            "tool_calls": tool_calls(steps),
            "model_rounds": len(rounds),
            "budget_exhausted": any(round_["call"] == "chat" for round_ in rounds),
            "tokens_in": _sum([round_["tokens_in"] for round_ in rounds]),
            "tokens_out": _sum([round_["tokens_out"] for round_ in rounds]),
            "latency_ms": latency_ms,
            "reload_ms": reload_ms,
            "retrieval_source": retrieval.get("source"),
            "grade": graded,
        }
        results.append(result)
        events = [{"task_id": task["id"], "step_index": index, **step} for index, step in enumerate(steps)]
        events += [{"task_id": task["id"], "kind": "model_round", "round_index": index, **round_} for index, round_ in enumerate(rounds)]
        with (out_dir / "task_results.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
        with (out_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.writelines(json.dumps(event, ensure_ascii=False, default=str) + "\n" for event in events)
        progress(
            f"{task['id']:<10} {'PASS' if result['passed'] else 'FAIL'} {latency_ms / 1000:6.1f}s"
            + (f" (nạp {reload_ms / 1000:.1f}s)" if reload_ms is not None else "")
            + (" ERROR" if error else "")
        )

    summary = {**summarize(results), **_aggregates(results)}
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["finished_at"] = datetime.now(UTC).isoformat()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


# ── CLI: the real model ──────────────────────────────────────────────────


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR)
    parser.add_argument("--tasks", help="comma-separated task ids (default: all)")
    parser.add_argument("--temperature", type=float, help="override the general model's temperature for this run only")
    parser.add_argument("--seed", type=int, help="pass a seed to Ollama for this run only (default: no seed)")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--probe", action="store_true",
        help="probe the registry as the API boots (needs the stack and the real .env); required for a citable baseline",
    )
    parser.add_argument(
        "--env-file", type=Path,
        help="the .env Settings reads (default: this checkout's); a worktree has none, so point it at the main checkout's",
    )
    parser.add_argument(
        "--gpu-shared", choices=("yes", "no"),
        help="declare whether another job (another project included) uses the GPU during this run; recorded, never guessed",
    )
    parser.add_argument(
        "--unload-between-tasks", action="store_true",
        help="unload the general model from Ollama and load it again before every task, so each task runs as if alone; "
        "compare two arms task by task only with this on (ticket 20 #3-D)",
    )
    return parser.parse_args(argv)


def build_settings(env_file: Path | None, *, probe: bool) -> Any:
    from app.config.settings import Settings

    kwargs: dict[str, Any] = {} if env_file is None else {"_env_file": env_file}
    if not probe:
        # Pointer only: no database is dialled, so a placeholder satisfies the validator.
        kwargs["database_url"] = PLACEHOLDER_DATABASE_URL
    return Settings(**kwargs)


def resolve_registry(settings: Any, probes: Any) -> Any:
    """probes=None: the pointer alone (`verified: false`, the 06 smoke mode).
    With probes: the same pointer -> probe -> fallback walk the API boots with,
    forced on even where MODEL_STARTUP_PROBES is false, because a baseline must
    be tied to what actually serves (ticket 07)."""
    from app.config.model_registry import overrides_from_settings, resolve

    return resolve(settings.registry(), overrides_from_settings(settings), probes)


def probe_database(settings: Any) -> str:
    """The database name and what is read from it, never the URL: host and
    credentials stay out of the manifest."""
    from sqlalchemy.engine import make_url

    return f"{make_url(str(settings.database_url)).database} (read-only: 2 COUNTs)"


def ollama_loaded(base_url: str) -> list[str] | None:
    """The models Ollama holds in memory now (/api/ps). Taken before the probe
    loads anything: with the general model among them the run is warm, without
    it cold (ticket 10's rule, read by the scorecard, ticket 23). None when
    Ollama does not answer."""
    import httpx

    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/ps", timeout=5.0)
        response.raise_for_status()
        return sorted(str(model["name"]) for model in response.json().get("models", []))
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None


class OllamaReloader:
    """--unload-between-tasks (ticket 20 #3-D, the owner's option 2): before a task,
    take the general model out of Ollama (keep_alive 0, as run_cold.sh does), wait
    until /api/ps stops listing it, and load it again with an empty prompt. The
    task then runs on a model just loaded, with nothing left from the task before
    it: on 28/10 the same code and tasks gave doc-51 a passing answer alone and a
    failing one after doc-50."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        keep_alive: str,
        options: dict[str, Any],
        timeout: float = 300.0,
        wait_seconds: float = 60.0,
        poll_seconds: float = 0.25,
        client: Any = None,
        pause: Any = sleep,
    ) -> None:
        import httpx

        self.model = model
        self.keep_alive = keep_alive
        self.options = options
        self.polls = int(wait_seconds / poll_seconds) + 1
        self.poll_seconds = poll_seconds
        self.wait_seconds = wait_seconds
        self.client = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        self.pause = pause

    def _listed(self) -> bool:
        response = self.client.get("/api/ps")
        response.raise_for_status()
        names = {str(model.get("name")) for model in response.json().get("models", [])}
        return self.model in names or f"{self.model}:latest" in names

    def reload(self) -> int:
        """Unload, wait, load; returns the load's wall time in ms. Raises when Ollama
        refuses or still lists the model after wait_seconds: a task run on a model
        that was not reloaded is not the isolated run the flag promises."""
        self.client.post("/api/generate", json={"model": self.model, "keep_alive": 0, "stream": False}).raise_for_status()
        for _ in range(self.polls):
            if not self._listed():
                break
            self.pause(self.poll_seconds)
        else:
            raise RuntimeError(f"{self.model} vẫn còn trong /api/ps sau {self.wait_seconds:.0f} giây")
        started = perf_counter()
        payload = {"model": self.model, "keep_alive": self.keep_alive, "options": self.options, "stream": False}
        self.client.post("/api/generate", json=payload).raise_for_status()
        return int((perf_counter() - started) * 1000)


def gpu_snapshot() -> dict[str, Any] | None:
    """GPU load, memory and compute processes as nvidia-smi sees them now: the
    measured half of "was the GPU shared" (the declared half is --gpu-shared).
    It cannot tell another project's requests to the same Ollama apart. None
    without nvidia-smi."""
    def query(*fields: str) -> list[str]:
        out = subprocess.run(["nvidia-smi", *fields, "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        out.check_returncode()
        return [line.strip() for line in out.stdout.splitlines() if line.strip()]

    try:
        utilization, memory = query("--query-gpu=utilization.gpu,memory.used")[0].split(", ")
        processes = [Path(name).name for name in query("--query-compute-apps=process_name")]
        return {"utilization_percent": int(utilization), "memory_used_mib": int(memory), "processes": processes}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def probe_refusal(general_role: Any, *, probed: bool) -> str | None:
    """Why a probed run must not start: the general role is not the verified
    pointer (fallback, missing, Ollama silent...). None = go. Only `general`
    matters here; the other roles are recorded, not gated."""
    if probed and (general_role.deviates or not general_role.verified):
        return f"general {general_role.status}: {general_role.reason or 'not verified'}"
    return None


def main(argv: list[str] | None = None) -> int:
    from app.config.model_registry import ProductionProbes
    from app.llm_clients.ollama_client import OllamaClient
    from app.services.model_router import ModelRouter

    args = parse_args(argv)
    dataset = load_dataset(args.dataset)
    settings = build_settings(args.env_file, probe=args.probe)
    loaded_at_start = ollama_loaded(settings.ollama_base_url) if args.probe else None
    gpu_at_start = gpu_snapshot() if args.probe else None
    resolved = resolve_registry(settings, ProductionProbes(settings) if args.probe else None)
    general_role = resolved.roles["general"]
    refusal = probe_refusal(general_role, probed=args.probe)
    if refusal:
        print(f"refusing to run: {refusal}", file=sys.stderr)
        return 2
    models = override_general(resolved.flat_models(), temperature=args.temperature, seed=args.seed)
    general = models["general"]
    reloader = None
    if args.unload_between_tasks:
        provider = general.get("provider", "ollama")
        if provider != "ollama":
            print(f"refusing to run: --unload-between-tasks unloads an Ollama model, and general is served by {provider}", file=sys.stderr)
            return 2
        # num_ctx sizes the runner: a load with another context would make the
        # first chat load the model a second time. --probe has already run by
        # now (it reads /api/tags and embeds with the embedding model, never
        # loading general), so the first task's unload comes after it.
        reloader = OllamaReloader(
            settings.ollama_base_url,
            general["name"],
            keep_alive=str(general.get("keep_alive", "5m")),
            options={"num_ctx": general["context"]} if "context" in general else {},
            timeout=settings.ollama_chat_timeout_seconds,
        )
    router = ModelRouter(
        {"ollama": OllamaClient(settings.ollama_base_url, settings.ollama_chat_timeout_seconds, settings.ollama_health_timeout_seconds, settings.ollama_retry_count)},
        models,
    )
    config = settings.load_config()
    agent_section = config.get("agent", {})
    # The same reads and defaults as main.py, so the eval runs what the API runs.
    agent_config = {
        "max_steps": int(agent_section.get("max_steps", 3)),
        "tool_result_max_chars": int(agent_section.get("tool_result_max_chars", 1200)),
        "read_result_max_chars": int(agent_section.get("read_result_max_chars", READ_RESULT_MAX_CHARS)),
        "turn_budget_seconds": float(agent_section.get("turn_budget_seconds", TURN_BUDGET_SECONDS)),
        "final_reserve_seconds": float(agent_section.get("final_reserve_seconds", FINAL_RESERVE_SECONDS)),
    }
    defense = InjectionDefense.from_config(config.get("rag", {}), enabled_override=settings.rag_injection_defense_enabled)

    seed_label = f"seed{args.seed}" if args.seed is not None else "noseed"
    run_id = args.run_id or f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-t{general.get('temperature')}-{seed_label}"
    run_meta = {
        "run_id": run_id,
        "commit": _git("rev-parse", "HEAD"),
        "worktree_dirty": bool(_git("status", "--porcelain")),
        "general_version": {
            "requested_id": general_role.requested_id,
            "loaded_id": general_role.loaded_id,
            "source": general_role.source,
            "status": general_role.status,
            "verified": general_role.verified,
        },
        "probed": args.probe,
        "ollama_loaded_at_start": loaded_at_start,
        # Another job on the same card moves latency, so the scorecard does not
        # compare latency across runs that differ here (coordination, 28/10).
        "gpu_shared": {"yes": True, "no": False}.get(args.gpu_shared),
        "gpu_at_start": gpu_at_start,
        # The probe's only database touch, named so a reader of a baseline knows
        # which real data it read: two COUNTs, read-only, as every API boot does.
        "probe_read_database": probe_database(settings) if args.probe else None,
        # Every role's verdict, not just general's: context for a reader, never a gate.
        "registry_fallback": resolved.fallback_flag() if args.probe else None,
        "env_file": str(args.env_file) if args.env_file else "default",
        "model": general.get("name"),
        "provider": general.get("provider", "ollama"),
        "temperature": general.get("temperature"),
        "top_p": general.get("top_p"),
        "seed": general["seed"] if "seed" in general else NO_SEED,
        "think": general.get("think"),
        "num_ctx": general.get("context"),
        "overrides": {"temperature": args.temperature, "seed": args.seed},
        "argv": sys.argv[1:] if argv is None else argv,
    }
    out_dir = args.out / run_id
    summary = run_eval(
        dataset,
        router,
        out_dir=out_dir,
        agent_config=agent_config,
        defense=defense,
        system_prompt=SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"),
        run_meta=run_meta,
        task_ids=[task_id.strip() for task_id in args.tasks.split(",") if task_id.strip()] if args.tasks else None,
        reloader=reloader,
    )
    overall = summary["overall"]
    card = scorecard(out_dir)
    (out_dir / "scorecard.json").write_text(json.dumps(card, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(render(card))
    print(f"{overall['passed']}/{overall['total']} passed, {summary['errors']} errors -> {out_dir}")
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
