Dự đoán. Viết lúc test trên `4936223` đang chạy, chưa thấy kết quả nào.

- Backend: 2.341 đạt, 14 xfail, 0 hỏng, giống lần chạy sáng trên cây làm việc. Lý do: code commit giống từng dòng; phần khác chỉ là docstring, tài liệu và đường dẫn của hai script.
- Gốc: 250 đạt, 1 bỏ qua (thiếu `mteb`).
- Worktree thiếu các tệp bị gitignore mà checkout chính có (bản sao BFCL, model...), nên có thể có thêm vài ca bị bỏ qua. Không ca nào được hỏng.
- Nếu có ca hỏng, nghi đầu tiên là test đọc đường dẫn tuyệt đối của checkout chính, hoặc đọc tệp không được track. Lúc đó phải tách ra: lỗi do môi trường worktree hay lỗi do commit.
