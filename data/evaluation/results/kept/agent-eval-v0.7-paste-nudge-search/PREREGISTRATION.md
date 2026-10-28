# Agent Eval v0.7 — ticket 20 #3-D, nhắc lại khi đoạn dán chưa đọc + tìm trong đoạn dán: đăng ký trước (opus 5.5, 28/10/2026, trước mọi lần chạy)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm công bố.

> **Sửa trước lần chạy lại (28/10, sau 22:45).** Bản gốc `347194a` (fable GỘP ĐƯỢC ở `73574da`) đã chạy được năm lần, theo
> chuỗi, rồi dừng: ba lần chạy một bài cho thấy câu trả lời của một bài phụ thuộc bài chạy ngay trước nó (ticket 20, 22:45;
> `diagnostics/`). Chủ dự án chọn cách 2: runner gỡ model trước mỗi bài, chỉ sửa mục Quy trình, chạy lại cả ba nhánh. Chủ dự
> án cũng bỏ phiếu lái sang tìm của 3' ("vậy bỏ"). Những gì đổi so với `347194a`:
> - Quy trình: mọi lần chạy dùng `--unload-between-tasks`; tên lần chạy mới `v0.7-3d-iso-*`; thêm điều kiện so
>   `unload_between_tasks: true`; ước lượng GPU mới.
> - Nhánh +1+3' dùng phiếu thu hẹp `92f5796`; các dự đoán của nhánh này viết lại theo phiếu đó. C3, C4 giữ nguyên.
> - Dự đoán "nền: doc-39..47 trùng #3-C phía sau" bỏ, vì #3-C là số theo chuỗi; thay bằng so với hai lần chạy một bài.
> - Điều kiện 47 bài không còn ngoại lệ hist-11.
> - Thêm kiểu trượt "lệnh công cụ hỏng → Ollama 500 → mất cả lượt", báo riêng.
>
> Luật B1–B4, C1–C4 và mọi dự đoán khác giữ nguyên chữ. Năm lần chạy theo chuỗi (`v0.7-3d-{base,nudge}-r{1,2}-cold`,
> `v0.7-3d-base-full-cold`) giữ trong thư mục này làm bằng chứng, không dùng cho luật.

Chủ dự án duyệt gói #3-D (28/10 21:20, nguyên văn ở ticket 20, 21:25): đo trên `int/20-3c`, không gộp #3-C trước; bước 1
nhắc lại một lần với lượt thử lại riêng; 3' cho `search_documents` tìm trong đoạn dán; một bản đăng ký ba nhánh; bài mới
mù, có ít nhất một bài đáp án sau đoạn 8.

- Nhân viên 1 viết bước 1 (`wip/20-paste-nudge`, `2955861` + `5e69dbe`, fable GỘP ĐƯỢC sau một lần sửa).
- Nhân viên 2 viết 3' (`wip/20-paste-search`, `f497da6` + `c270ded` + `92f5796`; phiếu thu hẹp ở `92f5796` chờ fable).
- Nhân viên 3 viết doc-48..53 (`wip/20-paste-tasks-d`, `a755981`, fable GỘP ĐƯỢC, đã gộp main `f45b764`) và runner gỡ model
  trước mỗi bài (`wip/20-eval-isolate`, chờ fable).

Người viết code nhánh không thấy bài mới, người viết bài không thấy code nhánh. Opus thấy cả hai và viết bản này trước khi
chạy; fable duyệt bản này trước lần chạy đầu.

## So cái gì

Ba commit trên một nhánh tạm, dựng sau khi bản sửa này, runner mới và bài duyệt của fable vào main. Không commit nào lên main
giữa lúc dựng và lúc đo xong; báo cáo ghi sha thật.

| Nhánh | Code | Khác nhánh trước ở đâu |
|---|---|---|
| **Nền** | `ed210e4` (`int/20-3c`, phiếu #3-C) gộp `--no-ff` main có bản này và runner mới | — |
| **+1** | Nền gộp `--no-ff` `wip/20-paste-nudge` `5e69dbe` | câu trả lời tự do nhờ dán lại, hoặc nói đã đọc hết, khi đoạn dán còn đoạn chưa đọc, bị trả lại một lần với lệnh `read_document` cụ thể; lượt thử lại riêng, không dùng chung với #2 |
| **+1+3'** | +1 gộp `--no-ff` `wip/20-paste-search` `92f5796` (xung đột duy nhất ở dòng import của `agent_service.py`: giữ cả hai) | `search_documents` xếp hạng các đoạn của đoạn dán bằng BM25, chỉ trên phần phiếu chưa cho thấy; phiếu thêm đúng một câu "search_documents tìm được trong văn bản dán, và kết quả cho chunk_index để đọc thẳng đoạn đó"; lệnh cụ thể duy nhất vẫn là đọc từ đoạn 0 |

Bộ bài `agent-eval-v0.7` (62 bài, sha `d87c4155eb3e…e56efb10`), bộ chấm `agent-eval-grader-v0.4` **nguyên vẹn** (gồm
`args_valid`, `max_tool_calls`, không ngoại lệ). Chạy **15 bài đoạn dán**: doc-39..53 (`--tasks`).

| Nhóm | Bài | Đáp án ở đoạn (đếm từ 0) / số đoạn | Lần đọc tối thiểu từ đoạn 0, mỗi lần 3 |
|---|---|---|---:|
| Đã thấy, cần phần giữa | doc-39 | 2 / 7 | 1 |
| | doc-40 | 3 / 8 | 2 |
| | doc-41 | 6 / 15 | 3 |
| | doc-43 | 1 và 5 / 10 | 2 |
| | doc-44 | 4 / 8 | 2 |
| | doc-46 | 7 / 12 | 3 |
| | doc-47 | 2 và 5 / 9 | 2 |
| Đã thấy, đáp án trong phiếu | doc-42 | mép cuối / 8 | 0 |
| | doc-45 | mép đầu / 10, `max_tool_calls: 0` | 0 |
| **Mới**, tới được bằng đọc lần lượt | doc-48 (i) | 5 / 8 | 2 |
| | doc-51 (l) | 0 (ngoài mép) và 6 / 9 | 3 |
| | doc-53 (n) | 6 / 11; đoạn mồi 8 trùng chữ câu hỏi, đoạn đáp án không trùng chữ nào | 3 |
| **Mới**, quá trần đọc lần lượt | doc-49 (j) | 10 / 15 (chỉ quá trần một đoạn: một lần đọc từ 9 phủ 9–11) | không tới |
| | doc-50 (k) | 14 / 25 | không tới |
| **Mới**, đáp án trong phiếu | doc-52 (m) | mép cuối / 9, `max_tool_calls: 0` | 0 |

Trần đọc lần lượt: mỗi lượt đọc tối đa 3 đoạn, mỗi lượt có 3 vòng công cụ, và mỗi lần thử lại (#2 hay bước 1) tiêu một vòng
trả lời để được thêm một vòng, nên một lượt đọc được nhiều nhất 3 lần: đoạn 0–8.

Doc-39..47 là bài đã thấy với cả ba nhánh: mẫu chữ của bước 1 viết từ câu trả lời doc-40, 44, 47, và Nhân viên 1 đã đọc câu
trả lời của cả 9 bài. **Luật chỉ đứng trên doc-48..53.**

## Quy trình

Worktree sạch tách tại đúng commit (`meas-<sha>`). Trước mỗi lần chạy: gỡ `qwen3.5:9b`, ghi `/api/ps` (`run_cold.sh`). Mọi
lần chạy dùng `--unload-between-tasks`: trước **mỗi** bài, kể cả bài đầu, runner gỡ model general, chờ `/api/ps` không còn
nó, nạp lại không prompt, rồi mới chạy bài; manifest ghi `unload_between_tasks: true`, mỗi dòng kết quả ghi `reload_ms`. t0,
seed 42, `--probe`, `--gpu-shared` theo thật. Từng lần một, đọc tin giữa các lần; nhiệt độ GPU > 85 °C thì dừng.

Thứ tự: nền r1, nền r2, +1 r1, +1 r2, +1+3' r1, +1+3' r2 (15 bài mỗi lần, `v0.7-3d-iso-{base,nudge,both}-r{1,2}`); rồi một
lần đủ 62 bài ở nền và một lần đủ 62 bài ở +1+3' (`v0.7-3d-iso-{base,both}-full`). Ước ~45 phút GPU: mỗi bài thêm một lần
gỡ và nạp, vài giây.

## Điều kiện phải đúng trước khi so (sai thì dừng)

- `tools_sha256` = `153209…a75e500`; `agent_guide_sha256`, `system_prompt_sha256` bằng nhau ở mọi lần chạy.
- `dataset.sha256` = `d87c4155eb3e…e56efb10` ở mọi lần chạy; `tasks_run` đúng 15 bài trên (hoặc đủ 62 ở hai lần đủ bộ).
- `unload_between_tasks: true` ở mọi lần chạy.
- Hai lần đủ bộ: 47 bài không có đoạn dán cho câu trả lời giống hệt nhau và cùng chuỗi công cụ ở nền và ở +1+3'. Sai
  thì dừng, không đề xuất gì, tìm nguyên nhân trước (hai thay đổi chỉ chạy khi lượt có đoạn dán).

## Đo gì

| Đo | Định nghĩa |
|---|---|
| **Đạt** | bộ chấm v0.4 nguyên vẹn; báo cáo nêu mục chấm nào trượt ở mỗi bài trượt |
| **Mở** | có ít nhất một lần gọi `read_document` với id `paste_…` |
| **Tới đáp án** | mọi đoạn đáp án nằm trong các `chunk_index` mà kết quả `read_document` của lượt trả về |
| **Bước 1 bắn** | có bước `unread_paste`; ghi mẫu (`asks_for_paste` / `claims_read_all`) và số đoạn đã đọc lúc bắn |
| **Tìm** (+1+3') | có gọi `search_documents`; kết quả có đoạn của đoạn dán không; đoạn đáp án có trong kết quả tìm không; lần đọc ngay sau có bắt đầu ở một `chunk_index` tìm được không |
| **Trả lời sau tìm mà không đọc** (+1+3') | có tìm, có kết quả ở đoạn dán, không có lần `read_document` nào sau đó |
| **Lộ lời nhắc** | câu trả lời cuối khớp `lời nhắc\|nhắc tới\|điều chỉnh lại\|kiểm tra lại câu trả lời\|trả lời lại\|hệ thống (yêu cầu\|nhắc)` (đọc tay mọi ca khớp) |
| **Mất lượt vì lệnh công cụ hỏng** | bài có `error` (Ollama trả 500 "tool call parsing failed", client báo "Cannot connect to Ollama"); vẫn tính trượt theo bộ chấm, báo riêng |
| Ghi thêm | `from_chunk`/`n` từng lần; bước `answer_check`; `stop_reason`; `tokens_in` lớn nhất; độ trễ; `reload_ms` |

## Dự đoán (sai thì báo; không sửa bài, code hay bộ chấm sau khi thấy kết quả)

| Dự đoán | Lý do |
|---|---|
| Nền: doc-41 trùng từng chữ `diagnostics/diag-base-doc41-alone`, doc-51 trùng `diagnostics/diag-base-doc51-alone` | gỡ model trước mỗi bài là để bài chạy như chạy riêng; khác thì "gỡ rồi nạp" chưa bằng "chạy riêng" (ví dụ do yêu cầu `--probe` lúc khởi động) |
| Nền: doc-49, doc-50 trượt | quá trần đọc lần lượt |
| Nền: doc-52 đạt, không gọi công cụ | như doc-45 ở #3-C |
| +1: doc-39, 41, 42, 43, 45, 46 trùng từng byte nền | mẫu chữ không bắn trên 20 câu đạt đã lưu (Nhân viên 1, fable kiểm lại); không bắn thì đầu vào model không đổi; bài nào cũng chạy trên model vừa nạp |
| +1: bước 1 bắn ở doc-40, 44, 47 | đúng ba câu đã thấy nó bắn |
| +1: doc-49, doc-50 vẫn trượt | bước 1 không vượt trần |
| +1: doc-52 trùng nền | không đọc, không có gì để bước 1 bắt |
| +1+3': doc-52 đạt, không gọi công cụ | phiếu vẫn đặt "đủ thì trả lời luôn" trước |
| +1+3': `search_documents` được gọi ở ít hơn một nửa trong 12 bài cần phần giữa | lệnh cụ thể duy nhất của phiếu vẫn là đọc từ đoạn 0; ở #3-C, 5/5 lần mở đầu làm đúng lệnh cụ thể của phiếu |
| +1+3': doc-49 và doc-50 vẫn trượt, tức C3 sai | như trên: model đọc lần lượt tới đoạn 8 rồi hết lượt |
| +1+3': doc-53 cùng đạt/trượt với +1 | không tìm thì không gặp đoạn mồi; đọc lần lượt tới đoạn 6 ở lượt thứ ba như ở +1 |
| Mỗi nhánh r1 trùng r2 từng chữ | t0, seed 42, mỗi bài trên model vừa nạp |

**Không dự đoán** doc-48, 51 ở nền và +1, và doc-39, 41, 43, 46 ở +1+3' (câu mới trong phiếu đổi đầu vào của mọi bài đoạn
dán, nên câu trả lời đổi chữ; đạt hay không thì chưa biết). Luật điều C2 bắt bài lùi.

## Luật quyết định (đặt trước khi thấy kết quả)

Hai đề xuất tách riêng; chủ dự án quyết gộp. r1 và r2 khác nhau thì đọc theo hướng bất lợi cho đề xuất: một bài "đạt ở nhánh
so" nếu một lần đạt; "đạt ở nhánh đề xuất" chỉ khi cả hai lần đạt.

**Đề xuất B — gộp #3-C + bước 1 vào main** nếu cả bốn điều sau đúng (so +1 với nền):

- B1. Các điều kiện so ở trên đúng.
- B2. Không bài nào trong 15 bài đạt ở nền mà trượt ở +1.
- B3. Gọi k là số bài trượt ở nền trong {doc-48, doc-51, doc-53} (bài mới, tới được bằng đọc lần lượt). Số bài từ trượt
  thành đạt trong nhóm đó ≥ max(1, ⌈k/2⌉). k = 0 thì B3 sai: không có bằng chứng bước 1 làm được gì trên bài mới.
- B4. Mọi bài tính ở B3 có bước `unread_paste` ở cả hai lần +1 (bước 1 làm, không phải ngẫu nhiên).

**Đề xuất C — gộp thêm 3'** nếu cả bốn điều sau đúng (so +1+3' với +1):

- C1. Các điều kiện so ở trên đúng.
- C2. Không bài nào trong 15 bài đạt ở +1 mà trượt ở +1+3'.
- C3. Ít nhất một trong doc-49, doc-50 (quá trần) từ trượt ở +1 thành đạt ở +1+3'.
- C4. Mọi bài tính ở C3, ở cả hai lần +1+3', có một lần `search_documents` trả đoạn của đoạn dán **trước** lần
  `read_document` tới được đoạn đáp án.

C xét độc lập với B: B trượt mà C đạt thì báo cả hai, chủ dự án quyết. Một điều sai thì báo kèm câu trả lời, không tự sửa tiếp.
B đạt nghĩa là gộp cả phiếu #3-C, thứ đã trượt luật riêng của nó; báo cáo nhắc điều đó ngay cạnh kết luận B (fable).

Báo cáo tách riêng, không gọi một lần đạt luật là "đọc được đoạn dán dài":

- bước 1 bắn ở bài nào, mẫu nào, bắn rồi có tới đáp án không;
- tìm ra đoạn đáp án ở bao nhiêu bài cần phần giữa;
- trả lời sau tìm mà không đọc: x/y;
- lộ lời nhắc: x/y;
- mất lượt vì lệnh công cụ hỏng: bài nào, nhánh nào;
- `tokens_in` lớn nhất mỗi nhánh.

Bảng điểm: lần đo 15 bài là lần đo một phần, không `--append-history`; hai lần đủ bộ chỉ dùng cho điều kiện 47 bài, cũng không
`--append-history` (chưa có gì được gộp). `analyze.py` bên cạnh tệp này được commit cùng bản sửa, trước lần chạy lại đầu: nó
là cách tính luật, không viết lại sau khi thấy số.

## Giới hạn đã biết

- 6 bài mới là bằng chứng duy nhất chưa bị nhìn thấy; mỗi bài một câu hỏi. Đủ để thấy hai thay đổi có làm được việc nó nhắm
  không, chưa đủ để nói tỉ lệ trên đoạn dán thật.
- Phiếu #3-C so với phiếu cũ trên main chưa đo trên doc-48..53: gói duyệt đo trên `int/20-3c`, không có nhánh phiếu cũ.
- Mọi số Agent Eval trước bản sửa này, kể cả năm lần chạy theo chuỗi trong thư mục này, là **số theo chuỗi**: chỉ so được với
  lần chạy cùng chuỗi bài (`kept/README.md`).
- Bước 1 chỉ bắt hai kiểu chữ đã thấy (nhờ dán/gửi/tải/cung cấp lại văn bản hay phần giữa; nói đã đọc hết/toàn bộ/đầy đủ).
  Kiểu "bạn có muốn tôi đọc tiếp không?", "cung cấp thêm thông tin" và "cần xem lại văn bản" (doc-47 theo chuỗi) không làm
  nó bắn.
- Bước 1 chỉ ở nhánh model tự trả lời; câu trả lời ép khi hết vòng công cụ không bị trả lại (doc-49 theo chuỗi: "đã đọc
  toàn bộ văn bản (15 đoạn)" sau 9 đoạn).
- Câu "không nhắc tới lời nhắc này" là cách giảm lộ, chưa phải bằng chứng; lộ vẫn được đếm.
- Bộ chia đoạn bỏ các dòng tiêu đề đánh số không có dấu câu cuối khỏi phần chữ (Nhân viên 3, fable): doc-39, 40, 41, 43 mất
  8, 6, 11, 5 dòng tiêu đề, không dòng nào chứa đáp án. Đè đều lên ba nhánh; sửa là việc riêng.
- Lệnh công cụ hỏng làm mất cả lượt (`ollama_client.py:129` báo "Cannot connect to Ollama"); việc riêng, không sửa ở đây.
- doc-49 chỉ quá trần một đoạn; doc-50 là bài xa hẳn.
- Mẫu số chỉ nhận chữ số ("sáu ngày" trượt), như v0.5/v0.6.
- doc-53 đo truy vấn bằng chữ của câu hỏi; truy vấn thật do model tự đặt.
