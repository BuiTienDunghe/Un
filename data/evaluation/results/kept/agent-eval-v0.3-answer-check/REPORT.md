# Agent Eval v0.3 — #2 kiểm con số trong câu trả lời (28/10/2026, 08:00–08:07)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm công bố.
Cách đo và luật quyết định được đăng ký trước khi chạy (`PREREGISTRATION.md`, 01:03). Chạy trong đợt A+B chủ dự án
duyệt lúc 07:58 (`joint-measurement-plan.md`).

## Thật ra chuyện này là gì

Trước khi gửi câu trả lời, agent so các con số trong đó với những gì nó đã thấy trong lượt. Gặp số không rõ nguồn,
nó tự làm lại một lần và được tra cứu. Ở bài hay bịa nhất (hỏi mức phụ cấp), lần làm lại đi tra tài liệu thật và
trả lời đúng. Mọi bài khác giữ nguyên từng chữ. Theo luật đặt trước, #2 đủ điều kiện giữ. Có một điểm xấu ngoài
luật: ở bài thứ hai, lần làm lại không tra mà viết thẳng cho người dùng rằng mình "cần điều chỉnh lại câu trả lời",
tức là để lộ việc kiểm ra ngoài.

## Kết quả (r1 = r2 từng chữ)

| | Tổng /48 | 40 bài cũ | 5 bài đọc dài |
|---|---:|---:|---:|
| #1-B (`2d4a830`, đã lưu) | 38 | 33 | 4 |
| **#2 (`86c419c`)** | **39** | **34** | **4** |

| Dự đoán đăng ký trước | Kết quả |
|---|---|
| 46/48 câu trùng #1-B từng chữ; chỉ doc-10, doc-22 đổi | **đúng** |
| Không bài đạt nào thành trượt | **đúng** (0 bài) |
| doc-10: câu cuối không còn số không nguồn | **đúng** (6 → 0) |
| doc-10, doc-22 mỗi bài đúng một bước `answer_check` | **đúng** |
| r1 trùng r2 | **đúng** |

**Luật:** không bài đạt nào thành trượt VÀ doc-10 hết số không nguồn → **đề xuất giữ #2** (code đã trên main).

## Hai bài bị bắt

| Bài | Lần đầu | Lần làm lại | Kết quả | Thêm thời gian |
|---|---|---|---|---:|
| doc-10 (mức phụ cấp) | không tra, 6 số không nguồn | gọi `search_documents`, trích 2 tệp, 0 số không nguồn | trượt → **đạt** | +5,1 s |
| doc-22 (đổi Postgres sang SQLite) | không tra, 1 số không nguồn (140) | **không gọi công cụ**, câu cuối vẫn 1 số không nguồn | trượt → trượt | +4,7 s |

Câu cuối của doc-22 mở đầu bằng "Tuy nhiên, tôi cần điều chỉnh lại câu trả lời: Không có con số 140TB trong câu hỏi
hay ngữ cảnh…". Người dùng đọc được lời model tự sửa mình. Luật không xét điều này; ghi lại để chủ dự án quyết có sửa
câu nhắc làm lại (`retry_instruction`) hay không.

## Ghi lại, không quyết

- K1 (`grounding`, chỉ ghi trace) trên 37 câu cuối có tra: grounded 15, weak 8, ungrounded 14. Tỉ lệ ungrounded cao
  như vậy chưa được đối chiếu tay, nên chưa nói được K1 đúng hay sai.
- Điểm mù đã biết của bộ kiểm (số tự tính, số viết bằng chữ, số thập phân ngắn, câu bịa không có số) không đổi.

## Điều kiện đo

| | |
|---|---|
| Code | worktree sạch tách tại `86c419c` (`worktree_dirty: false`, `verified: true`) |
| Băm | `tools_sha256`, `agent_guide_sha256`, `system_prompt_sha256` bằng #1-B |
| Quy trình | gỡ `qwen3.5:9b` qua API trước mỗi lần, ghi `/api/ps` (`ollama_ps.jsonl`); t0, seed 42, `--probe`; r1 08:00:14, r2 08:03:56 |
| GPU | không dùng chung: phiên Quản lý xác nhận bên đó không dùng GPU lúc 08:05–08:45; r1 bắt đầu trên GPU trống (0 MiB). r2: `qwen3-embedding:0.6b` còn nạp (1 782 MiB) |
| Lỗi | doc-39 bị từ chối `INPUT_TOO_LONG` ở cả hai lần, như #1-B (#3 chưa có ở commit này); runner thoát mã 1 vì lỗi đó |

## Tệp

`v0.3-check-r{1,2}-cold/`: bốn tệp mỗi lần chạy. `analyze.py` tính lại `analysis.json` từ các thư mục kept/.
