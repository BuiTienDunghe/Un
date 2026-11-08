# Cải tiến CPU trên nhánh — 08/11/2026

Status: verified — full backend CPU và benchmark đã hoàn tất.
Nhánh duy nhất được sửa: codex/backend-small-fixes, base 67260f3.
Không sửa checkout main; không đổi prompt, vòng agent hay model.

Kết quả: [báo cáo CPU](../../data/evaluation/results/kept/backend-improvements-2026-11-08/REPORT.md), có cả các lượt lỗi và đánh đổi thời gian cache ấm. Ghi sổ đo trong worktree nhánh, không ghi vào main.

Phạm vi:
- Lỗi index bất ngờ thành lỗi server có mã tra log, không lẫn với lỗi tài liệu.
- Tách SourcePageCounts: cache có giới hạn, theo content hash và stat, không giữ kết quả thiếu nguồn mãi.
- Dùng metadata Document đã tải khi resolve nguồn paper để bỏ SQL theo từng tài liệu.
- Thận trọng với metadata ingestion cũ sau queued/failed/cancelled replacement; nguồn đang đổi trả số trang chưa biết.
- Thống nhất hợp đồng URL test PostgreSQL, giữ bảo vệ dữ liệu thật.

Kiểm chứng dự kiến trước khi chạy:
- Unit/HTTP fake và SQL trên PostgreSQL riêng; toàn bộ backend nếu focused đạt.
- So cùng fixture với lớp ResearchService tại base 67260f3 và main c01d6dd, không chạy model.
- Đếm SELECT và PDF IO ở cache lạnh/ấm, kiểm payload tương đương khi nguồn ổn định; sửa số trang khi nguồn thay là khác biệt có chủ đích.
- Ghi cả lỗi test, lần sửa test và giới hạn của thời gian đo. Không có ngưỡng ship chất lượng model trong phép này.
- Guard chỉ cho Python test kết nối loopback, chặn cổng model phổ biến; Ollama trỏ cổng chết, khóa cloud trống, CUDA bị ẩn.
