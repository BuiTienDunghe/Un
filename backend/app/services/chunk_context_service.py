"""Contextual retrieval (P4-2): situate each chunk before it is indexed.

Anthropic's contextual-retrieval result: prepending a short generated context
to every chunk before embedding AND before BM25 cuts retrieval failures by
~49% (~67% with reranking). Generation happens once per chunk at INDEX time —
the inference-budget invariant is untouched because answering a question still
costs the same number of model calls.

Placement contract (plan §1 invariants):
- Called between chunking and persistence, with NO database session open —
  the N general-model calls never sit inside a transaction.
- A per-chunk failure degrades to "no context" for that chunk; ingestion never
  fails because contextualization did. The old version stays live regardless.
- Citations are untouched: only ``combined_retrieval_text`` consumers (the
  embedding input and the BM25 tokens) ever see the generated text.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from time import perf_counter
from typing import Callable, Iterable

from loguru import logger

from app.utils.chunking import DocumentChunk, count_tokens

_SYSTEM_PROMPT = (
    "Bạn tạo ngữ cảnh truy hồi cho một đoạn trích tài liệu. "
    "Chỉ trả về phần ngữ cảnh, không chào hỏi, không giải thích."
)

_USER_TEMPLATE = (
    "<document>\n{document}\n</document>\n\n"
    "Đây là đoạn trích cần đặt vào ngữ cảnh của toàn tài liệu:\n"
    "<chunk>\n{chunk}\n</chunk>\n\n"
    "Viết MỘT đoạn ngắn (tối đa khoảng {budget} token, cùng ngôn ngữ với tài liệu) "
    "nói rõ: tài liệu này là gì và đoạn trích nằm ở phần nào / nói về điều gì trong đó. "
    "Ưu tiên nhắc lại các tên riêng, mã số, con số định danh giúp tìm kiếm đoạn này. "
    "Chỉ trả về phần ngữ cảnh."
)


class ChunkContextService:
    def __init__(self, router, enabled: bool = False, context_tokens: int = 80, document_char_cap: int = 12_000) -> None:
        self.router = router
        self.enabled = bool(enabled)
        self.context_tokens = int(context_tokens)
        self.document_char_cap = int(document_char_cap)

    @classmethod
    def from_config(cls, router, rag_config: dict, *, enabled_override: bool | None = None) -> "ChunkContextService":
        """Build the service from the models.yaml ``rag`` block, honouring a
        per-machine override.

        ``enabled_override`` is ``Settings.rag_contextual_retrieval_enabled``
        (env ``RAG_CONTEXTUAL_RETRIEVAL_ENABLED``): ``None`` follows the shared
        models.yaml default; ``True``/``False`` lets one machine diverge without
        editing a versioned file. The API process and the RQ worker both build
        through here so the two index paths can never disagree on the flag.
        """
        config = rag_config.get("contextual_retrieval", {}) or {}
        yaml_enabled = bool(config.get("enabled", False))
        enabled = yaml_enabled if enabled_override is None else bool(enabled_override)
        logger.bind(event="chunk_context_config", enabled=enabled, source="env" if enabled_override is not None else "models.yaml", yaml_enabled=yaml_enabled).info(
            "Contextual retrieval {} ({})", "ON" if enabled else "OFF", "per-machine env override" if enabled_override is not None else "models.yaml default"
        )
        return cls(
            router,
            enabled=enabled,
            context_tokens=int(config.get("context_tokens", 80)),
            document_char_cap=int(config.get("document_char_cap", 12_000)),
        )

    def annotate(
        self,
        chunks: list[DocumentChunk],
        pages: Iterable[tuple[int | None, str, str]],
        document_id: str = "",
        on_progress: Callable[[int, int], None] | None = None,
        long_call: Callable[[], object] | None = None,
    ) -> list[DocumentChunk]:
        """Return chunks with ``retrieval_context`` filled; disabled = passthrough.

        ``long_call`` is the worker's lease-protection context manager, wrapped
        around each model call exactly as the embedding loop does.
        """
        if not self.enabled or not chunks:
            return chunks
        document = self._document_text(pages)
        started = perf_counter()
        annotated: list[DocumentChunk] = []
        failures = 0
        for index, chunk in enumerate(chunks, 1):
            context = None
            try:
                with (long_call() if long_call else nullcontext()):
                    answer, _ = self.router.chat(
                        "general",
                        [
                            {"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": _USER_TEMPLATE.format(document=document, chunk=chunk.content, budget=self.context_tokens)},
                        ],
                    )
                context = self._trim(answer)
            except Exception as error:
                # Degrade, never fail: this chunk is indexed bare, the run
                # continues, and the log carries enough to count the damage.
                failures += 1
                logger.bind(event="chunk_context_failed", document_id=document_id, chunk_index=index - 1, error_type=type(error).__name__).warning("Chunk context generation failed; indexing the bare chunk")
            annotated.append(replace(chunk, retrieval_context=context))
            if on_progress:
                on_progress(index, len(chunks))
        logger.bind(
            event="chunk_context_done", document_id=document_id, chunks=len(chunks), failures=failures,
            seconds=round(perf_counter() - started, 1), model_calls=len(chunks),
        ).info("Contextualized {} chunks in {:.1f}s ({} failures)", len(chunks), perf_counter() - started, failures)
        return annotated

    def _document_text(self, pages: Iterable[tuple[int | None, str, str]]) -> str:
        text = "\n".join(page_text for _, page_text, _ in pages).strip()
        if len(text) <= self.document_char_cap:
            return text
        # Head keeps the framing (title, intro); the cap keeps the prompt
        # inside the general model's context window for large documents.
        return text[: self.document_char_cap]

    def _trim(self, answer: str) -> str | None:
        context = " ".join(str(answer or "").split()).strip()
        if not context:
            return None
        limit = self.context_tokens * 2  # the budget is a target; only runaway outputs are cut
        if count_tokens(context) > limit:
            context = " ".join(context.split()[:limit]).strip()
        return context or None
