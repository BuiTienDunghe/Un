# Báo cáo chi tiết hệ thống Local AI Core — Giai đoạn 1

## 1. Mục đích và phạm vi

Local AI Core là hệ thống AI chạy cục bộ trên máy người dùng. Hệ thống dùng một backend FastAPI duy nhất, nhưng chia rõ các module để có thể nâng cấp độc lập sau này.

Giai đoạn 1 được chia thành ba mốc:

| Mốc | Trọng tâm | Trạng thái mã nguồn hiện tại |
| --- | --- | --- |
| 1A | Backend, cấu hình model, chat và code assistant | Đã triển khai |
| 1B | Upload, parse, indexing tài liệu và RAG dense | Đã triển khai |
| 1C | Memory, hội thoại, hybrid retrieval, UI, logging và kiểm thử | Đã triển khai ở mức baseline |

Hệ thống không train model. Nó gọi các model local qua Ollama, lưu dữ liệu cấu trúc trong SQLite và lưu vector trong Qdrant.

## 2. Kiến trúc và nguyên tắc vận hành

Một request từ UI hoặc client đi vào FastAPI. Router chỉ nhận request, kiểm tra dữ liệu đầu vào và trả response. Logic nghiệp vụ nằm ở service; service không gọi Ollama trực tiếp mà đi qua ModelRouter. ModelRouter đọc cấu hình từ `models.yaml`, xác định model cho từng nhiệm vụ và gọi OllamaClient. OllamaClient là điểm duy nhất thực hiện HTTP đến Ollama.

Luồng tổng quát:

1. Client gửi request đến endpoint.
2. Router kiểm tra schema, giới hạn độ dài và tham số.
3. Service xây dựng ngữ cảnh nghiệp vụ.
4. ModelRouter chọn model theo mode.
5. OllamaClient gọi Ollama local.
6. Service lưu dữ liệu cần thiết vào SQLite/Qdrant.
7. LoggingService ghi tóm tắt request vào SQLite và file log Loguru.
8. Router trả response thống nhất cho client.

Nguyên tắc quan trọng là không hard-code model trong ChatService, CodeService hoặc RagService. Khi muốn đổi model, người vận hành sửa cấu hình thay vì sửa logic.

## 3. Khởi động local

File `run-local-ai-core.bat` là launcher một-click cho Windows.

Khi người dùng double-click launcher, quá trình diễn ra theo thứ tự:

1. Chuyển thư mục làm việc về đúng thư mục dự án để các đường dẫn tương đối luôn chính xác.
2. Kiểm tra Python, Docker và Ollama có sẵn trong PATH.
3. Tạo môi trường Python `.venv` nếu chưa có.
4. Kiểm tra và cài các dependency đã khai báo, gồm FastAPI, Qdrant client, PyVi, Loguru và các parser tài liệu.
5. Tạo `.env` từ `.env.example` nếu chưa có cấu hình riêng.
6. Khởi động Qdrant bằng Docker Compose.
7. Kiểm tra Ollama. Nếu Ollama chưa trả lời, launcher mở Ollama service nền.
8. Kiểm tra ba model cần thiết. Model thiếu sẽ được tải trước khi API chạy.
9. Kiểm tra port 8000. Nếu backend đã chạy, launcher chỉ mở trang tài liệu API. Nếu chưa chạy, launcher khởi động FastAPI.
10. Mở trang Swagger tại `/docs` để người dùng thử API.

Lý do giữ cửa sổ launcher mở là FastAPI chạy ở foreground; đóng cửa sổ này sẽ dừng backend. Qdrant và Ollama là tiến trình/container riêng nên không nhất thiết dừng cùng cửa sổ đó.

## 4. Cấu hình model và định tuyến

Hệ thống hiện có bốn vai trò model:

| Vai trò | Model cấu hình | Nhiệm vụ |
| --- | --- | --- |
| General | `qwen3.5:9b` | Chat thường, trả lời RAG, reasoning cơ bản |
| Code | `qwen2.5-coder:7b` | Giải thích lỗi, hỗ trợ code và refactor |
| Embedding | `qwen3-embedding:0.6b` | Biến text thành vector cho document và memory |
| Vision | `qwen3.5:9b` | Được cấu hình trước, nhưng image input chưa triển khai |

ModelRouter dùng mode `general`, `code` hoặc embedding. Nó lấy nhiệt độ, top-p, context window và keep-alive từ cấu hình. Vì vậy chat, code và RAG có thể dùng model khác nhau mà không cần nhiều backend hoặc nhiều service.

Trong môi trường VRAM 16 GB, cách vận hành khuyến nghị là gọi model theo nhiệm vụ, không cố giữ tất cả model lớn trong VRAM cùng lúc. Keep-alive giúp Ollama giữ model trong một khoảng ngắn rồi giải phóng khi không dùng.

## 5. Luồng health check và kiểm tra model

### 5.1 Health check

Endpoint `/health` kiểm tra hai thành phần tối thiểu:

1. SQLite có mở được và thực hiện được truy vấn đơn giản hay không.
2. Ollama có phản hồi từ endpoint liệt kê model hay không.

Nếu cả hai đều sẵn sàng, trạng thái là `ok`. Nếu một trong hai không sẵn sàng, API vẫn trả lời nhưng trạng thái là `degraded`. Cách này giúp người dùng biết backend có sống nhưng dependency nào đang lỗi.

Qdrant không được gộp vào health check hiện tại. Vì vậy trước khi nghiệm thu RAG thật, cần kiểm tra thêm container Qdrant và thực hiện smoke test index/search.

### 5.2 Danh sách model

Endpoint `/models` trả lại cấu hình model đang được backend đọc. Nó không chứng minh model đã được Ollama tải; mục tiêu của endpoint là kiểm tra backend đang dùng cấu hình nào.

## 6. Luồng chat thường

Endpoint: `POST /chat`.

### 6.1 Chat không dùng memory

1. Client gửi message và có thể gửi conversation ID.
2. Nếu chưa có conversation ID, hệ thống tạo hội thoại mới trong SQLite.
3. Nếu có conversation ID nhưng không tồn tại, hệ thống trả `CONVERSATION_NOT_FOUND`.
4. Hệ thống đọc số message gần nhất theo giới hạn cấu hình để tạo history.
5. Hệ thống ghép system prompt tổng quát, history và message mới.
6. ModelRouter chọn model general và gọi Ollama.
7. User message và assistant answer được lưu vào SQLite.
8. Response trả answer, model đã dùng, conversation ID và latency.
9. Request được ghi vào SQLite `request_logs` và file log Loguru.

### 6.2 Chat có dùng memory

Client đặt `use_memory` bằng `true`.

1. Các bước tạo/kiểm tra hội thoại vẫn diễn ra như chat thường.
2. Message mới được embedding bằng model embedding.
3. Vector query được tìm trong collection `memories` của Qdrant.
4. Tối đa năm memory liên quan được lấy về.
5. Nếu có memory, hệ thống chèn memory prompt và danh sách memory vào system context.
6. History và message hiện tại được thêm sau context memory.
7. Model general sinh câu trả lời.

Memory chỉ là ngữ cảnh tham khảo. Memory prompt yêu cầu model không coi memory là chỉ dẫn có quyền cao hơn system prompt. Nếu collection memory chưa tồn tại hoặc chưa có memory, chat vẫn chạy bình thường mà không thêm memory context.

## 7. Luồng code assistant

Endpoint: `POST /code/chat`.

1. Client gửi yêu cầu code, có thể kèm code context, traceback hoặc repo context ngắn.
2. CodeService ghép các phần thành một yêu cầu duy nhất với code system prompt.
3. ModelRouter chọn model code.
4. Ollama trả câu trả lời.
5. Response trả answer, model used và latency.
6. Log request được ghi.

Module hiện là read-only assistant: nó phân tích, giải thích và gợi ý patch. Nó không tự ghi hoặc sửa file trong repository. Đây là chủ ý an toàn của giai đoạn 1.

## 8. Luồng upload tài liệu

Endpoint: `POST /documents/upload`.

1. Client gửi file multipart.
2. Hệ thống kiểm tra đồng thời extension và MIME type.
3. Các loại được chấp nhận là PDF, DOCX, TXT và Markdown.
4. Hệ thống đọc file với giới hạn tối đa 50 MB.
5. Hệ thống sinh document ID dạng UUID có tiền tố `doc_`.
6. File được lưu bằng tên UUID trong `data/uploads`; tên file gốc chỉ được lưu như metadata, không dùng làm path lưu trữ.
7. SQLite tạo record document với trạng thái `uploaded`.
8. Response trả document ID, filename gốc và trạng thái.

Việc dùng UUID tránh trùng tên file, path traversal và xung đột khi nhiều file có cùng tên.

## 9. Luồng parse và index tài liệu

Endpoint: `POST /documents/index`.

### 9.1 Quản lý trạng thái index

Trước khi parse, hệ thống đọc document trong SQLite.

- Không có document: trả `DOCUMENT_NOT_FOUND`.
- Đang `indexing`: trả `DOCUMENT_ALREADY_INDEXING` để tránh index trùng.
- `uploaded` hoặc `failed`: có thể bắt đầu hoặc retry index.

Khi bắt đầu, document chuyển sang `indexing`. Nếu toàn bộ pipeline thành công, trạng thái là `indexed`. Nếu bất kỳ bước nào lỗi, trạng thái là `failed` và SQLite lưu error message.

### 9.2 Parser theo định dạng

| Loại file | Cách đọc hiện tại | Đơn vị nguồn |
| --- | --- | --- |
| PDF | PyMuPDF4LLM | Từng trang |
| DOCX | python-docx | Một nguồn chung, chưa có page thực |
| TXT | Đọc text trực tiếp | Không có page |
| MD | Đọc text trực tiếp | Không có page |

Với PDF, PyMuPDF4LLM chuyển từng trang PDF thành text/Markdown. Số trang được giữ lại và đi theo chunk để RAG có thể trả source page.

### 9.3 Làm sạch và chunking

Sau khi parser trả text, hệ thống làm sạch khoảng trắng và tách text thành chunk.

Chunking ưu tiên ngắt tại paragraph hoặc cuối câu. Nếu một đoạn quá dài, hệ thống tách tại khoảng trắng gần giới hạn nhất. Chunk kế tiếp mang một phần overlap từ chunk trước để không mất hoàn toàn ngữ cảnh ở ranh giới.

Cấu hình hiện tại:

- Chunk size: 900 ký tự.
- Chunk overlap: 150 ký tự.

Mỗi chunk kèm document ID, filename, chunk index, page và nội dung.

### 9.4 Embedding và lưu trữ

1. Từng chunk được gửi tới model embedding qua ModelRouter.
2. Hệ thống lấy vector dimension của embedding đầu tiên.
3. Nếu collection Qdrant chưa tồn tại, nó được tạo với dimension đó và cosine distance.
4. Nếu collection đã tồn tại nhưng dimension khác embedding hiện tại, index dừng với `VECTOR_DIMENSION_MISMATCH`.
5. Qdrant xóa vector cũ của document đó rồi upsert vector mới.
6. SQLite thay thế danh sách `document_chunks` cho document.
7. SQLite cập nhật status `indexed` và chunks count.

SQLite là nguồn metadata và text chunk; Qdrant là chỉ mục semantic vector. Tách hai phần giúp có thể debug text/chunk độc lập với vector database.

### 9.5 PDF đơn giản, PDF phức tạp và OCR

Hiện tại hệ thống **chỉ dùng PyMuPDF4LLM; chưa có OCR fallback**.

PDF được xử lý tốt nếu trang đã có text layer có thể trích xuất. Đây thường là PDF sinh từ Word, Google Docs, LaTex hoặc hệ thống xuất báo cáo.

PDF scan hoặc PDF có text layer hỏng được xem là không đọc được nếu parser trả ít hoặc không có text. Hiện tại tiêu chí vận hành là:

- Nếu sau clean/chunk không có chunk nào, document index thất bại với thông báo không có text đọc được.
- Nếu có text nhưng chất lượng thấp, hệ thống vẫn index vì chưa có quality scoring tự động.

OCR chưa thuộc baseline 1C. Khi làm extension sau này, đề xuất quy trình là:

1. Đánh giá từng page bằng lượng ký tự trích xuất, mật độ ký tự có nghĩa và tỷ lệ ký tự lỗi.
2. Page có text layer đủ dài và hợp lệ dùng PyMuPDF để nhanh, ít tốn tài nguyên.
3. Page gần như không có text, có quá ít ký tự, hoặc có tỷ lệ ký tự bất thường cao sẽ được gắn cờ OCR.
4. Chỉ page bị gắn cờ đi qua OCR; không OCR toàn bộ PDF mặc định.
5. Metadata source ghi rõ text đến từ native extraction hay OCR để đánh giá chất lượng sau này.

Chưa được phép mô tả OCR như một tính năng đang hoạt động, vì code hiện tại chưa có engine OCR, tiêu chí chấm điểm định lượng hoặc fallback pipeline.

## 10. Luồng RAG và hybrid retrieval

Endpoint: `POST /rag/chat`.

### 10.1 Dense retrieval

1. Câu hỏi được embedding.
2. Qdrant tìm các vector chunk gần nhất theo cosine similarity.
3. Có thể giới hạn theo document ID nếu client chỉ muốn hỏi một tài liệu.
4. Kết quả gồm content, document ID, filename, chunk index, page và similarity score.

Dense retrieval phù hợp với câu hỏi diễn đạt khác wording trong tài liệu nhưng cùng ý nghĩa.

### 10.2 BM25 retrieval cho tiếng Việt

1. Hệ thống đọc các indexed chunks liên quan từ SQLite.
2. PyVi token hóa text và câu hỏi. Các từ ghép có thể trở thành token nối bằng dấu gạch dưới, ví dụ `học_sinh`.
3. BM25 chấm điểm dựa trên các token xuất hiện trong query và document.
4. Các chunk có điểm dương cao nhất được giữ lại.

BM25 mạnh ở các từ khóa chính xác, tên riêng, mã lỗi, thuật ngữ kỹ thuật và cụm từ tiếng Việt.

### 10.3 Ba retrieval mode

`models.yaml` hỗ trợ ba mode:

| Mode | Logic |
| --- | --- |
| `dense` | Chỉ dùng embedding + Qdrant |
| `bm25` | Chỉ dùng token + BM25 trên SQLite chunks |
| `hybrid` | Dùng cả dense và BM25, sau đó hợp nhất |

Mode mặc định là `hybrid`.

### 10.4 Reciprocal Rank Fusion

Khi hybrid mode hoạt động, dense và BM25 tạo hai danh sách xếp hạng. Hệ thống không cộng trực tiếp raw score vì cosine score và BM25 score có thang đo khác nhau.

Thay vào đó, mỗi result nhận điểm dựa trên thứ hạng của nó trong từng danh sách. Một chunk xuất hiện cao trong cả hai danh sách sẽ có tổng điểm cao hơn. Chunk trùng document ID và chunk index được hợp nhất để tránh lặp context.

Sau khi fusion, hệ thống lấy top-k chunk làm context. Context được đưa cùng RAG system prompt và câu hỏi vào model general.

Nếu không có chunk, API trả `INSUFFICIENT_CONTEXT`; hệ thống không gọi model để bịa câu trả lời không có nguồn.

Response RAG có answer và source list. Mỗi source gồm filename, document ID, chunk ID, page nếu có và score.

## 11. Luồng memory

### 11.1 Tạo memory

Endpoint: `POST /memory/add`.

1. Client gửi nội dung, loại memory và importance từ 0 đến 1.
2. Hệ thống tạo memory ID UUID với tiền tố `mem_`.
3. Nội dung được embedding.
4. SQLite lưu record memory.
5. Qdrant upsert vector vào collection `memories`.
6. API trả metadata memory đã lưu.

### 11.2 Tìm memory

Endpoint: `POST /memory/search`.

1. Query được embedding.
2. Qdrant tìm top-k memory gần nhất.
3. API trả memory content, type, importance và score.

Nếu collection `memories` chưa tồn tại, search trả danh sách rỗng thay vì làm lỗi chat.

### 11.3 Update và delete memory

Update thay đổi text, type hoặc importance trong SQLite, tạo embedding mới và upsert lại vector cùng memory ID. Delete xóa vector Qdrant rồi xóa record SQLite.

Mục tiêu là SQLite và Qdrant cùng phản ánh một memory. Trong vận hành production sau này, nên bổ sung cơ chế retry/compensation khi một storage thành công nhưng storage còn lại thất bại.

## 12. Luồng quản lý hội thoại

Chat tự tạo conversation và lưu message. API quản lý gồm:

- Liệt kê hội thoại: trả ID, thời gian tạo/cập nhật và số message.
- Xem chi tiết: trả metadata hội thoại và message theo thứ tự thời gian.
- Xóa hội thoại: xóa message trước, sau đó xóa conversation.

Không có memory dài hạn tự động được trích xuất từ hội thoại ở baseline hiện tại. Memory được người dùng thêm qua API/UI để kiểm soát dữ liệu lưu lại.

## 13. UI web

FastAPI serve UI tĩnh tại `/ui/`. UI có sáu tab:

1. Chat: gửi yêu cầu chat.
2. Code: gửi yêu cầu code assistant.
3. Documents: chọn và upload file.
4. RAG: hỏi trên tài liệu đã index; có thể nhập document ID.
5. Memory: lưu memory mới.
6. Health: gọi lại `/health` và hiển thị tình trạng service.

UI là client tối giản để smoke test các luồng chính, không phải frontend production hoàn chỉnh. Một số thao tác nâng cao như index sau upload, memory search/update/delete và quản lý conversations hiện thuận tiện hơn khi dùng Swagger `/docs`.

## 14. Vision

Endpoint `POST /vision/chat` tồn tại để client có contract API ổn định. Hiện nó trả lỗi chuẩn `VISION_NOT_IMPLEMENTED` với HTTP 501.

Điều này có nghĩa là system chưa nhận image, chưa base64/decode image, chưa gửi image đến Ollama và chưa thực hiện vision inference. Prompt vision đã được chuẩn bị để làm nền khi module image input được bổ sung.

## 15. Dữ liệu, logging và lỗi

### 15.1 SQLite

SQLite lưu:

- Conversations và messages.
- Request logs.
- Documents và status index.
- Document chunks và source page.
- Memories.

### 15.2 Qdrant

Qdrant có hai collection tách riêng:

- `documents`: vector chunk tài liệu.
- `memories`: vector memory.

Hai collection tách riêng tránh search memory lẫn với chunk tài liệu và cho phép mở rộng policy/tuning riêng sau này.

### 15.3 Loguru

Mỗi request nghiệp vụ được ghi vào SQLite request logs và log file theo ngày trong `data/logs`. File log được rotate mỗi ngày và giữ 30 ngày.

Thông tin log gồm endpoint, model used, latency, status và error code. Nội dung prompt/response đầy đủ không được log mặc định để hạn chế lưu thông tin nhạy cảm và tránh file log quá lớn.

### 15.4 Error response

HTTP errors có cấu trúc chung gồm cờ error, error code, message và detail. Ví dụ các error code chính:

| Tình huống | Error code |
| --- | --- |
| Ollama không truy cập được | `OLLAMA_UNAVAILABLE` |
| Model chưa được tải | `MODEL_NOT_LOADED` |
| Ollama timeout | `MODEL_TIMEOUT` |
| Hội thoại không tồn tại | `CONVERSATION_NOT_FOUND` |
| File không hợp lệ | `UNSUPPORTED_FILE_TYPE` |
| File quá lớn | `DOCUMENT_TOO_LARGE` |
| Document không tồn tại | `DOCUMENT_NOT_FOUND` |
| Index trùng | `DOCUMENT_ALREADY_INDEXING` |
| Vector dimension không khớp | `VECTOR_DIMENSION_MISMATCH` |
| Không có RAG context | `INSUFFICIENT_CONTEXT` |
| Vision chưa triển khai | `VISION_NOT_IMPLEMENTED` |

## 16. Kiểm thử hiện tại

Suite hiện có 23 test pass. Test bao phủ các nhóm sau:

1. Health và model router.
2. Chat, conversation ID và chat with memory.
3. Code chat route đúng model.
4. Upload, MIME validation, document status và index chunk.
5. RAG source, thiếu context và reciprocal rank fusion.
6. Memory add/search/update/delete.
7. Conversation list/detail/delete.
8. Qdrant dimension mismatch.
9. UI static và vision placeholder.
10. Vietnamese tokenizer với cụm `học_sinh`.

Các test API mock Ollama và phần lớn thao tác Qdrant. Vì vậy test pass chứng minh logic backend và contract API, nhưng không thay thế smoke test với Ollama/Qdrant thật.

## 17. Quy trình nghiệm thu local nên thực hiện

1. Chạy launcher.
2. Kiểm tra `/health` là `ok`.
3. Kiểm tra `/models` đúng model mong muốn.
4. Gọi chat thường và kiểm tra model used/general, conversation ID, log.
5. Tạo một memory, sau đó gọi chat với `use_memory=true` và kiểm tra log/context qua debug phù hợp.
6. Gọi code chat và kiểm tra model code.
7. Upload một TXT ngắn, index, xem status `indexed` và chunks count lớn hơn 0.
8. Gọi RAG với document ID, kiểm tra answer có sources đúng filename/page/chunk.
9. Upload một PDF text-native để xác nhận page source.
10. Upload một PDF scan để xác nhận trạng thái fail hiện tại; đây là expected behavior trước khi OCR extension tồn tại.
11. Mở `/ui/` và thử từng tab.
12. Kiểm tra SQLite, Qdrant dashboard và log file nếu có lỗi.

## 18. Các giới hạn hiện tại và hướng nâng cấp

Các mục sau chưa phải tính năng hoàn chỉnh trong baseline hiện tại:

- OCR fallback cho PDF scan.
- Reranker dùng `sentence-transformers`.
- Streaming token response.
- Memory extraction tự động từ chat.
- UI đầy đủ cho toàn bộ CRUD và index workflow.
- Vision input thực tế.
- Retry/compensation transaction giữa SQLite và Qdrant.
- Evaluation dataset và đo chất lượng retrieval tự động.

`sentence-transformers` chưa nằm trong requirements vì chưa có reranker service sử dụng nó. Khi bắt đầu reranker, cần bổ sung dependency, cấu hình enabled/disabled, model reranker, benchmark latency và test chất lượng trước khi bật mặc định.

OCR nên được làm sau khi core được smoke test ổn định. Việc thêm OCR trước khi có tiêu chí phát hiện page scan, cache kết quả và đánh giá chất lượng sẽ làm pipeline khó debug hơn mà chưa chắc cải thiện kết quả.
