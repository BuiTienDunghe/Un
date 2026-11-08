# Backend small fixes: hướng tiếp theo cho harness model nhỏ

Status: proposed — chỉ bổ sung tài liệu, chưa triển khai hay đo model.
Ngày: 08/11/2026.
Nhánh: `codex/backend-small-fixes`.
Mốc code đã đọc: `67260f3f22302fee2a6e666e2c8141d24ce450ac`.

## Bản chất và phạm vi

Nhánh này làm backend rõ ràng và dễ bảo trì hơn; chưa chứng minh harness giúp model nhỏ làm việc tốt hơn. Bước tiếp theo nên giảm những việc model phải tự suy ra: tham số hợp lệ, công cụ nào đang có, việc nào đã thực hiện và dữ kiện nào phải giữ qua lượt. Sau đó mới thử chuyển bước đơn giản sang model nhỏ hơn.

Hạ từ model hiện tại xuống model nhỏ không tự chứng minh giá trị harness. Giá trị cần đo là tăng khả năng hoàn thành với cùng model, hoặc giảm chi phí ở mức chất lượng chấp nhận được. Không chủ động làm yếu model đối chứng để tạo chênh lệch.

Tài liệu này bổ sung đề xuất, không thay thế kế hoạch BFCL đang được thảo luận và không xác nhận các ngưỡng ship còn bỏ ngỏ. Không sửa prompt, cấu hình model, worker hay script đo trong lần cập nhật này.

## Nhánh đã làm được gì

| Phần đã có | Ý nghĩa | Giới hạn bằng chứng |
| --- | --- | --- |
| Research báo provider chưa hỗ trợ bằng lỗi riêng | Không gửi nhầm yêu cầu JSON của model cloud sang Ollama | Chưa bổ sung JSON generation cho cloud |
| Factory khởi tạo client, caller khai báo provider được phép dùng | Giảm lặp cấu hình mà giữ phạm vi riêng cho API, worker, eval | Không phải bảng năng lực provider hay routing theo từng bước |
| Batch latest ingestion/version khi liệt kê | Loại các lượt đọc lặp đã được test ở đường document | Paper còn đường dự phòng đọc page count có thể phát sinh thêm truy vấn và mở tệp |

Bằng chứng hiện có nằm trong [báo cáo hồi quy](../../data/evaluation/results/kept/backend-small-fixes-2026-11-08/REPORT.md). Báo cáo không khẳng định nhanh hơn theo thời gian hay tốt hơn theo chất lượng model. Các đề xuất dưới đây chưa có kết quả đo.

## Việc nối tiếp trực tiếp từ nhánh này

### P1. Làm rõ năng lực và sự khác nhau giữa API với worker

Hiện API có thể tạo ngữ cảnh cho chunk bằng general model cloud; document worker chỉ có Ollama. Khi worker thiếu client, contextualization bắt lỗi theo chunk rồi tiếp tục index mà không có phần ngữ cảnh được tạo. Job không nhất thiết thất bại, nhưng nội dung index có thể khác giữa hai đường.

Đề xuất mới: có bản mô tả năng lực của cấu hình thực sự được resolve, kết hợp với allowlist của từng tiến trình. Phân biệt chat, tool calling, structured output và các vai trò cần dùng; không suy năng lực chỉ từ việc có API key. Trước tiên ghi rõ trạng thái contextualization là đầy đủ, bỏ qua có chủ đích hay suy giảm do lỗi trong metadata của ingestion.

Cần chốt hành vi sản phẩm riêng: báo không hỗ trợ; dùng một vai trò local cho chunk context; hoặc cho phép worker dùng provider cloud đã cấu hình. Không tự mở rộng allowlist hay âm thầm chuyển provider như một refactor nhỏ.

Kiểm chứng sau khi chọn: dùng client giả chạy cùng fixture qua thread và worker; đối chiếu provider/vai trò, số chunk được contextualize và trạng thái suy giảm. Không cần gọi model thật để chứng minh wiring.

### P1. Đo hết đường paper listing khi cache chưa có dữ liệu

`ResearchService._paper_rows()` đã batch các lượt đọc chính, nhưng `_total_pages()` vẫn có thể gọi `documents.source_file()` rồi đọc tệp cho từng paper. Test hiện tại thay source-file service bằng fake nên chưa chặn được toàn bộ đường phát sinh truy vấn lặp này.

Đề xuất: bổ sung fixture cache lạnh và cache ấm dùng document service thật với tệp nhỏ, trên database cô lập. Đếm riêng truy vấn SQL và lượt mở tệp. Nếu còn tăng theo số paper, ưu tiên lưu page count theo phiên bản tài liệu khi ingestion hoàn thành, hoặc lấy metadata nguồn theo lô. Quy tắc vô hiệu cache phải theo phiên bản, không chỉ document ID.

Chỉ đặt mục tiêu số truy vấn cho đường đã kiểm đầy đủ; không suy từ các lượt đọc chính ra tổng chi phí của endpoint.

### P1. Có bộ đối chiếu trace bằng model giả trước khi tách agent

Đề xuất mới: lưu fixture đầu vào/đầu ra của model và công cụ để đối chiếu hành vi trước/sau refactor. Các ca cần có: trả lời trực tiếp, công cụ lỗi, tham số sai, chờ duyệt, bị từ chối duyệt, hết thời gian và công cụ trả dữ liệu dài.

So sánh thứ tự gọi, tham số, quyền duyệt, kết quả và trạng thái kết thúc. Chuẩn hóa timestamp/ID ngẫu nhiên để diff hữu ích. Đây là kiểm tra giữ nguyên hành vi, không phải bài đo chất lượng model và không thay BFCL. Chỉ tách `AgentService` khi có điểm tựa này; không gom nhiều thay đổi hành vi vào cùng refactor.

## Những ý tưởng đáng học cho model nhỏ

Các dự án tham khảo cung cấp cơ chế thiết kế; chưa có bằng chứng chúng vượt Ún trên cùng nhiệm vụ, model và phần cứng. Trạng thái “đã có” dưới đây được đối chiếu với code của nhánh.

| Ưu tiên | Hiện trạng của Ún | Bổ sung hoặc tối ưu thế nào | Đo điều gì |
| --- | --- | --- | --- |
| P1 | Handler có kiểm tra riêng; `_run_tool()` chưa có validator schema chung | Kiểm JSON Schema trước khi xin duyệt và trước thực thi; trả lỗi chỉ đúng trường sai để model sửa trong ngân sách còn lại | Lệnh sai bị chặn trước tác dụng phụ; số lần sửa đúng; số lượt và thời gian thêm |
| P1 | `AGENT_GUIDE` viết cứng; danh sách schema được lấy từ registry | Sinh phần mô tả công cụ từ registry đang được phép dùng. Tách thay đổi mô tả khỏi thí nghiệm chính sách khi nào gọi công cụ | Tên công cụ không tồn tại, bỏ sót công cụ cần dùng, irrelevance và chat |
| P1 | Có cắt kết quả dài và `ContextBudget`, nhưng budget đang tắt; ước lượng dùng phần cố định hiệu chỉnh từ prompt cũ | Tính cả schema công cụ thực tế, lịch sử và phần dành cho câu trả lời; hiệu chỉnh theo model/template. Đo trước khi bật budget | Token đầu vào, chênh giữa ước lượng và thực tế, tràn cửa sổ, lỗi mất dữ kiện |
| P1 | Lịch sử lấy từ PostgreSQL hiện trả role/content; trace có lưu riêng | Giữ các biên nhận công cụ cần thiết qua lượt: ID kết quả, trạng thái, nguồn/phiên bản và phạm vi người dùng. Không nhét toàn bộ trace vào mọi prompt | Multi-turn tiếp tục đúng, không hỏi lại dữ kiện vừa có, không dùng dữ kiện đã xóa hoặc khác phạm vi |
| P1 | Có promise check và cơ chế sửa cho công cụ được đăng ký; chưa phải hợp đồng kết quả chung | Chuẩn hóa trạng thái `succeeded / failed / pending_approval / interrupted`. Với thao tác ghi, chỉ xác nhận thành công khi có biên nhận thực thi | Ca nói đã làm trong khi chưa làm; phân biệt chờ duyệt với thành công; số lần gọi kiểm tra thêm |
| P2 | `_offered_schemas()` hiện chủ yếu lọc theo khả năng xin duyệt | Khi số tool/schema thực sự lớn, thử nạp theo nhóm với đường tìm/bật nhóm còn thiếu. Nhóm công cụ không thay thế kiểm quyền | Token giảm, độ trễ, tác vụ thất bại vì tool bị ẩn; giữ thử nghiệm “gửi tất cả” làm đối chứng |
| P2 | Loop có giới hạn vòng và thời gian | Phát hiện gọi lặp theo tool + tham số chuẩn hóa + trạng thái/kết quả; cache chỉ cho thao tác đọc có điều kiện hợp lệ | Lượt gọi thừa giảm; không chặn phân trang, polling hoặc đọc sau khi dữ liệu đổi |
| P2 | `OllamaClient.chat_tools()` trả content/tool_calls nhưng chưa trả stop reason cho loop | Chuẩn hóa kết thúc bình thường, chạm giới hạn, lỗi parse và câu trả lời rỗng. Phân biệt model bị cắt với kết quả tool bị cắt | Lượt kết thúc giả thành công, lượt retry cứu được và chi phí retry |
| P3 | Model registry chọn theo vai trò lúc khởi động | Thử routing model nhỏ/lớn theo từng bước sau khi có trace và nhãn lỗi; ghi quyết định giả định trước khi cho router tác động | Chất lượng trên tập chưa dùng chọn router; chi phí router, tải lại model và fallback |

### Các ràng buộc khi áp dụng

**Schema:** MCP hiện cố ý rút gọn schema để giảm bề mặt prompt injection; `_property()` bỏ nhiều ràng buộc và cấu trúc lồng nhau. Cần tách schema thực thi đã kiểm soát khỏi bản mô tả ngắn cho model. Không đưa nguyên schema từ server vào prompt và không âm thầm sửa giá trị tham số làm thay đổi ý định. Với lệnh đã duyệt, kiểm lại tính hợp lệ mà không thay nội dung người dùng đã duyệt.

**Trạng thái qua lượt:** chỉ khôi phục kết quả trong đúng phạm vi truy cập; nguồn thay phiên bản hoặc người dùng xóa dữ liệu thì biên nhận phải được kiểm lại hoặc loại bỏ. Phân biệt “tool từng chạy” với “dữ liệu vẫn còn đúng”.

**Khôi phục sau gián đoạn:** lưu lịch sử gọi/kết quả là một việc, chạy lại thao tác ghi là việc khác. Muốn checkpoint từng bước phải có idempotency key hoặc cách đối soát. Kết quả không rõ sau timeout không được coi là chưa chạy rồi gọi lại ngay.

**Kiểm hoàn thành:** ưu tiên quy tắc dựa trên trạng thái thực thi và dữ kiện đã có. Không ép dùng tool chỉ vì benchmark thích tool, không thêm một lượt model phán xét vào mọi lời chào. Kiểm số liệu hiện có và promise check là nền tảng để mở rộng, không phải tính năng còn thiếu hoàn toàn.

**Routing:** không dùng câu “tôi tự tin” của model làm ngưỡng. Quyết định ghi thử vẫn có chi phí nếu gọi thêm model; đó không phải chế độ miễn phí. Nhãn model lớn cũng không mặc nhiên là đáp án đúng. Đánh giá nhiệm vụ độc lập và tính cả chi phí khi đổi model trên GPU hiện có.

## Thứ tự tôi đề nghị

| Giai đoạn | Việc nên làm | Điều kiện đi tiếp |
| --- | --- | --- |
| Trước thay đổi hành vi | Hoàn tất phép đo đang chạy; giữ nguyên model/config của nó. Chuẩn bị trace fixture, taxonomy lỗi và metadata cấu hình | Biết rõ lỗi thuộc chọn tool, tham số, mất trạng thái, kết thúc hay chất lượng trả lời |
| Backend tiếp nối | Chốt contextualization parity; kiểm đường page-count cache lạnh | Có test cô lập và mô tả chính xác phạm vi đã sửa |
| Harness nền tảng | Validator; biên nhận/trạng thái qua lượt; tính ngân sách prompt đầy đủ | Test có lỗi thực tế cần chặn, giữ nguyên quyền duyệt và đường trả lời trực tiếp |
| Thí nghiệm nhỏ | Mỗi lần thử một cơ chế: policy, budget, nạp tool theo nhóm hoặc chống gọi lặp | So với cùng model và cấu hình; không chọn và xác nhận trên cùng bài |
| Routing | Thử model nhỏ xử lý bước phù hợp, có đường chuyển lên model lớn | Thắng ở chất lượng/chi phí tổng, không chỉ token của một lần gọi |

Nếu cần chọn một phần harness để làm đầu tiên sau khi phép đo hiện tại kết thúc, tôi nghiêng về **validator schema + lỗi có cấu trúc**, rồi **biên nhận và trạng thái qua lượt**. Đây là giả thuyết ưu tiên dựa trên code: hai phần này đưa việc kiểm tra rõ ràng về code và cung cấp bằng chứng cho model nhỏ. Chưa khẳng định chúng cứu được bao nhiêu bài.

## Cách chứng minh harness có ích

Đăng ký trước ngưỡng chất lượng và chi phí trước khi xem kết quả ứng viên; dùng tập phát triển để chọn và tập khác để xác nhận. BFCL giữ nguyên giao thức chấm, đặc biệt vòng đầu và tool giả; bài sản phẩm dùng công cụ thật hoặc fixture tác dụng phụ được đối soát riêng.

Với từng model nhỏ được chọn, đối chiếu model có cùng tool interface và cấu hình suy luận nhưng không có cơ chế harness đang thử, harness hiện tại và harness thêm cơ chế đó. Model hiện tại là một mốc riêng. Nếu thử routing, tính cả mọi nhánh được gọi. Không thay nhiệt độ, giới hạn token hay cách gửi giữa các nhánh mà không ghi nhận.

Theo dõi song song hoàn thành tác vụ, gọi tool thừa, nói đã làm sai thực tế, lỗi quyền/duyệt, độ trễ và tổng token. Nếu có phép đo GPU/điện thì ghi cách đo riêng; token không thay thế được thời gian tải model hoặc chi phí phần cứng.

Thêm manifest cho mỗi lần chạy: commit, model/version hoặc digest đã resolve, template, tham số suy luận, provider được phép dùng, tool/schema hash, prompt hash và cờ tính năng. Chỉ ghi cấu hình cần tái lập, không ghi giá trị khóa hay nội dung môi trường. Chuẩn bị nối lại từ kết quả hợp lệ thay vì ghi đè; lỗi chạy không được đánh dấu như bài đã hoàn thành.

## Nguồn tham khảo và giới hạn suy luận

- [Mingbird — mã agent](https://github.com/Mingbird/Mingbird-agent/blob/main/ollama_agent.py): công cụ nền tảng và nạp thêm theo nhóm là mẫu đáng thử để giảm phần gửi ban đầu. Không sao chép số token hoặc ngưỡng của họ sang Ún. Chưa tái lập kết quả của dự án.
- [Qwen-Agent — BaseTool](https://github.com/QwenLM/Qwen-Agent/blob/main/qwen_agent/tools/base.py): helper kiểm tham số bằng JSON Schema là mẫu tham khảo cho lỗi có cấu trúc. Việc có helper không có nghĩa mọi tool đều tự động được kiểm; Ún cần đặt điểm kiểm chung rõ ràng.
- [Pydantic AI — message history](https://pydantic.dev/docs/ai/core-concepts/message-history/): lịch sử cần giữ quan hệ call/result, kể cả khi gián đoạn. Học nguyên tắc quản lý trạng thái, không cần thay framework hay coi sửa lịch sử là đã thực thi thành công.
- [Jev — decision points và modes](https://github.com/JevAgentHarness/JevAgentHarness/blob/main/docs/modes.md): có cách ghi quyết định mà chưa cho tác động, rồi hiệu chỉnh trên log. Tài liệu cũng giới hạn phạm vi bằng chứng; không suy rằng một router chắc chắn giúp model nhỏ của Ún.

Các nguồn web được đọc ngày 08/11/2026; liên kết trỏ nhánh tài liệu đang phát triển và có thể thay đổi. Trước khi triển khai cần pin commit tham khảo. Không có kết quả bên ngoài nào trong tài liệu này được coi là kết quả của Ún.

## Cập nhật sau khi đối chiếu main ngày 08/11

Báo cáo model nhỏ đã có trên main tại commit `c01d6dd`; vì vậy mốc "hoàn tất phép đo đang chạy" ở trên là bối cảnh của bản đề xuất đầu tiên. Không coi nó là lý do bắt đầu lại phép đo cũ.

Thứ tự ưu tiên cần cập nhật: tìm nguyên nhân mất bài nhiều lượt trước khi viết thêm validator hoặc routing. Runner hiện đã có `--max-steps` và `--carry-tool-traffic`; báo cáo main chỉ ra các giả thuyết về trần vòng, mất lịch sử công cụ và guide. Đã có một phép chẩn đoán riêng trong checkout main xét cả các yếu tố này. Dùng kết quả đó để chọn việc sửa, rồi xác nhận trên bài chưa dùng chọn; không nhân đôi phép đo hay tự tăng trần trong sản phẩm.

Validator vẫn là đề xuất củng cố hợp đồng công cụ, chưa được chứng minh là cách sửa phần tụt điểm lớn nhất. Các tối ưu nạp tool, ngân sách prompt và routing tiếp tục là thí nghiệm sau, không phải điều kiện để gộp các small fixes.

Đối chiếu code hai nhánh: agent loop, guide, context budget và cấu hình model giống nhau. Nhánh này có thể giảm chi phí đọc metadata và sửa thông báo provider; không có thay đổi hành vi agent để quy một mức tăng điểm harness cho nó.
