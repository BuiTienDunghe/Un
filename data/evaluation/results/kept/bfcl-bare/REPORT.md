# Model trần trên BFCL so với harness (06/11/2026)

Đăng ký trước: `PREREGISTRATION.md` (`b712d26`, commit trước lần chạy). 33 bài `ids_v1.json`, Qwen 9B (`6488c96f`), Ollama 0.40.13, nhiệt độ 0, seed 42, ngữ cảnh 16 384 (đã kiểm khi nạp), tắt suy nghĩ, gỡ model trước mỗi bài, cùng bộ chấm. Nhánh trần 11:59–12:04, đối chứng harness `ctl2` 12:04–12:09 (giờ VN), GPU tối đa 74 °C. Một lần chạy mỗi nhánh. Số tự đo trên 33 bài dự án chọn, không đặt cạnh bảng xếp hạng.

## Kết quả

| Hạng mục | Harness `ctl2` | Trần |
|---|---|---|
| simple_python (10) | 10 | 10 |
| multiple (8) | 7 | 7 |
| irrelevance (7) | 6 | 4 |
| multi_turn_base (5) | 1 | 2 |
| multi_turn_miss_func (3) | 1 | 0 |
| **Tổng** | **25/33** | **23/33** |

`ctl2` trùng lần chạy sáng nay (`forced`, 25/33) từng bài hỏng: đối chứng ổn định.

## Bài khác nhau giữa hai nhánh

| Bài | Harness | Trần | Đọc từ vết |
|---|---|---|---|
| `irrelevance_199` | đạt: trả lời bằng chữ | hỏng: gọi `play_poker` dù câu hỏi không cần | Harness giúp |
| `irrelevance_228` | đạt: trả lời bằng chữ | hỏng: gọi `get_local_time` | Harness giúp |
| `multi_turn_miss_func_157` | đạt | hỏng: lượt 2 không gọi công cụ nào | Harness giúp; chưa đọc kỹ vì sao |
| `multi_turn_base_113` | hỏng: thêm "Quasar Ltd." thay vì mã `QUAS` | đạt | Trần hơn; chưa tách được do lịch sử mang theo hay do số vòng |

Phần harness nào làm hai bài `irrelevance` trả lời bằng chữ thì chưa tách được: có thể là lời dặn hệ thống hoặc cách gọi `/api/chat`, cần một lần chạy harness bỏ lời dặn.

## Dự đoán so với thực tế

| Dự đoán | Thực tế |
|---|---|
| Trần 26–29/33, bằng hoặc hơn harness | **Sai**: 23/33 |
| `irrelevance_70` đạt ở trần (lỗi do lời dặn nhắc `calculate`) | **Sai**: trần cũng gọi công cụ (`calculate_mortgage_payment`); lỗi là của model |
| `128`, `180` đạt ở trần nhờ 20 vòng và lịch sử đầy đủ | **Sai**: cả hai vẫn hỏng (128 tự bịa giá MSFT 370,5 thay vì tra, lệnh mua bị từ chối, đúng lỗi harness gặp 02/11; 180 đặt ngân sách 20 000 thay vì 2 857,14, không đổi tiền) |
| `174` nghiêng hỏng | Đúng |
| 25 bài harness đạt giữ đạt, mất 0–2 | Mất 3 (199, 228, 157) |

Hệ quả cho H1/H2: lợi +1 bài mỗi cái đo 02/11 là lợi *bên trong* harness; vòng lặp gốc của BFCL có sẵn cả hai mà vẫn không cứu 128 và 180.

## Cách đọc

- Chênh 2 bài trên 33, một lần chạy: theo quy tắc đã đăng ký, **chưa phân biệt được**. Điều đọc được chắc chắn: harness không làm mất điểm so với model trần, và ở đây nó bớt gọi công cụ bừa.
- Trên 33 bài này, model là giới hạn chính: 6 bài hỏng ở cả hai nhánh, đều do model (sai tham số, không đổi tiền, hỏi lại mã đơn).
- Muốn biết harness thêm bao nhiêu thật, cần phạm vi lớn hơn (hàng trăm bài mỗi hạng mục).

## Dữ liệu

`bare/` (kết quả BFCL kèm log đầu vào, 4,5 MB, chỉ commit `manifest.json`, `scores.json`), `ctl2/` (harness, đủ). Model `un-bare-qwen9b` trong Ollama là tên riêng tạo từ `qwen3.5:9b` (dùng chung trọng số, không tốn thêm đĩa), giữ lại cho lần đo sau; gỡ bằng `ollama rm un-bare-qwen9b`.
