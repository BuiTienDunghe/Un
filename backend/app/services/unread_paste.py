"""An answer that asks the user for the paste the turn already holds, or says it read all of
one, while chunks of it are still unread: AgentService sends it back once to read on
(ticket 20 #3-D, step 1).

On #3-C's slip (kept/agent-eval-v0.6-paste-slip-c/, after side, both runs) three paste tasks
failed this way: doc-40 and doc-44 never opened the paste and asked the user to "cung cấp
phần giữa của văn bản" (doc-44 also "Dán lại toàn bộ văn bản đầy đủ"); doc-47 read one call's
worth and wrote "Tôi đã đọc được văn bản hợp đồng đầy đủ". The words alone decide nothing: the
step fires only while the turn's paste has a chunk no read_document result of this turn
returned. A search_documents excerpt is not a read.

The patterns were written from those three answers only. Over the 58 kept paste answers
(v0.3-pastes, v0.5-paste-slip-b, v0.6-paste-slip-c; every run, both sides) they fire on 10,
all failing: doc-40, doc-44 and doc-47 on #3-C's after side (2 runs each), and doc-41 on the
first slip ("đã đọc toàn bộ" after 3 of 15 chunks; 4 runs). They fire on none of the 20
passing answers, every one of which still had chunks unread.

Blind spots, by construction:
- a request in other words is not seen: "cung cấp thêm thông tin", "bạn có muốn tôi đọc
  tiếp không", an offer to read instead of reading;
- a give-verb after its object ("văn bản bạn cung cấp") is a reference, not a request, and
  so is one after "đã", "vừa", "được" or a negation ("không cần dán lại");
- a claim of having read it all needs "đã" or "sau khi" before "đọc".
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from app.services.pastes import read_paste

ASKS_FOR_PASTE = "asks_for_paste"
CLAIMS_READ_ALL = "claims_read_all"

_NOT_A_REQUEST = r"(?<!đã\s)(?<!vừa\s)(?<!được\s)(?<!đừng\s)(?<!không cần\s)"
_GIVE = r"(?:dán|gửi|tải lên|cung cấp)"
_AGAIN = r"(?:lại|thêm|nốt|tiếp|toàn bộ|đầy đủ|cả)"
_FOR_ME = r"(?:giúp|giùm|hộ|cho tôi|cho mình|cho em)"
_PART = r"(?:phần|đoạn|nội dung)\s+(?:giữa|còn lại|bị thiếu|bị cắt|thiếu|chưa)"
_WHOLE = r"(?:văn bản|toàn văn|bản đầy đủ|nội dung|tệp)"
_ASKS = re.compile(
    # "cung cấp phần giữa của văn bản": a part the model says it has not got.
    rf"{_NOT_A_REQUEST}\b{_GIVE}(?:\s+(?:{_AGAIN}|{_FOR_ME}))*\s+{_PART}"
    # "Dán lại toàn bộ văn bản": the whole text, again.
    rf"|{_NOT_A_REQUEST}\b{_GIVE}(?:\s+{_FOR_ME})*\s+{_AGAIN}(?:\s+(?:{_AGAIN}|{_FOR_ME}))*\s+{_WHOLE}"
    rf"|{_NOT_A_REQUEST}\b{_GIVE}\s+{_WHOLE}\s+(?:đầy đủ|hoàn chỉnh|gốc)\b"
)
# "đã đọc được văn bản hợp đồng đầy đủ": up to five words between, none of them a negation,
# and not the two edges the slip showed ("đã đọc hết phần đầu").
_READ_ALL = re.compile(
    r"\b(?:đã|sau khi)\s+đọc((?:\s+[^\W\d_]+){0,5}?)\s+(?:hết|toàn bộ|đầy đủ|trọn vẹn|từ đầu đến cuối)\b"
    r"(?!\s+(?:phần\s+)?(?:đầu|cuối))"
)
_NEGATION = re.compile(r"\b(?:chưa|không)\b")


def _normal(text: str) -> str:
    """Lower case, one Unicode form, no markdown emphasis: "**Cung cấp** phần giữa" reads as words."""
    return re.sub(r"[*_`]", "", unicodedata.normalize("NFC", text or "").lower())


def claim(answer: str) -> str | None:
    """Which of the two failures the answer's words show, or None."""
    text = _normal(answer)
    if _ASKS.search(text):
        return ASKS_FOR_PASTE
    if any(not _NEGATION.search(match.group(1)) for match in _READ_ALL.finditer(text)):
        return CLAIMS_READ_ALL
    return None


def _payload(content: str) -> object:
    """A tool result's JSON, inside the injection-defense wrapper (its <<<…>>> lines) or not."""
    lines = content.split("\n")
    body = "\n".join(lines[1:-1]) if len(lines) >= 3 and lines[0].startswith("<<<") and lines[-1].startswith("<<<") else content
    try:
        return json.loads(body)
    except ValueError:
        return None


def chunks_read(messages: list[dict[str, Any]], document_id: str) -> set[int]:
    """The chunks of one paste that read_document results in `messages` carried: what the
    model was actually shown, after _fit_chunks kept as many as fit."""
    read: set[int] = set()
    for message in messages:
        if message.get("role") != "tool" or message.get("tool_name") != "read_document":
            continue
        payload = _payload(str(message.get("content") or ""))
        if not isinstance(payload, dict) or payload.get("document_id") != document_id:
            continue
        read.update(chunk["chunk_index"] for chunk in payload.get("chunks") or () if isinstance(chunk, dict) and isinstance(chunk.get("chunk_index"), int))
    return read


def unread_paste(answer: str, messages: list[dict[str, Any]], pastes: dict[str, str]) -> dict[str, Any] | None:
    """{"pattern", "document_id", "from_chunk", "read"} when the answer should go back, else None.
    The paste is the turn's last one (take_pastes keeps message order): one a user pasted
    further back is not what an answer to the new message is about."""
    if not pastes:
        return None
    pattern = claim(answer)
    if pattern is None:
        return None
    document_id = list(pastes)[-1]
    total = int(read_paste(document_id, pastes[document_id], 0, 1)["total_chunks"])
    read = chunks_read(messages, document_id)
    first = next((index for index in range(total) if index not in read), None)
    if first is None:
        return None
    return {"pattern": pattern, "document_id": document_id, "from_chunk": first, "read": len(read)}


def read_on_instruction(found: dict[str, Any], n: int) -> str:
    """The system message for the one retry: the exact call to read on. No chunk count: on
    #3-B's slip the model asked n = the count it was shown."""
    call = f'read_document(document_id="{found["document_id"]}", from_chunk={found["from_chunk"]}, n={n})'
    if found["pattern"] == ASKS_FOR_PASTE:
        return (
            "Kiểm tra câu trả lời vừa viết: nó nhờ người dùng gửi văn bản, nhưng văn bản người dùng dán đã nằm "
            "sẵn trong tin nhắn, đừng nhờ dán, gửi hay cung cấp lại. Hãy tự đọc phần chưa đọc: gọi "
            f"{call}. Rồi trả lời lại."
        )
    return (
        "Kiểm tra câu trả lời vừa viết: nó nói đã đọc hết văn bản người dùng dán, nhưng văn bản còn phần "
        f"chưa đọc. Hãy đọc tiếp: gọi {call}. Rồi trả lời lại."
    )
