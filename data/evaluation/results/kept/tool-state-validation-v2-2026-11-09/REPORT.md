# Phản biện bộ đo và cải thiện nhánh state

Bộ tự viết chứng minh được cơ chế hoạt động và các rào chặn còn giữ, nhưng chưa
đủ để kết luận trợ lý giỏi hơn trên nhiều loại công việc. Vì vậy bản sửa này giữ
nó làm hồi quy và thêm bài công khai vào phép xác nhận. Chưa chạy model thật.

Chỉ sửa `codex/tool-state-continuity`, sau `5fd709a`; implementation commit
`eef0988`. Main vẫn ở `3eac7f6`, không merge/push, không commit hộ sổ main.
Feature sản phẩm vẫn mặc định OFF, model/guide/số vòng không đổi.

## Nhận xét của agent và cách xử lý

| Nhận xét | Kết luận |
| --- | --- |
| Bộ tự viết quá ít ca kiểm lợi ích | Đúng; không tăng số bằng cách đổi tên dữ kiện. Hạ xuống hồi quy, bỏ vai trò ngưỡng chính |
| BFCL cũ không qua code state mới | Đúng ở base trước sửa; nay có chế độ dùng cùng recorder, budget và restore với sản phẩm |
| Chọn D cùng C | Chỉ thực hiện C trên nhánh; chưa có phép gộp main |
| Phải commit sổ main trước | Không bắt buộc lúc này; khi được phép gộp có thể ghép nội dung, bảo toàn cả hai phía |
| Metadata đã bị touch làm bẩn chưa tự lành | Đúng với lối tắt ingestion metadata; đọc PDF thành công vẫn làm ấm cache mà không cần nạp lại |

Không có sửa dữ liệu thật hoặc tự backfill timestamp. Lỗi số trang tiếp tục
được sửa cho các lần RAG touch mới theo cách giữ updated_at.

## Đường BFCL mới

`scripts.bfcl_run --bounded-tool-state` lấy kết quả từ hook AgentService, ghi
bằng ToolStateRecorder, rồi gọi history_budget/restore_history đang dùng ở
ChatService. Không gọi tool_traffic cũ để giả lập cơ chế mới. Phép tính budget
được tách dùng chung với cùng biểu thức; bộ giả lập lưu trữ được dùng chung giữa
hai evaluator, có giới hạn/TTL và cô lập từng ca.

BFCL giữ ngữ cảnh văn bản riêng và executor/checker công khai. Các hàm của
benchmark opt-in kiểu observation trong adapter, không được coi là hàm chỉ đọc
và không thay policy mặc định của công cụ thật/MCP. Phép này đo cơ chế state,
không thay kiểm quyền tài liệu, actor Discord hoặc receipt nhắc việc trong bộ
ứng dụng. Không gọi đây là đo toàn bộ pipeline ChatService hoặc điểm leaderboard.

Hai trạng thái dùng cùng schema, model, guide và số vòng. Chế độ mới chỉ dùng
cho multi-turn, loại kết hợp legacy carry. Có đo ký tự message/schema mỗi lần
gọi, token và thời gian như runner cũ. Bài single-turn vẫn chỉ chấm vòng đầu.

## Bài xác nhận đã đóng băng

Chọn ID bằng hash có seed cố định trước khi thấy điểm ON. Không đọc điểm/ground
truth để chọn. Tách khỏi multi_turn_base đã dùng chẩn đoán, không tuyên bố dữ
liệu công khai này chưa bao giờ xuất hiện trong huấn luyện.

| Nhóm | Ca mỗi nhánh | Lượt người dùng mỗi nhánh | Cách dùng |
| --- | ---: | ---: | --- |
| Pilot BFCL | 12 | 56 | Đo chi phí, không chọn prompt |
| Xác nhận BFCL | 300 | 1.303 | miss_func, miss_param, long_context; mỗi loại 100 |
| Chẩn đoán tùy chọn | 200 | 734 | multi_turn_base, không cộng vào xác nhận |
| Product cũ | 26 | 37 | Hồi quy ứng dụng và đọc tay chat |

Giữ cả 9B, LFM3 và Qwen 2B. BFCL có OFF/ON, nhiệt độ 0, seed 42; product giữ
sampling cũ. Số job ca không phải số lượt hội thoại.

| Khối | Lượt chạy ca khi chạy mọi nhánh | Lượt người dùng |
| --- | ---: | ---: |
| Pilot | 72 | 336 |
| Xác nhận | 1.800 | 7.818 |
| Product | 624 | 888 |
| Chẩn đoán tùy chọn | 1.200 | 4.404 |

Chưa thực thi các khối này. Chưa có ước lượng GPU đáng tin; chỉ sau khi được phép
mới chạy pilot để ước chi phí theo model/loại bài. Không chạy hết kế hoạch một
cách tự động. Nhánh cùng model phải cùng ngày/digest/Ollama/config; thứ tự đảo
theo model, chưa randomize từng bài. Khai báo GPU dùng chung trước khi kết luận
latency. Các giới hạn này đã ghi vào đăng ký v2.

Luật đọc kết quả chính: 9B không tụt tổng; model nhỏ phải tăng trên tập công
khai, báo được cứu/mất và từng loại bài, dùng exact McNemar một phía với điều
chỉnh xét hai model nhỏ. Chưa qua hồi quy/quyền/duyệt/chat đọc tay thì không
bật feature. Chưa đo trần cùng ngày thì không nói harness hơn model trần.
Chi tiết và các ngưỡng được đăng ký trước, không chọn lại sau khi xem điểm.

## Bảo toàn kết quả và ghim phép đo

Runner BFCL trước sửa vẫn xóa trắng file lúc bắt đầu hạng mục. Nay:

- Từ chối thư mục/tệp có sẵn nếu không có resume rõ ràng.
- Kiểm toàn bộ category trước khi chạy; JSONL bị cắt, ID trùng/lạ thì dừng.
- Resume ghim code, dữ liệu, ID, model digest, phiên bản Ollama và cấu hình.
  Code/selection sai bị từ chối trước Settings/probe/reload.
- Chỉ bỏ ca hoàn tất. Bài model làm sai vẫn là ca hoàn tất; không tự thử đến
  khi đúng. Lỗi hạ tầng mới được chạy lại, giữ từng lần trong attempts.
- Result chính có một hàng mỗi ID, thay kết quả lỗi bằng ghi tạm rồi replace.
- Không sửa hay chuyển đổi các kết quả cũ. Không hỗ trợ hai tiến trình cùng ghi
  một run directory.

Plan ghim mọi script/backend và dữ liệu BFCL. Các lệnh dry-run đã đi qua kiểm
plan trước Settings/.env/HTTP. Model thật chỉ được chạm khi chủ dự án cho phép
chạy các lệnh thực thi; script prepare không tạo client hoặc gọi model.

## Kiểm chứng CPU

PostgreSQL/Redis/Qdrant dùng container tạm, không volume thật. CUDA ẩn, Ollama
cổng chết, cloud key trống, guard chặn mạng ngoài loopback/cổng model. Reranker
test sẵn có dùng cache CPU offline; không chạy model sinh.

| Kiểm | Kết quả |
| --- | --- |
| Nhóm BFCL/state đầu | 95 đạt, không lỗi/bỏ qua |
| Nhóm BFCL/state sau hoàn thiện plan | 100 đạt, không lỗi/bỏ qua |
| Toàn bộ backend cuối | 2.157 đạt, không lỗi/bỏ qua; khoảng 286,4 giây |
| Cú pháp/schema | 438 tệp Python hợp lệ; không drift |
| Checker chính thức với oracle / không làm gì | Đạt / trượt như kỳ vọng; chỉ là kiểm đường chấm |
| Chuẩn bị thực | 512 ca và 18 lệnh dry-run được kiểm, không Settings/HTTP |
| Tệp checker/dữ liệu liên quan | 48 tệp trùng clone ghim sau chuẩn hóa xuống dòng |
| Script kiểm phụ, lần đầu | Lỗi đường dẫn tương đối sau chdir; đã sửa, giữ failure record |

Full suite còn các warning cũ về escape/audioop, khóa JWT fixture và chu kỳ FK;
không che warning. Không cộng các lượt test lặp thành số test độc lập. Các số
oracle không phải điểm chất lượng của 9B hoặc model nhỏ.

## Bằng chứng và tái lập

- `checks.json`, `full-final.xml`: kết quả, hash raw/normalized và hash code.
- `prepared-summary.json`, các `*_ids.json`: bộ chia đã đóng băng; đây là
  snapshot bằng chứng, không thay runtime plan.
- `verification.json`: schema/lệnh/provenance checker; bản lỗi đầu được giữ riêng.
- Runtime plan:
  `data/evaluation/results/tool_state_continuity/bfcl-prepared-v2-20261109/`.
  Product runtime:
  `data/evaluation/results/tool_state_continuity/product-regression-v2-20261109/`.
- Chuẩn bị: `python -B -m scripts.prepare_tool_state_bfcl --out <thư mục mới>`.
  Kiểm không model: `.scratch/tool-state-continuity/verify_prepared_bfcl.py`.
  Chạy test: `.scratch/tool-state-continuity/run_cpu_checks.py --phase bfcl|full`.
- Raw log: `data/logs/tool-state-continuity-2026-11-09/review-*/` (chỉ trên máy).
- Đăng ký: `.scratch/tool-state-continuity/PREREGISTRATION.md`, mục Cập nhật v2.

Main giữ nguyên; các thay đổi tài liệu đang dở của chủ dự án trên main không bị
commit, ghi đè hoặc nhập vào nhánh này.
