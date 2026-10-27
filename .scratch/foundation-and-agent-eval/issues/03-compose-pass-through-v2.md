# 03 — Compose chỉ chuyển tiếp, Docker sang v2 (M1c, đổi hành vi có chủ đích)

Status: xong trên nhánh `wip/03-compose-pass-through-v2` — chờ fable 5.1 duyệt diff
Type: task
Blocked by: —

## Vì sao

`docker-compose.yml` tự khai 31 mặc định dạng `${VAR:-default}`, trong đó 16 biến trùng tên với một
field của `backend/app/config/settings.py`. Một biến đã lệch:
`DISCORD_MEMORY_EXTRACTOR_SCHEMA_VERSION` có mặc định v1 ở `docker-compose.yml:87` và
`.env.example:25`, nhưng v2 ở `settings.py:82` (từ ca52d39, 28/08: thêm từ vựng sinh nhật, đồ ăn,
đồ uống ưa thích). `.env` không đặt biến này. Hệ quả: container memory-worker trích theo v1, worker
trên máy (launcher) trích theo v2. Mục tiêu: Settings là nơi duy nhất giữ mặc định.

## Việc

1. Bỏ các mặc định trùng với Settings. **Bẫy:** `${VAR}` không có mặc định, khi VAR chưa đặt, sẽ
   thành chuỗi rỗng, và `settings.py:250` ném lỗi khi schema version rỗng. Chọn cách khiến biến
   chưa đặt **vắng hẳn** trong container (vd `environment: [VAR]` dạng chỉ tên, hoặc `env_file`),
   rồi kiểm bằng `docker compose --profile <p> config`. Nếu dùng `env_file`, ghi rõ hệ quả: mọi khoá
   trong `.env` sẽ vào mọi container. Ghi lựa chọn và lý do vào Comments.
2. Giữ nguyên các giá trị riêng của container (vd `LOCAL_AGENT_BASE_URL=http://api:8000`,
   `CONTAINER_DATABASE_URL`) — chúng không phải mặc định trùng.
3. `.env.example`: sửa v1 thành v2, hoặc bỏ dòng và để chú thích "mặc định trong Settings".
4. Test tĩnh (không cần Docker): đọc `docker-compose.yml`, fail nếu có `${VAR:-x}` mà VAR là field
   của Settings. Test phải đỏ trên `main` hiện tại và xanh sau khi sửa.
5. Test hạ nguồn: phiên bản pipeline (v2) đi vào khoá idempotency (lượt, phiên bản). **Đừng** dựa
   vào hằng `"v1"` trong JSON — định dạng gửi đi vẫn ghi `"v1"` ngay cả khi pipeline là v2
   (`discord_memory_extractor.py:24-35`), nên test hiện có ở `test_discord_memory_extractor.py:136,146`
   vẫn xanh dù có đổi. Test cần Postgres thì ghi "cần stack".

## File được đụng

`docker-compose.yml`, `.env.example`, test mới trong `backend/tests/`.

## Nghiệm thu

- `docker compose config` cho thấy memory-worker không còn nhận v1.
- 15 biến trùng còn lại: giá trị mà container thấy bằng mặc định của Settings (liệt kê trong Comments).
- Message commit nói rõ đây là **đổi hành vi** cho đường chạy bằng Docker.

## Comments

**Nhân viên của Ún 2, 27/10.**

Lựa chọn: khoá chỉ tên dạng mapping (`VAR:`), không dùng `env_file`. Lý do: mỗi container chỉ nhận
đúng các biến được liệt kê. Còn `env_file: .env` thì đưa mọi khoá trong `.env` (`DISCORD_TOKEN`,
`GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `LOCAL_AI_JWT_SECRET`…) vào mọi container, kể cả worker không
cần chúng. Đã kiểm bằng `docker compose config` (Compose v5.3.1):

| Người vận hành | `config` in ra | Container thấy |
|---|---|---|
| Không đặt biến | `VAR: null` | không có biến → Settings quyết định |
| Đặt trong shell hoặc `.env` | giá trị đó | giá trị đó |
| Đặt rỗng (`VAR=`) | `""` | `""` (ghim rỗng = chưa đặt, nhờ validator) |
| `main` cũ, không đặt | `DISCORD_MEMORY_EXTRACTOR_SCHEMA_VERSION: v1` | v1 |

Chưa kiểm bằng container thật (quy tắc 5): "null = vắng trong container" dựa trên spec của compose.
Dockerfile không COPY `.env`, nên Settings trong container không đọc được `.env` nào khác.

Ngoại lệ có chủ đích, đã được điều phối duyệt (Q-b): `command:` vẫn giữ
`${RQ_QUEUE_PREFIX:-local-ai:dev}` (3 worker) và `${DISCORD_MEMORY_QUEUE_NAME:-memory_extract}`
(worker-memory). Lý do: CLI rq nhận tên hàng đợi từ dòng lệnh, trước khi có Settings. Bỏ mặc định
thì một tiền tố chưa đặt sẽ thành `:ocr`, worker nghe nhầm hàng đợi và job không ai xử. Test bắt hai
mặc định này phải **bằng** mặc định của Settings. Hướng sạch hơn cho sau này: thêm
`backend/scripts/rq_worker.py --queue ocr|index|memory` tự dựng tên hàng đợi từ Settings rồi chạy
Worker thường (có fork), khi đó bỏ được cả ngoại lệ này.

Ngoài danh sách file, đã được điều phối duyệt (Q-a): sửa `backend/tests/test_compose_defaults.py`
(trước đây test này ép ghim phải ở dạng `${X:-}`), và sửa comment ở `settings.py:234` (chỉ comment).
Test mới nằm trong cùng file đó, vì file đã có sẵn bộ đọc compose.

Một biến đổi hành vi (v1 → v2). 15 biến trùng còn lại, khi người vận hành không đặt:

| Biến | Compose cũ | Settings | Container mới thấy |
|---|---|---|---|
| RQ_QUEUE_PREFIX | local-ai:dev | local-ai:dev | vắng → local-ai:dev |
| MODEL_VERSION_EXTRACTOR / VERIFIER / EMBEDDING | "" | None | vắng → None ("" cũng → None) |
| DISCORD_MEMORY_EXTRACTOR_MODEL | "" | None | vắng → None |
| DISCORD_MEMORY_INGESTION_ENABLED | false | False | vắng → False |
| DISCORD_MEMORY_EXTRACTOR_ENABLED | false | False | vắng → False |
| DISCORD_MEMORY_EXTRACTOR_NUM_CTX | 4096 | 4096 | vắng → 4096 |
| DISCORD_MEMORY_EXTRACTOR_TIMEOUT_SECONDS | 60 | 60.0 | vắng → 60.0 |
| DISCORD_MEMORY_EXTRACTOR_RETRY_COUNT | 1 | 1 | vắng → 1 |
| DISCORD_MEMORY_QUEUE_NAME | memory_extract | memory_extract | vắng → memory_extract |
| JOB_STALE_TIMEOUT_SECONDS | 900 | 900 | vắng → 900 |
| JOB_MAX_ATTEMPTS | 3 | 3 | vắng → 3 |
| REQUEST_LOG_RETENTION_DAYS | 7 | 7 | vắng → 7 |
| LOCAL_AI_API_KEY (discord-bot) | "" | "" | vắng → bot đọc `os.environ.get(..., "")` = "" |

Hệ quả thật nặng hơn phần "Vì sao" mô tả. Worker Docker chạy v1 không "trích theo v1": nó **từ chối
mọi job** mà API trên máy gửi sang dưới v2, với mã `MEMORY_SCHEMA_VERSION_STALE`
(`discord_memory_worker_service.py:177`). Test hạ nguồn tái hiện đúng câu lỗi này trên `main`:
"job schema v2 != worker v1".

Test (chạy từ `<worktree>\backend` bằng Python của checkout chính):
- `pytest tests/test_compose_defaults.py`: trên `main` có 5 bài đỏ (4 bài tĩnh + 1 bài hạ nguồn),
  sau khi sửa thì 6/6 xanh.
- Bài hạ nguồn giả lập Postgres bằng stub: phía máy, API gửi job; phía container, worker xét job.
  Bài này kiểm khoá job `(lượt, v2)` và khoá ứng viên `(lượt, v2)`. Chạy với Postgres thật: cần stack.
- Nhóm test liên quan (registry, extractor, worker_extractor_model, nightly_registry_gate): 157 xanh,
  `test_model_registry_app.py` có 2 fail và 1 error vì cổng 5432 đang là Postgres của edu (sai mật
  khẩu). Cần stack, không liên quan đổi này.

Ngoài phạm vi, chưa sửa:
- Constructor `DiscordMemoryWorkerService` vẫn có mặc định `extractor_schema_version="v1"`. Hiện
  `memory_tasks.py` luôn truyền từ Settings nên chưa gây lỗi.
- `.env.example` còn chép nhiều mặc định khác của Settings (NUM_CTX, TEMPERATURE, SEED…). Một `.env`
  chép từ đó sẽ ghim như nhau cho cả máy lẫn Docker. Hai đường không lệch nhau, nhưng sẽ lệch với
  Settings nếu Settings đổi mặc định. Ai có `.env` chép từ bản `.env.example` cũ thì vẫn ghim v1 ở
  cả hai đường.
- 14 mặc định của discord-bot trùng với `discord_bot/main.py`: điều phối đã chuyển sang ticket 04.
