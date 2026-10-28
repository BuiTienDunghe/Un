GỘP ĐƯỢC

# Duyệt wip/20-eval-isolate c33dffc (runner gỡ model trước mỗi bài, cách 2 chủ dự án chọn) — fable 5.1, 28/10/2026

Đã kiểm: diff c336d6a..c33dffc, hai commit 42bbf51 + c33dffc (2 tệp: `scripts/agent_eval.py` +98, `tests/test_agent_eval.py`
+125). Bộ giữ im; **không gọi Ollama**, mọi kiểm bằng client giả. Tệp này không nói gì về code hai nhánh harness hay bài
mới ngoài những gì bản đăng ký đã công khai.

## Kiểm độc lập

| Kiểm | Kết quả |
|---|---|
| Thứ tự trước **mỗi** bài, kể cả bài đầu | `reload()` gọi ngay đầu vòng lặp bài, trước cả kiểm độ dài: POST `/api/generate` `{model, keep_alive: 0, stream: false}` → GET `/api/ps` tới khi không còn tên model (khớp cả `name:latest`) → POST `/api/generate` `{model, keep_alive, options, stream: false}` không prompt → chạy bài. Tôi chạy với client giả: ca model không nạp (1 lần hỏi `/api/ps`), ca còn nạp rồi biến mất sau 2 lần hỏi, ca không biến mất → `RuntimeError` "vẫn còn trong /api/ps" sau đúng số lần hỏi, không ghi bài nào |
| Options lúc nạp lại so với lúc chat (opus hỏi) | chat (`ModelRouter._ollama_options`) gửi `temperature`, `top_p`, `seed` + `num_ctx` = `config["context"]`; nạp lại gửi `{"num_ctx": general["context"]}` từ cùng mục cấu hình, cùng `keep_alive = str(config.get("keep_alive", "5m"))`. Trong các tham số đó chỉ `num_ctx` quyết định cách Ollama dựng runner, nên không có lần nạp thừa ở câu chat đầu |
| Bài `INPUT_TOO_LONG` (opus hỏi) | cũng gỡ rồi nạp (reload đứng trước kiểm độ dài): chỉ tốn thời gian, không sai |
| `--probe` so với lần gỡ đầu (opus hỏi) | probe chạy trước; bộ probe của registry chỉ đọc `/api/tags` và gọi `/api/embed` của model embedding, không có đường nào gọi model general. Dù có, lần gỡ trước bài đầu xoá sạch, nên dự đoán "trùng lần chạy riêng" không phụ thuộc điều này |
| `reload_ms` | chỉ đếm từ lúc bắt đầu POST nạp lại tới khi xong; `latency_ms` bắt đầu sau đó, không cộng; ghi vào từng dòng `task_results`, `None` khi không bật cờ |
| Manifest | luôn có `unload_between_tasks` (true/false); đúng điều kiện so của bản đăng ký |
| Cờ mặc định tắt | không cờ → `reloader = None`, đường chạy như cũ (test "builds a reloader only with the flag"); provider không phải Ollama → từ chối chạy, mã 2 (đúng, vì ticket 26 đang thêm provider khác) |
| Không đổi gì model thấy | `tools_sha256` `153209652c06…`, `AGENT_GUIDE` `6f80aa8ca420…`, bộ bài v0.7 `d87c4155eb3e…` — bằng main |
| Test | 145 xanh (`test_agent_eval*.py`); test giả Ollama kiểm thứ tự gỡ/hỏi/nạp theo từng bài, payload gỡ và nạp, manifest, `reload_ms`, ca treo dừng cả lần chạy |
| Worktree | sạch, HEAD c33dffc |

## Ghi chú, không chặn

- Gỡ một model đang **không** nạp: Ollama nạp rồi gỡ ngay (POST không prompt với `keep_alive: 0`), tức một lần nạp thừa
  không được đếm vào `reload_ms` (nó nằm ngoài đoạn đo). Chỉ xảy ra ở bài đầu mỗi lần chạy (sau `run_cold.sh`), vì từ bài
  thứ hai model luôn còn nạp (`keep_alive` 5m). Nếu muốn sạch: hỏi `/api/ps` trước, chỉ gỡ khi còn; không cần cho lần đo này.
- Phép kiểm thật của cả nhánh là hai dự đoán đã đăng ký: nền doc-41/doc-51 trùng lần chạy riêng, và +1 sáu bài không bật lời
  nhắc trùng nền từng byte. Opus đọc `reload_ms` bài đầu như đã nói, và đọc hai dự đoán đó trước khi đọc luật.
- Trần chờ 60 giây sau khi gỡ: hợp lý; gỡ bằng `keep_alive: 0` là tức thì, treo quá 60 giây là lỗi phía Ollama, dừng là đúng.
