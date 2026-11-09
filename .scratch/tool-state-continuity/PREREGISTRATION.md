# Đăng ký trước — giữ kết quả công cụ qua lượt

Ngày 09/11/2026. Chưa chạy inference. Chủ dự án chưa chọn model nhỏ:
chuẩn bị riêng cho `qwen3.5:9b`, `lfm3:1.7b`, `qwen3.5:2b`.

## Giả thuyết và phần duy nhất thay đổi

Bản cũ chỉ gửi lại văn bản hội thoại. Bản thử thêm các cặp call/result hoàn chỉnh
vào đúng vị trí lịch sử, trong giới hạn và quyền hiện hành. Giữ nguyên model,
AGENT_GUIDE, system prompt, max_steps=3, policy lookup/read-rest hiện có.
Mỗi model đo OFF/ON cùng phiên; không dùng số cũ khác ngày làm đối chứng chính.
Feature mặc định OFF; không thay model đang ship và không giảm cả năm vai 9B.

## Bộ bài và độ độc lập

`data/benchmarks/tool_state/v1/cases.json`: 26 ca mới viết trước khi có kết quả
model, gồm 16 ca chat tiếng Việt không cần công cụ, 4 ca nhớ dữ kiện chưa được
chép vào câu trả lời, 2 ca đổi/xóa nguồn, 2 ca nhắc việc và 2 ca chờ duyệt.
Ca duyệt dùng tool giả qua ApprovalGate thật của vòng agent; không đại diện cho
một công cụ xóa tài liệu đang ship. Tất cả hệ thống ngoài là fixture, không đụng
dữ liệu thật. Mỗi ca có store/tool ledger mới, các lượt trong ca dùng chung store.

Đây là bộ xác nhận chức năng sản phẩm do người triển khai viết, chưa dùng để chọn
prompt/model và không lấy từ 12 ca chẩn đoán cũ. Không gọi nó là BFCL, điểm tổng
quát, hay bộ holdout độc lập do bên thứ ba xây dựng. Không sửa prompt/thuật toán
để khớp kết quả bộ này rồi dùng lại điểm của nó làm xác nhận.

## Thiết kế chạy sau khi được phép dùng model

- Ba model × OFF/ON. T=0 seed 42; T=0,4 seed 42/43/44. 624 job, 1 job là toàn bộ
  một ca nhiều lượt. Đảo thứ tự OFF/ON theo ca. Chạy tuần tự, không tải model.
- Context 16.384, top_p 0,9, think=false. Tool/schema/policy giống nhau trong cặp.
  Cố định code/data/config bằng SHA-256 trong manifest, ghi tag/digest và Ollama.
- Phân tích từng model và từng nhiệt độ, không gộp ba seed thành các ca độc lập
  để báo ý nghĩa thống kê. Báo số ca được cứu/mất, critical failures, số gọi model,
  ký tự message/schema thực gửi, token nhà cung cấp trả về và số lượt thiếu token,
  p50/p95 thời gian trọn lượt cùng thời gian từng lần gọi model.
- Oracle tự động là kiểm chức năng, không đủ chấm ngữ nghĩa chat tự do. Phải
  đọc câu trả lời chat che nhãn OFF/ON để kiểm đúng yêu cầu, mạch lạc và cách xưng
  hô trước khi bật; trả lời rỗng là trượt. Không gọi tỷ lệ no-tool là chất lượng
  chat toàn diện.
- Job hạ tầng lỗi giữ lại bản ghi lỗi, không tính đã hoàn tất. `--resume` chỉ bỏ
  job hoàn tất có cùng manifest; không xóa trắng kết quả cũ. JSONL bị cắt giữa dòng
  khi máy tắt sẽ khiến resume dừng để bảo toàn bằng chứng, không tự bỏ dòng.
- Không đối chiếu thời gian fake-client với thời gian model thật. CPU benchmark
  chỉ lượng hóa overhead PostgreSQL/input, với số lần gọi cố định.

## Luật quyết định, đặt trước khi xem điểm

1. Không có hồi quy về vượt quyền, xóa dữ liệu hoặc tự thi hành thao tác chờ duyệt.
   Bất kỳ ca này hỏng do ON đều chặn bật feature.
2. Chào hỏi mà ON gọi công cụ thì chặn bật. Với các ca chat khác: nếu OFF đạt
   toàn bộ thì ON cũng phải đạt toàn bộ; nếu OFF chưa đạt hết, ON không được
   kém OFF và phải công khai các lỗi cũ. Không tuyên bố chat an toàn chỉ bằng tổng.
3. 9B: tổng số ca đạt ON >= OFF ở mỗi nhiệt độ; công khai từng ca đổi kết quả.
   Model nhỏ: cần tăng số ca continuity đạt và tổng không tụt, không lấy việc
   một model cải thiện để bỏ qua model còn lại. Chưa chọn model, không tự ship.
4. Báo tradeoff ký tự/token/thời gian từng model. Không suy ra nhanh hơn chỉ từ
   ít lần gọi; chưa đặt một ngưỡng latency tùy ý khi chưa chọn model mục tiêu.
   Chỉ quyết định bật sau khi có số chất lượng và chi phí thật cùng nhau.
5. Chạy lại Agent Eval hiện có, cô lập từng bài, trên cả ba model cùng ngày.
   Bộ đó chủ yếu một lượt nên là hồi quy đối chứng; không dùng nó thay phép đo
   ChatService nhiều lượt. BFCL giữ nguyên runner/checker chính thức, không tự
   viết công cụ cho bài một lượt hay đổi cách chấm để nhận điểm từ retry.

## Cách chuẩn bị và chạy

Từ `backend`, Python của môi trường dự án, PYTHONPATH trỏ backend và repo:

```powershell
python -B -m scripts.tool_state_eval --out ../data/evaluation/results/tool_state_continuity/prepared
# Lệnh trên chỉ ghi manifest. Chỉ khi chủ dự án cho phép inference:
python -B -m scripts.tool_state_eval --out ../data/evaluation/results/tool_state_continuity/prepared --resume --execute
```

Không chạy lệnh thứ hai trong đợt triển khai CPU này. Nếu code/data đổi sau
prepare, phải tạo thư mục mới, không ghi đè manifest cũ. Muốn chỉ đo một model
dùng `--models <tag>` từ lúc prepare. Không sửa registry hoặc .env.

## Giới hạn đã biết

State là dữ liệu lịch sử, không phải hàng đợi thao tác hay bảo đảm exactly-once.
Crash sau khi thao tác đã chạy nhưng trước khi lưu receipt cần idempotency của
dịch vụ thao tác. Kết quả read-rest sinh bằng model, web/MCP không có policy
riêng, giờ hiện tại và trạng thái hệ thống không được lưu qua lượt. Receipt chờ
duyệt thể hiện trạng thái tại thời điểm ghi, không tự biết một lần duyệt về sau.
Metadata PDF đã bị updated_at làm bẩn trước bản sửa không được tự hồi phục.
