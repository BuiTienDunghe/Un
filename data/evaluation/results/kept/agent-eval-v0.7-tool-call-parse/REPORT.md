# Agent Eval v0.7 — ticket 27, lệnh gọi công cụ viết hỏng: báo cáo (opus 5.5, 29/10/2026 00:40)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Đo đúng `PREREGISTRATION.md` `26616b3` (fable GỘP ĐƯỢC ở
`53b1e80`). `analyze.py` tính `analysis.json`.

**Kết luận: đạt cả bốn điều của luật; đề xuất gộp ticket 27 vào main.**

## Bản chất

Trước khi sửa, khi model viết hỏng lệnh gọi công cụ, cả lượt mất: người dùng không nhận được gì, còn log báo nhầm là không
kết nối được. Sau khi sửa, cùng đầu vào ấy cho ra một câu trả lời. Agent nhắc model gọi lại, model gọi lại được, đọc văn bản
rồi trả lời. Ở những bài không gặp lỗi này, bản sửa không đổi gì: 62 bài trên main ra y hệt nhau từng chữ.

## Điều kiện so

| Điều kiện | Kết quả |
|---|---|
| Commit | tái hiện: trước `2839b52`, sau `48b5c0f` (`int/27-repro`); tác dụng phụ: M0 `53b1e80` (main), M1 `a2b7bde` (`int/27-main`) |
| `tools_sha256` `153209…a75e500`, `agent_guide_sha256`, `system_prompt_sha256` bằng nhau trong mỗi phép so | đúng |
| Bộ bài v0.7 `d87c4155eb3e…e56efb10`; `unload_between_tasks: true` ở 6 manifest; `tasks_run` đúng | đúng |
| GPU | 45–56 °C, không chia GPU |

## Luật

| Điều | Kết quả |
|---|---|
| 1. Điều kiện so | đúng |
| 2. Tái hiện: doc-44 phía trước mất lượt cả hai lần | đúng: `OllamaUnavailableError: Cannot connect to Ollama` ở cả hai lần |
| 3. Phía sau, cả hai lần: không mất lượt, có bước `tool_call_error` (`TOOL_CALL_PARSE`), có câu trả lời | đúng |
| 4. Mọi bài M1 không bật bước sửa đều giống hệt M0 | đúng: 62/62 giống hệt, không bài nào trên main bật bước sửa |

## doc-44 sau khi sửa (r1 = r2 từng chữ)

| Vòng | Việc |
|---|---|
| 1 | model viết hỏng lệnh gọi công cụ, Ollama trả 500 → bước `tool_call_error`, tin nhắc gọi lại |
| 2 | model trả lời mà chưa đọc, nhờ người dùng cung cấp phần thiếu → bước nhắc đoạn dán (của nhánh +1+3') bật |
| 3–4 | đọc `read_document` (0, 3), tức đoạn 0–2, chưa tới đoạn 4 có đáp án; rồi trả lời (`stop_reason: final`) |

Câu trả lời nêu **sai** nơi nghỉ ("Bản Nậm Sương"; đúng là "Đá Vàng", ở đoạn 4) và không có mức phụ thu 380.000, nên bộ chấm
cho trượt `must_mention`. Luật không đòi bài này đạt. Lần thử lại **viết được lệnh đúng**, không phải đi đường ép không công cụ.

## Dự đoán

| Dự đoán | Đúng? |
|---|---|
| Trước: doc-44 mất lượt cả hai lần | đúng |
| Sau: không mất lượt, có bước sửa, có câu trả lời, cả hai lần | đúng |
| Sau: r1 trùng r2 | đúng |
| M1 trùng M0 62/62, không bài nào trên main bật bước sửa | đúng |

## Mốc mới và một phép so ngoài luật

M0 là lần chạy đủ bộ cô lập đầu tiên **trên main**: **45/62** (phiếu #3). Main và nhánh nền #3-D chỉ khác nhau ở lời phiếu đoạn
dán (`git diff 94e321f 26616b3 -- backend/app` chỉ có `pastes.py`; fable). Vì vậy M0 so với
`../agent-eval-v0.7-paste-nudge-search/v0.7-3d-iso-base-full` chính là phiếu #3 so với phiếu #3-C, đều cô lập. Phép so này
**không đăng ký trước**, nên không dùng để quyết gộp #3-C; ghi ra để chủ dự án có số.

| Đo | Phiếu #3 (main, M0) | Phiếu #3-C (nền #3-D) |
|---|---|---|
| 62 bài | 45 | 50 |
| 47 bài không dán | giống hệt nhau 47/47 | |
| 15 bài đoạn dán | 5 | 10 |
| 6 bài mới | 3 | 4 (doc-48 trượt → đạt) |
| Bài đạt ở #3 mà trượt ở #3-C | — | 0 |

Với phiếu #3, model hay tìm trong thư viện thay vì mở văn bản dán: doc-39, doc-41 (tìm ba lần), doc-50. Với #3-C, model mở
văn bản dán. Theo luật riêng của #3-C (28/10), phiếu này vẫn trượt điều 3 dưới cô lập: trong doc-44, 46, 47, chỉ doc-46 từ
trượt thành đạt.

## Giới hạn

- Một ca tái hiện, trên nhánh chưa gộp; main không có ca nào dưới cô lập. Phép đo chứng minh bản sửa làm đúng việc trên một
  đầu ra hỏng thật, không chứng minh tần suất lỗi.
- Chỉ bắt chữ "XML syntax error". Lỗi cú pháp khác vẫn mất lượt, nhưng nay báo đúng mã và chữ lỗi.
- Hai cột bảng điểm vẫn coi lượt `tool_call_error` là thiếu; nên sửa trước khi bảng điểm dùng cho mốc chính thức (fable).
- `chat_service.py:173` ghi lượt `tool_call_error` là "ok", không mã riêng; nhất quán với `max_steps` và `turn_budget`.
- Mọi số trước #3-D bản cô lập là số theo chuỗi.
