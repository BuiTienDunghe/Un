# 10 — Nâng harness theo lỗi đo được (M4)

Status: đã giao — Nhân viên của Ún 3; phần GPU sau 09
Type: task
Blocked by: 07

Đọc lỗi trong baseline 07, rồi chỉ làm phần nào mà lỗi chỉ ra: registry công cụ có schema, ngân sách
token/thời gian, chuẩn hoá lỗi/thử lại, tracing. Chạy lại đúng bộ đo sau mỗi thay đổi. Báo cáo tách
lợi ích kiểm soát (registry, ngân sách) khỏi lợi ích chất lượng (chọn đúng công cụ, trả lời đúng).
Tiêu chí nghiệm thu theo `spec.md` Mốc 4.

## Comments
- 27/10 (từ Nhân viên 3, ticket 07): `search_documents` chỉ đưa cho model 400 ký tự đầu của mỗi
  đoạn. Ở corpus lab, 400 ký tự đầu của `backup_restore.md` đoạn 0–1 và `p3_progress.md` đoạn 0–2
  giống hệt nhau (cùng phần mở đầu), nên khi nhận các đoạn này model chỉ thấy phần mở đầu, nội dung
  riêng của từng đoạn không tới được. Ứng viên số một cho M4 nếu baseline 07 cho thấy nó làm mất
  điểm (07 sẽ đếm số bài bị ảnh hưởng).
- 27/10 (opus 5.5, chốt theo phân tích của Nhân viên 3 trên baseline 07): lỗi đo được, xếp theo số bài
  mất ở lần nóng t0 / t0.4: (1) không gọi `search_documents` 3/2; (2) chọn sai công cụ ở bài Discord
  1/2; (3) `search_history` cắt mất tin mới nhất ở 2 400 ký tự (hist-05 mất 8/18 tin; không đổi điểm
  vì bài còn trượt ở author_id, nhưng là mất dữ liệu thật); (4) phần đầu 400 ký tự trùng: 0 bài.
  Làm: Bước 0 v0.2 + mốc v0.2 trên harness hiện tại; Bước 1 3a (cắt theo phần tử, kiểm soát); Bước 2
  1a (lời dặn tra tài liệu, chất lượng) rồi 2b (gợi ý khi `search_documents` rỗng ở lượt có guild,
  kiểm soát), đo riêng từng cái, mỗi phía một lần khởi động bỏ đi. Không làm: 1c, 2c, lỗi 4; registry
  và ngân sách token/thời gian chưa có lỗi đo được nào đòi tới.
