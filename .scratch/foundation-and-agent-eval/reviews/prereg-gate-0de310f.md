GỘP ĐƯỢC (bản đăng ký kiểm 66 bài đủ, mốc so sánh đúng, `analyze.py` chạy trọn và rẽ đúng trên dữ liệu thay thế; không cần chạy lại)

# Duyệt bản đăng ký kiểm trước khi gộp N1 — `kept/agent-eval-v0.8-n1-gate/PREREGISTRATION.md` + `analyze.py`, main 0de310f — fable 5.1, 29/10/2026

| Mục | Kiểm | Kết quả |
|---|---|---|
| Commit đo 717e4d3 | như bài duyệt `int-20-n1-main-717e4d3.md`: code = N1 đã đo | đúng |
| Mốc 19 bài dán = `v0.8-arb-n1` (d40d4e0) | cùng code `backend/`, cùng bộ bài v0.8 (sha được P kiểm) | hợp lệ |
| Mốc 47 bài không dán = `v0.7-3d-iso-base-full` (94e321f) | N1 chỉ chạm tin cuối là đoạn dán (test ghim); ticket 27 không đổi prompt khi không có lỗi (M0 = M1 62/62, đo 29/10); 47 bài trong v0.8 giống v0.7 (tệp bài chỉ +4 dòng); ba băm bằng nhau được P kiểm | hợp lệ |
| So lần đủ bộ với lần 19 bài có hợp lệ không | dưới cô lập, #3-D đã chứng minh 15 bài dán trong lần 62 bài trùng lần 15 bài 15/15; lần phân xử N1 r1 = r2 9/9 từng byte | hợp lệ |
| G1 "66/66 câu trả lời và chuỗi lệnh giống mốc từng byte" so với script | `same()` so `answer` và danh sách (tên, tham số) của mọi `tool_call`; `differ` gộp hai nhóm; `merge` = P và G1 | khớp văn bản |
| Chạy thử | dựng lần chạy thay thế bằng cách ghép 19 dòng của `v0.8-arb-n1` + 47 dòng của `v0.7-3d-iso-base-full`: exit 0, P đúng cả 7, G1 đúng, điểm 58 = 18 + 40, khớp mốc; sửa một chữ ở câu trả lời hist-06 → G1 sai, `differ = [hist-06]` | script bắt đúng |
| Opus chạy trước khi tôi duyệt | phép kiểm là "giống hệt", không có chỗ phán đoán; nếu bản đăng ký cần sửa thì chạy lại | chấp nhận được; nếu bản này đạt thì không cần chạy lại |

## Nhỏ, không chặn

- G1 là bằng nhau từng byte, nên một bài khác chỉ vì model không tái lập được (dù cô lập) cũng làm trượt. Mọi lần cô lập tới nay
  đều r1 = r2, nên hợp lý; nếu có bài khác mà khác chỉ ở chữ, báo cáo phải nói rõ là khác nội dung hay khác tái lập, chủ dự án quyết.
- Mốc 47 bài nằm ở lần chạy v0.7 (sha bộ bài khác): P không so sha với mốc đó là đúng, vì đã kiểm 62 bài cũ không đổi.
