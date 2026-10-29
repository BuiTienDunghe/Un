CẦN SỬA (một chỗ: R2 đếm cả doc-57, bài mà N1 theo cách dựng không bao giờ hơn C7, nên kết luận "chọn N1, bỏ C" gần như không thể xảy ra; còn lại đủ và đúng, `analyze.py` chạy trọn trên dữ liệu thay thế và áp luật đúng như văn bản)

# Duyệt bản đăng ký đợt phân xử N1 / C7 — `kept/agent-eval-v0.8-paste-arbitration/PREREGISTRATION.md` + `analyze.py`, main 9062a9e — fable 5.1, 29/10/2026

Đối chiếu với tong-hop.md mục "Đề xuất", lời duyệt của chủ dự án, và ba bài duyệt nhánh. Không chạy model.

## Từng mục

| Mục | Kiểm | Kết quả |
|---|---|---|
| Ba commit đo | `613f0b2` = merge(62e7ca0, 0adc697); `d40d4e0` = merge(613f0b2, 32a2d50); `bc93975` = merge(613f0b2, bc2b8f9); patch-id của diff nền→N1 trùng diff 62e7ca0→32a2d50 (`a0f349ba…`), nền→C7 trùng 62e7ca0→bc2b8f9 (`87844d00…`) | đúng là nền + đúng nhánh đã duyệt, không thêm gì |
| Luật so với tong-hop | R1 "N1 thua C7 ≥ 2 bài giữa" thu hẹp về 3 bài mù (theo bài duyệt 0adc697); R2 "N1 ≥ C7 mọi bài, không bài đạt nào lùi"; R3 doc-50 lệch > 15 % | khớp, có thêm R0 và chặn cắt ngữ cảnh 14 500 |
| Script so với văn bản | R1 = `len(lose_middle) >= 2` trên `NEW_MIDDLE` được tính; R2 = không `lose_any` và không `regress` trên 19 bài; R0 = không R1 không R2; R3 = \|doc-50 − 10 900\| > 1 635; "N1 đạt bài giữa khi đạt cả hai lần" = `n1_pass`; loại bài có vòng > 14 500 ở nhánh nào | khớp từng điều |
| Tập bài giữa tính lại từ tệp bài | `in_middle` (khớp đầu của mọi mẫu ở 0,40–0,60) trên tasks.jsonl của 613f0b2 ra đúng 6 cũ + 3 mới, doc-57 ngoài | đúng |
| Điều kiện P | ba băm, bộ bài v0.8 một sha, 15 bài cũ trùng v0.7 (đọc từ manifest của `v0.7-3d-iso-base-r1`, đường dẫn meas-94e321f còn), cờ cô lập, khoá manifest phân biệt nhánh, `tasks_run` đúng thứ tự, N1 thật sự nạp nguyên | script kiểm đủ |
| Chạy thử | dựng dữ liệu thay thế từ `v0.7-3d-iso-base-r1` + 4 bài mới nhân bản từ doc-49, hai kịch bản: (a) C7 hơn N1 ở 1 bài mù → P đúng, R0; (b) C7 hơn ở 2 bài mù → R1. doc-50 đặt 12 600 → R3 bật | exit 0 cả hai; mọi điều kiện P đúng trên dữ liệu đó; luật rẽ đúng |
| Nền chạy lại 15 bài cũ | đã sửa theo bài duyệt 0adc697, lý do (ticket 27) đúng, có p1 để đối chiếu | đủ |
| Ghi riêng | tỉ lệ ký tự/token vòng đầu N1, vòng > 16 384, `turn_budget` tách riêng, số mồi doc-53/56, #2 bắn, lỗi lệnh | đủ cả bốn điều tôi nêu |

## Chỗ phải sửa — R2 và doc-57

Bản đăng ký tự nói ở doc-57: "C7 đọc tới đáp án ở lần thứ năm; nền và N1 thì không bao giờ tới". Nhưng R2 đếm `lose_any`
trên **cả 19 bài**, gồm doc-57. Vậy chỉ cần C7 đọc tới đoạn 13 và trả lời đúng ở doc-57 (cùng cơ chế với p4, điều opus tự
dự đoán sẽ xảy ra) là R2 sai, bất kể N1 làm gì ở 18 bài còn lại. Kết quả "chọn N1, bỏ C" khi ấy chỉ còn xảy ra nếu C7 cũng
trượt bài dài, tức luật trộn hai câu hỏi khác nhau: "N1 có bỏ sót khúc giữa không" (câu của đợt này) và "ngoài trần N1 thì
làm gì" (câu của P3, đã tách ra trong tong-hop). Hệ quả thực tế: gần như mọi kết quả rơi vào R1 hoặc R0.

Cách sửa, một dòng mỗi nơi: R2 đếm trên 18 bài N1 áp dụng được (`PASTE_TASKS` trừ `LONG`), doc-57 báo bên cạnh như "bài
ngoài trần: nhánh nào tới được". `regress` giữ nguyên 19 bài (ở doc-57 N1 = nền theo p6, vô hại). Nếu opus muốn giữ R2 trên
19 bài thì phải viết rõ trong luật rằng R2 đòi C7 cũng không tới được doc-57, và nói đó là chủ ý — tôi không thấy lý do.

## Nhỏ, không chặn

- Điều kiện P "N1 không có lần đọc đoạn dán nào": dưới N1 không có phiếu nên model không biết id `paste_…`; chỉ một lệnh bịa
  đúng tiền tố mới làm P sai và vô hiệu cả đợt. Xác suất gần 0; nếu muốn chắc thì đo "nạp nguyên" bằng token thôi, còn lần đọc
  chỉ báo.
- Chặn 14 500: C7 với một lần thử lại (8 lần đọc ≈ 15,1k) bị loại khỏi luật. Đúng chủ ý "mất câu hỏi trông như bỏ sót khúc
  giữa", nhưng báo cáo phải in danh sách `not_counted_near_window` ngay cạnh R1/R2, vì bài bị loại dễ là bài khó nhất.
- "Bài đạt nhờ đoán tính là trượt" là bước tay ngoài script: báo cáo ghi từng bài bị đổi và vì sao, tôi xác nhận ở bài duyệt
  báo cáo.
- `DECOYS` doc-56 có `30 ngày`: câu trả lời đúng kiểu "không phải 30 ngày như tạm dừng thường mà 75 ngày" sẽ bị đếm là có
  số mồi. Chỉ là ghi riêng, nhưng khi đọc cột đó phải mở câu trả lời.
- `__pycache__` như mọi lần; chạy với `PYTHONDONTWRITEBYTECODE=1`.
