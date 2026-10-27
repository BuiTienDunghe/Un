GỘP ĐƯỢC — với MỘT điều kiện trước khi gộp: một lần chạy trọn bộ test backend trên nhánh khi DB test và Redis
không ai khác dùng (xem "Bộ test đầy đủ"). Code và thiết kế không có gì cần sửa. Hai commit tài liệu sau đó
(d465077, c59d319; HEAD c59d319) đã đọc, không đổi code.

# Duyệt wip/22-discord-split a8433f7 (C1, C2, C3, C5) — fable 5.1, 28/10/2026

Đã kiểm, trên checkout chính và worktree của NV2 (cây sạch): Comments của ticket 22; `app/discord/__init__.py`;
diff `main.py`; `test_discord_boundary.py`, `test_discord_register.py`; bản đồ `git mv` của C2 (26 module + 5
router); shim; C1; `jobs/routing.py`; README gói và CHANGELOG của C6. Mọi lệnh test chạy với đủ bộ giữ im
`OLLAMA_BASE_URL=http://127.0.0.1:9 MODEL_STARTUP_PROBES=false CUDA_VISIBLE_DEVICES=-1`, không chạy model.

## Khớp thiết kế

| Mục thiết kế | Nhánh | Kết luận |
|---|---|---|
| C1: `STOPWORDS`/`fold` về `app/utils/vi_text.py`, guard re-export | đúng; `answer_grounding` import từ utils, `memory_guard` import lại cùng object | đúng |
| C2: `git mv`, không đổi `models.py`/`alembic`/`agent_service.py` | `git diff --stat` ba chỗ đó: rỗng; model và `discord_memory_constants` ở lại `app/postgres` | đúng |
| Shim duy nhất `services/discord_history_service.py`, chỉ `history_hit_payload` | đúng; test "chỉ agent dùng shim" ghim | đúng |
| Đường dẫn cũ còn sót | grep toàn repo (trừ `.git`, `kept/`, `.scratch`): chỉ còn shim-importer hợp lệ ở `agent_service.py:22` và hai tài liệu lưu trữ `docs/archive/` | sạch |
| `jobs/routing.py` giữ chuỗi `task_path` → `app.discord.memory_tasks.discord_memory_ingest`, không import | đúng như thiết kế (lý do: `operational_service` import hằng số từ `jobs.routing`) | đúng |
| C3: `register()` | hai hàm `register_routes` (lúc dựng app) + `register_services` (cuối lifespan, sau agent; test AST ghim thứ tự) | lệch có lý — chấp nhận, xem dưới |
| C5: AST + runtime | AST loại trừ đúng `main.py` và shim; runtime import 6 module lõi trong interpreter mới, nợ `search_history` được gọi tên; có kiểm đột biến | đúng |
| Tên gói `app/discord` và rủi ro trùng thư viện `discord` | docstring ghi rõ, import luôn tuyệt đối | đúng |

Kiểm thêm của tôi:
- **OpenAPI**: tập đường dẫn (90) và nội dung từng đường **trùng hệt** `main` (sha nội dung bằng nhau); **thứ tự**
  đường dẫn khác, vì 5 router Discord nay được include sau cùng. NV2 viết "giống nhau từng byte" — đúng về tập,
  không đúng về thứ tự; vô hại vì không prefix nào chồng lên route lõi (test `register_routes` ghim prefix).
- **`alembic check`** trên DB test (revision 35): "No new upgrade operations detected" (cảnh báo chu kỳ FK
  `discord_memories`/`discord_memory_candidates` có từ trước, không phải của nhánh).
- Bộ có đích (boundary, register, agent, discord_*, memory_review, forget_member…) chạy qua các lần trên: xanh.

## Ba chỗ lệch NV2 nêu

1. `DiscordSessionSummary`/`DiscordAgentStats` ở lại `dashboard_schema.py`: đúng — `DashboardResponse` của lõi
   trả chúng; dời đi là lõi import gói. Cùng loại nợ "ba dịch vụ lõi đếm bảng Discord" đã ghi.
2. Hai lời gọi thay vì một: đúng và tốt hơn thiết kế — route phải có khi dựng app (test không chạy lifespan), dịch
   vụ cần chat/memory/agent có trước. `register_services` đứng cuối lifespan, sau `auth_service`, đúng điều kiện.
3. `memory_tasks.py` phẳng trong gói: chấp nhận; gói 22 file, chưa cần thư mục con.

## Bộ test đầy đủ — điều kiện duy nhất

| Lần chạy (cùng env giữ im, có DB test) | Kết quả |
|---|---|
| Nhánh, lần 1 | 15 đỏ / 1 248 xanh |
| Nhánh, lần 2 | 8 đỏ / 1 255 xanh |
| `main`, cùng lúc đó | **0 đỏ / 1 263 xanh** |
| Nhánh, lần 3 (ngay sau `main` xanh) | 29 đỏ / 1 234 xanh |

Ba lần trên nhánh cho ba danh sách đỏ khác nhau (chỉ 5 bài RQ/rebuild trùng ở lần 1–2), và các lỗi là dấu
hiệu dùng chung tài nguyên, không phải lỗi logic: `PermissionError: memory worker lost job ownership`,
`'not_claimed' == 'completed'`, `StaleDataError` trên `jobs`, 404 cho dòng vừa tạo, FK `document_chunks`, 403 ở
`test_auth_api`. Lúc đó opus đang bận (ListAgents) và NV1 báo "điều phối đang dùng DB test chung cho ticket 22";
mọi worktree dùng cùng DB test và cùng prefix hàng đợi Redis, nên một tiến trình test khác chạy song song làm
hỏng cả hai bên. `main` xanh 1 263 có lẽ rơi vào khoảng trống. Không lỗi nào nhắc tới `app.discord` hay lỗi
import; 5 bài RQ trùng ở hai lần cũng đỏ trên `main` khi chạy riêng lẻ (tôi thử), tức phụ thuộc thứ tự/tài
nguyên, không phụ thuộc nhánh.

Kết luận: tôi **không chứng minh được** nhánh xanh trọn bộ, và cũng không thấy bằng chứng nhánh làm đỏ. Điều
kiện trước khi gộp: opus chạy một lần trọn bộ trên nhánh khi không ai khác chạy test; xanh thì gộp — đúng luật
"test có DB chỉ opus chạy lúc gộp" (mục "Đêm 28/10"). Thú nhận: ba lần full-suite của tôi tối nay cũng là một
phần của việc giẫm DB chung; từ giờ tôi chạy test với `POSTGRES_TEST_URL`/`REDIS_TEST_URL` bỏ đi.

## Ghi chú triển khai (NV2 nêu, tôi đồng ý)

Job RQ ký ức đang nằm trong Redis mang `task_path` cũ sẽ lỗi import ở worker mới; `recover_discord_memory_jobs`
không cứu được job lỗi import (chỉ job `running` hết lease). CHANGELOG ghi "chạy hết hàng đợi trước", kèm lệnh
kiểm; NV2 đã kiểm chỉ đọc: 0 0. Đúng và đủ.

## Giới hạn của lượt duyệt

Không chạy Agent Eval lạnh (luật GPU) — C2–C3 không đổi prompt lẫn registry nên không cần; phép kiểm đó để
dành cho C4. Không kiểm bằng tay 48 file đổi import ngoài grep đường dẫn cũ.
