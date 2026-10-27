# 01 — Eval đêm dừng sớm và nói rõ phụ thuộc nào tắt (M1a)

Status: chờ duyệt — Nhân viên của Ún 1, nhánh `wip/01-nightly-eval-fail-fast`
Type: task
Blocked by: —

## Vì sao

Đêm 16/09 là lần cuối eval đêm chạy được. Sau đó có 51 đêm exit 97 ("lab API did not answer /health
on port 8100 within 180 s"). Phần chẩn đoán kèm theo cho thấy stack của Ún không chạy: 30 đêm Docker
Desktop không trả lời, 18 đêm Docker chạy nhưng container đã tắt. Job không tự bật dịch vụ
(`backend/scripts/nightly_eval.py:203-220`). `/health` luôn trả 200 kể cả khi `degraded`
(`backend/app/services/operational_service.py:170`), nhưng phép thử Postgres không có connect
timeout (`backend/app/postgres/database.py:21`) và `redis.ping()` không có socket timeout
(`operational_service.py:95`). Giả thuyết: phụ thuộc chết thì `/health` treo, thay vì trả `degraded`.

Quyết định Q1 (theo uỷ quyền 27/10): cách (b) — kiểm phụ thuộc trước, thiếu thì dừng ngay và báo rõ.
Không để job tự bật container.

## Việc

1. **Tái hiện trước khi sửa.** Trong worktree, cho lab API chạy khi stack tắt (hiện stack đúng là
   đang tắt), và xác định `/health` treo ở phép thử nào. Worktree không có `.env`: nếu cần, tạo
   `.env` tối thiểu từ `.env.example` (không chép khoá thật). Ghi kết quả vào phần Comments.
2. Thêm timeout cho các phép thử của `/health` để phụ thuộc chết thì trả `degraded` trong vài giây.
   **Không đổi engine chính của API** (docstring `database.py:13-18` giải thích vì sao server nên
   chờ khi khởi động chậm); dùng timeout riêng cho phép thử.
3. `nightly_eval.py`: kiểm Postgres (DB lab), Qdrant, Redis trước khi bật lab API. Thiếu cái nào thì
   kết thúc ngay với mã thoát mới (chưa dùng: 93), và ghi vào ATTENTION:
   - phụ thuộc nào tắt;
   - Docker Desktop không trả lời hay container tắt (dựa vào mã thoát của `docker compose ps`);
   - nếu cổng 5432 đang do một container không phải của Ún giữ thì ghi tên nó (hiện là
     `edu-postgres-1`).
4. Sửa banner `nightly-eval-once.bat:24-25`: có ký tự xuống dòng thật nằm giữa
   `data\logs\nightly_eval.log`.
5. Test (không cần stack): phép thử `/health` có timeout (mock); phân loại phụ thuộc của nightly
   (mock subprocess/socket).

## File được đụng

`backend/scripts/nightly_eval.py`, `backend/app/services/operational_service.py`,
`nightly-eval-once.bat`, test mới trong `backend/tests/`. Cần đụng thêm file thì hỏi điều phối.

## Nghiệm thu

- Chạy tay khi stack tắt: kết thúc dưới 30 giây, ATTENTION nêu đúng phụ thuộc tắt.
- Test mới xanh; `backend/tests/test_operational*` (nếu có) vẫn xanh.
- Một đêm 03:00 thật exit 0 — điều phối kiểm sau khi có stack (không chặn việc gộp).

## Comments

### 27/10 — Nhân viên của Ún 1: tái hiện (bước 1)

Bản chất: giả thuyết chỉ đúng một nửa. Khi phụ thuộc chết, `/health` không treo mãi, nhưng
chậm, và chậm vượt trần mà job đêm chịu chờ cho mỗi lần hỏi. Thành ra API đã lên, sẽ trả lời
"degraded", mà job vẫn coi như chưa từng lên. Riêng Postgres ở cổng không ai nghe thì đúng là
treo hàng phút.

Nguyên nhân trực tiếp của exit 97: `wait_for_health` đặt `urlopen(timeout=3)` cho mỗi lần hỏi.
`/health` chậm hơn 3 s, nên lần hỏi nào cũng hết giờ, cho tới khi cạn ngân sách 180 s.

Đo bằng lab API thật chạy trong worktree, với stack Ún tắt, dùng `.env` chép từ `.env.example`:

| Cảnh | `/health` |
|---|---|
| Hôm nay: 5432 do `edu-postgres-1` giữ (từ chối ngay), 6333/6379 đóng | 200 `degraded` sau 10,4 s |
| Không ai nghe ở cổng Postgres (như các đêm tháng 9) | 200 `degraded` sau 270 s |

Từng phép thử, đo riêng bằng code của app:

| Phép thử | Cổng đóng | Cổng nhận kết nối mà không trả lời |
|---|---|---|
| Postgres `SELECT 1` (engine không có connect_timeout) | > 90 s; 0,02 s nếu edu giữ cổng | treo > 120 s |
| Redis `ping` (không có socket timeout) | 2,0 s (Windows thử lại SYN) | treo > 120 s |
| Qdrant `healthcheck` (3 lần × 10 s) | 8,4 s | 32 s |

`/health` hỏi Postgres hai lần (SELECT 1 và đếm outbox), nên con số 270 s là hai lần chờ cộng
lại. Cảnh "cổng câm" được giả lập bằng một socket của tôi, không đụng container. Nó giống Docker
Desktop đang lên dở, nhưng chưa kiểm cảnh đó trên Docker thật.

Log 51 đêm đỏ (`data/logs/nightly_eval.log` ở checkout chính) cho hai dạng `docker compose ps`:
exit 1 kèm `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`
(30 đêm); exit 0 chỉ có dòng tiêu đề (18 đêm). Bộ phân loại ở bước 3 dựa trên đúng hai dạng này.

### 27/10 — Nhân viên của Ún 1: sửa (bước 2–5)

- `/health`: mỗi phép thử dừng sau 3 s. Postgres dùng một engine riêng cho phép thử (có
  connect_timeout, NullPool), lấy URL từ engine của API. Engine chính giữ nguyên. Lượt đếm
  outbox bị bỏ qua khi Postgres đã không trả lời. Redis có socket timeout. Qdrant gọi
  `healthcheck` của store trong một luồng riêng, chờ tối đa 3 s, và không mở thêm luồng khi
  luồng cũ còn chạy.
- `nightly_eval.py`: trước khi bật lab API, hỏi thẳng Postgres (SELECT 1 trên DB lab), Qdrant
  (`/readyz`) và Redis (PING), mỗi cái tối đa 3 s. Thiếu cái nào thì exit 93, và ATTENTION ghi
  phụ thuộc nào tắt, trạng thái Docker, và container lạ nào đang giữ cổng Postgres.
  `docker compose ps` có trần 10 s. `wait_for_health` nâng trần mỗi lần hỏi từ 3 s lên 30 s.
- `nightly-eval-once.bat`: dòng banner bị gãy đã được nối lại thành `data\logs\nightly_eval.log`.
- Test mới: `tests/test_health_probe_timeouts.py`, `tests/test_nightly_preflight.py`. Cả hai
  không cần stack. Test dùng một socket nghe mà không bao giờ trả lời.

| Kiểm | Kết quả |
|---|---|
| Test mới + `test_nightly_registry_gate.py` | 20 bài xanh, 10 s |
| Cùng test trên code cũ | đỏ hết; hai bài `/health`, bỏ tham số timeout mới, vẫn treo quá 15 s / 5 s |
| Job đêm, ba phụ thuộc trỏ vào cổng trống | exit 93 sau 8,7 s, ATTENTION nêu đủ ba |
| Phép thử trước trên stack thật | cả ba trả lời, mất 1 s |
| Job đêm trọn vẹn từ worktree trên stack thật (DB lab) | exit 0 sau 57 s, cổng chặn hồi quy đạt, ATTENTION tự xoá |

Chưa kiểm: `tests/test_health.py` cần DB test, mà DB đó đang dành cho bộ test đầy đủ ở `main`.
Dòng "container lạ giữ cổng 5432" mới chỉ kiểm bằng mock, vì `edu-postgres-1` đang tạm dừng.
Một đêm 03:00 thật cũng chưa chạy.

Lệch ticket: (1) nâng trần `urlopen` trong `wait_for_health` từ 3 s lên 30 s. Việc này không
có trong danh sách việc, nhưng đó chính là nguyên nhân trực tiếp của exit 97. (2) Ollama không
được kiểm trước, vì ticket chỉ nêu ba phụ thuộc. Phần chẩn đoán của exit 97 vẫn chạy `ollama ps`.
