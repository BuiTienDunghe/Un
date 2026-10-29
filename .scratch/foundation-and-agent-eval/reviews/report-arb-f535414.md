ĐÚNG SỐ (mọi con số tôi tính lại từ tệp thô đều khớp báo cáo; đủ 15 điều kiện P; kết luận R2 đúng luật e6666c0; kiểm nguồn gốc: không bài nào đạt nhờ đoán, xác nhận)

# Duyệt báo cáo đợt phân xử N1 / C7 — `kept/agent-eval-v0.8-paste-arbitration/REPORT.md`, main f535414 — fable 5.1, 29/10/2026

Tính lại bằng script riêng (`verify_arb.py`, không dùng `analyze.py`/`analysis.json`) từ `task_results.jsonl` + `events.jsonl`
+ `manifest.json` của 4 lần chạy, `v0.7-3d-iso-base-r1`, hai tệp bài, `gpu_temperature.log`, `ollama_ps.jsonl`. Đã đọc trọn
câu trả lời của mọi bài đổi đạt/trượt giữa các nhánh và cả ba câu trả lời doc-56.

## Từng con số

| Mục báo cáo | Tính lại | Khớp |
|---|---|---|
| Điều kiện P: ba băm giống nhau ở 4 lần (`tools` 153209…, guide 6194cf…, system 385cb4…); bộ bài v0.8 một sha (35b39db4…); 15 bài cũ trùng v0.7 từng trường; `unload_between_tasks` 4/4; manifest nền không khoá, N1 `paste_inline.max_tokens` 12 288, C7 `paste_extra_rounds` 4; `tasks_run` 19 bài đúng thứ tự, lần 2 đúng 9 bài giữa; commit 613f0b2 / d40d4e0 / bc93975, worktree sạch, `gpu_shared` false, num_ctx 16 384, seed 42, nhiệt độ 0 | đúng cả 15 | ✓ |
| N1 nạp nguyên 18/18 (vòng đầu hơn nền ≥ 1 000 token), doc-57 vòng đầu bằng nền | đúng | ✓ |
| Bài bị loại vì > 14 500: không; vòng lớn nhất N1 10 561, C7 11 504, đều doc-55 | đúng | ✓ |
| R1 không (N1 thua C7 0 bài giữa mù); R2 có (18 bài: 0 bài C7 đạt mà N1 trượt; 19 bài: 0 bài nền đạt mà N1 trượt); R3 không (doc-50 vòng đầu 9 763, −10,4 %) | đúng từng số | ✓ |
| Điểm 19 / 15 cũ / 3 giữa mù / 6 giữa cũ / doc-57: nền 10 / 10 / 0 / 3 / trượt; N1 18 / 15 / 3 / 6 / trượt; C7 14 / 12 / 1 / 4 / đạt | đúng | ✓ |
| N1 lần 2: 9/9, câu trả lời giống lần 1 từng byte | đúng | ✓ |
| Trung vị độ trễ 12,1 / 5,5 / 11,8 s; tổng `tokens_in` 199 532 / 130 318 / 286 090 | đúng | ✓ |
| Bảng từng bài: đạt/trượt, số lần đọc đoạn dán, độ trễ làm tròn | 19 dòng × 3 nhánh khớp hết | ✓ |
| Dự đoán p1–p10: chỉ p5 sai (#2 bắn ở doc-47 dưới N1) | đúng; p10 kiểm trên 11 bài nền dừng trước trần | ✓ |
| #2 bắn: nền 3 (44, 47, 56), N1 1 (47), C7 4 (44, 47, 56, 57); không lỗi lệnh; không `turn_budget` | đúng | ✓ |
| Ký tự/token vòng đầu N1: 3,07 (doc-55) – 3,80 (doc-39), doc-50 3,72 | đúng | ✓ |
| Nạp lại trung vị 2,56 s | 2,56 ở ba lần đủ, 2,81 ở lần 2 | ✓ |
| GPU nóng nhất 79 °C, 09:58–10:13 | log 58 dòng, lớn nhất 79, đầu 09:58:57 40 °C, cuối 10:13:21 74 °C | ✓ |
| Năm bài C7 trượt: 0 lần đọc (40, 44, 54), 1 lần (47), dừng ở mồi (56); câu trả lời giống hệt nền | đúng cả 5 | ✓ |
| Bốn bài nền đạt nhờ câu ép vòng 4 (41, 46, 51, 53), C7 vẫn đạt | đúng | ✓ |
| C7 doc-50 lộ "chunk_index=14" | đúng | ✓ |

## Kiểm nguồn gốc (xác nhận)

Đã đọc 8 bài N1 đổi trượt → đạt (40, 44, 47, 49, 50, 54, 55, 56), 4 bài C7 đổi (49, 50, 55, 57) và 5 bài C7 trượt. Mọi lần
đạt nêu đúng số của văn bản kèm điều/mục (Điều 39, Điều 16 + 21, Điều 24, Mục 16, Phần 14, Điều 22…); không lần nào là
khoảng đoán hay câu rào. **Không bài nào bị đổi vì đoán.**

doc-56: cả bốn câu trả lời có số mồi. N1 trình bày Điều 9 (30 ngày, 150.000) rồi chỉ sang Điều 24 (75 ngày, 90.000) vì lý do y
khoa — đúng văn bản, số mồi chỉ là đối chiếu. Nền và C7 trả lời theo Điều 9 và tự nhận "trường hợp y tế không được đề cập rõ":
đây là ca "dừng ở mồi" đúng như bài được dựng.

doc-47 dưới N1: #2 bắt số 54.000.000 (= 3 × 18.000.000, model tự nhân), thử lại rồi trả lời đúng 36.000.000 theo Điều 10. Câu
mở "Xin lỗi, tôi đã nhầm lẫn" là lỗi lộ lời thử lại của #2 đã biết, không phải của N1.

## Nhận xét

- **Áp luật đúng, kết luận đúng.** Đây là lần đầu một nhánh của ticket 20 qua luật đăng ký trước, và qua với khoảng cách
  lớn (18 so với 14 và 10), trên bài mù 3/3. Rủi ro số một trong tong-hop ("bỏ sót khúc giữa" ở 9B) không xuất hiện ở bài nào
  tới 10 561 token.
- **Điều đợt này không nói:** 47 bài không dán chưa chạy lại trên N1 (chỉ test đơn vị); lịch sử hội thoại dài chưa có bài nào;
  nền và C7 chạy một lần. Lần chạy đủ 62 bài cô lập là thứ duy nhất còn thiếu trước khi gộp, như opus nêu.
- Về bốn cách A–D: số liệu ở đây chỉ phân biệt N1 với C7 trên phiếu #3-C; không có số nào so N1 trên phiếu #3 (main) với N1
  trên #3-C. Cách A vì thế là cách duy nhất gộp thứ chưa đo. Ý kiến tôi để ở báo cáo cho chủ dự án, không ở đây.
