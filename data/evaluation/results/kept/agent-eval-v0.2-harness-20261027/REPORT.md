# Ticket 10 — nâng harness theo lỗi đo được, Agent Eval v0.2 (27/10/2026)

**Thăm dò, chưa đủ chứng minh thống kê.** Mỗi điều kiện có 40 bài, đo 1 lần ở nhiệt độ 0 (sau một lần
khởi động bỏ đi) và 3 lần ở nhiệt độ 0.4. Cách chấm được đăng ký trước khi chạy 1a và 2b, trong
Comments của ticket 10.

## Thật ra chuyện này là gì

Có hai loại sửa, và chúng cho hai loại kết quả.

Loại thứ nhất là sửa **khung chạy** (kiểm soát): khi kết quả công cụ quá dài thì bỏ bớt trọn từng mục
và nói rõ đã bỏ bao nhiêu, thay vì cắt ngang. Cách này đo được chắc chắn: model không còn nhận JSON
gãy, và đọc lịch sử chat thì giữ được tin mới nhất.

Loại thứ hai là sửa **lời dặn** cho model (chất lượng). Lời dặn 1a ("cứ tra tài liệu trước, đừng hỏi
xin phép") làm model chịu tra hơn hẳn. Nhưng nó cũng làm model quên nêu tên tệp ở vài bài, và kéo câu
hỏi về chuyện đã bàn trong Discord sang tìm trong tài liệu. Gợi ý 2b ("tài liệu không có, thử tìm lịch
sử chat") một mình thì không đủ, vì model lại hỏi xin phép thay vì tự tìm. **1a và 2b đi cùng nhau**
thì cả hai câu hỏi Discord được trả lời đúng ở mọi lần chạy. Hai bài đó vẫn bị chấm trượt, vì tiêu chí
của chúng cấm bước tìm tài liệu đầu tiên. Tổng điểm vì vậy gần như không đổi, nhưng **cách** model
mất điểm đã đổi: từ "không tra" sang "tra mà không nêu nguồn".

Cuối cùng, chuyện "lần chạy đầu khác các lần sau" đã được khoanh lại: nó đi cùng lần đầu tiên model gặp
một phần mở đầu prompt mới (nạp lại model là một trường hợp như vậy), chứ không do các model khác nằm
cạnh trên GPU.

## Điều kiện đo

| | |
|---|---|
| Nhánh | `wip/10-harness`; mỗi điều kiện có commit riêng, cây sạch, `verified: true` (probe) |
| Bộ bài | `agent-eval-v0.2`, sha256 `99b2e915…`; bộ chấm `agent-eval-grader-v0.2` |
| Model | `general-v0` = `qwen3.5:9b`, max_steps 3, tool_result_max_chars 2400, injection defense ON |
| Máy | PC-dungbt, RTX 5060 Ti 16 GB, Ollama 0.40.8; GPU riêng cho ticket 10 từ 19:42 đến 20:41 |
| Mốc A | `d434c82` = bộ bài v0.2 + cụm 3a + mô tả "mỗi tin tối đa 800 ký tự". **Mốc v0.2 = bộ bài v0.2 + 3a; tác dụng của 3a lên điểm chưa đo** |

## Lần chạy lạnh khác lần chạy nóng: nguyên nhân đã khoanh lại

| Lần | Điều kiện | Đạt | Trùng câu trả lời với lần nóng |
|---|---|---|---|
| r1 | Gỡ mọi model | 34/40 | 20/40 |
| r2, r3 | Nóng | 31/40 | 40/40 |
| r4 | Chỉ gỡ OCR + embedding | 31/40 | 40/40 |
| r5 | Nóng, seed 43 thay 42 | 31/40 | 40/40 |
| r6 | Chỉ gỡ model chính | 34/40 | 20/40 (trùng r1 40/40) |
| Khởi động B | Model vẫn nạp, lời dặn **mới** (1a) | 28/40 | 22/40 với lần đo B |
| Khởi động C, D | Model vẫn nạp, lời dặn **đã chạy trước đó** | 32, 31 | 40/40 với lần đo của chính nó |

- **Seed không có tác dụng ở nhiệt độ 0** (r5 = r2): nhiều seed ở nhiệt độ 0 chỉ là cùng một lần chạy
  lặp lại.
- Model OCR hay embedding nằm cạnh **không** phải nguyên nhân (r4 = r2).
- Nạp lại model chính tái tạo đúng lần lạnh (r6 = r1). Một lời dặn chưa từng chạy cũng làm lần đầu khác
  đi, dù model không bị nạp lại (khởi động B). Cả hai **khớp** với giả thuyết Ollama dùng lại phần đầu
  prompt đã xử lý; cơ chế chưa được chứng minh.
- Hệ quả: quy tắc "khởi động bỏ đi" phải áp dụng cho **mỗi biến thể prompt mới**, không chỉ sau khi
  nạp lại model. Ticket 09 cần biết điều này.

## Kết quả theo cách đã đăng ký trước

Mục tiêu của 1a là 5 bài trượt vì không gọi công cụ ở mốc A: doc-10, doc-22, doc-25, doc-30 và
stat-02. Mục tiêu của 2b là hist-07 và hist-03. Luật chồng đã kích hoạt: B làm mất 5 bài ngoài mục
tiêu, nhiều hơn 3 bài mục tiêu nó cứu được. Vì vậy 2b được đo trên A (điều kiện C). D = A + 1a + 2b
là phần **bổ sung**.

| Điều kiện | Mục tiêu 1a (t0 / 0.4) | Mục tiêu 2b ở 0.4: chấm / chấm tay | Ngoài mục tiêu ở t0: được / mất | Tổng t0 | Tổng 0.4 (TB) |
|---|---|---|---|---|---|
| A, mốc | 0/5 / 4/15 | 3/6 / 3/6 | — | 31 | 31, 29, 33 (31,0) |
| B = A + 1a | **3/5 / 8/15** | 0/6 / 0/6 | +2 / −5 | 31 | 28, 31, 27 (28,7) |
| C = A + 2b | 2/5 / 4/15 | 3/6 / 3/6 | +4 / −3 | 32 | 30, 32, 31 (31,0) |
| D = A + 1a + 2b (bổ sung) | **3/5 / 11/15** | 0/6 / **6/6** | +2 / −4 | 31 | 29, 30, 29 (29,3) |

Ở C, 2/5 mục tiêu của 1a đạt là nhờ đổi prompt gây lật (doc-10, stat-02 nằm ngoài mục tiêu của C).
Đây là sàn nhiễu: ở mốc A, chỉ đổi một dòng mô tả công cụ mà 5 bài không liên quan đã lật.

**Đọc từng điều kiện:**
- **1a (chất lượng)** cứu được bài "không tra". Ở 0.4, mục tiêu tăng từ 4/15 lên 8/15, và lên 11/15
  khi đi cùng 2b. doc-22 và doc-30 vẫn trượt ở t0. Cái giá: doc-26, doc-27, doc-28 trượt vì **thiếu
  tên tệp** khi trích nguồn (doc-27 còn thiếu bước tính 2 giờ). Ở 0.4 dưới D, doc-26 và doc-27 trượt
  cả 3/3 lần. Giả thuyết: lời dặn dài hơn làm câu "nêu tên tệp và số trang" kém nổi bật; chưa thử.
  hist-03 chuyển sang tìm tài liệu, đúng tác dụng phụ mà 2b nhắm tới.
- **2b một mình (chất lượng, nhưng cài ở harness)**: gợi ý đến đúng chỗ, nằm ngoài khối dữ liệu. Ở
  hist-07, model đáp lại "Bạn có muốn tôi tìm trong lịch sử tin nhắn không?", tức là hỏi xin phép, nên
  không cứu được bài nào. Tổng điểm như A.
- **1a + 2b**: hist-03 và hist-07 được trả lời **đúng ở 8/8 lượt** (t0 và 3 lần 0.4, đúng người nói,
  đúng thời gian), theo luồng tìm tài liệu → gợi ý → tìm lịch sử. Bộ chấm vẫn đánh trượt cả 8, vì
  tiêu chí của hai bài cấm gọi `search_documents`. Nếu đếm tay, D ở 0.4 là 31, 32, 31 (trung bình
  31,3).

Chi phí: token vào của một lượt chạy t0 là A 88 335, B 96 685, C 92 217, D 100 947 (+14% so với A),
do lời dặn dài hơn và có thêm lượt gọi công cụ. Độ trễ p50 không tăng (A 3,3 s, D 2,7 s).

Ghi chú khác: một câu trả lời ở 0.4 (D, hist-07) có lẫn chữ Trung Quốc ("安排在"). Bộ chấm bỏ sót một
câu đúng của doc-19 ("không trả về thông tin…"), sẽ sửa ở v0.3.

## Kiểm soát (KS) và chất lượng (CL)

| Loại | Thay đổi | Bằng chứng | Tác dụng lên điểm |
|---|---|---|---|
| KS | 3a: cắt theo từng mục, trả object khi tràn, mỗi tin tối đa 800 ký tự, mô tả công cụ nói rõ trần | 24 lần chạy v0.2: 748 kết quả công cụ, **0** lần cắt giữa JSON (v0.1: 6–7 lần mỗi lượt chạy), 85 lần bỏ bớt theo mục có ghi chú. Kiểm tất định bằng test | Chưa đo (theo quyết định) |
| CL | 1a: lời dặn "tra trước, đừng hỏi xin phép" | Bảng trên | Đổi cách mất điểm; tổng không tăng |
| CL | 2b: gợi ý khi tìm tài liệu rỗng trên Discord | Bảng trên | Một mình: không đổi. Cùng 1a: 2 bài Discord đúng, bị chấm trượt vì tiêu chí |

**Chưa làm, kèm lý do:** registry công cụ có schema, ngân sách token/thời gian, chuẩn hoá lỗi/thử lại,
tracing. Chưa có lỗi đo được nào đòi tới chúng:
- 716 lượt kiểm tham số có 2 lỗi (`limit=20` khi tìm theo từ khoá; agent tự kẹp lại).
- Ngân sách vòng gọi cạn 4 lần trên 24 lần chạy, đều ở doc-12. `max_steps` hiện có đã chặn.
- 0 lỗi chạy, 0 timeout.

## Cần chủ dự án hoặc điều phối chốt

1. **Ship thay đổi chất lượng nào**:
   - (a) Ship 1a + 2b (D) ngay. Ưu: lỗi lớn nhất ("không tra") giảm rõ (0.4: 4/15 → 11/15), câu hỏi
     Discord được trả lời đúng. Nhược: mất trích nguồn ở 3 bài; tổng điểm chấm máy thấp hơn A (29,3 so
     với 31,0), đếm tay thì ngang (31,3).
   - (b) Ship 2b một mình. Ưu: không hồi quy. Nhược: không cứu được bài nào.
   - (c) Chưa ship thay đổi chất lượng; thử 1a-v2 giữ câu trích nguồn nổi bật (sửa lời dặn), đo lại một
     điều kiện (khoảng 12 phút GPU). Ưu: không ship hồi quy đã biết. Nhược: chậm một vòng.
   - Ý kiến: (c). Hồi quy đến từ một nguyên nhân cụ thể, rẻ để thử, và D chưa thắng A về tổng điểm. Đây
     chỉ là ý kiến.
2. **Tiêu chí của hist-03 và hist-07** (v0.3): giữ "cấm `search_documents`" (câu hỏi về chat phải đi
   thẳng vào lịch sử), hay cho phép "tài liệu trước rồi lịch sử" khi câu trả lời đúng (khớp với thiết
   kế của 2b)? Đổi thì là đổi sau khi đã xem câu trả lời, phải ghi lại và chạy lại.
3. **v0.3**: thêm "không trả về thông tin/kết quả" vào `NOT_FOUND_PATTERN` (doc-19).

## Tệp

Thư mục này chứa `manifest.json`, `summary.json`, `task_results.jsonl` của 24 lần chạy v0.2, và
`events.jsonl` của 5 lần then chốt (r1 lạnh, r2 nóng, các lần đo t0 của B, C, D). `analysis.json` được
tạo bằng `analyze.py`. Lời dặn và gợi ý nằm ở các commit `44318e6` (1a), `0ecc927` (2b), `4beb9ba`
(D); `64b2960` gác 1a lại để đo C.
