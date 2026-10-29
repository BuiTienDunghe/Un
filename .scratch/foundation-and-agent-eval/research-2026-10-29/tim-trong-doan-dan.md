# Tìm trong đoạn dán — đo offline (29/10/2026)

Không gọi model, không GPU, không sửa repo. Code trên `wip/20-paste-search` 92f5796. Script và dữ liệu:
`C:\Users\dungbt06\AppData\Local\Temp\claude\C--Users-dungbt06-local-ai-core\5e9b23d6-dd28-46a2-b314-bd7791bd6b8f\scratchpad\research\search\`
(`evalsearch.py` lõi, `matrix.py`, `detail.py`, `reads.py`, `grid.py`, `verify_and_cost.py`, `real_queries.json`, `user_queries.json`).

## Bản chất

Công cụ tìm hiện nay chấm điểm một đoạn theo những chữ nó có chung với câu hỏi. Nhưng nó bỏ qua mọi chữ xuất hiện ở quá
nửa số đoạn. Với một hợp đồng thuê, chữ "hợp đồng", "thuê", "tiền cọc" có ở khắp nơi, nên câu hỏi về hợp đồng thuê
không còn chữ nào được tính và công cụ trả lời "không có gì". Thứ hai, công cụ lẽ ra phải bỏ phần đầu và phần cuối mà
model đã thấy. Nhưng ở vài văn bản, nó không nhận ra phần đầu, vì bộ cắt đoạn đã xoá dòng tiêu đề đánh số. Thế là
đoạn chứa chính câu hỏi đứng đầu kết quả và đẩy mảnh đáp án thứ hai ra ngoài phần model được xem. Hai lỗi này sửa được
trong ruột công cụ. Còn một lỗi không sửa được bằng cách đếm chữ: khi văn bản dùng chữ khác câu hỏi ("khởi hành muộn"
thay vì "trễ"), và có một đoạn khác dùng đúng chữ câu hỏi, công cụ sẽ dẫn model tới đoạn sai.

## Điều kiện đo

| Mục | Giá trị |
|---|---|
| Bài | 15 bài đoạn dán v0. 12 bài cần phần giữa được tính hit; 3 bài đáp án ở mép (42, 45, 52) chỉ dùng cho phép đo lạc đề |
| Vị trí đáp án | theo brief, kiểm lại bằng regex `must_mention` trên từng đoạn: khớp cả 15 |
| Bộ (i) truy vấn thật | 10 cặp (bài, truy vấn) khác nhau, gom từ mọi `events.jsonl` trong `kept/`: doc-39 ×1, 41 ×6, 43, 47, 50 ×1. Chỉ 3/10 (41 ×1, 43, 47; `v0.7-paste-nudge-search`) được viết khi công cụ tìm được trong đoạn dán. 7/10 viết lúc công cụ chỉ thấy thư viện (v0.3–v0.6, `v0.7-tool-call-parse`); khi biết mình tìm trong đoạn dán, model có thể viết khác |
| Bộ (ii) | nguyên dòng câu hỏi (dòng đầu hoặc dòng cuối), 12 truy vấn |
| Bộ (iii) | 3 cụm ngắn tôi viết cho mỗi bài, 36 truy vấn. Viết trước khi chạy biến thể nào, nhưng sau khi đã biết số đoạn chứa đáp án; tôi chưa đọc chữ của đoạn đó |
| hit@3 (cột chính) | **mọi** mảnh đáp án nằm trong 3 mục đầu. Đây là số model thật sự thấy: `tool_result_max_chars` = 2400 ký tự, 3 mục chiếm 2061, nên mục thứ 4 bị `_dump` bỏ (`omitted: 1` ở cả hai lần tìm thật doc-41, doc-43) |
| hit@1 | **ít nhất một** mảnh ở hạng 1, nên có lúc hit@1 > hit@3 ở bài hai mảnh |
| Bản chép hàng A | thứ tự kết quả trùng `pastes.search_pastes` thật ở 70/70 truy vấn (top-8) |

## Bảng 1 — các biến thể (hit@1 / hit@3 / hit@4, rỗng = trả "không tìm thấy" ở bài cần phần giữa)

| Biến thể | (i) thật, n=10 | (ii) dòng hỏi, n=12 | (iii) cụm ngắn, n=36 | Tổng hit@3 /58 | Tổng rỗng /58 |
|---|---|---|---|---|---|
| **A hiện tại** (âm tiết, IDF chặn 0, k1 1,2, b 0,75) | 5/6/7, rỗng 3 | 5/7/9, rỗng 0 | 13/17/18, rỗng 9 | **30** | **12** |
| A0 = A, không loại mép | 1/6/7, rỗng 3 | 1/6/6 | 10/16/17, rỗng 8 | 28 | 11 |
| A' = A + mép neo (sửa lỗi mép, xem dưới) | 6/7/7, rỗng 3 | 5/7/9 | 13/17/18, rỗng 9 | 31 | 12 |
| B = IDF Lucene không chặn, mép cũ | 7/8/9 | 4/6/9 | 22/21/23 | 35 | 0 |
| **B'** = IDF Lucene + mép neo | 8/8/9 | 5/8/9 | 23/22/23 | **38** | **0** |
| B0 = IDF Lucene, không loại mép | 3/8/9 | 1/6/8 | 17/23/24 | 37 | 0 |
| Bg = B' + chỉ giữ đoạn có ≥ 1 chữ hiếm | 7/7/7, rỗng 3 | 5/8/9 | 18/17/18, rỗng 9 | 32 | 12 |
| Bm5 = B' + đoạn phải khớp ≥ 50% trọng số câu hỏi | 8/8/9 | 4/6/6, rỗng 2 | 23/20/21 | 34 | 2 |
| **C** = TF-IDF cosine + mép neo | 7/10/10 | 6/9/9 | 23/24/26 | **43** | **0** |
| D = cặp âm tiết, IDF chặn, mép neo | 6/6/6 | 8/9/10 | 16/15/16, rỗng 9 | 30 | 9 |
| E = cặp âm tiết, IDF Lucene, mép neo | 5/7/7 | 8/9/11 | 17/16/18, rỗng 5 | 32 | 5 |
| F = âm tiết + cặp, IDF chặn, mép neo | 6/6/6 | 9/9/9 | 21/19/21, rỗng 5 | 34 | 5 |
| **G** = âm tiết + cặp, IDF Lucene, mép neo | 7/8/8 | 8/10/10 | 23/22/23 | **40** | **0** |

Lưới k1 ∈ {0,6…2,0} × b ∈ {0,3…1,0} chỉ xê dịch ±2/58 ở cả hai loại IDF. Thứ quyết định là chặn IDF (31 → 38 hit@3,
12 → 0 rỗng), không phải k1/b. C 43, G 40, B' 38 là 58 truy vấn tương quan trên 12 bài, doc-41 chiếm 10: **không phân
biệt được** ba hàng này.

## Bảng 2 — bài hai mảnh (43, 47, 51; 14 truy vấn) và trích đoạn

| Biến thể | Cả hai mảnh trong 3 mục | Một cửa sổ đọc từ mục đầu phủ cả hai | Hai cửa sổ | Ba cửa sổ | Đáp án nằm trong 400 ký tự đầu của trích | Đáp án nằm trong cửa sổ 400 ký tự quanh chữ khớp |
|---|---|---|---|---|---|---|
| A | 3 | 0 | 5 | 5 | 0/38 | 19/38 |
| A' | 4 | 0 | 5 | 5 | 0/40 | 21/40 |
| B' | 5 | 0 | 4 | 6 | 0/52 | 26/52 |
| C | 8 | 0 | 6 | 9 | 1/57 | 28/57 |
| G | 7 | 0 | 5 | 8 | 0/54 | 27/54 |

Hai cột cuối đếm trên mọi đoạn đáp án vào được top-3, ở cả 58 truy vấn.

Một cửa sổ phủ được cả hai mảnh ở **0/14** truy vấn, ở mọi biến thể. Đó là cấu trúc chứ không phải xếp hạng: hai mảnh
cách nhau 4–6 đoạn, một lần đọc tối đa 3 đoạn, và `max_steps` = 3 nên tìm + đọc + đọc là trần. Trích hiện tại (400 ký tự
đầu đoạn) gần như không bao giờ chứa đáp án; cửa sổ quanh chữ khớp chứa được khoảng một nửa.

## Bảng 3 — giá: kết quả đoạn dán chen vào lần tìm thư viện

Truy vấn là 47 câu hỏi không dán của bộ v0, chạy với từng đoạn dán (705 cặp). Kết quả đoạn dán đứng **trước** kết quả
thư viện, và chỉ 3 mục được giữ.

| Biến thể | Số mục đoạn dán trung bình (trần 4) | Cặp mà thư viện bị đẩy khỏi 3 mục model thấy |
|---|---|---|
| A hiện tại | 3,74 | 661/705 |
| A' | 3,76 | 664/705 |
| B' / C / G | 3,98 | 700/705 |
| E (cặp âm tiết) | 1,67 | 249/705 |
| Bm5 (cổng 50%) | 1,42 | 113/705 |

Kết luận đo được: chặn IDF **không** che thư viện như docstring giả định, vì đã đẩy thư viện ra ở 94% số cặp. Bỏ chặn chỉ
thêm 5 điểm phần trăm. Muốn che thư viện phải đổi cách trộn, không phải đổi IDF. Giới hạn: tôi chưa biết thực tế người dùng
hỏi thư viện trong cùng cuộc chat có đoạn dán thường đến đâu.

## Ba lỗi cụ thể

**doc-47 (trả rỗng).** Cả 11 chữ của truy vấn thật đều có ở ≥ 5/9 đoạn ("hợp", "đồng", "thuê", "bằng" ở 9/9). Với IDF
chặn, mọi chữ nặng 0, nên công cụ trả rỗng. Mọi biến thể không chặn đều thoát: B' đưa đoạn 5 lên hạng 1, đoạn 2 chỉ ở
hạng 6; C đưa đoạn 5 lên hạng 1 và đoạn 2 lên hạng 3, nên cả hai mảnh đều lọt 3 mục. Giá là Bảng 3: +39 cặp lạc đề so với A.

**doc-43 (lỗi b, phần do công cụ).** Bộ cắt đoạn xoá dòng "1. Tổng quan dự án" trong 600 ký tự đầu. `_overlap` cần
đoạn 0 bắt đầu bằng nguyên phần đầu, nên không cắt gì. Hệ quả: đoạn 0, chứa chính câu hỏi, xếp hạng 1, và đoạn 5 (hạn nộp)
rơi xuống hạng 4. Hạng 4 là mục `_dump` bỏ, nên trong lần chạy thật model không hề thấy đoạn 5. Lỗi mép này gặp ở phần
đầu của doc-39, 40, 41, 43 và phần cuối của doc-40, 43. Mép neo (cắt sau 8 chữ cuối của phần đầu, trước 8 chữ đầu của phần
cuối, chỉ trong chuỗi đoạn liền ở mỗi mép) cắt đúng 15/15 văn bản. Với mép neo, đoạn 5 lên hạng 3 (A') hoặc hạng 2 (B'),
tức model thấy được. Mép neo phải giới hạn ở các đoạn sát mép: cụm "cho bên A trước ít nhất" lặp ở đoạn 2 của doc-47, và
bản neo đầu tiên của tôi đã cắt nhầm nửa đoạn đáp án đó.

**doc-53 (đoạn mồi 8).** Đáp án ở đoạn 6 viết "khởi hành muộn liên tục từ 6 giờ… 400.000 đồng". Đoạn 8 có nguyên câu "máy
bay… trễ khoảng 7 tiếng" (ví dụ về hành lý). Đoạn 8 hoặc 9 (cùng phần ví dụ) đứng hạng 1 ở mọi biến thể và mọi truy vấn.
Đoạn 6 nằm ngoài top-3 ở 4/4 truy vấn (dòng hỏi + 3 cụm ngắn), ở mọi biến thể. Tốt nhất nó chỉ lên hạng 4: E với dòng hỏi,
và A với "bồi thường trễ chuyến". **Không biến thể đếm chữ nào thoát.** Muốn thoát phải hiểu nghĩa
(nhúng hoặc reranker sẵn có, tôi chưa thử vì không được gọi model) hoặc dùng bảng từ đồng nghĩa (trễ ↔ muộn, tiếng ↔ giờ),
mà bảng đó viết theo đúng bài thì là học tủ đề thi. Nền **đạt** doc-53 nhờ đọc tuần tự (0)(3)(6). Vậy bất kỳ câu nào đẩy model
đi tìm sớm đều có thể làm bài này lùi. Đây là bằng chứng đo được cho nỗi lo của chủ dự án.

## Phương án sửa `search_pastes` (đều không đổi `tools_sha256` trừ khi ghi khác)

| # | Phương án | Ưu | Nhược / rủi ro |
|---|---|---|---|
| S1 | Mép neo thay `_overlap` | sửa doc-43 tận gốc (đoạn 5 từ hạng 4 lên 3); ~25 dòng | neo trượt nếu chính 8 chữ cuối của phần đầu nằm trong dòng bị xoá; lúc đó lùi về cách cũ, không tệ hơn |
| S1' | Cho bộ cắt đoạn giữ dòng tiêu đề đánh số | chữa gốc, có ích cả cho tài liệu tải lên | đổi chunk của **mọi** tài liệu → phải nạp lại chỉ mục, đo lại retrieval; quá rộng cho vé này |
| S2 | IDF Lucene không chặn (B') | rỗng 12 → 0; hit@3 30 → 38; sửa một dòng | lạc đề 661 → 700/705 |
| S3 | TF-IDF cosine (C) | hit@3 cao nhất (43), cả hai mảnh doc-47 vào top-3 | không phân biệt được với B'/G trên 12 bài; viết lại cả hàm chấm (~20 dòng) |
| S4 | Thêm cặp âm tiết (G) | tốt nhất ở dòng hỏi (10/12); hợp từ ghép tiếng Việt | mất 1–2 hit ở cụm ngắn; chỉ số lớn gấp đôi; không phân biệt được với C |
| S5 | Cổng điểm (Bm5) hoặc chữ hiếm (Bg) | Bm5 giảm chen thư viện xuống 113/705 | Bm5 mất 4 hit@3, Bg quay về 12 lần rỗng |
| S6 | Trần số mục đoạn dán khi thư viện **cũng** có kết quả (vd ≤ 2), hoặc áp S5 chỉ trong trường hợp đó | che thư viện mà không mất recall khi chỉ có đoạn dán | thêm một nhánh trong `_search_documents`; không bài nào hiện nay đo được (bài dán không có kết quả thư viện) |

## Phương án cho lỗi (b) — mảnh thứ hai

| # | Phương án | Ưu | Nhược / rủi ro |
|---|---|---|---|
| R1 | Trích của mục đoạn dán là cửa sổ quanh chữ khớp, thay cho 400 ký tự đầu | giữ 3 mục; đáp án hiện trong kết quả ~một nửa số lần; hai mảnh cùng hiện khi cả hai vào top-3 (C: 8/14) | mô tả công cụ nói "ký tự đầu" → sửa mô tả thì **đổi băm**, phải đo đủ bộ; không sửa thì công cụ nói sai |
| R2 | Thêm trường "khớp" (~150 ký tự quanh chữ khớp), giữ trích cũ | không đổi băm (thêm trường, không đổi schema) | mỗi mục thêm ~200 ký tự → 3 × ~890 > 2400, chỉ còn **2 mục**; phải rút trích xuống ~250 để giữ 3 |
| R3 | Khi các mục đoạn dán không liền nhau, thêm một câu trong kết quả: "các đoạn khớp nằm rời: 1, 5 — đọc từng đoạn" | không đổi băm; nhắm đúng doc-43 | tốn lượt đọc thứ hai (vừa đủ trong trần 3); chưa biết model 9B có theo không |
| R4 | Cho `read_document` nhận danh sách đoạn | một lần đọc lấy cả hai mảnh | **đổi schema và băm**, đo đủ bộ; thêm chỗ cho model gọi sai |

## Phương án câu phiếu — model tìm đúng lúc

Bằng chứng offline chỉ nói một điều: nếu model tìm với truy vấn hợp lý thì đáp án vào top-3 thường đến đâu. Nó không chứng
minh model sẽ tìm. doc-49 và doc-50 trượt vì model không gọi tìm, đó là lỗi hành vi chứ không phải lỗi xếp hạng.

| # | Cách | Ưu | Nhược / rủi ro |
|---|---|---|---|
| N0 | Giữ phiếu như 92f5796 | không rủi ro mới | 49, 50 vẫn trượt (model không tìm ở 9/12 bài) |
| N1 | Câu "cần một chi tiết thì tìm trước" cho mọi đoạn dán | đơn giản | chủ dự án đã bỏ; doc-53 là ca lùi có thật (đoạn mồi hạng 1 ở 4/4 truy vấn) |
| N2 | Harness chỉ thêm câu "tìm trước" khi văn bản > 9 đoạn, tức đọc tuần tự 3 lần không tới hết | đúng chỗ đọc tuần tự chắc chắn hỏng (41, 46, 49, 50); với ≤ 9 đoạn giữ nguyên hành vi cũ (39, 40, 42, 44, 47, 48, 51, 52) | vẫn lộ 43, 45, 53 (10–11 đoạn); phiếu lại hé số đoạn gián tiếp (#3-C đã bỏ con số vì model dùng làm n) |
| N3 | Không đổi phiếu; kết quả `read_document` thêm một câu khi số đoạn chưa đọc > 3 × số lượt còn lại: "còn k đoạn chưa đọc; chưa thấy thì search_documents để nhảy tới". Quy tắc "còn > 3 đoạn" thì sai, vì sau lần đọc (0) nó bắn ở 15/15 bài | phiếu không hé số đoạn; không đổi băm; lời gợi ý tới sau lần đọc đầu, khi model đã thấy 3 đoạn | lộ **đúng tập bài của N2** (> 9 đoạn: 41, 43, 45, 46, 49, 50, 53); doc-53 vẫn là ca lùi. N2 và N3 khác thời điểm, không khác phạm vi rủi ro |

**Vì sao biến thể mới làm câu "tìm" ít rủi ro hơn (bằng chứng gián tiếp):** với A, 12/58 lần tìm trả "không tìm thấy", và ở
doc-47 sau câu đó model trả lời luôn mà không đọc. Với B'/C/G, 0/58 lần rỗng. Còn lại một kiểu rủi ro không giảm: đoạn mồi
dùng đúng chữ câu hỏi.

## Ý kiến của tôi (chủ dự án quyết)

Tôi nghiêng về S1 + S2 trước, vì đó là thay đổi nhỏ nhất mà số đo vững nhất (rỗng 12 → 0; doc-43 đoạn 5 vào được tầm nhìn).
C hay G thay B' là tuỳ: chúng nhích hơn nhưng không phân biệt được trên 12 bài. Cho lỗi (b), tôi nghiêng về R1 kèm sửa mô
tả, chấp nhận đo đủ bộ, vì R2 mất một mục và R3 trông vào một lượt model có thể không dùng. Cho phiếu, tôi nghiêng về N3
hơn N2, chỉ vì N3 không hé số đoạn trong phiếu. Hai cách lộ cùng một tập bài, và doc-53 là bài canh của cả hai. S6 nên làm cùng nếu bỏ chặn IDF, dù hôm nay
chưa bài nào đo được nó.

## Thiết kế đo cô lập

- **Bài mới, NV3 viết mù**, không thấy code và không thấy báo cáo này: ≥ 8 bài. Trong đó ≥ 3 bài đáp án sau đoạn 9, ≥ 2 bài
  hai mảnh cách ≥ 4 đoạn, ≥ 2 bài có đoạn mồi dùng đúng chữ câu hỏi còn đáp án dùng chữ khác (kiểu doc-53), ≥ 1 bài đáp án ở
  mép.
- **Trước GPU:** chạy `evalsearch.py` trên bài mới với dòng hỏi, ghi hit@3 dự đoán vào bản đăng ký.
- **Nhánh:** nền = 2839b52 (+1+3' hiện tại); S = S1+S2(+S6), phiếu không đổi; S+R1 (+ mô tả); S+R1+N3.
- **Luật đăng ký trước:**
  1. Không nhánh nào làm bài nào đạt → trượt so với nhánh trước nó.
  2. S đạt thêm ≥ 1 trong các bài hai mảnh hoặc nhảy.
  3. N3 đạt thêm ≥ 2 trong các bài sau đoạn 9.
  4. N3 không làm bài mồi nào (cả doc-53) lùi.
  5. r1 = r2.
  6. 47 bài không dán: nhánh không đổi băm phải trùng từng chữ. Nhánh đổi băm (R1 sửa mô tả) thì điểm không thấp hơn nền,
     và liệt kê mọi bài đổi chữ. Lý do tách: ticket 10 đã thấy đổi mô tả công cụ xáo 39/40 câu, nên đòi trùng từng chữ là
     R1 trượt ngay từ thiết kế.

| Hạng mục GPU | Phép tính | Phút |
|---|---|---|
| Mỗi bài dán | trung vị 9–11 s chạy + 2,8 s gỡ/nạp lại (`v0.7-3d-iso-*`) | ~13 s |
| 4 nhánh × 2 lần × (15 cũ + 8 mới) | 184 lượt × 13 s | ~40 |
| Một lần đủ bộ cho nhánh thắng, nếu băm không đổi | 70 bài; nền 62 bài mất 9,4 phút | ~11 |
| Nếu sửa mô tả công cụ (R1), băm đổi: mỗi nhánh có R1 chạy đủ bộ thay cho dòng trên | 2 × 11 | ~22 |
| **Tổng** | | **~50 (băm không đổi) / ~62 (có R1)** |

## Điều tôi chưa kiểm

- Không gọi model, nên không biết model 9B có tìm, có theo câu R3/N3, hay có trả lời đúng từ trích cửa sổ không.
- Nhúng/reranker cho doc-53: chưa thử (cấm gọi model). Đó là cách duy nhất tôi thấy thoát được đoạn mồi.
- Bộ (iii) do một người viết, đã biết số đoạn đáp án; bộ (i) chỉ 10 truy vấn, 6 của doc-41, và 7/10 viết khi công cụ chưa tìm trong đoạn dán.
- Mép neo chưa thử ca 8 chữ cuối của phần đầu nằm trong dòng bị bộ cắt đoạn xoá.
- Bảng 3 giả định thư viện luôn có kết quả. Tần suất thật của "hỏi thư viện trong chat có đoạn dán" chưa biết.
- Số GPU là ngoại suy từ lần chạy 28/10, chưa tính GPU dùng chung với dự án khác.

## Vòng 2 — tranh luận chéo (sau khi đọc c-noi-tran-doc, harness-tim-ho, phan-bien)

**1. Có P3 thì công cụ tìm còn cần không?** Vẫn cần, làm đường dự phòng ở ba chỗ P3 không phủ:

- P3 trượt top-3 ở 3/12 bài (44, 46, 53; số trong mẫu của họ).
- Câu hỏi thứ hai ở lượt sau: phiếu P3 cache theo `paste_id`, nên đoạn kẹp sẵn là của câu đầu.
- Dán trước, hỏi sau: không tách được câu hỏi.

Cả ba là truy vấn ngắn model tự viết. Đó đúng là chỗ IDF chặn 0 làm hỏng: 9/36 cụm ngắn trả rỗng, so với 0/12 khi truy
vấn là nguyên dòng hỏi.

So cùng kiểu truy vấn (nguyên dòng hỏi, top-3 /12), số hai bên khớp: tôi 7 (hiện tại), 8 (B'), 9 (C), 10 (G); họ 8
(pyvi), 9 (âm tiết + cặp).
Họ dùng `BM25Okapi` (kiểm trong `outline/analyze.py`). Thư viện này thay IDF âm bằng một sàn dương, không chặn 0, tức đã
có sẵn bản sửa IDF. Họ gỡ dòng câu hỏi, tôi gỡ 600 ký tự mép; họ tách từ và bỏ hư từ. Áp cho P3, sửa IDF chỉ thêm 0–1 bài,
vì câu hỏi dài luôn có chữ hiếm. Sửa mép thì P3 cũng bắt buộc: không gỡ thì đoạn chứa câu hỏi chiếm hạng 1 (A0: hit@1 chỉ 1/12).

**2. N1 nạp nguyên văn bản.** doc-47 hết vấn đề: cả hai mảnh nằm sẵn trong ngữ cảnh. doc-53 hết là chuyện xếp hạng, thành
chuyện đọc. Dữ liệu có một quan sát nghiêng về N1: ở nền cô lập, lần đọc thứ ba chứa cả đoạn 6 lẫn đoạn mồi, và model vẫn
trả đúng "Khởi hành muộn" (`v0.7-3d-iso-base-r1`). Đoạn mồi làm hỏng xếp hạng, chưa thấy làm hỏng đọc. Mới một bài.

N1 hỏng ở đâu (suy luận, chưa đo):

- Bài dài nhất ≈ 11k token, cộng ≈ 1,84k nền thì còn ≈ 3,5k cho lịch sử và câu trả lời. Tràn thì Ollama được mô tả là bỏ
  tin cũ, đúng tin chứa câu hỏi. Vì vậy cần cổng đếm token, không thể dùng ngưỡng ký tự.
- Đáp án ở giữa văn bản 12/15 bài; doc-50 nằm ở đoạn 14/25. Đó là kiểu "lạc ở giữa", chưa đo trên 9B.
- Không có bài nào > 31,7k ký tự. Trên đó N1 không áp dụng được.

**3. Câu hỏi của phản biện.**

- (4) Model không gọi tìm thì sửa công cụ không đổi gì, đúng. Nhưng "khi gọi thì 2/3 ra đúng đoạn" là sai. Chỉ doc-41 ra
  đủ. doc-43 mất mảnh hai vì lỗi mép (hạng 4, bị `_dump` bỏ). doc-47 rỗng vì chặn IDF. Vậy công cụ đã làm hỏng 2/3 lần
  model thật sự tìm.
- (5) Đếm chữ thua kiểu ít từ chung: doc-53 trượt 4/4 truy vấn ở mọi biến thể, pyvi xếp hạng 9. Bỏ dấu cũng vô ích, vì
  trễ ≠ muộn. Cần nhúng hoặc reranker, chưa đo.
- (6) Sửa ruột `search_pastes` giữ băm; sửa mô tả "400 ký tự đầu" đổi băm, chạy đủ bộ ≈ 11 phút mỗi nhánh, đã tính.
- (10) Không có bài > 35k; phần N1 không phủ (quá cửa sổ, câu hỏi lượt sau) tôi chưa đo được.
- (11) Tôi đoán "sửa công cụ + gợi ý" **trượt** thắng − thua ≥ 3 trên 15 bài cũ: chỉ 49 và 50 có thể lật, 53 có thể lùi.
  Vì vậy chỉ nên chạy kèm bài mới.

**4. Xếp hạng (ý kiến của tôi, chủ dự án quyết).**

1. **Kết hợp:** N1 khi vừa ngân sách token, không thì P3, công cụ đã sửa làm dự phòng. Bỏ quyết định "đọc/tìm" ở mọi bài
   hiện có.
2. **N1 một mình:** đơn giản nhất, phủ 15/15 bài hiện có. Hỏng khi lịch sử dài, và bỏ trống văn bản > ~30k.
3. **P3:** không cần model quyết, nhưng 8–9/12 là số trong mẫu, và doc-45 bị đoạn nhiễu kéo lên hạng 1.
4. **Tìm-sửa + gợi ý trong kết quả đọc:** rẻ, giữ băm, nhưng vẫn cược vào việc model chịu tìm (3/12).
5. **C nới trần:** tốn token ≈ gấp ba N1 ở doc-50 (36k so với 11,5k, ước của phản biện), mà đáp án sau đoạn 14 vẫn không tới.

**Thí nghiệm ≤ 15 phút GPU: P3 hay sửa công cụ + gợi ý.**

- Bài: 10 bài mới, NV3 viết mù (≥ 3 bài nhảy, ≥ 2 bài hai mảnh, ≥ 2 bài đoạn mồi, ≥ 1 bài mép), cộng 15 bài cũ báo
  riêng.
- Chạy: hai nhánh trên `94e321f`, gỡ model trước mỗi bài, một lần (cô lập cho r1 = r2 15/15). 25 bài × 2 × ~13 s ≈ 11
  phút.
- Chỉ tiêu chính: số bài mới mà mọi mảnh đáp án đã vào ngữ cảnh trước câu trả lời cuối, đọc từ `events.jsonl`. Ít nhiễu
  hơn đạt/trượt.
- Luật: một nhánh thắng khi hơn ≥ 3 bài, không có bài đạt → trượt, và bài mép không gọi thêm công cụ. Hoà thì chọn sửa
  công cụ, vì phiếu không dài thêm ≈ 1,9k token ở mọi bài.
