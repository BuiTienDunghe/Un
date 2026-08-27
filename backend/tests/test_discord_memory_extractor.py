from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.services.discord_memory_extractor import (
    DISCORD_MEMORY_EXTRACTOR_PROMPT_VERSION,
    DISCORD_MEMORY_EXTRACTOR_SYSTEM_PROMPT,
    DiscordMemoryExtractorAdapter,
    DiscordMemoryExtractorEnvelopeBuilder,
    DiscordMemoryExtractorOutputError,
    DiscordMemoryExtractorTransportError,
    DiscordMemoryProposalV1,
    ExtractorSource,
    ExtractorTarget,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _proposal(operation: str = "create", **overrides):
    payload = {
        "schema_version": "v1",
        "operation": operation,
        "memory_type": "preference",
        "subject_type": "member",
        "subject_id": "author-a",
        "scope": "member_in_guild",
        "fact_key": "user.preferred_language",
        "canonical_fact": "Người dùng ưu tiên tiếng Việt.",
        "evidence_text": "Tôi ưu tiên dùng tiếng Việt.",
        "source_turn_id": "11111111-1111-1111-1111-111111111111",
        "source_discord_message_id": "123456789",
        "confidence": 0.95,
        "reason_code": "explicit_preference",
        "target_memory_id": None,
    }
    if operation in {"update", "delete"}:
        payload["target_memory_id"] = "22222222-2222-2222-2222-222222222222"
    if operation == "delete":
        payload["canonical_fact"] = None
    if operation == "no_op":
        payload.update(
            {
                "memory_type": None,
                "subject_type": None,
                "subject_id": None,
                "scope": None,
                "fact_key": None,
                "canonical_fact": "",
                "evidence_text": None,
                "confidence": 0.0,
                "reason_code": "insufficient_evidence",
                "target_memory_id": None,
            }
        )
    payload.update(overrides)
    return payload


def _envelope(*, targets=(), author_id="author-a", text=None):
    return DiscordMemoryExtractorEnvelopeBuilder().build(
        source=ExtractorSource(
            turn_id=uuid4(),
            discord_message_id="123456789",
            author_id=author_id,
            guild_id="guild-a",
            channel_id="channel-a",
            thread_id=None,
            request_text=text or "Tôi ưu tiên dùng tiếng Việt.",
        ),
        filter_metadata={
            "stage": "rule_filter",
            "policy_version": "discord_memory_rule_filter_v2",
            "decision": "candidate",
            "reason_code": "durable_preference",
            "candidate_strength": "normal",
            "detected_intent": "preference",
            "matched_rules": ["durable_preference"],
        },
        targets=targets,
    )


@pytest.mark.parametrize("operation", ["create", "update", "delete", "no_op"])
def test_proposal_v1_accepts_valid_operation_shapes(operation):
    proposal = DiscordMemoryProposalV1.model_validate_json(
        json.dumps(_proposal(operation)),
        strict=True,
    )
    assert proposal.operation == operation


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: {**value, "unexpected": True},
        lambda value: {**value, "operation": "merge"},
        lambda value: {**value, "confidence": 1.01},
        lambda value: {**value, "confidence": -0.01},
        lambda value: {**value, "confidence": "0.9"},
        lambda value: {key: item for key, item in value.items() if key != "fact_key"},
        lambda value: {
            **value,
            "operation": "update",
            "target_memory_id": None,
        },
        lambda value: {
            **value,
            "operation": "delete",
            "target_memory_id": None,
        },
        lambda value: {
            **value,
            "operation": "create",
            "target_memory_id": "22222222-2222-2222-2222-222222222222",
        },
    ],
)
def test_proposal_v1_rejects_invalid_or_permissively_coerced_shapes(mutation):
    with pytest.raises(ValidationError):
        DiscordMemoryProposalV1.model_validate_json(
            json.dumps(mutation(_proposal())),
            strict=True,
        )


def test_schema_is_closed_and_contains_operation_conditionals():
    schema = DiscordMemoryExtractorAdapter.strict_proposal_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "v1"
    assert schema["properties"]["confidence"]["minimum"] == 0.0
    assert schema["properties"]["confidence"]["maximum"] == 1.0
    assert schema["allOf"]


def test_ollama_schema_preserves_closed_types_but_removes_unsupported_grammar():
    schema = DiscordMemoryExtractorAdapter.proposal_json_schema()
    serialized = json.dumps(schema)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "v1"
    assert "allOf" not in schema
    assert "maxLength" not in serialized
    assert "minimum" not in serialized


def test_exact_schema_mode_ollama_request_and_bounded_logging(caplog):
    calls = []
    envelope = _envelope()
    payload = _proposal(
        source_turn_id=envelope.source_turn_id,
        subject_id=envelope.current_author_id,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps(payload)},
                "total_duration": 8_000_000,
                "load_duration": 1_000_000,
                "prompt_eval_count": 120,
                "prompt_eval_duration": 2_000_000,
                "eval_count": 40,
                "eval_duration": 5_000_000,
            },
        )

    adapter = DiscordMemoryExtractorAdapter(
        base_url="http://ollama.test",
        seed=7391,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    with caplog.at_level("INFO"):
        result = adapter.extract(envelope)

    assert result.proposal.operation == "create"
    assert result.prompt_version == DISCORD_MEMORY_EXTRACTOR_PROMPT_VERSION
    assert len(calls) == 1
    request = calls[0]
    assert request["model"] == "qwen3.5:2b"
    assert request["stream"] is False
    assert request["think"] is False
    assert isinstance(request["format"], dict)
    assert request["format"]["additionalProperties"] is False
    assert request["options"] == {
        "temperature": 0.0,
        "seed": 7391,
        "num_ctx": 4096,
    }
    assert request["messages"][0] == {
        "role": "system",
        "content": DISCORD_MEMORY_EXTRACTOR_SYSTEM_PROMPT,
    }
    assert envelope.raw_request_text not in caplog.text
    assert "model=qwen3.5:2b" in caplog.text
    assert result.performance == {
        "total_duration": 8_000_000,
        "load_duration": 1_000_000,
        "prompt_eval_count": 120,
        "prompt_eval_duration": 2_000_000,
        "eval_count": 40,
        "eval_duration": 5_000_000,
    }


def test_json_fallback_is_used_only_when_explicitly_enabled():
    formats = []
    envelope = _envelope()
    payload = _proposal(
        source_turn_id=envelope.source_turn_id,
        subject_id=envelope.current_author_id,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        formats.append(body["format"])
        if len(formats) == 1:
            return httpx.Response(400, json={"error": "schema unsupported"})
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(payload)}},
        )

    adapter = DiscordMemoryExtractorAdapter(
        base_url="http://ollama.test",
        json_fallback=True,
        retry_count=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert adapter.extract(envelope).format_mode == "json_fallback"
    assert isinstance(formats[0], dict)
    assert formats[1] == "json"


def test_schema_rejection_does_not_silently_fallback():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "schema unsupported"})

    adapter = DiscordMemoryExtractorAdapter(
        base_url="http://ollama.test",
        json_fallback=False,
        retry_count=2,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(DiscordMemoryExtractorTransportError):
        adapter.extract(_envelope())
    assert calls == 1


def test_transient_timeout_retries_are_bounded():
    calls = 0
    envelope = _envelope()
    payload = _proposal(
        source_turn_id=envelope.source_turn_id,
        subject_id=envelope.current_author_id,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 2:
            raise httpx.ReadTimeout("temporary", request=request)
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(payload)}},
        )

    adapter = DiscordMemoryExtractorAdapter(
        base_url="http://ollama.test",
        retry_count=1,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    assert adapter.extract(envelope).proposal.operation == "create"
    assert calls == 2


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "```json\n{}\n```",
        "Here is JSON: {}",
    ],
)
def test_malformed_fenced_or_prose_output_is_not_retried(content):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"message": {"content": content}})

    adapter = DiscordMemoryExtractorAdapter(
        base_url="http://ollama.test",
        retry_count=3,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(DiscordMemoryExtractorOutputError):
        adapter.extract(_envelope())
    assert calls == 1


def test_envelope_uses_stable_id_and_never_derives_third_party_subject():
    envelope = _envelope(
        author_id="stable-author-b",
        text="Đạt nói rằng Dũng thích cà phê.",
    )
    assert envelope.current_author_id == "stable-author-b"
    assert envelope.trusted_subjects[0].subject_id == "stable-author-b"
    assert envelope.trusted_subjects[0].allowed_scopes == ("member_in_guild",)
    assert "Đạt" not in {
        subject.subject_id for subject in envelope.trusted_subjects
    }
    assert "Dũng" not in {
        subject.subject_id for subject in envelope.trusted_subjects
    }


def test_same_display_name_or_rename_cannot_change_envelope_identity():
    # Display snapshots are intentionally not part of ExtractorSource.
    first = _envelope(author_id="author-a")
    renamed = _envelope(author_id="author-a")
    other = _envelope(author_id="author-b")
    assert first.trusted_subjects == renamed.trusted_subjects
    assert first.trusted_subjects != other.trusted_subjects


def test_target_list_is_bounded_and_typed():
    targets = [
        ExtractorTarget(
            memory_id=uuid4(),
            fact_key="user.response_style",
            canonical_fact=f"fact {index}",
            memory_type="fact",
            scope="member_in_guild",
            version=1,
        )
        for index in range(25)
    ]
    envelope = _envelope(targets=targets)
    assert len(envelope.allowed_target_memories) == 20
    assert {
        (item.fact_key, item.memory_type)
        for item in envelope.allowed_fact_keys
    } == {
        ("user.preferred_language", "preference"),
        ("user.response_style", "preference"),
        # Vocabulary v2 (28/08): durable_preference carries the taste keys.
        ("user.favorite_drink", "preference"),
        ("user.favorite_food", "preference"),
    }


def test_fact_key_and_memory_type_must_match_trusted_pair():
    envelope = _envelope()
    payload = _proposal(
        source_turn_id=envelope.source_turn_id,
        subject_id=envelope.current_author_id,
        memory_type="fact",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(payload)}},
        )

    adapter = DiscordMemoryExtractorAdapter(
        base_url="http://ollama.test",
        retry_count=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(
        DiscordMemoryExtractorOutputError,
        match="fact key",
    ):
        adapter.extract(envelope)


def test_forged_subject_and_target_are_rejected_by_trusted_binding():
    envelope = _envelope()
    forged_subject = _proposal(
        source_turn_id=envelope.source_turn_id,
        subject_id="forged-author",
    )
    forged_target = _proposal(
        "update",
        source_turn_id=envelope.source_turn_id,
        subject_id=envelope.current_author_id,
    )
    outputs = iter((forged_subject, forged_target))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(next(outputs))}},
        )

    adapter = DiscordMemoryExtractorAdapter(
        base_url="http://ollama.test",
        retry_count=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(
        DiscordMemoryExtractorOutputError,
        match="subject/scope",
    ):
        adapter.extract(envelope)
    with pytest.raises(
        DiscordMemoryExtractorOutputError,
        match="target",
    ):
        adapter.extract(envelope)


def test_exact_source_ids_are_required():
    envelope = _envelope()
    payload = _proposal(
        source_turn_id="wrong-turn",
        subject_id=envelope.current_author_id,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(payload)}},
        )

    adapter = DiscordMemoryExtractorAdapter(
        base_url="http://ollama.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(
        DiscordMemoryExtractorOutputError,
        match="source IDs",
    ):
        adapter.extract(envelope)


def test_prompt_contains_fail_closed_semantic_rules():
    prompt = DISCORD_MEMORY_EXTRACTOR_SYSTEM_PROMPT
    assert "exactly one JSON object" in prompt
    assert "display names" in prompt
    assert "Never invent IDs" in prompt
    assert "Possession/current state is not preference" in prompt
    assert "no_op" in prompt
    assert "filter_reason_code into reason_code exactly" in prompt


def test_real_model_benchmark_fixture_is_versioned_and_covers_hard_cases():
    fixture = json.loads(
        (
            FIXTURES / "discord_memory_extractor_benchmark_v1.json"
        ).read_text(encoding="utf-8")
    )
    cases = fixture["cases"]
    assert fixture["dataset_version"] == (
        "discord_memory_extractor_benchmark_v1"
    )
    assert fixture["case_count"] == len(cases) == 150
    assert len({case["id"] for case in cases}) == len(cases)
    assert sum(case["adversarial"] for case in cases) >= 20
    assert sum(case["critical"] for case in cases) >= 50
    assert {case["expected_operation"] for case in cases} == {
        "create",
        "update",
        "delete",
        "no_op",
    }
    assert any(len(case["source_text"]) > 4_096 for case in cases)
    assert any(case["allowed_targets"] for case in cases)
    assert any(
        "display name" in case["source_text"].casefold() for case in cases
    )
