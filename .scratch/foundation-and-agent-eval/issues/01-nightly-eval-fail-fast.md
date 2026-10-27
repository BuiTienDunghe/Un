# 01 — Eval đêm dừng sớm và nói rõ phụ thuộc nào tắt (M1a)

Status: đã giao — Nhân viên của Ún 1
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
