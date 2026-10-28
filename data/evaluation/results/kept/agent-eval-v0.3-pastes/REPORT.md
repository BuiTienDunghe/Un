# Agent Eval v0.3 — #3 đoạn dán dài (28/10/2026, 08:07–08:14)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm công bố.
Cách đo và luật quyết định được đăng ký trước khi chạy (`PREREGISTRATION.md`, 01:17). Chạy trong đợt A+B chủ dự án
duyệt lúc 07:58, ngay sau lần đo #2.

## Thật ra chuyện này là gì

Trước #3, một tin nhắn quá dài bị từ chối trước khi agent kịp đọc. Giờ nó tới được agent dưới dạng một tờ phiếu:
phần đầu, phần cuối, và lời chỉ cách mở phần giữa. Phần đó chạy đúng, và không làm xáo bài nào khác. Nhưng ở bài
duy nhất có đoạn dán dài, đáp án nằm ở phần giữa, và agent không mở nó ra. Nó tìm trong kho tài liệu (nơi đoạn dán
không nằm), không thấy, rồi hỏi người dùng có muốn nó đọc toàn bộ văn bản không. Theo luật đặt trước, #3 **chưa đủ
điều kiện đề xuất giữ**.

## Kết quả (r1 = r2 từng chữ)

| | Tổng /48 | doc-39 |
|---|---:|---|
| #2 (`86c419c`) | 39 | bị từ chối `INPUT_TOO_LONG` (10 164 > 10 000) |
| **#3 (`80cd369`)** | **39** | tới agent, 2 lượt model, trượt `must_mention` |

| Điều kiện của luật | Kết quả |
|---|---|
| 47 bài còn lại trùng #2 từng chữ | **đúng** (47/47) |
| doc-39 tới được agent | **đúng** (không lỗi, 2 lượt model) |
| doc-39 gọi `read_document` trên đoạn dán | **sai**: 0 lần gọi `read_document` |

**Luật: một điều kiện sai → không đề xuất giữ; báo kèm câu trả lời, không tự sửa tiếp.** Code #3 đã nằm trên main
(gộp 80cd369 lúc 01:30), nên giữ hay sửa hay lùi là việc chủ dự án quyết.

## doc-39 làm gì

1. Gọi `search_documents("hạn chót nộp hồ sơ dự thầu gói hộp giấy Minh Phát ai phụ trách")` → "không tìm thấy đoạn
   tài liệu nào phù hợp". Đúng như mong đợi, vì đoạn dán không nằm trong kho.
2. Trả lời, mở đầu: "Tôi đã tìm kiếm trong văn bản nhưng không tìm thấy thông tin cụ thể…". Kết thúc: "Bạn có muốn
   tôi đọc toàn bộ văn bản để tìm thông tin chi tiết hơn không?"

Agent nói "tìm kiếm trong văn bản", tức là nó tưởng công cụ tìm tài liệu cũng tìm trong đoạn dán. Phiếu viết "Văn
bản đã được lưu thành **tài liệu tạm**", và có thể chính chữ "tài liệu" làm model nghĩ vậy. Đây là giả thuyết, chưa
kiểm. Model dừng sau 2 lượt (khoảng 5 giây), còn dư 2 lượt công cụ và gần trọn ngân sách 90 giây, nên lỗi không phải do
hết lượt.

`tokens_in` cả bài: 3 572 (lượt lớn nhất 1 868), thay cho một tin 10 164 ký tự bị từ chối ở #2.

## Các cách đi tiếp (chủ dự án chọn)

| Cách | Ưu | Nhược |
|---|---|---|
| Giữ #3 như hiện tại | đoạn dán dài không còn bị từ chối; 47 bài không đổi | tính năng chính (đọc phần giữa) không được dùng ở bài duy nhất đo được |
| Sửa lời trong phiếu: bỏ chữ "tài liệu", dặn "tìm kiếm tài liệu không thấy đoạn dán; đọc bằng read_document trước khi trả lời" | phiếu chỉ xuất hiện ở tin dài, nên không đổi prompt của 47 bài kia (khác với sửa lời dặn chung, vốn từng xáo 37–39/40 câu) | chỉ có một bài để đo, dễ sửa khớp riêng doc-39; cần đăng ký trước và đo lại (~7 phút) |
| Harness tự đọc: khi có đoạn dán, chọn sẵn đoạn khớp câu hỏi và đưa vào phiếu | không phụ thuộc model có chọn đúng công cụ không | thêm code; câu hỏi nằm giữa đoạn dán thì khó bắt; cần thiết kế và duyệt |
| Lùi #3 | về đúng hành vi cũ | mất khả năng nhận đoạn dán dài 10 000–100 000 ký tự |

Ý kiến của opus, không phải quyết định: nghiêng về sửa lời trong phiếu, kèm thêm vài bài đoạn dán vào bộ bài trước
khi đo, để không sửa khớp một bài.

## Điều kiện đo

| | |
|---|---|
| Code | worktree sạch tách tại `80cd369` (`worktree_dirty: false`, `verified: true`) |
| Băm | `tools_sha256`, `agent_guide_sha256`, `system_prompt_sha256` bằng lần đo #2; `input_max_chars.web` 10 000 → 100 000 |
| Quy trình | gỡ `qwen3.5:9b` trước mỗi lần, ghi `/api/ps` (`ollama_ps.jsonl`); t0, seed 42, `--probe`; r1 08:07:29, r2 08:11:02 |
| GPU | không dùng chung (phiên Quản lý xác nhận); `qwen3-embedding:0.6b` còn nạp ở cả hai lần |
| Khác `80cd369` so với `86c419c` | ngoài #3 còn có ticket 22 C1–C3 (`d1711e7`); ba băm bằng nhau và 47 câu trùng từng chữ, nên C1–C3 không đổi những gì model thấy |

## Tệp

`v0.3-paste-r{1,2}-cold/`: bốn tệp mỗi lần chạy. `analyze.py` tính lại `analysis.json` từ các thư mục kept/.
