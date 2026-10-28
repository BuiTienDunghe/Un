GỘP ĐƯỢC

# Duyệt lại wip/20-paste-search 92f5796 (phiếu 3' sau quyết định "vậy bỏ" của chủ dự án) — fable 5.1, 28/10/2026

Đã kiểm: diff c270ded..92f5796 (2 tệp: `pastes.py` `slip()` + docstring +21/−12; `test_agent_pastes.py` +21/−14). Bộ giữ im,
không chạy model. BM25 và `_search_documents` không đổi so với c270ded (đã duyệt GỘP ĐƯỢC). Tệp này không nói gì về bài
mới của NV3.

| Kiểm | Kết quả |
|---|---|
| Phiếu dựng trên doc-39 | đúng một lệnh `read_document(`, mở bằng "gọi thẳng …from_chunk=0, n=3" như #3-C; không có `search_documents(`; thêm đúng một câu "search_documents tìm được trong văn bản dán, và kết quả cho chunk_index để đọc thẳng đoạn đó"; không còn "không cần search_documents trước", "không tìm thấy nó", "Cần một chi tiết", "tóm tắt, liệt kê" |
| Phần giữ của #3-C | câu trần `n` 1–3; không số đoạn; "đã đủ thì trả lời luôn" đứng trước lệnh đọc; `next_from_chunk` tới null |
| Khung lời phiếu | 804 ký tự (#3-C 780; c270ded 1 025) |
| `tools_sha256` / `AGENT_GUIDE` thô | `153209652c06…` / `6f80aa8ca420…`, không đổi |
| Test | 219 xanh, 13 bỏ qua (toàn bộ `tests/test_agent*.py`); test mới chặn phiếu có `search_documents(` hoặc hơn một `read_document(` |
| Worktree | sạch, HEAD 92f5796 |

Đúng với quyết định chủ dự án ("vậy bỏ", ghi ở `paste-directions-2026-10-28.md`): lệnh cụ thể duy nhất vẫn là đọc từ đoạn
0; tìm chỉ được nhắc tới như một khả năng. Hệ quả cho bản đăng ký lại phần +1+3': dự đoán phải nói model **có** gọi tìm hay
không là điều chưa biết (ở #3-C, 5/5 lần mở đầu làm đúng lệnh cụ thể duy nhất); C3/C4 giữ nguyên, nên "C trượt vì không ai
gọi tìm" là một kết quả có thể, và báo cáo phải tách "không gọi tìm" khỏi "tìm không ra".
