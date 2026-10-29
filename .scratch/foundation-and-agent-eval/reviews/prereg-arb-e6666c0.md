GỘP ĐƯỢC (chỗ CẦN SỬA ở 9062a9e đã sửa đúng; cả ba kết luận R0, R1, R2 giờ đều có thể xảy ra; `analyze.py` chạy trọn và rẽ đúng trên ba kịch bản thay thế)

# Duyệt lại bản đăng ký đợt phân xử N1 / C7 — main e6666c0 — fable 5.1, 29/10/2026

Chỉ kiểm phần đổi so với 9062a9e (`git diff 9062a9e e6666c0` trong thư mục kept), phần còn lại giữ nguyên kết luận ở
`prereg-arb-9062a9e.md`.

| Mục | Kiểm | Kết quả |
|---|---|---|
| R2 đếm "C7 đạt mà N1 trượt" trên 18 bài (trừ doc-57); "nền đạt mà N1 trượt" vẫn 19 bài | văn bản và `lose_any` (`t not in LONG`) khớp; `regress` giữ 19 | đúng đề nghị |
| doc-57 báo riêng | `long_passed` theo nhánh | đủ |
| Điều kiện "N1 nạp nguyên" chỉ xét token; lần đọc đoạn dán dưới N1 chỉ báo | `n1_inlined_all_but_long` bỏ vế `paste_reads`; thêm `n1_paste_reads` | đúng |
| Báo cáo in `not_counted_near_window` cạnh R1/R2 | ghi trong khối "Sửa trước lần chạy" | đủ |
| Chạy thử ba kịch bản trên dữ liệu thay thế (từ `v0.7-3d-iso-base-r1`, 4 bài mới nhân bản) | (a) C7 hơn N1 ở 1 bài mù → R0; (b) hơn ở 2 bài mù → R1; (c) C7 đạt doc-57 và doc-49, N1 đạt mọi bài C7 đạt trong 18 bài → **R2**, `long_passed.c7 = [doc-57]` | exit 0 cả ba; P đúng; mỗi kịch bản rơi đúng một mã |

Hai việc để vào báo cáo, như opus đã ghi: mở từng câu trả lời doc-56 trước khi đọc cột số mồi; ghi tay từng bài bị đổi vì đoán,
tôi xác nhận ở bài duyệt báo cáo.

Điều kiện chạy: bản đăng ký ghi "GPU riêng" và `--gpu-shared no`. Lúc này GPU có trò chơi đang chạy (theo opus: 26 %, 885 MiB).
Chạy trong lúc đó thì số độ trễ (p7, p8) không sạch và `gpu_shared` phải ghi đúng; có chạy hay chờ là việc chủ dự án quyết,
không phải của bài duyệt này.
