"""Hàm thuần của Không gian Nghiên cứu — chạy không cần Postgres hay Ollama.

PDF thử nghiệm được sinh tại chỗ bằng PyMuPDF, nên mỗi khẳng định về metadata /
mục lục là về đúng cái tệp ta vừa vẽ, không phải về một tệp mẫu ngoài repo.
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz
import httpx
import pytest

from app.schemas.research_schema import PaperSummary
from app.services import document_pages
from app.services.research_service import (
    ResearchService, bibtex_for, build_outline, compose_question, export_markdown, extract_metadata, paper_stages, parse_json_object,
    prune_schema, select_summary_text, short_name_from_title,
)


def _paper_pdf(path: Path, *, with_toc: bool = False) -> Path:
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((60, 40), "arXiv:2301.04567v2 [cs.CL] 11 Jan 2023", fontsize=8)
    page.insert_text((60, 120), "Attention Is Not Enough: A Study of", fontsize=20)
    page.insert_text((60, 146), "Retrieval for Vietnamese Law", fontsize=20)
    page.insert_text((60, 180), "Nguyen Van A, Tran Thi B and Le C", fontsize=11)
    page.insert_text((60, 200), "Hanoi University of Science", fontsize=9)
    page.insert_text((60, 240), "Abstract", fontsize=12)
    page.insert_text((60, 260), "We study retrieval. " * 8, fontsize=10)
    page.insert_text((60, 300), "1 Introduction", fontsize=14)
    page.insert_text((60, 320), "Body text of the introduction. " * 6, fontsize=10)
    page.insert_text((60, 360), "Figure 1: Overview of the pipeline.", fontsize=10)
    second = document.new_page(width=612, height=792)
    second.insert_text((60, 60), "2 Method", fontsize=14)
    second.insert_text((60, 80), "More body text here. " * 10, fontsize=10)
    second.insert_text((60, 120), "Table 1: Results on the held-out set.", fontsize=10)
    second.insert_text((60, 140), "Fig. 2 shows the ablation.", fontsize=10)
    if with_toc:
        document.set_toc([[1, "Introduction", 1], [1, "Method", 2], [2, "Ablation", 2]])
    document.save(str(path))
    document.close()
    return path


def test_metadata_takes_the_largest_font_as_title_and_the_next_line_as_authors(tmp_path):
    metadata = extract_metadata(_paper_pdf(tmp_path / "paper.pdf"))

    assert metadata["title"] == "Attention Is Not Enough: A Study of Retrieval for Vietnamese Law"
    assert metadata["authors"] == "Nguyen Van A, Tran Thi B and Le C"
    assert metadata["arxiv_id"] == "2301.04567"
    assert metadata["year"] == 2023


def test_metadata_on_a_broken_file_is_all_none(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    assert extract_metadata(bad) == {"title": None, "authors": None, "year": None, "arxiv_id": None, "doi": None}


def test_short_name_is_the_part_before_the_colon_capped_at_24_chars():
    assert short_name_from_title("Attention Is Not Enough: A Study") == "Attention Is Not Enough"
    assert len(short_name_from_title("A very long title without any colon that keeps going")) <= 24
    assert short_name_from_title("A very long title without any colon that keeps going") == "A very long title"
    assert short_name_from_title(None, "fallback") == "fallback"


def test_outline_uses_bookmarks_when_present(tmp_path):
    outline = build_outline(_paper_pdf(tmp_path / "toc.pdf", with_toc=True))

    assert outline["toc"] == [{"title": "Introduction", "page": 1, "level": 1}, {"title": "Method", "page": 2, "level": 1}, {"title": "Ablation", "page": 2, "level": 2}]


def test_outline_falls_back_to_font_size_headings_and_finds_figures_once(tmp_path):
    outline = build_outline(_paper_pdf(tmp_path / "notoc.pdf"))

    titles = [item["title"] for item in outline["toc"]]
    assert "1 Introduction" in titles and "2 Method" in titles
    assert all(len(title) <= 80 for title in titles)
    # Tiêu đề bài báo ở cỡ lớn nhất trang 1 không bị coi là mục.
    assert not any(title.startswith("Attention Is Not Enough") for title in titles)
    assert outline["figures"] == [{"label": "Figure 1", "page": 1}, {"label": "Table 1", "page": 2}, {"label": "Figure 2", "page": 2}]


def test_prune_schema_drops_grammar_breaking_keys_and_closes_the_object():
    pruned = prune_schema(PaperSummary.model_json_schema())

    dumped = json.dumps(pruned)
    for key in ("title", "default", "minLength", "maxLength", "allOf", "format"):
        assert f'"{key}"' not in dumped
    assert pruned["additionalProperties"] is False
    assert set(pruned["required"]) == set(PaperSummary.model_fields)


def test_summary_text_prefers_three_first_and_two_last_pages_within_the_cap():
    pages = [f"page{number} " * 50 for number in range(1, 11)]
    text = select_summary_text(pages, cap=100_000)

    assert "[Trang 1]" in text and "[Trang 3]" in text and "[Trang 9]" in text and "[Trang 10]" in text
    assert "[Trang 5]" not in text
    assert len(select_summary_text(pages, cap=500)) <= 500 + 5 * len("[Trang 10]\n") + 10
    assert select_summary_text(["", "   "]) == ""


def test_bibtex_builds_one_article_per_paper_with_only_known_fields():
    text = bibtex_for([
        {"short_name": "Attention Is Not Enough", "title": "Attention {Is} Not Enough", "authors": "A and B", "year": 2023, "arxiv_id": "2301.04567"},
        {"short_name": "Attention Is Not Enough", "title": "Second", "year": 2023},
        {"short_name": "", "title": None},
    ])

    assert text.startswith("@article{AttentionIsNotEnough2023,\n  title = {Attention \\{Is\\} Not Enough},\n  author = {A and B},\n  year = {2023},\n  eprint = {2301.04567},\n  archivePrefix = {arXiv}\n}")
    assert "@article{AttentionIsNotEnough2023a," in text
    assert "@article{paper,\n\n}" in text
    assert "doi" not in text


def test_export_markdown_has_title_meta_summary_highlights_and_notes():
    paper = {"title": "T", "short_name": "T", "authors": "A", "year": 2023, "status": "reading", "stars": 3, "tags": ["rag"], "summary": {"brief": "ngắn", "questions": ["q1", "q2"]}, "note_md": "ghi chú tự do"}
    annotations = [{"page": 3, "quote": "sau", "note": None, "created_at": "b"}, {"page": 1, "quote": "trước", "note": "nhớ", "created_at": "a"}]
    markdown = export_markdown(paper, annotations)

    assert markdown.startswith("# T\n")
    assert "- **Tác giả:** A" in markdown and "- **Tag:** rag" in markdown
    assert "**Tóm lược.** ngắn" in markdown and "- q1" in markdown
    assert markdown.index("«trước» — nhớ — tr. 1") < markdown.index("«sau» — tr. 3")
    assert markdown.rstrip().endswith("## Ghi chú\n\nghi chú tự do")


def test_stages_follow_the_document_status():
    assert paper_stages("indexed", None, None, None) == {"ocr": "done", "metadata": "pending", "outline": "pending", "summary": "pending"}
    assert paper_stages("processing", "x", {"toc": []}, {"brief": "b"})["ocr"] == "running"
    assert paper_stages("failed", None, None, None)["ocr"] == "failed"
    assert paper_stages("deleted", None, None, None)["ocr"] == "pending"


def test_parse_json_object_tolerates_fences_and_prose():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Đây là kết quả: {"a": [1, 2]} hết.') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        parse_json_object("[1, 2]")


def test_compose_question_wraps_the_quote_in_the_documented_shape():
    assert compose_question("Giải thích", None) == "Giải thích"
    assert compose_question(" Giải thích ", "đoạn  ") == 'Đoạn trích: "đoạn"\n\nCâu hỏi: Giải thích'


def test_words_are_normalised_to_unit_coordinates_and_rotated_pages_follow_the_image():
    words = document_pages.normalize_words([(10, 20, 110, 40, "Hello", 0, 0, 0), (0, 0, 5, 5, "  ", 0, 1, 0)], 200, 100)
    assert words == [{"x0": 0.05, "y0": 0.2, "x1": 0.55, "y1": 0.4, "text": "Hello", "block": 0, "line": 0}]
    # Xoay 90°: chữ ở hệ chưa xoay (trang 100×200) đi theo rotation_matrix sang ảnh 200×100.
    document = fitz.open()
    page = document.new_page(width=100, height=200)
    page.set_rotation(90)
    rotated = document_pages.normalize_words([(0, 0, 50, 10, "Top", 0, 0, 0)], float(page.rect.width), float(page.rect.height), page.rotation_matrix)
    document.close()
    assert rotated[0]["x0"] >= 0.9 and rotated[0]["y0"] == 0.0


def test_chunk_boxes_only_returns_real_bboxes_on_the_requested_page():
    locations = [{"page": 2, "start": 0, "end": 10}, {"page": 2, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.05}, {"page": 3, "bbox": [0, 0, 1, 0.5]}]
    assert document_pages.chunk_boxes(locations, 2) == [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.05}]
    assert document_pages.chunk_boxes(locations, 3) == [{"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.5}]
    assert document_pages.chunk_boxes(locations, 1) == []
    assert document_pages.chunk_boxes(None, 1) == []


def test_page_png_is_rendered_and_cached_on_disk(tmp_path):
    source = _paper_pdf(tmp_path / "p.pdf")
    cache = tmp_path / "pages"
    png = document_pages.render_page_png(source, 1, 110, cache)

    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert (cache / "1@110.png").read_bytes() == png
    assert document_pages.render_page_png(source, 1, 110, cache) == png
    with pytest.raises(document_pages.PageNotFoundError):
        document_pages.render_page_png(source, 3, 110, cache)
    assert document_pages.page_count(source) == 2
    assert document_pages.page_count(tmp_path / "missing.pdf") is None


def test_page_words_report_has_text(tmp_path):
    source = _paper_pdf(tmp_path / "p.pdf")
    words = document_pages.page_words(source, 1)
    assert words["page"] == 1 and words["has_text"] is True
    assert any(word["text"] == "Abstract" for word in words["words"])
    assert all(0 <= word["x0"] <= word["x1"] <= 1 for word in words["words"])

    blank = fitz.open()
    blank.new_page()
    blank.save(str(tmp_path / "blank.pdf"))
    blank.close()
    assert document_pages.page_words(tmp_path / "blank.pdf", 1) == {"page": 1, "width": 595.0, "height": 842.0, "has_text": False, "words": []}


class _Router:
    models = {"general": {"name": "qwen3:8b", "context": 8192}}


class _Response:
    def __init__(self, status_code: int, content: str | None = None) -> None:
        self.status_code = status_code
        self._content = content

    def json(self) -> dict:
        return {"message": {"content": self._content}}


def test_json_call_falls_back_to_plain_json_when_ollama_rejects_the_schema():
    calls: list[dict] = []

    def post(url, json, timeout):
        calls.append(json)
        if isinstance(json["format"], dict):
            return _Response(400)
        return _Response(200, '{"brief": "ok", "questions": ["a", "b", "c", "d"]}')

    service = ResearchService(None, None, ollama_base_url="http://ollama:11434/", model_router=_Router(), http_post=post)
    result, model = service._json_call([{"role": "user", "content": "x"}], PaperSummary.model_json_schema(), 5)

    assert model == "qwen3:8b" and result["brief"] == "ok"
    assert [type(call["format"]).__name__ for call in calls] == ["dict", "str"]
    assert calls[0]["think"] is False and calls[0]["stream"] is False and calls[0]["options"]["num_ctx"] == 8192
    assert calls[0]["format"]["additionalProperties"] is False


def test_json_call_maps_transport_failures_to_the_ollama_error_types():
    from app.llm_clients.ollama_client import OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError

    def timeout(url, json, timeout):
        raise httpx.ReadTimeout("slow")

    def missing(url, json, timeout):
        return _Response(404)

    def garbage(url, json, timeout):
        return _Response(200, "không phải json")

    schema = PaperSummary.model_json_schema()
    with pytest.raises(OllamaTimeoutError):
        ResearchService(None, None, ollama_base_url="http://x", model_router=_Router(), http_post=timeout)._json_call([], schema, 1)
    with pytest.raises(OllamaModelNotLoadedError):
        ResearchService(None, None, ollama_base_url="http://x", model_router=_Router(), http_post=missing)._json_call([], schema, 1)
    with pytest.raises(OllamaUnavailableError):
        ResearchService(None, None, ollama_base_url="http://x", model_router=_Router(), http_post=garbage)._json_call([], schema, 1)
    with pytest.raises(OllamaModelNotLoadedError):
        ResearchService(None, None, ollama_base_url="http://x", model_router=type("R", (), {"models": {}})(), http_post=garbage)._json_call([], schema, 1)


def test_thread_title_is_the_first_question_collapsed_and_capped_at_80():
    from app.services.research_service import thread_title_from_question

    assert thread_title_from_question("  Attention\n là gì?  ") == "Attention là gì?"
    assert thread_title_from_question("   ") is None
    long = thread_title_from_question("a" * 100)
    assert len(long) == 80 and long.endswith("…")


def test_attach_paper_refs_maps_citations_to_papers_and_keeps_the_page():
    from app.services.research_service import attach_paper_refs

    messages = [
        {"role": "user", "content": "?", "sources": []},
        {"role": "assistant", "content": "!", "sources": [{"document_id": "doc_1", "page_start": 3, "excerpt": "x"}, {"document_id": "doc_gone", "page_start": None, "excerpt": "y"}]},
    ]
    out = attach_paper_refs(messages, {"doc_1": {"paper_id": "pap_1", "short_name": "Attention", "color_index": 2}})
    assert out[0]["sources"] == []
    first, gone = out[1]["sources"]
    assert (first["paper_id"], first["short_name"], first["color_index"], first["page"]) == ("pap_1", "Attention", 2, 3)
    assert (gone["paper_id"], gone["short_name"], gone["color_index"], gone["page"]) == (None, None, None, None)
    assert messages[1]["sources"][0] == {"document_id": "doc_1", "page_start": 3, "excerpt": "x"}  # không sửa đầu vào
