# 47 — MCP, cắm công cụ ngoài

Status: mở
Type: task
Blocked by: —

Bản chất: chuẩn chung để Ún dùng công cụ người khác viết mà không phải viết riêng từng cái.

Việc: Ún làm client, nạp vào `ToolRegistry`; mặc định tắt và danh sách server rỗng; mỗi server khai danh sách công cụ được
phép; kết quả đi qua cùng lớp chống chèn lệnh và trần độ dài như công cụ khác. Chỉ thử với server giả viết trong test, không kết
nối dịch vụ ngoài. Ghi rõ rủi ro bảo mật và mức thêm công cụ làm model chọn sai (đo khi có GPU).
