ĐÚNG SỐ (66/66 câu trả lời và chuỗi lệnh giống mốc từng byte, tính lại độc lập; đủ điều kiện P; G1 đạt; điều kiện gộp ở `int-20-n1-main-717e4d3.md` đã thoả)

# Duyệt báo cáo kiểm trước khi gộp N1 — `kept/agent-eval-v0.8-n1-gate/REPORT.md`, main 23d7029 — fable 5.1, 29/10/2026

Tính lại bằng script riêng từ `task_results.jsonl` + `events.jsonl` + `manifest.json` của `v0.8-n1-gate-full`, hai mốc
`v0.8-arb-n1` và `v0.7-3d-iso-base-full`, và `v0.7-27-main-after-full`; không dùng `analyze.py`/`analysis.json`.

| Mục báo cáo | Tính lại | Khớp |
|---|---|---|
| Điều kiện P: commit 717e4d3, bộ bài v0.8 cùng sha với mốc dán (35b39db4…), 66 bài, ba băm bằng cả hai mốc (`tools` 153209…a75e500, guide 6194cf0f…, system 385cb475…), cô lập, `paste_inline.max_tokens` 12 288, không `paste_extra_rounds`, worktree sạch, `gpu_shared` false, qwen3.5:9b, num_ctx 16 384, seed 42 | đúng cả | ✓ |
| G1: 66/66 giống mốc, `differ` rỗng | 19 bài dán so `v0.8-arb-n1`, 47 bài so `v0.7-3d-iso-base-full`: 0 bài khác ở câu trả lời lẫn (tên, tham số) mọi lệnh; cờ đạt/trượt cũng trùng 66/66 | ✓ |
| Lỗi: không | không bài nào có `error` | ✓ |
| Điểm 58/66 = 18/19 + 40/47, bằng mốc | đúng | ✓ |
| Ngoài luật: 62 bài v0.7, main 45 → bản gộp 55; 10 bài đổi đều là bài dán, đều trượt → đạt; 47 bài khác giống main từng byte | đúng: doc-39, 40, 41, 43, 44, 46, 47, 48, 49, 50, không bài nào đạt → trượt; 47/47 trùng `v0.7-27-main-after-full` | ✓ |
| 10:31–10:40, GPU nóng nhất 80 °C | manifest 03:31Z–03:40Z; log 37 dòng, lớn nhất 80 | ✓ |
| Vòng lớn nhất 10 561 token (doc-55), nạp lại trung vị 2,81 s | đúng | (không trong báo cáo) |

## Nhận xét

- **Đúng luật, đúng số, điều kiện gộp đã thoả.** Bản gộp đưa lên main đúng thứ đã đo ở đợt phân xử và không đổi một câu nào
  ngoài 19 bài dán. Mốc mới của main sau gộp trên 62 bài v0.7 cô lập là 55/62 (cũ 45/62); trên 66 bài v0.8 là 58/66.
- Việc còn treo sau gộp, không chặn: hằng 12 288 theo num_ctx cứng; #2 tắt với đoạn dán nguyên văn (doc-47 cho thấy nó vẫn bắn
  được ở số viết khác dạng); lỗi lộ lời thử lại của #2; C7 lộ "chunk_index" không còn liên quan vì C7 không gộp; văn bản quá
  36 000 ký tự vẫn đi phiếu.
