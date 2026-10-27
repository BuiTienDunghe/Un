"""Prove a query-side prefix reaches Ollama: query vectors differ, passage vectors do not."""
import json, math, os, subprocess, sys

TEXT = "thủ tục cấp lại căn cước công dân"


def vectors() -> dict[str, list[float]]:
    from app.config.settings import Settings
    from app.llm_clients.ollama_client import OllamaClient
    from app.services.model_router import ModelRouter
    s = Settings()
    resolved = s.resolve_models(allow_missing_collections=True)
    router = ModelRouter({"ollama": OllamaClient(s.ollama_base_url, s.ollama_chat_timeout_seconds, s.ollama_health_timeout_seconds, s.ollama_retry_count)},
                         s.load_models(), embedding_refusal=resolved.embedding_refusal())
    return {side: router.embed(TEXT, side=side)[0] for side in ("query", "passage")}


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


if __name__ == "__main__":
    if sys.argv[1:] == ["--one"]:
        print(json.dumps(vectors())); raise SystemExit(0)
    env = {**os.environ, "MODEL_STARTUP_PROBES": "false"}
    base = json.loads(subprocess.check_output([sys.executable, __file__, "--one"], env={**env, "MODEL_VERSION_EMBEDDING": ""}))
    pinned = json.loads(subprocess.check_output([sys.executable, __file__, "--one"], env={**env, "MODEL_VERSION_EMBEDDING": sys.argv[1]}))
    print(json.dumps({"query_cosine": cosine(base["query"], pinned["query"]), "passage_cosine": cosine(base["passage"], pinned["passage"])}))
