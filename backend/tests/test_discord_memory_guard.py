"""P2-1b: the deterministic auto-apply guard, and the proof it still matches
the benchmark it was designed from.

The last test re-derives the measured policy numbers (coverage/poison on the
stored qwen3.5:9b results) using the PRODUCTION guard functions — if someone
tunes the guard and silently changes the trade-off, this fails.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.discord_memory_guard import (
    auto_apply_allowed,
    content_words,
    evidence_grounded,
    fact_overlap,
    fold,
)

BENCHMARK_9B = Path(__file__).parents[2] / "data" / "benchmarks" / "discord_memory_extractor_20260819_qwen9b_subset75.json"
FIXTURE = Path(__file__).parent / "fixtures" / "discord_memory_extractor_benchmark_v1.json"


def test_fold_is_accent_and_case_insensitive():
    assert fold("Tiếng Việt Đẹp") == "tieng viet dep"
    assert fold(None) == ""


def test_content_words_drop_stopwords_and_short_tokens():
    words = content_words("User prefers câu trả lời có ví dụ minh họa")
    assert "hoa" in words and "cau" in words
    assert "user" not in words and "prefers" not in words and "co" not in words
    # Accent folding makes "minh họa" collide with the stopword "mình" — an
    # accepted trade-off of accent-insensitive matching.
    assert "minh" not in words


def test_fact_overlap_accepts_grounded_and_rejects_hallucinated_facts():
    source = "Hãy nhớ rằng tôi luôn muốn câu trả lời có ví dụ minh họa cụ thể."
    assert fact_overlap("Người dùng muốn câu trả lời có ví dụ minh họa", source)
    # The live 19/08 hallucination: no content word in common with the source.
    assert not fact_overlap("User prefers Vietnamese.", source)
    assert not fact_overlap("", source)


def test_evidence_must_be_a_verbatim_quote():
    source = "Máy tôi dùng RAM DDR4 16GB."
    assert evidence_grounded("RAM DDR4 16GB", source)
    assert not evidence_grounded("RAM DDR5 16GB", source)
    assert not evidence_grounded("", source)


def test_auto_apply_allowed_needs_both_checks():
    source = "Hãy nhớ rằng tôi thích trả lời ngắn gọn."
    assert auto_apply_allowed(
        canonical_fact="Người dùng thích trả lời ngắn gọn.",
        evidence_text="tôi thích trả lời ngắn gọn",
        source_text=source,
    )
    assert not auto_apply_allowed(
        canonical_fact="Người dùng thích trả lời ngắn gọn.",
        evidence_text="một câu không hề có trong tin nhắn",
        source_text=source,
    )
    assert not auto_apply_allowed(canonical_fact="User prefers Vietnamese.", evidence_text=source, source_text=source)


def test_negation_clause_blocks_a_fact_its_source_denies():
    # The exact 9.1 triple: fact contradicts source, old guard ACCEPTED it.
    assert not auto_apply_allowed(
        canonical_fact="Dũng dùng Postgres",
        evidence_text="không dùng Postgres nữa",
        source_text="Dũng: thôi chốt bỏ Postgres nhé, không dùng Postgres nữa",
    )
    # Clause-scoped: negation in a DIFFERENT clause must not block.
    from app.services.discord_memory_guard import negation_clause_hit

    assert not negation_clause_hit(
        "GPU là RTX 3060", "tôi không thích trà, card tôi là RTX 3060"
    )


def test_single_content_word_facts_wait_for_a_human():
    # 9.2: {postgres} is the only content word and it hits an unrelated message.
    assert not auto_apply_allowed(
        canonical_fact="User prefers Postgres",
        evidence_text="postgres 16 ra rồi à",
        source_text="postgres 16 ra rồi à, ai thử chưa",
    )


def test_a_true_well_evidenced_fact_still_passes():
    # The guard's positive duty (e2e guard-03): fixing the two holes above
    # must not regress acceptance of grounded facts.
    assert auto_apply_allowed(
        canonical_fact="GPU là RTX 3060",
        evidence_text="card của tôi là RTX 3060",
        source_text="card của tôi là RTX 3060, mới lắp tuần trước",
    )


@pytest.mark.skipif(not BENCHMARK_9B.exists(), reason="stored 9b benchmark results missing")
def test_production_guard_reproduces_the_measured_benchmark_policy():
    """Policy C on qwen3.5:9b measured 19/08: coverage 96.7%, poison 21.6%.

    Re-derive both from the stored raw results with the production functions.
    Bounds carry a small margin so a legitimate retune fails loudly instead of
    drifting silently.
    """
    results = json.loads(BENCHMARK_9B.read_text(encoding="utf-8"))["results"]
    cases = {case["id"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}

    applied_wrong = applied_clean = clean_total = 0
    for result in results:
        if result["operation"] not in ("create", "update"):
            continue
        case = cases[result["id"]]
        proposal = result["normalized_output"] or {}
        severe = (
            case["expected_operation"] == "no_op"
            or not result["fact_contains_ok"]
            or not result["subject_id_ok"]
            or not result["fact_key_ok"]
        )
        clean_total += 0 if severe else 1
        if auto_apply_allowed(
            canonical_fact=proposal.get("canonical_fact"),
            evidence_text=proposal.get("evidence_text"),
            source_text=case["source_text"],
        ):
            if severe:
                applied_wrong += 1
            else:
                applied_clean += 1

    coverage = applied_clean / clean_total
    poison = applied_wrong / (applied_wrong + applied_clean)
    assert coverage >= 0.90, f"guard coverage collapsed: {coverage:.1%}"
    assert poison <= 0.25, f"guard lets too much poison through: {poison:.1%}"
