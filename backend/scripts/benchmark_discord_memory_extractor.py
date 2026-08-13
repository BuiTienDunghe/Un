"""Real-model benchmark for the Discord memory extractor.

This harness calls the dedicated adapter directly. It never creates jobs,
candidates, canonical memories, source links, or Qdrant points.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from app.services.discord_memory_extractor import (
    DISCORD_MEMORY_EXTRACTOR_PROMPT_VERSION,
    AllowedTargetMemory,
    DiscordMemoryExtractorAdapter,
    DiscordMemoryExtractorEnvelopeBuilder,
    DiscordMemoryExtractorOutputError,
    DiscordMemoryProposalV1,
    ExtractorSource,
    ExtractorTarget,
)


FIXTURE_NAMESPACE = UUID("d4457e31-4f58-4f2f-9045-cd27bb08c934")
MODEL_FIELDS = set(DiscordMemoryProposalV1.model_fields)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)
    return float(ordered[max(0, index)])


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def build_envelope(case: dict[str, Any]):
    trusted = case["trusted_subjects"][0]
    turn_id = uuid5(FIXTURE_NAMESPACE, f"turn:{case['id']}")
    message_number = int.from_bytes(
        uuid5(FIXTURE_NAMESPACE, f"message:{case['id']}").bytes[:8],
        "big",
    )
    source = ExtractorSource(
        turn_id=turn_id,
        discord_message_id=str(message_number),
        author_id=trusted["subject_id"],
        guild_id="benchmark-guild-001",
        channel_id="benchmark-channel-001",
        thread_id=None,
        request_text=case["source_text"],
    )
    targets = tuple(
        ExtractorTarget(
            memory_id=UUID(item["memory_id"]),
            fact_key=item["fact_key"],
            canonical_fact=item["canonical_fact"],
            memory_type=item["memory_type"],
            scope=item["scope"],
            version=item["version"],
        )
        for item in case["allowed_targets"]
    )
    envelope = DiscordMemoryExtractorEnvelopeBuilder().build(
        source=source,
        filter_metadata={
            "decision": "candidate",
            "reason_code": case["filter_reason"],
            "candidate_strength": "strong",
        },
        targets=targets,
        allowed_fact_keys=case["allowed_fact_keys"],
    )
    return envelope


def proposal_from_raw(raw: dict[str, Any] | None):
    if raw is None:
        return None
    try:
        return DiscordMemoryProposalV1.model_validate(raw, strict=True)
    except Exception:
        return None


def run_case(
    adapter: DiscordMemoryExtractorAdapter,
    case: dict[str, Any],
) -> dict[str, Any]:
    envelope = build_envelope(case)
    started = time.perf_counter()
    proposal = None
    raw: dict[str, Any] | None = None
    performance: dict[str, int] = {}
    error_code = None
    accepted = False
    try:
        result = adapter.extract(envelope)
        proposal = result.proposal
        raw = result.raw_output
        performance = result.performance
        accepted = True
    except DiscordMemoryExtractorOutputError as error:
        raw = error.raw_output
        performance = error.performance
        proposal = proposal_from_raw(raw)
        error_code = error.error_code
    except Exception as error:
        error_code = getattr(error, "error_code", type(error).__name__)
    latency_ms = int((time.perf_counter() - started) * 1000)

    valid_json = isinstance(raw, dict)
    schema_valid = proposal is not None
    operation = proposal.operation if proposal else None
    target_id = (
        str(proposal.target_memory_id)
        if proposal and proposal.target_memory_id is not None
        else None
    )
    trusted_ids = {
        item["subject_id"] for item in case["trusted_subjects"]
    }
    allowed_target_ids = {
        item["memory_id"] for item in case["allowed_targets"]
    }
    expected_operations = case.get(
        "allowed_operations",
        [case["expected_operation"]],
    )
    evidence_grounded = bool(
        proposal
        and (
            proposal.operation == "no_op"
            or (
                proposal.evidence_text
                and proposal.evidence_text in case["source_text"]
            )
        )
    )
    fact_contains_ok = bool(
        proposal
        and (
            proposal.operation == "no_op"
            or all(
                token.casefold() in (proposal.canonical_fact or "").casefold()
                for token in case["expected_fact_contains"]
            )
        )
    )
    subject_allowed = bool(
        proposal
        and (
            proposal.operation == "no_op"
            or proposal.subject_id in trusted_ids
        )
    )
    target_allowed = bool(
        proposal
        and (
            proposal.target_memory_id is None
            or target_id in allowed_target_ids
        )
    )
    source_turn_ok = bool(
        proposal and proposal.source_turn_id == envelope.source_turn_id
    )
    source_message_ok = bool(
        proposal
        and proposal.source_discord_message_id
        == envelope.source_discord_message_id
    )
    unsupported_inference = bool(
        case["critical"]
        and (
            (case["expected_operation"] == "no_op" and operation != "no_op")
            or (operation != "no_op" and not evidence_grounded)
        )
    )
    normalized = (
        proposal.model_dump(mode="json") if proposal is not None else None
    )
    return {
        "id": case["id"],
        "accepted": accepted,
        "valid_json": valid_json,
        "schema_valid": schema_valid,
        "error_code": error_code,
        "raw_output": raw,
        "normalized_output": normalized,
        "operation": operation,
        "operation_ok": operation in expected_operations,
        "memory_type_ok": bool(
            proposal
            and proposal.memory_type == case["expected_memory_type"]
        ),
        "subject_type_ok": bool(
            proposal
            and proposal.subject_type == case["expected_subject_type"]
        ),
        "subject_id_ok": bool(
            proposal
            and proposal.subject_id == case["expected_subject_id"]
        ),
        "scope_ok": bool(
            proposal and proposal.scope == case["expected_scope"]
        ),
        "fact_key_ok": bool(
            proposal
            and proposal.fact_key == case["expected_fact_key"]
        ),
        "fact_contains_ok": fact_contains_ok,
        "evidence_grounded": evidence_grounded,
        "source_turn_ok": source_turn_ok,
        "source_message_ok": source_message_ok,
        "subject_allowed": subject_allowed,
        "target_allowed": target_allowed,
        "target_ok": bool(
            proposal and target_id == case["expected_target_memory_id"]
        ),
        "additional_properties": (
            sorted(set(raw) - MODEL_FIELDS) if raw else []
        ),
        "forged_subject_attempt": bool(
            proposal
            and proposal.operation != "no_op"
            and proposal.subject_id not in trusted_ids
        ),
        "out_of_allowlist_target_attempt": bool(
            target_id is not None and target_id not in allowed_target_ids
        ),
        "unsupported_inference": unsupported_inference,
        "critical": case["critical"],
        "adversarial": case["adversarial"],
        "latency_ms": latency_ms,
        "performance": performance,
    }


def summarize(
    cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    total = len(results)
    applicable = [
        (case, result)
        for case, result in zip(cases, results, strict=True)
        if case["expected_operation"] != "no_op"
    ]
    no_ops = [
        result
        for case, result in zip(cases, results, strict=True)
        if case["expected_operation"] == "no_op"
    ]
    latencies = [float(item["latency_ms"]) for item in results]
    prompt_tokens = [
        item["performance"].get("prompt_eval_count", 0) for item in results
    ]
    output_tokens = [
        item["performance"].get("eval_count", 0) for item in results
    ]
    token_rates = [
        item["performance"]["eval_count"]
        / (item["performance"]["eval_duration"] / 1_000_000_000)
        for item in results
        if item["performance"].get("eval_count")
        and item["performance"].get("eval_duration")
    ]
    return {
        "total_cases": total,
        "valid_json_rate": ratio(
            sum(item["valid_json"] for item in results), total
        ),
        "schema_compliance_rate": ratio(
            sum(item["schema_valid"] for item in results), total
        ),
        "adapter_acceptance_rate": ratio(
            sum(item["accepted"] for item in results), total
        ),
        "additional_properties_violation_count": sum(
            bool(item["additional_properties"]) for item in results
        ),
        "source_turn_echo_accuracy": ratio(
            sum(item["source_turn_ok"] for item in results), total
        ),
        "source_message_echo_accuracy": ratio(
            sum(item["source_message_ok"] for item in results), total
        ),
        "trusted_subject_accuracy": ratio(
            sum(item["subject_id_ok"] for item in results), total
        ),
        "forged_subject_attempt_count": sum(
            item["forged_subject_attempt"] for item in results
        ),
        "forged_subject_accepted_count": sum(
            item["forged_subject_attempt"] and item["accepted"]
            for item in results
        ),
        "target_allowlist_accuracy": ratio(
            sum(item["target_allowed"] for item in results), total
        ),
        "out_of_allowlist_target_count": sum(
            item["out_of_allowlist_target_attempt"] for item in results
        ),
        "operation_accuracy": ratio(
            sum(item["operation_ok"] for item in results), total
        ),
        "memory_type_accuracy": ratio(
            sum(result["memory_type_ok"] for _, result in applicable),
            len(applicable),
        ),
        "scope_accuracy": ratio(
            sum(result["scope_ok"] for _, result in applicable),
            len(applicable),
        ),
        "fact_key_accuracy": ratio(
            sum(result["fact_key_ok"] for _, result in applicable),
            len(applicable),
        ),
        "evidence_exact_grounding_rate": ratio(
            sum(result["evidence_grounded"] for _, result in applicable),
            len(applicable),
        ),
        "fact_content_accuracy": ratio(
            sum(result["fact_contains_ok"] for _, result in applicable),
            len(applicable),
        ),
        "unsupported_inference_count": sum(
            item["unsupported_inference"] for item in results
        ),
        "no_op_accuracy": ratio(
            sum(item["operation"] == "no_op" for item in no_ops),
            len(no_ops),
        ),
        "mean_latency_ms": round(statistics.mean(latencies), 2),
        "p50_latency_ms": percentile(latencies, 0.50),
        "p95_latency_ms": percentile(latencies, 0.95),
        "max_latency_ms": max(latencies, default=0),
        "timeout_count": sum(
            item["error_code"] == "extractor_transport_error"
            for item in results
        ),
        "transport_error_count": sum(
            str(item["error_code"] or "").startswith("extractor_transport")
            for item in results
        ),
        "mean_input_tokens": round(statistics.mean(prompt_tokens), 2)
        if prompt_tokens
        else 0.0,
        "mean_output_tokens": round(statistics.mean(output_tokens), 2)
        if output_tokens
        else 0.0,
        "mean_eval_tokens_per_second": round(
            statistics.mean(token_rates),
            3,
        )
        if token_rates
        else 0.0,
        "error_codes": dict(
            Counter(
                item["error_code"]
                for item in results
                if item["error_code"]
            )
        ),
    }


def repeatability(
    adapter: DiscordMemoryExtractorAdapter,
    cases: list[dict[str, Any]],
    *,
    count: int,
    runs: int,
) -> dict[str, Any]:
    if count >= len(cases):
        selected = cases
    elif count == 1:
        selected = [cases[0]]
    else:
        indexes = [
            round(index * (len(cases) - 1) / (count - 1))
            for index in range(count)
        ]
        selected = [cases[index] for index in indexes]
    stable = 0
    details = []
    for index, case in enumerate(selected, 1):
        outputs = [run_case(adapter, case) for _ in range(runs)]
        signatures = [
            json.dumps(
                item["normalized_output"]
                if item["normalized_output"] is not None
                else {
                    "error_code": item["error_code"],
                    "raw_output": item["raw_output"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            for item in outputs
        ]
        exact = len(set(signatures)) == 1
        stable += int(exact)
        details.append(
            {
                "id": case["id"],
                "exact_normalized_stable": exact,
                "operations": [item["operation"] for item in outputs],
                "latencies_ms": [item["latency_ms"] for item in outputs],
            }
        )
        print(
            f"repeat {index}/{len(selected)} {case['id']} "
            f"stable={exact}",
            flush=True,
        )
    return {
        "case_count": len(selected),
        "runs_per_case": runs,
        "repeatability_rate": ratio(stable, len(selected)),
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(
            "tests/fixtures/discord_memory_extractor_benchmark_v1.json"
        ),
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3.5:2b")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--repeat-count", type=int, default=30)
    parser.add_argument("--repeat-runs", type=int, default=3)
    parser.add_argument("--skip-repeatability", action="store_true")
    parser.add_argument("--repeat-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    cases = fixture["cases"]
    if args.limit:
        cases = cases[: args.limit]
    adapter = DiscordMemoryExtractorAdapter(
        base_url=args.base_url,
        model=args.model,
        timeout_seconds=args.timeout_seconds,
        retry_count=0,
        json_fallback=False,
    )
    results = []
    if not args.repeat_only:
        for index, case in enumerate(cases, 1):
            result = run_case(adapter, case)
            results.append(result)
            print(
                f"case {index}/{len(cases)} {case['id']} "
                f"op={result['operation']} accepted={result['accepted']} "
                f"error={result['error_code']} "
                f"latency_ms={result['latency_ms']}",
                flush=True,
            )
    summary = summarize(cases, results) if results else {}
    repeat = None
    if not args.skip_repeatability:
        repeat = repeatability(
            adapter,
            cases,
            count=min(args.repeat_count, len(cases)),
            runs=args.repeat_runs,
        )
        summary["repeatability_rate"] = repeat["repeatability_rate"]

    output = {
        "dataset_version": fixture["dataset_version"],
        "model": args.model,
        "prompt_version": DISCORD_MEMORY_EXTRACTOR_PROMPT_VERSION,
        "schema_mode": "ollama_json_schema_object",
        "summary": summary,
        "repeatability": repeat,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
