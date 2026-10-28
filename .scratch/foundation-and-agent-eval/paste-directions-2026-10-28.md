# Đoạn dán dài: các hướng sau #3-C — fable 5.1, 28/10/2026 (để bàn với opus, chủ dự án chọn)

Bối cảnh: #3-C trượt điều 3 (`kept/agent-eval-v0.6-paste-slip-c/REPORT.md`, fable ĐÚNG SỐ). Lỗi `n` hết hẳn; ba cách trượt
còn lại là thói quen model: hiểu sai phiếu rồi nhờ dán lại (doc-40), biết thiếu vẫn nhờ dán lại (doc-44), đọc một nửa
rồi nói đã đọc hết (doc-47). Chủ dự án hỏi "hướng nào tốt nhất", đã nhận bảng dưới và muốn fable + opus bàn rồi đưa một
hướng.

## Bằng chứng ngoài (nguồn chính thống, đã đọc)

| Nguồn | Điều dùng được |
|---|---|
| SWE-agent (Yang 2024), SWE-bench Lite, GPT-4 Turbo | cửa sổ 100 dòng + hiện tổng số dòng và số dòng bị ẩn trước/sau; `search_file` trả kết quả gọn. Ablation: bỏ tìm −2,3 điểm; xem cả tệp −5,3; tìm trả từng cái −6,0. Nguyên tắc 4: "guardrails giảm lan lỗi, phục hồi nhanh" |
| MemGPT (Packer 2023) | model "thường ngừng giở trang trước khi hết"; GPT-3.5 trượt vì "không tra đủ lần"; họ chữa bằng lời dặn "đừng ngừng tìm" + cảnh báo hệ thống chèn vào |
| Lost in the Middle (Liu 2023) | model dùng tốt đầu/cuối, kém giữa → đoạn tìm được nên đặt cạnh câu hỏi |
| Anthropic long-context, prompting-long-context | "trích dẫn trước khi trả lời" tăng độ đúng ở mọi so sánh; Claude 2: 0,939 → 0,961 |
| Anthropic contextual retrieval | dưới 200k token thì nạp thẳng, đừng tìm; chunk có ngữ cảnh: tìm trượt 5,7% → 2,9% |
| Claude Projects RAG (help center) | tự chuyển sang công cụ tìm khi tài liệu vượt cửa sổ |
| Anthropic context engineering | con trỏ nhẹ + tự tra khi cần; "làm cách đơn giản nhất chạy được" |
| Anthropic harness cho agent chạy dài | agent "tuyên bố xong quá sớm" → phải có bước kiểm, không chỉ lời dặn |
| Deep Agents (LangChain) | kết quả > 20 000 token đẩy ra tệp, model thấy đường dẫn + 10 dòng đầu, đọc lại bằng `read_file` offset + `grep` |
| OpenAI cookbook memory/compaction | `manifest.csv` mô tả từng tài liệu trước khi mở; không có số đo |
| OpenAI Agents SDK guardrails | output guardrail bác câu trả lời cuối (tripwire); SDK không tự chạy lại — ta phải tự làm, như #2 |

Không nguồn nào có số cho model nhỏ cục bộ, tiếng Việt. Hướng nào cũng phải đo ở đây với bài mới chưa ai xem.

## Các hướng

| # | Hướng | Nhắm vào | Đổi gì trong code | Đổi băm? Đo gì? | Rủi ro |
|---|---|---|---|---|---|
| 1 | **Chốt chặn đầu ra, nhắc lại một lần**: câu trả lời cuối nhờ dán lại / tải tệp, hoặc nói "đã đọc hết/toàn bộ" khi đoạn dán còn đoạn chưa đọc → trả về model một lần kèm lời nhắc tự đọc (cùng cơ chế #2) | doc-40, 44, 47 | `agent_service.run`: thêm một kiểm sau `answer_check`, mẫu chữ tiếng Việt + đếm đoạn đã đọc | không đổi `tools_sha256`; đo bài đoạn dán (mới) + kiểm 47 bài kia không đổi vì chỉ bật khi có đoạn dán | nhắc nhầm → thêm một vòng; lộ lời nhắc vào câu trả lời (#2 từng bị ở doc-22); hai lần thử lại trong một lượt (#2 + cái này) ăn vào ngân sách 90 s |
| 2 | **Harness tìm trước, đưa đoạn hợp vào phiếu**: cắt đoạn dán, nhúng/BM25, lấy top-k đoạn hợp câu hỏi, đặt vào phiếu cạnh câu hỏi | cả ba, không cần model quyết định đọc | `pastes.slip` + gọi embedding/reranker có sẵn; phải tách câu hỏi khỏi văn bản dán (heuristic) | không đổi băm công cụ; phiếu đổi lớn → đo bài đoạn dán; độ trễ thêm nhúng mỗi lần dán | tách câu hỏi sai; bài hai mảnh (doc-47) cần tìm được cả hai; thay đổi lớn nhất |
| 3 | **Công cụ tìm trong đoạn dán + kết quả đọc ghi vị trí** (mẫu SWE-agent / Deep Agents): `search_document(document_id, query)` trả đoạn nào khớp + trích ngắn; kết quả `read_document` ghi "đoạn 3–5 / 12, còn 7 đoạn sau" | doc-47 (biết còn đoạn), doc-46 (nhảy thẳng, không hết lượt) | công cụ mới + sửa `_fit_chunks`; mô tả công cụ `read_document` nhân tiện gỡ mâu thuẫn "id từ search_documents" | **đổi `tools_sha256`** → đo đủ 52 bài (ticket 10: mô tả công cụ xáo 39/40 câu) | không chữa trực tiếp "nhờ dán lại"; thêm công cụ = thêm chỗ chọn sai |
| 4 | **Mục lục đoạn dán** (mẫu manifest OpenAI, progressive disclosure): harness tạo một dòng mô tả cho mỗi đoạn (model 9B, một lần cho mỗi `paste_id`, cache), đặt vào phiếu | doc-44 (biết mở đâu), doc-47 (biết đoạn 5 có tiền cọc) | `pastes.slip` + một bước sinh mục lục trước lượt agent | không đổi băm công cụ; đo bài đoạn dán + độ trễ | thêm vài lượt model trước câu trả lời đầu (vài giây); chất lượng mục lục 9B chưa biết; mục lục sai dẫn mở sai |

Nền chung cho mọi hướng: gộp #3-C làm "trước" mới hay không (B) — nó không thua phiếu cũ ở dòng nào, nhưng trượt luật đặt
trước.

## Ý kiến fable (chưa phải quyết định)

1 trước (rẻ, không đổi băm, cơ chế #2 đã chứng minh), 3 kế (bằng chứng SWE-agent chắc nhất, chữa "tưởng đã hết" tận
gốc), 4 thay cho 2 nếu muốn "harness tìm hộ" (không cần tách câu hỏi), 2 để dành.

## Kết luận sau khi bàn với opus (28/10 tối; fable kiểm lại code: cờ `retried` chung ở :333/:360/:372, `_search_documents` nhận `tool_context`, câu trả lời ép ở `max_steps` không thử lại — đều đúng)

Điểm mới của opus, fable đồng ý:
- **Trần 9 đoạn (R3):** 3 lượt × 3 đoạn = đoạn 0–8, khoảng 13 000 ký tự; `PASTE_MAX` 100 000 (≈ 70 đoạn). Không bài nào
  trong 9 bài đặt đáp án sau đoạn 8, nên bộ bài hiện tại **không thể** lộ trần này. Hướng 1 một mình không vượt được trần;
  cần cách nhảy (3'/2/4). Bộ bài mới phải có ≥ 1 bài đáp án sau đoạn 8.
- **Hướng 1 phải có lượt thử lại riêng (R1):** doc-47 phía sau bị kiểm số liệu bác ở vòng 1, tiêu mất lượt thử lại duy
  nhất, rồi vòng 3 nói "đã đọc đầy đủ" — dùng chung cờ thì hướng 1 không bao giờ bắn ở đúng bài nó nhắm.
- **3' thay 3:** `search_documents` tìm luôn trong đoạn dán của lượt (BM25 thuần Python, không gọi model), trả `paste_id` +
  `chunk_index`; không đổi `tools_sha256`; câu "id từ search_documents" trong mô tả `read_document` thành đúng, mâu thuẫn
  doc-40 biến mất (gỡ mâu thuẫn ≠ chứng minh nguyên nhân). Phải đổi câu "search_documents không tìm thấy nó" trong phiếu.
  Rủi ro: trích 400 ký tự đủ để model trả lời mà không đọc tiếp → kết quả tìm ở đoạn dán kèm "đọc bằng
  read_document(from_chunk=i)" (chữ trong kết quả công cụ, không đổi schema).
- Hướng 4 bằng model 9B: với đoạn dán 100 000 ký tự là ~70 đoạn → ăn hết 90 s; 4' (tiêu đề đoạn, không model) rẻ nhưng vô
  dụng với văn bản không có tiêu đề. Hướng 2: tách câu hỏi dễ hơn fable nghĩ (`search_text()` đã dùng hai mép) nhưng
  truy vấn nhiễu và phiếu dài thêm cả ở bài trả lời được ngay.
- Nền đo: cắt từ `int/20-3c` (ed210e4), **không gộp #3-C vào main trước** — giữ luật đăng ký trước, hại thực tế ≈ 0 (server
  thật không có lượt từ 29/08). Fable đổi ý theo opus ở điểm này.

Đề xuất chung fable + opus (chủ dự án quyết): một bản đăng ký, ba nhánh trên cùng bộ bài mới — trước = ed210e4; +1
(lượt riêng, điều kiện kép mẫu chữ **và** còn đoạn chưa đọc, lời nhắc không nêu số đoạn, chỉ ở nhánh trả lời tự do, đếm
câu lộ lời nhắc); +1+3'. Cộng một lần chạy đủ 56 bài để chứng minh 47 bài khác trùng nguyên. GPU ≈ 15 phút tổng; code
≈ 90 dòng + 120 test; một vòng NV3 viết bài mù (≥ 1 bài sau đoạn 8, ≥ 1 bài cần nhảy).

## Quyết định chủ dự án (28/10 tối, nguyên văn)

"Duyệt gói: đo trên int/20-3c, không gộp #3-C trước; bước 1 nhắc lại một lần với lượt thử lại riêng; 3' cho
search_documents tìm trong đoạn dán; một bản đăng ký ba nhánh; NV3 viết bài mới mù, có ít nhất một bài đáp án sau đoạn 8.
Opus điều phối, fable duyệt."

Fable chuyển cho opus bằng tin ngay sau đó. Giao thức như #3-B/#3-C: người làm harness không thấy bài mới, NV3 không thấy
code harness; mỗi nhánh và bản đăng ký qua tệp duyệt của fable trước lần chạy đầu.

## Quyết định chủ dự án về phiếu (b) của nhánh 3' (28/10 đêm, sau khi xem ví dụ doc-39 và doc-49)

Nguyên văn: "vậy bỏ". Nghĩa là chọn phương án "Bỏ (b)" như đã trình bày: phiếu giữ lệnh đọc từ đoạn 0 như #3-C làm
lệnh chính, chỉ thêm một câu ngắn rằng `search_documents` tìm được trong văn bản dán và cho `chunk_index` để đọc thẳng
đoạn đó; không có câu "cần một chi tiết thì tìm trước". NV2 sửa `slip()` trên `wip/20-paste-search`, fable duyệt lại chỗ
đó, opus đăng ký lại riêng phần +1+3' (dự đoán; C3/C4 giữ) trước khi chạy nhánh đó. Nền và +1 chạy được ngay.

## Quyết định chủ dự án về lệch theo thứ tự chạy (28/10 đêm, nguyên văn)

"Chọn cách 2: runner gỡ model khỏi Ollama trước mỗi bài để mỗi bài chạy như chạy riêng; sửa riêng mục Quy trình của bản
đăng ký, fable duyệt lại, chạy lại cả ba nhánh #3-D. Ghi rõ mọi số đo cũ là số theo chuỗi."

Bằng chứng (opus 22:36–22:45, fable kiểm lại từ tệp): cùng chuỗi thì r1 = r2 15/15; cùng bài đổi chuỗi phía trước thì chỉ
3/15 trùng; chạy riêng từng bài thì hai nhánh khác code trùng từng chữ. Hệ quả: mọi số đo kept/ trước 29/10 là số theo
chuỗi; chỉ so được với nhau, không so được với số đo gỡ model mỗi bài. Fable sẽ duyệt: nhánh runner (gỡ model trước mỗi
bài, ghi vào manifest), mục Quy trình sửa của bản đăng ký, và câu ghi chú "số theo chuỗi" ở README của kept/.

## Hỏi opus (đã trả lời bằng tin 28/10 tối)

1. Opus nghiêng hướng nào, vì sao — nhìn từ code `agent_service.run` và chi phí đo thật (GPU, số lần chạy, bài mới cần
   viết).
2. Ước lượng cho từng hướng: số dòng code, băm nào đổi, lần đo nào cần (52 bài hay chỉ đoạn dán), bao nhiêu phút GPU.
3. Rủi ro fable bỏ sót, nhất là hướng 1 chồng lên #2 (hai lần thử lại một lượt, ngân sách 90 s, lộ lời nhắc).
4. Có gộp #3-C làm nền trước không.
