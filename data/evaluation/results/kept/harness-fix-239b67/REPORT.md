# Bài hỏng BFCL và Agent Eval: nguyên nhân và ba thay đổi thử (02/11/2026)

Số tự đo, 33 bài BFCL và 66 bài Agent Eval do dự án chọn và viết, không đặt cạnh bảng xếp hạng. Đăng ký trước: `PREREGISTRATION.md` (commit `91562ce`, trước mọi lần đo). Mọi lần đo cùng ngày 02/11, Ollama 0.40.13, Qwen 9B, nhiệt độ 0, seed 42, gỡ model trước mỗi bài, GPU dùng chung với bot, dưới 85 °C, không có `League`.

## Bản chất

Mười bài hỏng không có chung một lỗi. Phần lớn là Qwen 9B làm sai việc nó có đủ công cụ để làm đúng: truyền tên công ty vào ô cần mã cổ phiếu, tự bịa giá thay vì tra, hỏi lại một mã đặt chỗ mà chính câu trả lời trước của nó đã ghi. Harness có hai chỗ yếu thật. Một là **lịch sử giữa các lượt chỉ có chữ**: kết quả công cụ lượt trước (mã tweet, mã đơn) biến mất, nên model phải đoán. Hai là **trần ba vòng công cụ** cắt ngang một lượt đang làm dở, rồi ép model viết câu kết từ những gì mới có, và câu kết đó đã khẳng định một điều chưa kiểm. Ngoài ra có một chỗ model "nói là sẽ đi tra rồi không tra" (`doc-25`), harness có thể bắt được và đẩy lại một lần.

Đường chat thật cũng chỉ lưu chữ (`get_messages` trả `{role, content}`), nên lịch sử chỉ-chữ không phải lỗi riêng của bộ chạy BFCL: nó là giới hạn của hệ thống, và BFCL gốc thì giữ lại.

## Nguyên nhân từng bài

| Bài | Nguyên nhân | Chi tiết (điều kiện: lượt chạy ở `v1-main` và `hf-c-bfcl`, giống nhau từng điểm) |
|---|---|---|
| `multi_turn_base_77` | **Model**, rồi **giới hạn lịch sử** | Lượt 0: ô `cityA` ghi "mã bưu chính", model truyền tên thành phố, gặp lỗi rồi bỏ cuộc dù có `get_zipcode_based_on_city`. Lượt 2: mã tweet 10 chỉ có trong kết quả công cụ, model bịa số 1734567890123456789 |
| `multi_turn_base_113` | **Model** | `add_to_watchlist("Quasar Ltd.")` thay vì `QUAS`; công cụ không báo lỗi, danh sách không đổi, model thấy mà không thử lại |
| `multi_turn_base_128` | **Model**, các lượt sau theo dây chuyền | Lượt 1 không gọi `get_stock_info`, tự bịa giá 370,5 (thật 310,23), lệnh bị từ chối; lượt 2–3 không có đơn để tra/huỷ |
| `multi_turn_base_180` | **Model**, có sức ép của trần ba vòng | Lượt 2 hỏi lại mã đặt chỗ 3426812 mà câu trả lời lượt 1 đã ghi; lượt 3 lại dùng đúng mã đó. Lượt 0 và 1 đều chạm trần ba vòng |
| `multi_turn_miss_func_143` | **Model**, dây chuyền | Lượt 1 hỏi lại mã đơn thay vì gọi `get_order_history`; lượt 3 công cụ `cancel_order` đã xuất hiện nhưng model không dùng |
| `multi_turn_miss_func_174` | **Harness (trần ba vòng)**, rồi model | Lượt 0: ba vòng đã dùng hết trước khi thử `SFO→CIA`; câu kết ép buộc viết "không có tuyến SFO→CIA" dù chưa hề gọi tuyến đó; các lượt sau tin câu đó. Lượt 5: nói "đã thêm bình luận" mà không gọi công cụ nào (harness chưa có kiểm tra "báo đã làm mà không gọi") |
| `multiple_51` | **Model** | Bỏ `n_rolls` dù đề nói hai con xúc xắc và mô tả ghi "số xúc xắc, mặc định 1" |
| `doc-25` | **Model**, harness bắt được | Không gọi công cụ, trả lời "không có thông tin… tôi cần tìm kiếm trong các tài liệu". Qua hơn 60 lần chạy giữ lại bài này lúc tra lúc không, kể cả ở nhiệt độ 0 seed 42: có vẻ nhạy với lời nhắc và phiên bản Ollama, không cố định theo commit |
| `doc-55` | **Model** | Dán 28 596 ký tự, vào nguyên văn (10 836 token, dưới trần 12 288). Văn bản nêu "nhà Bằng Lăng" 6 lần và "nhà Hoa Sữa" 1 lần; model chọn nhầm Bằng Lăng. Không công cụ, không phải lỗi harness; cách duy nhất là hạ trần nguyên văn, ngoài phạm vi |
| `hist-10` | **Model** | Công cụ đã trả "Đừng hỏi người dùng server nào", model vẫn hỏi "Tên server Discord nào?". Qua các lần chạy bài này cũng lúc đạt lúc hỏng |

**Bộ chạy BFCL**: không tìm thấy lỗi nào làm mất điểm. Việc nó không đưa lệnh gọi cũ sang lượt sau là cố ý, bắt chước đường chat; đo bên dưới.

## Bộ kiểm tra con số (14 lần trong 60 lượt)

Chạy lại với chính hàm `unsupported_figures` là không làm được cho câu bị loại (câu đó không được lưu, chủ ý); nhãn dưới đây đọc từ kết quả công cụ, câu hỏi và câu trả lời cuối.

| Loại | Lần | Ảnh hưởng điểm |
|---|---|---|
| Số tự tính, bắt đúng | 128 ("575" = 55 575 − 55 000), 180 ("457" = 2 857,14 − 2 400), 174 ("163", đổi tiền) | 128: model bỏ số; 180: lần thử lại **cứu** lượt (không có nó, model đã trả lời "đã đặt" sau khi chỉ tra giá; nhờ nó mới gọi `book_flight`) |
| Bắt nhầm | 180 ("10" trong "12/10/2026", đề viết "October 12th 2026") | Một lần, không đổi kết quả |
| Số lấy từ hiểu biết của model, bài một lượt, sau câu trả lời giả "ok" | 11 (irrelevance, simple_python, multiple) | 0: bài một lượt chấm theo vòng model đầu, không bài nào gọi thêm công cụ sau lần kiểm |

Kết luận: giữ nguyên bộ kiểm tra. Một lần bắt nhầm (tên tháng viết bằng chữ ở câu hỏi), ba lần cứu hoặc chặn số bịa, 11 lần vô hại. Chưa đọc từng câu trong 11 lần một lượt.

## Đo cùng ngày

Điều kiện đã thoả: đối chứng BFCL 26/33 và Agent Eval 54/66 như đợt 2; `hf-c2` (mã đã sửa, mọi cờ tắt) **trùng đối chứng từng chữ** ở cả 33 bài BFCL và 66 bài Agent Eval. `hf-c-ae` trùng `wave2-control` 66/66.

| Lần | Bộ | Đạt | Hỏng đổi | Ghi chú |
|---|---|---|---|---|
| Đối chứng `hf-c-*` (`91562ce`) | BFCL | 26/33 | — | 3 lượt dừng vì `max_steps` |
| | Agent Eval | 54/66 | — | |
| **H1** lịch sử giữ kết quả công cụ | BFCL | **27/33** | 128 hỏng→đạt; không bài nào đạt→hỏng | `retweet(10)` ở 77 lượt 2 như dự đoán, 77 vẫn hỏng vì lượt 0; tăng 12 % token vào (đỉnh một vòng 7 515, dưới 16 384) |
| **H2** trần 4 vòng | BFCL | **27/33** | 180 hỏng→đạt; không bài nào đạt→hỏng | `max_steps` 3→1 lượt. **Dự đoán sai**: tôi dự đoán không đổi điểm. Câu trả lời lượt 0 đổi sang tiếng Anh nên chưa chắc do trần |
| **H1+H2** | BFCL | **28/33** | 128, 180 hỏng→đạt; không bài nào đạt→hỏng | 174 đi xa hơn (gọi `SFO→CIA`, đặt vé ở lượt 2) nhưng vẫn hỏng vì lượt 1 không gọi `book_flight` |
| **H3** (mẫu rộng) | Agent Eval | **55/66** | doc-25 hỏng→đạt; không bài nào đạt→hỏng | bắn ở doc-17, doc-25, doc-46: **hai lần bắn nhầm** (doc-17 cấm mọi công cụ; may mà lần thử lại không gọi) |
| **H3b** (mẫu hẹp, đăng ký sau khi thấy H3) | Agent Eval | **55/66** | doc-25 hỏng→đạt; 65/66 trùng đối chứng | chỉ doc-25 bắn, đúng dự đoán; doc-25 gọi `search_documents` và trả đúng "quản trị", "hai bước" |
| H3 / H3b | BFCL (H3) | 26/33 | không | trùng đối chứng 33/33: sổ công cụ BFCL không có công cụ tra, H3 không bắn |

Thời gian trung vị Agent Eval 4,5 s (đối chứng) so 5,5 s (H3b, nhưng cả `hf-c2` với cờ tắt cũng 5,5 s, nên là GPU nóng/dùng chung chứ không phải H3b). Lâu nhất 12,1 → 15,3 s ở `hf-c2`.

## Quyết định thuộc chủ dự án

| | H3b: tra trước khi nói "không có thông tin" | H1: lưu kết quả công cụ qua các lượt | H2: trần 4 vòng thay 3 |
|---|---|---|---|
| Trạng thái | Code có, cờ `agent.lookup_check` / `--lookup-check`, **tắt** | Chỉ trong bộ chạy BFCL (`--carry-tool-traffic`); đường chat thật **chưa** làm | Chỉ cờ trong bộ chạy BFCL (`--max-steps`); cấu hình thật **không** đổi |
| Lợi | Sửa đúng 1 bài thật (doc-25); chỉ bắn khi chưa gọi công cụ nào | +1 bài BFCL; sửa được mất mã ở lượt sau (77 lượt 2) | +1 bài BFCL; bớt 2 lượt bị cắt ngang |
| Hại / chi phí | Thêm tối đa một lần gọi model cho lượt bắn: **phá luật 5 README** (thành ngoại lệ thứ năm), nên cần chủ dự án sửa luật mới bật; mẫu regex tiếng Việt bắt sót cách nói khác; mẫu hẹp được chỉnh sau khi thấy kết quả | Phải lưu và nạp lại kết quả công cụ trong DB (đụng `postgres_auxiliary_store`, bộ test DB, quyền riêng tư: kết quả công cụ có thể chứa tin nhắn); thêm ~12 % token | Mỗi lượt có thể lâu thêm một vòng (2–3 s); cần đo Agent Eval với cấu hình mới, chưa làm |
| Tôi nghiêng về | Giữ code tắt, chờ chủ dự án quyết luật 5 | Chưa làm đường thật; số này chỉ là trần lợi ích | Không đổi cấu hình trước khi đo Agent Eval |

Ý kiến của tôi, không phải kết luận: cả ba lợi nhỏ, và model nhạy với từng byte đầu vào (câu trả lời H2 ở 180 đổi ngôn ngữ), nên +1 hay +2 bài trên 33 bài một lần chạy có thể là ngẫu nhiên. Cái chắc chắn là: không bài nào đạt mà hỏng, và cờ tắt không đổi gì.

## Chưa làm / giới hạn

- Một lần chạy mỗi bên, một seed (42). Không biết lợi H1, H2 có giữ khi đổi seed; bộ chạy BFCL ghim seed, muốn thử phải thêm cờ.
- Chưa bật cờ nào trong đường chạy thật; `models.yaml` không đổi. Chưa chạy bộ test có DB (theo luật). Chạy chọn lọc 67 test (`test_agent_lookup_check`, `test_agent_answer_check`, `test_call_budget`, `test_bfcl_run` kể cả bộ chấm thật), qua; 255 test agent không DB khác qua trước khi sửa H3b.
- Không sửa: "báo đã làm mà không gọi công cụ" (174 lượt 5), và câu kết ép buộc ở `max_steps` còn khẳng định điều chưa kiểm. Hai chỗ này là lỗi harness thật, ngoài ba thay đổi đã đăng ký.
- Mẫu H3b đo trên đúng bộ 66 bài đã thấy H3 bắn nhầm: chỉ chứng minh không bắn nhầm ở đó.
- `worktree_dirty: true` trong manifest chỉ vì thư mục kết quả chưa commit lúc chạy; mã nguồn đã commit (`a2bc2c8`, H3b `b0a0887`).
- Thư mục `C:\tb1`… của nhân viên trước không đụng tới.

Dữ liệu: `hf-c-ae`, `hf-c2-ae`, `hf-h3-ae`, `hf-h3b-ae` (Agent Eval) và `bfcl/hf-*` (BFCL, kèm điểm từng bài); so sánh bằng `analyze.py`.
