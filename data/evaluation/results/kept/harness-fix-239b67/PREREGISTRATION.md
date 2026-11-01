# Sửa lỗi harness từ bài hỏng BFCL và Agent Eval: đăng ký trước (nhân viên Sonnet 5.5, 02/11/2026, trước mọi lần chạy)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Số BFCL ở đây là 33 bài tự chọn, chạy qua vòng lặp của Ún, không đặt cạnh bảng xếp hạng.

Việc: đọc từng bài hỏng (BFCL: `multi_turn_base_77, 113, 128, 180`, `multi_turn_miss_func_143, 174`, `multiple_51`; Agent Eval: `doc-25`, `doc-55`, `hist-10`), phân loại nguyên nhân, sửa phần là lỗi harness. Không sửa bộ chấm, không gỡ công cụ, không viết lại `AGENT_GUIDE`.

## Đã đọc trước khi đăng ký (không phải kết quả đo mới)

- Hai lần chạy BFCL có sẵn (`bfcl-v1-base`, `v1-main`) trùng từng điểm: 26/33; 7 bài hỏng như trên. Chạy ở `b3198ca`, Ollama 0.40.13.
- Lịch sử gửi cho model ở đường chat thật chỉ có chữ (`postgres_auxiliary_store.get_messages` trả `{role, content}`); kết quả công cụ lượt trước không sang lượt sau. `bfcl_run.py` làm giống vậy. Nên "không đưa lệnh gọi cũ sang lượt sau" là giới hạn của harness thật, không riêng của bộ chạy. BFCL gốc thì giữ lại.
- Bộ kiểm tra con số chạy 14 lần: 11 ở bài một lượt (không ảnh hưởng điểm, vì bài một lượt chấm theo vòng model đầu), 3 ở bài nhiều lượt (128, 180, 174).
- `doc-25` qua các lần chạy giữ lại: có lúc tra tài liệu, có lúc không, cùng nhiệt độ 0 seed 42; đổi byte của lời nhắc là đổi kết quả.

## Ba thay đổi thử

| Mã | Thay đổi | Nằm ở | Mặc định |
|---|---|---|---|
| H1 | Bộ chạy BFCL đưa lệnh gọi và kết quả công cụ của các lượt trước vào lịch sử (như BFCL gốc) | `bfcl_run.py`, cờ `--carry-tool-traffic` | tắt |
| H2 | Trần vòng công cụ 4 thay 3 | `bfcl_run.py`, cờ `--max-steps` (chỉ ghi đè trong lượt chạy) | không đổi cấu hình thật |
| H3 | Chưa gọi công cụ nào mà đã nói "không có thông tin / tôi cần tìm", trong khi có công cụ tra: một lần thử lại có tin nhắc gọi công cụ | `agent_service.py`, tham số `lookup_check` | tắt |

H1 chỉ đo **trần lợi ích** của việc lưu kết quả công cụ qua các lượt. Muốn đưa vào đường chat thật phải lưu kết quả trong DB và nạp lại: ngoài phạm vi, để chủ dự án quyết sau khi thấy số.

H3 chỉ bắn khi: lượt chưa có lệnh gọi công cụ nào, sổ công cụ có `search_documents` hoặc `search_history`, câu trả lời khớp mẫu "không có thông tin / cần tìm kiếm", còn đủ thời gian dự trữ, và chưa thử lại lần nào. Các bài đã gọi công cụ thì đường chạy không đổi byte nào.

## So cái gì

Mọi lần chạy cùng ngày 02/11, cùng Ollama (ghi phiên bản trong manifest; đổi giữa chừng thì chạy lại đối chứng trước), nhiệt độ 0, seed 42, `--unload-between-tasks`, `--probe`, `--gpu-shared yes` (bot đang chạy), GPU dưới 85 °C và không có tiến trình `League` trước mỗi lần.

| Lần | Mã nguồn | Bộ |
|---|---|---|
| C-bfcl, C-ae | `b169da0` (code của main; `950cdc0` chỉ khác `map.md`), cờ tắt | BFCL 33 bài, Agent Eval 66 bài |
| H1 | C + `--carry-tool-traffic` | BFCL |
| H2 | C + `--max-steps 4` | BFCL |
| H1+H2 | cả hai | BFCL, chỉ chạy nếu mỗi cái riêng không hỏng gì |
| H3 | C + `lookup_check` bật | Agent Eval 66 bài, và BFCL (phải không đổi: bài BFCL không có công cụ tra) |
| C2 | sau khi sửa code, mọi cờ tắt | BFCL và Agent Eval: phải trùng C từng câu (không tác dụng phụ) |

Bộ bài Agent Eval và `ids_v1.json` không đổi so với đợt 2.

## Điều kiện phải đúng trước khi so (sai thì dừng)

- `ollama_version` bằng nhau ở mọi manifest cùng phép so; `ids_sha256`/`dataset.sha256` bằng mốc.
- C-bfcl ra 26/33 và C-ae ra 54/66 như đối chứng đợt 2 (02/11). Lệch thì ghi và coi đối chứng mới là mốc, không dùng số cũ.
- Hai lần chạy C cùng cấu hình trùng từng chữ (nhiệt độ 0, seed 42): kiểm một lần bằng C2.

## Đo gì

| Đo | Định nghĩa |
|---|---|
| Đạt | bộ chấm BFCL (venv bfcl) / bộ chấm Agent Eval v0.8, không đổi |
| Bài đổi | bài có kết quả đạt/hỏng khác C, liệt kê từng bài (không chỉ tổng) |
| Giống hệt | cùng câu trả lời và cùng chuỗi lệnh công cụ |
| Dừng | `stop_reason` mỗi lượt (BFCL: đếm `max_steps`) |
| H3 bắn | số bước `kind: "lookup_check"`; bài nào bắn, bài nào đổi sau đó |
| Giá | `tokens_in` mỗi lượt; thời gian trung vị và lâu nhất |

## Dự đoán (sai thì báo; không sửa code sau khi thấy kết quả)

| Dự đoán | Lý do |
|---|---|
| H1: `multi_turn_base_77` lượt 2 gọi `retweet(tweet_id=10)`; bài vẫn hỏng vì lượt 0 đã sai | mã tweet chỉ có trong kết quả công cụ; lượt 0 gọi `estimate_distance` bằng tên thành phố |
| H1: điểm 26 hoặc 27 trên 33; không bài nào từ đạt thành hỏng | chỉ thêm thông tin vào ngữ cảnh |
| H1: `tokens_in` các lượt sau tăng, không quá 16 384 (num_ctx) | mỗi kết quả vài trăm ký tự, tối đa 6 lượt |
| H2: số lượt dừng vì `max_steps` giảm từ 3 xuống 0 hoặc 1 | 174 lượt 0 cần bốn vòng, 180 lượt 0 và 1 dùng đủ ba |
| H2: không tin hơn cho điểm | các bài hỏng đều có nguyên nhân khác ở lượt sau |
| H3: `doc-25` bắn H3 và gọi `search_documents` | câu trả lời hiện nói thẳng "cần tìm kiếm trong tài liệu" |
| H3: BFCL trùng C từng câu | sổ công cụ BFCL không có công cụ tra, nên H3 không bao giờ bắn |
| C2 trùng C từng câu cả hai bộ | mọi cờ tắt |

**Không dự đoán** `doc-25` có đạt sau H3: câu trả lời sau lần thử lại phải có "quản trị", "hai bước" và trích đúng tệp, và Qwen 9B chưa chắc làm được.

## Luật quyết định (đặt trước khi thấy kết quả)

Giữ một thay đổi chỉ khi:

- **H1** (cờ trong bộ chạy, mặc định tắt): BFCL ≥ C, và không bài nào từ đạt thành hỏng. Nếu không bài nào đổi, vẫn giữ làm công cụ chẩn đoán nhưng báo "không lợi điểm".
- **H2**: chỉ là số đo; không đổi cấu hình thật. Báo số, chủ dự án quyết.
- **H3** (cờ, mặc định tắt): trên Agent Eval, **không bài nào đạt ở C mà hỏng ở H3**, và có ít nhất một bài hỏng ở C thành đạt ở H3. Không đạt đủ cả hai thì **gỡ code H3 khỏi nhánh**, chỉ giữ báo cáo.
- C2 không trùng C: sửa tác dụng phụ trước, không báo kết quả.

## Giới hạn đã biết

- Chạy một lần mỗi bên ở nhiệt độ 0: không đo được độ nhiễu giữa các lần chạy khác seed. Hệ thống xác định tại seed 42, nên một bài đổi là do thay đổi, nhưng không nói gì về seed khác.
- Một bài "đổi" của Agent Eval khi đổi byte lời nhắc có thể do độ nhạy của model, không do cơ chế. H3 chỉ bắn ở bài chưa gọi công cụ nên các bài khác không đổi byte; bài đã bắn thì có.
- Ollama tự cập nhật (31/10): so cùng ngày, không so với số ngày khác.
- Mẫu "không có thông tin" là regex tiếng Việt, bắt sót những cách nói khác.
