# BFCL phạm vi lớn: model trần và harness (đăng ký trước, 07/11/2026)

Chủ dự án chọn "Đo phạm vi lớn" sau lần 33 bài (`kept/bfcl-bare`, trần 23, harness 25). Viết và commit trước lần chạy thật.

## Phạm vi

Toàn bộ phần không live và nhiều lượt của BFCL v4 (clone `6ea5797`): 2 190 bài, `data/benchmarks/bfcl/ids_full.json`.

| Hạng mục | Bài |
|---|---|
| simple_python / simple_java / simple_javascript | 400 / 100 / 50 |
| multiple / parallel / parallel_multiple | 200 / 200 / 200 |
| irrelevance | 240 |
| multi_turn_base / miss_func / miss_param / long_context | 200 mỗi loại |

Không đo: live (dữ liệu người dùng thật, cần bộ chấm khác), memory, web_search (cần dịch vụ ngoài), format_sensitivity (chỉ cho model không gọi hàm).

## Hai nhánh

Như `kept/bfcl-bare/PREREGISTRATION.md`: cùng model, nhiệt độ 0, seed 42, ngữ cảnh 16 384, tắt suy nghĩ, gỡ model mỗi bài, cùng bộ chấm. Trần = vòng lặp FC gốc của BFCL; harness = `AgentService.run()` (3 vòng, lịch sử chỉ chữ, lời dặn Ún, kiểm câu trả lời).

Thêm cho lần này (commit cùng tệp này): bộ chạy harness chạy được 6 hạng mục mới; Java/JavaScript xử lý mô tả hàm đúng như BFCL (có test so với chính mã BFCL); `long_context` bật đúng cờ của BFCL. Thử 2 bài mỗi hạng mục mới ở cả hai nhánh: chạy hết, không lỗi.

Chạy xen kẽ theo hạng mục (nhánh đi trước đổi luân phiên), tạm dừng khi GPU ≥ 85 °C hoặc có League, chạy tiếp khi ≤ 75 °C. Ghi phiên bản Ollama trước và sau mỗi lượt.

## Dự đoán

| Hạng mục | Dự đoán (harness − trần, điểm %) | Lý do |
|---|---|---|
| simple_*, multiple, parallel* | trong khoảng ±3 | Một lượt, vòng đầu; 33 bài trùng hệt |
| irrelevance | harness **hơn** 5–15 | 33 bài: 6/7 vs 4/7, trần gọi công cụ bừa |
| multi_turn_base, miss_func | trong khoảng ±5 | 33 bài hoà; lỗi chủ yếu của model |
| multi_turn_miss_param | harness **kém** 0–10 | Bài cần hỏi lại tham số; lịch sử chỉ chữ làm mất ngữ cảnh khi người dùng trả lời |
| multi_turn_long_context | harness **kém** 0–10 | Trần 3 vòng và cắt kết quả công cụ dài |
| Tổng (trung bình không trọng số theo hạng mục) | trong khoảng ±3 | |

## Cách đọc

- Mỗi hạng mục và tổng: so từng bài một (bài chỉ một bên đạt), kiểm McNemar hai phía; chênh lệch có nghĩa khi p < 0,05. Không có nghĩa thì báo là chưa phân biệt được, kèm khoảng chênh.
- Đọc vết khoảng 10 bài chênh mỗi hạng mục có chênh lệch có nghĩa, để gán nguyên nhân cho phần harness cụ thể.
- Một lần chạy, một seed. Số tự đo bằng bộ chấm gốc của BFCL nhưng qua bộ chạy của dự án; không phải số bảng xếp hạng.
