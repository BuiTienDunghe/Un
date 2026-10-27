# Điều phối — nền + Agent Eval

Chủ dự án giao (27/10/2026): "opus 5.5 của Ún" và "fable 5.1 của Ún" tự điều phối cho tới khi xong
`spec.md`, hoặc tới khi hạn mức tuần (tất cả model, hoặc riêng Fable) vượt 85%. Có ba phiên thực
hiện: "Nhân viên của Ún 1", "Nhân viên của Ún 2", "Nhân viên của Ún 3".

## Vai trò

| Phiên | Việc |
|---|---|
| opus 5.5 của Ún | Điều phối chính: giao ticket, gộp nhánh vào `main`, chạy bộ test đầy đủ, commit gộp, báo chủ dự án |
| fable 5.1 của Ún | Đồng điều phối: duyệt diff mỗi nhánh trước khi gộp; giữ chất lượng bộ bài Agent Eval; chọn mục tiêu M3 (ticket 08) |
| Nhân viên 1–3 | Mỗi phiên làm một ticket một lúc, trong worktree riêng |

## Quy tắc cho nhân viên

1. **Không bao giờ sửa file trong `C:\Users\dungbt06\local-ai-core` (checkout chính).** Cả bốn phiên
   đang dùng chung thư mục đó. Làm trong worktree riêng:
   ```
   git -c core.longpaths=true worktree add C:\Users\dungbt06\local-ai-core-wt\<NN-slug> -b wip/<NN-slug> main
   ```
2. Dùng Python của checkout chính: `C:\Users\dungbt06\local-ai-core\.venv\Scripts\python.exe`. Đã
   kiểm 27/10: chạy từ `<worktree>\backend` thì `import app` lấy code của worktree, không lấy code
   của checkout chính (venv không che gói cục bộ).
3. Commit trên nhánh `wip/<NN-slug>` của mình, theo kiểu message của repo (một câu tả hành vi mới,
   chữ thường, xem `git log`). **Không push, không merge, không đổi nhánh của checkout chính.**
4. Chỉ đụng đúng các file mà ticket liệt kê. Cần đụng thêm file khác thì hỏi điều phối trước.
5. Hiện chưa có stack Docker cho Ún: container đã tắt, còn `edu-postgres-1` (dự án khác) đang giữ
   cổng 5432. **Không bật, tắt hay xoá container nào.** Test cần Postgres thì ghi "chưa chạy, cần
   stack" — điều phối sẽ chạy sau.
6. Không đọc hay in `.env` (có khoá). Cần một biến thì đọc đúng dòng đó, che giá trị.
7. Xong thì gửi điều phối (`opus 5.5 của Ún`) một tin gồm: tên nhánh, các commit, lệnh test đã chạy
   kèm kết quả, những gì chưa kiểm, và nơi lệch khỏi ticket. Cập nhật `Status:` trong file ticket
   **ngay trên nhánh của mình**.
8. Bị chặn thì báo ngay, không đoán. Bị từ chối quyền thì báo lại, không nhờ phiên khác làm thay.

## Stack Docker

Chủ dự án cho phép (27/10): khi cần bật stack của Ún, **opus** được `docker stop edu-postgres-1`
(không xoá), xong việc thì `docker start edu-postgres-1`. Chỉ opus làm việc này; nhân viên và fable
không bật/tắt container. Stack chưa bật cho tới khi ticket 01 tái hiện xong cảnh "stack tắt".

## GPU

Mỗi lúc chỉ một việc nặng trên GPU, vì 07 và 09 đều ghi độ trễ và 09 có điều kiện dừng theo p50.
Thứ tự từ 27/10 18:45: **07** (ghi truy xuất lab + baseline) → **09** nhánh 0. Mọi eval stack
(`eval_stack --profile lab|heldout`) phải **dừng trước 02:45**: eval đêm 03:00 tự bật lab API ở
cổng 8100 và cần GPU; đêm 27→28/10 là đêm nghiệm thu của ticket 01.

## Tin nhắn

Ứng dụng giữ lại tin của một phiên khi nó gửi quá nhiều tin liên tiếp (fable 5.1 bị giữ sau khoảng 10
tin, 27/10; chủ dự án phải mở lại). Gom kết luận: mỗi nhánh một tin, đủ để không cần hỏi lại.

## Gộp

Nhánh → fable 5.1 duyệt diff (đúng ticket? có hồi quy? test có kiểm đúng điều cần kiểm?) → opus gộp
vào `main` ở checkout chính → chạy test → xoá worktree. Chỉ một phiên (opus) ghi vào `main`.

## Hạn mức

Mỗi lần giao việc, opus kiểm hạn mức tuần. Vượt 85% (tất cả model hoặc riêng Fable) thì dừng giao
ticket mới, chờ các ticket đang chạy xong, rồi báo chủ dự án.

## Bảng ticket

| # | Ticket | Phụ thuộc | Giao cho | Trạng thái |
|---|---|---|---|---|
| 01 | Eval đêm dừng sớm, báo rõ (M1a) | — | Nhân viên 1 | **đã gộp** — còn một đêm 03:00 thật |
| 02 | Một cách cài, xoá hack sys.path (M1b) | — | Nhân viên 1 | **đã gộp** |
| 03 | Compose chỉ chuyển tiếp, Docker sang v2 (M1c) | — | Nhân viên 2 | **đã gộp** |
| 04 | Một cơ chế bật bot + panel 401 (M1d) | 05 đã gộp | Nhân viên 1 | **đã gộp** |
| 05 | Dời job_*, query dashboard vào service (M1d) | 02 đã gộp | Nhân viên 1 | **đã gộp** |
| 06 | Agent Eval v0: khung chạy + bộ bài (M2) | — | Nhân viên 3 | **đã gộp** — chưa chạy lại với model thật |
| 07 | Agent Eval v0: ghi truy xuất thật + baseline 3 lần (M2) | 06 gộp; GPU sau 11 | Nhân viên 3 | **đã gộp** — 34/40 nóng, 29/40 t0.4 |
| 08 | Chọn mục tiêu thí nghiệm model (M3) | — (chỉ đọc) | fable 5.1 | xong — chọn B, nhánh 0 trước |
| 09 | Thí nghiệm B, nhánh 0 trước (M3) | 11 | Nhân viên 1 chuẩn bị, Nhân viên 2 chạy | record + probe đã gộp; nhánh 0 đang chạy |
| 10 | Nâng harness theo lỗi đo được (M4) | 07 gộp; GPU sau 09 | Nhân viên 3 | đã chốt cách làm |
| 11 | Đo dao động 788 câu held-out (tiền đề M3) | stack | Nhân viên 2 | **đã gộp** — sàn = 0 câu |
| 12 | Dọn nhỏ sau 03 (được phép trượt) | — | Nhân viên 3 | **đã gộp** |

## Mốc so sánh của bộ test

27/10, main ed51b4b, stack Ún bật, DB `local_ai_core_test` + Redis DB 15: backend 1045 xanh / 1 đỏ /
1 skip (2 phút 45 giây); root 65 xanh. Cái đỏ có sẵn trên main, không do nhánh nào gây ra:
`test_postgres_cleanup_lifecycle.py::test_postgres_log_and_ocr_retention_execute_only_due_rows`
(`assert 3 == 1`). DB test còn sót bản ghi OcrRun cũ, mà test lại đếm cả bản ghi không phải của nó.

Sau khi gộp 03 (main 9e00ed5): backend 1049 xanh / 0 đỏ / 1 skip; root 65 xanh. Test cleanup đỏ ở lần
trước giờ xanh — đúng với giải thích "bản ghi sót": lần chạy trước đã xoá chúng (ticket 12 mục 4 vẫn
cần, vì DB test sẽ lại có rác khi một test bị ngắt giữa chừng).

Sau khi gộp 01 (main 4844878): backend 1060 xanh / 0 đỏ / 1 skip (3 phút 10 giây); root 65 xanh.

Sau khi gộp 06 (main 7c645ec): backend 1104 xanh / 0 đỏ / 1 skip (3 phút 16 giây); root 65 xanh.

Sau khi gộp 12 (main 1c78054): backend 1106 xanh / 1 lỗi teardown / 1 skip. Lỗi là deadlock khi
DELETE documents trong `test_debt_t1_t2_t3.py`: lúc 17:59 Nhân viên 1 chạy chen một bài redteam trên
cùng DB test. Chạy lại riêng hai file đó (debt + redteam) trên main: 18 xanh. Không phải hồi quy.

Sau khi gộp 02 (main 73e3faa): backend 1107 xanh / 0 đỏ / 1 skip; root 65 xanh.

Sau khi gộp 05 (main 9d3fbe8): backend 1109 passed, 1 skipped, 5 warnings; root 65 xanh.
