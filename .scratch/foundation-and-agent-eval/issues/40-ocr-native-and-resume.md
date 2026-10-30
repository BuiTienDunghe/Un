# 40 — OCR không chép lại chữ có sẵn; tài liệu tự chạy tiếp sau khởi động lại

Status: xong trên nhánh — chủ dự án chọn B (31/10)
Type: task
Blocked by: —
Liên quan: ticket 38, 39.

## Bản chất

Màn OCR đọc mọi trang bằng model kể cả khi PDF đã có chữ. Việc lập chỉ mục sống trong tiến trình API nên khởi động lại là mất, tài liệu kẹt "đang xử lý" mãi: 31/10 tôi khởi động lại đúng lúc một tài liệu đang nhúng và nó kẹt ở 17/30 đoạn. Không có cơ chế nào gỡ.

## Quyết định

- Trang đạt cùng phép thử của thư viện (`SmartParser._needs_ocr`) lấy chữ có sẵn; `force_ocr` ép đọc bằng model.
- Khi API khởi động dưới supervisor, lần chạy còn "processing" là không còn ai làm: đánh dấu hỏng rồi chạy lại. Tài liệu từ OCR dùng lại các trang đã lưu, vì tệp gốc của nó chỉ là một khối chữ. Chỉ dưới supervisor, để eval và test không đụng.
- Đổi model bị từ chối (409) khi đang đọc hoặc lập chỉ mục, vì đổi là khởi động lại. Việc OCR đang chạy dở khi tắt máy vẫn mất: nó chỉ nằm trong bộ nhớ.
