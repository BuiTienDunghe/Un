"""Source-page counting needs no database, model, or GPU."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from app.postgres.models import Document, IngestionRun
from app.services.postgres_document_service import DocumentNotFoundError, PostgresDocumentService, SourceUnavailableError
from app.services.research_service import ResearchService
from app.services.source_page_counts import SourcePageCounts


def pdf_bytes(pages):
    pdf = fitz.open()
    for _ in range(pages):
        pdf.new_page()
    data = pdf.tobytes()
    pdf.close()
    return data


def test_reuses_only_the_current_source_revision(tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(pdf_bytes(2))
    calls = []
    def load(source):
        calls.append(source)
        from app.services.document_pages import page_count
        return page_count(source)
    counts = SourcePageCounts(loader=load)
    assert counts.count("doc", path, "old") == 2
    assert counts.count("doc", path, "old") == 2
    assert len(calls) == 1
    path.write_bytes(pdf_bytes(3))
    assert counts.count("doc", path, "new") == 3
    assert len(calls) == 2
    # The revision matters even if filesystem timestamps were preserved.
    assert counts.count("doc", path, "different-hash") == 3
    assert len(calls) == 3


def test_missing_or_unreadable_source_is_retried(tmp_path):
    path = tmp_path / "source.pdf"
    counts = SourcePageCounts()
    assert counts.count("doc", path) is None
    path.write_bytes(b"not a PDF")
    assert counts.count("doc", path) is None
    path.write_bytes(pdf_bytes(4))
    assert counts.count("doc", path) == 4
    path.unlink()
    assert counts.count("doc", path) is None
    path.write_bytes(pdf_bytes(5))
    assert counts.count("doc", path) == 5


def test_unknown_count_is_not_sticky_even_with_unchanged_stat(tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(b"test")
    answers = iter([None, 3])
    counts = SourcePageCounts(loader=lambda _: next(answers))
    assert counts.count("doc", path) is None
    assert counts.count("doc", path) == 3


def test_source_changed_during_read_is_not_cached(tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(pdf_bytes(1))
    def changing_loader(source):
        path.write_bytes(pdf_bytes(5))
        return 1
    counts = SourcePageCounts(loader=changing_loader)
    assert counts.count("doc", path) is None
    counts._loader = None
    assert counts.count("doc", path) == 5


def test_cache_evicts_least_recently_used_document(tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(b"fixture")
    calls = []
    counts = SourcePageCounts(max_entries=2, loader=lambda p: calls.append(p) or 1)
    for doc in ("a", "b", "a", "c", "a", "b"):
        assert counts.count(doc, path) == 1
    assert len(calls) == 4
    with pytest.raises(ValueError):
        SourcePageCounts(max_entries=0)


def test_known_metadata_must_cover_the_file(tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(pdf_bytes(3))
    def unexpected_read(_):
        pytest.fail("covered metadata should avoid PDF IO")
    counts = SourcePageCounts(loader=unexpected_read)
    assert counts.count("doc", path, known_pages=3, known_at=datetime.now(UTC) + timedelta(days=1)) == 3
    counts.clear()
    counts._loader = None
    assert counts.count("doc", path, known_pages=2, known_at=datetime(2000, 1, 1, tzinfo=UTC)) == 3
    counts.clear()
    assert counts.count("doc", path, known_pages=2, known_at=datetime(2100, 1, 1)) == 3


@pytest.mark.parametrize("status", ["deleting", "deleted"])
def test_preloaded_source_preserves_deleted_document_guard(tmp_path, status):
    service = PostgresDocumentService(None, None, None, None, None, tmp_path, 480, 80, None)
    doc = Document(id="doc", status=status, stored_filename="source.pdf", original_filename="source.pdf", source_available=True)
    with pytest.raises(DocumentNotFoundError):
        service.source_file_for(doc)


def test_preloaded_source_preserves_unavailable_guard(tmp_path):
    service = PostgresDocumentService(None, None, None, None, None, tmp_path, 480, 80, None)
    folder = tmp_path / "doc"
    folder.mkdir()
    (folder / "original.pdf").write_bytes(pdf_bytes(2))
    doc = Document(id="doc", status="indexed", stored_filename="source.pdf", original_filename="source.pdf", source_available=False)
    with pytest.raises(SourceUnavailableError):
        service.source_file_for(doc)
    doc.source_available = True
    assert service.source_file_for(doc) == (folder / "original.pdf", "source.pdf")


def test_legacy_source_adapter_stays_supported(tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(pdf_bytes(8))
    class Source:
        def source_file(self, document_id):
            return path, path.name
    service = ResearchService(None, Source(), ollama_base_url="http://127.0.0.1:1")
    doc = Document(id="doc", status="uploaded", content_hash="first")
    assert service._total_pages(doc, None) == 8
    path.write_bytes(pdf_bytes(12))
    doc.content_hash = "second"
    assert service._total_pages(doc, None) == 12


@pytest.mark.parametrize("status", ["processing", "indexed", "uploaded"])
def test_old_run_cannot_override_replaced_source(tmp_path, status):
    path = tmp_path / "source.pdf"
    path.write_bytes(pdf_bytes(12))
    class Source:
        def source_file(self, document_id):
            return path, path.name
    old = datetime(2000, 1, 1, tzinfo=UTC)
    doc = Document(id="doc", status=status, content_hash="new", active_version_id="v1",
                   updated_at=datetime.now(UTC), indexed_at=old)
    run = IngestionRun(id="old", document_id="doc", version_id="v1", total_pages=8, completed_at=old)
    service = ResearchService(None, Source(), ollama_base_url="http://127.0.0.1:1")
    assert service._total_pages(doc, run) == 12


def test_historical_page_count_survives_source_removal():
    class Source:
        def source_file(self, document_id):
            raise SourceUnavailableError(document_id)
    service = ResearchService(None, Source(), ollama_base_url="http://127.0.0.1:1")
    assert service._total_pages(Document(id="doc"), SimpleNamespace(total_pages=8)) == 8


def test_unstable_source_does_not_fall_back_to_stale_run(tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(pdf_bytes(8))
    class Source:
        def source_file(self, document_id):
            return path, path.name
    service = ResearchService(None, Source(), ollama_base_url="http://127.0.0.1:1")
    def replacing_loader(_):
        path.write_bytes(pdf_bytes(12))
        return 8
    service._page_counts = SourcePageCounts(loader=replacing_loader)
    doc = Document(id="doc", status="processing", content_hash="new")
    run = IngestionRun(total_pages=8)
    assert service._total_pages(doc, run) is None


@pytest.mark.parametrize("suffix", [".txt", ".md", ".docx"])
def test_non_pdf_keeps_parser_pages_after_metadata_only_update(tmp_path, suffix):
    path = tmp_path / ("source" + suffix)
    path.write_bytes(b"source fixture")
    class Source:
        def source_file(self, document_id):
            return path, path.name
    service = ResearchService(None, Source(), ollama_base_url="http://127.0.0.1:1")
    def unexpected_read(_):
        pytest.fail("non-PDF must use parser page metadata")
    service._page_counts = SourcePageCounts(loader=unexpected_read)
    old = datetime(2000, 1, 1, tzinfo=UTC)
    doc = Document(id="doc", status="indexed", active_version_id="v1", indexed_at=old,
                   updated_at=datetime.now(UTC), content_hash="unchanged")
    run = IngestionRun(total_pages=3, version_id="v1", completed_at=old)
    assert service._total_pages(doc, run) == 3


def test_unchanged_cached_pdf_survives_unreadable_loader_after_metadata_edit(tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(pdf_bytes(8))
    class Source:
        def source_file(self, document_id):
            return path, path.name
    research = ResearchService(None, Source(), ollama_base_url="http://127.0.0.1:1")
    doc = Document(id="doc", status="indexed", active_version_id="v1", content_hash="same-source",
                   updated_at=datetime.now(UTC))
    run = IngestionRun(total_pages=8, version_id="v1", completed_at=datetime(2000, 1, 1, tzinfo=UTC))
    assert research._total_pages(doc, run) == 8  # Count the actual PDF once.
    research._page_counts._loader = lambda _: None
    doc.updated_at = datetime.now(UTC)
    # A cached count with the exact current revision/fingerprint is proof.
    assert research._total_pages(doc, run) == 8


def test_cold_uncertain_pdf_does_not_guess_historical_count(tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(pdf_bytes(8))
    class Source:
        def source_file(self, document_id):
            return path, path.name
    research = ResearchService(None, Source(), ollama_base_url="http://127.0.0.1:1")
    research._page_counts = SourcePageCounts(loader=lambda _: None)
    doc = Document(id="doc", status="indexed", active_version_id="v1", content_hash="current",
                   updated_at=datetime.now(UTC))
    run = IngestionRun(total_pages=8, version_id="v1", completed_at=datetime(2000, 1, 1, tzinfo=UTC))
    # Without a cached fingerprint or covered metadata, a metadata-only edit
    # cannot be distinguished from a replaced source using this schema alone.
    assert research._total_pages(doc, run) is None


@pytest.mark.parametrize("status", ["processing", "indexed", "uploaded"])
def test_unreadable_changed_pdf_does_not_fall_back_to_old_run(tmp_path, status):
    path = tmp_path / "source.pdf"
    path.write_bytes(pdf_bytes(8))
    class Source:
        def source_file(self, document_id):
            return path, path.name
    research = ResearchService(None, Source(), ollama_base_url="http://127.0.0.1:1")
    doc = Document(id="doc", status=status, active_version_id="v1", content_hash="old",
                   updated_at=datetime.now(UTC))
    run = IngestionRun(total_pages=8, version_id="v1", completed_at=datetime(2000, 1, 1, tzinfo=UTC))
    assert research._total_pages(doc, run) == 8
    path.write_bytes(b"changed PDF cannot be decoded")
    doc.content_hash = "replacement"
    doc.updated_at = datetime.now(UTC)
    assert research._total_pages(doc, run) is None
