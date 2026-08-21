# D3a — Self-check bám nguồn cho câu trả lời RAG (không dùng model)

**Trạng thái 21/08/2026: PHẦN XÂY XONG (lane nhẹ, máy `hehehhe`) — chờ máy mạnh đo.**
Mục Track D3a trong `docs/DEVELOPMENT_PLAN.md`; phân lane theo `docs/machine_split.md`.

## Nó là gì

Một bộ kiểm tra **0 lời gọi model** (bất biến ngân sách inference, plan §1) chạy ngay
sau khi câu trả lời RAG sinh xong: từng câu của câu trả lời được đối chiếu với **văn
bản trần (`content`) của các chunk đã trích** — đúng thứ người dùng mở ra xem được,
không bao giờ dùng `retrieval_context` sinh bởi P4-2. Tư duy lấy từ guard memory P2-1b
(`discord_memory_guard.py`): fold dấu, content-word overlap, bằng chứng nguyên văn.

| Thành phần | Vị trí |
| --- | --- |
| Bộ chấm | `backend/app/services/answer_grounding.py` |
| Schema báo cáo | `GroundingReport` trong `backend/app/schemas/rag_schema.py` |
| Điểm gắn | `POST /rag/chat`: field `grounding` (response thường) và sự kiện SSE `done` (stream) |
| Web UI | chip "bám nguồn x%" ở footer tin nhắn (tooltip liệt kê câu chưa đủ nguồn) |
| Harness | `evaluate_rag.py` chế độ full (không `--retrieval-only`): `grounding` summary + `grounding_rate` |
| Test | `backend/tests/test_answer_grounding.py` (10 test, không model) |

**Chỉ báo cáo.** Không chặn, không sửa câu trả lời — quyết định đó cần số đo thật ở dưới.

## Cách chấm (và lý do từng ngưỡng)

| Bước | Quy tắc | Lý do |
| --- | --- | --- |
| Tách câu | theo `.?!…` và xuống dòng; bỏ bullet/số thứ tự/`#` | câu trả lời Markdown |
| Bỏ qua | câu < 4 content-word, câu xã giao (chào, cảm ơn, "tóm lại") | không phải mệnh đề cần nguồn; đếm vào sẽ chỉ thêm nhiễu |
| `grounded` | ≥ 60% content-word của câu có trong nguồn, **hoặc** có chuỗi ≥ 4 content-word liên tiếp nguyên văn trong nguồn | 0.6 = câu chủ yếu dùng từ vựng của nguồn; chuỗi nguyên văn là "evidence verbatim" của guard memory |
| `weak` | 34% ≤ overlap < 60% | 0.34 là sàn đo được của guard memory (benchmark P2-1b) |
| `ungrounded` | overlap < 34% | dưới sàn: câu gần như không lấy gì từ nguồn |
| Xuyên ngữ | câu khác ngôn ngữ với nguồn (phát hiện bằng chữ cái có dấu tiếng Việt) bị **trần ở `weak`** + cờ `language_mismatch` | kiểm tra từ vựng không nhìn xuyên ngôn ngữ được (điểm mù T12): kết luận đúng là "không chấm được", không phải "bịa" |
| Nhãn tổng | có câu `ungrounded` → `ungrounded`; ≥ 80% câu `grounded` → `grounded`; còn lại `weak`; không có câu nào chấm được → `unjudged` | một câu bịa là đủ để cả câu trả lời không đáng tin |
| Không có nguồn | mọi câu `ungrounded` | không nguồn thì không gì bám được, bất kể ngôn ngữ |

Điểm mù **có chủ đích**: diễn giải bằng từ khác với nguồn bị chấm thấp hơn thực tế.
Hướng thiết kế là **báo thiếu còn hơn chứng nhận nhầm** — `weak` là phía an toàn.

## Handoff cho máy MẠNH — đo `grounding_rate` trên bộ 82 câu

Chế độ full gọi model sinh cho 82 câu (lane nặng). Chạy khi API + Ollama đang chạy,
từ `backend/`:

```powershell
python -m scripts.evaluate_rag --multidoc-dataset ..\data\evaluation\rag_multidoc_eval.jsonl
# (KHÔNG --retrieval-only, KHÔNG --write-baseline: baseline D1 là retrieval-only, không đụng)
```

Báo cáo in `grounding` = `{graded, grounding_rate, ungrounded_rate, language_mismatch, labels}`
và liệt kê id các câu `ungrounded`; file kết quả có `grounding_label`, `grounded_ratio`,
`ungrounded_sentences` theo từng câu trong `data/evaluation/results/rag-multidoc-*.json`.

### Tiêu chí nghiệm thu D3a

1. **Đối chiếu tay 10 câu** (bắt buộc — kiểm tra guard không báo sai chiều): lấy 5 câu
   bị gắn `ungrounded` và 5 câu `grounded`, đọc câu trả lời cạnh nguồn và tự chấm.
   Đạt khi: không câu `grounded` nào chứa mệnh đề bịa rõ ràng (**không dương tính giả
   về độ tin cậy**), và ≥ 3/5 câu `ungrounded` thật sự có ý không có trong nguồn.
   Nếu đa số `ungrounded` chỉ là diễn giải đúng bằng từ khác → ngưỡng quá gắt, ghi lại
   và đề xuất hạ `GROUNDED_MINIMUM`/`WEAK_MINIMUM` kèm số liệu (không sửa ngay trong
   cùng lần đo).
2. Ghi `grounding_rate`, `ungrounded_rate`, phân phối nhãn, `language_mismatch` vào
   bảng dưới — đây là **baseline faithfulness** đầu tiên của dự án, thước đo cho
   mọi thay đổi prompt/model trả lời về sau.
3. Nhận định ngắn: các câu `ungrounded` rơi vào nhóm nào (single/cross), có trùng
   với 7 câu retrieval còn miss không (bịa vì không tìm thấy nguồn, hay bịa dù có nguồn).

**Bảng kết quả (điền khi đo trên máy nặng):**

| Metric | Giá trị | Ghi chú |
| --- | --- | --- |
| graded (câu có câu trả lời) | — | |
| grounding_rate | — | tỉ lệ nhãn tổng `grounded` |
| ungrounded_rate | — | |
| labels | — | grounded / weak / ungrounded / unjudged |
| language_mismatch | — | số câu trả lời bị trần vì khác ngôn ngữ |
| answer_pass_rate | — | proxy từ vựng cũ, để so với grounding |
| Đối chiếu tay 10 câu | — | dương tính giả về độ tin cậy: phải = 0 |

Sau khi có số: quyết định bước kế tiếp của D3a (giữ mức "chỉ báo", hay thêm hành vi
"thú nhận thiếu nguồn"/tìm thêm khi `ungrounded`) ghi vào `docs/DEVELOPMENT_PLAN.md`.
