from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.discord_memory_rule_filter import (
    DISCORD_MEMORY_RULE_FILTER_POLICY_VERSION,
    DiscordMemoryFilterInput,
    DiscordMemoryRuleFilter,
    normalize_discord_memory_text,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "discord_memory_rule_filter_v1.json"
)
CASES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _source(text: str, **overrides) -> DiscordMemoryFilterInput:
    values = {
        "turn_id": uuid4(),
        "source_discord_message_id": f"message-{uuid4()}",
        "author_id": "stable-author-id",
        "guild_id": "guild-id",
        "channel_id": "channel-id",
        "thread_id": None,
        "request_text": text,
        "turn_status": "completed",
        "delivery_exists": True,
        "session_state": "active",
    }
    values.update(overrides)
    return DiscordMemoryFilterInput(**values)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_versioned_vietnamese_filter_fixture(case):
    result = DiscordMemoryRuleFilter().evaluate(_source(case["text"]))
    allowed_reasons = case["expected_reason"]
    if isinstance(allowed_reasons, str):
        allowed_reasons = [allowed_reasons]
    assert result.decision == case["expected_decision"]
    assert result.reason_code in allowed_reasons
    assert result.policy_version == DISCORD_MEMORY_RULE_FILTER_POLICY_VERSION


def test_fixture_metrics_meet_acceptance_thresholds():
    filter_service = DiscordMemoryRuleFilter()
    expected = []
    actual = []
    reason_matches = 0
    explicit_expected = 0
    explicit_detected = 0
    critical_false_positives = []
    for case in CASES:
        result = filter_service.evaluate(_source(case["text"]))
        expected_candidate = case["expected_decision"] == "candidate"
        actual_candidate = result.decision == "candidate"
        expected.append(expected_candidate)
        actual.append(actual_candidate)
        allowed = case["expected_reason"]
        allowed = [allowed] if isinstance(allowed, str) else allowed
        reason_matches += int(result.reason_code in allowed)
        if case["id"].startswith(("remember_", "forget_", "correction_")):
            explicit_expected += 1
            explicit_detected += int(actual_candidate)
        if (
            "critical" in case.get("notes", "")
            and not expected_candidate
            and actual_candidate
        ):
            critical_false_positives.append(case["id"])

    true_positive = sum(e and a for e, a in zip(expected, actual))
    false_positive = sum(not e and a for e, a in zip(expected, actual))
    false_negative = sum(e and not a for e, a in zip(expected, actual))
    true_negative = sum(not e and not a for e, a in zip(expected, actual))
    candidate_precision = true_positive / (true_positive + false_positive)
    candidate_recall = true_positive / (true_positive + false_negative)
    no_op_precision = true_negative / (true_negative + false_negative)
    explicit_recall = explicit_detected / explicit_expected
    reason_accuracy = reason_matches / len(CASES)

    assert len(CASES) >= 100
    assert candidate_precision >= 0.95
    assert candidate_recall >= 0.80
    assert no_op_precision >= 0.80
    assert explicit_recall == 1.0
    assert critical_false_positives == []
    assert reason_accuracy >= 0.95


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"memory_policy_enabled": False}, "memory_policy_disabled"),
        ({"author_id": None}, "missing_trusted_author"),
        ({"source_role": "assistant"}, "bot_or_system_message"),
        ({"duplicate_source": True}, "duplicate_source"),
        ({"turn_status": "running"}, "unsupported_scope"),
        ({"delivery_exists": False}, "unsupported_scope"),
        ({"session_state": "closed"}, "unsupported_scope"),
        ({"guild_id": None}, "unsupported_scope"),
        ({"thread_id": "thread", "thread_enabled": False}, "unsupported_scope"),
    ],
)
def test_trusted_metadata_policy_exclusions_fail_closed(overrides, reason):
    result = DiscordMemoryRuleFilter().evaluate(
        _source("Hãy nhớ thông tin này.", **overrides)
    )
    assert result.decision == "rejected_policy"
    assert result.reason_code == reason
    assert result.candidate_strength == "none"


def test_normalization_is_stable_and_preserves_negation():
    display, match = normalize_discord_memory_text(
        "  KHÔNG   phải 16 GB mà là 32 GB  "
    )
    assert display == "KHÔNG phải 16 GB mà là 32 GB"
    assert "không" in match
    first = DiscordMemoryRuleFilter().evaluate(_source(display))
    second = DiscordMemoryRuleFilter().evaluate(_source(display))
    assert first == second
    assert first.reason_code == "explicit_correction"


def test_mixed_assertion_wins_over_question_and_thanks():
    hardware = DiscordMemoryRuleFilter().evaluate(
        _source("Máy tôi có RAM 32 GB, vậy chạy model nào?")
    )
    preference = DiscordMemoryRuleFilter().evaluate(
        _source("Cảm ơn nhé, từ giờ hãy trả lời bằng tiếng Việt.")
    )
    assert (hardware.decision, hardware.reason_code) == (
        "candidate",
        "hardware_configuration",
    )
    assert (preference.decision, preference.reason_code) == (
        "candidate",
        "durable_preference",
    )


def test_raw_text_is_not_rewritten_by_filter():
    raw = "  <@1522310732912398527>   Hãy nhớ rằng tôi dùng tiếng Việt.  "
    source = _source(raw)
    result = DiscordMemoryRuleFilter().evaluate(source)
    assert source.request_text == raw
    assert result.reason_code == "explicit_remember"
    assert not hasattr(result, "canonical_fact")
