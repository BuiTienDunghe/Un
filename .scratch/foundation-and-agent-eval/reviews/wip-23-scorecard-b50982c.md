CẦN SỬA (nhỏ, một chỉ số) — hoặc GỘP ĐƯỢC nếu opus chọn cách đổi tên thay vì đổi định nghĩa; xem mục 1.
NV3 báo xong ticket 23: xem Comments 00:35 (định nghĩa) và 00:55 (kết quả).

# Duyệt wip/23-scorecard b50982c — fable 5.1, 28/10/2026

Đã kiểm ở checkout chính và worktree của NV3 (cây sạch sau khi tôi xoá `scorecard.json` mà lần chạy
thử của tôi để lại): đọc trọn `agent_eval_scorecard.py` (416 dòng), diff runner, 8 test; chạy 75 test
(scorecard + agent_eval) xanh; chạy bảng điểm thật trên `v0.2-16-B-cold` và `--compare` hai cặp (cùng
dataset: in chênh, chỗ khác đầu tiên hist-08; khác dataset: từ chối đúng mã 2). Tính lại từng ô của
`v0.2-16-B-cold` bằng tay: đạt 34/40, trích nguồn 11/15, cắt theo mục 5, TOOL_UNAVAILABLE_HERE 3,
stop_reason final 40, minh bạch 40/40 — khớp bảng in ra.

## Sáu điểm NV3 hỏi

| # | Kết luận | Lý do |
|---|---|---|
| 1 | **Định nghĩa "bịa" chưa đủ, và đang đếm nhầm thứ khác** — cần sửa | Tôi đếm lại trên 38 lần đã lưu: 18 lần có "bịa" > 0, trong đó 15 lần là `doc-19`/`doc-12` trượt **chỉ** mục `not_found` — đúng lỗi regex của bộ chấm v0.2 đã ghi ở REPORT ("không trả về thông tin" chưa được nhận), không phải model khẳng định sai. Chỉ 3 lần (`doc-31`, `must_not_mention`) là model nói ra con số bị cấm. Tức cột "bịa" của lịch sử hiện phản ánh bộ chấm nhiều hơn model. |
| 2 | Đúng, giữ | "Tổng lượt gọi ÷ số bài đạt" là chi phí cho một thành công; nó gộp cả tỉ lệ đạt vào nên không độc lập với cột Đúng, nhưng có in kèm TB của riêng bài đạt, và định nghĩa viết trước khi chạy. Không đổi. |
| 3 | Đúng | Bốn điều kiện đọc đúng trường thật; `model_round` có token/độ trễ từ UsageRecordingRouter nên lấy theo vòng là cách duy nhất đúng trong eval. 0% trước 16 / 100% từ 16-B là phát hiện thật: harness trước 16 không ghi `arguments_shape`, `error_code`, `stop_reason`. |
| 4 | Đúng | `ollama_loaded_at_start` lấy TRƯỚC khi probe nạp model, đúng thứ tự trong `main()`. Lần cũ chép từ log GPU, có nguồn ghi từng dòng; không rõ thì để trống, đúng tinh thần "không đoán". Bằng chứng r1-cold (không model nào nạp) = r6 (model nhúng còn nạp) 40/40 là câu trả lời cho câu hỏi tôi nêu ở 1a-v2: model nhúng còn nạp không làm lệch lần lạnh, ít nhất ở cặp này. |
| 5 | Đúng | Khai báo + ảnh nvidia-smi là cách duy nhất, vì nvidia-smi không thấy tiến trình khác gọi chung Ollama. `--compare` không so độ trễ khi khác hoặc không rõ: đúng, và tôi đã thấy nó in "không so: n/a / n/a" cho cặp r1-cold/16-B. |
| 6 | Đúng, chấp nhận lệch chữ | Dòng lịch sử phải mở lại được artifact; lần nháp nằm ngoài git. Khoá trùng (run_id, commit) và sắp theo started_at đúng. |

## Chỗ cần sửa (mục 1)

Hai cách, opus/chủ dự án chọn; cả hai đều phải ghi vào Comments của ticket kèm lý do (bằng chứng doc-19) và
chạy lại backfill 38 dòng (cùng một lệnh, vài giây):

- (a) **Đổi định nghĩa**: `fabricated` = số bài trượt `must_not_mention` (model nói ra điều bị cấm — bằng chứng
  mạnh); thêm cột `not_found_missed` = số bài trượt `not_found` mà không trượt `must_not_mention` (chưa nói
  rõ "không tìm thấy", hoặc bộ chấm chưa nhận câu). Lịch sử và `--compare` dùng `fabricated`. Ưu: cột "bịa"
  đúng nghĩa. Nhược: khác chữ ticket và bản 00:35 — nhưng đây là định nghĩa báo cáo, không phải giả thuyết đo,
  và bằng chứng cho thấy định nghĩa cũ đo sai thứ.
- (b) **Giữ định nghĩa, đổi tên** cột thành "trượt tiêu chí phủ định (not_found / must_not_mention)" và bỏ chữ
  "bịa" khỏi bảng, README, RESULTS. Ưu: không đụng bản 00:35. Nhược: chỉ số vẫn trộn lỗi bộ chấm với lỗi model.

Ý tôi: (a). Dù chọn gì, dòng RESULTS.md hiện ghi "fabricated" cho các lần v0.2 cần sửa theo.

## Hai điều không chặn

- `v0.2-1a2-A/E/F` để `gpu_shared` trống. Có bằng chứng để điền `false`: lượt đo cuối của 09 kết thúc 22:28:10,
  ba lần này chạy 22:31–22:39 khi stack 8200 mở nhưng không đo gì (tôi đã đối chiếu mốc thời gian khi duyệt
  1a-v2). Tuỳ NV3 ghi với nguồn "ticket 09 + đối chiếu fable 28/10", hoặc để trống.
- Runner gọi `scorecard(out_dir)` không kèm `recorded_conditions()`: đúng cho lần mới (manifest tự có
  `ollama_loaded_at_start` khi `--probe`); lần chạy không `--probe` thì lạnh/nóng = không rõ, đúng ý.

## Giới hạn của lượt duyệt

Không kiểm 34 dòng `loaded_at_start` chép từ log GPU (log nằm ngoài repo); tin theo nguồn ghi từng dòng.
