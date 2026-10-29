# Phản biện độc lập: đoạn dán dài sau #3-D — red team, 29/10/2026

Không commit, không chạy model. Ký hiệu: **[tệp]** = đã kiểm trong tệp/số đo (kèm chỗ); **[ý kiến]** = suy luận của tôi;
**[nguồn ngoài]** = có URL ở mục Nguồn. Số đã trích để ở
`C:\Users\dungbt06\AppData\Local\Temp\claude\C--Users-dungbt06-local-ai-core\5e9b23d6-dd28-46a2-b314-bd7791bd6b8f\scratchpad\research\redteam\numbers.md`.

## Bản chất

Ún đang đọc văn bản dài như người chỉ được giở ba lần, mỗi lần ba trang. Bốn vòng sửa đều chỉnh lời dặn cho người đọc ấy
giở khéo hơn, nhưng hai bài trượt chung nằm ở trang mà ba lần giở không bao giờ tới. Trong khi đó, phần lớn văn bản trong bộ
bài thật ra vừa đủ đặt nguyên lên bàn một lần. Ngưỡng "quá dài" hiện nay do giới hạn cũ của API đặt ra, không phải do bàn
hết chỗ. Câu hỏi lớn hơn chưa ai trả lời: có ai thật sự dán văn bản dài vào Ún không. Còn cách đo thì mỗi vòng chỉ có sáu bài
mới, nên một thay đổi tốt hay xấu một hai bài trông giống hệt không đổi gì.

## 1. Tiền đề: bài toán này có đáng không?

| Điều | Bằng chứng |
|---|---|
| Đoạn dán chỉ tới được agent từ web, chế độ công cụ | **[tệp]** `routers/chat.py:88` chặn > 10 000 khi không dùng công cụ; `discord_bot/api_client.py:137` từ chối > 10 000 |
| Trên Discord, văn bản dài đến dưới dạng tệp, bot bỏ qua | **[nguồn ngoài]** Discord tự đổi tin > 2 000 ký tự thành `message.txt`; **[tệp]** grep `attachment` trong `discord_bot/` không ra gì |
| Server thật gần như không có lượt | **[tệp, memory]** dump 15/09: 59 lượt 25–28/08, 0 lượt 29/08→15/09; sau 15/09 chưa ai đếm |
| Lượng dùng web chưa ai đếm | **[tệp]** bảng `messages` (`postgres/models.py:1013`), `agent_traces` (:1074), `request_logs` (:1129) có sẵn |

Hai nghĩa của "đáng", nên tách:

- **Đáng vì người dùng:** chưa có bằng chứng nào. Cách đo rẻ nhất (chưa chạy; cột `role`, `content`, `created_at` đã kiểm ở
  `models.py:1013–1021`): `SELECT date_trunc('month', created_at), count(*) FILTER (WHERE length(content) > 2000),
  count(*) FILTER (WHERE length(content) > 10000), max(length(content)) FROM messages WHERE role='user' GROUP BY 1` (chỉ đọc). Docker tắt thì dùng cách đọc dump
  không cần Docker (memory `read-pg-dump-without-docker`). Năm phút. Ra 0 thì mọi việc dưới đây là việc cho CV, không cho người dùng.
- **Đáng vì CV (harness là mũi nhọn):** chủ dự án đã nói Agent Eval tự viết chỉ là test hồi quy (memory
  `benchmarks-must-be-reputable`). Cải tiến chỉ đo được trên 15 bài tự viết thì không khẳng định ra ngoài được. Nếu mục tiêu là CV,
  cần tra một bộ hỏi đáp tài liệu dài công khai có điểm công bố (từ khoá: "long document QA benchmark Vietnamese", LongBench,
  RULER) — **chưa tra, không khẳng định có bộ tiếng Việt phù hợp**.
- **[ý kiến]** Nếu có nhu cầu thật về văn bản dài, đường hay gặp hơn có lẽ là tệp `message.txt` trên Discord, không phải dán trên
  web. Máy đoạn dán hiện có dùng lại được cho tệp đính kèm.

## 2. Từng hướng: điều gì làm nó thất bại

Hai mục trong danh sách A–F đã cũ:

- **B đã xong:** ticket 27 gộp ở `5f60277`, đóng ở `ca099fa` (**[tệp]** git log coord-main).
- **E coi như đã đo, chỉ thiếu đăng ký trước:** báo cáo ticket 27 có bảng ngoài luật dưới cô lập. Phiếu #3 đạt 45/62, #3-C đạt 50/62;
  0 bài đạt → trượt; 47 bài không dán trùng nguyên (**[tệp]** `kept/agent-eval-v0.7-tool-call-parse/REPORT.md`). Vậy #3-C bị giữ ngoài
  main bởi một luật kiểm cơ chế ("2/3 bài giữa mới phải trượt → đạt"), không phải vì nó gây hại. Xem đề xuất luật hai tầng ở §3.

### Số học cửa sổ — nền cho hướng C và mọi hướng "đọc nhiều hơn"

Số đo **[tệp]** ở nền cô lập 62 bài: vòng đầu không công cụ ≈ 1,84k token (doc-42); doc-49 cộng 4 vòng = 17 550 token, nên mỗi lần đọc
thêm ≈ 1,7k token vào mọi vòng sau (giải 4 × 1,84k + 6r = 17,55k). Ước lượng, chưa đo:

| Cách | Prompt vòng cuối | Tổng token xử lý trong lượt | Tới được đoạn |
|---|---|---|---|
| Hiện tại, 3 lần đọc | ≈ 6,9k | 17,6k (đo) | 8 |
| C: 5 lần đọc | ≈ 10,3k | ≈ 36k | 14 (doc-50 cần đúng 14) |
| Nạp nguyên doc-49 (15 đoạn) một lần | ≈ 8k | ≈ 8k | hết |
| Nạp nguyên doc-50 (25 đoạn) một lần | ≈ 11,5k | ≈ 11,5k | hết |
| Đoạn dán tối đa 100 000 ký tự (≈ 70 đoạn) | — | — | không cách tuần tự nào tới |

Giới hạn của bảng: tỉ lệ ~2,9 ký tự/token lấy từ chú thích `agent_service.py:64` (đo trên corpus lab), chưa đo bằng tokenizer trên
văn bản dán tiếng Việt; Ollama dùng lại phần đầu prompt trong một lượt, nên "tổng token" phóng đại tính toán thật. Khi prompt vượt
`num_ctx`, Ollama được mô tả là **lặng lẽ bỏ tin cũ từ đầu**, giữ system và tin cuối (**[nguồn ngoài, thứ cấp, chưa kiểm mã]**):
tin đầu sau system chính là câu hỏi kèm phiếu.

### Bảng hướng

| Hướng | Điều làm nó thất bại | Bằng chứng ủng hộ / phản đối | Chi phí ẩn |
|---|---|---|---|
| **A** dừng, main giữ #3 | Mục tiêu "harness nổi bật" không đạt; main giữ phiếu kém hơn 5 bài | phản đối: #3-C +5/0 dưới cô lập (ngoài luật) | không |
| **C** nới trần 3 → 5 vòng khi có đoạn dán (agent C) | Chỉ cứu bài đáp án ở đoạn 9–14; trên 14 vẫn trượt. Prompt vòng cuối ≈ 10k, sát cửa sổ khi lịch sử dài. Model vẫn có thể ngừng sớm (MemGPT) | ủng hộ: doc-49, 50 trượt *chỉ* vì hết lượt, đều đọc (0)(3)(6) (**[tệp]** REPORT #3-D). `max_steps` không có trong lời model thấy (**[tệp]** grep "lượt/ba lần/3 lần": `slip()` ở main và ở `94e321f` (#3-C) không nhắc số lượt; `agent_service.py` chỉ nhắc ở lời ép trả lời :452, không nêu con số) → băm prompt giữ nguyên. Phản đối: SWE-agent thấy "thành công nhanh, thất bại chậm" (lượt trượt 21 bước, lượt đạt 12) — áp cho rủi ro lan man ở vòng 4–5, không giải thích doc-49/50 vốn trượt vì trần cứng | Độ trễ doc-49 18 s → ước ~30 s (dưới 90 s); token ~gấp đôi; bài đang đạt nhờ "hết lượt rồi trả lời" có thể đổi |
| **D** phiếu lái sang tìm (bản (b) đã bỏ) | Model 9B ít khi chọn tìm; tìm xong đọc một cửa sổ, bỏ sót mảnh hai | phản đối: gọi tìm 3/12; doc-43 tụt vì đọc một cửa sổ; doc-50 nói ngược phiếu (**[tệp]**). Ủng hộ: khi gọi thì 2/3 ra đúng đoạn; SWE-agent: bỏ tìm −2,3 điểm | Mỗi lần đổi lời phiếu xáo câu trả lời bài dán (ticket 10: đổi lời xáo 37–39/40) |
| **Tìm trong đoạn dán: sửa BM25 + phiếu** (agent thứ hai) | Chỗ hỏng chính là *model không gọi* (9/12), không phải tìm kém (2/3 trúng). BM25 trên âm tiết tiếng Việt yếu đúng ở kiểu (n) "ít từ chung" | phản đối: số trên. Ủng hộ: Anthropic khuyên công cụ tìm thay vì liệt kê; SWE-agent: kết quả tìm gọn tốt hơn từng cái (−6,0 khi lặp) | Chỉ khi đổi mô tả công cụ: đổi `tools_sha256` → chạy đủ 62 bài (3' cố ý giữ băm); chỉ đổi phiếu thì xáo câu trả lời bài dán |
| **Harness tìm hộ / mục lục** (agent thứ ba) | Tách câu hỏi khỏi văn bản dán sai; bài hai mảnh cần trúng cả hai; mục lục bằng 9B với 70 đoạn ăn hết 90 s (ước của opus) | ủng hộ: bỏ hẳn bước model phải *quyết định* đọc/tìm — đúng chỗ hỏng đo được; Claude Projects tự chuyển sang tìm khi tài liệu vượt cửa sổ; Anthropic: "lấy một phần trước cho nhanh" (hybrid). Phản đối: kiểu (n) cần nhúng, không đủ BM25 | Phiếu dài thêm cả ở bài trả lời được ngay; độ trễ nhúng mỗi lần dán; code lớn nhất |
| **F** sửa bộ chia đoạn bỏ tiêu đề | Bộ chia đoạn dùng chung với nạp tài liệu → đổi kết quả RAG 82 câu, phải nạp lại chỉ mục | ủng hộ: đè doc-39, 40, 41, 43 (**[tệp]**); liên quan lỗi "chunker từ chối văn bản luật" (memory) | Đo lại RAG + nạp lại; nên tách khỏi việc đoạn dán |

Tiền lệ nguồn chính thống về "nới lượt / cho công cụ tìm / harness tìm hộ":

- **Nới lượt:** không nguồn nào đặt trần nhỏ cố định. SWE-agent dùng trần chi phí $4/bài. Anthropic nói bài khó "có thể cần hàng chục" lượt
  gọi công cụ. Nhưng các harness ấy có cửa sổ 100k–200k; ở 16k, thêm lượt nghĩa là đầy cửa sổ nhanh. **[ý kiến]**
- **Cho công cụ tìm:** SWE-agent (bỏ tìm −2,3), Anthropic viết công cụ (tìm thay vì liệt kê), Claude Code và Deep Agents (grep + đọc theo
  offset). Cả ba dựa vào model mạnh *tự quyết* gọi tìm — đúng thứ model 9B ở đây làm 3/12.
- **Harness lo trước:** Anthropic contextual retrieval: dưới 200k token thì nạp nguyên, không cần tìm. Claude Code: thả CLAUDE.md vào từ đầu,
  phần còn lại tìm khi cần. Claude Projects: chỉ chuyển sang tìm khi vượt cửa sổ.
- **Ngưỡng đẩy ra ngoài:** Claude Code cắt kết quả công cụ ở 25k token (≈ 12% cửa sổ 200k). Deep Agents đẩy ra tệp ở 20k. Ngưỡng 10 000 ký tự
  của Ún ≈ 3,4k token ≈ 21% cửa sổ 16k — tức đã *rộng tay hơn* họ theo tỉ lệ. Đây là lý lẽ phản lại hướng "nạp nguyên" ở §4, phải cân.

## 3. Phản biện cách đo

**Sáu bài mới không đủ:**

- Ba nhánh đều 4/6, nên lần đo không phân biệt được ba nhánh (**[tệp]** REPORT #3-D, mục Giới hạn).
- Ở t = 0, "r1 = r2" chỉ chứng minh máy chạy lặp lại. Nó không chứng minh kết quả bền: doc-48 trượt ở #3, đạt ở #3-C mà không có cơ chế đoạn
  dán nào nhắm riêng nó (**[tệp]**). Mỗi bài là một lần tung đồng xu theo lời phiếu.
- Phép thử dấu hai phía: 5 thắng 0 thua cho p = 0,0625; cần 6 thắng 0 thua mới p ≈ 0,031 (tính tay). Vậy với ≤ 20 bài, chỉ thay đổi ≥ 6 bài
  mới phân biệt được với nhiễu.

**Luật đăng ký trước bị vênh, ba kiểu:**

1. **Luật cơ chế dùng làm cổng gộp.** #3-C không gây hại, +5 bài, nhưng ra ngoài vì không đạt "2/3 bài giữa". Phép thử giả thuyết và cổng gộp
   bị trộn làm một.
2. **Chạy một vòng mà chính bản đăng ký đã đoán luật trượt.** Dự đoán "+1+3': doc-49, 50 vẫn trượt (C3 sai)" đúng (**[tệp]**). Vòng ấy về
   mặt luật là biết trước kết quả.
3. **Bộ chấm sai cả hai chiều.** doc-51 đạt nhờ mẫu `7\s*ngày` khớp câu đoán "3-7 ngày". doc-40 trượt `tools_forbidden` dù đọc tới đáp án,
   câu trả lời đủ ý (**[tệp]**).

**Chi phí mỗi vòng** (**[tệp]** manifest `started_at/finished_at`; tệp duyệt trong `reviews/`):

| Vòng | Nhánh làm việc | Tệp duyệt | Bài mù mới | Phút GPU | Kết quả |
|---|---|---|---|---|---|
| #3-B | 2 | 4 | 4 | 2,4 | trượt |
| #3-C | 2 | 4 | 4 | 4,5 | trượt |
| #3-D | 4 | 9 | 6 | 57,5 (theo chuỗi 16,9 + cô lập 39,7 + chẩn đoán 0,9) | trượt |

GPU rẻ: 15 bài cô lập ≈ 3,5 phút. Thứ đắt là người: tệp duyệt, nhánh, bài mù. **[ý kiến]** Vậy nên đổi GPU lấy độ chắc, đừng đổi người lấy độ chắc.

**Khung đo cố định đề xuất** (**[ý kiến]**, chủ dự án chọn):

- **Kho bài chia đôi:**
  - *Dev* = 15 bài đã lộ, sửa tự do không cần đăng ký.
  - *Test* = bài mù, viết một lần cho nhiều vòng, chỉ mở khi quyết gộp.
- **Test 21–24 bài, 7 tầng × 3:** mép (không cần đọc); giữa sớm (đoạn 1–5); xa trong trần (6–8); quá trần (≥ 9); hai mảnh; ít từ chung;
  rất dài (35 000–100 000 ký tự).
  - Thêm 2–3 bài **đáp án không có trong văn bản**, để bắt đoán kiểu doc-49/50/51.
  - **Điều kiện tiên quyết:** bộ hiện tại không có bài nào > 31 681 ký tự (14/15 ≤ 21 342; **[tệp]** `tasks.jsonl`). Hướng "nạp nguyên" sẽ phủ
    trọn bộ hiện tại, nên chưa có tầng rất dài thì không đo trung thực được.
- **Mỗi bài chạy 3 lần** ở nhiệt độ thật (0,4, ba seed); "đạt" = ≥ 2/3. Chi phí ≈ 3 × (thời gian một lần) ≈ 15 phút mỗi nhánh.
- **Luật mẫu hai tầng:**
  - *Cổng gộp:* 47 bài không dán trùng nguyên (hoặc thua 0); trên bài test, thắng − thua ≥ 3 và thua ≤ 1; bài "không có đáp án" không xấu đi.
  - *Giả thuyết cơ chế:* báo riêng, không chặn gộp.
- **Bỏ vòng** khi bản đăng ký tự đoán cổng trượt.
- **Dừng hướng** sau 2 vòng liên tiếp trượt cổng trên cùng một tầng: đổi cơ chế, không đổi lời.
- **Sổ chi phí mỗi vòng:** số nhánh, tệp duyệt, bài mù tiêu, phút GPU.

## 4. Hướng chưa ai đề xuất

| Hướng | Ưu | Nhược |
|---|---|---|
| **N1. Nạp nguyên văn khi vừa cửa sổ** (chế độ công cụ, đoạn dán ≤ ~30 000 ký tự ≈ ≤ 11k token; chỉ ở lượt dán, lượt sau trở lại phiếu) | Không cần model quyết đọc; một vòng; ít token hơn cách hiện tại (doc-49: ≈ 8k so với 17,6k đo). Ngưỡng 10 000 là "giới hạn /chat cũ" (**[tệp]** `pastes.py:24`), không phải do cửa sổ. Đúng lời Anthropic "vừa thì nạp nguyên" | Mất độ chính xác khi ngữ cảnh dài ("context rot", Chroma, có Qwen3; "lost in the middle") — chưa đo với 9B tiếng Việt. Theo tỉ lệ cửa sổ, rộng tay hơn Claude Code/Deep Agents. Trên ngưỡng vẫn cần hướng khác. Lịch sử 40 tin sẽ mang theo nếu quên đổi lại phiếu |
| **N2. Câu trả lời ép nói thật vị trí** (khi hết lượt mà còn đoạn chưa đọc, harness ghép một câu cố định "đã đọc tới đoạn X/Y") | Code thường, không đổi lời model thấy; chữa doc-49/50 đoán "thông lệ chung"; Anthropic: agent "tuyên bố xong quá sớm" cần bước kiểm, không chỉ lời dặn | Không làm bài đạt; bộ chấm hiện không thưởng sự trung thực |
| **N3. Tăng `READ_RESULT_MAX_CHARS` / số đoạn mỗi lần đọc** | Một hằng số; 3 lần × 6 đoạn tới đoạn 17 | `READ_MAX_CHUNKS` nằm trong schema (**[tệp]** `agent_service.py:95`) → đổi `tools_sha256`, chạy đủ 62, xáo câu đọc tài liệu thường; cửa sổ đầy như N1 nhưng qua quyết định của model |
| **N4. Đọc tệp `message.txt` trên Discord bằng máy đoạn dán sẵn có** | Có thể là đường văn bản dài thật sự của người dùng (§1) | Phụ thuộc tách mềm Discord (ticket 22); vẫn cần đo nhu cầu trước |

## 5. Xếp hạng tạm (không phải quyết định)

| # | Việc | Vì sao đứng đây |
|---|---|---|
| 0 | Đếm nhu cầu (SQL một dòng) | 5 phút; ra 0 thì đổi mục tiêu sang CV, kéo theo đổi thước đo |
| 1 | Luật hai tầng → xét lại gộp #3-C | Số đã có (+5/0, 47/47); không tốn GPU, chỉ tốn một quyết định về luật |
| 2 | N1 nạp nguyên khi vừa cửa sổ, đo trên khung §3 có tầng rất dài | Gỡ đúng chỗ hỏng "model không chịu đọc/tìm"; rẻ token; rủi ro chính đo được |
| 3 | Harness tìm hộ cho phần vượt ngưỡng N1 | Chỉ khi §1 cho thấy có văn bản > 30 000 ký tự |
| 4 | N2 câu trả lời ép nói thật | Rẻ, độc lập, tăng tin cậy |
| 5 | C nới trần | Thua N1 về token ở mọi độ dài N1 phủ; quá ngưỡng thì cũng không tới |
| 6 | D / sửa BM25 | Chỗ hỏng chính là tần suất gọi, không phải chất lượng tìm |
| — | F | Đúng nhưng là việc RAG, tách riêng |

## Câu hỏi cho ba agent kia khi tranh luận

**Agent C (nới trần):**
1. Với 5 vòng, prompt vòng cuối của doc-50 là bao nhiêu token đo thật, và có lần nào vượt 16 384 khi có lịch sử hội thoại không?
2. Vì sao nới lượt hơn nạp nguyên doc-49/50 một lần, khi nạp nguyên tốn ít token hơn và không cần model quyết đọc tiếp?
3. Bài nào đang đạt nhờ bị ép trả lời ở vòng 3, sẽ đổi khi có vòng 4–5?

**Agent tìm trong đoạn dán:**
4. Ở 9/12 bài model không gọi tìm, sửa BM25 thay đổi được gì?
5. Kiểu (n) "ít từ chung" thì BM25 tiếng Việt xử lý ra sao: tách từ, bỏ dấu, hay cần nhúng?
6. Đổi phiếu/mô tả có đổi `tools_sha256` không, và đã tính lần chạy đủ 62 bài chưa?

**Agent harness tìm hộ / mục lục:**
7. Tách câu hỏi khỏi văn bản dán sai bao nhiêu trên 15 bài? Bài câu hỏi ở giữa thì sao?
8. Top-k bao nhiêu thì doc-43/47/51 (hai mảnh) lấy đủ cả hai, và phiếu dài thêm bao nhiêu ở bài không cần đọc (doc-42, 45, 52)?
9. Dưới 30 000 ký tự, tìm hộ có hơn nạp nguyên không — có số nào ngoài ý kiến?

**Cả ba:**
10. Bộ test của bạn có bài > 35 000 ký tự không? Không có thì hướng của bạn đo được phần nào mà N1 không phủ?
11. Bạn dự đoán cổng gộp (thắng − thua ≥ 3) đạt hay trượt? Nếu tự đoán trượt thì vì sao vẫn chạy?

## Nguồn

- SWE-agent (Yang và cộng sự 2024), bản HTML: https://arxiv.org/html/2405.15793 — trần $4/bài; lượt đạt trung vị 12 bước, lượt trượt 21; "succeed quickly and fail slowly"; ablation cửa sổ và tìm.
- Anthropic, Effective context engineering for AI agents: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents — context rot, hybrid, Claude Code, "làm cách đơn giản nhất".
- Anthropic, Writing effective tools for agents: https://www.anthropic.com/engineering/writing-tools-for-agents — Claude Code cắt kết quả công cụ 25 000 token; tìm thay vì liệt kê; "có thể hàng chục" lượt gọi.
- Anthropic, Contextual Retrieval: https://www.anthropic.com/news/contextual-retrieval — dưới 200 000 token thì nạp nguyên.
- Anthropic, Effective harnesses for long-running agents: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents — tuyên bố xong quá sớm (trích lại từ `paste-directions-2026-10-28.md`, lần này không mở lại).
- MemGPT (Packer và cộng sự 2023): https://arxiv.org/abs/2310.08560 (trích lại từ `paste-directions`).
- Lost in the Middle (Liu và cộng sự 2023): https://arxiv.org/abs/2307.03172 (trích lại).
- Claude Projects tự chuyển sang tìm khi tài liệu vượt cửa sổ (help center): https://support.claude.com/en/articles/11473015-retrieval-augmented-generation-rag-for-projects — theo kết quả tìm kiếm: "khi được thì vẫn xử lý trong ngữ cảnh", tự chuyển sang tìm khi gần giới hạn, về lại khi nhỏ đi; không công bố ngưỡng.
- Chroma, Context Rot (2025): https://research.trychroma.com/context-rot — theo kết quả tìm kiếm, chưa mở trang gốc.
- LangChain Deep Agents, harness: https://docs.langchain.com/oss/python/deepagents/harness — đẩy kết quả > 20 000 token ra tệp; theo kết quả tìm kiếm, khớp bảng của fable.
- Discord Support, The Chat Bar: https://support.discord.com/hc/en-us/articles/360034632292 — tin > 2 000 ký tự thành tệp văn bản (theo kết quả tìm kiếm).
- Ollama cắt prompt khi vượt `num_ctx`: https://particula.tech/blog/ollama-num-ctx-silent-prompt-truncation — nguồn thứ cấp đọc mã `server/prompt.go`, chưa kiểm với bản Ollama đang dùng.

## Vòng 2 (29/10, sau khi đọc c-noi-tran-doc.md, tim-trong-doan-dan.md, harness-tim-ho.md)

**Bản chất.** Ba báo cáo đo kỹ phần "làm sao cho người đọc giở đúng trang". Nhưng số của chính họ cho thấy: trong khoảng độ dài
mà giở thêm còn với tới, đặt nguyên văn bản lên bàn một lần cũng vừa, và không cần ai quyết định giở. Phần thật sự cần
"tìm hộ" chỉ là văn bản quá dài để đặt lên bàn — và bộ bài hiện tại không có văn bản nào như thế.

### 1. Tin gì, nghi gì

| Báo cáo | Tin (đo bằng code/dữ liệu thật) | Nghi | Câu hỏi cho họ |
|---|---|---|---|
| C nới trần | vòng đầu 1 842, mỗi lần đọc +1 673 token (n = 118); hồi quy độ trễ (n = 256); bảng tầm với chạy bằng `_fit_chunks` thật; trần lợi +2 trên 15 bài cũ | mọi số trên 6 479 token là ngoại suy (đã lệch 8% ở doc-49); chất lượng ở 10–15k chưa có; doc-41/46/51/53 đang đạt nhờ câu ép, đổi hay không chưa biết | 7 lần đọc với tới ~26–27k ký tự — đúng khoảng nạp nguyên một lần cũng vừa. Lý do gì để chọn 7 vòng model tự quyết thay vì một vòng không cần quyết? |
| Tìm trong đoạn dán | lỗi cơ chế: IDF chặn 0 → doc-47 rỗng; mép không cắt vì bộ chia đoạn xoá tiêu đề → doc-43 mất đoạn 5; chép trùng production 70/70; giá chen thư viện 661–700/705 | 58 truy vấn chỉ 10 là thật, 3/10 viết khi công cụ tìm được đoạn dán, 6/10 là doc-41; 36 cụm viết sau khi biết đoạn đáp án; C/G/B' tự nhận không phân biệt được | Model không gọi tìm ở 9/12 bài. Sửa xếp hạng đổi được bao nhiêu bài *đạt*, khi doc-49/50 không hề gọi? |
| Harness tìm hộ | tách câu hỏi trên biến thể (15/15; dính liền 4/15 → 15/15 với R2); số *trượt* (44, 46, 53 hạng 7–10) đáng tin hơn số trúng; bảng token P3 | quy tắc + hư từ viết sau khi đọc 15 câu hỏi (8–9/12 trong mẫu); chấm tay mục lục 11/12 bởi người biết đáp án; 2,9 ký tự/token lệch với 3,55 đo của C | P3 đặt đoạn mồi (hạng 1 ở doc-53, doc-45) sát câu hỏi. Dự đoán gì cho doc-53, bài nền đang đạt? |

### 2. N1 đối đầu P3 và C, bằng số của họ

- **doc-53 (đoạn mồi).** **[tệp]** Ở nền, model đã đọc (0)(3)(6) = đoạn 0–8. Tức là đoạn đáp án 6 và đoạn mồi 8 cùng nằm trong
  ngữ cảnh, và model vẫn đạt (`task_results.jsonl` nền đủ bộ). Đó là bằng chứng gần nhất cho N1 (11 đoạn, ít hơn 1–2 đoạn so
  với nền). Còn P3: BM25 xếp đoạn 6 hạng 9 (harness) và ngoài top-3 ở 4/4 truy vấn (tìm) → P3 chèn đoạn mồi, bỏ đoạn đáp án.
  C: không thêm gì; bài này đang đạt nhờ câu ép, nên thêm vòng chỉ là rủi ro.
- **doc-47 (hai mảnh, đoạn 2 và 5).** **[tệp]** Ở nền, model đọc (0), viết "75 ngày" đúng, rồi dừng và lấy nhầm 54.000.000.
  - N1 có cả hai mảnh trong ngữ cảnh. Bước kiểm số #2 cũng không bác nhầm, vì nó coi mọi tin trong `working` là đã thấy
    (`answer_figures.turn_texts:50`). Model có nối được Điều 5 sang Điều 10 hay không thì **chưa đo**.
  - P3: B1 sót mảnh 2 (hạng 8), B2 đủ.
  - C: không đổi gì, vì model tự dừng sau một lần đọc.
- **Token vòng 1** (N1 ≈ 1,4k nền không phiếu + văn bản ở 2,9–3,55 ký tự/token; P3 lấy bảng của harness). Độ trễ thêm tính theo
  hệ số 0,13 ms/token vào (của C). Hệ số 0,29 của harness cho số gấp đôi.

| Độ dài | N1 vòng 1 | P3 vòng 1 | N1 − P3 độ trễ | Ghi chú |
|---|---|---|---|---|
| 10k ký tự | 4,2–4,9k | ~3,7k | +0,1–0,2 s | N1 thường 0 lần đọc; P3 trượt thì còn đọc tiếp |
| 30k ký tự | 9,9–11,7k | ~4,1k | +0,8–1,0 s mỗi vòng | N1 chỉ còn ~4k chỗ; model gọi thêm công cụ là chật |
| 100k ký tự | 29–36k: **không áp dụng** (> 16 384) | ~5,3k (trần ~4,4k) | — | chỉ P3 (hoặc phiếu cũ) |

- **47 bài không dán: không đổi theo cấu trúc code**, với điều kiện N1 là một hằng mới trong `take_pastes`, không sửa
  `PASTE_THRESHOLD`. Lý do (**[tệp]**): `take_pastes` chỉ thay tin có `is_paste` (> `PASTE_THRESHOLD`, `pastes.py:24,33`); bài
  không dán không có tin nào như thế. `PASTE_THRESHOLD` còn giữ chat thường (`chat.py:88`) nên không được đụng.
  - N1 phải chỉ áp cho tin user cuối. Tin cũ trong lịch sử 40 tin vẫn thành phiếu, không thì mỗi lượt sau kéo theo ~10k token.
    Agent Eval chỉ có bài một lượt nên không đo được chỗ này; cần test đơn vị.
  - Ngưỡng N1 phải theo nguyên tắc nêu trước (cửa sổ − nền − 4k dự trữ ≈ 10k token ≈ 29–35k ký tự). doc-50 (31 681) nằm đúng
    mép, nên dễ bị coi là chỉnh theo bài đã thấy — cùng lời chê C tự nêu về N = 5.

### 3. Khung tối thiểu phân xử N1 / P3 / C trong một đợt

| Mục | Đề xuất |
|---|---|
| Nhánh | nền `94e321f` (#3-C); C1 (N = 7 theo nguyên tắc của C); P3 không nhúng; N1 (trên ngưỡng giữ phiếu #3-C). N1 và P3 tác động lên hai khoảng độ dài tách rời, nên ghép lại không cần nhánh riêng |
| Bài mù | 18 bài: 3 tầng × 6 kiểu. L1 10–15k ký tự; L2 15–30k (N1 áp dụng, C cần > 3 lần đọc); L3 40–100k (> 12k token, N1 không áp dụng, quá tầm với C). Sáu kiểu: giữa, xa, hai mảnh cách ≥ 4 đoạn, mồi/khác chữ, câu hỏi dạng lệnh hoặc nằm giữa, **không có đáp án** |
| Cửa offline, không GPU | P3: tách câu hỏi ≥ 80%, top-3 ≥ 60% trên bài mới (luật của chính harness). C: mô phỏng tầm với. N1: ước token < ngưỡng. Nhánh nào bản đăng ký tự đoán trượt cổng → không chạy |
| Lần chạy | 15 bài cũ (dev): 1 lần t = 0 mỗi nhánh. 18 bài mù: t = 0 + 2 lần ở 0,4 với seed khác ("đạt" = ≥ 2/3); cần runner nhận seed/nhiệt độ — chưa kiểm. r1 = r2 ở t = 0 đã chứng minh, không chạy lại. Một lần đủ 62 + 18 cho nhánh thắng |
| Luật (cổng) | mỗi nhánh so nền trên 18 bài mù: thắng − thua ≥ 3, thua ≤ 1; bài không có đáp án không xấu đi; 47 bài không dán trùng nguyên; không vòng nào > 15 000 token, không bài nào > 60 s. Nhiều nhánh qua cổng thì nhánh có thắng − thua cao hơn được chọn; bằng nhau thì nhánh ít token hơn. Dòng cơ chế theo tầng chỉ báo, không chặn. Ghi rõ: 18 bài thì ≥ 3 là ngưỡng thực dụng; muốn phân biệt được với nhiễu theo phép thử dấu cần 6–0 |
| GPU (ước, ~13 s/bài dán gồm nạp lại; L3 ở C tới ~38 s) | dev 4 × 15 × 13 s ≈ 13 phút; mù 4 × 18 × 3 ≈ 216 lượt ≈ 55–65 phút; đủ bộ ≈ 11 phút → **~80–90 phút** |
| Tệp duyệt | 6: bài mù, 3 nhánh, bản đăng ký, báo cáo (#3-D: 9). Code ước: C1 ~5 dòng, N1 ~15 dòng + test, P3 ~70 dòng + ~100 test |
| Dừng | GPU ≥ 85 °C: tạm dừng, chờ nguội (đã thấy 46–58 °C). Hạn tuần ≥ 35%: dừng, để quyết định sáng. Cửa offline trượt: bỏ nhánh, không tốn GPU. Phiên khác xin GPU: nhường, trừ khi đang giữa một lần chạy |

### 4. Xếp hạng cuối (tạm, ý kiến)

0. **Đếm nhu cầu** (SQL một dòng). Đây là điều kiện trước, không phải một hướng; ra 0 thì cả bảng dưới thành việc làm CV.
1. **N1 ≤ ngưỡng, trên ngưỡng giữ phiếu.** Bỏ hẳn bước model quyết đọc, là chỗ hỏng chính đo được. Cùng tầm với C (~27–30k ký
   tự) nhưng chỉ tốn một vòng. 47 bài không đổi theo code. doc-53 ở nền là bằng chứng gần nhất.
2. **P3 cho phần trên ngưỡng.** Là hướng duy nhất với tới văn bản 100k; chỉ đáng làm khi cửa offline trên bài mù qua được.
3. **S1 + S2 (mép neo, bỏ chặn IDF)** như sửa lỗi. Lỗi có thật và rẻ, nhưng không đổi tần suất gọi tìm; nên làm kèm S6, vì cái
   giá chen thư viện ở 94% số cặp là có thật.
4. **Câu trả lời ép nói thật vị trí đã đọc tới.** Rẻ, độc lập, chữa cách đoán "thông lệ chung" ở mọi nhánh.
5. **C1.** Về token thì thua N1 ở mọi độ dài N1 phủ, và quá ~27k ký tự cũng không tới; giữ làm phương án dự phòng nếu N1 hỏng.
6. **Phiếu lái sang tìm (N2/N3 của báo cáo tìm).** doc-53 là ca lùi được dự đoán sẵn.

**Điều sẽ làm tôi đổi hạng 1:**
- (a) Trên tầng L2 mù, N1 thua ≥ 2 bài mà nền đạt (nhất là bài mồi): khi đó model 9B kém với ngữ cảnh 10–12k, và C1 hoặc P3
  lên hạng 1.
- (b) Số đếm nhu cầu cho thấy văn bản dán thật phần lớn > 30k ký tự: P3 lên hạng 1.
- (c) Đếm token thật (`prompt_eval_count`) cho thấy tiếng Việt dán < 2,9 ký tự/token: ngưỡng N1 tụt dưới ~20k và nó mất nửa tầm với.
