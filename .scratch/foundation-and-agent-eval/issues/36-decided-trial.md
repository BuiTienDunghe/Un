# 36 — Cắm thử decided phân loại tin vào ngăn trí nhớ

Status: đang thử — chủ dự án chọn "cắm thử luôn" (30/10)
Type: task
Blocked by: —
Liên quan: ticket 14.

## Bản chất

Mỗi tin của người, decided đề xuất ngăn; người duyệt. Không có ngưỡng tự ghi cho tới khi tỉ lệ đồng ý trên tin thật đủ tin.

## Quyết định

- Chỉ "bỏ qua" chắc từ 0,8 được khỏi hàng duyệt, không ghi gì nên không có rủi ro bẩn trí nhớ; có thể sót tin đáng nhớ, xem trong số `skipped`.
- Không chép chữ vào bảng nhãn: đọc từ sổ gốc nên sửa, xoá tin có hiệu lực luôn.
- Điều duyệt ở bảng riêng, chưa vào `discord_memories` vì đường đó cần lượt gốc.

## Thử đầu (48 tin tự viết)

Đúng 36/38 tin rõ; ngưỡng 0,8 tự xếp 30/38, đúng 29, 2/10 tin mơ hồ lọt. Không dùng số này chọn ngưỡng.
