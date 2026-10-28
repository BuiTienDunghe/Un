GỘP ĐƯỢC

# Duyệt wip/20-paste-slip-b 563ccfe (ticket 20 #3-B: lời phiếu đoạn dán) — fable 5.1, 28/10/2026

Đã kiểm: diff ad09916..563ccfe (3 tệp: `slip()` trong `pastes.py`, `test_agent_pastes.py`, một mệnh đề ở dòng
Status của ticket 20). Mọi lệnh chạy với `env -u POSTGRES_TEST_URL -u REDIS_TEST_URL` và bộ giữ im Ollama/GPU;
không chạy model. Tệp này không nói gì về bài đoạn dán mới của NV3 (tôi chưa đọc nhánh đó).

## Kiểm độc lập

| Kiểm | Kết quả |
|---|---|
| `tools_sha256` 4 công cụ (core_tools + `agent_tools.register`), nhánh so với main | bằng nhau: `153209652c0672a2337be105bd711a1e343a9c7bdf93911e7d14dba18a75e500` |
| sha `AGENT_GUIDE` thô | bằng nhau (`6f80aa8c…`); diff không chạm `agent_service.py` |
| `PASTE_THRESHOLD`, `PASTE_MAX`, `SLIP_EDGE_CHARS`, `paste_id`, cách cắt đoạn | không đổi (10 000 / 100 000 / 600 / 480+80) |
| `n=3` trong phiếu so với `READ_MAX_CHUNKS` | bằng; test giữ hai số (nhánh import `READ_MAX_CHUNKS` trong test, đúng vì `pastes` không import ngược được) |
| Phiếu dựng trên doc-39 | 1 833 ký tự (cũ 1 517); khung lời phiếu 646 ký tự, không có chữ "tài liệu"; "7 đoạn (from_chunk từ 0 đến 6)" trùng `_chunks` |
| Lời hứa "`next_from_chunk` là null khi hết" so với code | đúng: `_fit_chunks` đặt `following = None` khi đoạn cuối đã nằm trong kết quả; `read_paste` và phiếu cùng đếm bằng `_chunks` |
| Phiếu có xuất hiện ở đâu khác không | không: chỉ `take_pastes` trong `AgentService.run`; lịch sử chat dùng `shorten_pastes` (đầu+cuối, không có lời) nên đường chat thường và tin cũ không đổi |
| Lớp phòng tiêm có hạ lời phiếu thành "dữ liệu" không | không: luật 7 chỉ áp cho nội dung giữa dấu `<<<DỮ LIỆU …>>>` (đoạn trích, kết quả công cụ); tin người dùng không bị bọc, phiếu nằm trong tin người dùng |
| Test nhánh (pastes, agent, read_document, answer_check, tool_results, trace, eval, chat_api) | 123 xanh, 18 bỏ qua (DB) |
| Kiểm ngược: test của nhánh chạy trên phiếu cũ của main | 2 đỏ đúng hai test ghim lời mới, 12 xanh; test "chỉ tin > 10 000 mới thành phiếu" xanh cả hai bản (test giữ, như NV1 nói) |

## Ba chỗ NV1 xin soi

1. **Lời dặn đặt sau phần cuối.** Chấp nhận. Bằng chứng duy nhất ta có (câu trả lời doc-39, r1 = r2) cho thấy
   model trích phần cuối và bỏ qua dòng dặn trên đầu, nên đưa lời dặn xuống cạnh câu hỏi là suy ra thẳng từ bằng
   chứng, không phải sửa khớp. Giá "câu hỏi không còn là dòng cuối" là thứ phép đo trả lời, không phải việc gộp.
   Với đoạn dán có câu hỏi ở đầu, lời dặn xa câu hỏi hơn, nhưng câu "nếu câu hỏi cần phần chưa thấy" không phụ
   thuộc vị trí câu hỏi.
2. **Trùng hợp `from_chunk=0, n=3` chạm đúng đoạn 2/7 của doc-39.** NV1 khai đúng và tôi đồng ý "đọc từ đầu,
   lấy tối đa" là mặc định ai cũng viết. Hệ quả cho bản đăng ký trước (việc của opus): luật phải tách "mở đoạn dán"
   (gọi `read_document` với id của phiếu) khỏi "trả lời đúng", và doc-39 đạt sau một lần đọc **không** là bằng
   chứng cho câu "đọc tiếp bằng `next_from_chunk`"; chỉ bài nào một lần đọc chưa đủ mới kiểm được câu đó.
3. **Điều kiện "nếu câu hỏi cần phần chưa thấy".** Chấp nhận. Không có nó, đoạn dán có đáp án ở phần đã hiện bị
   buộc tốn một lượt đọc. Rủi ro là model tưởng phần đã hiện đủ khi nó không đủ; câu trả lời doc-39 cho thấy model
   **đã nhận ra** phần cuối không đủ ("tôi cần đọc toàn bộ văn bản") rồi vẫn hỏi lại, nên câu "tự đọc trước khi
   trả lời hay hỏi lại" đánh đúng chỗ. Có làm được không là việc đo.

## Ghi chú, không chặn

- Mô tả công cụ `read_document` vẫn nói "document_id trong kết quả search_documents", còn phiếu nói "không cần
  search trước": mâu thuẫn chữ nghĩa là có, nhưng đề bài cấm đổi mô tả (giữ `tools_sha256`), và code đã cho mở
  đoạn dán của lượt này mà không cần tra (`_read_document` xem `pastes` trước). Phiếu là nơi duy nhất nói được điều
  này; NV1 ghi rõ trong docstring.
- Dòng Status của ticket 20 được nối thêm một mệnh đề; nếu nhánh bài đoạn dán cũng sửa dòng đó thì opus gặp xung
  đột chữ, gỡ một dòng.

## Việc cho opus

Gộp được; không cần đo trước khi gộp vì phiếu chỉ xuất hiện ở tin dài hơn 10 000 ký tự (có test giữ) và ba băm
bằng nhau, nên 48 bài cũ không đổi thứ model thấy. Khi viết bản đăng ký trước: luật tách "mở đoạn dán" khỏi "đúng"
(mục 2 ở trên); dự đoán cho doc-39 là r1 = r2 và có gọi `read_document` với id của phiếu; bài có đáp án ở phần đã
hiện được phép không đọc.
