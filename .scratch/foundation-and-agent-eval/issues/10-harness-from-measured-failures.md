# 10 — Nâng harness theo lỗi đo được (M4)

Status: chờ
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
