# Không gian Nghiên cứu — những chỗ chờ chủ dự án chốt

Mỗi mục là một chỗ README hứa nhưng bản dựng 11/10 **không làm** hoặc **làm theo một hướng** mà đổi hướng
kia là việc có chi phí rõ. Không mục nào là lỗi.

## Chưa làm — cần quyết định hướng

| # | Chức năng README | Vì sao chưa làm | Các hướng |
|---|---|---|---|
| 1 | **Thẻ tham chiếu `[n]`** trong PDF → card "Có trong kho / Chưa có · Thêm", nút Mở cạnh bên | README nói resolve qua Crossref/OpenAlex/arXiv — cần Internet; hệ chạy LAN offline (lý do bỏ Google Fonts ở Phần 1) | **A.** Khớp cục bộ: cắt mục References bằng regex, so tiêu đề với kho bằng chuỗi mờ (không mạng, trúng ~70–80%, sai khi tiêu đề bị ngắt dòng). **B.** Gọi Crossref/OpenAlex khi có mạng, cache kết quả vào DB (đúng hơn, thêm phụ thuộc mạng + rate limit). **C.** Bỏ hẳn, chỉ giữ tìm trong kho bằng ⌘K. |
| 2 | **AI tự gộp cụm** và **gán nhãn quan hệ** (Xây trên / Cùng bài toán / Chung backbone) với câu trích + trang | Cần một lượt LLM đọc toàn kho (N paper × tóm tắt + related work), chưa có mốc đo đúng/sai; chạy 9b mất nhiều phút | **A.** Giữ thủ công (đang làm): người dùng tạo cụm, kéo paper vào, thêm kết nối tay. **B.** Một nút "Gợi ý cụm & kết nối" chạy LLM trên các `summary.brief` + mục Related Work (trang 2), hiện đề xuất để duyệt từng dòng như Ghi nhớ (thêm ~1 ngày, cần worker vì chạy lâu). **C.** Chỉ gợi ý kết nối (edge) từ chuỗi khớp tiêu đề trong References (rẻ, không cần LLM, nhãn mặc định "Xây trên"). |
| 3 | **"Hỏi về hình này"** (gửi ảnh cắt vào chat) | Cần model vision (vai trò `vision` có trong registry nhưng chưa dùng ở web) + endpoint nhận ảnh | **A.** Cắt vùng từ PNG trang theo bbox người dùng kéo, gửi `/research/chat` kèm ảnh base64 → vai trò vision. **B.** Bỏ. |
| 4 | **Tóm tắt tự chạy nền** sau khi index ("Xử lý nền: OCR → metadata → outline → tóm tắt") | Chưa có worker cho việc này; model 9b 30–120 s/paper | **A.** (đang làm) gọi tay: nút / mở panel Tóm tắt lần đầu. **B.** Thêm task vào worker index: sau khi index xong tự tóm tắt (thêm hàng đợi `research_summary`, dễ nghẽn Ollama khi thả 10 PDF). |
| 5 | **Highlight trên PDF scan** (không có lớp chữ) | `words` rỗng → không bôi đen được; OCR có text theo trang nhưng không có toạ độ từng từ | **A.** Chấp nhận: ô đọc báo "PDF scan — chưa bôi đen được, vẫn hỏi AI được". **B.** Lưu bbox từ GLM-OCR (nếu model trả) vào `DocumentPage` rồi dựng lớp chữ từ đó (phải sửa parser OCR). |
| 6 | **@Tên trong ghi chú** → chip "Gắn với" | Làm được client-side khi `short_name` khớp; đang làm ở mức khớp chuỗi đơn giản | Giữ, hoặc bỏ nếu thấy nhiễu. |

## Đã làm theo một hướng — đổi được

| # | Chỗ | Đang làm | Hướng kia |
|---|---|---|---|
| 7 | Render trang | PNG dpi 110 từ máy chủ, phóng bằng CSS tới 150% rồi tải lại dpi 160 | pdf.js trong trình duyệt: chữ nét ở mọi zoom, nhưng phải vendor ~1 MB JS, mở ngân sách `fetch(` và danh sách script trong test |
| 8 | Chat trong panel | Lịch sử chỉ trong phiên (không lưu conversation) | Lưu như `/rag/chat` (truyền `conversation_id`) để quay lại đọc tiếp — thêm cột `conversation_id` vào paper/project |
| 9 | Dự án | Lọc theo chủ sở hữu khi bật tài khoản (như hội thoại) | Dự án dùng chung cả nhóm (bỏ lọc owner) |
| 10 | Thêm paper từ link arXiv/DOI | 501 kèm câu "máy chủ chạy offline" | Cho phép khi có mạng: tải PDF arXiv về rồi đi tiếp pipeline (thêm `httpx` GET + kiểm tra kích thước) |
| 11 | Bố cục | `Shell.setLayout("full")`: ẩn sidebar + header của app, nút ← về `#/chat`; **đăng xuất không với tới** khi đang ở Nghiên cứu | Giữ header 58 của app (mất 58px dọc, lệch prototype) hoặc thêm nút đăng xuất vào bộ chọn dự án |
