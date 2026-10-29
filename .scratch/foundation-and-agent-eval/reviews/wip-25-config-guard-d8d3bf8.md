GỘP ĐƯỢC

# Duyệt wip/25-config-guard d8d3bf8 (ticket 25, cách 1B: khoá danh sách trường `discord_*` mà lõi được đọc) — fable 5.1, 30/10/2026

Đã kiểm: diff 0cc0e68..d8d3bf8 (2 tệp: `settings.py` +7, `test_discord_boundary.py` +100). Không chạy model, không DB.

| Kiểm | Kết quả |
|---|---|
| `settings.py` chỉ thêm chú thích | 7 dòng thêm đều là `#`; không trường, kiểu, mặc định, alias hay validator nào đổi (0 dòng không phải chú thích trong diff) |
| Danh sách 8 cặp (module, trường) đúng với code hôm nay | test tự chứng minh hai chiều: cặp mới → đỏ, cặp đã liệt kê mà biến mất → đỏ; chạy trên bản sao d8d3bf8: 12 xanh |
| Tự làm hỏng | thêm một lần đọc `settings.discord_memory_queue_name` vào `chat_service.py` → 1 đỏ đúng test; đổi tên một lần đọc trong `main.py` → 1 đỏ ("gone"); khai một trường `discord_zzz` ngoài khối → 1 đỏ đúng test khối. 3/3 |
| Phạm vi quét | mọi `.py` dưới `app/` trừ `app/discord/` và `settings.py`; `main.py` không được miễn (đúng, vì nó là nơi nối gói); `scripts/` ngoài phạm vi, hợp lý vì script không phải lõi |
| Cách bắt | thuộc tính trên mọi đối tượng, chuỗi bằng đúng tên trường, tên ghép từ `"discord_"` (báo là "built at run time"); test tự kiểm 7 dạng dương và 4 dạng âm (cột ORM, tên job, tên biến môi trường, dòng log) |
| Worktree | `25-config-guard` sạch, HEAD d8d3bf8 |

## Nhận xét

- Đúng cách 1B chủ dự án chọn: không dời trường, chỉ đóng khung và khoá cửa. Giá trị thật nằm ở chỗ từ nay thêm một lần đọc
  `discord_*` trong lõi phải ghi tên vào danh sách và nói lý do trong commit.
- Hai lần đọc còn lại trong `main.py` (`discord_memory_queue_name`, `discord_memory_ingestion_enabled`) và năm trong
  `model_registry.py` là đúng chỗ ticket 22 đã chấp nhận; không cần dời trong lượt này.
- Nhỏ: chuỗi bằng đúng tên trường ở bất kỳ đâu (kể cả trong docstring) cũng bị tính là đọc; hiếm, và lỗi sẽ chỉ rõ dòng.
