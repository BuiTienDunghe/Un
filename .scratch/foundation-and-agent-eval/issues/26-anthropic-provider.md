# 26 — Claude (Anthropic) làm lựa chọn thứ hai cho vai trò `general`

Status: code xong trên `wip/26-anthropic-provider`, chờ chủ dự án duyệt và quyết định promote
Type: task
Blocked by: —

## Bản chất

Hệ đã có ổ cắm cho model đám mây (Gemini, DeepSeek) nhưng chỉ ở đường chat thường; chế độ công
cụ của agent, tức mọi lượt Discord, chỉ chạy với Ollama. Ticket này cắm Claude vào đúng ổ đó và
dạy ổ cắm nói chuyện với chế độ công cụ, để Haiku 5.5 đứng đúng chỗ Qwen 9B đang đứng ở mọi
đường: chat, RAG, viết lại câu hỏi, lượt công cụ, sinh ngữ cảnh đoạn lúc nạp tài liệu.

## Quyết định đã chốt (28/10, chủ dự án)

| Câu hỏi | Chốt | Vì sao |
|---|---|---|
| Model | `claude-haiku-5-5` | chủ dự án chọn |
| Phạm vi | toàn vai trò `general`, kể cả lượt công cụ; không tách vai trò nạp tài liệu | "vai trò tương đương Qwen 9B" |
| Cách chọn | registry: bản ghi `general-haiku-v1` SAU v0, pin shell `MODEL_VERSION_GENERAL` để thử, đổi `active` để ship | đúng hợp đồng ADR 0001; v0 là đường lùi tự động về máy; Claude không bao giờ tự phục vụ |
| Thư viện | SDK `anthropic` 2.x, retry của SDK tắt, vòng retry riêng theo deadline ticket 16 | tool-use + stream + thinking nhiều bề mặt hơn Gemini chỉ-text |
| Núm sinh | `effort: low`, `max_tokens: 4096`, không temperature/top_p | Claude 5.x từ chối temperature/top_p; Qwen chạy think: false |

## Lớp dịch cho lượt công cụ (`anthropic_client.convert_messages`)

- system đầu → `system` cấp cao; system giữa cuộc → giữ vai system khi đứng sau user và là cuối
  (hoặc trước assistant), còn lại gấp vào user.
- assistant có `tool_calls` là khối Anthropic (`raw_tool_calls` trả về) → phát lại NGUYÊN VĂN, kể cả
  khối thinking; `tool_calls` kiểu Ollama → dựng `tool_use` với id mới.
- `{"role": "tool"}` → `tool_result` khớp id theo tên rồi theo thứ tự; nhiều kết quả liền nhau nằm
  chung một tin user.
- `cache_control` ở lượt công cụ: vòng 2 đọc lại tiền tố vòng 1 từ cache.

## Cách thử trên máy này

```
set MODEL_VERSION_GENERAL=general-haiku-v1   (shell, không .env)
run-local-ai-core.bat
```
`/models.registry` phải ghi general = general-haiku-v1, source pin; `/health.model_fallback` lệch
pointer nên nightly sẽ từ chối chấm — đúng thiết kế.

## Điều kiện promote (đổi `active`)

1. Chạy D1 multidoc dưới Haiku, điền `eval.reports.d1_multidoc` (invariant #4; `--check` từ chối
   active không có báo cáo).
2. Agent Eval v0.6 dưới Haiku để so với mốc Qwen 39/48.
3. Đo lại `vram_mib` của extractor-v0: nó đang ghi 0 vì dùng chung tag với general-v0.
4. Quyết định riêng tư: mọi câu hỏi, lịch sử Discord, và toàn văn tài liệu lúc nạp sẽ rời máy.

## Chưa làm / nợ

- Router chat vẫn chỉ map lỗi Ollama ra mã 502/504; lỗi Claude (và Gemini/DeepSeek từ trước) ra 500
  INTERNAL_ERROR. Nợ chung của mọi provider đám mây, chưa thuộc ticket này.
- `strict: true` cho schema công cụ chưa bật.
