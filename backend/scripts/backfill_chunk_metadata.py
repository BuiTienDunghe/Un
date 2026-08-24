"""T15 backfill: fill locations/heading_path/token_count on rows written before the fix.

`replace_chunks` dropped three chunker-computed columns until T15, so every
chunk indexed before the fix carries NULLs there and every production citation
showed `heading_path: null`. This script repairs rows IN PLACE:

- `token_count` is recomputed from the stored `content` alone — always safe.
- `heading_path`/`locations` need the chunker; pages are re-chunked from the
  stored `document_pages` rows (the same reconstruction `index_for_worker`
  uses) and are written ONLY when every recomputed chunk's content hash equals
  the stored `content_hash`. A mismatch means the chunker or its config moved
  since indexing — those versions are reported and left untouched rather than
  guessed at.
- `retrieval_context`, embeddings, Qdrant and version rows are never touched:
  re-indexing would regenerate the situating context (a model call per chunk)
  and silently shift retrieval ranking, which this backfill exists to avoid.

Candidate rows are those with `token_count IS NULL`: the chunker has always
set it since T15, so NULL is a reliable pre-T15 marker. Default is a dry run;
pass --apply to write.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import DocumentChunk
from app.postgres.repositories import PostgresDocumentRepository
from app.utils.chunking import chunk_pages, count_tokens


@dataclass
class Report:
    versions_matched: int = 0
    versions_no_pages: int = 0
    versions_content_drift: int = 0
    versions_page_mismatch: int = 0
    chunks_token_count: int = 0
    chunks_heading_path: int = 0
    chunks_locations: int = 0
    skipped_versions: list[tuple[str, str]] = field(default_factory=list)

    def line(self) -> str:
        return (
            f"versions: matched={self.versions_matched} no_pages={self.versions_no_pages} "
            f"content_drift={self.versions_content_drift} page_mismatch={self.versions_page_mismatch} | "
            f"chunks updated: token_count={self.chunks_token_count} "
            f"heading_path={self.chunks_heading_path} locations={self.chunks_locations}"
        )


def backfill(sessions: sessionmaker, chunk_tokens: int, overlap_tokens: int, apply: bool) -> Report:
    report = Report()
    with sessions() as session:
        version_ids = list(session.scalars(
            select(DocumentChunk.version_id).where(DocumentChunk.token_count.is_(None)).distinct()
        ))
    for version_id in version_ids:
        # One transaction per version; nothing mutates unless apply=True, so a
        # dry run commits unchanged sessions (a no-op) and stays read-only.
        with sessions.begin() as session:
            stored = list(session.scalars(
                select(DocumentChunk).where(DocumentChunk.version_id == version_id).order_by(DocumentChunk.chunk_index)
            ))
            # The worker-path reconstruction (index_for_worker): stored pages in
            # page_number order, exactly what the original chunking consumed.
            pages = [
                (page.page_number, page.selected_text or "", page.extraction_method)
                for page in PostgresDocumentRepository(session).pages_for_version(version_id)
            ]

            def fill_token_counts() -> None:
                for chunk in stored:
                    if chunk.token_count is None:
                        if apply:
                            chunk.token_count = count_tokens(chunk.content)
                        report.chunks_token_count += 1

            if not pages:
                fill_token_counts()
                report.versions_no_pages += 1
                report.skipped_versions.append((version_id, "no_pages"))
                continue
            recomputed = chunk_pages(pages, chunk_tokens, overlap_tokens)
            hashes_match = len(recomputed) == len(stored) and all(
                sha256(fresh.content.encode()).hexdigest() == kept.content_hash
                for fresh, kept in zip(recomputed, stored)
            )
            if not hashes_match:
                fill_token_counts()
                report.versions_content_drift += 1
                report.skipped_versions.append((version_id, "content_drift"))
                continue
            pages_match = all(
                fresh.page_start == kept.page_start and fresh.page_end == kept.page_end
                for fresh, kept in zip(recomputed, stored)
            )
            if not pages_match:
                report.versions_page_mismatch += 1
                report.skipped_versions.append((version_id, "page_mismatch (heading/token filled, locations skipped)"))
            for fresh, kept in zip(recomputed, stored):
                if kept.token_count is None:
                    if apply:
                        kept.token_count = fresh.token_count
                    report.chunks_token_count += 1
                if kept.heading_path is None and fresh.heading_path:
                    if apply:
                        kept.heading_path = list(fresh.heading_path)
                    report.chunks_heading_path += 1
                if kept.locations is None and fresh.locations and pages_match:
                    if apply:
                        kept.locations = [
                            {"page": location.page, "start": location.start, "end": location.end}
                            for location in fresh.locations
                        ]
                    report.chunks_locations += 1
            report.versions_matched += 1
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run, print only)")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    rag_config = settings.load_models().get("rag", {})
    chunk_tokens = int(rag_config.get("chunk_tokens", rag_config.get("chunk_size", 480)))
    overlap_tokens = int(rag_config.get("chunk_overlap_tokens", rag_config.get("chunk_overlap", 80)))
    sessions = create_session_factory(create_postgres_engine(settings.database_url))
    report = backfill(sessions, chunk_tokens, overlap_tokens, apply=args.apply)
    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"[{mode}] {report.line()}")
    for version_id, reason in report.skipped_versions:
        print(f"  - {version_id}: {reason}")
    if not args.apply:
        print("No rows were written. Re-run with --apply to persist.")


if __name__ == "__main__":
    main()
