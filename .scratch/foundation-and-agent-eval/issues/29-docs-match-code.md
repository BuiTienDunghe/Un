# 29 — Tài liệu khớp code

Status: đang làm — chủ dự án (30/10): "xử lý nốt phần code và những thứ xung quanh"
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
