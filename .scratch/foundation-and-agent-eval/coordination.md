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

## Gộp

Nhánh → fable 5.1 duyệt diff (đúng ticket? có hồi quy? test có kiểm đúng điều cần kiểm?) → opus gộp
vào `main` ở checkout chính → chạy test → xoá worktree. Chỉ một phiên (opus) ghi vào `main`.

## Hạn mức

Mỗi lần giao việc, opus kiểm hạn mức tuần. Vượt 85% (tất cả model hoặc riêng Fable) thì dừng giao
ticket mới, chờ các ticket đang chạy xong, rồi báo chủ dự án.

## Bảng ticket

| # | Ticket | Phụ thuộc | Giao cho | Trạng thái |
|---|---|---|---|---|
| 01 | Eval đêm dừng sớm, báo rõ (M1a) | — | Nhân viên 1 | đã giao |
| 02 | Một cách cài, xoá hack sys.path (M1b) | 01 đã gộp | — | chờ |
| 03 | Compose chỉ chuyển tiếp, Docker sang v2 (M1c) | — | Nhân viên 2 | đã giao |
| 04 | Một cơ chế bật bot + panel 401 (M1d) | 02 đã gộp | — | chờ |
| 05 | Dời job_*, query dashboard vào service (M1d) | 02 đã gộp | — | chờ |
| 06 | Agent Eval v0: khung chạy + bộ bài (M2) | — | Nhân viên 3 | đã giao |
| 07 | Agent Eval v0: ghi truy xuất thật + baseline 3 lần (M2) | 06; cần stack | — | chờ |
| 08 | Chọn mục tiêu thí nghiệm model (M3) | — (chỉ đọc) | fable 5.1 | đã giao |
| 09 | Chạy thí nghiệm model (M3) | 08; cần GPU + stack | — | chờ |
| 10 | Nâng harness theo lỗi đo được (M4) | 07 | — | chờ |
