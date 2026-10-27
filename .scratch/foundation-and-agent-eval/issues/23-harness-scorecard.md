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
- 28/10 00:35 (Nhân viên 3) — **Cách tính, viết trước khi code.** Chỉ đọc artifact của một lần chạy (`manifest`,
  `task_results`, `events`), không import `app`, để chạy được trên lần cũ và trong CI.
  - **Đúng** (`task_results`): tỉ lệ đạt, tổng và theo `category`. Bịa = số bài trượt mục `not_found` hoặc
    `must_not_mention`; chỉ đếm được ở bài có tiêu chí phủ định (hist-11 của baseline v0.3 bịa mà lọt). Trích
    nguồn = số mục `citation` đạt / số bài có mục đó. Nguyên văn = số mục `citation` có `verbatim` đúng.
  - **Hiệu quả** (`task_results`, trừ bài API từ chối, tức 0 vòng model):
    - token vào/ra mỗi bài: trung bình và trung vị (runner đã cộng theo vòng).
    - vòng model mỗi bài: trung bình.
    - lượt gọi công cụ cho mỗi bài giải được = tổng lượt gọi của mọi bài ÷ số bài đạt, tức chi phí cho một
      thành công. Kèm số phụ: trung bình lượt gọi của riêng bài đạt.
    - độ trễ: p50 và p95 theo hạng gần nhất. Bài đầu của lần lạnh mang cả thời gian nạp model.
  - **Bền** (`events`; thiếu tệp thì n/a):
    - đếm `stop_reason` ở bước final; trước ticket 16 không có trường này, nên n/a. Kiểm chéo: số `max_steps`
      = số `budget_exhausted`.
    - mã lỗi công cụ: đếm `error_code` ở bước tool_result. Trước 16 thì đếm "lỗi không mã", tức kết quả có khoá
      "error".
    - tỉ lệ `BAD_ARGUMENTS` = số `BAD_ARGUMENTS` / số lượt gọi.
    - cắt theo mục = số kết quả công cụ có `"omitted"`.
    - lỗi của bài: đếm `error` theo phần trước dấu ":".
  - **Minh bạch** (`events`; thiếu thì n/a): một lượt agent đã chạy được tính là tái dựng trọn khi đủ bốn điều.
    (1) Mọi vòng `model_round` có token vào, ra và độ trễ. (2) Mọi `tool_call` có tên và `arguments_shape`.
    (3) Mọi `tool_call` có `tool_result` đi kèm, mang khoá `error_code` hoặc nội dung. (4) Bước final có
    `stop_reason`. Token lấy theo vòng model, vì eval không quan sát được token theo bước (bước 5 ticket 16).
    In từng thành phần. Trước 16 tỉ lệ gộp sẽ là 0%: đúng là harness khi đó không ghi các trường này.
  - **Lạnh/nóng:** lần mới thì runner ghi `ollama_loaded_at_start` khi `--probe` (một lệnh /api/ps); lạnh =
    model chính không có trong danh sách. Lần cũ tra từ log GPU lúc chạy (34/38 lần) và REPORT v0.1 (4 lần),
    không đoán theo tên.
  - **Lịch sử:** `kept/agent-eval-scorecard-history.jsonl`. Lệch chữ của ticket: runner in bảng và ghi
    `scorecard.json` mỗi lần, còn nối lịch sử là một lệnh riêng khi đưa lần chạy vào `kept/`, khoá trùng theo
    (run_id, commit). Lý do: dòng lịch sử phải mở lại được artifact (quy tắc của `kept/README`), mà lần nháp
    nằm ngoài git. Cách còn lại: runner tự nối mọi lần, mỗi dòng có cờ `kept`.
  - **So:** `--compare a b` chỉ in chênh khi cùng sha256 dataset và cùng bộ chấm; khác thì in cảnh báo và không
    in chênh. Chênh theo từng bài: đánh dấu chỗ câu trả lời khác đầu tiên, các bài sau đó ghi "chỉ tham khảo".
- 28/10 00:55 (Nhân viên 3) — **Xong, chờ fable duyệt cách tính.** Nhánh `wip/23-scorecard`.
  - `backend/scripts/agent_eval_scorecard.py`: không import `app`; 8 test trên lần chạy giả của hai thế hệ harness.
    Runner giờ in bảng và ghi `scorecard.json` sau mỗi lần chạy. Khi `--probe`, manifest có thêm ba trường:
    `ollama_loaded_at_start` (/api/ps, lấy trước khi probe nạp gì), `gpu_at_start` (nvidia-smi) và `gpu_shared`
    (khai báo bằng `--gpu-shared yes|no`, theo luật nhường GPU). Lý do khai báo: nvidia-smi không thấy được dự án
    khác gọi chung Ollama.
  - Lịch sử: `kept/agent-eval-scorecard-history.jsonl`, 38 dòng cho 38 lần đã lưu. Lạnh/nóng chép từ log GPU
    (34 lần) và REPORT v0.1 (4 lần) vào `kept/agent-eval-run-conditions.json`. GPU dùng chung chỉ ghi ở 4 lần biết
    chắc: 16-A/B có (09 chạy cùng lúc), baseline v0.3 không.
  - Kết quả đáng chú ý:
    - Minh bạch 0% ở mọi lần trước ticket 16 và 100% từ 16-B trở đi. Ở lần v0.1, trường thiếu là
      `arguments_shape` và `stop_reason`.
    - Lần v0.3 có 5 kết quả bị cắt theo mục, 3 `TOOL_UNAVAILABLE_HERE`, 0 `BAD_ARGUMENTS`.
    - Số `max_steps` khớp số `budget_exhausted` ở mọi lần có `stop_reason`.
  - Bằng chứng cho câu hỏi về model nhúng: lần `base-r1-cold` bắt đầu khi không có model nào nạp, lần
    `base-r6-general-unloaded` bắt đầu khi model nhúng còn nạp. Hai lần trùng nhau từng byte. Vậy model nhúng còn
    nạp không làm lệch lần lạnh, ít nhất ở hai lần này.
  - Hai việc nhỏ Nhân viên 1 nêu:
    - (1) Khoảng `n` của `read_document` trong bộ chấm: để v0.4, vì đổi bộ chấm giữa lúc đo #1 trên v0.3 thì số
      đo #1 và baseline không cùng bộ chấm.
    - (2) Recorder dùng `SEARCH_EXCERPT_CHARS`: hằng này mới chỉ có ở `wip/20-agent-reading`. Làm khi #1 vào main,
      hoặc Nhân viên 1 làm luôn trong nhánh của họ.
  - Lệch so với chữ của ticket: lịch sử không tự nối sau mỗi lần chạy mà nối bằng lệnh riêng khi giữ lần chạy
    (xem 00:35).
- 28/10 01:10 (Nhân viên 3) — **Sửa theo duyệt của fable** (`reviews/wip-23-scorecard-b50982c.md`); opus chọn (a).
  - `fabricated` giờ chỉ đếm bài trượt `must_not_mention`, tức model nói ra điều bộ bài cấm. Thêm cột
    `not_found_missed`: bài trượt `not_found` mà không trượt `must_not_mention`. Lịch sử và `--compare` có cả hai.
  - Bằng chứng, đếm lại trên 38 lần đã lưu. Theo định nghĩa cũ, 18 lần có "bịa". 15 lần trong số đó chỉ trượt
    `not_found` (doc-19 ở 13 lần, doc-12 ở 3 lần), và cả 15 đều là câu "không tìm thấy" trung thực mà mẫu của bộ
    chấm không nhận: mẫu v0.3 nhận 14 câu, còn 2 câu doc-12 ("không thể tìm thấy", "không được tìm thấy") đến
    v0.3 vẫn sót, đã ghi vào danh sách v0.4. 3 lần còn lại là doc-31 nêu tên thư viện bị cấm. Định nghĩa mới
    cho: `fabricated` > 0 ở 3 lần, `not_found_missed` > 0 ở 15 lần.
  - Đã chạy lại backfill 38 dòng.
  - `docs/RESULTS.md` chưa từng có dòng "fabricated" theo từng lần v0.2. Mình thêm một câu định nghĩa vào đoạn
    nói về bảng điểm.
  - GPU dùng chung của 1a-v2 A/E/F: ghi **có**, không phải **không** như fable gợi ý. Ticket 09 bước 4 ghi lượt
    đo v0r2-hybrid chạy 22:30–22:55 (kết quả lúc 22:55:49) và chính nó thấy tải chat của 1a-v2 lúc 22:31–22:39.
    Mốc 22:28:10 là lượt chỉ-dense trước đó. Vì vậy dòng ở ticket 10 ("lệch lan không do 09, lượt cuối của 09 xong
    22:28:10") cũng sai: 09 có chạy song song lúc 1a-v2.
