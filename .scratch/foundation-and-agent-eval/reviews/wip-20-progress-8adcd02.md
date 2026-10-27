GỘP ĐƯỢC

# Duyệt wip/20-progress 8adcd02 (ticket 20 #4: hiện tiến độ lượt agent) — fable 5.1, 28/10/2026

Đã kiểm diff e252459..8adcd02 (11 tệp): `agent_service.py` (on_step/emit, label), `routers/chat.py`
(`_agent_stream`, luồng phụ, SSE lỗi), `chat_service.py` (chuyền on_step), gói Discord (`turn_progress.py`,
`_tracked`, endpoint, schema, `register_services`), `frontend/views/chat.js`, 15 test mới. Chạy không DB, Ollama/GPU
che: 168 test xanh (progress + registry + boundary + register + 9 bộ agent/chat/discord), 19 bỏ qua (DB);
`node --check chat.js` sạch. Không cần đăng ký đo: `tools_sha256` vẫn `153209652c06…` (nhãn không nằm trong
schema), lời dặn không đổi, on_step không chạm prompt; eval không truyền on_step.

## Điều tôi soi kỹ

| Điểm | Kết luận |
|---|---|
| Sự kiện không mang nội dung | `emit` chỉ ghi kind/round/label/tool/ok/stop_reason; `tool` = tên chỉ khi registry khai báo (tên model bịa → None + nhãn chung), cùng luật với bảng rút gọn 16. Test `events_carry_no_argument_result_or_answer` ghim. |
| Listener hỏng không đổi câu trả lời | `emit` nuốt mọi Exception; test ghim cả câu trả lời lẫn các bước. Đúng ưu tiên: hiện tiến độ không được tốn câu trả lời. |
| Luồng phụ + ContextVar + hạn giờ | `start_in_request_context` chạy `copy_context().run`; agent tự đặt `call_within` bên trong `run()` nên hạn giờ luôn ở đúng luồng (test: vòng công cụ ≤ 70 s, câu cuối ≤ 90 s, không rò sang luồng gọi); `consume_usage`/`record_usage` cũng ở luồng đó nên `request_logs` vẫn đọc đúng lần gọi cuối. NV1 nói thẳng: bỏ `copy_context` thì test hạn giờ vẫn xanh — đúng, và đó là dấu hiệu thiết kế đúng (hạn giờ không phụ thuộc ai gọi); `copy_context` giữ cho những gì request đã đặt trước (test riêng). Đồng ý. |
| Session DB | store mở session mỗi lần gọi; luồng phụ không chia sẻ session với request. Đúng. |
| Lỗi giữa chừng khi đã stream | `_stream_failure` dùng đúng mã của đường JSON và `log_request` ở đúng ba lỗi Ollama như đường JSON (tôi so với các `except` còn lại trong router); lỗi lạ → `INTERNAL_ERROR` + log có traceback. Khác biệt duy nhất, không tránh được: mã HTTP không đổi được sau khi stream đã mở. |
| Client bỏ đi giữa chừng | generator dừng, luồng phụ chạy tiếp và lưu như đường JSON; queue không ai đọc chỉ chứa ≤ vài chục sự kiện nhỏ. Chấp nhận. |
| Kho tiến độ Discord (P-a) | dict + Lock, dọn theo trần 600 s ở mỗi lần ghi/đọc, `finish` trong `finally` của `_tracked`; không có kho thì không truyền từ khoá → chat_service giả cũ vẫn chạy. Endpoint chỉ đọc bộ nhớ, dưới guard của router mà bot đang dùng. Giả định một tiến trình uvicorn được ghi rõ; nếu sau này chạy nhiều worker thì bot chỉ thấy `running=False` — xuống cấp êm, không sai. |
| Frontend | `setProgress` đặt `textContent`, không HTML. Đúng. |
| `declared = registry.get(name) is not None` | tương đương `name in names()`, rẻ hơn. |

## Hai ghi chú, không chặn

- `TurnProgress.steps` đếm mọi sự kiện kể cả "thinking", không phải số bước trace; tên trường dễ hiểu nhầm với
  `agent_steps`. Khi bot hiển thị (D1–D3, chờ chủ dự án) nên gọi nó là "events" hoặc ghi chú trong schema.
- Nhãn tiếng Việt nằm trong code service (`THINKING_LABEL`…): chấp nhận cho sản phẩm một ngôn ngữ; nếu có lúc
  cần tiếng Anh thì chuyển sang `label_key` + bảng dịch ở client — không làm bây giờ.

## Việc cho opus

Gộp được; không cần đo. Phần bot hiển thị (D1/D2/D3) là quyết định của chủ dự án, ngoài phạm vi commit này.
