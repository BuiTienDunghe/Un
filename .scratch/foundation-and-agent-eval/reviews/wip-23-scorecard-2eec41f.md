GỘP ĐƯỢC

# Duyệt wip/23-scorecard 2eec41f (cột "số liệu không tra được" + gộp main) — fable 5.1, 28/10/2026

Đã kiểm: diff 31b92bf..2eec41f của script (+28) và test (+17); nhánh đã gộp main (059edf3) nên phần còn lại là
code main. 77 test (scorecard + agent_eval) xanh, không DB, Ollama/GPU che. Lịch sử: 42 dòng (thêm 4 lần đọc
tài liệu v0.3), hai cột mới `correctness.answer_checks` / `correctness.finals_unsupported` = None cho mọi lần
trước #2 — đúng ("n/a", không phải 0).

| Điểm | Kết luận |
|---|---|
| `unsupported_figures(events)`: `answer_checks` = số bước `answer_check`; `finals_unsupported` = số bài có bước final với `unsupported_figures > 0`, đọc từ `arguments_shape` | đúng nguồn dữ liệu mà #2 ghi (review ebf2686, mục "Ticket 23"); trước #2 trả lý do n/a thay vì 0 |
| Ghép vào `correctness` và `SCALARS` | chấp nhận; cosmetic tôi nêu ở review 31b92bf (mục con `figures`) không đáng một vòng sửa nữa |
| Dòng bảng in "lần kiểm bắt và cho thử lại / câu trả lời vẫn còn" | rõ nghĩa |
| Phần 31b92bf (opus chọn (a)) | đã duyệt riêng ở `wip-23-scorecard-31b92bf.md`: GỘP ĐƯỢC |

Ghi chú khi đọc cùng v0.4: `figures_without_lookup` của bộ chấm (bài không tra mà có số) và cột này của bảng
điểm (số lần bộ kiểm #2 bắt được lúc chạy) đo cùng hiện tượng từ hai phía; một câu phân biệt trong README của
`kept/` là đủ (đã ghi ở review v0.4).
