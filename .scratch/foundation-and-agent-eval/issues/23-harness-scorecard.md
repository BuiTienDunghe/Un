# 23 — Bảng điểm harness: đúng, hiệu quả, bền, minh bạch; lưu lịch sử để so qua các phiên bản

Status: đã giao — Nhân viên của Ún 3 (sau khi báo xong baseline v0.3)
Type: task
Blocked by: — (đọc artifact sẵn có; không cần GPU)

## Vì sao

Chủ dự án (28/10): "harness là điểm nổi bật nhất — xử lý tốt, hiệu quả". Hiện Agent Eval chỉ cho một số: số bài
đạt. Phần lớn chỉ số khác đã nằm rải trong artifact (`manifest.json`, `task_results.jsonl`, `events.jsonl`,
`summary.json`) nhưng không ai gom. Chủ dự án duyệt dựng bảng điểm (28/10 00:15).

## Việc

1. `backend/scripts/agent_eval_scorecard.py` (hoặc một mode của runner): đọc thư mục một lần chạy, in và ghi
   `scorecard.json` + một bảng markdown. Không gọi model, không cần GPU.
2. Bốn chiều — mỗi chỉ số ghi rõ cách tính từ trường nào của artifact:

| Chiều | Chỉ số |
|---|---|
| Đúng | tỉ lệ đạt (tổng và theo loại bài); bài bịa (trượt mục "không tìm thấy"/must_not); trích nguồn đúng; trích nguyên văn (`citation_verbatim`) |
| Hiệu quả | token vào/ra mỗi bài (cộng các vòng); số vòng model mỗi bài; số lần gọi công cụ trên mỗi bài **giải được**; độ trễ trung vị và p95 mỗi bài |
| Bền | đếm `stop_reason` (final / max_steps / turn_budget / turn_budget_exhausted); đếm mã lỗi công cụ; tỉ lệ `BAD_ARGUMENTS`; số lần cắt kết quả theo mục (`omitted`) |
| Minh bạch | tỉ lệ lượt tái dựng được trọn: mọi vòng model có token + độ trễ, mọi lần gọi công cụ có tên + hình dạng tham số + mã lỗi/kết quả |

3. **Lịch sử:** mỗi lần chạy nối một dòng vào một tệp lịch sử được track (vd
   `data/evaluation/results/kept/agent-eval-scorecard-history.jsonl`): commit, phiên bản dataset, bộ chấm,
   model, nhiệt độ, lạnh/nóng, các chỉ số. Lệnh so `--compare <run_a> <run_b>` in chênh từng chỉ số và từng bài.
   **Chỉ so khi cùng phiên bản dataset và bộ chấm**; khác thì in cảnh báo, không in chênh.
4. Ghi giới hạn ngay trên bảng: cỡ mẫu (1 bài ≈ 2,1 điểm % ở 48 bài); quy tắc gỡ model trước mỗi lần đo; so
   từng bài chỉ chắc tới chỗ khác đầu tiên (ticket 10).
5. Chạy ngược trên các lần đã có trong `kept/` (v0.2 A/B/E/F, 16-A/B, baseline v0.3) để lịch sử có điểm xuất phát.
6. Test: tính chỉ số trên artifact giả nhỏ; so hai lần khác phiên bản dataset thì từ chối.

## Nghiệm thu

Bảng điểm của baseline v0.3 in đủ bốn chiều; lịch sử có các lần cũ; fable duyệt cách tính.

## Comments
