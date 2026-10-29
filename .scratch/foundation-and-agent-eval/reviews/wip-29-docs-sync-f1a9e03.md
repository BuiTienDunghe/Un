GỘP ĐƯỢC (0 câu sai trong hơn 60 câu khẳng định đối chiếu được tới dòng code; hai câu nên nói đủ hơn, không chặn; bốn nghi lỗi code: ba xác nhận, một không xác định được, đều là việc của ticket riêng)

# Duyệt wip/29-docs-sync f1a9e03 (ticket 29: tài liệu về lại đúng code) — fable 5.1, 30/10/2026

Đã kiểm: diff dcdb3e7..f1a9e03 (11 tệp, +148 −63, chỉ tài liệu và chú thích `.env.example`; mọi dòng `KEY=` giống từng byte,
tự so). Phần đối chiếu từng câu khẳng định với code giao cho một subagent đọc-chỉ trên worktree `29-docs-sync` (HEAD f1a9e03,
sạch), bảng đầy đủ ở `scratchpad/verify-29-docs-sync-f1a9e03.md` (ngoài repo); tôi tự kiểm lại các số đếm và các chỗ có hệ quả.

## Kết quả đối chiếu

| Nhóm câu | Số câu | Kết quả |
|---|---|---|
| Số đếm: 1 492 test thu thập (1 417 + 75), 139 tệp test, 35 migration đều có downgrade, head `20261027_35`, 4 job CI, 23 trường `discord_*`, 11 màn web | 7 | đúng, đếm lại bằng `pytest --collect-only`, `ls`, `grep` |
| Luồng OCR/index trong thread của API theo backend mặc định `thread`, Redis chỉ chở job trí nhớ trừ khi `rq`; launcher chỉ bật `redis` | 6 | đúng (`settings.py:51`, `main.py:115–123`, `postgres_document_service.py`, `run-local-ai-core.bat:94–95`) |
| Trí nhớ: tự áp dụng ≥ 0,8 qua guard khi extractor bật, xoá luôn chờ người, verifier tắt mặc định, extractor pull theo cờ | 5 | đúng (`memory_worker_service.py:477–515`, `memory_guard.py`, registry) |
| Agent: 3 tool lõi + `search_history`, đọc ≤ 3 đoạn / 6 000 ký tự, `max_steps` 3, 90 s / 20 s, #2, ticket 27, phiếu dán 10 000 / 100 000 / 600, ước `1 253 + ký tự/3,3 ≤ 12 288` | 9 | đúng từng số với `agent_service.py`, `pastes.py`, `models.yaml` |
| Bot: `/memory`, `/status` ephemeral, allowlist guild (rỗng = không guild), ba cách bật, 409 khi panel đang chạy, phiên bền ba nguồn | 6 | đúng |
| Backup, cleanup, hybrid retrieval, cutover Postgres, training tree, reranker trượt gate, lock file chưa có, P3-1 | 12+ | đúng; một câu không kiểm được: "các bước container/alembic bên dưới vẫn chạy" (không chạy thử) |

## Hai câu nên nói đủ hơn (không sai, không chặn)

1. `README.en.md:48–49` "launcher pulls them, except `ocr-v1`, built once by hand": launcher có thử `ollama create` từ Modelfile
   đã track (`run-local-ai-core.bat:137, :225–233`), chỉ bỏ qua vì gguf chưa dựng. Đúng kết quả, thiếu nửa cơ chế.
2. `docs/versioned_ingestion.md:90` "nor, for documents, the outbox dispatcher": dispatcher vẫn bật cho trí nhớ khi
   `DISCORD_MEMORY_INGESTION_ENABLED=true`; ở chế độ thread chỉ là không có sự kiện outbox cho tài liệu. Câu hiện tại đọc được
   hai cách.

## Bốn nghi lỗi code opus nêu (không sửa trong nhánh này, đúng)

| # | Nghi vấn | Kết quả | Hệ quả |
|---|---|---|---|
| 1 | `/docs` không có cổng guild | **xác nhận**: `discord_bot/main.py:488–520` → `rag_prepare` → `POST /rag/chat` không mang guild id; `_tools_allowed_for_guild` chỉ chặn lượt @mention | bot ở guild nào cũng tra được cả kho tài liệu qua `/docs`, kể cả khi allowlist rỗng — ticket riêng, mức ưu tiên cao hơn ba cái kia |
| 2 | Luật 5 README.en ("không tính năng nào thêm một lần sinh chữ vào đường trả lời mặc định") | **code trái**: `rag_service.py` gọi `router.chat` viết lại câu hỏi nối tiếp trước khi tra, `condense_enabled` mặc định true, chỉ bỏ ở lượt đầu | từ lượt thứ hai đường RAG mặc định có 2 lần sinh chữ; luật có từ trước, không thuộc diff; hoặc sửa luật, hoặc đo giá của bước viết lại — chủ dự án quyết |
| 3 | Khoá train không tồn tại | **không xác định được** khoá nào; mọi cờ trong `training/README.md` đều có. Lệch gần nhất: README nói mỗi thư mục model có `AUTHORSHIP.md`, `data/models/reranker/reranker-vi-v1/` không có và git không track tệp nào tên đó | nhỏ |
| 4 | Cờ phiên bền ba mặc định | **xác nhận**: code bot `"false"` (`discord_bot/main.py:90–93`), compose `:-true`, `.env.example` `true`, panel ép `true` | chạy bot tay ngoài compose mà không đặt biến thì phiên không bền; README mới mô tả đúng ba nguồn |

## Nhận xét

- Tài liệu giờ nói đúng thứ code làm, kể cả chỗ code làm sai luật; đó là việc của ticket 29 và nó làm đúng.
- Hai câu ở mục trên sửa được trong một dòng mỗi câu nếu opus muốn trước khi gộp; không sửa cũng không sai.
