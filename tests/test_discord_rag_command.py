"""P1-1: the /docs (né /hoi 19/08) document-QA path — client method, source footer, resolution."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from discord_bot.api_client import (
    BackendInsufficientContextError,
    BackendRagSource,
    BackendTimeoutError,
    BackendUnavailableError,
    LocalAgentClient,
    LocalAgentSettings,
)
from discord_bot.client import escape_discord_markdown, format_rag_sources


def test_rag_ask_sends_scope_and_parses_sources() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["payload"] = json.loads(request.content)
        seen["api_key"] = request.headers.get("X-API-Key")
        return httpx.Response(200, json={
            "answer": "Máy in cần bảo dưỡng 3 tháng một lần [Source 1].",
            "model_used": "test", "latency_ms": 1, "conversation_id": "conv_9",
            "sources": [
                {"filename": "so-tay.pdf", "page_start": 7, "page_end": 8, "content": "..."},
                {"filename": "so-tay.pdf", "page_start": None, "page_end": None},
                {"filename": 123},
            ],
        })

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend", api_key="secret-key"), http)
            result = await client.rag_ask("Bảo dưỡng thế nào?", document_ids=["doc_1"], conversation_id="conv_9")

        assert result.answer.startswith("Máy in")
        assert result.conversation_id == "conv_9"
        # The malformed entry is dropped instead of crashing the reply.
        assert [source.filename for source in result.sources] == ["so-tay.pdf", "so-tay.pdf"]
        assert result.sources[0].page_start == 7 and result.sources[0].page_end == 8

    asyncio.run(scenario())
    assert seen["path"] == "/rag/chat"
    assert seen["payload"] == {"message": "Bảo dưỡng thế nào?", "stream": False, "document_ids": ["doc_1"], "conversation_id": "conv_9"}
    assert seen["api_key"] == "secret-key"


def test_rag_ask_maps_insufficient_context_to_a_friendly_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error_code": "INSUFFICIENT_CONTEXT", "message": "no context"})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            with pytest.raises(BackendInsufficientContextError, match="tài liệu"):
                await client.rag_ask("Câu hỏi lạc đề?")

    asyncio.run(scenario())


def test_rag_ask_maps_qdrant_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error_code": "QDRANT_UNAVAILABLE", "message": "down"})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            with pytest.raises(BackendUnavailableError, match="Qdrant"):
                await client.rag_ask("Hỏi gì đó?")

    asyncio.run(scenario())


def test_rag_ask_uses_the_long_execute_timeout() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json={"answer": "ok", "sources": []})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend") as http:
            settings = LocalAgentSettings("http://backend", timeout_seconds=45.0, turn_execute_timeout_seconds=180.0)
            await LocalAgentClient(settings, http).rag_ask("Hỏi dài?")

    asyncio.run(scenario())
    # Retrieval + a full local-model answer cannot fit the 45s default budget.
    assert seen["timeout"]["read"] == 180.0


def test_rag_ask_timeout_is_a_friendly_vietnamese_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow model")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            with pytest.raises(BackendTimeoutError, match="thời gian"):
                await client.rag_ask("Câu hỏi?")

    asyncio.run(scenario())


def test_list_documents_parses_and_skips_malformed_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/documents"
        return httpx.Response(200, json=[
            {"document_id": "doc_1", "filename": "a.pdf", "status": "indexed"},
            {"document_id": "doc_2", "filename": "b.txt", "status": "processing"},
            {"filename": "no-id.pdf"},
        ])

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend") as http:
            documents = await LocalAgentClient(LocalAgentSettings("http://backend"), http).list_documents()
        assert [(d.document_id, d.status) for d in documents] == [("doc_1", "indexed"), ("doc_2", "processing")]

    asyncio.run(scenario())


def test_source_footer_groups_duplicate_files_and_keeps_marker_numbering() -> None:
    sources = [
        BackendRagSource("bao-cao_*quy1*.pdf", 2, 2),
        BackendRagSource("phu-luc.pdf", 5, 6),
        BackendRagSource("bao-cao_*quy1*.pdf", 2, 2),
    ]

    footer = format_rag_sources(sources)

    # [Source n] markers in the answer cite positions, so grouped lines must
    # keep every index ("[1,3]"), never renumber. Underscores and asterisks in
    # filenames are escaped so Discord renders them literally.
    assert "[1,3] bao-cao\\_\\*quy1\\*.pdf · trang 2" in footer
    assert "[2] phu-luc.pdf · trang 5–6" in footer
    assert footer.startswith("**Nguồn:**")


def test_source_footer_handles_missing_pages_and_empty_lists() -> None:
    assert format_rag_sources([]) == ""
    footer = format_rag_sources([BackendRagSource("ghi-chu.txt", None, None)])
    assert footer == "**Nguồn:** [1] ghi-chu.txt"


def test_markdown_escaping_neutralizes_formatting_characters() -> None:
    assert escape_discord_markdown("a_b*c~d`e|f") == "a\\_b\\*c\\~d\\`e\\|f"
