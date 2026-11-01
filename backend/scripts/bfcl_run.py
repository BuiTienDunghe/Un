"""BFCL through Ún's own agent loop (ticket 42; design in .scratch/foundation-and-agent-eval/ticket24-design.md).

BFCL's own runner sends each task straight to a model, so it measures the model. Here every
BFCL turn is one AgentService.run(), so what is measured is the harness around the model: the
tool-round limit, the turn budget, the coded tool errors, the clipping of results, the answer
check. Only the tools differ: the registry holds the task's own functions in place of Ún's
(`AgentService(registry=...)`), and a call is executed by BFCL's own backends so that the
scorer replays the same state. The score only compares two versions of the harness with each
other on this fixed set; it is never to be put beside the leaderboard.

    cd backend
    python -m scripts.bfcl_run --dry-run                              # load, build tools, no model
    python -m scripts.bfcl_run --only simple_python_6 --gpu-shared no  # one task
    python -m scripts.bfcl_run --probe --env-file <main checkout>/.env --gpu-shared yes
    <bfcl-venv>/Scripts/python backend/scripts/bfcl_score.py <run_dir>   # then score it

Pinned: temperature 0, seed 42 (as the Agent Eval's repeatable runs), the 33 ids of
data/benchmarks/bfcl/ids_v1.json, BFCL clone at 6ea5797 (read, never written to).

How a turn is recorded: result[turn][step] is, per model round, the calls the loop really
executed, as {name: json-arguments} (the form BFCL's own FC handlers store); the calls are
executed from that very text, so the scorer's replay (decode_execute) is the same run. The
answer text goes last, as BFCL stores a text-only step; the scorer skips it. A single-turn
task has the flat list of every call made, or the answer text when none was made.

What the loop is NOT given, and why it is stated here: between turns the model gets the earlier
turns' user and answer text only, as Ún's chat path hands history to the agent, not the earlier
tool calls (BFCL's loop would carry them). AGENT_GUIDE is unchanged, so it still names
search_documents, search_history and the others, which are absent in these turns. No persona
prompt. A single-turn task's tool answers "ok": BFCL does not execute those. For that reason a
single-turn task's result holds the calls of the FIRST model round only, as BFCL's own result
holds the first response: a model that calls again after the made-up "ok" (to fetch a value that
does not exist) is not failed by it. The later rounds' calls still run and stay in
inference_log and in the line's `later_round_calls`.

One caution: a parameter name the model writes goes into the call string that BFCL `eval`s, in
this process, exactly as BFCL's own scorer does when it replays it. The model is local, so the
risk is the scorer's own.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from app.services.agent_service import AGENT_GUIDE, AgentService, AgentTool, ToolRegistry
from app.services.injection_defense import InjectionDefense
from scripts.agent_eval import (
    NO_SEED,
    OllamaReloader,
    UsageRecordingRouter,
    _git,
    build_settings,
    gpu_snapshot,
    ollama_loaded,
    ollama_version,
    override_general,
    probe_refusal,
    resolve_registry,
)

BACKEND = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND.parent
IDS_PATH = PROJECT_ROOT / "data" / "benchmarks" / "bfcl" / "ids_v1.json"
RESULTS_DIR = PROJECT_ROOT / "data" / "evaluation" / "results" / "bfcl"
DEFAULT_CLONE = Path(r"C:\Users\dungbt06\tools\gorilla-6ea5797\berkeley-function-call-leaderboard")
CLONE_COMMIT = "6ea5797"
RUNNER_VERSION = "bfcl-run-v1"

# The name BFCL files the results under and the scorer registers; no underscore, because
# BFCL's runner turns every "_" of a result directory back into "/" to look the model up.
MODEL_DIR = "un-harness"
TEMPERATURE = 0.0
SEED = 42

SINGLE_TURN = ("simple_python", "multiple", "irrelevance")
MULTI_TURN = ("multi_turn_base", "multi_turn_miss_func")
HINT = " Note that the provided function is in Python 3 syntax."
SINGLE_TURN_OK = json.dumps({"result": "ok"})
# What BFCL joins with the task id into the name of a backend instance and then `eval`s as a
# variable: it must stay a valid identifier, which a run id (it starts with a date) is not. Fixed,
# never the run id.
RUN_TAG = "unrun"


def default_run_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-t{TEMPERATURE:g}-seed{SEED}"


def instance_prefix(run_tag: str, entry_id: str) -> str:
    """The start of BFCL's instance names for a task, as it spells them (multi_turn_utils.py)."""
    return re.sub(r"[-./:]", "_", f"{run_tag}_{entry_id}_")


# ── the BFCL clone (read only) ───────────────────────────────────────────


class Bfcl:
    """What the runner takes from the clone: the data files and three pure modules (the
    multi-turn backends' executor, the type table, the prompt constants). Not bfcl_eval.utils
    or model_handler.utils: they import eval_config, which creates directories next to the
    clone, and filelock/tenacity."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        if not (self.root / "bfcl_eval" / "data").is_dir():
            raise FileNotFoundError(f"no BFCL clone at {self.root}")
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(self.root))
        from bfcl_eval.constants.default_prompts import DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_FC
        from bfcl_eval.constants.executable_backend_config import MULTI_TURN_FUNC_DOC_FILE_MAPPING
        from bfcl_eval.constants.type_mappings import GORILLA_TO_OPENAPI
        from bfcl_eval.eval_checker.multi_turn_eval import multi_turn_utils

        self.additional_function_prompt = DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_FC
        self.func_doc_files = MULTI_TURN_FUNC_DOC_FILE_MAPPING
        self.type_mapping = GORILLA_TO_OPENAPI
        self.utils = multi_turn_utils
        self.data = self.root / "bfcl_eval" / "data"

    def commit(self) -> str:
        import subprocess

        try:
            return subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return "unknown"

    def load_entries(self, category: str, ids: list[str]) -> list[dict[str, Any]]:
        """The entries of `ids` in file order, as BFCL's load_dataset_entry builds them for a
        run: a multi-turn entry gets its functions from the func-doc files (the held-out ones
        set aside under missed_function), every function a Python hint in its description."""
        lines = (self.data / f"BFCL_v4_{category}.json").read_text(encoding="utf-8").splitlines()
        wanted, entries = set(ids), []
        for line in lines:
            entry = json.loads(line) if line.strip() else None
            if entry and entry["id"] in wanted:
                entries.append(entry)
        missing = wanted - {entry["id"] for entry in entries}
        if missing:
            raise ValueError(f"{category}: ids not in the BFCL data: {sorted(missing)}")
        for entry in entries:
            if category in MULTI_TURN:
                entry["function"] = []
                for collection in entry["involved_classes"]:
                    doc_path = self.data / "multi_turn_func_doc" / self.func_doc_files[collection]
                    entry["function"].extend(json.loads(line) for line in doc_path.read_text(encoding="utf-8").splitlines() if line.strip())
                held_out = entry.get("missed_function", {})
                for turn, names in list(held_out.items()):
                    held_out[turn] = []
                    for name in names:
                        for position, doc in enumerate(entry["function"]):
                            if doc["name"] == name:
                                held_out[turn].append(entry["function"].pop(position))
                                break
            for doc in entry["function"]:
                doc["description"] += HINT
        return entries

    def to_tool(self, doc: dict[str, Any]) -> dict[str, Any]:
        """A function doc as the OpenAI-style tool BFCL's handlers send (convert_to_tool with
        ModelStyle.OPENAI_COMPLETIONS): "." in a name becomes "_" (the scorer's ModelConfig has
        underscore_to_dot for it), parameter types are mapped, the `response` schema is not sent
        (Ollama drops the field in any case)."""
        item = copy.deepcopy(doc)
        item["name"] = item["name"].replace(".", "_")
        item["parameters"]["type"] = "object"
        item["parameters"]["properties"] = self._cast(item["parameters"]["properties"])
        item.pop("response", None)
        return {"type": "function", "function": item}

    def _cast(self, properties: dict[str, Any]) -> dict[str, Any]:
        mapping = self.type_mapping
        for key, value in properties.items():
            if "type" not in value:
                value["type"] = "string"
            else:
                kind = value["type"]
                if kind == "float":
                    value["format"] = "float"
                    value["description"] = value.get("description", "") + " This is a float type value."
                value["type"] = mapping.get(kind, "string")
            if value["type"] in ("array", "object"):
                if "properties" in value:
                    value["properties"] = self._cast(value["properties"])
                elif "items" in value:
                    items = value["items"]
                    items["type"] = mapping.get(items.get("type"), "string")
                    if items["type"] == "array" and "items" in items:
                        items["items"]["type"] = mapping.get(items["items"].get("type"), "string")
                    elif items["type"] == "object" and "properties" in items:
                        items["properties"] = self._cast(items["properties"])
        return properties


def load_ids(path: Path = IDS_PATH) -> dict[str, list[str]]:
    ids = json.loads(path.read_text(encoding="utf-8"))
    unknown = set(ids) - set(SINGLE_TURN) - set(MULTI_TURN)
    if unknown:
        raise ValueError(f"categories this runner does not run: {sorted(unknown)}")
    return ids


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── one call: the text that is recorded is the text that is executed ─────


def call_string(name: str, arguments_json: str) -> str:
    """The call as BFCL's decode_execute spells it (convert_to_function_call), from the very
    JSON text that goes into the result file. The scorer replays exactly this string."""
    arguments = json.loads(arguments_json)
    return f"{name}({','.join(f'{key}={value!r}' for key, value in arguments.items())})"


class TurnLog:
    """The calls the loop executed, by model round. A round is the router's call count so far:
    UsageRecordingRouter appends to `rounds` when a call returns, so while a tool runs the
    current round is the last one appended."""

    def __init__(self, recording: UsageRecordingRouter) -> None:
        self.recording = recording
        self.by_round: dict[int, list[dict[str, str]]] = {}

    def add(self, recorded: dict[str, str]) -> None:
        self.by_round.setdefault(len(self.recording.rounds) - 1, []).append(recorded)

    def take(self) -> dict[int, list[dict[str, str]]]:
        taken, self.by_round = self.by_round, {}
        return taken


def make_tool(bfcl: Bfcl, doc: dict[str, Any], *, execute: dict[str, Any] | None, log: TurnLog) -> AgentTool:
    """One of the task's functions as a registry tool. `execute` is None in a single-turn task
    (BFCL runs nothing there), else what the multi-turn backends need to run a call."""
    schema = bfcl.to_tool(doc)
    name = schema["function"]["name"]
    label = f"Đang gọi {name}…"

    def run(service: AgentService, arguments: dict[str, Any], context: dict[str, Any] | None) -> tuple[str, str | None, str | None]:
        if not isinstance(arguments, dict):
            return service._error("BAD_ARGUMENTS", f"{name} cần tham số là một đối tượng.")
        recorded = {name: json.dumps(arguments, ensure_ascii=False)}
        log.add(recorded)
        if execute is None:
            return SINGLE_TURN_OK, None, None
        results, _ = bfcl.utils.execute_multi_turn_func_call(
            [call_string(name, recorded[name])],
            execute["initial_config"],
            execute["involved_classes"],
            execute["model_name"],
            execute["entry_id"],
            long_context=False,
            is_evaL_run=False,
        )
        try:
            payload = json.loads(results[0])
        except ValueError:
            payload = results[0]
        return service._dump(payload), None, None

    return AgentTool(schema, run, label)


def drop_instances(bfcl: Bfcl, model_name: str, entry_id: str) -> None:
    """BFCL keeps each task's backend instances in its module's globals under a name made of the
    model and the task: a second run of the same task in this process would continue from the
    first one's state."""
    prefix = instance_prefix(model_name, entry_id)
    scope = vars(bfcl.utils)
    for key in [key for key in scope if key.startswith(prefix)]:
        del scope[key]


# ── one task ─────────────────────────────────────────────────────────────


def run_entry(
    bfcl: Bfcl,
    entry: dict[str, Any],
    category: str,
    recording: UsageRecordingRouter,
    make_agent: Any,
    run_tag: str,
) -> dict[str, Any]:
    """Every turn of one task through AgentService.run(); returns the line for the result file.
    `make_agent(registry)` builds the service, so a test hands in a scripted model."""
    multi = category in MULTI_TURN
    if multi and not (instance_prefix(run_tag, entry["id"]) + "GorillaFileSystem_instance").isidentifier():
        # Otherwise every call fails at BFCL's eval with a SyntaxError that reaches the model as a
        # plain error string, and the scorer, replaying under its own valid name, still scores it.
        raise ValueError(f"run_tag {run_tag!r} does not make a valid BFCL instance name")
    log = TurnLog(recording)
    execute = (
        {
            "initial_config": entry.get("initial_config", {}),
            "involved_classes": entry["involved_classes"],
            "model_name": run_tag,
            "entry_id": entry["id"],
        }
        if multi
        else None
    )
    registry = ToolRegistry()
    for order, doc in enumerate(entry["function"]):
        registry.register(make_tool(bfcl, doc, execute=execute, log=log), order)
    agent = make_agent(registry)
    held_out: dict[str, list[dict[str, Any]]] = entry.get("missed_function", {})

    history: list[dict[str, Any]] = []
    turns: list[list[Any]] = []
    turn_logs: list[dict[str, Any]] = []
    tokens_in: list[list[float]] = []
    tokens_out: list[list[float]] = []
    latency: list[list[float]] = []
    error: str | None = None
    answers: list[str] = []
    all_calls: list[dict[str, str]] = []
    first_round_calls: list[dict[str, str]] = []
    try:
        for turn_index, turn_messages in enumerate(entry["question"]):
            if str(turn_index) in held_out:
                # The functions held back appear now, and the user turn is BFCL's fixed sentence
                # (the data's own turn is empty): BFCL does the same in inference_multi_turn_FC.
                for position, doc in enumerate(held_out[str(turn_index)]):
                    registry.register(make_tool(bfcl, doc, execute=execute, log=log), len(entry["function"]) + position)
                turn_messages = [{"role": "user", "content": bfcl.additional_function_prompt}]
            recording.take()
            log.take()
            started = perf_counter()
            answer, model, steps = agent.run([*history, *turn_messages])
            rounds, by_round = recording.take(), log.take()
            ordered = [by_round[index] for index in sorted(by_round)]
            turns.append([*ordered, answer] if answer else ordered)
            if turn_index == 0 and ordered and 0 in by_round:
                first_round_calls = list(by_round[0])
            all_calls.extend(call for calls in ordered for call in calls)
            answers.append(answer)
            history += [*turn_messages, {"role": "assistant", "content": answer}]
            tokens_in.append([float(round_["tokens_in"] or 0) for round_ in rounds])
            tokens_out.append([float(round_["tokens_out"] or 0) for round_ in rounds])
            latency.append([round_["latency_ms"] / 1000 for round_ in rounds])
            turn_logs.append({
                "begin_of_turn_query": turn_messages,
                "model": model,
                "wall_seconds": round(perf_counter() - started, 3),
                "model_rounds": [round_["call"] for round_ in rounds],
                "stop_reason": next((step.get("stop_reason") for step in reversed(steps) if step["kind"] == "final"), None),
                "steps": steps,
            })
    except Exception as exc:  # one broken task must not cost the others; a multi-turn one then has too few turns and fails
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if multi:
            drop_instances(bfcl, run_tag, entry["id"])
    line: dict[str, Any] = {"id": entry["id"]}
    if multi:
        line.update(result=turns, input_token_count=tokens_in, output_token_count=tokens_out, latency=latency)
    else:
        line.update(
            result=first_round_calls if first_round_calls else (answers[0] if answers else ""),
            later_round_calls=len(all_calls) - len(first_round_calls),
            input_token_count=sum(sum(turn) for turn in tokens_in),
            output_token_count=sum(sum(turn) for turn in tokens_out),
            latency=sum(sum(turn) for turn in latency),
        )
    line["inference_log"] = turn_logs
    if error:
        line["error"] = error
    return line


# ── the run ──────────────────────────────────────────────────────────────


def group_of(category: str) -> str:
    return "multi_turn" if category in MULTI_TURN else "non_live"


def result_path(root: Path, category: str) -> Path:
    return root / "result" / MODEL_DIR / group_of(category) / f"BFCL_v4_{category}_result.json"


def summarize(lines_by_category: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """What the harness did, not what the scorer will say: why each turn ended (the design's
    prediction, ticket 24 s.5, is that max_steps ends more turns than turn_budget), coded tool
    errors, the answer check's retries."""
    stops: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    per_category: dict[str, Any] = {}
    wall: list[float] = []
    for category, lines in lines_by_category.items():
        turns = 0
        for line in lines:
            for turn in line["inference_log"]:
                turns += 1
                stops[str(turn["stop_reason"])] += 1
                wall.append(turn["wall_seconds"])
                for step in turn["steps"]:
                    kinds[step["kind"]] += 1
                    if step.get("error_code"):
                        errors[step["error_code"]] += 1
        per_category[category] = {"tasks": len(lines), "turns": turns, "errors": sum(1 for line in lines if "error" in line)}
    return {
        "per_category": per_category,
        "turn_stop_reasons": dict(stops),
        "step_kinds": dict(kinds),
        "error_codes": dict(errors),
        "turn_wall_seconds": {"mean": round(statistics.fmean(wall), 2), "max": round(max(wall), 2)} if wall else None,
    }


def run_all(
    bfcl: Bfcl,
    selection: dict[str, list[str]],
    recording: UsageRecordingRouter,
    make_agent: Any,
    out_dir: Path,
    *,
    run_tag: str,
    reloader: Any = None,
    progress: Any = print,
) -> dict[str, Any]:
    lines_by_category: dict[str, list[dict[str, Any]]] = {}
    for category, ids in selection.items():
        path = result_path(out_dir, category)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        lines_by_category[category] = []
        for entry in bfcl.load_entries(category, ids):
            reload_ms = reloader.reload() if reloader is not None else None
            started = perf_counter()
            line = run_entry(bfcl, entry, category, recording, make_agent, run_tag)
            lines_by_category[category].append(line)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
            progress(
                f"{entry['id']:<28} {perf_counter() - started:6.1f}s"
                + (f" (nạp {reload_ms / 1000:.1f}s)" if reload_ms is not None else "")
                + (" ERROR" if "error" in line else "")
            )
    summary = summarize(lines_by_category)
    (out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


# ── CLI: the real model ──────────────────────────────────────────────────


def ollama_facts(base_url: str, model: str) -> dict[str, Any]:
    """The pinned model's digest (/api/tags) and the server's version: a different quantisation
    or build gives numbers that do not compare. None where Ollama does not answer."""
    import httpx

    # The version is asked on its own (agent_eval.ollama_version), so a failed /api/tags no longer hides it.
    facts: dict[str, Any] = {"digest": None, "ollama_version": ollama_version(base_url)}
    try:
        tags = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=5.0).json().get("models", [])
        facts["digest"] = next((m.get("digest") for m in tags if model in (m.get("name"), m.get("model"))), None)
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    return facts


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ids", type=Path, default=IDS_PATH)
    parser.add_argument("--only", help="comma-separated task ids out of the ids file (default: all 33)")
    parser.add_argument("--clone", type=Path, default=Path(os.environ.get("BFCL_CLONE", DEFAULT_CLONE)))
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    parser.add_argument("--run-id")
    parser.add_argument("--dry-run", action="store_true", help="load the tasks and build their tools; no model is called")
    parser.add_argument("--probe", action="store_true", help="probe the registry as the API boots (needs the stack and the real .env)")
    parser.add_argument("--env-file", type=Path, help="the .env Settings reads (default: this checkout's)")
    parser.add_argument("--gpu-shared", choices=("yes", "no"), help="declare whether another job uses the GPU during this run; recorded, never guessed")
    parser.add_argument("--unload-between-tasks", action="store_true", help="unload and reload the general model before every task (as in agent_eval); otherwise once, before the first")
    return parser.parse_args(argv)


def select(ids: dict[str, list[str]], only: str | None) -> dict[str, list[str]]:
    if not only:
        return ids
    wanted = {item.strip() for item in only.split(",") if item.strip()}
    chosen = {category: [i for i in members if i in wanted] for category, members in ids.items()}
    unknown = wanted - {i for members in ids.values() for i in members}
    if unknown:
        raise ValueError(f"not in the ids file: {sorted(unknown)}")
    return {category: members for category, members in chosen.items() if members}


def main(argv: list[str] | None = None) -> int:
    from app.config.model_registry import ProductionProbes
    from app.llm_clients.ollama_client import OllamaClient
    from app.services.agent_service import FINAL_RESERVE_SECONDS, TURN_BUDGET_SECONDS
    from app.services.model_router import ModelRouter

    args = parse_args(argv)
    bfcl = Bfcl(args.clone)
    selection = select(load_ids(args.ids), args.only)
    if args.dry_run:
        for category, ids in selection.items():
            for entry in bfcl.load_entries(category, ids):
                held = sum(len(docs) for docs in entry.get("missed_function", {}).values())
                print(f"{entry['id']:<28} turns={len(entry['question'])} tools={len(entry['function'])} held_out={held}")
        return 0
    settings = build_settings(args.env_file, probe=args.probe)
    loaded_at_start = ollama_loaded(settings.ollama_base_url)
    gpu_at_start = gpu_snapshot()
    resolved = resolve_registry(settings, ProductionProbes(settings) if args.probe else None)
    general_role = resolved.roles["general"]
    refusal = probe_refusal(general_role, probed=args.probe)
    if refusal:
        print(f"refusing to run: {refusal}", file=sys.stderr)
        return 2
    models = override_general(resolved.flat_models(), temperature=TEMPERATURE, seed=SEED)
    general = models["general"]
    if general.get("provider", "ollama") != "ollama":
        print(f"refusing to run: the pins are for an Ollama model, and general is served by {general.get('provider')}", file=sys.stderr)
        return 2
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
    # The same reads and defaults as agent_eval.main (and main.py), so the harness is the shipped one.
    agent_config = {
        "max_steps": int(agent_section.get("max_steps", 3)),
        "tool_result_max_chars": int(agent_section.get("tool_result_max_chars", 1200)),
        "turn_budget_seconds": float(agent_section.get("turn_budget_seconds", TURN_BUDGET_SECONDS)),
        "final_reserve_seconds": float(agent_section.get("final_reserve_seconds", FINAL_RESERVE_SECONDS)),
    }
    defense = InjectionDefense.from_config(config.get("rag", {}), enabled_override=settings.rag_injection_defense_enabled)
    recording = UsageRecordingRouter(router)

    def make_agent(registry: ToolRegistry) -> AgentService:
        return AgentService(recording, None, None, defense=defense, registry=registry, **agent_config)

    run_id = args.run_id or default_run_id()
    out_dir = args.out / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "runner": RUNNER_VERSION,
        "commit": _git("rev-parse", "HEAD"),
        "worktree_dirty": bool(_git("status", "--porcelain")),
        "bfcl_commit": bfcl.commit(),
        "bfcl_expected": CLONE_COMMIT,
        "ids_file": str(args.ids.relative_to(PROJECT_ROOT)) if args.ids.is_relative_to(PROJECT_ROOT) else str(args.ids),
        "ids_sha256": sha256_of(args.ids),
        "tasks": {category: len(ids) for category, ids in selection.items()},
        "model": general.get("name"),
        **ollama_facts(settings.ollama_base_url, str(general.get("name"))),
        "general_version": {"requested_id": general_role.requested_id, "loaded_id": general_role.loaded_id, "status": general_role.status, "verified": general_role.verified},
        "probed": args.probe,
        "ollama_loaded_at_start": loaded_at_start,
        "gpu_shared": {"yes": True, "no": False}.get(args.gpu_shared),
        "gpu_at_start": gpu_at_start,
        "temperature": general.get("temperature"),
        "seed": general["seed"] if "seed" in general else NO_SEED,
        "think": general.get("think"),
        "num_ctx": general.get("context"),
        "agent_config": agent_config,
        "agent_guide_sha256": hashlib.sha256(AGENT_GUIDE.encode("utf-8")).hexdigest(),
        "persona_prompt": None,
        "history_between_turns": "user and answer text only",
        "single_turn_scored_calls": "first model round only",
        "unload_between_tasks": args.unload_between_tasks,
        "started_at": datetime.now(UTC).isoformat(),
        "argv": sys.argv[1:] if argv is None else argv,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.unload_between_tasks:
        reloader.reload()
    summary = run_all(
        bfcl, selection, recording, make_agent, out_dir,
        run_tag=RUN_TAG, reloader=reloader if args.unload_between_tasks else None,
    )
    manifest["finished_at"] = datetime.now(UTC).isoformat()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"results -> {out_dir / 'result'}; score with scripts/bfcl_score.py {out_dir}")
    return 1 if any(c["errors"] for c in summary["per_category"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
