# Cải tiến backend và kiểm chứng CPU — 08/11/2026

## Bản chất

Đường liệt kê paper dùng lại thông tin tài liệu đã tải thay vì đọc lại database cho từng paper. Bộ đếm số trang được tách riêng và gắn với bản nguồn hiện tại, nên thay tệp không tiếp tục dùng cache cũ. Lỗi của máy chủ khi yêu cầu index cũng được báo đúng loại và có mã tra log. Các thay đổi này giúp backend dễ bảo trì và chính xác hơn; chưa phải cải thiện khả năng suy luận của harness.

## Phạm vi thay đổi

- Chỉ sửa worktree của `codex/backend-small-fixes`, gốc `67260f3`.
- `SourcePageCounts` quản lý fingerprint, cache có giới hạn, khóa ngắn và PDF IO; `ResearchService` giữ việc ghép metadata paper. Không giữ lock lúc đọc PDF.
- `PostgresDocumentService.source_file_for(document)` kiểm nguồn từ record đã tải, giữ guard deleted/deleting/source unavailable và không thêm SQL. API `source_file(id)` cũ vẫn dùng được.
- Cache theo content hash và fingerprint filesystem; không giữ lỗi/nguồn thiếu vĩnh viễn. Nguồn đổi giữa lúc đọc trả số trang chưa biết, không lấy số cũ thay vào.
- Chỉ tin metadata ingestion khi version/timestamp đủ mới và có timezone. Queued, failed, cancelled replacement được test riêng vì run cũ có thể vẫn được chọn trước.
- TXT/MD/DOCX giữ số trang logic của parser. Nguồn đã gỡ vẫn giữ số trang lịch sử như trước; PDF đang có nhưng không đọc ổn định có thể trả `None` thay số lịch sử.
- Index endpoint giữ lỗi dự kiến; lỗi bất ngờ thành HTTP 500 với thông báo chung và `error_id` khớp log. Lỗi khi dựng response sau enqueue cũng không bị báo thành lỗi parse của người dùng.
- Test PostgreSQL dùng chung validator, yêu cầu URL tường minh và database hậu tố `_test`, chặn các query override database/service. Không coi hậu tố là bằng chứng tự đủ về cô lập.
- Test reranker từ cache chạy trong tiến trình mới với offline flags đặt trước import; không thay loader/model/config sản phẩm.

Không đổi prompt, giới hạn vòng, registry model hoặc policy của agent. Checkout main được kiểm bằng `git diff HEAD` trên các thư mục code và cấu hình build: không có thay đổi code; HEAD vẫn là `c01d6dd`.

## Điều kiện và phương pháp

| Mục | Điều kiện |
| --- | --- |
| Python | Venv hiện có, Python 3.11.9; không cài/thay dependency |
| Dịch vụ | PostgreSQL 16 Alpine, Redis 7 Alpine, Qdrant v1.18.2 dùng một lần; localhost cổng ngẫu nhiên; không volume dữ liệu dự án |
| Database | `backend_improve_test` cho test; `backend_improve_perf_test` riêng cho benchmark |
| GPU/model API | CUDA bị ẩn trong tiến trình và subprocess; Ollama trỏ cổng chết; khóa cloud trống; guard Python chỉ cho loopback và chặn cổng model |
| Model cục bộ | Có test reranker bằng weights đã cache, chạy CPU trong tiến trình offline mới; không tải model |
| Hồi quy | Toàn bộ backend/tests, Alembic upgrade/check, parse source Python |
| Benchmark | Cùng fixture paper/PDF; main `c01d6dd`, base nhánh `67260f3`, bản sửa hiện tại |
| Cách so baseline | Nạp class ResearchService từ git show vào module riêng, dùng cùng các dependency còn lại; không khởi động ứng dụng main hay sửa checkout main |
| Thứ tự | main → trước sửa → sau sửa, rồi đảo ngược; làm nóng đường gọi trước khi lấy mẫu |
| Đăng ký trước | Phạm vi và cách kiểm trong `.scratch/backend-small-fixes-followups/IMPLEMENTATION.md` trước focused test; đây là kiểm hồi quy/chẩn đoán, không có ngưỡng ship chất lượng model |

## Các lượt kiểm, gồm cả lượt lỗi

| Lượt | Đạt | Hỏng | Lỗi thiết lập | Bỏ qua |
| --- | ---: | ---: | ---: | ---: |
| Focused ban đầu | 99 | 0 | 0 | 0 |
| Backend đầy đủ đầu tiên | 2029 | 1 | 0 | 0 |
| Module reranker, chỉ đồng bộ một cờ offline | 19 | 1 | 0 | 0 |
| Module reranker, tiến trình offline mới | 20 | 0 | 0 | 0 |
| **Backend đầy đủ trên bản cuối** | **2033** | **0** | **0** | **0** |

| Kiểm bổ sung trên bản cuối | Kết quả |
| --- | --- |
| Parse source Python | 423 tệp, không lỗi cú pháp |
| Alembic check | Không phát hiện schema drift |
| Cảnh báo của lượt backend cuối | 9; có cảnh báo Unicode subprocess của test BFCL, khóa JWT fixture và vòng FK hiện có |

Lượt backend đầu có bài real reranker thất bại vì thư viện đã import trước lúc test bật offline, nên thử truy cập Hub; guard chặn đúng. Chỉ sửa cờ đã cache ở một thư viện chưa đủ, lượt module tiếp vẫn lỗi. Sau khi chuyển phần kiểm real weights sang tiến trình mới, mọi offline flag có hiệu lực từ import đầu, test qua mà không mở mạng. Không bỏ/skip bài để làm xanh.

Giữa các lượt có thời gian dừng công việc do hết hạn mức duyệt thao tác; không tính khoảng chờ đó là thời gian thực thi test hay tốc độ sản phẩm. Mỗi lượt có timestamp riêng ở `*-steps.json`.

## Hiệu quả trước/sau

Fixture ổn định gồm paper có nguồn PDF, các version và lịch sử ingestion. Số SELECT bao gồm truy vấn tải danh sách paper. Cache “lạnh” là cache ứng dụng; không xóa cache hệ điều hành hoặc PostgreSQL.

| Thiết kế | Số lượng |
| --- | ---: |
| Paper mỗi lượt | 100 |
| Mẫu mỗi nhánh, mỗi chế độ | 10 |
| Chế độ | 3: biết số trang; cache lạnh; cache ấm |
| Payload ổn định đối chiếu giữa các nhánh | Hash giống nhau ở cả 3 chế độ |

| Chế độ | SELECT main / trước / sau | Trung vị ms main / trước / sau | PDF đọc main / trước / sau |
| --- | --- | --- | --- |
| Đã có metadata số trang hợp lệ | 103 / 4 / 4 | 97,52 / 13,10 / 26,44 | 0 / 0 / 0 |
| Cache lạnh, thiếu số trang ingestion | 403 / 304 / 4 | 720,45 / 610,27 / 96,87 | 100 / 100 / 100 |
| Cache số trang ấm | 103 / 4 / 4 | 99,29 / 13,46 / 25,29 | 0 / 0 / 0 |

Đường lạnh giảm SQL theo từng paper xuống số truy vấn cố định trong fixture và nhanh hơn rõ so với base nhánh. Payload không đổi khi nguồn ổn định. Test hồi quy riêng kiểm việc số trang đổi theo nguồn, cache giới hạn dung lượng, nguồn thiếu rồi khôi phục, nguồn đổi giữa lúc đọc và replacement queued/failed/cancelled.

**Đánh đổi được giữ rõ:** đường metadata/cache ấm chậm hơn base nhánh vì phải kiểm fingerprint filesystem để nhận ra nguồn thay đổi. Nó vẫn nhanh hơn main trong phép đo này. Không tuyên bố mọi đường đều nhanh hơn; không bỏ kiểm freshness chỉ để lấy số đẹp.

Đây là thời gian service trên máy hiện tại, không gồm HTTP/serialization, startup hoặc model; chưa đo tải đồng thời hay latency production. Số truy vấn và payload được kiểm trực tiếp; các trung vị không là cam kết tốc độ triển khai.

## Bằng chứng và tái lập

- `checks.json`: kết quả từng lượt, fingerprint file backend, hash XML gốc/đã chuẩn hóa và điều kiện CPU.
- `focused.xml`, `full.xml`, `reranker-offline.xml`, `reranker-fresh-process.xml`, `full-final.xml`: giữ kết quả, tên ca, thời gian; bỏ hostname, chuẩn hóa đường dẫn và bỏ khoảng trắng cuối dòng ở marker traceback rỗng của pytest.
- `benchmark-raw.json`, `benchmark-summary.json`: từng mẫu, SELECT/PDF reads, hash payload và trung vị.
- Script tại `.scratch/backend-small-fixes-followups/`: `run_cpu_checks.py`, `benchmark_cpu.py`, `publish_cpu_evidence.py`; guard chỉ áp dụng khi runner đưa thư mục guard vào PYTHONPATH, không thay startup sản phẩm.
- Log gốc/PDF giả ở `data/logs/backend-improvements-2026-11-08/` (gitignore, chỉ trong worktree nhánh). Trước khi tái lập, dựng dịch vụ riêng rồi truyền URL của chúng; không dùng URL production.
- Container dùng một lần được dừng sau khi lưu bằng chứng.

Phần tách policy/state của AgentService vẫn để sau phép chẩn đoán harness. Không có điểm BFCL hay Agent Eval mới từ lần cải tiến CPU này.
