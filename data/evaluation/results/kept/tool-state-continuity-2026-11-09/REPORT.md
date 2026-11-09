# Lịch sử công cụ qua lượt — triển khai và kiểm CPU

Đã triển khai trên `codex/tool-state-continuity`, worktree riêng từ main
`3eac7f6`. Chưa merge/push, chưa đổi model hoặc bật tính năng. Main không bị sửa
code bởi đợt này. Chưa có số chất lượng/latency thực trên 9B, LFM3 hoặc Qwen 2B.

## Hành vi mới và các sửa nhỏ

Web lấy lịch sử có ID message do server sinh. Discord ghép đúng lượt hoàn tất
của cùng actor bằng ID lượt và vị trí assistant từ bộ dựng speaker context;
không so nội dung câu trả lời. ChatService khôi phục các cặp call/result trước
câu trả lời gốc, AgentService nhận lịch sử native rồi chạy cùng policy cũ.
Model, lời dặn, ba vòng chính, các kiểm lookup/read-rest đều giữ nguyên.

State có policy riêng trên AgentTool: read, receipt, hoặc mặc định none.
Hiện lưu tìm/đọc tài liệu, calculate, search_history và receipt
remember/remind/ask_user. Giờ hiện tại, trạng thái hệ thống, web/MCP chưa có
policy rõ và ghi chú read-rest do model sinh không được khôi phục.

- Nhóm phải hoàn chỉnh và có schema tương ứng hiện tại. Tài liệu phải khớp
  phiên bản active/indexed lấy từ kết quả lúc đọc; tài liệu mất/đổi phiên bản
  khiến cả nhóm liên quan bị bỏ. Kết quả cũ không cấp readable_documents cho
  lượt mới. Đây là quan sát lịch sử, không phải cache câu trả lời hiện tại;
  thêm tài liệu mới không làm một tìm kiếm cũ trở thành kết quả mới.
- Receipt phân biệt thành công, lỗi, chờ duyệt và đã hỏi người dùng. Khi có lỗi
  thì executed=null, vì lỗi không chứng minh chưa có tác dụng phụ.
  Loader chỉ đưa dữ liệu vào lịch sử, không dispatch thao tác. Receipt được
  giữ khỏi phép clear-result có lời dặn gọi lại. Yêu cầu mới thực sự vẫn có thể
  tạo thao tác mới. Model có lặp thao tác hay không còn phải kiểm bằng inference.
- PostgreSQL lưu bằng AgentTrace riêng, không cần migration/bảng mới; tối đa
  tám envelope/cuộc trò chuyện, mỗi envelope tám nhóm và 8.000 ký tự JSON.
  Chỉ khôi phục trong 30 phút; dọn bản cũ khi có lần ghi kế tiếp. TTL là hiệu
  lực đọc, không phải cam kết xóa vật lý đúng phút thứ 30. State thêm tối đa
  64.000 ký tự mỗi conversation, chưa tính overhead database; các trace thường
  của dự án vẫn theo vòng đời cũ.
- Không đưa envelope vào API trace thường hay summary giữ lâu. Quên thành viên
  vô hiệu toàn bộ envelope ở guild liên quan, gồm nội dung lẫn routing metadata;
  xóa message/conversation dùng cascade. Ghi state lỗi không làm mất câu trả lời.
- Log mới có request ID cho Web, turn ID cho Discord, thời gian chuẩn bị/xử lý/
  lưu, hàng chờ và đến xác nhận gửi Discord; đo ký tự message/schema theo mỗi
  model call. Không ghi nội dung vào log mới. tokens_in/out trên log chat cũ và
  log hoàn tất là usage lần cuối; runner đo mới giữ usage từng call riêng.
  Đây chưa phải đo thời gian tới trình duyệt của người dùng.

Sửa lỗi nhỏ cùng nhánh:

1. RAG chỉ cập nhật last_accessed_at, giữ updated_at. Đã rà các chỗ đọc:
   cleanup dùng last_accessed_at/created_at; freshness số trang dùng updated_at.
   Pin/metadata thực vẫn cập nhật updated_at. Không bỏ điều kiện freshness và
   không khôi phục mù số trang cũ khi nguồn thay. Dữ liệu đã bị touch làm bẩn từ
   trước không tự được backfill.
2. Test thiếu POSTGRES_TEST_URL được ghim vào database không thể kết nối, trước
   import app; URL được cung cấp vẫn phải qua bộ kiểm hợp đồng test.
3. Hai lỗi research-provider/index có thông báo tiếng Việt và retry phù hợp;
   giữ nội dung research đã lưu, không tạo vòng retry vô ích.

## Bằng chứng kiểm thử

PostgreSQL 16, Redis 7, Qdrant v1.18.2 dùng container tạm, không volume production.
CUDA bị ẩn, Ollama URL cổng chết, khóa cloud trống; guard chặn mạng ngoài
loopback và các cổng model. Test real-reranker sẵn có chạy CPU với cache offline;
không chạy inference model sinh. Python dùng lại môi trường có sẵn, không cài
thêm dependency. Schema không drift.

| Lượt | Đạt | Hỏng | Bỏ qua | Ghi chú |
| --- | ---: | ---: | ---: | --- |
| Small fixes | 65 | 0 | 2 | Chưa có test DB ở lượt đầu |
| State unit đầu | 72 | 1 | 9 | Ghi envelope rỗng; đã sửa |
| Focused v2 | 170 | 1 | 0 | Fixture cần bao phủ timestamp filesystem Windows; đã sửa fixture |
| Focused v3 | 197 | 0 | 0 | Có PostgreSQL thật |
| Focused v4 | 202 | 0 | 0 | Có runner/model giả |
| Full v1 | 2.134 | 0 | 0 | Có cảnh báo cp1252 của reader thread |
| Full cuối | 2.139 | 0 | 0 | 273,7 giây; UTF-8 loại lỗi reader thread |
| Runner/grader cuối | 6 | 0 | 0 | Kiểm lại thay đổi grader/fingerprint sau collection full |

Full cuối còn sáu warning có sẵn: escape trong test backup, audioop của thư viện
Discord, khóa JWT ngắn trong fixture và vòng FK ở phép kiểm schema. Không giấu
warning. Cú pháp 435 tệp Python hợp lệ. Các lượt hỏng vẫn có trong checks.json,
XML liên quan và raw log cục bộ.

Test cơ chế gồm: service restart, phạm vi actor/guild/conversation, ID anchor
trùng văn bản, không grant quyền từ lịch sử, đổi/xóa phiên bản tài liệu, receipt
pending/failed/succeeded, không dispatch khi load, nhắc lại do người dùng yêu
cầu, nhánh promise-fill, lỗi lưu/đọc state, retention/TTL, ghi đồng thời, cascade,
privacy forget/recount, no content trong summary và số ký tự đầu vào.

## Chi phí CPU, có đối chứng

Phép đo phụ dùng ChatService/AgentService/ModelRouter và PostgreSQL thật, nhưng
client sinh câu trả lời theo kịch bản cố định: sáu cặp, mỗi nhánh mười hai lượt,
mỗi lượt hai lần gọi giả. Đảo thứ tự nhánh. Đây là overhead backend và đầu vào;
không phải phép đo trí thông minh hoặc tốc độ inference.

| Đại lượng | OFF | ON |
| --- | ---: | ---: |
| Lượt mỗi nhánh | 72 | 72 |
| p50 trọn lượt giả | 23,39 ms | 35,97 ms |
| p95 | 29,68 ms | 43,10 ms |
| Tổng lần gọi giả | 144 | 144 |
| Trung vị câu SQL/lượt | 10 | 16 |
| Tổng ký tự JSON message | 236.016 | 389.520 |
| Tổng ký tự JSON schema | 347.616 | 347.616 |

Trong fixture này ON tốn thêm khoảng 12,58 ms ở p50; message dài thêm 65%,
message cộng schema dài thêm 26,3%. Không được suy ra latency model nhỏ tăng
tương ứng hoặc tính năng sẽ làm ít lần gọi hơn: lịch gọi ở đây cố định.
Lợi ích đã kiểm là kết quả công cụ xuất hiện đúng ở lượt sau, dữ liệu/quyền được
cô lập và trạng thái thêm không tăng vô hạn theo số lượt trong một conversation.

## Phần chưa được xác nhận

Đã đăng ký phép so sánh mới và tạo manifest cho ba model, OFF/ON, nhiệt độ 0 và
0,4 với các seed đã đặt. Có 26 ca mới, gồm 16 ca chat tiếng Việt; 624 job đã
chuẩn bị, chưa thực thi. Bộ chức năng mới do người triển khai viết, không phải
BFCL hoặc bộ holdout bên thứ ba. Oracle tự động không thay được đọc tay câu
trả lời chat. Không dùng kết quả chẩn đoán 12 ca cũ để tuyên bố thắng.

Chỉ nên xem xét bật sau khi 9B không tụt, model nhỏ có tiến bộ, các ca không cần
công cụ/duyệt/nhắc việc không hồi quy và đã cân chi phí prompt/latency thật.
Chưa có bằng chứng để bỏ 9B. Thay riêng general cũng chưa giải phóng các vai
9B còn lại.

Crash sau khi thao tác đã chạy nhưng trước khi commit receipt vẫn cần idempotency
của dịch vụ thao tác. Receipt pending là trạng thái lúc ghi, không tự cập nhật
khi người dùng duyệt về sau. Không thêm cơ chế khóa chặn mọi lời gọi cùng tham
số, vì như vậy sẽ chặn cả yêu cầu lặp hợp lệ của người dùng.

## Tái lập và tài liệu

- Đăng ký trước: `.scratch/tool-state-continuity/PREREGISTRATION.md`.
- Test CPU: `.scratch/tool-state-continuity/run_cpu_checks.py`.
- Overhead: `.scratch/tool-state-continuity/benchmark_cpu.py`, `cpu-overhead.json`.
- Bộ đo model: `backend/scripts/tool_state_eval.py`; mặc định chỉ prepare,
  cần `--execute` riêng mới có inference. Refuse ghi đè, resume bỏ job hoàn tất,
  giữ job lỗi để chạy lại, không âm thầm bỏ JSONL bị cắt giữa dòng.
- `prepared-manifest.json` là bản sao bằng chứng, không phải thư mục runtime để
  resume. Manifest runtime cuối ở
  `data/evaluation/results/tool_state_continuity/prepared-final-20261109/`.
  Nếu code/data đổi, tạo run mới; không sửa manifest cũ để vượt kiểm hash.
- Raw log trong `data/logs/tool-state-continuity-2026-11-09/` (chỉ trên máy);
  `checks.json` giữ hash, số đếm và danh sách hash code. Không đọc .env.
