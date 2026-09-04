"""End-to-end memory eval — the measuring stick for jobs 0c and 4.

memory_design.md §13.4. Runs the fixture at
tests/fixtures/discord_memory_e2e_v1.jsonl against a REAL database through the
REAL write machinery (candidate → update_candidate_result → review approve
with supersession, DB constraints live) and the REAL read path
(``list_active_context_memories`` — the filtered ledger SELECT that 0c wired
into Discord answers). Zero generation calls; the Qdrant mirror is stubbed to
a no-op so nothing embeds.

Case statuses:
  PASS        expectation met
  FIXED       row was written as the acceptance test of a shipped fix
              (known_fail flag set, but it now passes)
  KNOWN-FAIL  fails exactly as documented (e.g. the §9.1 guard rows — they
              are the acceptance tests for job 4 and MUST keep failing until
              the 3-state verifier lands)
  PENDING     needs machinery that is deliberately not built yet (job 2 BM25)
  FAIL        unexpected — the run exits non-zero

Extraction expectations (``expected_extraction``) are carried in the fixture
for job 4's ``--with-extractor`` phase; this runner does not call the model.

Never points at production: the default database is the test database, every
row is namespaced by a per-run prefix, and cleanup removes exactly that
prefix (--keep to inspect).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import delete, select

BACKEND = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.postgres.database import create_postgres_engine, create_session_factory  # noqa: E402
from app.postgres.discord_memory_repositories import DiscordMemoryRepository  # noqa: E402
from app.postgres.models import (  # noqa: E402
    Conversation,
    DiscordChannelMessage,
    DiscordChannelPolicy,
    DiscordConversationSession,
    DiscordMemory,
    DiscordMemoryCandidate,
    DiscordMemorySource,
    DiscordSessionTurn,
)
from app.services.discord_history_service import DiscordHistoryService  # noqa: E402
from app.services.discord_memory_guard import auto_apply_allowed  # noqa: E402
from app.services.discord_memory_review_service import DiscordMemoryReviewService  # noqa: E402
from app.services.discord_session_service import DiscordSessionService  # noqa: E402
from app.services.discord_turn_service import DiscordTurnService  # noqa: E402

FIXTURE = BACKEND / "tests" / "fixtures" / "discord_memory_e2e_v1.jsonl"

REASON_BY_KEY = {
    "user.preferred_language": "durable_preference",
    "user.response_style": "durable_preference",
    "user.display_name_preference": "identity_preference",
    "hardware.gpu": "hardware_configuration",
    "hardware.ram": "hardware_configuration",
    "hardware.cpu": "hardware_configuration",
    "software.python_version": "software_configuration",
    "project.database": "project_decision",
    "project.architecture": "project_decision",
    "workflow.codex_prompt_after_update": "workflow_rule",
}


class _NoMirror:
    """Stands in for MemoryService: the mirror is job-irrelevant here and
    embedding would violate the zero-model-call contract of this runner."""

    def upsert_with_id(self, *args, **kwargs):
        return {}

    def remove_with_id(self, *args, **kwargs):
        return True


def default_database_url() -> str:
    from app.config.settings import get_settings

    url = str(get_settings().database_url)
    base, _, _ = url.rpartition("/")
    return f"{base}/local_ai_core_test"


def migrate(database_url: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONUTF8": "1"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(PROJECT_ROOT), env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}")


class CaseWorld:
    """Per-case namespace: fixture placeholders (G1, UA) become prefixed ids."""

    def __init__(self, factory, prefix: str, case_id: str):
        self.factory = factory
        self.prefix = f"{prefix}-{case_id}"
        self.resolver = DiscordSessionService(factory)
        self.turns = DiscordTurnService(factory, self.resolver, None)
        self.history = DiscordHistoryService(factory)
        # Snowflakes carry per-world entropy in the low bits: the column is
        # globally unique, so day+index alone would collide across cases and
        # across --keep runs (review finding 28/08). Timestamp bits (>>22)
        # stay purely day-derived, keeping sent_at ordering deterministic.
        self._snowflake_salt = (
            int.from_bytes(
                hashlib.sha256(self.prefix.encode()).digest()[:3], "big"
            )
            % (1 << 22)
        )
        self.sessions: dict[tuple[str, str], object] = {}
        self.turn_ids: list[UUID] = []
        self.turn_meta: list[dict] = []

    def guild(self, placeholder: str) -> str:
        return f"{self.prefix}-{placeholder.lower()}"

    def author(self, placeholder: str) -> str:
        return f"{self.prefix}-{placeholder.lower()}"

    def ingest(self, setup: list[dict]) -> None:
        for index, message in enumerate(setup):
            key = (message["guild"], message["channel"])
            if key not in self.sessions:
                self.sessions[key] = self.resolver.resolve(
                    self.guild(message["guild"]), f"{self.prefix}-{message['channel']}"
                )
            session = self.sessions[key]
            enqueued = self.turns.enqueue(
                session.session_id,
                f"{self.prefix}-m{index}",
                message["content"],
                None,
                author_id=self.author(message["author"]),
                author_display_name=message["author"],
            )
            self.turn_ids.append(enqueued.turn_id)
            self.turn_meta.append(message)
            # Job 1: the same message also lands in the raw ledger, with a
            # synthetic snowflake carrying the fixture day so sent_at ordering
            # (the search tie-breaker) is deterministic.
            sent_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC) + timedelta(
                days=int(message.get("day", 1)), seconds=index
            )
            snowflake = str(
                ((int(sent_at.timestamp() * 1000) - 1_420_070_400_000) << 22)
                | ((self._snowflake_salt + index) & 0x3FFFFF)
            )
            recorded = self.history.record_message(
                guild_id=self.guild(message["guild"]),
                channel_id=f"{self.prefix}-{message['channel']}",
                thread_id=None,
                discord_message_id=snowflake,
                author_id=self.author(message["author"]),
                author_display_name=message["author"],
                is_bot=False,
                content=message["content"],
            )
            if not recorded:
                raise RuntimeError(
                    f"eval ledger write refused (snowflake {snowflake}) — "
                    "leftover rows from --keep? dọn bằng cleanup rồi chạy lại"
                )

    def apply(self, op: dict) -> None:
        """The real write path minus the model: candidate → result → approve."""
        message = self.turn_meta[op["setup_index"]]
        turn_id = self.turn_ids[op["setup_index"]]
        guild_id = self.guild(message["guild"])
        with self.factory.begin() as database:
            turn = database.get(DiscordSessionTurn, turn_id)
            repository = DiscordMemoryRepository(database)
            candidate, _ = repository.create_or_get_candidate(
                source_turn_id=turn_id,
                session_id=turn.session_id,
                source_discord_message_id=turn.discord_message_id,
                source_author_id=turn.author_id,
                source_author_display_name=turn.author_display_name,
                guild_id=guild_id,
                channel_id=f"{self.prefix}-{message['channel']}",
                thread_id=None,
                extractor_schema_version="e2e-eval-v1",
                filter_decision="candidate",
                filter_reason_code=REASON_BY_KEY[op["fact_key"]],
            )
            repository.update_candidate_result(
                candidate.id,
                guild_id=guild_id,
                expected_validation_status="pending",
                extractor_model="e2e-fixture",
                operation=op["operation"],
                memory_type=op["memory_type"],
                subject_type="discord_member",
                subject_id=self.author(op["subject"]),
                scope=op["scope"],
                fact_key=op["fact_key"],
                canonical_fact=op["canonical_fact"],
                evidence_text=op["evidence"],
                confidence=None,
                decision="deferred",
            )
            candidate_id = candidate.id
        review = DiscordMemoryReviewService(self.factory, _NoMirror())
        review.approve(candidate_id, reviewed_by="e2e-eval")

    def check_state(self, expected: dict) -> list[str]:
        problems: list[str] = []
        with self.factory() as database:
            query = select(DiscordMemory).where(
                DiscordMemory.guild_id == self.guild(expected["guild"]),
                DiscordMemory.subject_id == self.author(expected["subject"]),
            )
            if "fact_key" in expected:
                query = query.where(DiscordMemory.fact_key == expected["fact_key"])
            elif expected.get("fact_key_prefix"):
                query = query.where(DiscordMemory.fact_key.like(expected["fact_key_prefix"] + "%"))
            rows = list(database.scalars(query))
        active = [row for row in rows if row.status == "active"]
        superseded = [row for row in rows if row.status == "superseded"]
        if len(active) != expected.get("active_count", len(active)):
            problems.append(f"active_count={len(active)} muốn {expected['active_count']}")
        text = " | ".join(row.canonical_fact for row in active)
        for needle in expected.get("active_contains", []):
            if needle not in text:
                problems.append(f"active thiếu {needle!r}")
        for needle in expected.get("active_not_contains", []):
            if needle in text:
                problems.append(f"active chứa nhầm {needle!r}")
        if "superseded_count" in expected and len(superseded) != expected["superseded_count"]:
            problems.append(f"superseded={len(superseded)} muốn {expected['superseded_count']}")
        if "max_version" in expected:
            top = max((row.version for row in rows), default=0)
            if top != expected["max_version"]:
                problems.append(f"max_version={top} muốn {expected['max_version']}")
        return problems

    def check_retrieval(self, expected: dict) -> list[str]:
        """The exact read the Discord answer path uses, including its filters.

        Step 4 (28/08): the answer path reads guild-wide member facts
        (all_members=True) — the asker no longer narrows the member scope, so
        as_subject documents who asks but only the guild filters. attrib-04's
        cross-guild isolation is the boundary this must keep pinning.
        """
        if expected.get("source") == "bm25":
            # Job 2 landed as Postgres FTS over the raw ledger (§13.5 option
            # c); "bm25" stays as the fixture's historical name for "lexical
            # search over sổ gốc".
            hits = self.history.search(
                guild_id=self.guild(expected["guild"]),
                query=expected["query"],
                limit=5,
            )
            text = " | ".join(hit.content for hit in hits)
            problems = []
            for needle in expected.get("must_contain", []):
                if needle not in text:
                    problems.append(f"lịch sử thiếu {needle!r} trong top-5")
            for needle in expected.get("must_not_contain", []):
                if needle in text:
                    problems.append(f"lịch sử rò {needle!r}")
            return problems
        problems: list[str] = []
        with self.factory() as database:
            rows = DiscordMemoryRepository(database).list_active_context_memories(
                guild_id=self.guild(expected["guild"]),
                subject_id=None,
                all_members=True,
                limit=10,
            )
            text = " | ".join(row.canonical_fact for row in rows)
            # stale_leak by ROW STATUS, not by text: identical content may
            # legitimately exist as both v1 (superseded) and v2 (active), so a
            # substring scan false-positives. What must never happen is a
            # returned row whose status is not 'active'.
            stale_rows = [row for row in rows if row.status != "active"]
        for needle in expected.get("must_contain", []):
            if needle not in text:
                problems.append(f"truy xuất thiếu {needle!r}")
        for needle in expected.get("must_not_contain", []):
            if needle in text:
                problems.append(f"truy xuất rò {needle!r}")
        for row in stale_rows:
            problems.append(f"stale_leak: dòng {row.status} lọt vào truy xuất")
        return problems

    def cleanup(self) -> None:
        with self.factory.begin() as database:
            like = f"{self.prefix}-%"
            database.execute(
                delete(DiscordChannelMessage).where(
                    DiscordChannelMessage.guild_id.like(like)
                )
            )
            database.execute(
                delete(DiscordChannelPolicy).where(
                    DiscordChannelPolicy.guild_id.like(like)
                )
            )
            memory_ids = list(
                database.scalars(select(DiscordMemory.id).where(DiscordMemory.guild_id.like(like)))
            )
            # memories ↔ candidates reference each other (origin_candidate_id
            # one way, target_memory_id the other), so break the cycle first.
            from sqlalchemy import update as sql_update

            database.execute(
                sql_update(DiscordMemoryCandidate)
                .where(DiscordMemoryCandidate.guild_id.like(like))
                .values(target_memory_id=None)
            )
            if memory_ids:
                database.execute(
                    delete(DiscordMemorySource).where(DiscordMemorySource.memory_id.in_(memory_ids))
                )
                database.execute(delete(DiscordMemory).where(DiscordMemory.id.in_(memory_ids)))
            database.execute(
                delete(DiscordMemoryCandidate).where(DiscordMemoryCandidate.guild_id.like(like))
            )
            session_ids = list(
                database.scalars(
                    select(DiscordConversationSession.id).where(
                        DiscordConversationSession.guild_id.like(like)
                    )
                )
            )
            conversation_ids = [
                str(value)
                for value in database.scalars(
                    select(DiscordConversationSession.backend_conversation_id).where(
                        DiscordConversationSession.guild_id.like(like)
                    )
                )
            ]
            if session_ids:
                database.execute(
                    delete(DiscordSessionTurn).where(DiscordSessionTurn.session_id.in_(session_ids))
                )
                database.execute(
                    delete(DiscordConversationSession).where(
                        DiscordConversationSession.id.in_(session_ids)
                    )
                )
            if conversation_ids:
                database.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))


def run_case(factory, prefix: str, case: dict, keep: bool) -> tuple[str, list[str]]:
    if case.get("pending"):
        return "PENDING", [f"chờ {case['pending']}"]
    problems: list[str] = []
    # Top-level known_fail_today: a case whose measured failure IS the point
    # (the dense-retrieval tripwire) — same contract as the guard flag.
    known_fail = bool(case.get("known_fail_today"))
    world = CaseWorld(factory, prefix, case["id"])
    try:
        world.ingest(case.get("setup", []))
        for op in case.get("apply_ops", []):
            world.apply(op)
        for expected in case.get("expected_state", []) or []:
            problems += world.check_state(expected)
        if case.get("expected_retrieval"):
            problems += world.check_retrieval(case["expected_retrieval"])
        if case.get("guard_check"):
            check = case["guard_check"]
            known_fail = known_fail or bool(check.get("known_fail_today"))
            allowed = auto_apply_allowed(
                canonical_fact=check["canonical_fact"],
                evidence_text=check["evidence_text"],
                source_text=check["source_text"],
            )
            if allowed != check["expected_allowed"]:
                problems.append(
                    f"guard trả {allowed}, muốn {check['expected_allowed']}"
                )
    finally:
        if not keep:
            world.cleanup()
    if problems:
        return ("KNOWN-FAIL" if known_fail else "FAIL"), problems
    return ("FIXED" if known_fail else "PASS"), []


def run_extraction_phase(cases: list[dict]) -> tuple[bool, dict]:
    """The §13.4 night benchmark: REAL filter + REAL extractor (+ verifier)
    over every setup message, scored against expected_extraction.

    This is the only model-ful phase of this runner (the base phase stays
    zero-model by contract). Gates measured here:
      - extraction P >= 0.80 / R >= 0.70  (chặn đổi prompt)
      - forged_subject == 0               (điều kiện tự-áp-dụng)
    plus the verifier's entailment rate on correct extractions (E1).
    """
    from app.config.settings import get_settings
    from app.services.discord_memory_extractor import (
        DISCORD_MEMORY_EXTRACTOR_PROMPT_VERSION,
        DiscordMemoryExtractorAdapter,
        DiscordMemoryExtractorEnvelopeBuilder,
        DiscordMemoryExtractorError,
        ExtractorSource,
        ExtractorTarget,
    )
    from app.services.discord_memory_rule_filter import (
        DiscordMemoryFilterInput,
        DiscordMemoryRuleFilter,
    )
    from app.services.discord_memory_verifier import DiscordMemoryVerifierAdapter

    settings = get_settings()
    rule_filter = DiscordMemoryRuleFilter()
    builder = DiscordMemoryExtractorEnvelopeBuilder()
    extractor = DiscordMemoryExtractorAdapter(
        base_url=settings.ollama_base_url,
        model=settings.discord_memory_extractor_model,
        schema_version=settings.discord_memory_extractor_schema_version,
        num_ctx=settings.discord_memory_extractor_num_ctx,
        temperature=settings.discord_memory_extractor_temperature,
        seed=settings.discord_memory_extractor_seed,
        timeout_seconds=settings.discord_memory_extractor_timeout_seconds,
        retry_count=settings.discord_memory_extractor_retry_count,
    )
    verifier = DiscordMemoryVerifierAdapter(
        base_url=settings.ollama_base_url,
        model=settings.discord_memory_verifier_model,
        timeout_seconds=settings.discord_memory_verifier_timeout_seconds,
    )
    print(
        f"\n─── pha trích xuất: model={extractor.model} "
        f"schema={extractor.schema_version} verifier={verifier.model} ───",
        flush=True,
    )

    predicted = 0
    correct = 0
    expected_total = 0
    forged = 0
    errors = 0
    verifier_correct_entailment = 0
    verifier_correct_total = 0
    verifier_wrong_verdicts: list[str] = []

    for case in cases:
        setup = case.get("setup") or []
        expected_by_index = {
            entry["setup_index"]: entry
            for entry in (case.get("expected_extraction") or [])
        }
        expected_total += sum(
            1
            for entry in expected_by_index.values()
            if entry.get("operation") != "no_op"
        )
        # Per-guild target chains so update-vs-create scores like production:
        # earlier accepted proposals become allowed targets for later ones.
        targets_by_guild: dict[str, dict[str, ExtractorTarget]] = {}
        for index, message in enumerate(setup):
            author_id = f"{case['id']}-{message['author'].lower()}"
            filter_result = rule_filter.evaluate(
                DiscordMemoryFilterInput(
                    turn_id=uuid4(),
                    source_discord_message_id=f"{case['id']}-m{index}",
                    author_id=author_id,
                    guild_id=message["guild"],
                    channel_id=message["channel"],
                    thread_id=None,
                    request_text=message["content"],
                    turn_status="completed",
                    delivery_exists=True,
                    session_state="active",
                )
            )
            expected_entry = expected_by_index.get(index)
            wants_fact = bool(
                expected_entry and expected_entry.get("operation") != "no_op"
            )
            if filter_result.decision != "candidate":
                if wants_fact:
                    print(
                        f"  MISS   {case['id']}[{index}] filter="
                        f"{filter_result.reason_code} — kỳ vọng "
                        f"{expected_entry['fact_key']}",
                        flush=True,
                    )
                continue
            guild_targets = targets_by_guild.setdefault(message["guild"], {})
            try:
                result = extractor.extract(
                    builder.build(
                        source=ExtractorSource(
                            turn_id=uuid4(),
                            discord_message_id=f"{case['id']}-m{index}",
                            author_id=author_id,
                            guild_id=message["guild"],
                            channel_id=message["channel"],
                            thread_id=None,
                            request_text=message["content"],
                        ),
                        filter_metadata={
                            "stage": "rule_filter",
                            "policy_version": filter_result.policy_version,
                            "decision": filter_result.decision,
                            "reason_code": filter_result.reason_code,
                            "candidate_strength": filter_result.candidate_strength,
                            "detected_intent": filter_result.detected_intent,
                            "matched_rules": list(filter_result.matched_rules),
                        },
                        targets=list(guild_targets.values()),
                    )
                )
            except DiscordMemoryExtractorError as error:
                errors += 1
                print(
                    f"  ERROR  {case['id']}[{index}] {error.error_code}: "
                    f"{str(error)[:90]}",
                    flush=True,
                )
                continue
            proposal = result.proposal
            if proposal.operation == "no_op":
                if wants_fact:
                    print(
                        f"  MISS   {case['id']}[{index}] extractor no_op "
                        f"({proposal.reason_code}) — kỳ vọng "
                        f"{expected_entry['fact_key']}",
                        flush=True,
                    )
                continue
            predicted += 1
            if proposal.subject_id != author_id:
                forged += 1
                print(
                    f"  FORGED {case['id']}[{index}] subject="
                    f"{proposal.subject_id!r} ≠ author {author_id!r}",
                    flush=True,
                )
            is_correct = bool(
                wants_fact
                and proposal.operation == expected_entry["operation"]
                and proposal.fact_key in expected_entry["fact_key"]
                and proposal.subject_id == author_id
            )
            if is_correct:
                correct += 1
            else:
                print(
                    f"  WRONG  {case['id']}[{index}] "
                    f"{proposal.operation}/{proposal.fact_key} — kỳ vọng "
                    f"{expected_entry and expected_entry.get('operation')}/"
                    f"{expected_entry and expected_entry.get('fact_key')}",
                    flush=True,
                )
            # Maintain the target chain for later messages in this guild.
            if proposal.operation in {"create", "update"} and proposal.fact_key:
                guild_targets[proposal.fact_key] = ExtractorTarget(
                    memory_id=(
                        proposal.target_memory_id
                        if proposal.operation == "update"
                        and proposal.target_memory_id is not None
                        else uuid4()
                    ),
                    fact_key=proposal.fact_key,
                    canonical_fact=proposal.canonical_fact or "",
                    memory_type=proposal.memory_type or "fact",
                    scope=proposal.scope or "member_in_guild",
                    version=1,
                )
            verdict = verifier.verify(
                canonical_fact=proposal.canonical_fact or "",
                source_text=message["content"],
            )
            if is_correct:
                verifier_correct_total += 1
                if verdict.result == "entailment":
                    verifier_correct_entailment += 1
            else:
                verifier_wrong_verdicts.append(verdict.result)
            print(
                f"  OK={'y' if is_correct else 'n'} {case['id']}[{index}] "
                f"{proposal.operation}/{proposal.fact_key} "
                f"conf={proposal.confidence:.2f} verifier={verdict.result} "
                f"({result.latency_ms}ms)",
                flush=True,
            )

    precision = correct / predicted if predicted else 0.0
    recall = correct / expected_total if expected_total else 0.0
    entail_rate = (
        verifier_correct_entailment / verifier_correct_total
        if verifier_correct_total
        else 0.0
    )
    print(
        f"\ntrích xuất: P={precision:.2f} ({correct}/{predicted}) · "
        f"R={recall:.2f} ({correct}/{expected_total}) · forged={forged} · "
        f"lỗi transport/output={errors}",
        flush=True,
    )
    print(
        f"verifier: entailment trên ca ĐÚNG = {entail_rate:.2f} "
        f"({verifier_correct_entailment}/{verifier_correct_total}) · "
        f"verdict trên ca SAI: {verifier_wrong_verdicts or '—'}",
        flush=True,
    )
    passed = precision >= 0.80 and recall >= 0.70 and forged == 0
    print(
        "GATE §13.4: "
        + (
            "ĐẠT — P≥0.80, R≥0.70, forged=0. Đủ điều kiện bật verifier + "
            "mở tự-áp-dụng (kèm entailment gate trong worker)."
            if passed
            else "CHƯA ĐẠT — giữ verifier tối và tự-áp-dụng tắt."
        ),
        flush=True,
    )
    return passed, {
        "precision": precision,
        "recall": recall,
        "forged": forged,
        "errors": errors,
        "entailment_on_correct": entail_rate,
        # Which run produced these numbers. Without them the metrics are not
        # comparable across days: P=0.94 under one extractor model and prompt
        # version says nothing about P=0.94 under another.
        "extractor_model": extractor.model,
        "extractor_schema_version": extractor.schema_version,
        "verifier_model": verifier.model,
        "prompt_version": DISCORD_MEMORY_EXTRACTOR_PROMPT_VERSION,
        "cases": len(cases),
        "predicted": predicted,
        "correct": correct,
        "expected_total": expected_total,
        "gate_passed": passed,
    }


EXTRACTION_REPORT_DIR = PROJECT_ROOT / "data" / "benchmarks" / "memory_e2e"


def write_extraction_report(metrics: dict, output: str | None) -> Path:
    """Persist the extraction-phase metrics next to the extractor benchmarks.

    The gate used to print P/R/forged and drop the dict on the floor, so the
    only record of "P=0.94 · R=0.80 · forged=0" was a sentence in
    docs/memory_design.md — a number nobody could re-open, diff or plot. It is
    also the number a distilled student has to match, which makes an
    un-inspectable version of it useless as a baseline.
    """
    path = Path(output) if output else EXTRACTION_REPORT_DIR / f"memory-e2e-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"created_at": datetime.now(UTC).isoformat(), **metrics}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã ghi báo cáo pha trích xuất: {path}", flush=True)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=str(FIXTURE))
    parser.add_argument(
        "--output",
        default=None,
        help="Nơi ghi metrics pha trích xuất (mặc định data/benchmarks/memory_e2e/memory-e2e-<timestamp>.json)",
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--case", default=None, help="chỉ chạy một ca theo id")
    parser.add_argument("--keep", action="store_true", help="giữ lại dữ liệu để soi")
    parser.add_argument(
        "--with-extractor",
        action="store_true",
        help="chạy thêm pha model thật (filter + extractor + verifier) — §13.4",
    )
    arguments = parser.parse_args()

    database_url = arguments.database_url or default_database_url()
    migrate(database_url)
    factory = create_session_factory(create_postgres_engine(database_url))
    prefix = f"e2e-{uuid4().hex[:8]}"

    cases = [
        json.loads(line)
        for line in Path(arguments.fixture).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if arguments.case:
        cases = [case for case in cases if case["id"] == arguments.case]

    counts: dict[str, int] = {}
    unexpected: list[str] = []
    print(f"database: {database_url.rsplit('@', 1)[-1]}   prefix: {prefix}\n")
    for case in cases:
        status, problems = run_case(factory, prefix, case, arguments.keep)
        counts[status] = counts.get(status, 0) + 1
        detail = ("  ← " + "; ".join(problems)) if problems else ""
        print(f"{status:<11} {case['id']:<20} {case['category']}{detail}")
        if status == "FAIL":
            unexpected.append(case["id"])

    print()
    print("tổng:", " · ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if unexpected:
        print(f"FAIL ngoài dự kiến: {', '.join(unexpected)}")
        return 1
    notes = ["Không có FAIL ngoài dự kiến."]
    if counts.get("KNOWN-FAIL"):
        notes.append("KNOWN-FAIL là bài nghiệm thu đang chờ việc tương ứng.")
    if counts.get("PENDING"):
        notes.append("PENDING chờ việc 2 (BM25 sổ gốc).")
    if counts.get("FIXED"):
        notes.append("FIXED = bài nghiệm thu đã hạ cánh — hợp đồng trong test giữ nó không thoái lui.")
    print(" ".join(notes))

    if arguments.with_extractor:
        gate_passed, metrics = run_extraction_phase(cases)
        write_extraction_report(metrics, arguments.output)
        if not gate_passed:
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
