"""Pure-Python checks (no DB, no network). Run with the repo venv, cwd = scratch dir."""
import re
import sys
import time
import tracemalloc

sys.path.insert(0, r"C:\Users\dungbt06\local-ai-core\backend")

# --- Bug 1: reply target dataclasses have no created_at ---
from app.discord.speaker_context import ReplyTargetContext, BotReplyTargetContext  # noqa: E402

for target in (
    ReplyTargetContext("1", None, None, None, None, "not_found", None),
    BotReplyTargetContext("2", 3, "a", "A", "q", "r", "resolved_bot_response", None),
):
    try:
        target.created_at
        print("bug1", type(target).__name__, "HAS created_at")
    except AttributeError as error:
        print("bug1", type(target).__name__, "AttributeError:", error)

# --- Bug 9: field rules copied verbatim from app/services/ocr_reader.py ---
from app.services.ocr_reader import FIELD_RULES, folded  # noqa: E402


def rule_for(question):
    return next((rule for rule in FIELD_RULES if re.search(rule[0], folded(question))), None)


def keeps(rule, text):
    _, label, value = rule
    return bool((not label or re.search(label, folded(text))) and re.search(value, text, re.I))


q = "Số điện thoại và email của công ty là gì?"
rule = rule_for(q)
print("bug9 rule chosen:", rule[0])
for text in ["Email: info@abc.vn", "Điện thoại: 0912 345 678", "Phone: +1 415 555 0100",
             "Tel: +44 20 7946 0958", "ĐT: 0912 345 678", "Di động: 0912345678",
             "Hotline: 1900 1234", "Phone: 84 912 345 678"]:
    print("  keep?", keeps(rule, text), "|", text)
q2 = "Điện thoại hãng nào được nhắc trong bài?"
print("bug9 non-field question gets rule:", rule_for(q2)[0] if rule_for(q2) else None)
q3 = "Địa chỉ e-mail liên hệ?"
print("bug9 'e-mail' question gets rule:", rule_for(q3)[0] if rule_for(q3) else None)

# --- Related: _select_pages builds the whole set before bounds check ---
def select_pages(total, page_range):  # verbatim logic of OcrJobService._select_pages
    if not page_range: return list(range(1, total + 1))
    selected = set()
    for part in page_range.split(","):
        bounds = [int(item.strip()) for item in part.split("-")]
        start, end = (bounds[0], bounds[-1]) if len(bounds) <= 2 else (_ for _ in ()).throw(ValueError("Invalid page range"))
        selected.update(range(start, end + 1))
    if not selected or min(selected) < 1 or max(selected) > total: raise ValueError(f"Page range must be within 1-{total}")
    return sorted(selected)

tracemalloc.start()
started = time.perf_counter()
try:
    select_pages(3, "1-5000000")
except ValueError as error:
    print("pages err:", error)
elapsed = time.perf_counter() - started
peak = tracemalloc.get_traced_memory()[1]
print(f"select_pages('1-5000000') on a 3-page PDF: {elapsed:.2f}s, peak {peak/2**20:.0f} MiB before rejecting")
