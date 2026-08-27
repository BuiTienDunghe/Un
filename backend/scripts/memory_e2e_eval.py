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
import json
import os
import subprocess
import sys
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
    DiscordConversationSession,
    DiscordMemory,
    DiscordMemoryCandidate,
    DiscordMemorySource,
    DiscordSessionTurn,
)
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
        """The exact read 0c wired into Discord answers, including its filters."""
        problems: list[str] = []
        with self.factory() as database:
            rows = DiscordMemoryRepository(database).list_active_context_memories(
                guild_id=self.guild(expected["guild"]),
                subject_id=self.author(expected["as_subject"]),
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
    known_fail = False
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
            known_fail = bool(check.get("known_fail_today"))
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=str(FIXTURE))
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--case", default=None, help="chỉ chạy một ca theo id")
    parser.add_argument("--keep", action="store_true", help="giữ lại dữ liệu để soi")
    parser.add_argument("--with-extractor", action="store_true")
    arguments = parser.parse_args()

    if arguments.with_extractor:
        print("--with-extractor là pha của việc 4 (verifier); chưa nối extractor vào runner này.")
        return 2

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
