# Agent Eval v0.7 — ticket 20 #3-D: báo cáo (opus 5.5, 28/10/2026 23:50)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Đo đúng `PREREGISTRATION.md` bản sửa `28df7c7` (fable GỘP
ĐƯỢC ở `b103ef3`). `analyze.py` tính `analysis.json`.

**Kết luận: cả hai đề xuất trượt luật. Không gộp gì; main giữ phiếu #3.**

- Đề xuất B (#3-C + nhắc lại) trượt điều B3.
- Đề xuất C (thêm tìm trong đoạn dán) trượt điều C2 và C3.

## Bản chất

Ba nhánh làm đúng như nhau trên 6 bài mới: mỗi nhánh đạt 4/6, trượt đúng hai bài có đáp án nằm sâu quá đoạn 8.

- **Lời nhắc** chỉ bật ở một bài, và không cứu được bài đó.
- **Công cụ tìm** được model dùng ở 3 bài:
  - một bài nhờ tìm mà đọc ít hơn vẫn đúng;
  - một bài vì tìm mà chỉ đọc một cửa sổ, sót mảnh thứ hai nên trượt;
  - hai bài cần tìm nhất thì model không hề tìm.

Phần đứng được của lần đo này là cách đo. Gỡ model trước mỗi bài làm kết quả không còn phụ thuộc thứ tự chạy, và lần đủ 62
bài ở nền là mốc sạch đầu tiên của Agent Eval.

## Điều kiện so

| Điều kiện | Kết quả |
|---|---|
| Commit đo | nền `94e321f`, +1 `04b89a2`, +1+3' `2839b52` (nhánh tạm `int/20-3d-iso`), worktree sạch |
| `tools_sha256` `153209…a75e500`, `agent_guide_sha256`, `system_prompt_sha256` bằng nhau ở 8 lần chạy | đúng |
| `dataset.sha256` `d87c4155eb3e…e56efb10` (v0.7, 62 bài); `tasks_run` đúng 15 bài | đúng |
| `unload_between_tasks: true` ở mọi manifest | đúng; `reload_ms` trung vị 2,8 s, bài đầu mỗi lần ~6 s |
| 47 bài không dán, nền đủ bộ so với +1+3' đủ bộ: câu trả lời và chuỗi công cụ | 47/47 giống hệt |
| r1 = r2 mỗi nhánh | 15/15 cả ba nhánh |
| GPU | 46–58 °C; không chia GPU (`--gpu-shared no`) |

Hai lớp kiểm cô lập (ghi chú 2 của fable) đều qua:

- nền doc-41 và doc-51 trùng từng chữ hai lần chạy riêng trong `diagnostics/`;
- ở +1, 14 bài lời nhắc không bật trùng từng chữ nền;
- thêm một kiểm: 15 bài đoạn dán trong lần đủ 62 bài trùng lần chạy 15 bài ở cả nền và +1+3' (15/15). Theo chuỗi chỉ trùng
  3/15.

## Luật

| Điều | Kết quả | Vì sao |
|---|---|---|
| B1 điều kiện | đúng | |
| B2 không đạt → trượt (nền → +1) | đúng | không bài nào đổi điểm |
| **B3** bài mới tới được, trượt → đạt | **sai** | k = 0: doc-48, 51, 53 đều đạt sẵn ở nền, nên không có bằng chứng bước 1 làm được gì trên bài mới |
| B4 quy nguyên nhân | đúng (không có bài nào để xét) | |
| C1 điều kiện | đúng | |
| **C2** không đạt → trượt (+1 → +1+3') | **sai** | doc-43 đạt → trượt, `must_mention` |
| **C3** bài quá trần trượt → đạt | **sai** | doc-49, doc-50 trượt ở cả ba nhánh; ở +1+3' không bài nào gọi tìm |
| C4 quy nguyên nhân | đúng (không có bài nào để xét) | |

B đạt thì sẽ gộp cả phiếu #3-C, thứ đã trượt luật riêng của nó; B không đạt nên câu đó không cần bàn.

## Điểm

| Nhánh | 15 bài đoạn dán | 6 bài mới | Đủ 62 bài |
|---|---|---|---|
| Nền | 10 | 4 | **50** (47 bài không dán: 40) |
| +1 | 10 | 4 | — |
| +1+3' | 9 | 4 | 49 |

## Từng bài (r1 = r2, nên một dòng cho mỗi nhánh)

Ký hiệu: Đ đạt, T trượt; số trong ngoặc là `from_chunk` từng lần đọc.

| Bài | Nền | +1 | +1+3' |
|---|---|---|---|
| doc-39 | Đ (0) | Đ (0) | Đ (0) |
| doc-40 | T: gọi `search_history` bị cấm, không đọc | T `tools_forbidden`: **nhắc bật**, đọc (0)(3), câu trả lời đủ ý; trượt vì vòng đầu đã gọi `search_history` | T: đọc (0), thiếu ý |
| doc-41 | Đ (0)(3)(6), hết lượt | Đ, như nền | Đ: **tìm** → đoạn 6, 4, 7 → đọc (4); một lần đọc thay ba |
| doc-42 | Đ, không đọc | Đ | Đ |
| doc-43 | Đ (0)(3) | Đ | **T**: **tìm** → đoạn 0, 1, 3 → đọc (1) → thấy người phụ trách ở đoạn 1, sót hạn nộp ở đoạn 5, nói "văn bản không nêu" |
| doc-44 | T: bị kiểm số bác, không đọc, nói văn bản không ghi | T, như nền | T: **mất lượt**, lệnh công cụ hỏng (Ollama 500 ba lần) |
| doc-45 | Đ, không đọc | Đ | Đ |
| doc-46 | Đ (0)(3)(6), hết lượt | Đ | Đ |
| doc-47 | T: bị kiểm số bác, đọc (0), thiếu khoản giữ cọc | T, như nền | T: **tìm** → không có kết quả ở đoạn dán, không đọc |
| doc-48 | Đ (0)(3) | Đ | Đ |
| doc-49 | T: (0)(3)(6), hết lượt, đoán "thường do Ban quản lý" | T, như nền | T: như nền, không tìm |
| doc-50 | T: (0)(3)(6), hết lượt, gợi ý theo "thông lệ chung" | T, như nền | T: gọi `search_history` bị cấm, nói `search_documents` không đọc được văn bản dán, nhờ "copy lại toàn bộ văn bản" |
| doc-51 | Đ (0)(3)(6), đọc tới đoạn 6 | Đ | Đ theo bộ chấm, nhưng **đoán**: đọc (0), viết "thông thường … 3-7 ngày"; mẫu `7\s*ngày` khớp "3-7 ngày" |
| doc-52 | Đ, không gọi công cụ | Đ | Đ |
| doc-53 | Đ (0)(3)(6), không gặp đoạn mồi | Đ | Đ, không tìm |

## Các dòng tách riêng (như đã đăng ký)

| Dòng | Nền | +1 | +1+3' |
|---|---|---|---|
| Bước 1 bắn | — | doc-40 (`asks_for_paste`), cả hai lần; đọc tới đáp án, vẫn trượt `tools_forbidden` | 0 bài |
| Gọi tìm, trong 12 bài cần phần giữa | — | — | 3 (doc-41, 43, 47) |
| Tìm ra đoạn đáp án | — | — | doc-41 (đủ), doc-43 (một trong hai mảnh); doc-47 không ra |
| Không gọi tìm / tìm không ra | — | — | 9 / 1 (doc-47) |
| Trả lời sau tìm mà không đọc | — | — | 0 (doc-47 tìm không ra rồi không đọc) |
| Lộ lời nhắc (đọc tay) | 0 | 0 | 1: doc-41 mở bằng "Xin lỗi, tôi cần kiểm tra lại câu trả lời của mình", là lời nhắc **của bước kiểm số #2** (bị kiểm số bác ở vòng đầu), không phải của bước 1 |
| Mất lượt vì lệnh công cụ hỏng | 0 | 0 | doc-44, cả 3 lần (r1, r2, đủ bộ) |
| `tokens_in` lớn nhất một bài (cộng các vòng) | 17 550 | 17 550 | 17 607 |

## Dự đoán

| Dự đoán | Đúng? |
|---|---|
| Nền doc-41, doc-51 trùng lần chạy riêng | đúng |
| Nền: doc-49, 50 trượt; doc-52 đạt không gọi công cụ | đúng |
| +1: sáu bài không đổi trùng nền từng byte | đúng (thực tế 14/15 bài trùng; chỉ doc-40 khác) |
| +1: bước 1 bắn ở doc-40, 44, 47 | **sai**: chỉ doc-40. Chạy cô lập, câu trả lời doc-44, 47 khác bản theo chuỗi mà mẫu chữ đã học: doc-44 không nhờ dán mà nói "văn bản không ghi rõ"; doc-47 không nói "đã đọc đầy đủ" |
| +1: doc-49, 50 vẫn trượt; doc-52 trùng nền | đúng |
| +1+3': doc-52 đạt không gọi công cụ | đúng |
| +1+3': tìm được gọi ở dưới nửa 12 bài cần phần giữa | đúng (3/12) |
| +1+3': doc-49, 50 vẫn trượt (C3 sai) | đúng |
| +1+3': doc-53 cùng đạt/trượt với +1 | đúng |
| r1 = r2 mỗi nhánh | đúng |

## Phát hiện ngoài luật

1. **Bộ chấm cho doc-51 ở +1+3' đạt nhờ một con số đoán.** Mẫu `(?<!\d)7\s*ngày` khớp "3-7 ngày" trong câu "thông
   thường… 3-7 ngày". Không đổi kết luận, vì C đã trượt ở C2. Không sửa bộ chấm sau khi thấy kết quả; ghi lại để lần sau.
2. **Lệnh công cụ hỏng làm mất cả lượt** gặp lại dưới cô lập: doc-44 ở +1+3', lặp đúng ở cả ba lần chạy. Như vậy đó là hành
   vi thật của model trên đầu vào ấy, không do thứ tự. Ollama trả 500 "tool call parsing failed"; `ollama_client.py:129` báo
   "Cannot connect to Ollama"; người dùng không nhận được gì.
3. **Câu "search_documents tìm được trong văn bản dán" có thể làm model sai theo kiểu khác.** Ở doc-50, model nói
   ngược lại phiếu ("search_documents… chỉ đọc các tài liệu đã upload"), gọi công cụ bị cấm và nhờ người dùng copy lại
   văn bản. Bước 1 không bắt câu này, vì "copy" không có trong mẫu chữ.
4. **Câu trả lời ép khi hết lượt** (doc-49, 50 ở cả ba nhánh) đoán hoặc lấy "thông lệ chung" thay vì nói rõ là chưa đọc tới.
   Bước 1 không chạy ở nhánh ép, như bản đăng ký đã ghi.

## Mốc mới

Nền đủ 62 bài, gỡ model trước mỗi bài: **50/62** trên `agent-eval-v0.7`, commit `94e321f` (phiếu #3-C, chưa ở main). Đây là
lần chạy đủ bộ đầu tiên không phụ thuộc thứ tự chạy. Mọi số Agent Eval trước đây là **số theo chuỗi**
(`../README.md`), kể cả năm lần chạy theo chuỗi trong thư mục này (nền 9/15, +1 10/15, nền 50/62 theo chuỗi). Không so
chúng với số ở đây.

## Giới hạn

- 6 bài mới, mỗi bài một câu hỏi; ba nhánh đều 4/6, nên lần đo không phân biệt được ba nhánh trên bài mới.
- Phiếu #3-C so với phiếu cũ trên main vẫn chưa đo dưới cô lập.
- Bước 1 chỉ bắt hai kiểu chữ; dưới cô lập, model hiếm khi viết đúng hai kiểu đó (1/15 bài).
- Bộ chia đoạn bỏ dòng tiêu đề đánh số ở doc-39, 40, 41, 43 (đè đều ba nhánh).
