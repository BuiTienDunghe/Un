# OCR evidence pipeline trên nhánh model nhỏ

Triển khai 09/11/2026 trên `codex/tool-state-continuity`. OCR mặc định là
`ocr-ovis-v1`: OvisOCR3 0,8B, GGUF Q8 cùng BF16 vision projector, chạy qua Ollama.
Model trả lời không cần vision. Không mở đường tới model 9B hoặc cloud.

## Thay đổi runtime

- `OCRService` dùng prompt native của model, giới hạn ảnh 2048 px, hiệu chỉnh
  EXIF và kiểm JSON/bbox. Native PDF vẫn dùng text sẵn có.
- `OcrResult` mang text dùng cho ingestion, raw output và block evidence. Bảng
  HTML có header được đổi thành Markdown để chunker giữ cấu trúc bảng và lặp
  header khi chia chunk; raw HTML vẫn được giữ nguyên để kiểm tra.
- Mỗi hàng bảng có evidence riêng kèm tên cột. Các nhóm text nằm ở hai cột
  được gom theo bbox để reader không ghép ngày/mã từ hai đơn hàng khác nhau.
  Nhóm dẫn lại các source ID; tọa độ không được bịa cho dòng/hàng/nhóm suy ra.
- OCR console lưu `raw.txt`, `result.json` gồm block/bbox và text theo trang.
  Mỗi trang hoàn thành được checkpoint vào OCR run trong PostgreSQL. Job bị
  từ chối do đang có job khác cũng lưu đúng trạng thái thất bại.
- Cache PostgreSQL lưu raw evidence trong envelope có version. Fingerprint
  gồm pipeline, prompt, model revision, token cap, think, DPI và preprocess.
  Cache cũ không bị giải nghĩa như JSON mới khi fingerprint thay đổi.
- Model startup probe dùng 384 token cho hợp đồng structured, kiểm JSON hợp lệ
  cùng nội dung và kết thúc lượt. Probe text cũ giữ cap 64 token. Chain chỉ có
  Ovis → GLM local có sẵn → disabled nếu không có phiên bản nào đạt.

`POST /api/ocr/jobs/{job_id}/ask` nhận `{question, pages?}`. Cần job completed;
có cùng API-key guard và admin guard như bề mặt OCR quản trị. UI OCR có ô hỏi
tài liệu. Các job cũ chưa có blocks vẫn đọc được bằng cách tạo evidence từ
text đã lưu, không OCR lại.

Reader giới hạn context, chọn nguyên block/hàng, rồi gọi model general một lần
với JSON schema chỉ cho chọn ID có thật. Code trả nguyên văn bằng chứng, không
nhờ model viết lại số/tên. Các câu hỏi về điện thoại/email/tài khoản được lọc
theo nhãn và hình dạng giá trị; thiếu trường thì trả insufficient_evidence,
không tốn call. ID lạ/trùng và structured output hết token bị từ chối.
Registry LFM3 đặt rõ `think: false` để lượt chọn ID ngắn không dùng hết token
cho suy luận trước khi trả JSON; Qwen 2B hiện cũng đã có cấu hình này.

Khi vision role tắt, `/vision/chat` dùng OCR evidence. Discord đã đưa kết quả
endpoint này vào câu hỏi dạng text nên dùng được ngay với model general không
vision. Đây là OCR chữ trong ảnh, không phải lời khẳng định hiểu được ảnh cảnh
vật. Khi vision role được cấu hình, luồng vision cũ vẫn hoạt động.

## Model và nguồn tham khảo

- Model gốc: [ATH-MaaS/OvisOCR3](https://huggingface.co/ATH-MaaS/OvisOCR3), revision
  `17f255e2c8ae6d18d5d5edb0a474bd4ed39aef90`. Prompt structured được giữ trong
  `backend/app/services/ocr_profiles.py`, theo contract trong thư mục prompts
  của model. Raw output được giữ trước bước parse như hướng dẫn chính thức.
- GGUF: [prithivMLmods/ATH-MaaS-OvisOCR3-GGUF](https://huggingface.co/prithivMLmods/ATH-MaaS-OvisOCR3-GGUF),
  revision `c29551652e828085ca1e892092f1319dbee22d2f`. Đây là bản chuyển đổi cộng
  đồng, không phải GGUF do nhóm Ovis phát hành. Registry ghim Ollama digest và
  chỉ cho đúng tag này ở role OCR.
- [LightOnOCR harness](https://github.com/lightonai/LightOnOCR): học contract
  `grounding`, bbox 0–1000, block theo loại và raw artifacts từng trang. Parser
  có adapter cho định dạng này; chưa cài LightOn weights trong lần triển khai.
- [GLM-OCR](https://github.com/zai-org/GLM-OCR): tham khảo tách bố cục, nhận dạng
  và formatting. Việc gom cột ở đây là hậu xử lý hình học của bbox Ovis; không
  tuyên bố đã triển khai PP-DocLayout-V3 hoặc toàn bộ GLM SDK.

## Kết quả và giới hạn

Artifacts: [ocr-rollout-20261109](../data/evaluation/results/kept/ocr-rollout-20261109/REPORT.md).
Trên 10 ảnh tổng hợp / 28 câu hỏi cùng manifest:

| Cấu hình | Lookup đúng điều kiện chấm |
| --- | ---: |
| GLM cũ + reader mới | 22/28 |
| Ovis JSON + reader, chưa gom cột | 25/28 |
| Ovis JSON + bảng/gom cột + reader | 27/28 |

Lỗi còn lại: tên kho `Liên Chiểu` bị OCR thành `Liên Chiếu`. Giữ nguyên lỗi,
không dùng model text để đoán sửa dấu. Median OCR ghi nhận: GLM 0,907 s/ảnh,
Ovis 1,792 s/ảnh; chưa đo tải đồng thời production. Ollama báo `size_vram`
1.293.313.637 byte cho Ovis ở ctx 16384; đây không phải peak VRAM cả hệ thống.

Đây là regression/diagnostic trên ảnh tổng hợp, không chứng minh accuracy scan
thật hay chữ viết tay. Ba ảnh mới đã được xem kết quả khi cải thiện layout;
replay sau đó không được gọi là đánh giá held-out. Chấm expected-string trong
bằng chứng chỉ đo lookup hẹp, chưa chấm entailment tổng quát.

Trên chính worktree đích: 2.217 test backend qua; sau sửa pin `think` cho LFM3,
128 test liên quan qua, gồm regression kiểm cấu hình registry thực. Smoke HTTP
với FastAPI và Ollama thật đã trả đúng mã phiếu cùng block/bbox và từ chối trường
điện thoại không tồn tại với 0 call. Chi tiết và JUnit nằm trong report ở trên.

Các giới hạn còn giữ rõ:

- `citation_integrity=passed` chỉ chứng minh ID có thật; không chứng minh model
  đã chọn đúng thông tin. Các field ngoài nhóm có rule vẫn có thể từ chối sai
  hoặc chọn nhầm.
- Bbox/block được giữ trong OCR runs và OCR cache. Library ingestion giữ text
  cấu trúc để chunk/index; citation RAG vẫn theo trang/đoạn, chưa có schema mới
  để highlight OCR bbox trong mọi tài liệu đã promote.
- PDF có text layer đủ dài nhưng còn ảnh nhúng vẫn dùng native fast path.
  Dùng force_ocr khi cần kiểm tra cả trang; chưa merge OCR riêng vùng ảnh nhúng.
- Không có confidence được tự tạo, không dùng một điểm số để tự nhận là đã
  kiểm chứng đúng OCR, không tự lặp model khi gặp output lỗi xác định.

## Vận hành và quay lại

Từ worktree của nhánh, launcher đọc registry mới và pull đúng tag. Model đã
được tải và chạy trên máy này bằng Ollama 0.40.13. API cần khởi động lại từ
worktree này để dùng code mới; không thay `.env` hay chạy migration production
trong triển khai OCR này.

Quay lại GLM trên một phiên chạy: đặt `MODEL_VERSION_OCR=ocr-small-v1` trong
shell rồi khởi động backend. Không ghi pin vào `.env`. Nếu upstream tag không
còn khớp digest, resolver ghi rõ fallback; không âm thầm tải model thay thế.

Đo lại từ thư mục backend:

```powershell
python -m scripts.ocr_evidence_eval --manifest ../data/benchmarks/ocr_evidence/v1/manifest.json --output ../data/evaluation/results/ocr-rerun
python -m app.config.model_registry --check
```
