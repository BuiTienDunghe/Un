from __future__ import annotations

from typing import Any, Literal
from collections.abc import Iterator

from app.llm_clients.ollama_client import OllamaClient, OllamaModelNotLoadedError
from app.llm_clients.gemini_client import GeminiClient
from app.llm_clients.deepseek_client import DeepSeekClient


# Union type for all supported clients
LLMClient = OllamaClient | GeminiClient | DeepSeekClient

# Which end of a retrieval pair a text is: the embedding version may prefix the
# two sides differently (multilingual-e5: "query: " / "passage: ").
EmbedSide = Literal["query", "passage"]


class EmbeddingRefusedError(OllamaModelNotLoadedError):
    """The embedding role is `degraded`: the model registry verified a contradiction
    between the version and its collections (probe width != record, collection width !=
    record, or a collection missing while the corpus is non-empty).

    A subclass on purpose: every existing except-branch (rag/chat/memory/documents
    routers, the SSE error event, job_errors -> non-retryable) already maps
    OllamaModelNotLoadedError to 502 MODEL_NOT_LOADED, so the refusal reaches the caller
    with a message naming the reason and /models.registry without a new router branch.
    Raised BEFORE any Ollama or Qdrant call: nothing ever writes foreign vectors into a
    collection, and no query pays the 2 s Qdrant retry sleep for a known-bad state.
    `ModelRouter.require_embedding()` is the check itself, for the one path that can hand
    out a vector without calling embed() — the index path's embedding cache.
    """


class ModelRouter:
    """Routes model requests to the correct LLM client based on ``provider`` in models.yaml.

    Supported providers
    -------------------
    - ``ollama``   – local Ollama inference server (default)
    - ``gemini``   – Google Gemini REST API
    - ``deepseek`` – DeepSeek API (OpenAI-compatible)

    To switch a model to a different provider, change the ``provider`` field
    in ``backend/app/config/models.yaml`` and restart the server.  The
    corresponding API key must be set in ``.env``.
    """

    def __init__(
        self,
        clients: dict[str, LLMClient],
        models: dict[str, dict[str, Any]],
        *,
        embedding_refusal: str | None = None,
    ) -> None:
        self.clients = clients
        self.models = models
        # The resolver's reason when the embedding role is degraded (None = serving).
        # A constructor argument, never a key of models["embedding"]: every key of
        # that dict is part of the embedding cache fingerprint (constraint 11), so a
        # bookkeeping key would invalidate every cached vector.
        self.embedding_refusal = embedding_refusal

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self, config: dict[str, Any]) -> LLMClient:
        provider = str(config.get("provider", "ollama")).lower()
        client = self.clients.get(provider)
        if client is None:
            available = ", ".join(self.clients.keys())
            raise RuntimeError(
                f"Provider '{provider}' is not configured. "
                f"Available providers: {available}. "
                f"Check that the corresponding API key is set in .env."
            )
        return client

    def _ollama_options(self, config: dict[str, Any]) -> dict[str, Any]:
        options = {key: config[key] for key in ("temperature", "top_p") if key in config}
        if "context" in config:
            options["num_ctx"] = config["context"]
        return options

    def _cloud_kwargs(self, config: dict[str, Any]) -> dict[str, Any]:
        """Extract keyword arguments understood by Gemini and DeepSeek clients."""
        kwargs: dict[str, Any] = {}
        if "temperature" in config:
            kwargs["temperature"] = config["temperature"]
        if "max_tokens" in config:
            kwargs["max_tokens"] = config["max_tokens"]
        if "top_p" in config:
            kwargs["top_p"] = config["top_p"]
        return kwargs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, mode: str, messages: list[dict[str, str]], options: dict[str, Any] | None = None) -> tuple[str, str]:
        """`options` overrides per-call generation knobs (e.g. num_predict for a
        short utility call) on top of the configured defaults. Keyword-optional
        so every existing caller keeps its exact behaviour."""
        if mode != "general":
            raise ValueError(f"Unsupported model mode: {mode}")
        config = self.models[mode]
        model_name = str(config["name"])
        client = self._get_client(config)

        if isinstance(client, OllamaClient):
            answer = client.chat(
                model=model_name,
                messages=messages,
                options={**self._ollama_options(config), **(options or {})},
                keep_alive=str(config.get("keep_alive", "5m")),
                think=config.get("think") if isinstance(config.get("think"), bool) else None,
            )
        elif isinstance(client, (GeminiClient, DeepSeekClient)):
            kwargs = self._cloud_kwargs(config)
            if options:
                # Cloud clients speak max_tokens, not Ollama's num_predict.
                if "num_predict" in options:
                    kwargs["max_tokens"] = options["num_predict"]
                if "temperature" in options:
                    kwargs["temperature"] = options["temperature"]
            answer = client.chat(model=model_name, messages=messages, **kwargs)
        else:
            raise RuntimeError(f"Unknown client type: {type(client)}")

        return answer, model_name

    def chat_tools(
        self,
        mode: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], str]:
        """One function-calling turn. Only the ollama provider supports the
        tools API; cloud providers raise so the caller can fall back."""
        if mode != "general":
            raise ValueError(f"Unsupported model mode: {mode}")
        config = self.models[mode]
        model_name = str(config["name"])
        client = self._get_client(config)
        if not isinstance(client, OllamaClient):
            raise RuntimeError("Tool calling requires the 'ollama' provider for the general model")
        result = client.chat_tools(
            model=model_name,
            messages=messages,
            tools=tools,
            options=self._ollama_options(config),
            keep_alive=str(config.get("keep_alive", "5m")),
            think=config.get("think") if isinstance(config.get("think"), bool) else None,
        )
        return result, model_name

    def require_embedding(self) -> None:
        """Raise EmbeddingRefusedError while the embedding role is `degraded`; a no-op otherwise.

        embed() calls it first, and so does PostgresDocumentService._embed_with_cache BEFORE
        its cache lookup: a cache hit answers without embed(), and a re-index of a document
        whose chunks are all cached would otherwise carry 1024-d vectors to upsert_chunks,
        whose _ensure_collection CREATES the collection the probe found missing — the next
        boot then probes `incomplete` for a one-document index instead of `degraded`, and
        the "run rebuild_qdrant" refusal the registry promises is silently gone.
        """
        if self.embedding_refusal is not None:
            raise EmbeddingRefusedError(f"Embedding refused: {self.embedding_refusal} (see /models.registry)")

    def embed(self, text: str, *, side: EmbedSide) -> tuple[list[float], str]:
        """Embedding always uses Ollama (cloud embedding not yet supported).

        ``side`` is keyword-REQUIRED: a caller that forgets it fails in the test suite,
        not by embedding with the wrong prefix in production. The prefix is
        ``config["query_prefix"]`` / ``config["passage_prefix"]`` — absent on
        embedding-v0, so its vectors are byte-identical to before the registry landed —
        and it lives INSIDE the config block on purpose: a prefix change re-keys the
        embedding cache because the vectors differ. The returned model name is the
        bare config name; the cache identity compares it.
        """
        self.require_embedding()
        if side not in ("query", "passage"):
            raise ValueError(f"embed side must be 'query' or 'passage', got {side!r}")
        config = self.models["embedding"]
        model_name = str(config["name"])
        # Embedding is only supported via Ollama regardless of provider field
        ollama = self.clients.get("ollama")
        if not isinstance(ollama, OllamaClient):
            raise RuntimeError("Embedding requires the 'ollama' provider to be configured")
        prefix = str(config.get(f"{side}_prefix") or "")
        return ollama.embed(model_name, prefix + text), model_name

    def stream_chat(self, mode: str, messages: list[dict[str, str]]) -> tuple[Iterator[str], str]:
        if mode != "general":
            raise ValueError(f"Unsupported model mode: {mode}")
        config = self.models[mode]
        model_name = str(config["name"])
        client = self._get_client(config)

        if isinstance(client, OllamaClient):
            stream = client.stream_chat(
                model_name,
                messages,
                self._ollama_options(config),
                str(config.get("keep_alive", "5m")),
                think=config.get("think") if isinstance(config.get("think"), bool) else None,
            )
        elif isinstance(client, GeminiClient):
            stream = client.stream_chat(model=model_name, messages=messages, **self._cloud_kwargs(config))
        elif isinstance(client, DeepSeekClient):
            stream = client.stream_chat(model=model_name, messages=messages, **self._cloud_kwargs(config))
        else:
            raise RuntimeError(f"Unknown client type: {type(client)}")

        return stream, model_name

    def ocr(self, image_base64: str, prompt: str = "Text Recognition:") -> tuple[str, str]:
        """Extract text from a base64-encoded image using the OCR vision model.

        OCR is always routed through Ollama (vision API requires local model).
        """
        config = self.models.get("ocr")
        if config is None or not config.get("enabled", False):
            raise ValueError("OCR fallback is disabled or not configured in models.yaml")
        model_name = str(config["name"])
        ollama = self.clients.get("ollama")
        if not isinstance(ollama, OllamaClient):
            raise RuntimeError("OCR requires the 'ollama' provider to be configured")
        options: dict[str, Any] = {}
        if "temperature" in config:
            options["temperature"] = config["temperature"]
        if "context" in config:
            options["num_ctx"] = config["context"]
        answer = ollama.vision_chat(
            model=model_name,
            prompt=prompt,
            images_base64=[image_base64],
            options=options,
            keep_alive=str(config.get("keep_alive", "5m")),
        )
        return answer, model_name
