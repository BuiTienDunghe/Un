# Web UI v2 — những chỗ chờ chủ dự án chốt

Mỗi mục dưới đây là một chỗ **README, prototype và hành vi cũ nói khác nhau**, hoặc một chỗ đánh đổi
giữa "khớp ảnh mẫu" và "đúng dữ liệu thật". Bản đang chạy đã chọn sẵn một hướng (ghi rõ), đổi hướng
kia tốn 1–3 dòng. Không mục nào là lỗi.

## Ảnh hưởng tới điều người dùng thấy

| # | Màn | Đang làm | Hướng kia | Vì sao đáng chốt |
|---|---|---|---|---|
| 1 | Bảng điều khiển | "Lượt Discord" = tổng mọi trạng thái (421) | chỉ lượt hoàn tất (412, như prototype) | con số trên thẻ khác nhau |
| 2 | Bảng điều khiển | "k/13 ok" coi trạng thái *disabled* là bình thường (xanh), như prototype | chỉ xanh khi đủ 13/13 | máy này luôn có 2 dịch vụ tắt |
| 3 | Tài liệu | Cột Version luôn in `v<số>` kể cả khi chưa có bản phục vụ (theo prototype) | in "—" | lệch ảnh mẫu 2 ô nếu đổi |
| 4 | Tài liệu | Nút "Tất cả" đếm 23, bảng hiện 24 hàng (hàng "đang xóa" bị trừ) | đếm cả hàng đang xóa | số trên nút ≠ số hàng |
| 5 | Ghi nhớ | % tin cậy của bản do người duyệt và tên model tóm tắt chỉ hiện khi rê chuột | hiện thẳng như trang cũ | trang cũ hiện, thiết kế mới bỏ |
| 6 | Bot | Nhãn phiên "mồ côi" màu cam (theo brief) | màu xám | 5/8 hàng đang cam |
| 7 | Bot | Gộp "đang chờ" vào thanh "đang chạy" | tách 5 thanh | prototype vẽ 4 thanh |
| 8 | OCR | "Tải kết quả (zip)" chỉ bật khi job hoàn tất | bật cả job đã hủy/lỗi còn trang | máy chủ cho tải mọi trạng thái |
| 9 | OCR | Job đang chạy luôn hiện lại khi mở màn OCR, không tắt được | cho phép đóng thẻ job | bấm "OCR" ở thanh bên không làm gì khi có job |
| 10 | Chat | Hàng hội thoại đang mở có 3 nút (ghim, đổi tên, xóa) khi máy chủ hỗ trợ ghim | 2 nút như README | README vẽ 2 nút |
| 11 | Chat | Chip nguồn chỉ in mục cuối của đường mục ("Versioning") | in cả đường | in cả đường làm chip xuống 2 dòng, lệch ảnh tăng từ 1,1% lên 4,1% |
| 12 | Người dùng | "Khóa tài khoản" vẫn hỏi xác nhận | bỏ hỏi | brief không yêu cầu hỏi |

## Ảnh hưởng tới tải máy chủ

| # | Màn | Đang làm | Hướng kia |
|---|---|---|---|
| 13 | Tài liệu | Còn hàng "chờ index"/"đang xóa" thì 30 giây tải lại một lần (brief ghi 5 giây) | đúng 5 giây — một tab mở sẵn gửi ~17.000 lượt/ngày vì hàng "đang xóa" sống tới 24 giờ |
| 14 | Ghi nhớ | Làm mới cả 3 tab mỗi 20 giây để số trên tab không cũ | chỉ tab đang xem (giảm 2/3 lưu lượng) |
| 15 | Bảng điều khiển | `/documents` và `/health` nằm trong nhịp 20 giây (theo brief) | bỏ ra: mất dòng "N đang xử lý" và chip cũ của thẻ sức khỏe |
| 16 | Model | Không tự tải lại `/models` | thêm nhịp 60 giây (2 dòng) |

## Thêm sau vòng kiểm xuyên màn hình (16/09)

| # | Chỗ | Đang làm | Hướng kia |
|---|---|---|---|
| 17 | Chat ↔ Cài đặt | Bật "Ghi nhớ mặc định" trong Cài đặt rồi sang Chat: chip vẫn "tắt" cho tới khi bấm "Cuộc trò chuyện mới" hoặc tải lại trang — **đúng hành vi cũ** (trang cũ cũng chỉ áp cho lượt chat mới) | đọc lại `prefs.memoryDefault` mỗi lần vào `#/chat` không có id (1 dòng) — hợp trực giác hơn nhưng ai tắt tay giữa phiên sẽ thấy nó tự bật lại |
| 18 | Toàn app | Chủ đề và hiệu ứng động không đồng bộ giữa hai tab (trang cũ cũng vậy) | shell nghe thêm khóa `lac.prefs` |
| 19 | Tài liệu, OCR ở 390px | Bảng cuộn ngang được nhưng không có dấu hiệu còn cột bên phải | thêm bóng mờ mép phải |
| 20 | Ghi nhớ, thành viên | Thanh chọn tab chỉ còn một ô (vì member chỉ xem được 1 tab) | ẩn hẳn thanh tab, chỉ để tiêu đề |

Đã kiểm và **bác** một phát hiện: nút "Thêm người dùng" khi tắt chế độ tài khoản — nút nằm trong DOM
nhưng cả thanh công cụ đã ẩn, người dùng không thấy (`addVisible: false`).

## Nợ kỹ thuật đã ghi nhận, không chặn

- `common.js` bị đóng băng theo yêu cầu, nên `ERROR_HINTS` thiếu `INTERNAL_ERROR` và lỗi 5xx chung;
  các màn tự dịch tại chỗ. Một dòng trong `common.js` sẽ bỏ được các bản vá đó.
- `sendJson` bỏ mất trường `detail` của lỗi 422, nên màn Người dùng không phân biệt được "giá trị sai"
  với "máy chủ chưa nhận trường này".
- `Uploads.start()` chưa nhận `signal` của view (dialog xung đột vẫn tự đóng khi đổi route nên không hỏng).
- Bấm đúp chuột thật lên một mục menu có thể rơi trúng lớp phủ của dialog vừa mở — đã chặn bằng mốc
  350 ms trong `components.js`.
- `views/chat.css` đặt vài tên class không gắn tiền tố (`.doc-name`, `.doc-meta`, `.docs-head`); các màn
  sau đều dùng tiền tố riêng (`dv-`, `mv-`, `dash-`, `ocr-`, `bot-`, `mdl-`, `usr-`, `set-`, `ck-`).
- Màn Model dùng `:has()` để nới rộng một dialog (Chrome 105+, Safari 15.4+); nơi chưa hỗ trợ thì dialog
  vẫn dùng được, chỉ giữ bề ngang 440px.
