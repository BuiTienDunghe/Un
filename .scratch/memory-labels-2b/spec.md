# Model nhỏ gắn nhãn trí nhớ (vai i)

Status: 13/11/2026 đã viết code nấc 0 (quầy 2B, chưa commit, chưa chạy test); chưa đo.

Đã chốt (chủ dự án, 12/11):
- Hướng B: model chính 8–9B, model ~2B lo trí nhớ. Fine-tune do chủ dự án tự lo; phía Ún chỉ chừa chỗ cắm và bộ đo.
- Vai (i): model nhỏ gợi ý loại cho tin hoặc ghi chú. Code hoặc người duyệt vẫn quyết định ghi.
- Hai nấc: (a) gắn nhãn ghi chú lưu bằng lệnh "nhớ", rồi (b) đọc mọi tin Discord, gợi ý vào hàng chờ duyệt.
- Cách cắm Y: một quầy riêng cho 2B trả đúng `POST /classify` như decided; đổi model = đổi địa chỉ.

Model chính 8–9B có spec riêng, không thuộc tệp này.

## Bản chất

Ún đang nhớ bằng cách chép nguyên văn câu người dùng bảo "nhớ…". Tất cả ghi chú đều cùng một loại, nên model chính
không phân biệt được một sở thích thật với một câu nói đùa. Việc ở đây là thêm một người thư ký nhỏ: đọc mỗi ghi chú,
dán một trong bốn nhãn (sự thật, quyết định chung, câu đùa, không đáng nhớ). Thư ký chỉ dán nhãn, không cất hay bỏ gì.
Thư ký đầu tiên là model 2B có sẵn; sau này model chủ dự án tự dạy thay vào đúng chỗ đó, và một bộ đo cố định cho
biết người mới có hơn người cũ không.

## Đã có trong code (kiểm 12/11)

| Phần | Ở đâu | Hiện trạng |
|---|---|---|
| Ghi chú v2 | `services/source_memory.py`, bảng `source_memories` | Chỉ lưu khi có lệnh "nhớ" rõ, cả web (`chat_service.py`) lẫn Discord (`discord/source_memory.py`). Cột `memory_type` luôn `source_note`, `importance` luôn 0,5 |
| Model chính thấy loại | `SourceMemoryService.context` | Mỗi ghi chú đưa vào lượt đã kèm `memory_type`, `importance` |
| Tìm lại | `SourceMemoryService.search` | Xếp theo khớp chữ và độ mới; không dùng loại hay mức quan trọng |
| Dịch vụ decided | `tools/decided_server.py` | `POST /classify {"text"}` trả `{label, confidence, stable, probs, model}` |
| Bộ gắn nhãn tin Discord (ticket 36) | `scripts/decided_worker.py`, `discord/message_labels.py` | Gửi mọi tin của người trong sổ gốc tới `DECIDED_URL`. Nhãn `fact`, `decision`, `joke`, `ignore`; `ignore` chắc ≥ 0,8 thì bỏ qua, còn lại chờ người duyệt |
| Màn duyệt | `views/labels.js`, `/api/message-labels` | Duyệt, sửa nhãn, đếm tỉ lệ người đồng ý theo từng nhãn |
| Nhãn đã duyệt vào lượt Discord | `discord/turn_service.py` (~741) | Bị tắt khi trí nhớ v2 bật (`if not v2`), tức là từ 10/11 |

## Hợp đồng chung (mọi model gắn nhãn đều theo)

- Vào: một đoạn chữ, tối đa 2 000 ký tự.
- Ra: `label` thuộc `fact` / `decision` / `joke` / `ignore`; `confidence` = xác suất của nhãn chọn; `stable` = chọn
  giống nhau ở mọi thứ tự lựa chọn; `probs` = xác suất từng nhãn; `model` = tên model.
- Câu hỏi và bốn lựa chọn: dùng nguyên văn `QUESTION`, `OPTIONS` của `decided_server.py`, để 2B và decided được so
  trên cùng một đề.
- Cách tính: xoay thứ tự bốn lựa chọn bốn lần, mỗi lần lấy xác suất của bốn chữ A–D, lấy trung bình. Như decided.

## Nấc 0: 2B trả lời đúng hợp đồng, đo ngoài giờ chạy thật

Cắm ở đâu: **chủ dự án chọn Y (12/11).** Bảng dưới giữ lại để biết đã cân nhắc gì.

| Cách | Được | Mất |
|---|---|---|
| X. Vai mới trong registry, chạy qua Ollama | Có lịch sử phiên bản, con trỏ active, kiểm lúc khởi động như mọi vai; không thêm tiến trình | Model chủ dự án dạy phải xuất sang dạng Ollama chạy được; decided hiện chạy bằng PyTorch + adapter |
| Y. Một dịch vụ nhỏ cho 2B trả đúng `POST /classify` như decided; đổi model = đổi địa chỉ | Bộ gắn nhãn ticket 36 không phải sửa; decided cắm thẳng như hiện nay; ít code nhất | Nằm ngoài registry, không có lịch sử phiên bản; thêm một tiến trình phải giữ chạy; chốt chặn model nhỏ không thấy nó |
| Z. Registry thêm kiểu nhà cung cấp "HTTP" | Cả hai cách cắm, có lịch sử phiên bản | Sửa registry, chỗ nhạy (kiểm khởi động, chốt chặn model); nhiều code nhất |

Ý kiến của người viết: Y cho nấc 0 vì nhanh và so được công bằng ngay; chuyển sang Z nếu sau này cần lịch sử phiên bản.

### Thiết kế quầy 2B (cách Y)

- Code: `tools/label_server.py`, cổng 8379 (8378 đã thuộc quầy nghe), chỉ nghe trên máy này. `GET /` báo tình trạng,
  `POST /classify {"text"}` trả `{label, confidence, stable, probs, model}`. 422 chữ rỗng hoặc sai dạng, 413 thân quá
  lớn.
- 503 hay 500 (bộ gắn nhãn chờ cả hàng khi 503, ghi riêng tin đó hỏng khi 500): không tới được Ollama, quá giờ, đứt giữa
  chừng thì 503. Ollama trả lời mà không dùng được (mã lỗi, không có xác suất, không có chữ A–D) thì hỏi thêm một câu
  mẫu cố định: câu mẫu ra chữ cái thì lỗi là của tin này (500), không ra thì lỗi là của model (503). Nhờ vậy một model
  không bao giờ ra chữ cái sẽ làm hàng chờ, chứ không đóng dấu hỏng cả hàng.
- Không cần tiến trình con như decided: Ollama giữ model và tự nhả khi rảnh. Quầy chỉ chuyển lời.
- Đề bài lấy thẳng `QUESTION`, `OPTIONS` từ `decided_server.py` (tệp đó chỉ nạp thư viện model bên trong hàm, nên
  nhập được mà không kéo theo PyTorch). Sửa đề một chỗ thì cả hai quầy cùng đổi.
- Mỗi lần hỏi: gọi `/api/chat` của Ollama với `think: false`, nhiệt độ 0, chỉ sinh 1 token, `logprobs: true`,
  `top_logprobs: 20`. Lấy xác suất của A, B, C, D ở token đầu, chia lại cho tổng bốn chữ. Chữ nào không lọt top 20
  thì tính 0; cả bốn đều không lọt thì hỏi câu mẫu như mục 503/500 ở trên.
- Xoay bốn thứ tự, lấy trung bình, `stable` như decided.
- Không ghi chữ của tin vào log, như decided.
- Bật: dùng lại `DECIDED_URL`. Cổng 8379 thì supervisor bật quầy 2B; mọi giá trị khác bật decided như trước, nên `.env`
  cũ chạy y như cũ. Bộ gắn nhãn (và nấc a sau này) chỉ đọc địa chỉ đó.
- `LABEL_OLLAMA_MODEL`, `LABEL_OLLAMA_NUM_CTX`, `OLLAMA_BASE_URL`: quầy đọc từ môi trường cửa sổ, rồi tới `.env`, rồi
  mặc định (supervisor không truyền `.env` cho dịch vụ).
- Test (`tests/test_label_server.py`, giả Ollama, không chạy model): hợp đồng; xoay bốn lần; cắt 2 000 ký tự; chữ ngoài
  top tính 0; câu mẫu phân lỗi tin hay lỗi model; Ollama tắt, mã lỗi, không phải JSON, đứt giữa chừng; đọc `.env`;
  422 / 413 / 404; nội dung tin không vào console hay lời báo lỗi. `tests/test_supervisor.py`: cổng chọn quầy, kể cả
  `localhost`.
- Bản duyệt Fable: `.scratch/memory-labels-2b/reviews/`.

Đã kiểm 12/11: Ollama trên máy là 0.40.13. Tài liệu `/api/chat` có `logprobs`, `top_logprobs`, `think`. Chưa chạy
thử với `qwen3.5:2b` (cần cho phép); nếu thực tế không trả được thì phương án dự phòng là lấy chữ trả lời,
`confidence` = tỉ lệ bốn lần chọn trùng, ghi rõ là khác cách tính của decided.

Hai chỗ 2B và decided **không** giống nhau, phải ghi kèm mọi số so sánh:
- Khung câu hỏi: decided dùng khung của dự án Fine-tune (`render_prompt`, `prompt_frames.json`), tôi chưa đọc. Quầy 2B
  tự dựng khung từ cùng câu hỏi và bốn lựa chọn.
- Xác suất: decided lấy trên toàn bộ từ vựng rồi so bốn chữ; 2B chỉ thấy top 20 token.

Rủi ro phải kiểm khi đo: nếu quầy gọi 2B với độ dài ngữ cảnh khác lượt chat, Ollama có thể nạp lại model giữa các
lần gọi. Hiện model chính (`general-small-v1`) cũng là `qwen3.5:2b`, context 16384, keep_alive 5m; quầy gửi đúng các
số đó (chép tay, đổi yaml thì phải đổi quầy). Chọn model khác ở màn Model thì quầy vẫn hỏi `qwen3.5:2b`: hai model cùng
nằm trên card.

Bộ đo (chờ chọn):
- Bộ test có nhãn của decided bên dự án Fine-tune. Cùng bốn nhãn, so được ngay. Cần chủ dự án cho đường dẫn và cho
  phép đọc; chỉ đọc tại chỗ, không đưa vào repo.
- Bộ mới, tự gán nhãn. Tốn công, và người viết đề cũng là người gán nhãn.
- Bộ 150 ca trích trí nhớ cũ: chỉ ánh xạ được "không ghi" sang `ignore`, không có `decision` hay `joke`.

Chỉ số: đúng theo từng nhãn, bảng nhầm lẫn, tỉ lệ `stable`, thời gian mỗi tin, VRAM. Đối chứng: decided trên cùng bộ,
cùng ngày. Đăng ký dự đoán vào `docs/SO_DO.md` trước khi đo. Số này chỉ là test hồi quy nội bộ, không dùng để khẳng
định chất lượng; chưa biết bộ công khai tiếng Việt nào cho việc này.

## Nấc a: gắn nhãn ghi chú lưu bằng lệnh "nhớ"

- Phủ cả web lẫn Discord, vì cả hai lưu vào cùng bảng.
- Sau khi lưu, chạy nền: gọi bộ gắn nhãn, rồi ghi `memory_type` = nhãn, chỉ khi ghi chú còn `active` và revision chưa
  đổi. Bộ gắn nhãn lỗi hoặc tắt thì giữ `source_note`; lưu và tìm lại không bao giờ chờ nó.
- Ghi chú bị gắn `ignore` vẫn giữ, vì người dùng đã bảo nhớ. Nhãn đó chỉ để đo.
- `importance` giữ 0,5: decided không trả mức quan trọng.
- Thêm một câu vào lời dặn của khối trí nhớ để model chính hiểu các loại (`joke` là câu đùa, không phải sự thật).
- Cờ riêng, tắt mặc định. Tắt thì model chính thấy đúng như trước.
- Test: cờ tắt giống hệt; nhãn được ghi sau khi lưu; bộ gắn nhãn lỗi thì giữ mặc định; ghi chú bị sửa hay quên trong
  lúc chờ thì không ghi nhãn; nhãn lạ bị từ chối.

## Nấc b (sau nấc a)

- Bộ gắn nhãn ticket 36 dùng được 2B (theo cách cắm đã chọn ở nấc 0).
- Nối nhãn đã duyệt vào v2: tin `fact` / `decision` đã duyệt được lưu thành ghi chú v2, `source_id` = `discord:<id>`,
  `memory_type` = nhãn. Sửa hay xoá tin gốc thì ghi chú bị chặn như mọi nguồn v2.
- Chỉ Discord: tin chat web không nằm trong sổ gốc.

## Không thuộc spec này

Train model (chủ dự án lo). Chọn và cắm model chính 8–9B. Dùng mức quan trọng khi tìm lại. Đưa tin chat web vào sổ gốc.

## Câu hỏi mở

1. ~~Cắm ở đâu~~: Y (12/11).
2. Bộ đo nào.
3. Ghi chú `joke` có vẫn đưa vào khối trí nhớ (kèm nhãn) hay bỏ ra.
4. Đo 2B một mình trước, hay chờ model chính để đo VRAM khi hai model cùng nằm trên card.
5. Khung câu hỏi: đọc khung của dự án Fine-tune để quầy 2B dùng y hệt, hay để quầy 2B tự dựng khung.
