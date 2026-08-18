# Hồ sơ lịch sử

Các tài liệu trong đây là **bằng chứng thi công đã hoàn tất** — báo cáo phase, audit và
sprint record. Chúng được giữ nguyên văn vì quy trình chất lượng của dự án
(`docs/DEVELOPMENT_PLAN.md` mục 6) dựa trên vết tích kiểm chứng được, nhưng chúng
**không mô tả hệ thống hiện tại**. Đừng trích dẫn chúng làm tài liệu vận hành.

| Thư mục | Nội dung | Vì sao còn giữ |
| --- | --- | --- |
| `sqlite_to_postgres/` | 17 báo cáo phase của cuộc migration SQLite → PostgreSQL (hoàn tất 07/2026) | Registry quyết định KEEP của phase 8A và lệnh audit/restore của 8B vẫn được tham chiếu khi đụng tới SQLite archive; bản tổng kết chính thức nằm ở `docs/sqlite_to_postgres_final_report.md` |
| `discord_memory/` | 12 sprint/audit record của pipeline Discord memory | Pipeline này còn được mở rộng ở P1-3..P1-5; các gate và benchmark trong đây là baseline đối chiếu |

Tài liệu sống (mô tả hệ thống *hôm nay*) nằm ở `docs/` và được liệt kê trong README mục
"Tài liệu bổ sung".
