Ticket 20 #1 — thiết kế đọc dài theo handle (Nhân viên của Ún 1). Chưa code. Đọc trên main 1a846bd.

BẢN CHẤT
Hôm nay agent tra tài liệu thì chỉ được xem đầu mỗi đoạn, như đọc lướt dòng đầu của mỗi trang mục lục. Muốn đọc tiếp thì không có cách. #1 đưa cho agent một "dấu trang": kết quả tra ghi rõ đoạn nào của tài liệu nào, và hai công cụ mới cho agent mở đúng đoạn đó (hoặc các tin nhắn Discord quanh một tin) để đọc đủ. Agent chỉ phải đưa lại mã và vài con số. Cái giá là mỗi lần mở tốn một trong ba lượt công cụ, và chữ đọc vào chiếm chỗ trong trí nhớ ngắn của model.

SỐ ĐO LÀM ĐỔI THIẾT KẾ
| Đo | Số | Điều kiện |
|---|---|---|
| Độ dài một đoạn tài liệu thật | trung vị 1 680, max 2 429 ký tự; 59/70 đoạn dài hơn 400 | 70 đoạn trong retrieval.jsonl v0.2 (12 bài ghi từ index thật) |
| Agent thấy | 400 ký tự đầu, tức ~24% một đoạn trung vị | agent_service.py:418 |
| Một đoạn dài nhất so với trần kết quả công cụ | 2 429 > 2 400: một đoạn đã không vừa | models.yaml agent.tool_result_max_chars |
| Ký tự trên một token (Qwen, tiếng Việt + JSON) | trung vị 2,9 (1,9–3,1) | 14 bài một lượt công cụ, chênh tokens_in vòng 2 − vòng 1, lần chạy v0.2-16-B-cold; phần chênh gồm cả lời gọi công cụ, nên số token bị đếm dư (phía an toàn) |
| Vỏ một mục lịch sử, chưa có chữ (id 18–19 chữ số, link, giờ ISO, message_id) | 297 ký tự | đo bằng json.dumps một mục mẫu |
| Prompt vòng đầu | trung vị 993, max 1 476 token | cùng lần chạy, 40 bài |
| Cửa sổ | 16 384 token | model_versions.yaml |
| document_id | 36 ký tự (doc_ + 32 hex) | models.py new_id |

1. SCHEMA

search_documents — giữ nguyên tham số; mỗi mục thêm 3 trường:
  {"document_id": "doc_…", "chunk_index": 7, "filename", "page", "excerpt": <400 ký tự đầu>, "chars": 1680, "score"}
  "chars" = độ dài cả đoạn, để model biết excerpt bị cắt. Thêm ~60 ký tự/mục; 4 mục vẫn dưới 2 400.

read_document (mới)
  {"document_id": string (bắt buộc), "from_chunk": integer (mặc định 0), "n": integer (1–3, mặc định 2)}
  [+ "page": integer, nếu chọn P2 bên dưới; có page thì bỏ qua from_chunk, để model không mất một lượt vì lỗi]
  Trả: {"document_id", "filename", "total_chunks": 31, "chunks": [{"chunk_index", "page_start", "page_end", "content"}], "next_from_chunk": 9 | null}
  read_document TỰ xếp đoạn cho vừa trần: nó biết độ dài từng đoạn, lấy lần lượt cho tới khi đoạn sau không vừa, rồi đặt next_from_chunk = đoạn đầu tiên chưa lấy. _dump chỉ là lưới an toàn: kết quả là dict nên _dump không bỏ được từng mục, và cũng không biết next_from_chunk.
  from_chunk ≥ total_chunks → {"result": "đã hết tài liệu", "total_chunks": N} (một kết quả, không phải lỗi).

search_history — mỗi mục thêm "message_id" (snowflake). Hôm nay id chỉ nằm trong "link", model phải tự tách.

read_messages_around (mới, chỉ Discord)
  {"message_id": string (bắt buộc), "before": integer (0–10, mặc định 5), "after": integer (0–10, mặc định 5)}
  Trả: danh sách mục CÙNG HÌNH với search_history (speaker, author_id, is_bot, sent_at, message, link, message_id) theo thứ tự thời gian, mục gốc có "anchor": true. Cùng kênh/thread với tin gốc, bỏ tin đã xoá.
  Cùng hình là có chủ ý: forget_member (ticket 17) che được nó bằng đúng hàm đang che search_history.

Lỗi (theo mã của ticket 16):
  read_document, document_id lạ hoặc không được phép đọc → BAD_ARGUMENTS "document_id này không có trong kết quả search_documents của lượt này. Dùng đúng document_id trong kết quả tra; chưa tra thì gọi search_documents trước." Không phân biệt "không có" với "không được đọc", để công cụ không thành máy dò xem id nào tồn tại.
  read_messages_around ở web → TOOL_UNAVAILABLE_HERE, cùng câu với search_history.
  message_id không có trong server này → BAD_ARGUMENTS "Không có tin này trong server đang trò chuyện; dùng message_id trong kết quả search_history."

2. ĐƯỜNG LẤY DỮ LIỆU
Protocol mới cho AgentService, tham số tuỳ chọn (None → TOOL_UNAVAILABLE_HERE), nên các chỗ dựng AgentService và test hiện có không đổi:
  class DocumentReader(Protocol):
      def read_chunks(self, document_id: str, from_chunk: int, n: int) -> dict | None: ...
      def chunks_on_page(self, document_id: str, page: int, n: int) -> dict | None: ...   # chỉ khi chọn P2
  None = không có bản đang active (đã xoá, chưa index).
  Bản thật: thêm read_chunks vào ChunkInspectionService. Service này đã đọc đúng đoạn của bản active mà retriever index (list_chunks, :53), nhưng read_chunks bỏ phần join feedback. main.py truyền app.state.chunk_inspection_service.
HistoryBackend thêm:
  def around(self, *, guild_id: str, message_id: str, before: int, after: int) -> list[object] | None: ...
  Bản thật trong DiscordHistoryService. Tin gốc phải có guild_id = guild của phiên. Hàng xóm cùng guild, channel_id và thread_id; sắp theo (sent_at, id); bỏ deleted_at và content NULL. Có sẵn index ix_discord_channel_messages_guild_channel_sent.
Guild vẫn lấy từ tool_context, không bao giờ từ model.

3. GIỚI HẠN KẾT QUẢ
| Công cụ | Trần mỗi mục | Trần cả kết quả | Tràn thì bỏ |
|---|---|---|---|
| search_documents | excerpt 400 (giữ nguyên) | 2 400 (giữ nguyên) | mục xếp cuối (3a) |
| read_document | 2 400 / đoạn (≈ mọi đoạn đo được) | 6 000 (đề xuất, xem L1–L3) | đoạn cuối; next_from_chunk trỏ vào đoạn đầu tiên bị bỏ |
| search_history | 800 / tin (giữ nguyên) | 2 400 | như hôm nay |
| read_messages_around | 800 / tin | 6 000, dùng chung trần đọc với read_document (xem R1/R2) | tin XA tin gốc nhất, bỏ xen kẽ hai đầu (chế độ drop mới "edges" của _dump; kết quả là list nên _dump bỏ được từng mục); tin gốc không bao giờ bị bỏ |
Cắt vẫn theo cả mục với hình {"omitted","note","items"} của 3a. Riêng read_document thì note chỉ cho model: gọi lại với from_chunk = next_from_chunk.
Trần đọc là một con số riêng trong models.yaml (agent.read_result_max_chars), dùng cho cả hai công cụ đọc; trần chung 2 400 không đổi.
Vì sao read_messages_around không dùng được 2 400: vỏ mỗi mục đã 297 ký tự. Mặc định 5 + 1 + 5 = 11 mục là ~3 300 ký tự trước khi có chữ nào; với tin 80 ký tự là ~4 150. Ở 2 400, mặc định luôn tràn; muốn vừa thì chỉ được 2 + 1 + 2.

4. QUYỀN ĐỌC
Sự thật hôm nay (đính chính tiền đề "web có owner"): bảng documents KHÔNG có cột chủ sở hữu. Chỉ conversations và research_projects có owner_user_id. search_documents tra toàn bộ corpus đã index (repositories.py:205 active_versions không lọc gì). Vậy ở web, ai chat được với agent thì đọc được mọi tài liệu, kể cả tài liệu của dự án Nghiên cứu của người khác. Đây là chuyện có từ trước, không do #1.
Discord: cả vòng agent chỉ chạy ở guild nằm trong discord_agent_tools_guild_allowlist (mặc định rỗng = không guild nào), settings.py:93. Ngoài danh sách thì không có công cụ nào.
Đề xuất cho #1, không mở thêm đường lộ nào:
  - read_document: xem A1/A2 bên dưới.
  - read_messages_around: tin gốc phải thuộc guild của phiên; hàng xóm cùng kênh. Không mở rộng gì, vì search_history đã đọc được mọi kênh được nghe của guild.

5. HỢP ĐỒNG FIXTURE CHO agent_eval (Nhân viên 3 viết v0.3 theo đây)
- Tệp mới documents.jsonl, đưa vào DATA_FILES (tính vào hash). Mỗi dòng là một tài liệu ĐẦY ĐỦ:
  {"document_id": "doc_…", "filename": "…", "chunks": [{"chunk_index": 0, "page_start": 1, "page_end": 1, "content": "…"}]}
  chunk_index liên tục từ 0, đúng thứ tự.
- retrieval.jsonl: đoạn nào muốn đọc được thì phải có document_id + chunk_index, và content phải TRÙNG đoạn tương ứng trong documents.jsonl. load_dataset từ chối nếu lệch. Đoạn viết tay không có document_id thì đọc vào sẽ ra BAD_ARGUMENTS; điều đó hợp lệ.
- Fake mới FixtureDocuments(documents.jsonl) cài DocumentReader. FixtureHistory thêm around() đúng ngữ nghĩa bản thật (cùng guild, cùng channel_id, theo sent_at).
- Bản ghi đoạn thật: recorder lấy cả tài liệu qua GET /documents/{id}/chunks (chỉ đọc) cho mọi document_id đã gặp. Kèm cờ "answer_in_preview" (400) và "answer_in_document".
- dataset.json, server giả: id tin là duy nhất. Bài đọc quanh cần kênh có ≥ 11 tin quanh tin gốc, và câu trả lời phải nằm ở tin hàng xóm KHÔNG khớp từ khoá truy vấn, nếu không thì search_history một mình đã đủ. Hôm nay server giả có 18 tin, dài nhất 110 ký tự: chưa đủ.
- Mỗi mục search_history có thêm message_id, nên mọi bài hist đổi đầu ra. v0.3 là mốc mới, đằng nào cũng phải chạy lại.
- Các loại bài đọc dài:
  L-a: đáp án nằm trong đoạn search trả về, sau ký tự 400 → cần read_document đúng đoạn đó.
  L-b: đáp án ở đoạn kề mà search không trả về → from_chunk = k±1.
  L-c (chỉ khi chọn P2): câu hỏi nêu số trang.
  H-a: đáp án ở tin kề một tin mà search_history tìm thấy.
  Bài đối chứng: đáp án nằm trong 400 ký tự đầu. Bài này bắt lỗi agent đọc thừa (max_tool_calls).
  corpus_source ghi thêm char_offset.
- Bộ chấm: args "equals" so đúng kiểu (3 ≠ "3"). Ràng buộc số nên dùng regex hoặc chuẩn hoá kiểu trong grader.

6. CHỖ CÓ LỰA CHỌN THẬT (quyết định của chủ dự án; tôi ghi chỗ mình nghiêng, đó chỉ là ý kiến)

Dạng handle
  H1 — mã thật (document_id 36 ký tự, message_id snowflake).
    Ưu: đúng ý điều phối; không thêm trạng thái; trace dễ đọc.
    Nhược: model 9B phải chép đúng 32 ký tự hex; chép sai thì tốn một lượt để thử lại, mà chỉ có 3 lượt.
  H2 — bí danh ngắn theo lượt ("D1", "M3"), AgentService giữ bảng ánh xạ trong lượt.
    Ưu: gần như không chép sai; ngắn hơn; chỉ mở được cái đã được cho xem.
    Nhược: thêm trạng thái theo lượt; bài v0.3 phải viết args theo bí danh.
  Tôi nghiêng H1: đơn giản hơn, và v0.3 đo được ngay tỉ lệ BAD_ARGUMENTS trên read_document. Tỉ lệ đó cao thì mới chuyển H2. Chưa đo model chép sai bao nhiêu.

Ai đọc được tài liệu nào
  A1 — mọi tài liệu đã index.
    Ưu: đơn giản; đọc thẳng được tài liệu người dùng nêu tên.
    Nhược: tài liệu tạm của #3 (mỗi hội thoại một tài liệu) sẽ đọc chéo được nếu lộ id.
  A2 — chỉ tài liệu mà search_documents đã trả về TRONG LƯỢT NÀY, cộng tài liệu tạm của lượt (#3 đưa qua tool_context).
    Ưu: không mở đường lộ mới; #3 cắm vào sẵn.
    Nhược: luôn phải tra trước rồi mới đọc, tốn một lượt.
  Tôi nghiêng A2: #3 cần đúng ranh giới này, và vì kết quả công cụ không sang lượt sau (messages chỉ lưu user/assistant), A2 không mất gì so với A1 trong một hội thoại.

Đọc theo trang
  P1 — không có trang; chỉ theo đoạn.
    Ưu: bề mặt nhỏ nhất.
    Nhược: câu "trang 12 nói gì" phải tra trước.
  P2 — tham số "page" chọn các đoạn có page_start ≤ trang ≤ page_end.
    Ưu: cùng đầu ra, không thêm đường dữ liệu, ~20 dòng.
    Nhược: một đoạn có thể vắt sang trang khác.
  P3 — chữ cả trang từ bảng document_pages.selected_text.
    Ưu: đúng chữ đã index, có cả trang OCR; research_service.py:893 đã đọc kiểu này.
    Nhược: đầu ra hình khác; một trang có thể dài hơn trần.
  P4 — lớp chữ PDF (routers/documents.py:144, page_words).
    Nhược: chỉ PDF, chỉ chữ gốc (trang OCR ra rỗng), cần tệp gốc còn, trả từ kèm toạ độ. Tôi không đề xuất cách này.
  Tôi nghiêng P2. Nếu muốn #1 nhỏ nhất thì P1 cũng hợp lý.

Trần read_document (ước tính theo 2,9 ký tự/token; thời gian xử lý prompt dài chưa đo)
  L1 — 2 400 như mọi công cụ.
    Nhược: chỉ vừa ~1 đoạn mỗi lần, nên đọc 3 đoạn là hết cả 3 lượt.
  L2 — 6 000.
    Ưu: 3 lần đọc ≈ 6,2k token, cộng prompt tối đa ≈ 7,7k, còn nửa cửa sổ.
    Nhược: prompt dài hơn, model dễ "lạc giữa" (chưa đo trên Qwen).
  L3 — 12 000.
    Nhược: 3 lần ≈ 12,4k + 1,5k ≈ 14k, sát 16k. Ollama cắt ĐẦU prompt khi tràn (hành vi đã biết, chưa kiểm trên bản đang chạy), tức mất lời dặn hệ thống.
  Tôi nghiêng L2.

Trần cho read_messages_around
  R1 — dùng chung trần đọc 6 000, mặc định 5/5.
    Ưu: 11 tin ngắn vừa một lần đọc.
    Nhược: prompt dài hơn.
  R2 — giữ 2 400, mặc định 2/2.
    Ưu: không đổi trần.
    Nhược: chỉ thấy 2 tin mỗi phía, nên hội thoại dài phải gọi lại, tốn lượt.
  Tôi nghiêng R1.

7. TỔ CHỨC CODE KHI LÊN 5 CÔNG CỤ (điều phối hỏi; agent_service.py 466 dòng, 12 file import nó)
(a) Giữ một file, thêm nhánh if.
  Ưu: diff nhỏ nhất, không dời gì.
  Nhược: _run_tool lên ~5 nhánh, ~200 dòng một hàm. Trần riêng mỗi công cụ và chế độ bỏ mục rải rác trong nhánh. #2–#4 cùng đụng một hàm, nên xung đột merge nối tiếp.
  Chi phí: 0 ngoài #1.
(b) Registry tối thiểu trong cùng file: mỗi công cụ là một mục {schema, hàm xử lý, trần kết quả, chế độ bỏ mục}; _run_tool chỉ còn tra bảng rồi gọi.
  Ưu: trần riêng có chỗ tự nhiên; thêm công cụ = thêm một mục; AGENT_TOOLS/TOOL_NAMES/_DECLARED sinh từ bảng như hôm nay; importer không đổi.
  Nhược: vẫn một file ~600 dòng; chưa tách được việc song song theo file.
  Chi phí: ~nửa ngày. Hành vi không đổi, kiểm bằng các test agent hiện có (tool_results, tool_errors, turn_budget, trace_summaries).
(c) Gói app/agent/: loop.py (vòng lặp + ngân sách), errors.py, results.py (_dump/_clip), registry.py, tools/ mỗi công cụ một file. app/services/agent_service.py còn lại làm lớp re-export, để 12 importer khỏi sửa (một test import cả _clip). Commit đầu chỉ dời code.
  Ưu: mỗi công cụ test riêng; nhiều người làm song song không đụng nhau.
  Nhược: diff lớn nhất; giữ lớp re-export là nợ; tốn duyệt.
  Chi phí: ~1 ngày + một lần Agent Eval lạnh cần GPU. Việc kiểm "40/40 trùng câu trả lời" khả thi: ticket 16 bước 5 ở temperature 0, seed 42 đã ra trùng từng chữ ở mọi bài có đầu ra công cụ không đổi.
Lựa chọn đi kèm, độc lập với (a)/(b)/(c): khai báo công cụ theo nơi trò chuyện.
  D1 — như hôm nay, web cũng thấy công cụ Discord.
  D2 — chỉ khai báo search_history/read_messages_around khi tool_context có guild.
    Ưu: bài học hist-10 (model hỏi lại "server nào?") không còn chỗ xảy ra.
    Nhược: prompt web đổi, nên các bài web phải đo lại.
  Với (b), D2 chỉ là một dòng lọc bảng; với (a) thì phải rẽ nhánh khi dựng AGENT_TOOLS.
Tôi nghiêng (b) làm commit đầu của #1. Lý do: công cụ thứ 4–5 là đúng điều kiện chủ dự án đặt, và trần riêng mỗi công cụ cần một chỗ ngay bây giờ. (c) đáng làm khi có người thứ hai sửa công cụ song song; hiện #2–#4 do một người làm nối tiếp.

8. HỆ QUẢ Ở CHỖ KHÁC
- forget_member (ticket 17): _copies chỉ che tool_result của search_history. Kết quả read_messages_around chứa lời thành viên nên phải che cùng cách. Việc này nằm trong commit code của #1, kèm test. read_document không chứa lời thành viên.
- Prompt đổi (thêm 2 công cụ, guide nói đọc tiếp bằng read_document): số v0.2 không mang sang được. Ticket 10 cho thấy đổi lời dặn xáo 38/40 câu, nên so sánh trước/sau phải làm trên v0.3, đăng ký trước.
- Trace không nội dung: arguments_shape tự xử lý công cụ mới qua _DECLARED (chuỗi → "str:N", số giữ nguyên).
- #2 (kiểm câu trả lời) có lợi: chữ đã đọc đủ thì việc đối chiếu trích dẫn có cơ sở hơn so với 400 ký tự.
