"""Score this project's embedding model on public Vietnamese retrieval benchmarks.

Runs in `.venv-eval`, not the production environment, and talks to the model over
Ollama's OpenAI-compatible endpoint — so it measures exactly the weights the
system serves, without loading them a second time.

What this measures, and what it does not: mteb encodes queries and the corpus and
ranks by vector similarity. That is the embedding model alone. It does not touch
this project's chunker, its BM25 layer, its rank fusion or its reranker, so a
score here is comparable with published numbers and is *not* a measurement of the
product. `training/common/eval_heldout.py` measures the product; the two answer
different questions and neither replaces the other.

    .venv-eval\\Scripts\\python -m training.common.run_mteb --tasks VieQuADRetrieval
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "data" / "evaluation" / "mteb"

# The four retrieval tasks written in Vietnamese by Vietnamese speakers, rather
# than machine-translated from English BEIR as the bulk of VN-MTEB is. Ordered
# smallest first so a broken run fails in two minutes instead of an hour.
NATIVE_VIETNAMESE = [
    "VieQuADRetrieval",                 # 2 490 documents
    "TVPLRetrieval",                    # 10 576
    "GreenNodeTableMarkdownRetrieval",  # 44 678
    "ZacLegalTextRetrieval",            # 61 425
]


def use_pooled_connections() -> None:
    """Make the wrapper reuse TCP connections instead of opening one per batch.

    `openai_wrappers._make_request` calls `requests.post` at module level, which
    builds and discards a connection every time. On Windows each discarded socket
    sits in TIME_WAIT for minutes against an ephemeral pool of about 16 000, so a
    long benchmark run exhausts the machine's ports and Ollama starts answering
    `bind: An operation on a socket could not be performed because the system
    lacked sufficient buffer space`. Observed here at 14 131 sockets in TIME_WAIT,
    mid-run, on the second task.

    A Session pools and reuses, which turns thousands of connections into a
    handful. Injected rather than patched upstream: the module reads
    `requests.post` at call time, so rebinding the name it looks up is enough.
    """
    import requests
    from requests.adapters import HTTPAdapter

    from mteb.models import openai_wrappers

    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=3)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    class PooledRequests:
        """The requests module with a pooled `post`, and nothing else changed.

        Rebinding the whole name to a Session was the first attempt and it broke
        the caller: `_make_request` catches `requests.exceptions.Timeout`, and a
        Session has no `.exceptions`, so the handler itself raised AttributeError
        and turned a legible network failure into a confusing one. Proxy every
        other attribute through to the real module.
        """

        def __getattr__(self, name):
            return getattr(requests, name)

        @staticmethod
        def post(*args, **kwargs):
            # Windows hands out 16 384 ephemeral ports, and Ollama opens a fresh
            # connection to its own model runner for roughly every text it
            # embeds — measured at 1.11 sockets per text on /api/embed and 1.70
            # on /v1/embeddings. A 61 425-document corpus therefore needs about
            # 68 000 sockets over the run and no batching changes that, because
            # the connections are made inside Ollama, not here.
            #
            # Sockets in TIME_WAIT do expire, so the run only has to stop
            # outpacing them. Ollama reports the exhaustion as a 400 whose body
            # names the bind failure; waiting and retrying turns a dead run into
            # a slow one, which is the right trade for an overnight benchmark.
            for attempt in range(12):
                response = session.post(*args, **kwargs)
                if response.status_code != 400 or "buffer space" not in response.text:
                    return response
                pause = min(15 * (attempt + 1), 90)
                print(f"    [cong mang can kiet, cho {pause}s roi thu lai "
                      f"(lan {attempt + 1}/12)]", flush=True)
                time.sleep(pause)
            return response

    openai_wrappers.requests = PooledRequests()


def build_model(model_name: str, endpoint: str, instruction: bool):
    from mteb.models import OpenAIAPIEncodeWrapper

    kwargs = dict(
        endpoint_url=endpoint,   # the wrapper appends /v1/embeddings itself
        model_name=model_name,
        api_key="ollama",        # Ollama ignores it; the client requires one
        modalities=["text"],
        # The default (True) sends even pure text as a vLLM chat-embeddings
        # payload — `messages` with content parts. Ollama's /v1/embeddings only
        # accepts `input` as a string or list of strings and answers
        # `400 invalid input type`. False takes the plain-text path, which is
        # what this endpoint speaks. "OpenAI-compatible" is not one protocol.
        use_chat_template=False,
    )
    if instruction:
        # Qwen3-Embedding is trained to take an instruction on the query side
        # only; its card reports 1-5% from using one. Documents stay bare.
        kwargs["use_instructions"] = True
        kwargs["apply_instruction_to_documents"] = False
        # The shape Qwen3-Embedding was trained with, from its model card:
        #   Instruct: {task description}\nQuery: {query}
        # The wrapper uses this as a prefix and appends the text, so the trailing
        # "Query: " belongs in the template.
        kwargs["instruction_template"] = "Instruct: {instruction}\nQuery: "
        # Required, and easy to miss: the wrapper only consults the instruction
        # path `if self.use_instructions and self.prompts_dict is not None`. With
        # prompt_dict left at None, use_instructions=True changes nothing and the
        # run silently measures the no-instruction path — two "different"
        # configurations that produce identical numbers because they are the same
        # configuration. An empty dict is enough; the instruction itself comes
        # from each task's metadata.
        kwargs["prompt_dict"] = {}
    model = OpenAIAPIEncodeWrapper(**kwargs)
    # mteb writes results to `.../results/<meta.name>/...`, and an Ollama tag
    # carries a colon, which Windows cannot put in a path. Rename only the
    # metadata; `model_name` stays exactly what Ollama is asked for, so the
    # weights measured are the weights served.
    meta = getattr(model, "mteb_model_meta", None)
    if meta is not None and ":" in str(getattr(meta, "name", "")):
        meta.name = str(meta.name).replace(":", "__")
    return model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3-embedding:0.6b")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--tasks", nargs="*", default=None,
                        help="Task names; default is the four native Vietnamese retrieval tasks.")
    parser.add_argument("--instruction", action="store_true",
                        help="Send a query-side instruction (Qwen3-Embedding is trained for it).")
    parser.add_argument("--version-id", default=None,
                        help="model_versions.yaml roles.embedding id whose weights --model serves; stamped into "
                             "summary.json as versions.embedding (mteb talks to Ollama directly, so the id is declared, "
                             "and `--check` verifies summary.model == that version's config.name).")
    parser.add_argument("--output-folder", default=None)
    parser.add_argument("--batch-size", type=int, default=128,
                        help="Texts per embedding request. The default of 32 upstream means four times "
                             "as many connections; Ollama handles 128 fine and it matters on Windows.")
    arguments = parser.parse_args()

    import mteb

    use_pooled_connections()

    names = arguments.tasks or NATIVE_VIETNAMESE
    tasks = mteb.get_tasks(tasks=names)
    output = Path(arguments.output_folder) if arguments.output_folder else OUT_DIR / arguments.model.replace(":", "_").replace("/", "_")
    output.mkdir(parents=True, exist_ok=True)

    print(f"model    : {arguments.model} qua {arguments.endpoint}")
    print(f"instruction: {'CO' if arguments.instruction else 'khong'}")
    print(f"tasks    : {', '.join(t.metadata.name for t in tasks)}")
    print(f"ket qua  : {output}\n")

    model = build_model(arguments.model, arguments.endpoint, arguments.instruction)
    started = time.monotonic()
    # mteb 2.x caches into ~/.cache/mteb and returns a ModelResult; there is no
    # output_folder any more. Point the cache at this repo so a result belongs
    # to the run that produced it rather than to whoever last used the machine.
    results = mteb.evaluate(model, tasks, cache=mteb.ResultCache(str(output)),
                            encode_kwargs={"batch_size": arguments.batch_size},
                            show_progress_bar=False)
    elapsed = time.monotonic() - started

    rows = []
    for result in results:
        name = getattr(result, "task_name", "?")
        for split_scores in (getattr(result, "scores", {}) or {}).values():
            for entry in split_scores:
                rows.append({
                    "task": name,
                    "split": entry.get("hf_subset") or "-",
                    "ndcg_at_10": entry.get("ndcg_at_10"),
                    "recall_at_10": entry.get("recall_at_10"),
                    "mrr_at_10": entry.get("mrr_at_10"),
                    "main_score": entry.get("main_score"),
                })

    print(f"\n{'task':34} {'nDCG@10':>9} {'recall@10':>10} {'MRR@10':>9}")
    for row in rows:
        def show(value):
            return f"{value:9.4f}" if isinstance(value, (int, float)) else f"{'-':>9}"
        print(f"  {row['task']:32} {show(row['ndcg_at_10'])} {show(row['recall_at_10']):>10} {show(row['mrr_at_10'])}")
    print(f"\nxong sau {elapsed/60:.1f} phut")

    summary = output / "summary.json"
    summary.write_text(json.dumps({
        "model": arguments.model,
        "versions": {"embedding": arguments.version_id},
        "endpoint": arguments.endpoint,
        "instruction": arguments.instruction,
        "elapsed_minutes": round(elapsed / 60, 2),
        "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"tom tat -> {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
