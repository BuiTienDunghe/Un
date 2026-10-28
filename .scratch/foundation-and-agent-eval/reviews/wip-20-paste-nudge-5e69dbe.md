GỘP ĐƯỢC

# Duyệt lại wip/20-paste-nudge 5e69dbe (sửa theo `wip-20-paste-nudge-2955861.md`) — fable 5.1, 28/10/2026

Đã kiểm: diff 2955861..5e69dbe (2 tệp: `unread_paste.py` +21/−6, test +23). Bộ giữ im, không chạy model. Tệp này không nói
gì về bài mới của NV3.

| Kiểm | Kết quả |
|---|---|
| `from_chunk` sau khi sửa | đoạn chưa đọc nhỏ nhất **sau** đoạn đã đọc lớn nhất; chỉ khi không còn đoạn nào sau mới lùi về đoạn chưa đọc nhỏ nhất. Tôi thử trực tiếp trên đoạn dán 19 đoạn: chưa đọc gì → 0; đọc 0–2 → 3; đọc 7–9 → 10; đọc 0–2 và 7–9 → 10; đọc 16–18 → 0; đọc hết → không bắn |
| Lời nhắc | cả hai mẫu kết bằng "Rồi trả lời lại như lần đầu, không nhắc tới lời nhắc này."; vẫn không nêu số đoạn, vẫn một lệnh `read_document` cụ thể với `n` = `READ_MAX_CHUNKS` |
| Phần còn lại của nhánh | không đổi so với 2955861 (đã duyệt): cờ riêng, điều kiện kép, chỉ nhánh trả lời tự do, giữ `final_reserve` |
| Test | 234 xanh, 13 bỏ qua (toàn bộ `tests/test_agent*.py`); test mới cho ca nhảy 7–9 → 10 và ca ba đoạn cuối → 0 |
| Worktree | sạch, HEAD 5e69dbe |

Ghi chú cho bản đăng ký: câu "không nhắc tới lời nhắc này" là cách giảm lộ, chưa phải bằng chứng; vẫn đếm câu lộ như đã
đăng ký.

Về đường dẫn: thư mục gốc `C:\Users\dungbt06\local-ai-core` đang ở nhánh `wip/26-anthropic-provider` (chuyển lúc 20:05),
nên các tệp duyệt của tôi từ đó nằm untracked ở đó; opus đã chép sang `coord-main` và commit (6fce071), cứ tiếp tục như
vậy. Phiên làm ticket 26 đừng `git add -A` trong thư mục gốc kẻo cuốn các tệp này vào nhánh 26.
