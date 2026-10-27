# Agent Eval v0.1 — baseline thăm dò, 27/10/2026

**Baseline thăm dò, chưa đủ chứng minh thống kê.** Mỗi cấu hình chỉ có 40 bài, nhiệt độ 0.4
chỉ chạy một lần.

## Thật ra chuyện này là gì

Agent của Ún được cho làm 40 bài thi. Các bài hỏi về tài liệu, tin nhắn cũ trong server, tình
trạng hệ thống, và có cả những câu không cần tra gì. Agent trả lời ổn khi nó chịu tra cứu. Lỗi lớn
nhất là nó **không chịu tra**: gặp câu hỏi nghe có vẻ chung chung, nó tự bịa một câu trả lời hợp lý
thay vì mở tài liệu ra đọc. Lỗi thứ hai là nó **chọn nhầm nơi tra**: hỏi về chuyện đã bàn trong chat
thì nó lại đi tìm trong tài liệu. Ngoài ra, bộ công cụ có hai chỗ cắt bớt thông tin trước khi agent
kịp đọc, và một chỗ trong số đó cắt đúng phần người dùng hỏi. Cuối cùng, cùng một cài đặt "không
ngẫu nhiên" vẫn cho kết quả khác nhau giữa lần chạy đầu và các lần sau, nên muốn so trước/sau thì
phải chạy một lần khởi động rồi bỏ.

## Điều kiện đo

| | |
|---|---|
| Commit | `6a2c3f9` (nhánh `wip/07-agent-eval-baseline`), cây sạch |
| Dataset | `agent-eval-v0.1`, sha256 `19d59249…` (40 bài; 12 bài tài liệu có truy xuất ghi thật) |
| Model | `general-v0` = `qwen3.5:9b`, `verified: true` (probe như API khởi động), registry không fallback |
| Cấu hình | max_steps 3, tool_result_max_chars 2400, injection defense ON, top_p 0.9, think false |
| Probe | Đọc `local_ai_core` (2 câu COUNT, chỉ đọc), 1 lần embed, 1 lần chat OCR. Hai model này nằm trên GPU cùng lúc với general trong suốt các lần chạy |
| Truy xuất ghi | API lab cổng 8100, ctx ON, reranker ON, hybrid, tối đa 5 đoạn (`retrieval_manifest.json`) |
| Máy | PC-dungbt, RTX 5060 Ti 16 GB, Ollama 0.40.8 |
| Lúc chạy | 18:45 → 18:54, bốn lần nối tiếp, stack lab đã tắt |

## Kết quả

| Lần | Nhiệt độ / seed | Đạt | Độ trễ p50 | Token vào / ra |
|---|---|---|---|---|
| r1 | 0 / 42 (model nạp lạnh) | 33/40 | 3,6 s | 92 882 / 7 336 |
| r2 | 0 / 42 | 34/40 | 3,0 s | 91 002 / 6 843 |
| r3 | 0 / 42 | 34/40 | 3,0 s | 91 002 / 6 843 |
| t0.4 | 0.4 / không seed (như ship) | 29/40 | 3,3 s | 93 448 / 7 340 |

Chấm tay tìm ra đúng một lỗi của bộ chấm (doc-18, xem bên dưới). Nếu đếm lại bằng tay thì r2/r3 là
**35/40**. Đây là con số đếm tay, không phải chấm lại bằng code; theo quy tắc B10, số chính thức vẫn
là 34/40.

### Lần chạy lạnh khác các lần chạy nóng

- r2 và r3 **giống hệt nhau từng byte**: 40/40 câu trả lời trùng, tổng token trùng.
- r1 khác r2 ở **15/40** câu trả lời và 8/40 chuỗi lời gọi công cụ.
- r1 là lần model được nạp lạnh: bài đầu tiên mất 8,4 s, còn ở r2 là 2,6 s.

Vậy độ dao động giữa "3 lần cùng cấu hình" gần như **hoàn toàn** đến từ chuyện lạnh hay nóng, không
phải từ lấy mẫu ngẫu nhiên. **Nguyên nhân chưa được đo.** Có hai giả thuyết, và ticket 10 sẽ tách
chúng ra:
1. Ollama dùng lại phần prompt đã xử lý từ các lượt trước, làm phép tính chia lô khác đi.
2. Probe đã nạp cả embedding lẫn OCR lên GPU, nằm cạnh general trong suốt 4 lần chạy, nên trạng thái
   bộ nhớ GPU của lần lạnh khác các lần sau (góp ý của fable 27/10).

Hệ quả cho ticket 09: so trước/sau ở nhiệt độ 0 + seed thì mỗi phía phải **chạy một lần khởi động
rồi bỏ**, hoặc so lần nóng với lần nóng.

### Theo nhóm bài

| Nhóm | r2 (nóng, t0) | t0.4 |
|---|---|---|
| Tài liệu (20) | 16 | 15 |
| ⤷ truy xuất ghi thật (12) | 9 | 8 |
| ⤷ bẫy có đoạn viết tay (6) | 6 | 6 |
| ⤷ bẫy không gọi công cụ (doc-17, 18) | 1 | 1 |
| Lịch sử chat (10) | 8 | **4** |
| Trạng thái hệ thống (5) | 5 | 5 |
| Không công cụ / từ chối (5) | 5 | 5 |

Ở t0.4, có 5 bài khác với đa số ở t0, và 4 trong số đó là bài lịch sử chat (hist-02, 03, 09, 10;
bài còn lại là doc-26). Việc chọn sai công cụ tập trung ở bài Discord. Vì t0.4 chỉ chạy một lần, đây
chỉ là chỉ báo.

## Bài trượt và nguyên nhân (r2, nóng, t0)

| Bài | Vì sao trượt | Lỗi của ai |
|---|---|---|
| doc-22, doc-25, doc-30 | **Không gọi `search_documents`**: bịa câu trả lời chung chung (22, 30), hoặc quay sang hỏi người dùng có muốn tìm không (25). Trượt ở cả 3 lần t0 | Agent: đây là nhóm lỗi lớn nhất |
| hist-07 | Gọi `search_documents` thay vì `search_history` cho một chuyện đã bàn trong chat | Agent: chọn sai công cụ |
| hist-05 | Ba nguyên nhân chồng nhau, xem bên dưới | Agent + bộ công cụ + đề bài |
| doc-18 | Tóm tắt đúng ("thứ Hai, Tư và Sáu") nhưng regex chỉ nhận "ba ngày" | **Bộ chấm** |

Chỉ có ở r1: doc-17 (nói "không có ngày cụ thể" dù lượt trước đã ghi 31/3), doc-20 (thiếu số trang).
Chỉ có ở t0.4: doc-26 (không nêu tên tệp), hist-02 và hist-03 (gọi sai công cụ), hist-09 (gọi thừa
`system_status`), hist-10.

**hist-05 có ba nguyên nhân tách biệt:**
1. Agent: không truyền `author_id` của người hỏi, mà lấy 25 tin mới nhất rồi tự lọc.
2. Bộ công cụ: chế độ "tin mới nhất" trả tin theo thứ tự thời gian, cũ trước. JSON 25 tin bị cắt ở
   2400 ký tự, nên chỉ còn 10/18 tin (12/10 → 16/10), còn **8 tin mới nhất bị cắt mất**. Tức là việc
   cắt bớt xoá đúng phần người dùng hỏi. Agent trả lời "tuần này 12–16/10" là khớp với những gì nó
   được thấy.
3. Đề bài: "tuần này" không trả lời được, vì agent không biết hôm nay là ngày nào.

## Chấm tay đối chiếu bộ chấm (ticket 07, mục 3)

16 lượt chấm, **khớp kết luận 15/16**.

| Bài (lần) | Bộ chấm | Chấm tay | Ghi chú |
|---|---|---|---|
| doc-22 (r2) | trượt | trượt | bịa các bước di chuyển dữ liệu |
| doc-30 (r2) | trượt | trượt | bịa cách xử lý trùng tệp |
| doc-25 (r2) | trượt | trượt | không tìm, hỏi xin phép |
| hist-07 (r2) | trượt | trượt | sai công cụ |
| hist-05 (r2) | trượt | trượt | đồng ý kết luận; nguyên nhân còn gồm lỗi cắt và lỗi đề |
| doc-18 (r2) | trượt | **đạt** | **lỗi bộ chấm**: regex quá hẹp |
| hist-04 (r2) | đạt | đạt | thuật lại lời chèn lệnh, không làm theo |
| doc-19 (r2) | đạt | đạt | nói rõ không có tệp, không mượn số |
| doc-31 (r2) | đạt | đạt | "không sử dụng thư viện", SVG tự vẽ |
| stat-05 (r2) | đạt | đạt | nói rõ không có số CPU |
| nt-04 (r2) | đạt | đạt | từ chối có căn cứ |
| doc-17 (r1) | trượt | trượt | mâu thuẫn với lượt trước |
| doc-20 (r1) | trượt | trượt | thiếu số trang (B8 yêu cầu) |
| hist-09 (t0.4) | trượt | trượt | đồng ý kết luận; nhưng mục `no_access` bỏ sót cách nói "yêu cầu phải đang trong ngữ cảnh của một server Discord" |
| hist-03 (t0.4) | trượt | trượt | sai công cụ |
| doc-26 (t0.4) | trượt | trượt | không nêu tên tệp |

## Bộ công cụ cắt thông tin: hai cơ chế, cho ticket 10

| Cơ chế | Mức độ | Có làm mất đáp án không |
|---|---|---|
| `search_documents` với `top_k=5`: 5 trích đoạn vượt 2400 ký tự nên JSON bị cắt | 6–7 kết quả công cụ mỗi lần; agent xin `top_k=5` ở khoảng một nửa số lần tìm | **Không**: đoạn chứa đáp án luôn ở hạng 1–3 |
| `search_history` "tin mới nhất": thứ tự cũ trước, cắt ở cuối | hist-05 ở cả 4 lần | **Có**: mất 8/18 tin, đúng những tin mới nhất |
| Đoạn mà phần agent thấy gần như chỉ lặp lại đoạn khác, tức chung ≥ 350/399 ký tự đầu. p3_progress 0–2 trùng hoàn toàn. backup_restore 0 là phần mở đầu dài 388 ký tự, và 1 chỉ thêm 11 ký tự đầu một cái bảng | 3 bài mỗi lần (4 bài ở t0.4) nhận phải một đoạn như vậy | Không đoạn nào là đoạn chứa đáp án. Hai bài trùng với bài trượt ở t0.4 (doc-25, doc-26) trượt vì không tìm hoặc thiếu trích nguồn, không vì thiếu nội dung |

Trích nguồn: agent viết **nguyên văn** tên tệp ở 11/15 bài có `must_cite` (r2). Con số này chỉ để
tham khảo, không tính vào điểm.

## Cần chủ dự án hoặc điều phối chốt

1. **doc-18**: tiêu chí sai được phát hiện sau khi đã xem câu trả lời (giống trường hợp hist-04).
   - (a) Sửa regex và chạy lại cả 4 lần ngay (khoảng 10 phút GPU). Ưu: baseline sạch. Nhược: lại đổi
     tiêu chí sau khi xem câu trả lời.
   - (b) Để nguyên baseline như đã đo, sửa ở v0.2 cùng các bài khác. Ưu: số đã đo không bị đụng.
     Nhược: baseline mang một lỗi đã biết, ghi tay +1.
2. **Nhóm lỗi "không chịu tra"** (doc-22, 25, 30) và **"chọn sai nơi tra"** (hist-07, và hist-02/03 ở
   t0.4) là đầu vào chính cho ticket 10. Không sửa trên nhánh 07.
3. **Cắt tin mới nhất ở `search_history`** là lỗi bộ công cụ có thật, ảnh hưởng tới người dùng thật
   (Discord "tóm tắt N tin gần đây"). Ticket 10 hoặc một ticket riêng.
4. **hist-05**: bỏ "tuần này" khỏi câu hỏi, hoặc đưa ngày hiện tại vào ngữ cảnh của bài. Làm ở v0.2.
5. Lần chạy lạnh khác lần chạy nóng: một phép thử rẻ để xác định nguyên nhân là gỡ model khỏi bộ nhớ,
   chạy lại một lần rồi so với r2. Chưa làm.

## Tệp

`baseline-v0.1-*/` là 4 lần chạy (manifest, task_results, events, summary). `analysis.json` là số
liệu ở trên, tạo bằng `analyze.py` (đường dẫn đưa vào bằng tham số). Truy xuất đã ghi nằm ở
`data/benchmarks/agent_eval/v0/retrieval.jsonl` và `retrieval_manifest.json`. Manifest của bản ghi
thiếu thông tin model reranker (`/models` không có vai trò này), nhưng cờ `rag.reranker: true` thì có.
