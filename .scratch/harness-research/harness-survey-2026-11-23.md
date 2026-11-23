# Khảo sát harness cuối 2026: cái gì đang tốt nhất, cái gì mới, cái gì đã đo là vô ích

Viết 23/11/2026 bởi claude-fable-5-2. Nối tiếp `.scratch/foundation-and-agent-eval/harness-capabilities-survey.md` (27/10) và
không lặp lại nó. Là nền bằng chứng cho `breakthrough-plan.md` cùng thư mục.

## Bản chất

Cùng một bộ óc, đặt vào hai cái khung khác nhau, có thể làm việc giỏi gấp đôi hoặc gần như không làm được gì. Với bộ óc lớn
thì khung càng mỏng càng tốt, vì nó tự biết lúc nào dừng, lúc nào kiểm lại. Với bộ óc nhỏ thì ngược lại ở một điểm: phần nó
nhìn thấy vẫn phải thật gọn, nhưng những quyết định lặp đi lặp lại phải do phần code quanh nó làm thay. Các nhóm đi đầu năm
nay không thắng nhờ viết lời dặn dài hơn hay cho model nghĩ nhiều vòng hơn; họ thắng nhờ code kiểm, code chặn, code sửa.
Cái mới nhất là để máy tự tìm cách sửa khung, và cảnh báo mới nhất là phần lợi của việc đó thường biến mất trên bài chưa
từng thấy.

## Cách làm và giới hạn

- Bốn mảng tìm đọc song song ngày 23/11/2026, khoảng 390 lượt tìm và đọc trang. Ghi chú gốc đầy đủ nằm ngoài repo.
- Nhãn bằng chứng: **[Đ]** đã mở trang, **[T]** chỉ đọc phần tóm tắt của bài, **[S]** chỉ thấy trong kết quả tìm kiếm.
- Trang được đọc qua một công cụ tóm tắt, trang trên 100 nghìn ký tự bị cắt. Số [Đ] là "số công cụ trích ra", chưa đối
  chiếu tay với bản gốc.
- "Tự báo" là số của chính tác giả phương pháp. Phần lớn số về model nhỏ là tự báo.
- **Không nghiên cứu nào đo các ý dưới đây trên hỏi đáp tài liệu có trích nguồn, trên tiếng Việt, hay trong trần 3 vòng
  công cụ và 90 giây.** Mọi ý là giả thuyết cho Ún cho tới khi đo trên Ún.

## 1. Harness đổi kết quả bao nhiêu khi giữ nguyên model

| Model | Bài đo | Harness thấp nhất → cao nhất | Loại số | Nguồn |
|---|---|---|---|---|
| Claude Opus 5 | Terminal-Bench 4 | 30,16 (pi) → 57,14 (OpenHands) | độc lập | [arXiv 2610.00917](https://arxiv.org/html/2610.00917) [Đ] |
| GPT-6 Astra | Terminal-Bench 4 | 49,21 (OpenHands) → 60,32 (pi) | độc lập | như trên |
| Haiku 4.5 | Terminal-Bench 2.0 | 13,9 (OpenHands) → 37,6 (Meta-Harness) | tự báo | [arXiv 2603.28052](https://arxiv.org/html/2603.28052v1) [Đ] |
| gemma4:e2b (2B) | bài tệp và code tự viết | 0,017 (opencode) → 0,271 (goose) → 0,821 (Mingbird) | tự báo | [arXiv 2610.02001](https://arxiv.org/html/2610.02001v2) [Đ] |
| Qwen3.5-9B | Aider Polyglot | 19,1 % (Aider) → 45,6 % (little-coder) | tự báo | [bài viết của tác giả](https://itayinbarr.substack.com/p/honey-i-shrunk-the-coding-agent) [Đ] |
| model 4B | WebArena-Verified | 6,7 % → khoảng 45 %, ít hơn 76–92 % lượt gọi model | tự báo | [arXiv 2609.26760](https://arxiv.org/abs/2609.26760) [T] |

- Thứ hạng harness đảo theo model: pi tốt nhất cho GPT-6 Astra và tệ nhất cho Claude Opus 5. Harness của hãng không phải
  lúc nào cũng tốt nhất cho model của hãng.
- Hiệu ứng phụ thuộc từng model: trong một nghiên cứu 432 lượt chạy, một model 2B giữ nguyên 91,7 % dưới cả ba kiểu khung
  nhẹ, vừa, chặt, trong khi khung dài dòng làm một model lớn tụt 29–38 điểm
  ([arXiv 2605.26731](https://arxiv.org/abs/2605.26731) [T]).
- Một phần chênh lệch không do thiết kế: khoảng cách 20–30 điểm giữa hai harness phần lớn là do giới hạn thời gian
  ([arXiv 2611.08417](https://arxiv.org/abs/2611.08417) [Đ]).
- Trần của model nhỏ vẫn còn: Qwen 9B với harness đã chỉnh kỹ chỉ đạt 9,2 % trên Terminal-Bench 2.0
  ([little-coder](https://github.com/itayinbarr/little-coder) [Đ]).

## 2. Ý có số đo ở model từ 10B trở xuống, gần như không tốn thêm lượt gọi

| # | Ý | Số đo và điều kiện | Chi phí | Rủi ro | Nguồn |
|---|---|---|---|---|---|
| 1 | Cổng hoàn tất bằng code: phép kiểm xác định chặn câu "xong" sai rồi giao lại việc | Bỏ 5/6 phép kiểm thì mất 0,152 ở model 2B, p = 0,014 | 1 lượt thêm khi cổng chặn | bài do tác giả tự viết | [arXiv 2610.02001](https://arxiv.org/html/2610.02001v2) [Đ] |
| 2 | Sửa schema, đừng âm thầm sửa lệnh gọi: công cụ không tham số được cho một tham số bắt buộc | 7/40 → 29/40, vi phạm 93 % → 0 % (Qwen2.5-1.5B, Qwen3-1.7B) | 0 | 40 bài, phụ thuộc model | [NeurIPS 2026 workshop](https://neurips.cc/virtual/2026/171301) [T] |
| 3 | Cắt kết quả dài giữ cả đầu và đuôi | Chỉ giữ đuôi làm một bài tụt 1,00 → 0,35 (2B); Claude Code 2.1.321 chuyển sang đầu+đuôi | 0 | tín hiệu có thể nằm giữa | như #1; [changelog](https://code.claude.com/docs/en/changelog.md) [Đ] |
| 4 | Ví dụ lệnh gọi mẫu trong prompt | +21,5 % (Llama-3.2-3B); lợi giảm sau 3 ví dụ [S] | token prompt | một tác giả; chưa đo ngoài tiếng Anh | [arXiv 2604.20148](https://arxiv.org/abs/2604.20148) [T] |
| 5 | Ít công cụ trong prompt | Qwen2.5-1.5B 55,20 → 29,48 và Qwen2.5-7B 76,95 → 69,24 khi tăng lên 20 công cụ | 0 | Ún mới có 7 công cụ, lợi sẽ nhỏ hơn | [arXiv 2603.11495](https://arxiv.org/html/2603.11495v1) [Đ] |
| 6 | Đổi tên công cụ theo tên model đã quen | Llama3.2-3B 43,6 → 60,6; Qwen2.5-7B 78,3 → 88,2; Qwen2.5-3B gần như không đổi | khoảng 33 lượt gọi một lần cho mỗi tên | chỉ đo schema tiếng Anh | [arXiv 2510.07248](https://arxiv.org/html/2510.07248v3) [Đ] |
| 7 | Nghĩ tự do, đóng khuôn sau: để model trả lời tự do rồi code đóng thành lệnh | Ép schema cứng: Qwen2.5-1.5B 91,5 % → 48,0 % lệnh chạy được; đóng khuôn bằng code giữ 91,5 % | 0 nếu đóng bằng code | đo trên vLLM, chưa đo trên Ollama | [arXiv 2605.26128](https://arxiv.org/html/2605.26128) [Đ] |
| 8 | Ràng buộc cứng chỉ hợp với JSON phẳng | Qwen3-0.6B: 94,8 % lỗi cú pháp được sửa, 70,5 % trong đó thành đúng nghĩa | không đáng kể | thư viện Python, không phải Ollama | [IJCAI 2026](https://www.ijcai.org/proceedings/2026/0267.pdf) [Đ] |
| 9 | Lỗi công cụ trả về thành chữ, không kết thúc im lặng | Model tự bắt đầu 180/192 lần sửa khi có tín hiệu (model lớn) | 0 | model nhỏ hay lặp lại lệnh sai ([arXiv 2601.15625](https://arxiv.org/abs/2601.15625) [T]) | [arXiv 2610.00917](https://arxiv.org/html/2610.00917) [Đ] |

Về quyết định **gọi hay không gọi công cụ**, bốn kết quả chỉ cùng một hướng:

- Lời dặn "đừng gọi khi không cần" chặn luôn cả lệnh gọi cần thiết. Nhu cầu gọi công cụ đọc được từ trạng thái bên trong
  model trước khi nó viết chữ nào (AUROC 0,89–0,96 trên sáu model); cách đọc đó giảm 38 % lệnh gọi, mất 1,7 % độ đúng
  ([When2Tool, arXiv 2605.09252](https://arxiv.org/abs/2605.09252) [T]).
- Ràng buộc model chỉ được viết tên công cụ làm hỏng quyết định "không gọi", tệ nhất −29,5 điểm ở model 0,6–4B, và chỉ có
  lợi ở bài cần gọi ([arXiv 2608.13959](https://arxiv.org/abs/2608.13959) [T]).
- Hai model nhỏ chỉ trả lời không gọi ở 9 % và 17 % số câu không cần công cụ
  ([arXiv 2610.02142](https://arxiv.org/abs/2610.02142) [Đ]).
- LoRA gọi công cụ bằng dữ liệu công khai làm Qwen3.5-4B tụt ở đúng mục này: irrelevance 80 % → 42 %, tổng 87,3 % → 79,0 %
  trên một phần BFCL V4 ([thẻ model](https://huggingface.co/sukhrobnurali/tooltuned-qwen-3.5-4b) [Đ]).

Về **máy chủ model cục bộ**:

| Điều | Số đo và điều kiện | Nguồn |
|---|---|---|
| Lượng tử hoá 4-bit ở model dưới 2B | Qwen3-1.7B bỏ sót lệnh gọi 6,0 % → 17,3 % (p = 0,0001); Qwen3-4B không đổi | [NeurIPS 2026 poster](https://neurips.cc/virtual/2026/171153) [T] |
| Q4_K_M trên bài nhiều lượt | Qwen3-1.7B 14,50 % → 8,75 % | [NeurIPS 2026 poster](https://neurips.cc/virtual/2026/171271) [T] |
| Dùng lại phần đầu prompt | Trúng 0,9–3,0 s, trượt 12–88 s cho khoảng 950 token; trượt vì dòng giờ ở đầu prompt hoặc thứ tự khoá JSON công cụ đổi. Một bài blog, model 0,5B trên CPU, Ollama 0.20.3 | [blog](https://baeseokjae.github.io/posts/local-agent-prompt-cache-invalidation-2026/) [Đ] |
| Ollama báo số token đã dùng lại | Từ v0.33.3 | [ghi chú phát hành](https://github.com/ollama/ollama/releases?page=3) [Đ] |
| Model lai của họ Qwen mất phần dùng lại | Lỗi còn mở ở llama.cpp với Qwen3.6; chưa rõ có dính Qwen3.5 2B và 9B | [llama.cpp #24055](https://github.com/ggml-org/llama.cpp/issues/24055) [Đ] |
| Ép đầu ra có cấu trúc có thể âm thầm tắt việc gọi công cụ | Ở một model, lượt chạy bịa nguồn mà thước đo kết quả cuối vẫn chấm đạt; chỉ trace từng công cụ mới lộ ra. Không phải số đo trên Ollama | [arXiv 2608.28439](https://arxiv.org/abs/2608.28439) [T] |

## 3. Đã đo là trung tính hoặc có hại

| Việc | Số đo | Nguồn |
|---|---|---|
| Thêm chữ vào system prompt | −2,3 điểm, trong khi trí nhớ dài hạn +5,6, công cụ +3,3, lớp chặn giữa +2,2 (Terminal-Bench 2) | [arXiv 2604.25850](https://arxiv.org/abs/2604.25850) [T] |
| Bộ lập kế hoạch chung, nén ngữ cảnh, sub-agent chung | Trung tính hoặc âm trên bài sửa code | [arXiv 2609.32459](https://arxiv.org/abs/2609.32459) [T] |
| Thêm khung qua 35 bản phát hành Qwen Code | Token +70 %, chất lượng không có xu hướng | [arXiv 2607.03691](https://huggingface.co/papers/2607.03691) [Đ] |
| Định tuyến nhiều agent với model dưới 10B | Tỉ lệ hoàn thành 79,92 % → 72,01 % | [ACL 2026 Industry](https://aclanthology.org/2026.acl-industry.123.pdf) [Đ] |
| Lấy 5 mẫu rồi bỏ phiếu, model từ 1B trở xuống | Lật câu đúng thành sai ở 3–10,5 % số câu; Qwen lượng tử hoá kém chạy một lần 3 điểm trên MATH-500; tốn gấp 5 lượt gọi | [arXiv 2611.11201](https://arxiv.org/abs/2611.11201) [T] |
| Bỏ phiếu đa số ở bài khó, model 7–8B | Giảm độ đúng ở 56,6 % số bài (Qwen2.5-7B) và 65,7 % (Llama-3-8B), GPQA Diamond | [arXiv 2608.11403](https://arxiv.org/abs/2608.11403) [T] |
| Model đệ quy đọc văn bản dài, Qwen3-8B | 26,0 / 2,0 / 24,0 / 4,3 trên bốn bộ bài; sau khi chưng cất từ thầy 480B vẫn chỉ 32,0 / 14,0 / 32,0 / 5,2. Tác giả: model không giỏi viết code thì khó dùng cách này | [arXiv 2512.24601](https://arxiv.org/html/2512.24601v2) [Đ] |
| Để model viết lại trí nhớ thành "sự kiện" | Xem mục 5 | |

## 4. Harness tự cải tiến

| Phương pháp | Cơ chế | Số đo | Điều phải biết | Nguồn |
|---|---|---|---|---|
| Meta-Harness (03/2026) | Một agent viết code đọc mã nguồn, điểm và **toàn bộ trace** của mọi bản harness trước rồi viết bản mới | Cho xem trace đầy đủ: trung vị 50,0; chỉ điểm: 34,6; điểm kèm tóm tắt: 34,9 | Khoảng 10 triệu token đề xuất mỗi vòng; model nhỏ nhất được thử là 20B; số Terminal-Bench tìm và chấm trên cùng 89 bài | [arXiv 2603.28052](https://arxiv.org/html/2603.28052v1) [Đ] |
| WHALE (08/2026) | Xen kẽ tìm harness và tinh chỉnh model | **Qwen3.5-2B**, SearchQA: chỉ tìm harness 38,29, chỉ chỉnh model 38,27, cả hai 48,34; tìm harness chỉ cần 5,79 % số lượt chạy. Toán: tìm harness gần như vô ích (0,42) | Chọn bản tốt nhất trên chính tập thử | [arXiv 2609.00196](https://arxiv.org/html/2609.00196v1) [Đ] |
| Phản biện độc lập (07–10/2026) | Chạy lại tiến hoá harness với tập huấn luyện/xác nhận/thử 45/10/34 | Lợi trên bài chưa thấy: **+0,0 điểm**; thua lấy mẫu song song cùng ngân sách (67,4 so với 72,3) | Có lợi ở trò chơi dài hơi | [arXiv 2607.12227](https://arxiv.org/html/2607.12227v4) [Đ] |
| HarnessCompass (08/2026) | Chỉ cho sửa đổi không gắn với bài cụ thể | Nói thẳng các phương pháp trước "hay khớp quá mức với bài dùng để tiến hoá" | Chỉ đọc tóm tắt | [arXiv 2608.01918](https://arxiv.org/abs/2608.01918) [T] |
| AHE (04/2026) | Mỗi sửa đổi kèm một dự đoán, vòng sau kiểm | 69,7 % → 77,0 % trong 10 vòng (tự báo) | Bản chạy lại độc lập là dòng trên | [arXiv 2604.25850](https://arxiv.org/abs/2604.25850) [T] |
| GEPA (ICLR 2026) | Model mạnh đọc trace và viết lại lời dặn | Qwen3 8B: 45,23 → 54,85 với 1.839–7.051 lượt chạy mỗi bộ bài; hơn LoRA-GRPO (48,91 ở 24.000 lượt) | Model phản tư yếu thì vô ích; thêm dữ liệu làm lời dặn dài và tệ hơn; trần 1.500 ký tự có tác dụng điều chuẩn ([Decagon](https://decagon.ai/blog/optimizing-gepa-for-production) [Đ]) | [arXiv 2507.19457](https://arxiv.org/html/2507.19457v2) [Đ] |
| Viết lại mô tả công cụ từ trace | — | Agent Qwen3-4B: 37,4 → 40,1 và 54,1 → 62,1 | Cần huấn luyện một bộ viết lại | [arXiv 2602.20426](https://arxiv.org/html/2602.20426) [Đ] |
| Lượt chạy đạt của chính mình làm ví dụ | Tìm lại rồi chèn vào prompt | ALFWorld 73 % → 89 % (gpt-4o-mini, 2025). Một mẩu tốt hơn hai đến bốn mẩu: 49,7 so với 46,0–44,4 | Chưa có số ở model dưới 10B | [arXiv 2505.00234](https://arxiv.org/abs/2505.00234) [T], [arXiv 2509.25140](https://arxiv.org/html/2509.25140v1) [Đ] |
| Ghi rồi phát lại trace làm test | Phần đã ghi phát lại, phần code mới chạy thật, không gọi model | 6/6 sự cố tự dựng | Đổi lời dặn thì bản ghi hết hiệu lực | [arXiv 2609.20625](https://www.alphaxiv.org/abs/2609.20625.md) [Đ] |

## 5. Trí nhớ và truy xuất

| Kết quả | Số đo và điều kiện | Nguồn |
|---|---|---|
| Tìm lại nguyên văn thắng trí nhớ do model viết | LongMemEval-S / BEAM-100K: nguyên văn + Qwen3-Embedding-0.6B 78,0 / 56,0; LightMem 64,0 / 51,5; Mem0 57,0 / 42,7; A-Mem 47,4 / 33,5. Dựng trí nhớ tốn 109–988 lượt gọi model mỗi hội thoại; nguyên văn tốn 0 | [arXiv 2610.24671](https://arxiv.org/html/2610.24671v1) [Đ], độc lập |
| Model nhúng là đòn bẩy lớn nhất | MiniLM → Qwen3-Embedding-0.6B: 63,2 → 78,0. Lập chỉ mục từng tin 78,0, từng cặp hỏi–đáp 63,8 | như trên |
| Trí nhớ trích xuất chỉ hơn ở việc biết từ chối | Hơn 6,7 và 15,0 điểm ở mục từ chối; thua ở cập nhật kiến thức (79,2 so với 88,9) | như trên |
| Ghi chú nền cạnh nguyên văn | Model đọc Qwen3.5-9B: 42,8 % → 51,0 %; agent tìm nhiều bước 58,6 % nhưng mất khoảng 26 s | [arXiv 2605.12493](https://arxiv.org/html/2605.12493v1) [Đ] |
| Tách câu hỏi bằng vòng lặp do code điều khiển | Qwen2.5-7B trên Ollama, HotpotQA: 43,1 → 52,9 với 2 lượt gọi model; bước tìm thứ ba chỉ thêm 0,3 | [arXiv 2606.21553](https://arxiv.org/html/2606.21553) [Đ] |
| Gọi model cho từng chunk lúc lập chỉ mục | Giúp BM25 (+8,7 recall) nhưng không giúp khi đã có dense mạnh và reranker; tiền tố đường dẫn mục cho kết quả tương đương mà không tốn lượt gọi | [arXiv 2603.23533](https://arxiv.org/abs/2603.23533) [T] |
| Tiếng Việt: lai luôn thắng | BM25 + dense tốt nhất trên cả 10 bộ. Trộn điểm có trọng số (0,7 cho dense) hơn RRF ở đa số dòng | [ViRE, EACL 2026](https://aclanthology.org/2026.findings-eacl.110/) [Đ] |
| Lời dặn "không biết thì nói không biết" | Xử lý được ngữ cảnh thiếu (tỉ lệ trả lời ≤ 1 %), không xử lý được ngữ cảnh gây nhầm (41,6 % vẫn trả lời), model 3,8–8B | [arXiv 2608.22228](https://arxiv.org/html/2608.22228) [Đ] |
| Model yếu không tự mở trí nhớ | Chỉ có lợi khi được bảo rõ "đọc trí nhớ trước" | [Anthropic, 06/11/2026](https://www.anthropic.com/engineering/components-of-agent-memory) [Đ] |

## 6. Đo thế nào cho đáng tin khi chỉ có 66 bài

Nguồn phương pháp: [Miller 2024](https://arxiv.org/html/2411.00640v1), [Bowyer và cộng sự 2025](https://arxiv.org/html/2503.01747v3),
[τ-bench](https://arxiv.org/html/2406.12045), [arXiv 2607.12227](https://arxiv.org/html/2607.12227v4). Các con số dưới đây là phép tính
áp các nguồn đó vào 66 bài, không phải số trích.

| Câu hỏi | Trả lời |
|---|---|
| Một điểm 58/66 chắc tới đâu | Khoảng Wilson 95 %: 78,0–93,8 % |
| Chênh 58 và 55 trên cùng commit | McNemar chính xác p = 0,25: không phân biệt được với không đổi. Nhiễu nền khoảng 3 bài |
| Cần thắng:thua bao nhiêu ở các bài lệch để p < 0,05 | 6:0, 8:1, 10:2, 12:3. Chưa đủ: 5:0, 7:1, 9:2 |
| Hiệu ứng nhỏ nhất phát hiện được | 8–11 điểm phần trăm khi hai bản lệch nhau ở 5–10 % số bài |
| Muốn thấy hiệu ứng 3 điểm | Khoảng 969 bài |

Quy trình ghép từ các nguồn: ghim digest model, mức lượng tử, phiên bản máy chủ; chạy đối chứng và ứng viên cùng ngày, xen kẽ;
so từng bài bằng phép thử chính xác đã ghi trước; khoá một tập xác nhận mà không bộ tối ưu, người viết lời dặn hay tập huấn
luyện nào được đọc; báo token, độ trễ, số vòng cạnh điểm. Dự án đã làm phần lớn các điều này; điều còn thiếu là tập khoá.

Bộ đo ngoài chạy được hoàn toàn cục bộ, không cần model chấm: [When2Tool](https://arxiv.org/abs/2605.09252) (18 môi trường, hỏi
có cần gọi công cụ không), [ToolMisuseBench](https://arxiv.org/abs/2604.01508) (6.800 bài, có ngân sách bước và lỗi cài sẵn),
[Multilingual-BFCL](https://huggingface.co/datasets/qualgo-technologies/Multilingual-BFCL) (gọi hàm tiếng Việt và tiếng Thái,
SIGIR 2026). Chưa bộ nào thành chuẩn; chưa bộ nào có số độc lập cho model dưới 10B.

## 7. Chưa kiểm được

- Bảng chính thức của Terminal-Bench không tải được; số xếp hạng lấy từ một bản sao.
- Không có lần chạy BFCL độc lập nào cho Qwen3.5-2B hay 9B. Số tự báo của hãng: 9B 66,1; 2B 43,6 ở chế độ suy nghĩ.
- Ollama có ràng buộc ngữ pháp cho lệnh gọi công cụ hay không; trạng thái lỗi [#14493](https://github.com/ollama/ollama/issues/14493)
  (bộ dựng và bộ đọc của Qwen3.5 lệch nhau) trên bản 0.40.x.
- Độ trôi điểm giữa các phiên bản Ollama với model GGUF: không nguồn nào đo.
- Chưng cất model 2–9B từ trace của chính harness, đo trên bộ bài không cần model chấm: không nguồn nào.
- Hai trang được tìm thấy có chèn câu nhắm vào AI đọc trang (một trang của Mem0, điều khoản của Amp). Không làm theo; số
  của Mem0 được coi là số tự báo.
