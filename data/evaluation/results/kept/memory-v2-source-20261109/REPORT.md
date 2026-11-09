# Memory v2: kết quả triển khai và đánh giá

Ngày 09/11/2026. Nhánh `codex/tool-state-continuity`; baseline `966e6b7`.

Đã nối memory nguồn nguyên văn vào API, web chat, Discord, RAG rewrite, công cụ
lịch sử, giữ trạng thái công cụ và lệnh quên. Dữ liệu chuẩn cùng chỉ mục FTS nằm
trong PostgreSQL. Không có model tự viết fact, vector mirror của memory v2 hay
đường fallback 9B/cloud. Đây là profile thử nghiệm, không phải kết luận tốt nhất thị trường.

## Những thay đổi có tác dụng trực tiếp

- Lệnh lưu nhận từ chính câu người dùng. Backend lấy actor và audience từ identity/session/turn; bỏ qua fact do model viết.
- Lưu nguyên câu, hash, tác giả, thời gian ghi, revision và trạng thái. Giữ nguyên phủ định, số, chủ thể và điều kiện thời gian.
- Web theo tài khoản; Discord đúng guild/channel/thread. Lọc SQL trước ranking. Chat/RAG v2 không mượn hội thoại khác chủ qua quyền admin xem transcript.
- Sửa/xóa/quên cùng transaction với invalidation. Tombstone chặn gửi lặp; expected_epoch chặn write đã chuẩn bị trước lần quên; barrier lọc lịch sử cũ; tool state phải cùng epoch.
- Ghi/xóa raw ledger dùng thứ tự khóa nhất quán và UPSERT khi record/delete đua nhau. Công cụ lịch sử còn kiểm tombstone chuẩn để xử lý delete thiếu metadata.
- Kiểm epoch dưới khóa ngắn trước khi lưu/đưa ra câu trả lời. V2 SSE đệm tới điểm này; câu trả lời/trace/tool state lỗi thời bị bỏ.
- Không đưa ledger memory, nhãn/jokes hay recap legacy vào prompt v2. Không tự nhập fact cũ thiếu provenance. Script forget_member có tìm được source-only member và đếm đúng dry-run.
- Màn hình Ghi nhớ có danh sách nguồn, lưu nguyên văn, sửa theo revision và quên. Giữ recipe OCR GLM đã có; vision tắt. General Qwen 2B mặc định, LFM 1.7B chỉ khi chọn rõ.

## Kiểm thử

| Phép kiểm | Kết quả |
|---|---|
| Toàn bộ backend trên mã cuối | **2198 passed**, không failure/error; `backend-final-state.xml` |
| Bot/launcher | **242 passed, 1 skipped**; `root-tests.log` |
| Review nguồn/quyền/registry/forget | 179 passed; `final-review.xml` |
| Review cuối raw ledger/tool state/forget | 85 passed; `post-review.xml` |
| Chạy đồng thời PostgreSQL | 12 vòng hai luồng edit/delete hoặc record/delete, không sống lại dữ liệu hoặc lỗi deadlock |
| Migration | Upgrade từ database sạch, downgrade/upgrade head mới trên DB riêng; schema check không có upgrade operation mới |
| Registry | 0 error, 2 warning stamp của report embedding/reranker cũ; không có 9B route |
| JavaScript | Cú pháp màn hình qua `node --check`; 36 trạng thái của sơ đồ, tiến/lùi/khôi phục state qua kiểm DOM offline |

Backend có các warning đã biết của fixture JWT ngắn, audioop và vòng FK memory legacy;
registry cảnh báo hai report lịch sử chưa có stamp. Không đánh đồng kiểm logic DOM với
kiểm layout trên trình duyệt: chưa kiểm bằng ảnh chụp giao diện.

PG/Redis/Qdrant chạy trong container riêng, port riêng, database `memory_v2_test`.
Không migration vào database hoạt động. Các model đã cài sẵn; không tải trọng số.
Mọi vòng lỗi/setup/hồi quy đều giữ trong `RUN_HISTORY.md` và log tương ứng.

## Đánh giá reader 2B

Tách **truy hồi đúng nguồn** khỏi **model hiểu đúng câu**:

| Tập | Truy hồi | Đáp án hữu ích theo tiêu chí thủ công |
|---|---|---|
| Sáu ca ban đầu | Đúng nguồn cần thiết / đúng abstention | 3/6: ba lần từ chối quá mức |
| Cùng sáu ca sau chỉnh cách đọc lời tự khai | Đúng nguồn cần thiết / đúng abstention | 6/6; đây là tập đã tune, không gọi là heldout |
| Sáu ca mới khóa trước khi chạy, giữ prompt | 6/6 kỳ vọng truy hồi | **5/6**; một ca Redis/PostgreSQL vẫn từ chối quá mức |

Ca âm được giữ nguyên: nguồn nói “Redis chỉ để cache, PostgreSQL lưu dữ liệu chính”
nhưng reader vẫn không chịu kết luận Redis không phải kho chính. Điều này không phải
lỗi lưu/truy hồi; cũng không được che bằng cách đổi prompt rồi chấm lại tập mới.

Các ca còn lại kiểm điều kiện đi taxi, hai người dùng Windows/Linux, dự định đi Nhật
so với đã từng đi, đề xuất ngày họp so với quyết định và câu hỏi không có nguồn.
Đây là dữ liệu tổng hợp nhỏ, chấm thủ công, gọi reader trực tiếp với gói nguồn thật;
chưa chứng minh multi-turn agent quality hay parity với model lớn trên dữ liệu người dùng.

Sáu ca warm đã tune có median POST reader 273.35 ms;
gọi đầu lạnh 6311.11 ms. Harness gọi tìm nguồn hai lần,
median cộng lại 7.6 ms trên sáu note. Các số này chỉ là
smoke timing nhỏ, không phải p95 production hay tải đồng thời. Digest, Ollama và thông số
ở `runtime-metadata.json`; câu trả lời nguyên vẹn ở `small-reader*.json`/`fresh-cases.json`.

## So với cơ chế cũ

`legacy-negation-probe.json` chứng minh gate tỉ lệ từ cũ chấp nhận fact sai
“Tôi thích cà phê đen” từ câu “Hãy nhớ tôi **không** thích cà phê đen”. V2 không cho
fact do model tạo quyền ghi, nên giữ nguyên câu có phủ định. Đây là đối chiếu cơ chế,
không chạy lại 9B làm đối chứng hoặc teacher.

V2 có kiểm nguồn, quyền và thu hồi rõ hơn; đổi lại bỏ tự suy diễn fact, thu hẹp từ
guild-wide sang channel/thread và dùng FTS nên yếu hơn với đồng nghĩa/paraphrase.
Quên toàn bộ tăng barrier chung tenant để chặn trích dẫn gián tiếp; vì vậy mất một
phần ngữ cảnh gần đó. Source note khác vẫn đọc được theo quyền.

## Giới hạn cần giữ rõ

Chưa có typed slots/entity graph, tự hợp nhất/supersede fact bằng ngữ nghĩa hay hybrid
vector retrieval. Thu hồi sử dụng trong context không xóa toàn bộ transcript, log,
backup hoặc tin đã gửi ra Discord. Lịch sử và gói nguồn dùng ngân sách ký tự, chưa
phải chứng minh token tuyệt đối. LFM và OCR chưa được đánh giá lại trong phép thử này.

Không tự động chọn fact mới nhất khi nguồn mâu thuẫn; không cam kết prompt sẽ thay
thế được mọi khả năng suy luận của model. Nếu thêm vector, cần outbox bền vững,
generation check và đọc lại canonical source; không đưa payload vector thẳng vào prompt.

## Xem pipeline và chạy lại

- [Pipeline đầy đủ, ví dụ và bảng so sánh](../../../../../docs/source_memory_runtime.md).
- `run_small_reader.py` và `run_fresh_cases.py`: chỉ nhận đúng database kiểm thử, gọi Qwen 2B local.
- `pipeline.html`: cùng sơ đồ tương tác trong cuộc trò chuyện; `visual_qa.js` kiểm logic offline.
- `SOURCE_MEMORY_ENABLED=true` là mặc định nhánh. Legacy mode chỉ để đối chiếu trên dữ liệu thử;
  không dùng để phục hồi một kho dữ liệu thật đã yêu cầu quên. Không rollback schema nếu muốn giữ source note.

Tác vụ triển khai vào nhánh và lưu bằng chứng; không push, merge main hoặc triển khai production.
