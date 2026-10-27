# 16 — Kiểm soát harness: ngân sách cả lượt, lỗi công cụ có mã, trace bền (M4, cách B)

Status: đang thiết kế — chờ khảo sát harness nổi tiếng (nguồn chính thống); code sau khi 10 gộp
Type: task
Blocked by: 10 (cùng đụng `backend/app/services/agent_service.py`; đổi harness giữa chừng làm bẩn phép đo của 10)

## Vì sao

Chủ dự án chọn cách B (27/10): ba tiêu chí nghiệm thu của họ ở Mốc 4 — quản lý tài nguyên, tracing,
khả năng phục hồi — không bao giờ hiện thành lỗi trong Agent Eval (bài thi không thử treo hay xoá), nên
"chỉ làm khi lỗi đo được chỉ ra" sẽ không bao giờ tới chúng. Registry công cụ **chỉ khi có công cụ thứ 4**.

Bằng chứng đã có (kiểm code 27/10):

| Điều | Bằng chứng |
|---|---|
| Không có ngân sách thời gian cho cả lượt | `agent_service.py` không có timeout; chỉ `max_steps` 3 và mỗi lần gọi model chờ tối đa `ollama_chat_timeout_seconds` 120 s (`settings.py:173`) → một câu trả lời có thể ~8 phút |
| Lỗi công cụ là chuỗi tự do | `_execute_tool` (`agent_service.py:203`) trả `{"error": "..."}`; hist-10 ở t0.4 hỏi lại "server nào?" thay vì nói rõ công cụ không dùng được ở web |
| Trace chết cùng hội thoại | `agent_traces.conversation_id` `ondelete="CASCADE"` (`models.py:1079`); chú thích `models.py:1104` ghi bảng có 0 dòng. Cả web (`chat_service.py:155`) lẫn Discord (qua `respond_with_context`) đều ghi vào bảng này |

## Câu hỏi thiết kế phải trả lời trước khi code

1. **Ngân sách**: thời gian tường cho cả lượt (bao nhiêu? cấu hình ở đâu — `models.yaml` mục `agent`?);
   có cần ngân sách token không; khi chạm thì làm gì (trả lời từ những gì đã có, như nhánh "Tool budget
   exhausted" hiện tại, hay báo lỗi rõ).
2. **Lỗi có mã**: bộ mã nhỏ (vd `TOOL_UNAVAILABLE_HERE`, `TOOL_FAILED`, `TOOL_TIMEOUT`, `BAD_ARGUMENTS`),
   phần nào cho model đọc, phần nào ghi vào trace; có thử lại không.
3. **Trace bền — và quyền riêng tư**: chú thích `models.py:1069-1071` ghi đây là thiết kế có chủ đích
   ("a trace never outlives the answer it explains"). Trace chứa tham số công cụ (câu hỏi của người dùng)
   và kết quả (đoạn tài liệu, tin Discord). Giữ nguyên văn sau khi người dùng xoá hội thoại là giữ dữ liệu
   cá nhân trái ý họ. Phải chọn giữa: (a) giữ trọn; (b) giữ bản rút gọn không có nội dung (tên công cụ,
   số bước, độ trễ, mã lỗi, token, hash) và xoá nội dung theo hội thoại; (c) giữ trọn có thời hạn. Đối
   chiếu với khuyến nghị của các harness và OpenTelemetry GenAI về việc ghi nội dung.
4. **Registry**: không làm (chưa có công cụ thứ 4); ghi điều kiện mở lại.

## Khảo sát harness (nguồn chính thống)

(điền khi khảo sát xong)

## Nghiệm thu

- Test tất định cho từng cơ chế: chạm ngân sách → kết quả kiểm soát được; mỗi mã lỗi; trace còn sau khi
  xoá hội thoại đúng theo phương án đã chọn.
- Agent Eval v0.2: không suy giảm so với mốc của ticket 10 (một lần khởi động bỏ đi mỗi phía).

## Comments
