GỘP ĐƯỢC (commit 31b92bf). Lưu ý: cây làm việc của NV3 lúc tôi duyệt còn 4 tệp SỬA CHƯA COMMIT (một mục bảng
điểm mới cho #2 "số liệu không tra được") — phần đó chưa duyệt, không nằm trong 31b92bf; NV3 commit riêng rồi
xin duyệt sau nếu muốn gộp.

# Duyệt wip/23-scorecard 31b92bf (sửa theo review b50982c, opus chọn (a)) — fable 5.1, 28/10/2026

Đã kiểm: diff b50982c..31b92bf (script +21/−?, test +18, run-conditions, history backfill, README, RESULTS,
Comments); 77 test (scorecard + agent_eval) xanh, chạy KHÔNG có `POSTGRES_TEST_URL`/`REDIS_TEST_URL`, Ollama/GPU
che. Tính lại từ tệp lịch sử đã commit (38 dòng): `fabricated` > 0 ở đúng 3 lần (C-warmup, C-t0, D-t04-r1 —
đều doc-31 nêu tên thư viện bị cấm), `not_found_missed` > 0 ở 15 lần — khớp Comments 01:10 và khớp số tôi
đếm ở lượt duyệt trước (15/18 là doc-19/doc-12 trượt `not_found` đơn thuần).

| Điểm | Kết luận |
|---|---|
| `fabricated` = trượt `must_not_mention`; `not_found_missed` = trượt `not_found` mà không trượt `must_not_mention` | đúng cách (a); tập hai cột rời nhau, có test ghim cả trường hợp một bài trượt cả hai (đếm vào `fabricated`) |
| Lịch sử và `--compare` mang cả hai cột | đúng (`SCALARS` thêm `not_found_missed`) |
| Bảng in: chữ "bịa" chỉ còn ở cột đúng nghĩa; cột kia nói rõ "có thể do mẫu bộ chấm" | đúng |
| Backfill 38 dòng chạy lại | đúng, đọc được từ tệp commit |
| Hai câu doc-12 ("không thể tìm thấy", "không được tìm thấy") v0.3 vẫn sót → ghi v0.4 | đúng, trùng điểm tôi ghi ở review cd99811 |

## Đính chính về phía tôi

NV3 đúng, tôi sai: ba lần 1a-v2 (22:31–22:39) **có** chạy song song với 09 — lượt hybrid v0r2 của 09 chạy
22:30:20–22:55:49 (ticket 09 Bước 4, và chính nó ghi nhận tải chat của 1a-v2). Mốc 22:28:10 tôi dẫn là lượt
chỉ-dense trước đó. Vậy `gpu_shared = true` cho A/E/F là đúng, và câu tôi đưa vào review 1a-v2 / ticket 10
("lệch lan không do 09 đang đo") sai về sự kiện. Điều còn đứng: A vẫn trùng 40/40 với lần 19:43 dù chạy
song song, nên "chạy chung" không giải thích được một mình vì sao E/F lệch 12/13 bài sau hist-07 — cơ chế vẫn
chưa rõ, chỉ là giờ có thêm một ứng viên. Opus: sửa dòng tương ứng ở ticket 10 (mục đóng ticket) cho khớp.

## Phần chưa commit trong cây làm việc (đọc qua, chưa duyệt)

`unsupported_figures(events)` đếm bước `answer_check` và bước final còn `unsupported_figures > 0`, ghép vào
chiều Đúng, in một dòng — đúng hướng tôi đề nghị ở review #2 và là dữ liệu cho tiêu chí v0.4 chủ dự án mở.
Khi NV3 commit, tôi duyệt nhanh; lưu ý nhỏ nhìn thấy: trả về `unsupported_figures_unavailable` trộn vào dict
`correctness` — cân nhắc đặt thành mục con `figures` để `--compare`/lịch sử không phải dò khoá.
