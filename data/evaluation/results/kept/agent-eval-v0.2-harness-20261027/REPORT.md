# Ticket 10 — nâng harness theo lỗi đo được, Agent Eval v0.2 (27/10/2026)

**Thăm dò, chưa đủ chứng minh thống kê.** Mỗi điều kiện có 40 bài. Cách chấm được đăng ký trước khi
chạy 1a và 2b (Comments của ticket 10). Bản này sửa bản đầu (commit `8848e67`): bản đầu đọc các lần
chạy "nóng" như một điểm neo chung, nhưng thật ra không phải. Xem mục "Điểm neo".

## Thật ra chuyện này là gì

Có hai loại sửa, và chúng cho hai loại kết quả.

Loại thứ nhất là sửa **khung chạy** (kiểm soát): khi kết quả công cụ quá dài thì bỏ bớt trọn từng mục
và nói rõ đã bỏ bao nhiêu, thay vì cắt ngang. Cách này đo được chắc chắn: model không còn nhận JSON
gãy, và đọc lịch sử chat thì giữ được tin mới nhất.

Loại thứ hai là sửa **lời dặn** cho model (chất lượng), và ở đây kết quả xấu hơn mình mong:
- Lời dặn 1a ("cứ tra tài liệu trước, đừng hỏi xin phép") làm model chịu tra ở đúng những bài nó từng
  bỏ qua. Nhưng nó làm mất **nhiều bài khác hơn số bài nó cứu**: quên nêu tên tệp, tính thiếu, và kéo
  câu hỏi về chuyện đã bàn trong Discord sang tìm trong tài liệu.
- Gợi ý 2b ("tài liệu không có, thử tìm lịch sử chat") một mình **không đổi gì**: model đọc gợi ý rồi
  hỏi xin phép thay vì tự tìm.
- Hai cái đi cùng nhau thì câu hỏi Discord được trả lời đúng, nhưng tổng điểm vẫn thấp hơn khi không
  sửa gì.

Kết luận thực tế: chưa nên đưa 1a vào sản phẩm theo cách viết hiện tại.

Về phương pháp, nhiệt độ 0 chỉ cho kết quả lặp lại được khi **gỡ model chính trước mỗi lần đo**. Hai
lần chạy "nóng" cách nhau bởi việc khác có thể khác nhau hẳn, kể cả khi prompt giống hệt.

## Điều kiện đo

| | |
|---|---|
| Nhánh | `wip/10-harness`; mỗi điều kiện có commit riêng, cây sạch, `verified: true` (probe) |
| Bộ bài | `agent-eval-v0.2`, sha256 `99b2e915…`; bộ chấm `agent-eval-grader-v0.2` |
| Model | `general-v0` = `qwen3.5:9b`, max_steps 3, tool_result_max_chars 2400, injection defense ON |
| Máy | PC-dungbt, RTX 5060 Ti 16 GB, Ollama 0.40.8; GPU riêng cho ticket 10 từ 19:42 đến 20:55 |
| Mốc A | `d434c82` = bộ bài v0.2 + cụm 3a + mô tả "mỗi tin tối đa 800 ký tự". **Mốc v0.2 = bộ bài v0.2 + 3a; tác dụng của 3a lên điểm chưa đo** |
| Điều kiện | B = A + 1a (`44318e6`); C = A + 2b (`0ecc927`); D = A + 1a + 2b (`4beb9ba`, bổ sung) |

## Điểm neo: lạnh thì lặp lại được, nóng thì không

| So sánh | Prompt | Câu trả lời trùng |
|---|---|---|
| r1 lạnh và r6 lạnh (cùng gỡ model chính, cách nhau 14 phút và 4 lần chạy) | giống hệt | 40/40 |
| A lạnh và C lạnh (cách nhau khoảng 1 giờ), trên 33 bài web | giống hệt (2b chỉ tác động lượt Discord) | **33/33** |
| Các lần nóng **nối tiếp** nhau (r2, r3, r4 chỉ gỡ OCR/embedding, r5 seed 43) | giống hệt | 40/40 |
| A nóng (r2) và C nóng (t0), hai khối cách nhau bởi việc khác, trên 33 bài web | giống hệt (mọi mã băm prompt khớp) | **3/33**, 7 bài lật kết quả |
| Lần đầu với lời dặn mới (khởi động B) và lần ngay sau | giống hệt | 22/40 |
| Lần lạnh (r1) và lần nóng (r2) | giống hệt | 20/40 |

- **Seed không có tác dụng ở nhiệt độ 0** (seed 43 = seed 42 từng byte).
- Model OCR hay embedding nằm cạnh **không** phải nguyên nhân.
- Kết quả của một lần chạy nóng phụ thuộc vào việc máy chủ vừa xử lý gì trước đó. Lần chạy lạnh thì
  không. **Điểm neo dùng được là "gỡ model chính rồi đo".** "Một lần khởi động bỏ đi" chỉ cho kết quả
  ổn định trong một khối chạy liền, không cho một điểm neo dùng chung giữa các điều kiện.
- Cơ chế chưa được chỉ ra. Giả thuyết hợp nhất là Ollama dùng lại phần prompt đã xử lý.
- Hệ quả cho ticket 09 và mọi phép so trước/sau ở t0: gỡ model chính trước **mỗi** lần đo. Quy tắc
  trong `data/benchmarks/agent_eval/v0/README.md` đã được sửa theo đó.

## Kết quả

Mục tiêu của 1a là 5 bài trượt vì không gọi công cụ ở mốc A nóng: doc-10, doc-22, doc-25, doc-30 và
stat-02. Mục tiêu của 2b là hist-07 và hist-03. Luật chồng đã đăng ký trước đã kích hoạt (B làm mất 5
bài ngoài mục tiêu, cứu 3 bài mục tiêu), nên 2b được đo trên A (C), còn D là phần bổ sung.

**So sánh chính: lạnh, cùng trạng thái** (bổ sung chạy sau đăng ký; tất định, như mục trên).

| Điều kiện | Đạt | Mục tiêu 1a | Mục tiêu 2b: chấm / chấm tay | Ngoài mục tiêu: được / mất |
|---|---|---|---|---|
| A, mốc | 34/40 | 2/5 | 1/2 / 1/2 | — |
| B = A + 1a | 30/40 | **4/5** | 0/2 / 0/2 | +1 / **−7** |
| C = A + 2b | 34/40 | 2/5 | 1/2 / 1/2 | 0 / 0 (web giống hệt A) |
| D = A + 1a + 2b | 30/40 | **4/5** | 0/2 / **2/2** | +1 / **−6** |

Bài 1a làm mất (lạnh), giống nhau ở B và D:
- doc-26, doc-28: thiếu tên tệp khi trích nguồn.
- doc-27: không tính ra 2 giờ, và thiếu tên tệp.
- doc-17: nói "không có ngày cụ thể" dù lượt trước đã ghi 31/3.
- doc-19: trượt `not_found`; có thể lại là lỗi bộ chấm (xem dưới), chưa chấm tay.
- hist-05: không lọc theo `author_id`.
- hist-03 (chỉ B): chuyển sang tìm tài liệu.

**Bằng chứng rõ nhất cho cái giá của 1a** là trích nguồn, rõ hơn cả tổng điểm (fable tính, mình kiểm
lại; thêm ngày 27/10 sau khi duyệt). Tính trên mọi lượt chạy, gồm lạnh, nóng và 0.4:

| | Lượt doc-26/27/28 mất trích dẫn |
|---|---|
| Có 1a (B, D) | **32/36** (B 15/18, D 17/18) |
| Không có 1a (A, C) | **5/45** (A 1/27, C 4/18) |

Chênh tổng điểm lạnh (−4) chỉ ngang mức nhiễu khoảng 5 bài khi đổi prompt; chênh trích dẫn thì vượt xa
mức đó và lặp lại ở mọi trạng thái.

D đếm tay (hist-03 và hist-07 trả lời đúng người và đúng nội dung, chỉ trượt mục "cấm
`search_documents`") là 32/40, vẫn thấp hơn A.

**Ba lần ở nhiệt độ 0.4** (như ship; có lấy mẫu thật, dao động khoảng ±2):

| Điều kiện | 0.4 | TB | Mục tiêu 1a | Mục tiêu 2b: chấm / chấm tay |
|---|---|---|---|---|
| A | 31, 29, 33 | 31,0 | 4/15 | 3/6 / 3/6 |
| B | 28, 31, 27 | 28,7 | 8/15 | 0/6 / 0/6 |
| C | 30, 32, 31 | 31,0 | 4/15 | 3/6 / 3/6 |
| D | 29, 30, 29 | 29,3 (đếm tay 31,3) | 11/15 | 0/6 / **6/6** |

Hai cách đo nói cùng một điều:
- 1a tăng tỉ lệ chịu tra ở bài mục tiêu, nhưng tổng điểm giảm.
- 2b không có tác dụng gì một mình.
- 1a + 2b làm câu hỏi Discord đi đúng đường, nhưng vẫn chưa bù được phần 1a làm mất. Trong 10 lượt
  hist-03/07 của D (t0 nóng, lạnh, 3 lần 0.4; không tính lần khởi động), cả 10 đúng người và đúng
  nội dung. Chỉ 8/10 đúng thời điểm đăng tin: 2 lượt ở 0.4 ghi ngày đăng của Trang là 24/10, là ngày
  hạn chót, trong khi tin được đăng ngày 16/10. Bộ chấm không chấm thời điểm đăng, dù lời dặn đòi "nêu
  lúc nào". A và C lạnh cũng đạt hist-03 với một ngày đăng sai. Ghi lại cho v0.3. Cột "chấm tay" ở các
  bảng trên tính theo người và nội dung.

Các lần đo nóng ở t0 của từng điều kiện (A 31, B 31, C 32, D 31) **không** dùng để so: mỗi lần đo ở
một trạng thái máy chủ khác nhau, và trên prompt giống hệt đã thấy 7 bài lật. Bản đầu của báo cáo này
đã đọc nhầm chúng thành tác dụng của việc đổi prompt.

Chi phí: token vào của một lượt chạy nóng t0 là A 88 335, D 100 947 (+14%), do lời dặn dài hơn và thêm
lượt gọi công cụ. Ghi chú: một câu trả lời ở 0.4 (D, hist-07) lẫn chữ Trung Quốc ("安排在").

## Kiểm soát (KS) và chất lượng (CL)

| Loại | Thay đổi | Bằng chứng | Tác dụng lên điểm |
|---|---|---|---|
| KS | 3a: cắt theo từng mục, trả object khi tràn, mỗi tin tối đa 800 ký tự, mô tả công cụ nói rõ trần | **0** lần cắt giữa JSON trong 748 kết quả công cụ (v0.1: 6–7 lần mỗi lượt chạy), 85 lần bỏ bớt theo mục có ghi chú. Số 748 đếm trên events của cả 24 lần chạy ở máy chạy; `kept/` chỉ giữ events của 8 lần, gồm 253 kết quả, và cũng 0. Kiểm tất định bằng test | Chưa đo (theo quyết định) |
| CL | 1a: lời dặn "tra trước, đừng hỏi xin phép" | Lạnh: 34 → 30; mục tiêu 2/5 → 4/5 | **Âm** |
| CL | 2b: gợi ý khi tìm tài liệu rỗng trên Discord | Lạnh: C = A | Không đổi một mình; chỉ có tác dụng cùng 1a |

**Chưa làm, kèm lý do:** registry công cụ có schema, ngân sách token/thời gian, chuẩn hoá lỗi/thử lại,
tracing. Chưa có lỗi đo được nào đòi tới chúng:
- 716 lượt kiểm tham số có 2 lỗi (`limit=20` khi tìm theo từ khoá; agent tự kẹp lại).
- Ngân sách vòng gọi cạn 4 lần trên 24 lần chạy, đều ở doc-12. `max_steps` hiện có đã chặn.
- 0 lỗi chạy, 0 timeout.

## Cần chủ dự án hoặc điều phối chốt

1. **Ship thay đổi chất lượng nào.** Nhánh hiện ở trạng thái D (1a + 2b), tức là **gộp nguyên nhánh =
   ship 1a + 2b**.
   - (a) Ship 1a + 2b. Ưu: lỗi "không tra" giảm, câu hỏi Discord đi đúng đường. Nhược: tổng điểm thấp
     hơn mốc ở cả hai cách đo (lạnh 30 so với 34; 0.4 TB 29,3 so với 31,0).
   - (b) Ship 2b một mình. Ưu: không hồi quy (lạnh: giống hệt A), có sẵn cơ chế cho bước sau. Nhược:
     không cứu được bài nào khi đứng một mình.
   - (c) Không ship thay đổi chất lượng nào. Thử 1a-v2: giữ phần "đừng hỏi xin phép, cứ tra", bỏ phần
     liệt kê dài, và giữ câu trích nguồn nổi bật. Đo lạnh A / 1a-v2 / 1a-v2 + 2b, khoảng 8 phút GPU.
     Ưu: không ship hồi quy đã đo được. Nhược: chậm một vòng.
   - Ý kiến: (c). Đây chỉ là ý kiến.
2. **Tiêu chí của hist-03 và hist-07** (v0.3). fable chỉ ra rằng mục tiêu của 2b **bất khả thi ngay từ
   lúc đăng ký**: gợi ý chỉ hiện sau khi `search_documents` trả rỗng, nên bài nào 2b cứu được thì cũng
   đã phạm "cấm `search_documents`". Đây là một mâu thuẫn biết trước được, không phải chấm lại sau khi
   xem câu trả lời. Hai cách:
   - (a) v0.3 tách "đúng câu trả lời" và "đúng đường đi" thành hai cột; hist-03/07 bỏ
     `search_documents` khỏi danh sách cấm, vẫn bắt buộc `search_history`. Ưu: khớp với thiết kế của
     2b. Nhược: chấp nhận thêm một lượt gọi công cụ.
   - (b) Giữ tiêu chí, kết luận rằng 2b sai cơ chế, và sửa định tuyến ngay trong lời dặn. Ưu: rẻ khi
     chạy. Nhược: 2b vô dụng theo định nghĩa.
   
   Chọn cách nào cũng thành v0.3 và phải chạy lại.
3. **v0.3**: thêm "không trả về thông tin/kết quả" vào `NOT_FOUND_PATTERN` (doc-19), và chấm tay
   doc-19 dưới 1a.

## Tệp

Thư mục này chứa `manifest.json`, `summary.json`, `task_results.jsonl` của 27 lần chạy v0.2, và
`events.jsonl` của các lần then chốt:
- r1 lạnh, r2 nóng;
- lần đo t0 nóng của B, C, D;
- lần lạnh của B, C, D.

Code của 1a, 2b và D, cùng bản báo cáo đầu (`8848e67`), **không** được gộp vào `main`. Chúng nằm trên nhánh
`wip/10-harness` làm hồ sơ; các mã commit nhắc trong báo cáo này trỏ vào nhánh đó.

`analysis.json` được tạo bằng `analyze.py`, phần so sánh nóng và 0.4. Bảng lạnh tính trực tiếp từ các
thư mục `*-cold` và `base-r1-cold`. Commit `64b2960` gác 1a lại để đo C. Lần lạnh của B, C, D được
chạy bằng cách checkout đúng commit của điều kiện, nên manifest ghi đúng commit đó.
