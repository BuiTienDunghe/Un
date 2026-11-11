# Agent Eval — bộ bài v0-discord-chat

**Bài hồi quy do dự án tự viết, không phải benchmark chất lượng.** Đạt bộ này chỉ nói rằng Ún không tụt ở các tình huống đã viết ra; nó không chứng minh Ún trò chuyện tốt.

Bộ này hỏi một việc: trong một cuộc trò chuyện Discord đang diễn ra, Ún có để yên công cụ khi người ta chỉ chào, cảm ơn, tán gẫu, hỏi ý kiến, hỏi tiếp câu vừa rồi hay hỏi kiến thức phổ thông không. Bảy bài cần gọi công cụ được kèm vào để không thể qua bộ này bằng cách không bao giờ gọi; ba bài trong đó hỏi bằng giọng trò chuyện, không nhờ thẳng "tra giúp".

Cùng runner, bộ chấm và cấu trúc tệp với `../v0/` (xem `../v0/README.md`); không có bài nào của v0, nên băm của v0 không đổi.

```
cd backend
python -m scripts.agent_eval --dataset ../data/benchmarks/agent_eval/v0-discord-chat --temperature 0 --seed 42 --unload-between-tasks
python -m scripts.agent_eval --dataset ../data/benchmarks/agent_eval/v0-discord-chat --temperature 0 --seed 42 --unload-between-tasks --clock-note --discord-persona
```

## Các bài

| Nhóm | Bài | Số bài | Tiêu chí |
|---|---|---:|---|
| Không được gọi | `nt-d01` … `nt-d18` | 18 | `tools_forbidden: ["*"]`; một số bài thêm `must_mention` |
| Cần gọi, nhờ thẳng | `hist-d01`, `hist-d02` | 2 | `search_history`; đáp án ở tin cũ của server, không ở cuộc trò chuyện |
| Cần gọi, giọng trò chuyện | `hist-d03`, `hist-d04`, `hist-d05` | 3 | `search_history`; hỏi bâng quơ ("mà hồi trước…", "ủa mà…"), đáp án vẫn chỉ có ở tin cũ của server |
| Cần gọi, nhờ thẳng | `stat-d01` | 1 | `system_status` |
| Cần gọi, nhờ thẳng | `doc-d01` | 1 | `search_documents`; đoạn tài liệu viết tay |

Một chính sách "không bao giờ gọi" đạt nhiều nhất 18/25 (vẫn là phần lớn bộ, nên chỉ điểm tổng thì không đủ); một chính sách "luôn gọi" đạt nhiều nhất 7/25. Hai nhóm luôn được báo riêng.

| Loại tình huống không được gọi | Bài |
|---|---|
| Chào, cảm ơn, tạm biệt | nt-d01, nt-d02, nt-d16 |
| Tán gẫu, than thở | nt-d03, nt-d12, nt-d13, nt-d17 |
| Hỏi ý kiến | nt-d04, nt-d18 |
| Hỏi tiếp câu trả lời vừa rồi | nt-d05, nt-d15 |
| Điều đã nói trong cuộc trò chuyện | nt-d09 |
| Kiến thức phổ thông | nt-d06, nt-d07, nt-d08 |
| Viết, dịch ngắn | nt-d10, nt-d11 |
| Hỏi về chính bot | nt-d14 |

## Khác v0 ở đâu

- Mọi bài đều là `surface: discord` và có `history`.
- Lượt user trong `history` mang `speaker: {name, author_id}`. Runner gắn nhãn người nói cho lượt đó bằng chính hàm của sản phẩm (`build_discord_speaker_context`), như turn service làm với các lượt trước. Lượt không có `speaker` (mọi bài v0) đi qua nguyên vẹn.
- `guild` có thêm `name`: tên server trong dòng giới thiệu mà bot gửi khi chạy `--discord-persona`.
- Server giả riêng (`900000000000000002`, 8 tin, 4 thành viên Vy 2001, Khoa 2002, Thảo 2003, Đạt 2004 và bot 2999), không dùng chung tin nào với v0.

## Điều cần biết khi đọc kết quả

- **Trượt `tools_forbidden` có hai nguyên nhân khác nhau, phải đếm riêng.** Một là model **tự gọi**: lượt gọi do model viết, và trước nó trong cùng bài không có bước nào harness trả lượt về. Hai là **gọi sau khi harness trả về**: trước lượt gọi có ít nhất một bước `answer_check` (câu trả lời có con số lượt đó chưa thấy ở đâu), `lookup_check` (câu trả lời nói "mình không biết / chưa rõ" khi chưa tra gì; đang bật trong `models.yaml`), `read_on_check`, `promise_check` hoặc `read_rest`. Lượt gọi do code tự làm (`by_code`, `constrained`) không thuộc loại nào. Lệnh gọi model viết mà Ollama không phân tích được (bước `tool_call_error`) được tính như một lượt gọi của model và liệt kê riêng. Đếm bằng `backend/scripts/count_self_chosen.py`, đọc `events.jsonl`; không đếm bằng tay.
- Bài dễ bị trả về: `nt-d08` (đáp án có số 100), `nt-d05` (ví dụ đệ quy), `nt-d13` (tốc độ chạy), và mọi bài mà một câu trả lời tự nhiên có thể là "mình không rõ…" (`nt-d03`, `nt-d09`, `nt-d14`). `nt-d09` có số nhưng số nằm sẵn trong lịch sử.
- `nt-d12` có chữ "hôm nay" và `nt-d17` có chữ "server": cố ý, để bắt việc gọi `current_time` hoặc `system_status` theo từ khoá. Không bài nào có đáp án phụ thuộc ngày thật.
- Không bài nào hoặc tin nào dùng ngày tương đối ("tuần này", "tối nay") cho điều cần trả lời: khi bật `--clock-note`, đồng hồ thật khác `guild.now`.
- `doc-d01` không chấm trích nguồn, để bài chỉ đo quyết định gọi.
- Không có bài nào cần công cụ mà bộ đo không có (nhắc việc, ghi nhớ, kho câu đùa, web).

## Giới hạn

- 18 + 7 bài là mẫu nhỏ; chênh 2–3 bài giữa hai lần chạy chưa nói được gì.
- Ba bài giọng trò chuyện (`hist-d03..05`) dùng chữ chỉ thời gian mơ hồ ("hồi trước", "bữa đó"); không bài nào cần biết ngày thật.
- `tools_forbidden: ["*"]` chỉ chấm việc gọi, không chấm câu trả lời có tự nhiên hay đúng vai không.
- Người viết đã đọc các lần đo 08–10/11 của 9B và 2B trước khi viết. Bài được viết theo ý định sản phẩm (không tra khi chỉ trò chuyện), không theo vết của model nào, nhưng không thể cam đoan hoàn toàn độc lập.
- Viết ngày 11/11/2026, khi không được phép chạy gì: lúc viết, bộ này chưa từng được nạp bằng `load_dataset` hay chạy qua model. Test `test_the_discord_chat_set_loads_and_cannot_be_passed_by_never_calling_a_tool` kiểm việc nạp và tiêu chí.

## Lịch sử tiêu chí

| Ngày | Thay đổi |
|---|---|
| 11/11/2026 | `agent-eval-v0-discord-chat.1`: 22 bài, viết trước mọi lần chạy |
| 11/11/2026 | Vẫn `.1`, vẫn trước mọi lần chạy (chưa có số nào mang phiên bản này): thêm `hist-d03..05` theo bản duyệt của Opus 5.5, để "không bao giờ gọi" không qua được phần lớn bộ; định nghĩa "tự gọi" loại thêm `lookup_check`, `read_on_check`, `promise_check`, `read_rest` |
