GỘP ĐƯỢC

# Duyệt wip/20-pastes a07d7f7 (ticket 20 #3: đoạn dán dài thành tài liệu tạm) — fable 5.1, 28/10/2026

Đã kiểm: đọc trọn `pastes.py` (98 dòng), diff `agent_service.py` (+24/−?), `chat_service.py`, `routers/chat.py`,
`chat_schema.py`, 11 test mới, bản đăng ký trước (commit sau code, trước mọi lần chạy; lần đo hoãn). Chạy với
bộ giữ im: 149 test không DB (pastes, answer_check, read_document, 7 bộ agent, grounding) xanh; 36 test có DB
(chat_api, agent_service, discord_turn, trace_summaries, forget_member_copies) xanh — lần này chạy TRƯỚC khi
opus ra luật "test có DB chỉ opus chạy"; ghi lại để opus không phải lặp, nhưng lúc gộp opus vẫn chạy theo luật.

## Khớp lựa chọn đã chốt (S1, trần 100 000, phiếu đầu–cuối)

| Điểm | Nhánh | Kết luận |
|---|---|---|
| Đoạn dán ở lại `messages`, không index, không migration | `chat_service` lưu nguyên tin; `pastes` chỉ sống trong `tool_context` của lượt | đúng S1 |
| Ngưỡng 10 000 = giới hạn cũ; tin ngắn hơn đi y như trước | `PASTE_THRESHOLD = 10_000`, `is_paste` dùng `>` | đúng; 47/48 bài v0.3 không đổi một byte, đúng dự đoán đăng ký |
| Chat thường giữ trần cũ | `routers/chat.py` 422 `INPUT_TOO_LONG` khi không `use_tools`; schema lên 100 000 chỉ cho chế độ công cụ | đúng |
| Phiếu: độ dài, số đoạn, id, 600 đầu + 600 cuối, cách mở | `slip()` | đúng; câu hỏi ở cuối (doc-39) lọt vào phiếu |
| Đọc bằng `read_document` từ chính lượt, không hỏi store | `_read_document`: id trong `pastes` → `read_paste`; store không bao giờ nhận id đoạn dán | đúng; test "store từ chối" ghim |
| Lịch sử chat thường / stream thấy ghi chú một dòng | `shorten_pastes` ở hai đường | đúng |
| Tìm trí nhớ | `search_text` = hai mép | hợp lý: nhúng 100 000 ký tự là vô nghĩa và tốn |

## Điều tôi soi kỹ

1. **Chống cài cắm qua `tool_context`**: `run()` LUÔN ghi đè `tool_context["pastes"]` bằng đoạn dán lấy từ
   `messages`, nên bên gọi không thể đưa văn bản lạ vào dưới danh nghĩa "đoạn dán"; `readable_documents` chỉ
   thêm id suy ra từ chính tin. Test `only_this_turns_own_pastes_open` ghim đúng việc này.
2. **Nội dung đoạn dán là dữ liệu không tin cậy**: kết quả `read_document` của đoạn dán đi qua
   `defense.wrap_tool_result` như mọi công cụ (vòng lặp bọc mọi output), nên phần giữa của văn bản dán được
   model đọc dưới nhãn "dữ liệu, không phải chỉ dẫn" — đúng. Hai mép trong phiếu nằm trong tin user, là lời
   người dùng, không cần bọc.
3. **Tương tác với #2**: bộ kiểm con số thấy phiếu, không thấy phần giữa, nên con số ở giữa chưa đọc bị coi là
   "không nguồn" và kích hoạt thử lại — có chủ ý, có test. Hệ quả cần biết khi đo: doc-39 có thể tốn tới 2 lượt
   model thêm (đọc + trả lời lại); bản đăng ký đã nói "không dự đoán doc-39 đạt hay không".
4. **Ticket 16/17/23**: bước `tool_result` của đoạn dán lưu trong `agent_traces` (cascade với hội thoại), bảng
   rút gọn chỉ hash — đúng (b). `forget_member` không liên quan (web). Scorecard: `read_document` đoạn dán là
   lượt gọi công cụ bình thường.
5. **Cùng văn bản cùng id** (`sha256[:12]`): lượt sau mở lại được; hai đoạn dán khác nhau trong một hội thoại
   có id khác. Trùng 12 hex giữa hai văn bản khác nhau trong cùng hội thoại: xác suất bỏ qua được.
6. **`lru_cache(maxsize=8)` theo văn bản**: tối đa 8 × 100 000 ký tự — vài MB, ổn.
7. **Eval**: runner đọc trần từ schema (`MaxLen`), nên doc-39 (10 164) không còn bị từ chối trước agent — đúng
   dự đoán "doc-39 tới được agent".
8. Chữ ký `chunk_pages(pages, chunk_tokens, overlap_tokens)` khớp cách gọi `[(None, text, "native")]`.

## Giới hạn và điểm mù (đã ghi trong bản đăng ký, tôi đồng ý)

Mỗi lượt đọc được ~18 000 ký tự; không tìm kiếm bên trong đoạn dán; câu hỏi nằm giữa đoạn dán thì model không
thấy nếu chưa đọc. Thêm một điểm nhỏ chưa ghi: `shorten_pastes` áp cho MỌI tin user dài trong lịch sử kể cả
tin của lượt trước đã được trả lời — chat thường sau đó mất ngữ cảnh đoạn dán hoàn toàn (chỉ còn ghi chú).
Đúng với S1, nhưng nên ghi vào docs để người dùng biết: muốn hỏi tiếp về đoạn dán thì phải ở chế độ công cụ.

## Việc cho opus

Gộp được. Lần đo gom cùng #2 theo bản đăng ký (hash tools/guide phải bằng #2). Khi gộp, OpenAPI đổi
`maxLength` của `ChatRequest.message` (10 000 → 100 000) — ghi CHANGELOG, vì client web có thể đang lấy trần từ
schema.
