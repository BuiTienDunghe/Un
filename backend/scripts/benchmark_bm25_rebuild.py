"""Measure the real BM25 rebuild cost on the real corpus. Read-only.

Plan §4c#3 justifies P4-4a (and option B) with one number — "98.1% of rebuild
time is pyvi tokenization" — extrapolated from a 27-chunk fixture, the exact
practice §6 records as having produced 2x errors twice. This script replaces
the extrapolation with a measurement on whatever corpus DATABASE_URL points
at, and separates the pieces so A(c) (hide the rebuild in a background thread)
can be weighed against B (persist the tokens) on evidence:

  cold first question   what the user actually pays after every restart
                        (fingerprint + snapshot + tokenize incl. pyvi init
                        + BM25Okapi build + one scoring pass)
  tokenize share        steady-state pyvi share of a rebuild — the piece B
                        erases and A(c) merely hides
  warm per-query        scoring cost while the index is hot, the piece only
                        P4-4b would change
  fallback per-query    the all-zero-score path after the 24/08 reuse patch

Only SELECTs are issued. Nothing is written anywhere; results go to stdout
(human lines + one JSON blob) for docs/p4_progress.md to quote.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from time import perf_counter

# The 22/08 lesson: a bare console on this machine is cp1252 and dies on the
# first Vietnamese character. The launcher exports PYTHONUTF8=1; a diagnostic
# script must not depend on being started from it.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in {"utf-8", "utf8"}:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rank_bm25 import BM25Okapi

from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.services.postgres_bm25_service import PostgresBm25Service
from app.utils.chunking import combined_retrieval_text
from app.utils.vi_tokenizer import tokenize_vietnamese

# Shaped like D1 questions: Vietnamese, a handful of content words.
DEFAULT_QUERIES = [
    "cơ chế attention trong mô hình transformer hoạt động thế nào",
    "quy trình backup và restore postgres gồm những bước nào",
    "phiên bản tài liệu được kích hoạt ra sao",
]


def _timed(fn) -> tuple[float, object]:
    start = perf_counter()
    result = fn()
    return perf_counter() - start, result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=7, help="warm-path repetitions per query (median reported)")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    sessions = create_session_factory(create_postgres_engine(settings.database_url))

    # ── Cold first question: one fresh service, one search, nothing pre-warmed.
    # pyvi loads its model lazily inside the first tokenize call, exactly as it
    # does in a freshly started API process, so its init cost belongs here.
    service = PostgresBm25Service(sessions)
    cold_s, _ = _timed(lambda: service.search(DEFAULT_QUERIES[0], 5))
    chunks = service._chunks
    if not chunks:
        raise RuntimeError("Active corpus is empty; nothing to measure")
    texts = [combined_retrieval_text(chunk.retrieval_context, chunk.content) for chunk in chunks]

    # ── Steady-state breakdown of one rebuild, pyvi already initialized.
    fingerprint_s, _ = _timed(service._current_fingerprint)
    snapshot_s, _ = _timed(service._snapshot)
    tokenize_s, corpus_tokens = _timed(lambda: [tokenize_vietnamese(text) for text in texts])
    build_s, _ = _timed(lambda: BM25Okapi(corpus_tokens))
    rebuild_s = fingerprint_s + snapshot_s + tokenize_s + build_s

    # ── Warm query paths on the already-built index.
    def median_search(question: str) -> float:
        return statistics.median(_timed(lambda: service.search(question, 5))[0] for _ in range(args.repeats))

    warm_ms = {question[:40]: round(median_search(question) * 1000, 2) for question in DEFAULT_QUERIES}
    fallback_ms = round(median_search("zzz qqq xxx yyy www") * 1000, 2)  # no token overlaps anything → all-zero path

    report = {
        "corpus": {"active_chunks": len(chunks), "corpus_chars": sum(len(text) for text in texts), "tokens": sum(len(tokens) for tokens in corpus_tokens)},
        "cold_first_question_s": round(cold_s, 3),
        "rebuild_steady_state": {
            "total_s": round(rebuild_s, 3),
            "fingerprint_s": round(fingerprint_s, 4),
            "snapshot_s": round(snapshot_s, 4),
            "tokenize_s": round(tokenize_s, 3),
            "bm25_build_s": round(build_s, 4),
            "tokenize_share": round(tokenize_s / rebuild_s, 3),
        },
        "warm_query_median_ms": warm_ms,
        "fallback_query_median_ms": fallback_ms,
        "repeats": args.repeats,
    }
    share = report["rebuild_steady_state"]["tokenize_share"]
    print(f"corpus: {len(chunks)} active chunks, {report['corpus']['corpus_chars']} chars")
    print(f"cold first question (incl. pyvi init): {cold_s:.3f}s")
    print(f"steady-state rebuild: {rebuild_s:.3f}s  (tokenize {tokenize_s:.3f}s = {share:.1%}, snapshot {snapshot_s * 1000:.1f}ms, fingerprint {fingerprint_s * 1000:.1f}ms, bm25 build {build_s * 1000:.1f}ms)")
    print(f"warm query median: {warm_ms}")
    print(f"fallback (all-zero) query median: {fallback_ms}ms")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
