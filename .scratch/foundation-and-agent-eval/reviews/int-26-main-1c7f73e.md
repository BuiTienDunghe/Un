GỘP ĐƯỢC (merge sạch, chỉ dời mục CHANGELOG; code ticket 26 đúng API Claude hiện hành; bản ghi Haiku nằm sau v0 nên không tự phục vụ; chủ dự án đã chọn "gộp nhưng chưa bật")

# Duyệt int/26-main 1c7f73e (merge --no-ff wip/26-anthropic-provider 22ccbc0 lên main dcdb3e7) — fable 5.1, 30/10/2026

Đây là lần duyệt code ticket 26 đầu tiên (22ccbc0 chưa có bài duyệt riêng), nên tôi đọc trọn `anthropic_client.py` (341 dòng),
diff `model_router.py`, `model_registry.py`, `settings.py`, `main.py`, `model_versions.yaml`, `requirements.txt`,
`.env.example`, và đối chiếu với tài liệu API Claude hiện hành (skill claude-api). Không gọi API thật.

## Merge

| Kiểm | Kết quả |
|---|---|
| 1c7f73e so với merge tự động của hai cha (`git merge-tree dcdb3e7 22ccbc0`) | chỉ khác `CHANGELOG.md`: mục ticket 26 dời từ [1.4.0] sang [Unreleased], nội dung giữ nguyên |
| Diff nhánh so với merge-base d6c5886 | 15 tệp, +839 −15: client mới + 3 tệp test, phần còn lại là nối provider và tài liệu |
| Test ở worktree `int-26-main` (sạch, HEAD 1c7f73e) | `test_anthropic_client` + `test_model_router` + `test_model_registry` + `test_agent_service` + `test_agent_pastes`: 152 xanh, 9 bỏ qua; bộ rộng hơn theo opus 981 xanh, 2 đỏ `/health` do thiếu Redis, đỏ y hệt trên main — tôi không chạy lại bộ rộng |

## Code so với API Claude hiện hành

| Điểm | Code | Tài liệu API | Khớp |
|---|---|---|---|
| Model | `claude-haiku-5-5`, `max_tokens: 4096` (bắt buộc), `effort: low` qua `output_config` | đúng id; Haiku 5.5 nhận `effort` low–max; `output_config` là chỗ đúng | ✓ |
| Không gửi `temperature`/`top_p` | `_anthropic_kwargs` lọc bỏ cả khi config hay caller nêu | Haiku 5.5: giá trị khác mặc định bị 400 | ✓ |
| Tin `system` giữa hội thoại (lời "trả lời ngay" / thử lại của agent) | giữ `role: system` khi đứng sau `user` và là tin cuối hoặc trước `assistant`; chỗ khác gập vào `user` | đúng ba luật đặt tin system giữa hội thoại; Haiku 5.5 nằm trong danh sách model hỗ trợ, không cần beta | ✓ |
| `cache_control` ở cấp request | `kwargs["cache_control"] = {"type": "ephemeral"}` trong `chat_tools` | "automatic caching" ở cấp request là hợp lệ | ✓ |
| `stop_reason == "refusal"` | ném `AnthropicRefusalError` kèm `stop_details.category`, không thử lại | đúng; Haiku 5.5 không có fallback phía server | ✓ |
| `max_tokens` chạm trần | giữ văn bản, ghi log `anthropic_max_tokens` | giống cách Ollama; chấp nhận | ✓ |
| Replay `tool_use` | `raw_tool_calls` = nguyên content (kể cả khối thinking) phát lại y nguyên; kết quả công cụ liên tiếp gộp vào một tin `user` | đúng yêu cầu "thinking block pass back unchanged" và "mọi tool_result trong một tin" | ✓ |
| Thử lại | SDK `max_retries=0`, vòng tự viết theo khuôn Gemini, mọi lần chờ đều dưới hạn 90 s của lượt (`deadline.py`); 4xx khác 429 không thử lại | đúng chuỗi except từ hẹp tới rộng | ✓ |
| Khoá API | chỉ đi vào `anthropic.Anthropic(api_key=…)`; không log, không vào thông điệp lỗi | — | ✓ |
| Registry | `anthropic` vào `PROVIDERS` và `CLOUD_PROVIDERS`; probe = "đã đăng ký khoá"; `general-haiku-v1` đứng SAU `general-v0` nên không tự phục vụ; pin bằng `MODEL_VERSION_GENERAL` trong shell | đúng invariant "ứng viên sau active" của registry | ✓ |

## Nhận xét

- **Đúng thứ chủ dự án chọn: có trong code, không bật.** Không có khoá thì provider không đăng ký, bản ghi Haiku bị bỏ qua, mọi
  thứ chạy như hôm qua. Có khoá mà không pin thì cũng vậy.
- `general-haiku-v1` không có `context`: với N1 hiện tại hằng 12 288 là số cứng nên không sao; ticket 28 (#4) đọc `context` từ
  config và quay về 12 288 khi thiếu, nên cũng không sao. Cửa sổ thật của Haiku 5.5 là 1M, tức N1 có thể nạp nhiều hơn rất
  nhiều khi dùng Claude; đó là việc tinh chỉnh sau, không chặn.
- Chưa có số đo nào cho Haiku trên Agent Eval (bản ghi `d1_multidoc: null`, đúng như invariant #4 đòi trước khi promote).
- Nhỏ: `requirements.txt` pin `anthropic>=2.3,<3.0`; SDK 2.x dùng `httpx2` song song `httpx`, đã ghi chú.
