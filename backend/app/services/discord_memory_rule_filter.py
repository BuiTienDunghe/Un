from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal
from uuid import UUID


DISCORD_MEMORY_RULE_FILTER_POLICY_VERSION = "discord_memory_rule_filter_v1"

FilterDecision = Literal["candidate", "no_op", "rejected_policy"]
CandidateStrength = Literal["strong", "normal", "none"]


@dataclass(frozen=True, slots=True)
class DiscordMemoryFilterInput:
    turn_id: UUID
    source_discord_message_id: str
    author_id: str | None
    guild_id: str | None
    channel_id: str | None
    thread_id: str | None
    request_text: str
    turn_status: str
    delivery_exists: bool
    session_state: str
    memory_policy_enabled: bool = True
    dm_enabled: bool = False
    thread_enabled: bool = False
    source_role: str = "user"
    duplicate_source: bool = False


@dataclass(frozen=True, slots=True)
class DiscordMemoryFilterResult:
    decision: FilterDecision
    reason_code: str
    candidate_strength: CandidateStrength
    detected_intent: str
    matched_rules: tuple[str, ...]
    policy_version: str = DISCORD_MEMORY_RULE_FILTER_POLICY_VERSION


def normalize_discord_memory_text(value: str) -> tuple[str, str]:
    """Return evidence-preserving display and case-insensitive match forms."""

    normalized = unicodedata.normalize("NFC", value or "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized, normalized.casefold()


def _matches(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _result(
    decision: FilterDecision,
    reason: str,
    strength: CandidateStrength,
    intent: str,
    *rules: str,
) -> DiscordMemoryFilterResult:
    return DiscordMemoryFilterResult(
        decision=decision,
        reason_code=reason,
        candidate_strength=strength,
        detected_intent=intent,
        matched_rules=tuple(rules),
    )


class DiscordMemoryRuleFilter:
    """High-precision deterministic gate before any memory extractor."""

    _MENTION_PREFIX = re.compile(
        r"^(?:(?:<@!?\d+>|@[\wÀ-ỹ]+)[\s,:-]*)+",
        flags=re.IGNORECASE,
    )
    _QUESTION_WORDS = (
        r"\b(?:gì|gi|nào|nao|ai|sao|tại sao|tai sao|vì sao|vi sao|"
        r"bao nhiêu|bao nhieu|được không|duoc khong|là gì|la gi)\b",
    )
    _TRANSIENT_MARKERS = (
        r"\b(?:hôm nay|hom nay|bây giờ|bay gio|lúc này|luc nay|"
        r"hiện giờ|hien gio|tạm thời|tam thoi)\b",
        r"\b(?:đang|dang)\s+(?:uống|uong|ăn|an|ở|o|ngồi|ngoi|xem)\b",
        r"\b(?:tôi|toi)\s+có\s+(?:một|mot)\s+(?:cốc|coc|ly|chai|hộp|hop)\b",
    )
    _NON_OWNED_HARDWARE = (
        r"\b(?:đang xem|dang xem|định mua|dinh mua|muốn mua|muon mua|"
        r"đang cân nhắc|dang can nhac)\b",
    )

    def evaluate(self, source: DiscordMemoryFilterInput) -> DiscordMemoryFilterResult:
        # Trusted metadata exclusions always win and fail closed.
        if not source.memory_policy_enabled:
            return _result(
                "rejected_policy",
                "memory_policy_disabled",
                "none",
                "policy_exclusion",
                "memory_policy_disabled",
            )
        if source.source_role.casefold() != "user":
            return _result(
                "rejected_policy",
                "bot_or_system_message",
                "none",
                "policy_exclusion",
                "untrusted_source_role",
            )
        if source.duplicate_source:
            return _result(
                "rejected_policy",
                "duplicate_source",
                "none",
                "policy_exclusion",
                "duplicate_source",
            )
        if not (source.author_id or "").strip():
            return _result(
                "rejected_policy",
                "missing_trusted_author",
                "none",
                "policy_exclusion",
                "missing_author_id",
            )
        if (
            not (source.guild_id or "").strip()
            or not (source.channel_id or "").strip()
            or source.turn_status != "completed"
            or not source.delivery_exists
            or source.session_state != "active"
        ):
            return _result(
                "rejected_policy",
                "unsupported_scope",
                "none",
                "policy_exclusion",
                "invalid_completed_source",
            )
        if source.thread_id is not None and not source.thread_enabled:
            return _result(
                "rejected_policy",
                "unsupported_scope",
                "none",
                "policy_exclusion",
                "thread_memory_disabled",
            )

        normalized, text = normalize_discord_memory_text(source.request_text)
        if not normalized:
            return _result(
                "no_op",
                "empty_content",
                "none",
                "empty",
                "empty_content",
            )
        classification_text = self._MENTION_PREFIX.sub("", text).strip()

        # Explicit user intent outranks incidental greetings/questions.
        if _matches(
            classification_text,
            r"\b(?:hãy|hay)\s+(?:quên|quen)\b",
            r"\b(?:đừng|dung)\s+(?:nhớ|nho)\b",
            r"\b(?:xóa|xoá|xoa)\s+(?:memory|bộ nhớ|bo nho)\b",
            r"\b(?:không|khong)\s+(?:lưu|luu).*(?:nữa|nua)\b",
        ):
            return _result(
                "candidate",
                "explicit_forget",
                "strong",
                "forget",
                "explicit_forget",
            )
        if _matches(
            classification_text,
            r"\b(?:à|a)\s+(?:nhầm|nham)\b",
            r"\b(?:tôi|toi)\s+(?:sửa|sua)\s+(?:lại|lai)\b",
            r"\b(?:không|khong)\s+phải\b.+\b(?:mà|ma)\s+là\b",
            r"\b(?:thông|thong) tin (?:trước|truoc) (?:đó|do) sai\b",
            r"\b(?:đính chính|dinh chinh)\b",
        ):
            return _result(
                "candidate",
                "explicit_correction",
                "strong",
                "correction",
                "explicit_correction",
            )
        if _matches(
            classification_text,
            r"\b(?:hãy|hay)\s+(?:nhớ|nho)\s+(?:cho\s+)?"
            r"(?:server|máy chủ|may chu|guild)\b",
            r"\b(?:ghi nhớ|ghi nho|lưu lại|luu lai).*\b"
            r"(?:cho server|cho máy chủ|cho may chu)\b",
        ):
            return _result(
                "candidate",
                "explicit_shared_fact",
                "strong",
                "shared_fact",
                "explicit_shared_scope",
            )
        if _matches(
            classification_text,
            r"\b(?:hãy|hay)\s+(?:nhớ|nho)\b",
            r"\b(?:nhớ|nho)\s+(?:giúp|giup)\s+(?:tôi|toi)\b",
            r"\b(?:từ giờ|tu gio).*(?:ghi nhớ|ghi nho)\b",
            r"\b(?:ghi nhớ|ghi nho|lưu lại rằng|luu lai rang)\b",
        ):
            return _result(
                "candidate",
                "explicit_remember",
                "strong",
                "remember",
                "explicit_remember",
            )

        if _matches(
            classification_text,
            r"\b(?:tên|ten)\s+(?:tôi|toi)\s+(?:là|la)\b",
            r"\b(?:từ giờ|tu gio).*(?:gọi|goi)\s+(?:tôi|toi)\s+(?:là|la)\b",
            r"\b(?:hãy|hay)\s+(?:gọi|goi)\s+(?:tôi|toi)\s+(?:là|la)\b",
        ):
            return _result(
                "candidate",
                "identity_preference",
                "normal",
                "identity",
                "identity_assertion",
            )

        if _matches(
            classification_text,
            r"\b(?:mỗi lần|moi lan)\b.+\b(?:hãy|hay|phải|phai)\b",
            r"\b(?:luôn|luon)\b.+\b(?:trước khi|truoc khi)\b",
            r"\b(?:quy tắc|quy tac|workflow)\b.+\b(?:là|la|phải|phai)\b",
            r"\b(?:từ giờ|tu gio).*\b(?:mỗi|moi|luôn|luon)\b",
        ):
            return _result(
                "candidate",
                "workflow_rule",
                "normal",
                "workflow",
                "durable_workflow_rule",
            )

        owned_hardware = _matches(
            classification_text,
            r"\b(?:máy|may|pc|laptop)\s+(?:(?:của|cua)\s+)?(?:tôi|toi)\b",
            r"\b(?:ram|gpu|cpu|ổ cứng|o cung)\s+(?:máy|may)\s+"
            r"(?:(?:của|cua)\s+)?(?:tôi|toi)\b",
        )
        hardware_spec = _matches(
            classification_text,
            r"\b(?:rtx|gtx|radeon|ryzen|intel|core i[3579]|"
            r"ram|gpu|cpu|ssd|hdd)\b",
            r"\b\d+\s*(?:gb|tb)\b",
        )
        if (
            owned_hardware
            and hardware_spec
            and not _matches(classification_text, *self._NON_OWNED_HARDWARE)
        ):
            return _result(
                "candidate",
                "hardware_configuration",
                "normal",
                "hardware",
                "owned_hardware_configuration",
            )

        if _matches(
            classification_text,
            r"\b(?:dự án|du an|project)\s+(?:(?:của|cua)\s+)?(?:tôi|toi|"
            r"chúng ta|chung ta).*\b(?:dùng|dung|sử dụng|su dung|chạy|chay)\b",
            r"\b(?:tôi|toi)\s+(?:đang\s+)?(?:chạy|chay)\b.+\b"
            r"(?:cho|trong)\s+(?:dự án|du an|project)\b",
        ) and _matches(
            classification_text,
            r"\b(?:postgresql|postgres|sqlite|mysql|redis|python|"
            r"node(?:\.js)?|typescript|docker|fastapi|django)\b",
        ):
            return _result(
                "candidate",
                "software_configuration",
                "normal",
                "software",
                "project_software_configuration",
            )

        if _matches(
            classification_text,
            r"\b(?:chúng ta|chung ta|dự án|du an).*\b"
            r"(?:chốt|chot|quyết định|quyet dinh|thống nhất|thong nhat)\b",
            r"\b(?:chốt|chot|quyết định|quyet dinh|thống nhất|thong nhat)"
            r"\s+(?:dùng|dung)\b",
            r"\b(?:dự án|du an)\s+(?:sẽ|se)\s+(?:dùng|dung)\b",
        ) and not _matches(
            classification_text,
            r"\b(?:chưa|chua|không|khong)\s+"
            r"(?:chốt|chot|quyết định|quyet dinh|thống nhất|thong nhat)\b",
        ):
            return _result(
                "candidate",
                "project_decision",
                "normal",
                "project_decision",
                "durable_project_decision",
            )

        durable_preference = _matches(
            classification_text,
            r"\b(?:tôi|toi)\s+(?:thích|thich|không thích|khong thich|"
            r"ưu tiên|uu tien)\b",
            r"\b(?:từ giờ|tu gio).*\b(?:trả lời|tra loi|giải thích|giai thich)\b",
            r"\b(?:luôn|luon)\s+(?:trả lời|tra loi|giải thích|giai thich)\b",
        )
        transient_preference = _matches(
            classification_text,
            *self._TRANSIENT_MARKERS,
            r"\b(?:hôm nay|hom nay).*(?:thôi|thoi)\b",
        )
        if durable_preference and (
            not transient_preference
            or _matches(classification_text, r"\b(?:từ giờ|tu gio|luôn|luon)\b")
        ):
            return _result(
                "candidate",
                "durable_preference",
                "normal",
                "preference",
                "durable_preference",
            )

        if _matches(classification_text, *self._TRANSIENT_MARKERS):
            return _result(
                "no_op",
                "transient_state",
                "none",
                "transient",
                "transient_state",
            )

        if _matches(
            classification_text,
            r"^(?:xin\s+)?(?:chào|chao)(?:\s+(?:bot|ún|un|bạn|ban))?[!. ]*$",
            r"^(?:hello|hi|hey)(?:\s+(?:bot|ún|un))?[!. ]*$",
        ):
            return _result(
                "no_op",
                "greeting",
                "none",
                "smalltalk",
                "greeting",
            )
        if _matches(
            classification_text,
            r"^(?:ok[, ]*)?(?:cảm ơn|cam on|thanks|thank you)"
            r"(?:\s+(?:nhé|nhe|bạn|ban))?[!. ]*$",
        ):
            return _result(
                "no_op",
                "thanks",
                "none",
                "smalltalk",
                "thanks",
            )
        if _matches(
            classification_text,
            r"^(?:haha+|hihi+|lol+|kk+)[!. ]*$",
            r"^(?:đùa thôi|dua thoi|chọc bạn thôi|choc ban thoi)[!. ]*$",
        ):
            return _result(
                "no_op",
                "joke_or_smalltalk",
                "none",
                "smalltalk",
                "joke_or_smalltalk",
            )

        has_question = "?" in classification_text or _matches(
            classification_text,
            *self._QUESTION_WORDS,
        )
        if has_question:
            return _result(
                "no_op",
                "question_only",
                "none",
                "question",
                "question_without_durable_assertion",
            )
        return _result(
            "no_op",
            "no_durable_fact",
            "none",
            "none",
            "no_durable_fact",
        )
