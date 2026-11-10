import sys, time
sys.path.insert(0, r"C:\Users\dungbt06\local-ai-core\backend")
from datetime import datetime, UTC
# 1
from app.discord.speaker_context import ReplyTargetContext, BotReplyTargetContext
t = ReplyTargetContext("1", None, None, None, None, "not_found", None)
for obj in (t, BotReplyTargetContext("1", 1, None, None, "q", "a", "resolved_bot_response", None)):
    try: obj.created_at <= datetime.now(UTC)
    except Exception as e: print("1:", type(obj).__name__, type(e).__name__, e)
try: None <= datetime.now(UTC)
except Exception as e: print("1 pitfall None<=dt:", type(e).__name__)
# 9
from app.services.ocr_reader import read_evidence
class R:
    def chat_structured(self, role, messages, schema, options=None):
        import json
        ids = schema["properties"]["block_ids"]["items"]["enum"]
        print("   offered ids:", ids)
        return json.dumps({"block_ids": ids[:3]}), "fake"
blocks = [{"id":"b1","text":"Điện thoại: 0903 123 456"},{"id":"b2","text":"Email: a@b.vn"},
          {"id":"b3","text":"Hotline: 1900 1234"},{"id":"b4","text":"Phone: +1 415 555 0100"},
          {"id":"b5","text":"ĐT: 028 3822 1234"},{"id":"b6","text":"Tel: (84-28) 3822 1234"}]
for q in ["Số điện thoại và email là gì?", "Email và số điện thoại?", "số điện thoại hotline?", "What phone model is this manual for?"]:
    print("9:", q); r = read_evidence(R(), q, blocks); print("   ->", r["status"], [b["id"] for b in r["evidence"]], r.get("reason"))
print("9 only-intl:", read_evidence(R(), "phone?", blocks[3:4])["reason"])
print("9 only-hotline:", read_evidence(R(), "số điện thoại?", blocks[2:3])["reason"])
# 8-related page range
def _select_pages(total, page_range):
    selected=set()
    for part in page_range.split(","):
        bounds=[int(i.strip()) for i in part.split("-")]
        start,end=(bounds[0],bounds[-1])
        selected.update(range(start,end+1))
    if not selected or min(selected)<1 or max(selected)>total: raise ValueError("range")
    return sorted(selected)
s=time.perf_counter()
try: _select_pages(3,"1-20000000")
except ValueError: pass
print("page_range 1-2e7 on 3-page pdf: %.1fs before rejection"%(time.perf_counter()-s))
# 7 pitfall: route matching
from starlette.routing import Route
from pathlib import Path
r = Route("/api/ocr/history/{job_id}", endpoint=lambda request: None, methods=["DELETE"])
for p in ["/api/ocr/history/..", "/api/ocr/history/.." + chr(92) + ".." + chr(92) + "x", "/api/ocr/history/ocr_abc"]:
    m, child = r.matches({"type":"http","path":p,"method":"DELETE"})
    jid = child.get("path_params",{}).get("job_id")
    print("7 route:", repr(p), m.name, repr(jid), "->", (Path(r"C:\data\ocr_runs")/jid) if jid else None)
