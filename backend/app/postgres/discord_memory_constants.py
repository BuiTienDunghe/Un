from __future__ import annotations

"""Immutable Sprint 2B Discord-memory domain vocabulary.

Alembic revision ``20260728_16`` imports these V1 tuples when constructing
TEXT-based CHECK constraints.  Treat the tuples as migration history: add a
new version instead of changing their meaning after deployment.
"""

DISCORD_MEMORY_OPERATIONS_V1 = (
    "create",
    "update",
    "delete",
    "no_op",
)

DISCORD_MEMORY_SCOPES_V1 = (
    "member_in_guild",
    "guild",
    "channel",
    "thread",
)

DISCORD_MEMORY_FILTER_DECISIONS_V1 = (
    "candidate",
    "no_op",
)

# Sprint 2B.3 needs an honest durable receipt before any rule filter runs.
# V1 remains immutable because revision 20260728_16 is already complete.
DISCORD_MEMORY_FILTER_DECISIONS_V2 = (
    *DISCORD_MEMORY_FILTER_DECISIONS_V1,
    "not_run",
)

DISCORD_MEMORY_FILTER_DECISIONS_V3 = (
    *DISCORD_MEMORY_FILTER_DECISIONS_V2,
    "rejected_policy",
)

DISCORD_MEMORY_FILTER_REASON_CODES_V1 = (
    "foundation_receipt_only",
    "explicit_remember",
    "explicit_forget",
    "explicit_correction",
    "durable_preference",
    "hardware_configuration",
    "software_configuration",
    "project_decision",
    "identity_preference",
    "workflow_rule",
    "explicit_shared_fact",
    "greeting",
    "thanks",
    "question_only",
    "transient_state",
    "joke_or_smalltalk",
    "no_durable_fact",
    "missing_trusted_author",
    "memory_policy_disabled",
    "duplicate_source",
    "unsupported_scope",
    "bot_or_system_message",
    "empty_content",
)

# Vocabulary v2 (28/08/2026): birthday statements get their own reason so the
# closed fact-key list can carry user.birthday — three production cases died at
# the filter gate as no_durable_fact (memory_design.md §13). V1 stays immutable
# per this file's contract; revision 20260828_29 rebuilds the CHECK from V2.
DISCORD_MEMORY_FILTER_REASON_CODES_V2 = (
    *DISCORD_MEMORY_FILTER_REASON_CODES_V1,
    "personal_fact",
)

DISCORD_MEMORY_FILTER_STRENGTHS_V1 = (
    "strong",
    "normal",
    "none",
)

DISCORD_MEMORY_VALIDATION_STATUSES_V1 = (
    "pending",
    "accepted",
    "rejected",
    "error",
)

DISCORD_MEMORY_CANDIDATE_VALIDATION_STATUSES_V2 = (
    *DISCORD_MEMORY_VALIDATION_STATUSES_V1,
    "not_required",
)

DISCORD_MEMORY_CANDIDATE_DECISIONS_V1 = (
    "pending",
    "deferred",
    "approved",
    "rejected",
    "applied",
    "no_op",
    "expired",
    "failed",
)

# Job 4 (memory_design.md 13.2 E1): 1-vs-1 verifier verdict vocabulary.
# entailment -> eligible for autonomous apply (when the threshold returns);
# contradiction -> review with the supersession pre-filled, NEVER auto;
# unknown -> review. Absence (NULL) means the verifier has not run.
DISCORD_MEMORY_VERIFICATION_RESULTS_V1 = (
    "entailment",
    "contradiction",
    "unknown",
)

DISCORD_MEMORY_STATUSES_V1 = (
    "active",
    "superseded",
    "disputed",
    "expired",
    "deleted",
)

DISCORD_MEMORY_INDEX_STATUSES_V1 = (
    "pending",
    "indexed",
    "pending_reindex",
    "failed",
    "not_required",
)

DISCORD_MEMORY_SOURCE_ROLES_V1 = (
    "primary",
    "supporting",
    "confirmation",
    "contradiction",
    "correction",
    "forget_request",
)
