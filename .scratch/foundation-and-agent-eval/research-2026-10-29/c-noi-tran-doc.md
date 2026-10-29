# Hướng C — nới trần lượt công cụ khi có đoạn dán (nghiên cứu, 29/10/2026)

Chưa gọi model, chưa sửa repo. Số đo lấy từ lần chạy cô lập `kept/agent-eval-v0.7-paste-nudge-search/` (8 lần chạy,
commit đo 94e321f) và từ bộ chia đoạn thật chạy trên `tasks.jsonl`. Script + kết quả thô:
`C:\Users\dungbt06\AppData\Local\Temp\claude\C--Users-dungbt06-local-ai-core\5e9b23d6-dd28-46a2-b314-bd7791bd6b8f\scratchpad\research\c-rounds\`
(`analyze_c.py`, `results.json`, `results_extra.json`).

## Bản chất

Trợ lý đọc văn bản dài theo từng nắm, mỗi lượt được giở một số trang nhất định rồi buộc phải trả lời. Hai bài trượt vì
câu trả lời nằm ở trang mà trợ lý chưa kịp giở tới, chứ không phải vì đọc sai. Cho giở thêm vài lần thì tới được hai bài
đó, tốn thêm chút thời gian, vẫn trong giới hạn. Nhưng trí nhớ ngắn hạn của trợ lý có sức chứa cố định: mọi trang đã giở
đều nằm lại trong đó, nên dù cho giở bao nhiêu lần, trợ lý cũng chỉ giữ được một phần nhỏ của văn bản dài nhất mà
người dùng được phép dán. Hướng này vá được trần hiện tại cho văn bản vừa vừa, không giải quyết văn bản rất dài.

## 1. Chỗ đổi trong code (đã đọc code `coord-main` = main ca099fa, và diff tới 94e321f)

**Chỗ đổi nhỏ nhất:** `agent_service.py:347` `rounds, retried = self.max_steps, False` →
`rounds = self.max_steps + (PASTE_EXTRA_ROUNDS if pastes else 0)`. `pastes` đã có sẵn ở :322 (`take_pastes`).

| Chỗ | Ảnh hưởng | Kiểm bằng |
|---|---|---|
| `rounds` chỉ dùng ở điều kiện vòng lặp :351 và hai chỗ `+1` (:383 thử lại lệnh hỏng #27, :405 thử lại kiểm số #2) | không chữ nào trong prompt nhắc số lượt → bài không chạm trần (`stop_reason ≠ max_steps`) giữ nguyên từng byte | đọc code; grep `max_steps` trong `agent_service.py`, `pastes.py` |
| `take_pastes` quét **mọi** tin trong lịch sử | lượt sau trong cùng hội thoại, không dán gì mới, vẫn được thêm lượt. Muốn chặt thì xét tin user cuối | đọc `pastes.py:63` |
| Discord | không bị ảnh hưởng: tin Discord tối đa 10 000 ký tự = ngưỡng đoạn dán | `settings.py:197`, `discord/schema.py:40`, manifest `input_max_chars.discord` |
| `READ_DOCUMENT_SCHEMA` (:95) nhúng `READ_MAX_CHUNKS` vào mô tả | chỉ biến thể đổi `n` mới đụng; đổi → `tools_sha256` đổi | đọc code |
| Phiếu #3-C (94e321f) ghi cứng `most = 3`, test `test_agent_pastes.py:125,136` giữ bằng `READ_MAX_CHUNKS` | biến thể đổi `n` phải sửa phiếu → cả 15 bài dán đổi prompt | `git show 94e321f:…` |
| Nhánh ép khi hết lượt (:449) | không đổi; vẫn chạy khi hết N lượt | đọc code |
| `manifest.json` đã ghi `max_steps` | khoá mới phải ghi vào manifest, không thì không phân biệt được lần chạy | manifest base-full |
| Nền đo | main còn phiếu #3; nền đo #3-D là phiếu #3-C (94e321f, chưa ở main) | `git diff 94e321f HEAD` |

## 2. Token và độ trễ — đo từ dữ liệu thật

Điều kiện: GPU riêng, qwen3.5:9b, num_ctx 16 384, nhiệt độ 0, gỡ model trước mỗi bài; 117 vòng đầu bài dán, 118 cặp vòng
có đúng một lần đọc ở giữa.

| Đại lượng | Giá trị |
|---|---|
| Vòng đầu bài dán (prompt + công cụ + phiếu) | trung vị 1 842 token (1 803–1 939) |
| Mỗi lần đọc 3 đoạn thêm vào | trung vị 1 673 token (1 196–1 832); ≈ 3,55 ký tự JSON/token + ~155 token lệnh gọi |
| Schema công cụ (vòng ép không gửi công cụ) | ≈ 856 token |
| Độ trễ vòng có công cụ | 211 ms + 0,13 ms/token vào + 14,4 ms/token ra (R² 0,989, n = 256) |
| Độ trễ câu trả lời cuối bài dán | trung vị 8,5 s, lớn nhất 11,2 s; dài nhất 623 token |
| Vòng lớn nhất từng thấy | 6 479 token — **mọi số dưới đây trên mức này là ngoại suy** |

Kiểm mô hình dự báo với số thật ở N = 3: doc-50 vòng ép dự báo 5 737 / thật 5 721; doc-49 dự báo 5 964 / thật 6 470 (thấp
8%). Bảng dưới đã cộng biên 10% vào cột "đỉnh".

| Bài | N lần đọc | Đọc tới đoạn | Đỉnh token vòng cuối (+10%) + câu trả lời dài nhất | Độ trễ ước (trung vị / trả lời dài nhất) |
|---|---|---|---|---|
| doc-49 (15 đoạn) | 3 | 8 | 8 100 | 16,0 / 18,9 s |
| | 5 | 14 (hết bài) | 11 300 | 22,8 / 25,7 s |
| doc-50 (25 đoạn) | 3 | 8 | 7 850 | 15,8 / 18,7 s |
| | 5 | 14 | 11 400 | 22,7 / 25,6 s |
| | 7 | 20 | 14 600 | 30,4 / 33,3 s |
| | 8 | 23 | **16 600 > 16 384** | 34,6 / 37,5 s |

Chồng thêm cả thử lại kiểm số #2 và thử lại lệnh hỏng #27 (N = 5 thành 7 vòng): doc-50 ≈ 12 300 token, ≈ 38 s. Vẫn dưới
16 384 và dưới mốc 70 s (90 − 20 dự trữ) mà vòng lặp ngừng mở lượt mới.

**Trần cửa sổ, bất kể N:** sau phần đầu và chỗ cho câu trả lời còn ~13 900 token, chứa được ~7 lần đọc có biên (8 nếu
không biên) = đoạn 0–20/23. Đoạn chồng lấp nhau, nên mỗi đoạn chỉ mang ~1 270 ký tự mới: 7 lần đọc ≈ 26 000–27 000 ký tự.
Đoạn dán tối đa 100 000 ký tự ≈ 79 đoạn ≈ 27 lần đọc. **C phủ được tối đa khoảng 27–30% đoạn dán dài nhất cho phép.**

## 3. Tầm với: đọc tuần tự từ đoạn 0, mỗi lần 3 đoạn

Mô phỏng bằng `read_paste` + `_fit_chunks` thật (giới hạn 6 000 ký tự): mọi lần đọc đều lấy đủ 3 đoạn. Vị trí đáp án khớp
mẫu `must_mention` của từng bài ở cả 15 bài.

| Bài | 39 | 40 | 41 | 42 | 43 | 44 | 45 | 46 | 47 | 48 | 49 | 50 | 51 | 52 | 53 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Tới đáp án ở lần đọc | 1 | 2 | 3 | 0 | 2 | 2 | 0 | 3 | 2 | 2 | **4** | **5** | 3 | 0 | 3 |

| N lần đọc | Bài tới được (/15) | Biến thể n ≤ 5 (giới hạn 10 000 ký tự): N lần đọc → tới được |
|---|---|---|
| 3 (hiện tại) | 13 | 2 → 13 |
| 4 | 14 | 3 → 15 |
| 5 | 15 | 4 → 15 |
| 6 | 15 | |

**Tới được ≠ đạt.** Ở N = 3 tới được 13 nhưng nền đạt 10: doc-40, 44, 47 trượt vì lý do C không chạm (gọi công cụ cấm;
bị kiểm số bác rồi không đọc; đọc một lần rồi dừng). Trần lợi của C trên 15 bài cũ là +2, và cả hai bài đó đã bị xem.

## 4. Các biến thể

| Biến thể | Đổi gì | `tools_sha256` / prompt | Ưu | Nhược |
|---|---|---|---|---|
| **C1** thêm cố định khi có đoạn dán (vd. 3 → 5 hoặc 7) | 1 dòng :347 + hằng số + manifest | không đổi băm, không đổi chữ nào | thay đổi nhỏ nhất; chỉ bài chạm trần 3 mới có thể đổi; đo 15 bài dán là đủ, 62 bài chỉ để kiểm | N cố định; vẫn chạm trần cửa sổ ~đoạn 20 |
| **C2** N theo số đoạn: `min(ceil(đoạn/3), 7)` | như C1, thêm tính số đoạn (đã có `_chunks`, có cache) | không đổi | không thêm lượt thừa cho văn bản ngắn | trần 7 vẫn do cửa sổ quyết; thêm một chỗ tính dễ sai |
| **C3** cho đọc nhiều đoạn hơn mỗi lần khi là đoạn dán (n ≤ 5, giới hạn ~10 000) | `_read_document` kẹp n theo loại tài liệu; phiếu #3-C phải sửa câu "n từ 1 đến 3" | băm giữ được nếu không đụng schema, nhưng phiếu đổi → **cả 15 bài dán đổi prompt**; nếu sửa schema → băm đổi → đo đủ 62 bài làm kết quả chính (ticket 10) | 3 lượt hiện có tới đoạn 14; ít vòng hơn, nhanh hơn C1 (~17 s cho doc-50) | schema nói 1–3 mà đoạn dán nhận 5 = mâu thuẫn mới (đúng loại đã làm doc-40 trượt); kết quả 10 000 ký tự/lượt; cùng trần cửa sổ |
| **C4** C1 + C3 | cả hai | như C3 | | cộng nhược của cả hai, không thêm tầm với vì trần là cửa sổ |

Ý kiến của tôi (không phải quyết định): nghiêng C1, vì đó là cách duy nhất không đổi chữ nào model đọc, nên tập bài có
thể đổi được biết trước và nhỏ. C2 hợp lý nếu chủ dự án muốn tránh lượt thừa. C3 nhanh hơn nhưng tạo lại đúng kiểu lệch
giữa mô tả công cụ và phiếu từng gây trượt. Chọn N nên theo nguyên tắc nêu trước, không theo vị trí đáp án doc-50
(N = 5 vừa khít đoạn 14, dễ bị coi là chỉnh theo bài đã thấy): ví dụ "nhiều nhất số lần đọc vừa cửa sổ có biên 10% và chỗ
cho hai lần thử lại" → N = 7.

## 5. Rủi ro

| Rủi ro | Bằng chứng / mức chắc |
|---|---|
| Bài đang đạt đổi: doc-41, 46, 51, 53 đạt nhờ **câu trả lời ép** ở vòng 4 (`stop_reason = max_steps` ở base-full). Với C chúng được hai lượt tự quyết: đọc tiếp hoặc tự trả lời ở vòng có công cụ, prompt khác → chữ khác | đã kiểm từ events. doc-53 có đoạn mồi ở đoạn 8 (đã đọc ở lần 3 hiện nay); doc-41 còn 6 đoạn, doc-46 còn 3 đoạn sau đáp án → đọc thêm có thể gặp số nhiễu. Đổi ý thật hay không: chưa biết |
| 47 bài không dán | chắc theo code: `pastes` rỗng khi không tin nào > 10 000 ký tự → `rounds` như cũ, prompt như cũ. doc-36 (không dán) có chạm trần 3 nhưng không được thêm. Nên vẫn chạy một lần đủ 62 để xác nhận |
| Model có giở tiếp ở vòng 4–5 không | ở doc-49/50 model vẫn đang gọi đọc ở vòng 3 khi bị cắt — dấu hiệu tốt; MemGPT ghi model nhỏ "ngừng giở trước khi hết". **Suy luận, chưa đo** |
| Lượt thêm = thêm cơ hội gọi công cụ cấm; bộ chấm trượt bất kể câu trả lời (doc-40 nền, doc-50 ở +1+3' đã trượt kiểu này) | chắc về cơ chế chấm; xảy ra bao nhiêu thì chưa biết |
| Chất lượng ở 10–15k token | chưa có dữ liệu trên 6 479 token. Lần đọc mới nhất nằm cuối, sát câu hỏi (tốt theo Lost in the Middle), nhưng chưa thấy 9B ở mức này |
| Câu trả lời ép vẫn đoán "thông lệ chung" khi hết N lượt mà chưa thấy (doc-49/50 hiện nay) | C không chữa; văn bản dài hơn tầm với N vẫn gặp đúng lỗi này |
| Văn bản thật tới 100 000 ký tự | **C không đủ**: trần cửa sổ ~27–30%. Muốn hơn phải bỏ bớt kết quả đọc cũ khỏi ngữ cảnh (khi đó bài hai mảnh xa nhau như doc-43, 47, 51 dễ mất mảnh đầu) hoặc nhảy thẳng tới đoạn cần (hướng tìm 3'/2/4) |

## 6. Thiết kế đo đề xuất

- Nền: cắt từ 94e321f (phiếu #3-C) như #3-D, hoặc từ main (phiếu #3) — chủ dự án chọn; hai nền cho số không so được với
  nhau. Gỡ model trước mỗi bài (đã chứng minh r1 = r2 15/15).
- Bài mới mù (NV3, không thấy code): ≥ 1 bài đáp án ở đoạn 9–11, ≥ 1 ở 12–14, ≥ 1 **quá tầm với của N đã chọn**, ≥ 1 sau
  ~đoạn 23 (lộ trần cửa sổ), ≥ 1 có đoạn mồi **sau** đáp án (đo "đọc thêm rồi đổi ý"), ≥ 1 hai mảnh cách xa. doc-49/50 đã
  bị xem: chỉ báo cáo, không tính vào luật.
- Luật đăng ký trước (phác): (1) không bài nào đạt → trượt trong 15 bài cũ + bài mới; (2) trong bài mới có đáp án nằm
  giữa đoạn 9 và tầm với N, ≥ 2/3 từ trượt → đạt; (3) 47 bài không dán giống hệt nền (câu trả lời + chuỗi công cụ); (4)
  không vòng nào vượt 15 000 token, không bài nào quá 60 s; (5) bài quá tầm với: ghi riêng câu trả lời ép có đoán hay nói
  rõ chưa đọc tới.
- Dòng tách riêng: số lần đọc thật / N, bài tự dừng trước N, đỉnh token mỗi bài, doc-41/46/51/53 đổi chữ hay không, số lần gọi công cụ cấm ở vòng 4 trở đi.

| Lần chạy | Bài | GPU ước |
|---|---|---|
| Nền trên bài mới, r1 + r2 (15 bài cũ dùng lại số cô lập có sẵn nếu cùng nền) | ~6 | ~3 phút |
| C, r1 + r2 | 15 + ~6 | ~10–11 phút (mỗi bài dán ~14 s gồm nạp lại; bài chạm trần thêm ~7 s) |
| C, đủ 62 + bài mới | ~68 | ~10 phút (base-full: 372 s trả lời + 194 s nạp lại) |
| **Tổng** | | **~23–25 phút** (bỏ lần đủ bộ nếu chấp nhận chứng minh bằng code: ~14 phút) |

Code: ~5 dòng + 3–4 test (bài có dán được N, bài không dán giữ 3, hai lần thử lại vẫn cộng thêm, manifest ghi khoá mới).

## Điều tôi chưa kiểm

- Model có thật sự đọc tiếp ở vòng 4+ hay không, và có đổi câu trả lời ở doc-41/46/51/53 không — cần chạy model.
- Ollama làm gì khi prompt vượt num_ctx: client (`llm_clients/ollama_client.py`) không đặt tuỳ chọn cắt; theo tôi biết
  Ollama cắt bớt phần đầu im lặng, tức có thể mất chính phiếu và câu hỏi — chưa kiểm ở bản đang chạy.
- Độ trễ khi GPU dùng chung với dự án khác hoặc chạy CPU: hệ số trên chỉ cho GPU riêng.
- Số token trên 6 479 là ngoại suy tuyến tính; dự báo từng thấp 8% ở doc-49.
- `tokens_in` của Ollama là độ dài cả prompt (suy từ việc số tăng dồn qua các vòng và vòng ép thấp hơn đúng cỡ schema),
  không đọc tài liệu Ollama để xác nhận.

## Vòng 2 (sau khi đọc phan-bien.md, harness-tim-ho.md, tim-trong-doan-dan.md)
**Bản chất.** Đặt nguyên văn bản lên bàn hay cho giở thêm trang thì đều đụng cùng một cái bàn, và hai cách chạm mép bàn ở
gần cùng một độ dài. Cách đặt nguyên nhanh hơn và không cần trợ lý tự quyết giở trang. Cách giở trang giữ được hai thứ:
trang vừa giở luôn nằm sát câu hỏi, và bước kiểm số vẫn biết trợ lý đã thật sự thấy những gì. Văn bản dài hơn mép bàn thì
cả hai đều bó tay; khi đó chỉ còn cách nhảy thẳng tới đúng trang.

**1. N1 và P3, xét bằng số đã đo** (ký tự/token: 3,3 cho chữ thường, đo từ 186 câu trả lời; 3,55 cho kết quả đọc dạng JSON;
phản biện dùng 2,9, bi quan hơn. Phần prompt không có phiếu ≈ 1,3k token.)

| | C, N=5 (doc-50) | N1 doc-49 | N1 doc-50 | N1, văn bản 30k ký tự |
|---|---|---|---|---|
| Prompt lớn nhất | 9,8k | 7,0k | 10,9k | 10,4k (11,6k nếu tính 2,9 ký tự/token) |
| + câu trả lời + một lần thử lại #2 | ~11,2k | ~8,4k | ~12,3k | ~11,8k (13,0k) |
| Có biên 10% | 12,3k | 9,2k | 13,5k | 13,0k (14,3k), vẫn vừa 16 384 |
| Độ trễ ước | ~23 s | ~9–11 s | ~10–13 s | ~10–13 s |

- "36k so với 11k" của phản biện là tổng `tokens_in` cộng qua các vòng. Bản dự báo của tôi còn ra 43k. Nhưng Ollama dùng lại
  phần đầu prompt trong cùng một lượt: hệ số độ trễ cho mỗi token vào ở vòng có bộ đệm là 0,13 ms, ở vòng đầu không có bộ
  đệm là 0,30 ms. Vì vậy thước đo đúng là độ trễ. Theo thước đo đó N1 nhanh gấp khoảng 2 lần, không phải 3 lần. Số prefill
  ở 11k token là ngoại suy, vì vòng đầu lớn nhất từng đo chỉ 1 939 token.
- **Cái giá của N1 mà phản biện chưa tính:** `turn_texts` (`answer_figures.py:50`) coi mọi tin nhắn là "đã thấy". Nạp
  nguyên văn bản thì mọi con số trong đó đều qua được bước kiểm #2, kể cả số mồi như 300.000 ở doc-53. Với phiếu, số ở phần
  chưa đọc vẫn bị bắt. Vậy #2 gần như tắt với đoạn dán.
- Thêm: đáp án doc-50 (đoạn 14/25) nằm giữa tin 11k token — chỗ yếu "lost in the middle" (C đặt đoạn vừa đọc cuối, sát câu hỏi); N1 đổi prompt cả 15 bài dán, C chỉ 6.
- **Ngưỡng N1 phải nhường:** nên quyết bằng ước token của cả prompt, tính cả lịch sử (giới hạn 40 tin, `settings.py:202`),
  không theo số ký tự cố định. Đề xuất: N1 khi ước ≤ ~11k token, để dành ~5k cho câu trả lời, một lần thử #2, một vòng công
  cụ và biên. Không có lịch sử thì ngưỡng ≈ 28–32k ký tự. **Trần của C ≈ 27k ký tự, nên không có khoảng độ dài nào mà C tới
  được còn N1 thì không.** Trên ngưỡng chỉ còn cách nhảy thẳng (P3 / tìm).
- P3 tốn thêm ~1,5–2k token mỗi lần dán, nhẹ hơn N1 ở văn bản dài, nhưng tìm trúng chỉ 8–9/12 bài, và là số trong mẫu. Dưới
  ngưỡng N1, P3 không có lý do để hơn N1 vì N1 thấy đủ 100%. P3 chỉ có chỗ đứng trên ngưỡng.
- 47 bài không dán: N1 và C như nhau (chỉ chạm tin > 10 000 ký tự); N1 cần hằng số riêng vì `PASTE_THRESHOLD` còn chặn chat thường (`routers/chat.py:88`).

**2. Trả lời câu hỏi của phản biện cho C.**

- **Q1.** Chưa đo: ước 9,8k (biên 10,8k), lớn nhất từng đo 6,5k. Vượt 16 384 khi lịch sử > ~4,9k token (N=5) / ~8,9k (N=3); eval không có lịch sử nên chưa lộ.
- **Q2.** Theo token và độ trễ, C không hơn; chỉ hơn ở đáp án cạnh câu hỏi, #2 giữ nghĩa, ít bài đổi prompt — chưa đo cái nào có ích với 9B.
- **Q3.** doc-41, 46, 51, 53 (đạt nhờ câu trả lời ép ở vòng 4). **Q10.** Không có bài > 35k; C không tới mức đó, nên phần C đo được N1 đều phủ.
- **Q11.** Với cổng "thắng − thua ≥ 3", tôi đoán C trượt hoặc vừa sát ngưỡng: thắng chắc chỉ 49 và 50 (cả hai đã bị xem), còn
  41/46/51/53 là chỗ có thể thua.

**3. Điều làm tôi đổi ý:** trần N1 ≥ trần C mà không cần model tự quyết đọc; "gọi tìm 3/12" và "doc-53 thua mọi cách đếm chữ" cho thấy dựa vào model tự tìm đều yếu. Xếp lại:

| Hạng | Hướng | Lý do |
|---|---|---|
| 1 | Kết hợp: N1 khi vừa ngưỡng token; trên ngưỡng thì P3 + S1/S2 | mỗi cơ chế dùng đúng khoảng nó mạnh |
| 2 | N1 một mình | phủ đủ dưới ngưỡng, một vòng, nhanh nhất; rủi ro "lost in the middle" và #2 tắt, phải đo |
| 3 | Sửa BM25 (S1+S2) | rẻ, không đổi băm, là nền của P3; một mình thì vướng việc model ít gọi tìm |
| 4 | P3 | cách duy nhất cho văn bản > ngưỡng N1; số trong mẫu, thua kiểu khác chữ |
| 5 | C | bị N1 lấn ở mọi độ dài N1 phủ; chỉ còn vai phụ "+2 lượt khi > ngưỡng N1" để đọc quanh đoạn P3 chỉ tới |

**4. Một thí nghiệm có model, khoảng 10–12 phút GPU, cô lập** (gỡ model trước mỗi bài; r1 = r2 đã chứng minh nên chạy r1).

- **Nhánh:** nền = 94e321f (dùng lại `v0.7-3d-iso-base-r1`, không tốn GPU); C7 = `max_steps` 3 → 7 khi có đoạn dán; N1 = nạp nguyên khi ước ≤ 11k token (cả 15 bài vừa; doc-50 ≈ 10,9k).
- **Bài:** 15 bài dán cũ. Thêm ≥ 3 bài mù của NV3, văn bản 25–30k ký tự, đáp án ở 40–60% chiều dài: đây là chỗ "lost in the
  middle" cắn N1 mạnh nhất và chỗ C phải đọc ≥ 4 lần.
- **Luật, đăng ký trước:**
  1. N1 thua C7 ở ≥ 2 bài có đáp án ở 40–60% → kết luận "lost in the middle" có thật với 9B: giữ C cho khúc giữa, hạ ngưỡng N1.
  2. Ngược lại, N1 ≥ C7 ở mọi bài và không làm bài nào trong 10 bài đạt của nền trượt → bỏ C.
  3. `tokens_in` vòng đầu của N1 ở doc-50 lệch > 15% so với 10,9k → tính lại mọi ngưỡng trước khi bàn tiếp.
  4. Ghi riêng: số lần #2 bắn ở N1 (dự đoán ≈ 0), câu trả lời có số mồi. ~18 bài chỉ bắt chênh lớn: phép thử cơ chế, không phải cổng gộp.
