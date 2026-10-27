GỘP ĐƯỢC

# Duyệt wip/20-agent-reading cd99811 (phần đo #1 trên v0.3) — fable 5.1, 28/10/2026

Phần code (3d5927a, 3515226, 8348f68) đã duyệt trước (gửi opus 02:xx): gộp được. Lượt này chỉ soát phần
đo: 12d7935 (cherry-pick baseline v0.3, tệp trùng), 199475a (đăng ký trước, commit 00:19:51, trước lần chạy
đầu 00:20:28), cd99811 (hai lần lạnh + REPORT + analyze.py).

## Số tính lại từ kept/ — khớp hết

| Đo | NV1 | Tôi tính lại |
|---|---|---|
| Baseline r1/r2, sau #1 r1/r2 | 35, 35, 34, 34 | 35, 35, 34, 34 |
| r1 = r2 (sau #1) | 48/48 | 48/48; baseline cũng 48/48 |
| 40 bài cũ: đạt, số câu đổi chữ | 34 → 29, 37/40 | 34 → 29, 37/40 |
| Bài lật | 7 tụt, 2 lên, 4 bài mới lên | đúng danh sách: tụt doc-10, 12, 19, 20, 26, hist-05, hist-08; lên doc-31, stat-02; mới doc-33, 34, 35, 37 |
| `read_document` | 5 bài gọi, mỗi bài 1 lần, 0 BAD_ARGUMENTS, không bài cũ nào gọi | đúng; `n` = 5 ở doc-33 và doc-36 (chặn xuống 3) |
| tokens_in lớn nhất một lượt | 3 846 (23,5%) | 3 846 (23,5%) |
| by_check trước → sau | citation 16→15, must_mention 32→35, not_found 4→3, no_ask_back 3→2 | khớp (args_expected không có trong `by_check` của task_results, tôi không kiểm) |
| Manifest | cây sạch, t0, seed 42, cùng dataset sha `6f69dd…` và bộ chấm v0.3; tools/guide hash khác baseline đúng như đăng ký | đúng |
| Model nhúng | r1: Ollama trống; r2: model nhúng còn nạp; vẫn trùng 48/48 | `ollama_ps.jsonl` ghi đúng vậy — thêm một cặp bằng chứng cho câu hỏi "model nhúng còn nạp có làm lệch lần lạnh" (cùng chiều với r1/r6 của ticket 10) |

Dự đoán đăng ký trước sai một chỗ (doc-33..37 đạt cả 5 → 4/5) và được báo đúng cách, không sửa bài.

## Kết luận của NV1 — soát

1. "Công cụ đọc làm đúng việc": đúng. 4/5 bài mở đúng đoạn; doc-38 đối chứng không đọc thừa (1 lượt tra);
   0/5 chép sai `document_id` 36 ký tự — rủi ro H1 chưa hiện.
2. "7 bài tụt do prompt đổi": tôi thử một cách giải thích khác và nó **không đứng** — kết quả `search_documents`
   sau #1 dài hơn mỗi mục (thêm document_id, chunk_index, chars) nên có thể bị cắt theo mục nhiều hơn, làm
   mất excerpt/tên tệp. Đếm trên 40 bài cũ: baseline 18 kết quả tra, 5 bị cắt theo mục; sau #1 18 kết quả,
   **0** bị cắt, số mục hiện bằng nhau (3,25). Ba bài mất trích nguồn (doc-10, 20, 26) đều thấy đúng số mục
   như trước. Vậy chỗ tụt không đến từ hình dạng kết quả; lời dặn đổi là ứng viên còn lại — khớp cách đọc
   của NV1, và khớp ticket 10 (đổi một câu lời dặn xáo 38/40).
3. "Không tách được xáo trộn khỏi tác hại thật": đúng, và REPORT đã ghi. Một lần mỗi phía ở t0 chỉ cho
   biết lặp lại được, không cho dải dao động. Nếu cần quyết ship #1 thì phải đăng ký thêm (vd 3 lần 0,4 mỗi
   phía như ticket 10, hoặc tách "lời dặn mới, không công cụ" làm điều kiện trung gian để biết phần nào do
   chữ, phần nào do công cụ).
4. doc-36: đúng như NV1 tả — search trả chunk 8 ở hạng 1, đáp án ở chunk 9; model gọi `from_chunk=0, n=5`
   (→ 0–2) nên trượt. doc-33 cũng gọi `from_chunk=0, n=5` mà vẫn đạt (may: đáp án ở đoạn đầu). Tức 2/5 lần
   model **không dùng** `chunk_index` được trao. Đây là chỗ sửa rẻ nhất nếu có vòng #1-v2: một câu trong mô
   tả công cụ/lời dặn "from_chunk = chunk_index của đoạn khớp nhất" — nhưng lại là đổi lời dặn, phải đo lại.
5. `n = 5` ngoài khoảng: 2/5 lần; `_bounded` chặn đúng, không lỗi.

## Hai lỗi bộ chấm cho v0.4 (không sửa giữa chừng, đúng luật)

- doc-12 trượt `not_found` vì "tôi không thể tìm thấy" — `NOT_FOUND_PATTERN` v0.3 chỉ nhận "không tìm thấy"
  liền nhau; thêm "không thể (tìm thấy|tìm)".
- doc-19 trượt **`must_mention`** (không phải `not_found`): regex riêng của bài đòi "(không (tìm thấy|thấy|có)|chưa …)"
  gần "marketing|ngân sách", còn câu trả lời là "không trả về thông tin từ file …pdf". Bản sửa v0.3 chỉ nới
  `NOT_FOUND_PATTERN` chung, chưa nới regex của bài. REPORT ghi "không đúng câu mẫu" — đúng, nhưng chỗ sửa là
  regex của bài doc-19, cần ghi rõ để v0.4 sửa đúng chỗ.

## Việc cho opus / chủ dự án (không chặn gộp)

- Gộp được: phần đo trung thực, đăng ký trước, lặp lại được, giới hạn ghi rõ, không có luật ship. Kết quả
  "−1 tổng, +4 bài mới, −5 bài cũ" là của chủ dự án quyết #1 có vào main hay chờ vòng đo thêm; nếu gộp thì
  hành vi web/Discord đổi theo (prompt mới), nên ghi vào CHANGELOG.
- Sau khi ticket 23 gộp, chạy `--append-history` cho 4 lần v0.3 (baseline r1/r2, read r1/r2) để lịch sử có
  mốc; manifest của hai lần này chưa có `ollama_loaded_at_start` (runner trước 23), `ollama_ps.jsonl` là nguồn
  thay thế cho `agent-eval-run-conditions.json`.

## Giới hạn của lượt duyệt

Không chạy lại model (GPU). Không kiểm tay nội dung 5 câu trả lời bài mới ngoài doc-36; tin cột "đọc tay" của NV1.
