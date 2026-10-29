# 29 — Tài liệu khớp code

Status: xong — gộp main 5d670ea (30/10); bốn nghi lỗi code chờ chủ dự án
Type: task
Blocked by: —

## Vì sao

Ngày 13/09, khi đối chiếu README và `docs/` với thân hàm, thấy nhiều chỗ lệch. Từ đó tới nay, các ticket 01–27
đổi nhiều thứ:

- Compose chuyển sang v2.
- Có một cơ chế bật bot duy nhất.
- Discord thành gói riêng.
- Có registry phiên bản model.
- Agent có thêm `read_document`, phiếu đoạn dán và nạp nguyên văn.

Có chỗ lệch cũ đã được sửa (panel bot 401 ở ticket 04), có chỗ lệch mới sinh ra.

## Danh sách lệch ngày 13/09 (phải kiểm lại, đừng tin)

- **OCR/index:** README và `current_architecture.md` vẽ việc chạy qua worker Redis. Thật ra mặc định
  `INGESTION_EXECUTION_BACKEND=thread`, chạy trong luồng phụ của API.
- **Trí nhớ Discord:** README nói "không gì tự áp dụng". Code mặc định tự áp dụng khi độ tin ≥ 0,8.
- **`/docs` của bot** gọi `/rag/chat` mà không có cổng guild. Đây là chuyện code; chỉ ghi lại, không sửa ở ticket này.
- **Panel bot** trả 401 khi có khoá. Ticket 04 đã sửa?
- **README:** ghi CI 3 job (nay là 4).
- **`.env.example`:** `CONVERSATION_HISTORY_LIMIT=12`, trong khi code là 40.
- **`versioned_ingestion.md`:** còn nói mặc định SQLite.
- **Tài liệu cũ nhiều chỗ:** `memory_design.md` (đầu tệp), `training/README.md`.

## Việc

1. Đối chiếu README.md, README.en.md, `docs/current_architecture.md` và `.env.example` với code trên main. Đối
   chiếu thêm các tệp `docs/` mà README trỏ tới.
2. Sửa tài liệu cho khớp code. **Không sửa code.**
3. Chỗ nào code có vẻ sai còn tài liệu đúng ý định thì không sửa. Ghi vào phần Comments của ticket này: tệp,
   dòng, điều quan sát được.

## Nghiệm thu

- Mỗi câu sửa dẫn được tới dòng code chứng minh.
- Không đổi tệp nào ngoài tài liệu và `.env.example`. Riêng `.env.example` chỉ sửa giá trị mặc định cho khớp
  code, không thêm biến.
- `.env` thật không được đọc.

## Comments
- 30/10 (opus 5.5): năm commit, gộp main `5d670ea`, fable GỘP ĐƯỢC: 0 câu sai trong hơn 60 câu đối chiếu được. Hai câu fable muốn nói đủ hơn đã sửa ở `f072e69`.
- Bốn nghi lỗi code, không sửa ở ticket này:
  1. **`/docs` của bot không có cổng guild** (fable xác nhận). `discord_bot/main.py:488-520` → `/rag/chat`; autocomplete liệt kê mọi tên tệp đã index (`:443-463`). Danh sách guild được phép chỉ chặn lượt agent (`turn_service.py:127-132`). Hệ quả: server nào có bot cũng tra được cả kho. Cần ticket riêng.
  2. **Luật 5 của README.en bị code trái từ trước** (fable xác nhận). Luật nói không thêm lần sinh chữ nào vào đường mặc định, nhưng `rag_service` viết lại câu hỏi nối tiếp (`condense_enabled: true`). Thêm vào đó còn lần thử lại của #2 và lần nhắc lại khi lệnh công cụ hỏng. Hoặc sửa luật, hoặc đo giá các bước đó.
  3. **Khoá train không tồn tại**: `training/README.md:97-99` tả một khoá khiến eval đêm bỏ qua, nhưng không có code nào làm việc đó. Đã thêm ghi chú.
  4. **`DISCORD_PERSISTENT_SESSIONS_ENABLED` có ba giá trị mặc định** (bot `false`, compose `true`, panel bật cứng). Chú thích compose nói là cố ý; chỉ ghi lại.
