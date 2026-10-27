# Ticket 10 — đo 1a-v2, Agent Eval v0.2 (27/10/2026, 22:31–22:39)

**Thăm dò: mỗi điều kiện một lần chạy lạnh, 40 bài.** Cách đo và luật quyết định được đăng ký trước
khi chạy (ticket 10, Comments 27/10 21:15 và 21:45). Đọc kèm `../agent-eval-v0.2-harness-20261027/REPORT.md`.

## Thật ra chuyện này là gì

Lời dặn 1a đầu tiên bảo model "cứ tra tài liệu trước". Nó cứu được những câu model từng trả lời theo
hiểu biết chung mà không tra, nhưng làm mất nhiều câu khác hơn, chủ yếu vì quên nói thông tin lấy từ tệp
nào. Bản 1a-v2 chỉ viết lại một câu trong lời dặn: giữ ý "cứ tra, đừng hỏi xin phép", và nhắc luôn nêu
tên tệp.

Bản mới giữ được phần lợi (vẫn cứu đúng những câu đó) và bớt hẳn phần hại so với bản đầu. Nhưng nó vẫn
chưa hơn việc không sửa gì: tổng điểm kém mốc một câu, và vẫn làm hỏng ba câu trong nhóm phải giữ nguyên,
trong khi luật chỉ cho hỏng một. Theo luật đã đăng ký: không đưa vào sản phẩm.

Thêm gợi ý 2b ("tài liệu không có thì xem lịch sử chat") lên trên bản mới thì model trả lời đúng một câu
hỏi Discord trước đó trả lời sai, nhưng bộ chấm vẫn đánh trượt câu đó, tổng điểm không đổi, nên cũng
không đưa vào.

## Điều kiện đo

| | |
|---|---|
| Thời gian | 27/10 22:31–22:39, **cùng lúc ticket 09 chạy** (stack heldout cổng 8200, `qwen3-embedding:0.6b` nạp trên cùng GPU), theo lệnh đổi lịch của opus |
| Quy trình | mỗi điều kiện: checkout đúng commit, gỡ `qwen3.5:9b` (không đụng model nhúng), chạy một lần ở nhiệt độ 0, seed 42, `--probe`; cây sạch, `verified: true` |
| Bộ bài, bộ chấm | `agent-eval-v0.2` sha256 `99b2e915…`; `agent-eval-grader-v0.2` |
| Điều kiện | A = `9aaa75d` (mốc v0.2); E = `5ed9d5a` (A + 1a-v2); F = `1434c6c` (E + 2b). Code E, F chỉ có trên nhánh `wip/10-1a-v2` |
| Mã băm lời dặn | A `6194cf0f…`, giống lần lạnh 19:43; E = F `e17ef119…`; B (1a đầu) `e469cb52…`. System prompt, ngữ cảnh Discord và mô tả công cụ giống hệt ở cả năm lần |
| Lệch so với đăng ký | đăng ký ghi "sáng 28/10, chạy nối tiếp với 09, không xen kẽ"; run-id là `v0.2-1a2-<X>-cold` thay vì `v0.2-<X>-cold-0328` |

## Áp luật

B là lần lạnh của 1a đầu (20:47 cùng ngày, thư mục v0.2), đưa vào để thấy hướng đi; luật không dùng nó.

| | A (mốc) | B (1a đầu) | E (1a-v2) | F (1a-v2 + 2b) |
|---|---:|---:|---:|---:|
| Tổng lạnh | 34/40 | 30 | 33 | 33 |
| Mục tiêu 1a đạt (doc-10, doc-22, doc-25, doc-30, stat-02) | 2/5 | 4/5 | 4/5 | 4/5 |
| Bài theo dõi bị mất so với A (7 bài) | — | 7 | 3 | 3 |
| Mất trích dẫn ở doc-26/27/28 | 0/3 | 3/3 | 1/3 | 1/3 |

Luật ship E:

| Điều kiện | Ngưỡng | E | Đạt |
|---|---|---|---|
| Tổng ≥ A | ≥ 34 | 33 | không |
| Mục tiêu ≥ A + 1 | ≥ 3 | 4 | có |
| Mất trong danh sách theo dõi | ≤ 1 | 3 (doc-17, doc-26, doc-27) | không |
| Mất trích dẫn ở doc-26/27/28 | ≤ 1 | 1 (doc-26) | có |

**Không ship E.**

**Không ship F.** Điều khoản F viết là "ship F *thay* E": nó chọn giữa hai bản khi E đã đủ điều kiện,
nên E trượt thì không áp. Đọc theo chữ thì F thoả cả hai vế (tổng F = E = 33; hist-07 đếm tay đúng mà
không mất bài nào so với E), nhưng F mang đúng bốn bài mất của E, nên áp bốn điều kiện của E lên F thì
trượt y hệt.

## Bài lật so với A

E và F lật đúng cùng các bài này. Cột đọc tay là bổ sung ngoài luật.

| Bài | E, F | Đọc tay |
|---|---|---|
| doc-30 | được | tra rồi trả lời theo tài liệu, nêu tên tệp (mục tiêu 1a) |
| stat-02 | được | gọi `system_status`, nêu đúng Qdrant hỏng (mục tiêu 1a) |
| doc-29 | được | nêu tên tệp, A thì thiếu; ngoài mọi danh sách |
| doc-17 | mất | hỏng thật: nói tài liệu "không có ngày cụ thể"; A trả đúng 31/3 |
| doc-26 | mất | thiếu tên tệp: đúng cái giá đã đăng ký |
| doc-27 | mất | nội dung đúng ("từ 8 giờ đến 10 giờ sáng"); trượt vì bộ chấm đòi chữ "2 tiếng". Lỗi bộ chấm, ghi cho v0.3 |
| hist-10 | mất | kiểu hỏng mới, ngoài mọi danh sách: lượt web, gọi `search_history` rồi tự diễn giải câu hỏi là về một trang web, không nói công cụ này không dùng được ở đây |

Tính doc-27 là đạt thì E bằng A (34), nhưng vẫn mất 2 bài theo dõi, quá ngưỡng 1: luật không đổi.
doc-22 vẫn không được tra, cả ở B lẫn E.

## 2b trên nền 1a-v2

| | E | F |
|---|---|---|
| hist-03 | đạt (`search_history`) | đạt, giống E |
| hist-07 | trượt: chỉ tra tài liệu, trả lời "không tìm thấy" | bộ chấm đánh trượt vì đã gọi `search_documents` trước; đếm tay đúng người đăng, giờ đăng và nội dung |

Tiêu chí cấm tra tài liệu trước ở hist-07 là lỗi đã ghi ở REPORT v0.2.

## Lặp lại

- A lúc 22:31 trùng từng chữ với A lạnh lúc 19:43 trên 40/40 câu trả lời, dù 09 đang nạp model nhúng
  trên cùng GPU. **Đã kiểm**: lặp qua 3 giờ, và khi có model khác cùng nạp. **Chưa kiểm**: qua khởi động
  lại Ollama (tiến trình chạy liên tục từ 22/10) và qua ngày.
- Cho ticket 16: E và F có prompt giống hệt ở mọi bài trừ lượt hist-07. Câu trả lời giống nhau tới
  hist-07, rồi khác ở cả 12 bài sau đó (không bài nào đổi đạt/trượt). B và D, khác nhau đúng chỗ đó, chỉ
  khác ở 2 bài hist. Vậy trong một lần chạy lạnh, một lượt khác đi có lúc kéo theo các bài sau, có lúc
  không; chưa rõ vì sao (lần này 09 chạy song song). So từng bài giữa hai điều kiện chỉ chắc cho các bài
  đứng trước chỗ khác đầu tiên.
- Đổi một câu lời dặn làm 38/40 câu trả lời đổi chữ. Với một lần chạy mỗi điều kiện, chênh 1 bài nằm
  trong mức xáo trộn đó: luật là ngưỡng cho một quyết định thăm dò, không phải phép thử thống kê.

## Các cách tiếp theo

| Cách | Ưu | Nhược |
|---|---|---|
| (a) Dừng hướng 1a, giữ A | không tốn gì, không rủi ro | 3/5 câu "không tra" vẫn trả lời theo hiểu biết chung |
| (b) Đo E thêm 3 lần ở 0.4, như đã làm cho 1a đầu | biết 4 bài mất là có hệ thống hay do một lần chạy; 0.4 là mức sản phẩm dùng | ~8 phút GPU mỗi lần; luật hiện tại không dựa trên 0.4, phải đăng ký luật mới trước khi chạy |
| (c) 1a-v3 nhắm hai lỗi còn lại (doc-17 bỏ mất con số, hist-10 gọi công cụ lịch sử ở lượt web) | hướng này có tiến bộ thật: mất 7 → 4, mất trích dẫn 3/3 → 1/3 | mỗi vòng sửa lời dặn đổi gần hết câu trả lời; 40 bài quá ít để tách tác dụng khỏi xáo trộn, dễ thành vá theo đề |
| (d) Sửa bộ chấm doc-27 (nhận "từ 8 đến 10 giờ") cho v0.3 | đúng với câu trả lời thật | độc lập với (a)–(c), không đổi quyết định hôm nay |

Ý kiến của Nhân viên 3: (a), và ghi (d) cho v0.3. Phần lợi của 1a là 2 bài trên 40, trong khi mỗi vòng
một lần chạy không tách được chênh 1–2 bài khỏi xáo trộn. Nếu hướng này vẫn cần cho M3/M4 thì làm (b)
trước (c).

## Tệp

`v0.2-1a2-{A,E,F}-cold/`: đủ bốn tệp mỗi lần chạy. `decide.py` tính lại `analysis.json` từ các lần chạy
này và hai lần của thư mục v0.2 (A lạnh 19:43, B lạnh).
