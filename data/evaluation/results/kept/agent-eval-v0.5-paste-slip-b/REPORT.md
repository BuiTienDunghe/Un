# Agent Eval v0.5 — ticket 20 #3-B, lời phiếu đoạn dán mới (28/10/2026, 15:08–15:13)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm công bố.
Đăng ký trước: `PREREGISTRATION.md` (073d152, 10:53), fable duyệt (`reviews/prereg-20-3b-073d152.md`).

## Thật ra chuyện này là gì

Khi người dùng dán một văn bản dài, model chỉ được xem đầu và cuối, kèm một tờ phiếu chỉ cách mở phần giữa. Với
phiếu cũ, model hay đi tìm trong kho tài liệu thay vì mở chính văn bản được dán. Phiếu mới sửa đúng chỗ đó: lần nào
model cũng mở văn bản, đọc tiếp đúng thứ tự, và tìm ra đáp án ở bốn trên năm bài. Nhưng model cứ xin mỗi lần đọc nhiều
phần hơn mức công cụ cho phép. Công cụ tự cắt bớt nên model vẫn nhận đúng phần được đọc, còn bộ chấm thì coi lời xin
sai đó là một lỗi. Vì thế, theo luật viết trước khi chạy, phiếu mới **không đạt**: có một bài đang đạt lại thành trượt.

## Kết quả (mỗi phía r1 = r2 từng chữ)

| Luật đăng ký trước | Kết quả |
|---|---|
| 1. Băm công cụ, lời dặn, prompt, bộ bài bằng nhau ở hai phía | **đúng** (`153209…`, `6194cf…`, `385cb4…`, `eb62c4…`) |
| 2. doc-39 mở đoạn dán | **đúng** |
| 3. Ít nhất 2/3 bài doc-40, 41, 43 mở | **đúng** (3/3) |
| 4. Không bài đoạn dán nào từ đạt thành trượt | **SAI**: doc-42 |
| 5. Ít nhất một bài cần phần giữa từ trượt thành đạt | **đúng**: doc-39 |

**Không đề xuất gộp.** Main vẫn ở `8bb58e1` (phiếu cũ); `int/20-3b` (`c54e3eb`) giữ nguyên làm nhánh.

Hai dòng tách riêng như fable yêu cầu (ghi chú 1 của bài duyệt):

| | Trước (phiếu cũ) | Sau (phiếu mới) |
|---|---:|---:|
| Phiếu làm model mở đoạn dán | 2/5 (doc-40, 41) | **5/5** |
| Đọc tiếp đúng bằng `next_from_chunk` ở bài đáp án xa (40, 41, 43) | 0/3 | **2/3** (40, 41) |
| Mở chỉ sau khi bị kiểm con số bác | 0 | 0 |

## Từng bài: hai mục chấm quyết định

| Bài | Đáp án ở đoạn | Trước: đủ ý | Sau: đủ ý | Sau: `n` xin (trần 3) | Sau: đạt |
|---|---|:-:|:-:|---|:-:|
| doc-39 | 2 | ✗ (tìm kho, hỏi lại) | ✓ | 3 | ✓ |
| doc-40 | 3 | ✗ (đọc đoạn 4–6, trả lời sai ngày, sai người) | ✓ | 8, 5 | ✗ chỉ vì `n` |
| doc-41 | 6 | ✗ (đọc 0–2, nói "đã đọc toàn bộ 15 đoạn") | ✓ | 15, 12, 10 | ✗ chỉ vì `n` |
| doc-42 | đã thấy ở cuối | ✓ (không đọc) | ✓ | 8, 5, 2 | ✗ chỉ vì `n` |
| doc-43 | 1 và 5 | ✗ (không đọc, hỏi lại) | ✗ (thấy người, thiếu ngày; nói "văn bản không nêu") | 10 | ✗ |

Điểm: trước 1/5, sau 1/5. Công cụ cắt `n` về 3 (`agent_service.py:545`, `_bounded(…, 1, READ_MAX_CHUNKS)`), nên `n` xin
sai không đổi gì model nhận được; mỗi lần đọc vẫn trả đúng 3 đoạn, `next_from_chunk` nhảy 0→3→6→9. Chỉ bộ chấm v0.4
(`args_valid`, `n` 1–3) phạt lời xin. Ở lần đọc đầu, model xin `n` bằng đúng số đoạn mà phiếu nêu ("Văn bản có N đoạn")
ở 4/5 bài (doc-40..43); riêng doc-39 (7 đoạn) dùng đúng lệnh gợi ý `n=3`. Đây là quan sát, chưa phải nguyên nhân đã kiểm.
Phiếu cũ cũng có lời xin như vậy (doc-40 `n=4`, doc-41 `n=15`).

doc-42 chính là ca điều 4 được đặt ra để bắt. Bản đăng ký ghi "số lần đọc thừa ở doc-42 được ghi nhưng không chặn",
nhưng `args_valid` trên chính các lần đọc thừa đó lại chặn. Hai câu này vênh nhau, và bản đăng ký không nói câu nào
thắng; tôi áp đúng luật như viết.

**Không phải luật đã đăng ký, chỉ để chủ dự án thấy cỡ:** nếu bỏ riêng mục `n` ra ngoài, phía sau đạt 4/5 và có 3
bài từ trượt thành đạt (39, 40, 41). Con số này tính sau khi đã thấy kết quả, không dùng để quyết.

## Dự đoán

| Dự đoán | Kết quả |
|---|---|
| Trước: doc-39 trùng từng chữ lần đo #3 | **sai**: cùng lệnh tìm, cùng 3 572 token vào, trùng 525/674 ký tự đầu rồi đổi chữ ở câu hỏi lại. Fable nghi trước tiên thứ tự chạy (lần này doc-39 là bài 1/5, trước là bài 48/48); chưa kiểm. Không ảnh hưởng luật 2–5 vì hai phía cùng quy trình 5 bài |
| Trước: doc-40, 41, 43 không mở | **sai**: doc-40, 41 mở với phiếu cũ (doc-40 đoán `from_chunk=4`; doc-41 tìm kho hai lần rồi đọc 0–2) |
| Sau: doc-39 mở và đạt | **đúng** |
| Sau: ít nhất 2/3 bài xa mở | **đúng** (3/3) |
| Sau: doc-42 không mở, đạt | **sai**: mở, đọc 3 lần tới hết lượt, vẫn đủ ý, trượt vì `n` |
| Mỗi phía r1 = r2 | **đúng** |

## Chi phí của phiếu mới (r1; r2 trùng)

| Bài | Token vào cả bài: trước → sau | Độ trễ (ms): trước → sau | Lý do dừng sau |
|---|---|---|---|
| doc-39 | 3 572 → 5 158 | 11 363 → 9 596 | final |
| doc-40 | 5 024 → 10 223 | 4 873 → 7 845 | final |
| doc-41 | 8 298 → 15 929 | 9 417 → 9 903 | max_steps |
| doc-42 | 1 728 → 15 850 | 1 709 → 7 796 | max_steps |
| doc-43 | 1 693 → 5 240 | 2 646 → 5 220 | final |

Lượt model lớn nhất phía sau nhận 5 760 token, dưới một nửa khung 16k.

## Điều kiện đo

| | |
|---|---|
| Trước | worktree sạch tách tại `8bb58e1` (main sau khi gộp bài v0.5) |
| Sau | worktree sạch tách tại `c54e3eb` (`int/20-3b` = `8bb58e1` + gộp `--no-ff` `wip/20-paste-slip-b`) |
| Quy trình | `--tasks doc-39,doc-40,doc-41,doc-42,doc-43`; gỡ `qwen3.5:9b` trước mỗi lần, ghi `/api/ps` (`ollama_ps.jsonl`); t0, seed 42, `--probe`, `--gpu-shared no`; trước r1 15:08:44, r2 15:10:15, sau r1 15:11:10, r2 15:12:17 |
| GPU | không dùng chung: phiên Quản lý trả lúc 15:05; 43–49 °C lúc bắt đầu mỗi lần. Trước r1 chưa nạp `qwen3-embedding:0.6b` (0 MiB), ba lần sau có (1 782 MiB); trước r1 = r2 nên không gây lệch |
| Bảng điểm | không `--append-history`: lần đo 5 bài không phải lần đo đủ bộ (fable) |

## Tệp

`v0.5-3b-{before,after}-r{1,2}-cold/`: bốn tệp mỗi lần chạy, kèm `scorecard.json`. `analyze.py` tính lại
`analysis.json`; "lần tệ hơn" đọc theo hướng bất lợi cho đề xuất (đạt trước nếu một lần trước đạt; đạt sau chỉ khi cả
hai lần sau đạt).
