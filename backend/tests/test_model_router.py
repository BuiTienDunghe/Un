import pytest

from app.llm_clients.ollama_client import OllamaClient, OllamaModelNotLoadedError
from app.services.job_errors import classify_error
from app.services.model_router import EmbeddingRefusedError, ModelRouter


class FakeOllama(OllamaClient):
    def __init__(self):  # no HTTP setup; only the chat surface is exercised
        self.model = None
        self.options = None
        self.think = None

    def chat(self, model, messages, options, keep_alive, think=None):
        self.model = model
        self.options = options
        self.think = think
        return "answer"


def test_model_router_uses_general_model():
    client = FakeOllama()
    router = ModelRouter({"ollama": client}, {"general": {"name": "qwen3.5:9b", "context": 123, "temperature": 0.4}})

    answer, model_used = router.chat("general", [{"role": "user", "content": "Hello"}])

    assert answer == "answer"
    assert model_used == "qwen3.5:9b"
    assert client.model == "qwen3.5:9b"
    assert client.options["num_ctx"] == 123


def test_model_router_disables_thinking_when_configured():
    client = FakeOllama()
    router = ModelRouter({"ollama": client}, {"general": {"name": "qwen3.5:9b", "think": False}})

    router.chat("general", [{"role": "user", "content": "Hello"}])

    assert client.think is False


def test_model_router_rejects_removed_code_mode():
    router = ModelRouter({"ollama": FakeOllama()}, {"general": {"name": "qwen3.5:9b"}})

    with pytest.raises(ValueError):
        router.chat("code", [{"role": "user", "content": "Hello"}])


# ── embed(side=): the model registry's query/passage prefixes ────────────────


class FakeEmbedOllama(OllamaClient):
    def __init__(self):  # no HTTP setup; only the embed surface is exercised
        self.embedded: list[tuple[str, str]] = []

    def embed(self, model, text):
        self.embedded.append((model, text))
        return [0.1, 0.2, 0.3]


V0 = {"provider": "ollama", "name": "qwen3-embedding:0.6b", "revision": "qwen3-embedding-0.6b-r1", "normalization": "raw", "dimensions": 1024}


def test_embed_side_is_keyword_required_and_v0_text_is_byte_identical():
    client = FakeEmbedOllama()
    router = ModelRouter({"ollama": client}, {"embedding": dict(V0)})

    assert router.embed("xin chào", side="query") == ([0.1, 0.2, 0.3], "qwen3-embedding:0.6b")
    router.embed("xin chào", side="passage")
    assert client.embedded == [("qwen3-embedding:0.6b", "xin chào")] * 2, "no prefix keys on v0: the vectors cannot move on landing"

    with pytest.raises(TypeError):
        router.embed("xin chào", "query")  # positional side: a missed caller must fail loudly
    with pytest.raises(TypeError):
        router.embed("xin chào")
    with pytest.raises(ValueError):
        router.embed("xin chào", side="passge")
    assert client.embedded == [("qwen3-embedding:0.6b", "xin chào")] * 2, "a refused call never reaches Ollama"


def test_embed_prefixes_each_side_from_the_config_block_and_returns_the_bare_name():
    client = FakeEmbedOllama()
    e5 = {"provider": "ollama", "name": "local-ai/multilingual-e5-large:q8", "query_prefix": "query: ", "passage_prefix": "passage: "}
    router = ModelRouter({"ollama": client}, {"embedding": e5})

    _, query_model = router.embed("xin chào", side="query")
    _, passage_model = router.embed("xin chào", side="passage")

    assert [text for _, text in client.embedded] == ["query: xin chào", "passage: xin chào"]
    assert query_model == passage_model == "local-ai/multilingual-e5-large:q8", "the cache identity compares the bare name"


def test_require_embedding_is_the_refusal_the_index_cache_path_calls_first():
    """PostgresDocumentService._embed_with_cache answers cache hits without embed(); it calls
    this first, so a hit can never route around a `degraded` role (index-safety review)."""
    router = ModelRouter({}, {"embedding": dict(V0)}, embedding_refusal="collection documents does not exist while active chunks = 10")
    with pytest.raises(EmbeddingRefusedError, match="see /models.registry"):
        router.require_embedding()
    assert ModelRouter({}, {"embedding": dict(V0)}).require_embedding() is None


def test_embedding_refusal_raises_before_any_ollama_call_as_a_model_not_loaded_error():
    class Exploding(OllamaClient):
        def __init__(self):
            pass

        def embed(self, model, text):
            raise AssertionError("a degraded embedding role must never reach Ollama")

    reason = "probe width 768 != dimensions 1024 (embedding-v0); rebuild_qdrant"
    router = ModelRouter({"ollama": Exploding()}, {"embedding": dict(V0)}, embedding_refusal=reason)

    with pytest.raises(OllamaModelNotLoadedError) as excinfo:
        router.embed("xin chào", side="query")

    assert isinstance(excinfo.value, EmbeddingRefusedError)
    assert reason in str(excinfo.value) and "/models.registry" in str(excinfo.value)
    # The existing except-branches map the subclass to 502 MODEL_NOT_LOADED; the RQ
    # classifier keeps it non-retryable, so an index run fails instead of looping.
    assert classify_error(excinfo.value) == (False, "UNEXPECTED_ERROR")
    assert ModelRouter({"ollama": Exploding()}, {"embedding": dict(V0)}).embedding_refusal is None
