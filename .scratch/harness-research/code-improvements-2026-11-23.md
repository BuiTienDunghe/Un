# Cải tiến harness bằng code, 23/11/2026: đối chiếu pi, opencode, DeepSeek Harness

Status: code xong, test CPU xanh, chưa đo model
Type: task
Viết 23/11/2026. GPU và CPU đang dành cho dự án khác, nên đợt này chỉ sửa code và chạy test nhẹ. Mục sổ đo:
`docs/SO_DO.md`, 23/11/2026. Nền bằng chứng: `harness-survey-2026-11-23.md`, `breakthrough-plan.md`.

## Bản chất

Ba harness được khen nhiều nhất hiện nay đều làm một việc giống nhau: giữ phần model nhìn thấy thật gọn, và để code chặn
những lỗi lặt vặt trước khi chúng thành lỗi lớn. Đọc lại các lần đo đã lưu của chính Ún, model nhỏ không sai vì thiếu
hiểu biết. Nó sai ở những chỗ khung đặt bẫy: được đưa công cụ không dùng được ở đó, được cho xem phần đầu đoạn văn trong
khi đáp án nằm ở giữa, được trả lời "không có gì" khi chỉ là tìm sai chữ, và được để chạy lại y hệt một lệnh vừa chạy. Đợt
này gỡ bốn cái bẫy đó và một chỗ làm chậm, mỗi thứ sau một công tắc riêng, đều đang tắt. Kèm theo là một lỗi thật: bản trí
nhớ mới (đang bật) làm việc "tóm tắt tin gần đây" mất đúng những tin mới nhất.

## Ba harness làm gì, và Ún lấy gì

Nguồn: mã nguồn và tài liệu đọc ngày 23/11/2026; opencode đọc hai bản, v1.19.6 và nhánh `dev` (2.0). Ghi chú gốc nằm ngoài repo.

| Cơ chế | pi | opencode | DeepSeek Harness (`dsh`) | Ún |
|---|---|---|---|---|
| Lời dặn chỉ nói về công cụ đang có | — | 2.0: có (`system-prompt.ts`) | — | **lấy**: `scoped_tools` |
| Vòng cuối giữ danh sách công cụ để không phá phần đầu prompt đã đọc | — | 2.0: có (`runner/llm.ts`) | — | **lấy**: `final_keeps_tools` |
| Chặn lệnh lặp | — | v1: có (ngưỡng chưa kiểm được) | — | **lấy**: `dedupe_calls`, chặn ngay lần lặp đầu (Ún chỉ có 3 vòng) |
| Kiểm tham số theo schema, ép kiểu, trả lỗi kèm tham số đã nhận | có, ép kiểu | có, không ép kiểu | có, không sửa | **lấy, theo yêu cầu chủ dự án**: `validate_arguments`. Trên Agent Eval không đổi gì (0/4.129 lệnh đã lưu); lợi ích nếu có là ở MCP và công cụ ghi tệp |
| Sửa tên công cụ viết sai chữ hoa/thường | — | v1: có, rồi chuyển sang công cụ `invalid` | báo `UNKNOWN_TOOL` | **chưa**: 2B không gọi tên công cụ lạ nào trong 66 bài |
| Cắt kết quả công cụ dài | giữ đầu (đọc tệp) / đuôi (lệnh) | giữ đầu | khi thiếu chỗ: 4.096 đầu + 1.024 đuôi | đã có: bỏ nguyên mục theo danh sách |
| Dọn kết quả cũ khi gần đầy cửa sổ | không | v1: xoá kết quả cũ; 2.0: thang thu gọn không gọi model | giữ đầu + đuôi | đã có, đang tắt (ticket 44); **thêm bậc giữ đầu + đuôi**: `context_budget.keep_edges`, tắt |
| Không chạy lệnh gọi bị cắt ở trần độ dài | có | 2.0: có | — | không cần: vòng agent không đặt trần độ dài trả lời |
| Gọi lại một lần khi trả lời rỗng | — | — | có | **không lấy**: 0 câu rỗng trong 4.711 bài đã lưu |
| Trích đoạn quanh chỗ khớp | grep qua bash | công cụ grep | — | **lấy**: `focused_excerpts` |

Bằng chứng ngoài cho các cơ chế này yếu. Nghiên cứu duy nhất so harness ở model 2B (Mingbird, arXiv 2610.02001, do tác giả
một harness cạnh tranh viết) cho opencode 0,017 và Mingbird 0,821. Trong các phép bỏ từng phần của chính nghiên cứu đó, chỉ
bước kiểm hoàn tất có ý nghĩa thống kê; chặn lặp và thu gọn đầu ra thì không. Lý do Ún lấy các cơ chế dưới đây là lỗi đã
thấy trong dữ liệu của chính Ún, không phải số của nghiên cứu ngoài.

## Lỗi trong dữ liệu đã lưu (qwen3.5:2b, Agent Eval v0, 66 bài, chạy 10/11)

| Điều thấy | 2B | 9B | Bài |
|---|---:|---:|---|
| Lần gọi `search_documents` | 48 | 28 | — |
| Lệnh lặp y hệt trong cùng bài | 5 | 0 | doc-51, doc-53, doc-54 |
| Gọi `search_history` trên web, bị chấm trượt | 1 | 0 | doc-31 |
| Tìm lịch sử bằng từ khóa không khớp, rồi nói "không truy cập được" | 1 | 0 | hist-08 |
| Đáp án nằm sau ký tự 400 của đoạn, phải tốn một vòng đọc | 4 bài đọc, 1 vẫn trượt | — | doc-33..37 |
| Lượt hết vòng, phải buộc trả lời | 9 % số bài | 4,7 % | 132 bài 2B, 4.564 bài 9B, mọi lần đã lưu |

## Đã làm

| Thay đổi | Mặc định | Tệp | Vì sao |
|---|---|---|---|
| Sửa: đọc "tin gần đây" ở bản trí nhớ mới giữ tin mới nhất | **bật** (sửa lỗi) | `discord/source_memory.py` (`fit_history`) | Cắt ngân sách sau khi đã xếp cũ → mới, rồi `_dump` bỏ cuối: cả hai bước bỏ tin mới nhất. Bản cũ đã sửa đúng lỗi này (hist-05) |
| `scoped_tools` | tắt | `agent_service.py` (`agent_guide_for`, `AgentTool.discord_only`), bốn công cụ Discord | Không đưa công cụ chỉ chạy ở Discord ra lượt web; lời dặn chỉ nêu công cụ đang có. Khi đủ năm công cụ, lời dặn giống `AGENT_GUIDE` từng byte |
| `dedupe_calls` | tắt | `agent_service.py` (`DUPLICATE_CALL`) | Lệnh y hệt lệnh đã chạy được trong lượt thì không chạy lại; model nhận một câu ngắn thay vì bản sao kết quả. Lệnh lỗi vẫn được thử lại |
| `focused_excerpts` | tắt | `services/excerpts.py`, `agent_service.py` | Trích 400 ký tự khớp câu tìm kiếm nhất, có `excerpt_from`; chỉ dời khỏi phần đầu khi có cửa sổ khớp nhiều hơn hẳn. Mô tả hai công cụ đổi theo |
| `history_hints` | tắt | `discord/agent_tools.py`, `discord/source_memory.py` | Tìm theo từ khóa không ra gì thì bảo gọi lại không có từ khóa để xem tin gần đây |
| `final_keeps_tools` | tắt | `agent_service.py` (`_final_keeping_tools`) | Lượt buộc trả lời gửi kèm đúng danh sách công cụ như các vòng trước; lệnh gọi model viết thì không chạy; không có chữ thì hỏi lại không kèm công cụ như cũ |

Chỗ suýt sai đã chặn trong lúc làm: `_promises()` gọi danh sách công cụ không kèm ngữ cảnh lượt, nên khi bật `scoped_tools`
thì `remind` sẽ bị coi là không có ở mọi lượt và bước kiểm lời hứa tắt âm thầm. Đã truyền ngữ cảnh lượt; có test.

## Kết quả kiểm trên CPU

| Kiểm | Kết quả |
|---|---|
| 23 test mới | đạt (lần đầu 21/23; đã sửa cách chọn cửa sổ trích đoạn) |
| 43 tệp test agent, công cụ, bộ đo | 871 đạt, 65 bỏ qua (cần PostgreSQL hoặc BFCL), 1 hỏng do đường dẫn khác ổ, chạy lại đạt |
| Trích đoạn ngoại tuyến, 20 bài | đáp án lọt vào trích đoạn: 15 → 17; được doc-34, doc-37; không mất bài nào |

Chưa chạy: test cần PostgreSQL. Phần sửa `ScopedSearchHistory` chỉ được kiểm qua hàm thuần `fit_history`, chưa qua
database thật.

## Đo khi có GPU

Mỗi cờ một nhánh, cùng ngày, xen kẽ với đối chứng tắt cả năm, theo luật của `PREREGISTRATION-2b-baseline.md`
(nhiệt độ 0, seed 42, gỡ model trước mỗi bài). Từ `backend`:

```
..\.venv\Scripts\python.exe -X utf8 -m scripts.agent_eval --env-file ..\.env --model qwen3.5:2b --temperature 0 --seed 42 --unload-between-tasks --gpu-shared no --out <thư mục> --run-id <nhãn> [--scoped-tools | --dedupe-calls | --focused-excerpts | --history-hints | --final-keeps-tools]
```

Dự đoán, viết trước mọi lần đo:

| Cờ | Điểm Agent Eval /66 so với đối chứng | Thứ khác |
|---|---|---|
| `scoped_tools` | +0 đến +2 (doc-31) | rủi ro: hist-10 (hỏi lịch sử trên web) có thể đổi cách trả lời |
| `dedupe_calls` | ±1 | số vòng model trung bình giảm ở doc-51, doc-53, doc-54 |
| `focused_excerpts` | ±1 | doc-34, doc-37 bớt một lần `read_document`; trung vị độ trễ không tăng |
| `history_hints` | +0 đến +1 (hist-08) | — |
| `final_keeps_tools` | ±1 | số token Ollama báo đã dùng lại tăng ở lượt buộc trả lời; cần Ollama ≥ 0.33.3 để đọc số này |

Luật giữ: không bài `no_tool` nào gọi công cụ thêm; không bài nào trước đạt nay trượt mà không giải thích được; số vòng model
không tăng. Với 66 bài, chênh dưới khoảng 3 bài là nhiễu (mục 6 của bản khảo sát).

## Đợt 2 cùng ngày: hai ý chủ dự án yêu cầu làm luôn

| Thay đổi | Mặc định | Tệp | Ghi chú |
|---|---|---|---|
| `validate_arguments` | tắt | `services/tool_arguments.py`, `agent_service.py` | Chuyển kiểu chính xác, từ chối thiếu bắt buộc và sai kiểu không chuyển được, để qua mọi thứ không hiểu (kể cả enum lạ, vì MCP cắt bớt danh sách enum). Kiểm trước cả bước xin duyệt. BFCL không đọc cờ: ở BFCL nhiều lượt, lệnh chạy sẽ khác lệnh được chấm |
| `context_budget.keep_edges` | tắt | `services/context_budget.py` | Bậc thang: cắt mọi kết quả cũ còn 800 đầu + 200 đuôi trước, chưa vừa mới xoá từ cũ nhất. Đuôi giữ `next_from_chunk` và dấu đóng của lớp chống chèn lệnh |

Đếm ngoại tuyến `validate_arguments` trên 4.129 lệnh gọi đã lưu (131 tệp kết quả): 0 đổi kiểu, 0 từ chối. Dự đoán khi đo
`keep_edges` trên ctx-01..07: điểm ±1 bài so với budget không có nó; số lần model gọi lại đúng lệnh cũ giảm. Mục sổ đo: 23/11/2026,
"Kiểm tham số theo schema và giữ đầu-đuôi".

## Còn lại, xếp theo bằng chứng

1. Chuẩn hoá NFC hai phía trước khi so trích dẫn (pi so khớp sau chuẩn hoá); phải kiểm `answer_grounding.py` có làm chưa.
2. `prompt_hash` chỉ băm tin đầu (`chat_service.py:300`), nên không thấy được khi lời dặn hay công cụ đổi.
3. BFCL nhiều lượt với `validate_arguments`: phải ghi lệnh đã chuyển kiểu thay cho lệnh gốc thì mới chấm đúng.
