GỘP ĐƯỢC

# Duyệt wip/20-answer-check ebf2686 (ticket 20 #2: kiểm con số trong câu trả lời) — fable 5.1, 28/10/2026

Đã kiểm: đọc trọn `answer_figures.py` (107 dòng), diff `agent_service.py` (+57/−5), 12 test mới, bản đăng ký
trước (commit sau code, trước mọi lần chạy; lần đo hoãn theo ý chủ dự án). Chạy 175 test (answer_check,
read_document, 7 bộ agent, chat_api, discord_turn, forget_member_copies, answer_grounding) với đủ bộ giữ im
`OLLAMA_BASE_URL=http://127.0.0.1:9 MODEL_STARTUP_PROBES=false CUDA_VISIBLE_DEVICES=-1`: xanh. Không chạy
model.

## Kiểm độc lập điều cốt lõi

Tôi chạy lại bộ kiểm **ngoài agent** trên 144 câu trả lời đã lưu (v0.3 baseline, #1, #1-B; nguồn = câu
hỏi + lượt trước + kết quả công cụ của từng bài): bắt đúng 3 câu, đều là câu đang trượt — doc-33 ở baseline
("27", "30"), doc-10 ("100.000, 200.000, 150.000, 300.000") và doc-22 ("140") ở #1-B — và **không câu đang
đạt nào**. Khớp con số trong docstring của module và khớp cơ sở của dự đoán "46/48 trùng chữ" trong bản đăng
ký. Tức cổng này, ở t0 trên bộ bài hiện tại, không có tác dụng phụ lên bài đang đạt.

## Ba chỗ NV1 chọn

| Chọn | Kết luận | Lý do |
|---|---|---|
| Câu bị loại không lưu text | đúng | kind "final" thì dashboard (`operational_service.py:279` lọc `kind == "final"`) hiện câu bịa thành hoạt động; kind mới có text thì `forget_member._copies` (chỉ che `tool_result`/`tool_call`/`final`, dòng 158–164) sót. Giữ số đếm là đủ cho eval: dự đoán đã đăng ký chỉ cần `unsupported_figures` trước/sau. |
| Kết quả kiểm vào `arguments_shape` của bước final | chấp nhận | cột JSONB đã có, không migration; chỉ nhãn và số đếm, không nội dung — đúng tinh thần bảng rút gọn của 16. Lệch nghĩa tên cột thì ghi một dòng trong docstring của `AgentTraceSummary`. |
| Thêm đúng một vòng có công cụ, tối đa +2 lượt model | đúng | `rounds + 1` một lần (`retried`), vòng thêm vẫn qua cửa `left ≥ final_reserve` ở đầu vòng lặp và qua ngân sách tường của 16; retry mà gọi công cụ thì câu cuối bắt buộc trả lời — test `test_the_retry_gets_a_round_of_its_own_with_tools` ghim đúng đường đó. |

## Tương tác với các ticket đã gộp — đã rà

- Ticket 16 (bảng rút gọn): `kind` "answer_check" vừa String(32); `arguments_shape` dict; `content` None → hash
  None; không có `tool_declared` → `tool_name` None. Không lộ gì thêm. Token của vòng bị loại ghi vào bước
  `answer_check` (`**last`), bước final ghi vòng của nó; `record_usage(last)` cuối vẫn là lần gọi cuối (k2).
- Ticket 17: bước mới không có `content`/`arguments` → `_copies` bỏ qua, không có gì để che. Lời dặn thử lại
  (trích con số) chỉ nằm trong `working`, không được lưu.
- Ticket 23 (bảng điểm): `tool_error_codes` chỉ đếm `error_code` trên `tool_result`, nên UNSUPPORTED_FIGURES
  của bước `answer_check`/`final` không bị tính nhầm là lỗi công cụ — nhưng cũng chưa được đếm ở đâu. Việc
  nhỏ cho NV3 sau khi gộp: thêm hai số vào chiều Bền: số bước `answer_check` và số bước final còn
  `unsupported_figures > 0` (đọc từ `arguments_shape`). Đây chính là cột "trả lời có số liệu mà không tra"
  mà chủ dự án mở cho v0.4 — bộ kiểm này cho nó dữ liệu từ trace.
- Grader: `tool_calls()` chỉ lấy `kind == "tool_call"`; lượt thử lại có gọi công cụ thì tính vào
  `max_tool_calls` — đúng, đó là lượt gọi thật.
- Eval: `events.jsonl` ghi mọi bước, kể cả kind mới ✓.

## Một điểm mù chưa ghi (không chặn)

`_NUMBER = \d+(?:[.,]\d{3})+|\d+` coi dấu phân cách chỉ là nhóm 3 chữ số, nên số thập phân ngắn ("3,5 triệu",
"1.5 giờ", "10,5%") tách thành chữ số lẻ và không bao giờ bị kiểm. Thêm một dòng vào danh sách điểm mù trong
docstring; sửa regex thì phải đo lại nên để sau.

## Đăng ký trước — soát

Dự đoán 46/48 trùng chữ, không bài đạt nào thành trượt, doc-10 hết số không nguồn, mỗi bài một bước
`answer_check`, r1 = r2: đều kiểm được từ artifact; luật ship rõ (hai điều cùng đúng); hash tools/guide phải
bằng #1-B — tôi xác nhận nhánh không đổi `AGENT_GUIDE` lẫn schema công cụ. Một lưu ý khi đo: lượt thử lại
của doc-10 có thể gọi `search_documents`, kết quả tra là nguồn hợp lệ, nên "hết số không nguồn" đạt được mà
câu vẫn có thể trượt `citation` — bản đăng ký đã nói trước điều này, tốt.

## Giới hạn của lượt duyệt

Không chạy model (luật giữ im). Replay ngoài agent dùng nguồn = câu hỏi + lượt trước + kết quả công cụ,
thiếu system prompt và lời dặn so với bản thật, tức nghiêm hơn một chút; vẫn ra cùng 3 câu.
