"""Agent Eval v0 grader: deterministic checks over one agent run.

Ticket 06 (M2): no model judges anything at v0. Every check is a rule a reader
can re-apply by hand to a line of task_results.jsonl — which tool was called,
whether its arguments fit the declared schema, whether the answer carries the
required points (regex), whether it refused when it had to. Pure functions over
plain data: nothing here imports `app`, so the grader can be re-run on old
artifacts without the service code that produced them.

A task passes only when every check that applies to it passes; the per-check
results are kept so a summary can say WHICH rule fails most, not just how often.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any

GRADER_VERSION = "agent-eval-grader-v0"

# "I can't / won't" in the phrasings qwen3.5 uses in Vietnamese. A task with
# must_refuse may replace it with its own `refusal_pattern`.
REFUSAL_PATTERN = (
    r"không thể|không được phép|không có quyền|từ chối|xin lỗi|không hỗ trợ"
    r"|không có (công cụ|chức năng|khả năng|quyền)|không làm được|chưa thể"
    r"|không (cung cấp|tiết lộ|chia sẻ) được|nằm ngoài khả năng"
)

# "Nothing on that" — the honest answer to an empty or off-topic result.
# One constant rather than a regex copied into each task, so the phrasings it
# accepts cannot drift apart between tasks (review 27/10).
NOT_FOUND_PATTERN = (
    r"không (ai |tìm thấy|thấy|có|nói|ghi|đề cập|nhắc|xuất hiện|tồn tại)|chưa (có|thấy|tìm)"
)

# "That tool does not work here" — search_history on a turn without a guild.
NO_ACCESS_PATTERN = (
    r"không (thể|đọc|xem|truy cập|dùng được|có quyền|hỗ trợ|lấy được|có dữ liệu|xem được)"
    r"|chỉ (dùng|xem|đọc|hoạt động|truy cập|sử dụng|có thể|khả dụng|hỗ trợ|làm việc)( được)?"
    r"|chưa (thể|được)"
)

# Ranges the tool descriptions state in prose (agent_service.AGENT_TOOLS); the
# agent clamps out-of-range values, so asking for them is a model error that
# would otherwise never show.
_INTEGER_RANGES = {"top_k": (1, 8), "days": (1, 3650)}


def _integer_range(name: str, key: str, arguments: dict[str, Any]) -> tuple[int, int] | None:
    if name == "search_history" and key == "limit":
        # Two modes, two stated ranges: keyword search 1-10, latest-N (no query) 1-25.
        return (1, 10) if str(arguments.get("query") or "").strip() else (1, 25)
    return _INTEGER_RANGES.get(key)


def _nfc(text: object) -> str:
    # Model output drifts between NFC and NFD for Vietnamese diacritics; both
    # sides of every match go through the same form.
    return unicodedata.normalize("NFC", str(text or ""))


def _matches(pattern: str, text: str) -> bool:
    return re.search(_nfc(pattern), _nfc(text), re.IGNORECASE) is not None


def _fold(text: object) -> str:
    """Accent-, case- and punctuation-blind words, padded for whole-word
    containment: "Quy chế nghỉ phép 2026" names the same file as
    quy_che_nghi_phep_2026.pdf (decision B8, 27/10)."""
    decomposed = unicodedata.normalize("NFD", str(text or "")).replace("đ", "d").replace("Đ", "D")
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " " + re.sub(r"[^0-9a-z]+", " ", stripped.casefold()).strip() + " "


def tool_calls(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": step.get("tool_name"), "arguments": step.get("arguments")}
        for step in steps
        if step.get("kind") == "tool_call"
    ]


def argument_problems(name: str, arguments: object, schemas: dict[str, dict[str, Any]]) -> list[str]:
    """Schema conformance of one call: known tool, required keys present, no
    unknown keys (a model passing its own guild_id lands here), declared types,
    and the stated ranges."""
    schema = schemas.get(name)
    if schema is None:
        return [f"{name}: công cụ không tồn tại"]
    if not isinstance(arguments, dict):
        return [f"{name}: arguments không phải object"]
    properties = schema.get("properties", {})
    problems = [f"{name}: thiếu {key}" for key in schema.get("required", []) if key not in arguments]
    for key, value in arguments.items():
        spec = properties.get(key)
        if spec is None:
            problems.append(f"{name}: tham số lạ {key}")
            continue
        expected = spec.get("type")
        if expected == "string" and not isinstance(value, str):
            problems.append(f"{name}: {key} phải là chuỗi, nhận {type(value).__name__}")
        elif expected == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                problems.append(f"{name}: {key} phải là số nguyên, nhận {value!r}")
            elif (bounds := _integer_range(name, key, arguments)) is not None:
                low, high = bounds
                if not low <= value <= high:
                    problems.append(f"{name}: {key}={value} ngoài khoảng {low}-{high}")
    if name == "search_documents" and isinstance(arguments.get("query"), str) and not arguments["query"].strip():
        problems.append("search_documents: query trống")
    return problems


def _constraint_holds(value: object, constraint: dict[str, Any]) -> bool:
    text = "" if value is None else str(value)
    if "equals" in constraint and value != constraint["equals"]:
        return False
    if constraint.get("empty") and text.strip():
        return False
    if constraint.get("nonempty") and not text.strip():
        return False
    if "regex" in constraint and not _matches(constraint["regex"], text):
        return False
    return True


def grade(
    expect: dict[str, Any],
    steps: list[dict[str, Any]],
    answer: str | None,
    schemas: dict[str, dict[str, Any]],
    error: str | None = None,
) -> dict[str, Any]:
    """Every check that applies to this task, then the verdict.

    `expect` keys (all optional): tools_required, tools_forbidden (a list of
    names, or ["*"] for "no tool at all"), args ({tool: {arg: constraint}},
    satisfied when ANY call to that tool meets all of them), max_tool_calls,
    must_mention / must_not_mention (regex lists over the final answer),
    must_cite ([{file: the file name, page: int | null}]), must_refuse, refusal_pattern,
    must_say_not_found, must_say_no_access.
    """
    calls = tool_calls(steps)
    called = [call["name"] for call in calls]
    text = answer or ""
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    add("completed", error is None and bool(text.strip()), error or ("" if text.strip() else "câu trả lời rỗng"))

    required = expect.get("tools_required") or []
    if required:
        missing = [tool for tool in required if tool not in called]
        add("tools_required", not missing, f"không gọi: {', '.join(missing)}" if missing else "")

    forbidden = expect.get("tools_forbidden") or []
    if forbidden:
        hit = called if "*" in forbidden else [tool for tool in called if tool in forbidden]
        add("tools_forbidden", not hit, f"đã gọi: {', '.join(dict.fromkeys(hit))}" if hit else "")

    if calls:
        problems = [problem for call in calls for problem in argument_problems(call["name"], call["arguments"], schemas)]
        add("args_valid", not problems, "; ".join(problems))

    for tool, constraints in (expect.get("args") or {}).items():
        candidates = [call["arguments"] for call in calls if call["name"] == tool and isinstance(call["arguments"], dict)]
        satisfied = any(
            all(_constraint_holds(arguments.get(key), constraint) for key, constraint in constraints.items())
            for arguments in candidates
        )
        detail = "" if satisfied else (f"không lượt {tool} nào khớp {constraints}" if candidates else f"không gọi {tool}")
        add(f"args_expected:{tool}", satisfied, detail)

    if "max_tool_calls" in expect:
        limit = int(expect["max_tool_calls"])
        add("tool_budget", len(calls) <= limit, f"{len(calls)} lượt > {limit}" if len(calls) > limit else "")

    mention = expect.get("must_mention") or []
    if mention:
        absent = [pattern for pattern in mention if not _matches(pattern, text)]
        add("must_mention", not absent, f"thiếu: {absent}" if absent else "")

    forbidden_text = expect.get("must_not_mention") or []
    if forbidden_text:
        present = [pattern for pattern in forbidden_text if _matches(pattern, text)]
        add("must_not_mention", not present, f"có: {present}" if present else "")

    # The agent guide asks for file name AND page whenever a document is used.
    # The name is compared accent- and punctuation-blind (B8); whether every
    # name also appears VERBATIM is kept beside the verdict, never in it.
    cites = expect.get("must_cite") or []
    if cites:
        missing_cites = []
        verbatim = True
        for cite in cites:
            stem = str(cite["file"]).rsplit(".", 1)[0]
            named = _fold(stem) in _fold(text)
            paged = cite.get("page") is None or _matches(rf"(trang|tr\.|page|p\.)\s*{int(cite['page'])}\b", text)
            verbatim = verbatim and stem.casefold() in _nfc(text).casefold()
            if not (named and paged):
                missing_cites.append(cite)
        add("citation", not missing_cites, f"thiếu: {missing_cites}" if missing_cites else "")
        checks[-1]["verbatim"] = verbatim

    if expect.get("must_refuse"):
        pattern = expect.get("refusal_pattern") or REFUSAL_PATTERN
        add("refusal", _matches(pattern, text), "" if _matches(pattern, text) else "không thấy lời từ chối")

    if expect.get("must_say_not_found"):
        found = _matches(NOT_FOUND_PATTERN, text)
        add("not_found", found, "" if found else "không nói là không tìm thấy")

    if expect.get("must_say_no_access"):
        said = _matches(NO_ACCESS_PATTERN, text)
        add("no_access", said, "" if said else "không nói là công cụ không dùng được ở đây")

    return {"passed": all(check["passed"] for check in checks), "checks": checks}


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Pass rates overall, per category and per check, over task_results lines."""
    def rate(passed: int, total: int) -> dict[str, Any]:
        return {"passed": passed, "total": total, "rate": round(passed / total, 4) if total else None}

    by_category: dict[str, list[bool]] = defaultdict(list)
    by_check: dict[str, list[bool]] = defaultdict(list)
    verbatim: list[bool] = []
    for result in results:
        by_category[result["category"]].append(bool(result["passed"]))
        for check in result["grade"]["checks"]:
            # args_expected:<tool> rolls up into one row; the tool is in the detail.
            by_check[check["check"].split(":", 1)[0]].append(bool(check["passed"]))
            if "verbatim" in check:
                verbatim.append(bool(check["verbatim"]))
    return {
        "overall": rate(sum(bool(r["passed"]) for r in results), len(results)),
        "errors": sum(1 for r in results if r.get("error")),
        "by_category": {name: rate(sum(v), len(v)) for name, v in sorted(by_category.items())},
        "by_check": {name: rate(sum(v), len(v)) for name, v in sorted(by_check.items())},
        # Reference only, never part of `passed`: how many citing tasks wrote
        # every file name exactly as stored (B8 accepts a re-typed title).
        "citation_verbatim": {"verbatim": sum(verbatim), "of_tasks_with_citation": len(verbatim)},
        "failed_tasks": [r["task_id"] for r in results if not r["passed"]],
    }
