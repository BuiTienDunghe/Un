# Agent Eval v0.7 — ticket 27, lệnh gọi công cụ viết hỏng: đăng ký trước (opus 5.5, 29/10/2026, trước mọi lần chạy)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm công bố.

Chủ dự án chọn B sau #3-D (28/10 23:58): "sửa lỗi lệnh công cụ hỏng làm mất cả lượt (bắt Ollama 500 tool call parsing
failed, thử lại một lần, báo đúng tên lỗi), đo dưới cô lập." Nhân viên 1 sửa ở `wip/27-tool-call-parse` `c144999` (chờ
fable). Đề bài: `.scratch/foundation-and-agent-eval/issues/27-malformed-tool-call.md`.

## So cái gì

Mọi lần chạy dùng `--unload-between-tasks` (gỡ model trước mỗi bài), t0, seed 42, `--probe`, `--gpu-shared` theo thật, lạnh
(`run_cold.sh`). Commit dựng sau khi bản này, bài duyệt của fable và nhánh sửa đều xong; báo cáo ghi sha thật.

| Phép so | Trước | Sau | Bài |
|---|---|---|---|
| **Tái hiện** | `2839b52` (nhánh +1+3' của #3-D, nơi doc-44 mất lượt 3/3 lần dưới cô lập) | `2839b52` gộp `--no-ff` `wip/27-tool-call-parse` (xung đột duy nhất: hai hằng nhãn tiến độ, giữ cả hai) | doc-44, 2 lần mỗi bên |
| **Tác dụng phụ** | main có bản này (M0) | M0 gộp `--no-ff` `wip/27-tool-call-parse` (M1); đây là thứ sẽ vào main | đủ 62 bài, 1 lần mỗi bên |

Bộ bài `agent-eval-v0.7` (sha `d87c4155eb3e…e56efb10`), bộ chấm v0.4 nguyên vẹn. Thứ tự: tái hiện trước r1, trước r2, sau r1,
sau r2; rồi M0 đủ bộ, M1 đủ bộ. Ước ~22 phút GPU. Nhiệt độ GPU > 85 °C thì dừng.

## Điều kiện phải đúng trước khi so (sai thì dừng)

- `tools_sha256` = `153209…a75e500`; `agent_guide_sha256`, `system_prompt_sha256` bằng nhau ở mọi lần chạy cùng phép so.
- `dataset.sha256` = `d87c4155eb3e…e56efb10`; `unload_between_tasks: true` ở mọi manifest.
- `tasks_run`: đúng `doc-44` ở bốn lần tái hiện; đủ 62 ở hai lần đủ bộ.

## Đo gì

| Đo | Định nghĩa |
|---|---|
| **Mất lượt** | dòng kết quả có `error` (không có câu trả lời) |
| **Bước sửa bật** | có bước `kind: "tool_call_error"` với `error_code: "TOOL_CALL_PARSE"`; đếm số lần trong lượt |
| **Kết thúc** | `stop_reason` của bước cuối; câu trả lời có rỗng không |
| **Đạt** | bộ chấm v0.4; ghi lại, không có luật nào đòi doc-44 đạt |
| **Giống hệt** | cùng câu trả lời và cùng chuỗi lệnh công cụ (tên + tham số) |

## Dự đoán (sai thì báo; không sửa code sau khi thấy kết quả)

| Dự đoán | Lý do |
|---|---|
| Trước: doc-44 mất lượt ở cả hai lần | 3/3 lần dưới cô lập ở #3-D, và lần bắt thân lỗi lúc 23:55 |
| Sau: doc-44 không mất lượt, có bước `tool_call_error`, có câu trả lời không rỗng, ở cả hai lần | đó là việc bản sửa làm |
| Sau: r1 trùng r2 từng chữ | t0, seed 42, cô lập |
| M1 trùng M0 ở cả 62/62 bài, và không bài nào có bước `tool_call_error` trên main | main mang phiếu #3, không phải phiếu của nhánh +1+3'; dưới cô lập, nhánh nền #3-D đủ bộ không có lỗi 500 nào |

**Không dự đoán** doc-44 có đạt không sau bản sửa: lần thử lại có tin nhắc, nên đầu vào khác và câu trả lời chưa biết.

## Luật quyết định (đặt trước khi thấy kết quả)

Đề xuất gộp ticket 27 vào main nếu cả bốn điều sau đúng:

1. Các điều kiện so ở trên đúng.
2. Tái hiện được: doc-44 ở phía trước mất lượt ở cả hai lần. Sai thì không có gì để chứng minh bản sửa trên model thật; báo
   lại, không đề xuất, chủ dự án quyết.
3. Bản sửa làm được việc: doc-44 ở phía sau, cả hai lần, không mất lượt, có bước `tool_call_error`, và có câu trả lời không
   rỗng.
4. Không tác dụng phụ: mọi bài trong 62 bài mà M1 không có bước `tool_call_error` thì giống hệt M0.

Bảng điểm: hai lần đủ bộ không `--append-history`; M0 là mốc main đủ bộ dưới cô lập đầu tiên, báo cáo ghi điểm của nó. Hai
cột bảng điểm coi lượt `tool_call_error` là thiếu (`max_steps_matches_budget_exhausted`, `rounds_timed_and_counted`, NV1 đã
ghim bằng test): không đọc chúng là thụt lùi. `analyze.py` bên cạnh tệp này được commit cùng bản đăng ký, trước lần chạy đầu.

## Giới hạn đã biết

- Một bài tái hiện, trên nhánh chưa gộp; main chưa có ca tái hiện nào dưới cô lập. Phép đo chứng minh bản sửa làm đúng việc
  trên một đầu ra hỏng thật, không chứng minh tần suất lỗi.
- Chỉ bắt chữ "XML syntax error" trong thân lỗi 500. Parser khác từ chối bằng chữ khác thì vẫn đi đường thử lại ba lần (lỗi
  cuối nay nêu mã và chữ của server).
- Tin nhắc nằm lại trong ngữ cảnh cho các vòng sau, như lời nhắc của #2.
- `chat_service.py:173` ghi lượt `tool_call_error` là "ok", không có mã riêng; dashboard không tách được. Ngoài phạm vi, để chủ
  dự án quyết.
- Mọi số Agent Eval trước #3-D bản cô lập là số theo chuỗi; không so với số ở đây.
