# Đăng ký trước — giữ kết quả công cụ qua lượt

**Bổ sung v2 ở cuối tệp thay vai trò của bộ tự viết và phép đo chính.**
Các manifest v1 được giữ làm bằng chứng lịch sử, không resume sau khi code đổi.

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

## Cập nhật v2 — sau phản biện, trước mọi inference mới

Bộ tự viết kiểm được việc mang dữ liệu qua lượt và các rào chặn, nhưng chưa đủ
để biết trợ lý làm việc tốt hơn trên nhiều loại việc. Phép xác nhận chính chuyển
sang bài công khai có công cụ thực thi và bộ chấm sẵn có. Không thêm nhiều bản
đổi tên của cùng một bài rồi coi là bằng chứng độc lập.

### Vai trò và lựa chọn bài

Giữ nguyên bộ product v1 làm hồi quy Web/Discord, không dùng các ca nhớ dữ kiện
trong đó làm ngưỡng chính để tuyên bố model nhỏ tăng chất lượng. Oracle chat vẫn
cần đọc tay che nhãn cấu hình. Không chọn một model nhỏ thay chủ dự án.

BFCL lấy từ checkout công khai đã ghim, không đọc điểm cũ hoặc ground truth để
chọn bài. Sắp ID bằng SHA-256 của `SPLIT_SEED + ":" + ID`, seed nằm trong
`scripts.prepare_tool_state_bfcl`. Lấy tập xác nhận và pilot không giao nhau.
Nhóm base từng dùng chẩn đoán được giữ riêng, không cộng vào tập xác nhận.
Đây là tách khỏi tập chẩn đoán của đợt trước, không phải khẳng định benchmark
chưa từng xuất hiện trong dữ liệu huấn luyện hoặc chưa ai từng đo.

| Nhóm | Bài mỗi nhánh | Lượt người dùng mỗi nhánh | Vai trò |
| --- | ---: | ---: | --- |
| Pilot | 12 | 56 | Ước chi phí và phát hiện lỗi chạy; không chọn prompt |
| Xác nhận | 300 | 1.303 | miss_func, miss_param, long_context; mỗi loại 100 bài |
| Chẩn đoán tùy chọn | 200 | 734 | multi_turn_base đã dùng trước; giải thích nguyên nhân |
| Product v1 | 26 | 37 | Hồi quy ứng dụng, không phải benchmark xác nhận chính |

Mỗi nhóm BFCL có ba model × OFF/ON, nhiệt độ 0, seed 42. Tập xác nhận tương ứng
1.800 lượt chạy ca, không phải 1.800 lượt hội thoại; có tổng 7.818 lượt người
dùng. Product vẫn có 624 lượt chạy ca ở các sampling đã đặt, tương ứng 888 lượt
người dùng. Không cộng các seed lặp thành bài độc lập. Chưa chạy bất kỳ model
sinh nào trong đợt chuẩn bị này.

### Đường code được đo và giới hạn suy luận

`--bounded-tool-state` dùng ToolStateRecorder, history_budget và restore_history
đang dùng ở sản phẩm; lấy kết quả qua hook AgentService, không dựng lại từ trace
bằng tool_traffic cũ. OFF/ON có cùng schema, lời dặn và số vòng; không bật legacy
carry cùng lúc. Dùng cùng giới hạn nhóm/ký tự/tuổi state. Store in-memory mỗi ca
có TTL/retention; test PostgreSQL vẫn là bằng chứng cho adapter production.

Các hàm BFCL được opt-in kiểu observation rõ ràng chỉ trong evaluator. Nhãn
`read` ở adapter là cách mang nguyên kết quả, không phải khẳng định mọi hàm BFCL
không có tác dụng phụ. Không đổi policy none mặc định của công cụ sản phẩm/MCP.
BFCL không kiểm quyền tài liệu, actor Discord hay receipt nhắc việc của Ún;
các phần đó vẫn phải qua bộ ứng dụng. Không gọi đây là phép đo toàn bộ ChatService.

Sửa câu ở bản đầu: giữ dataset/executor/checker BFCL; runner inference của dự án
được thêm chế độ state. Không thay cách chấm, không tự viết backend cho câu
một lượt, không sửa clone BFCL. Bài một lượt vẫn chấm vòng model đầu tiên.
Checker chính thức được kiểm bằng ca oracle đạt và ca không làm gì trượt, đều
trên CPU. Điểm BFCL của cấu hình harness này không tự trở thành điểm leaderboard.

### Trình tự và luật đọc kết quả

1. Chỉ sau khi được phép dùng model, chạy pilot cùng ngày theo từng model.
   Ước thời gian còn lại từ thời gian thật theo loại bài, tách reload khỏi xử lý;
   không suy GPU-time từ CPU fake-client. Nếu phải sửa lỗi vận hành, ghi bổ sung
   và tạo manifest mới trước khi chạy xác nhận.
2. Chạy OFF/ON của mỗi model trong cùng ngày, cùng server/digest/config. Khai báo
   GPU dùng chung bằng `--gpu-shared`; nếu không khai báo hoặc có tải khác, không
   coi chênh thời gian là kết luận hiệu suất. Thứ tự nhánh đảo theo model trong
   plan; chưa có randomization theo từng bài, nên vẫn báo hạn chế warmup/nhiệt.
3. Chấm bằng `scripts.bfcl_score` với môi trường có BFCL chính thức cho từng thư
   mục run. Chỉ phân tích đủ ID, không có lỗi hạ tầng chưa xử lý. Báo số được
   cứu/mất theo cặp và từng loại bài, không chỉ tổng hoặc p-value.
4. 9B không giảm tổng bài đạt ON so với OFF. Model nhỏ cần tăng trên tập xác nhận
   công khai, không dựa vào bộ product tự viết. Báo exact McNemar một phía;
   ngưỡng bằng chứng cho mỗi model nhỏ là p < 0,025 để xét hai model. Nếu chưa
   đủ bằng chứng thì kết luận chưa rõ, không chọn lại bài/ngưỡng sau khi thấy điểm.
5. Giữ mọi rào chặn product đã đặt. Khi chưa qua chat đọc tay, quyền và thao tác
   chờ duyệt, không bật tính năng dù BFCL tăng. Agent Eval vẫn chạy cô lập từng
   bài cùng ngày trên các model. Chưa đo model trần cùng ngày thì không tuyên bố
   harness hơn model trần. Không tự ship hoặc đổi model sau phép đo.

### Chuẩn bị và bảo toàn kết quả

```powershell
# Từ backend; lệnh chỉ đọc BFCL và ghi plan/ID/lệnh tương lai, không model/.env:
python -B -m scripts.prepare_tool_state_bfcl --out ../data/evaluation/results/tool_state_continuity/bfcl-prepared-v2
```

Plan ghim toàn bộ code backend/script, ID, dữ liệu BFCL, cấu hình sampling và số
vòng; runner kiểm `--prepared-plan` trước Settings/probe/reload. Lệnh thực thi nằm
trong plan cho cả hai trạng thái, chỉ dùng khi được phép inference. Dùng đúng
môi trường có BFCL khi chấm; scorer không tự tải package hoặc model.

Runner từ chối thư mục/tệp có sẵn nếu thiếu `--resume`. Resume ghim code/data/
selection/model digest/Ollama/config, chỉ bỏ ca hoàn tất; lỗi hạ tầng được thử
lại và giữ trong attempts. Result chính có một hàng mỗi ID; thay hàng lỗi bằng
ghi tệp tạm rồi replace. JSONL bị cắt, ID trùng/lạ hoặc manifest cũ thiếu thông
tin khiến runner dừng bảo toàn dữ liệu. Không chuyển đổi hay ghi vào các lần
đo cũ, không hỗ trợ hai tiến trình đồng thời cùng run directory.

Main và sổ đo main giữ nguyên. Xung đột tài liệu chỉ được ghép khi chủ dự án cho
phép gộp; không cần commit hộ phần đang sửa trên main lúc này.
