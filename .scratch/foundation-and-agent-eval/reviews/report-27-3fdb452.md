ĐÚNG SỐ (báo cáo khớp dữ liệu thô ở mọi con số tôi tính lại; đạt cả bốn điều đúng luật đã đăng ký; bảng so phiếu #3 / #3-C đúng và được ghi đúng là ngoài luật)

# Duyệt báo cáo ticket 27 — `kept/agent-eval-v0.7-tool-call-parse/REPORT.md`, commit 3fdb452 — fable 5.1, 29/10/2026

Tính lại từ `task_results.jsonl` + `events.jsonl` + `manifest.json` của 6 lần chạy `v0.7-27-*` và từ `v0.7-3d-iso-base-full`
của #3-D, bằng script riêng; đối chiếu với bản đăng ký 26616b3.

| Mục báo cáo | Tính lại | Khớp |
|---|---|---|
| Điều kiện: ba băm bằng nhau ở 6 lần, `tools` `153209…a75e500`, bộ bài `d87c4155eb3e…`, cờ cô lập, `tasks_run` `["doc-44"]` ×4 và 62 ×2, worktree sạch; commit 2839b52 / 48b5c0f / 53b1e80 / a2b7bde | đúng cả 6 manifest | ✓ |
| Điều 2: trước, doc-44 mất lượt cả hai lần | `error` = "OllamaUnavailableError: Cannot connect to Ollama", không bước nào, cả r1 và r2 | ✓ |
| Điều 3: sau, cả hai lần: không `error`, bước `tool_call_error` mã `TOOL_CALL_PARSE`, câu trả lời không rỗng | đúng; chuỗi bước r1 = r2: `tool_call_error` → `unread_paste` (`asks_for_paste`) → `read_document(0, 3)` → `final` (`stop_reason: final`) | ✓ |
| Thử lại viết được lệnh đúng, không đi đường ép | `stop_reason` là `final`, có `read_document` sau bước sửa | ✓ |
| doc-44 sau sửa trượt `must_mention`, nêu "Bản Nậm Sương", không có "Đá Vàng" | đúng; đọc 0–2, đáp án ở đoạn 4 | ✓ |
| Điều 4: M1 so M0 62/62 giống hệt, không bài nào bật bước sửa; cả hai 45/62; không bài nào mất lượt | đúng từng số | ✓ |
| Bảng ngoài luật: phiếu #3 (M0) so phiếu #3-C (`v0.7-3d-iso-base-full`): 62 bài 45 / 50; 15 bài dán 5 / 10; 6 bài mới 3 / 4; 0 bài đạt → trượt; 47 bài không dán giống hệt | đúng; trượt → đạt: doc-39, 41, 43, 46, 48; tập bài đạt của #3: 42, 45, 51, 52, 53 | ✓ |
| Hai lần chạy làm bảng đó chỉ khác ở lời phiếu | `git diff 94e321f 26616b3 -- backend/app` chỉ `pastes.py` (đã kiểm ở bài duyệt bản đăng ký) | ✓ |

## Nhận xét

- **Kết luận đúng luật: đề xuất gộp ticket 27 đứng được.** Bản sửa làm đúng việc trên ca hỏng thật (thử lại viết được lệnh
  đúng) và không đổi một byte nào ở 62 bài trên main.
- **Bảng phiếu #3 / #3-C là bằng chứng sạch, chỉ thiếu chữ "đăng ký trước".** Hai lần chạy đều cô lập, cùng bộ bài, cùng thứ
  tự, chỉ khác lời phiếu; so từng bài là hợp lệ. Kết quả: +5 bài trượt → đạt, 0 bài đạt → trượt, 47 bài khác trùng nguyên. Nếu
  chủ dự án muốn giữ đúng kỷ luật "đăng ký trước rồi đo", một lần đo E đăng ký lại sẽ cho đúng các số này (cô lập là lặp
  lại được), tức tốn ~20 phút GPU cho một con dấu. Đó là lựa chọn của chủ dự án; tôi chỉ nói rõ cái giá.
- doc-44 sau sửa cho thấy chuỗi "lỗi cú pháp → thử lại → nhờ dán lại → nhắc đoạn dán → đọc" chạy đúng thứ tự thiết kế, dù
  câu trả lời cuối vẫn sai vì đọc chưa tới đoạn 4. Đây là ca trần đọc, không phải lỗi của ticket 27.
