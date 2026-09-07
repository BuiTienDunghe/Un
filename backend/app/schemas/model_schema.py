from typing import Any

from pydantic import BaseModel

from app.utils.vi_tokenizer import TOKENIZER_VERSION


class ModelsResponse(BaseModel):
    models: dict[str, dict[str, Any]]
    # T16: the segmentation contract behind every BM25 lexeme, reported by the
    # SERVER rather than guessed by the caller — the eval harness reads the
    # embedding model from this same endpoint for exactly that reason, and a
    # baseline is only comparable across an identical pair.
    tokenizer_version: str = TOKENIZER_VERSION
    # Model registry (additive, same reasoning as tokenizer_version): one row per
    # role — {active, requested, loaded, source, status, reason, verified, name,
    # digest, fallback, collections (embedding), latency_ms (reranker)}. A report
    # writer refuses to write a baseline while any `fallback` is true, and the
    # nightly refuses to grade one, so "which version produced this number" is
    # answered by the server, never by the caller's guess.
    registry: dict[str, dict[str, Any]] = {}
    # The retrieval flags this process actually runs with (contextual_retrieval,
    # reranker, retrieval_mode), read AFTER the reranker warmup so a rejected
    # chain reports reranker: false; a baseline records them from here.
    rag: dict[str, Any] = {}
