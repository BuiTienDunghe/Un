GỘP ĐƯỢC (với một điều cần chủ dự án biết: (b) đổi phiếu rộng hơn chữ nghĩa gói đã duyệt; tôi đã báo, chủ dự án bác thì đổi lại trước khi đăng ký)

# Duyệt wip/20-paste-search c270ded (ticket 20 #3-D 3': search_documents tìm trong đoạn dán) — fable 5.1, 28/10/2026

Đã kiểm: diff ed210e4..c270ded, hai commit f497da6 + c270ded (3 tệp: `agent_service.py` +24/−1 trong `_search_documents`,
`pastes.py` +121 gồm `search_pastes`, `_unseen`, `slip()`; `test_agent_pastes.py` +160/−14). Mọi lệnh chạy với bộ giữ im;
không chạy model. Tệp này không nói gì về bài mới của NV3.

## Kiểm độc lập

| Kiểm | Kết quả |
|---|---|
| Schema công cụ và lời dặn | `tools_sha256` `153209652c06…`, `AGENT_GUIDE` thô `6f80aa8ca420…`, bằng ed210e4: đổi chỉ ở kết quả công cụ và phiếu |
| Không ảnh hưởng bài không có đoạn dán | `search_pastes({}, …)` trả rỗng; nhánh "không tìm thấy" chỉ khi cả hai rỗng; test "without a paste search_documents answers exactly as before" xanh. Lần chạy đủ 56 bài trong bản đăng ký sẽ chứng minh 47 bài khác trùng nguyên |
| ReplayRetrieval của eval | không đổi: gộp ở `agent_service`, trước khi gọi backend |
| (a) chỉ chấm phần phiếu chưa cho thấy | `_unseen` cắt đúng 600 ký tự đầu khỏi đoạn 0 và 600 ký tự cuối khỏi đoạn cuối (doc-44: 1 719 → 1 114; 1 855 → 1 250), các đoạn giữa gần nguyên; doc-45 có đáp án trong phần đầu phiếu: tìm "sảnh B nhà thi đấu Phú Lâm" **không** trả đoạn 0 — đúng ý |
| Kết quả ở đoạn dán | có `document_id` = `paste_…`, `chunk_index`, trích 400 ký tự, và câu `read: đọc trọn đoạn này bằng read_document(…, from_chunk=i, n=3)`; đặt trước kết quả kho; không có điểm số (đúng, BM25 không cùng thang) |
| BM25 | Okapi chuẩn, IDF Robertson chặn 0 (từ có ở ≥ nửa số đoạn không tính), NFC trước khi tách `\w+`; cache `_unseen` theo văn bản |
| Phiếu (b) dựng trên doc-39 | không còn "search_documents không tìm thấy nó" và "không cần search_documents trước"; câu trần `n` 1–3, không số đoạn, "đã đủ thì trả lời luôn" đứng trước; khung lời 1 025 ký tự (#3-C: 780) |
| Test | 219 xanh, 13 bỏ qua (toàn bộ `tests/test_agent*.py`) |
| Worktree | sạch, HEAD c270ded |

## BM25 tìm được đoạn đáp án không — thử trên 9 bài đã công khai

Hai kiểu truy vấn: nguyên câu hỏi (dòng đầu hoặc cuối của tin), và cụm ngắn tôi viết như model hay viết. Đáp án theo vị trí
đã kiểm ở v0.5/v0.6. `top_k` mặc định của công cụ là 4.

| Bài | Đáp án ở đoạn | Nguyên câu hỏi: hạng | Cụm ngắn: hạng |
|---|---|---|---|
| doc-39 | 2 | 1 | 1 |
| doc-40 | 3 | 3 | 1 |
| doc-41 | 6 | 1 | 1 |
| doc-43 | 1 và 5 | 2 và 3 | 2 (đoạn 1); đoạn 5 ngoài top-4 |
| doc-44 | 4 | 4 | ngoài top-3 |
| doc-46 | 7 | ngoài top-4 | 4 |
| doc-47 | 2 và 5 | ngoài top-4 | 2 và 3 |
| doc-42, doc-45 | trong phần phiếu cho thấy | không trả (đúng) | không trả (đúng) |

Đọc: tìm từ trùng đưa đoạn đáp án vào top-4 ở 5–6/7 bài tuỳ cách hỏi, đứng đầu ở 3/7; doc-44 và doc-46 là hai bài yếu.
Đây là số của tôi trên bài đã thấy, không thay phép đo; bản đăng ký nên dự đoán riêng doc-44 và doc-46 ở nhánh +1+3'.

## (b) — rộng hơn chữ nghĩa gói đã duyệt, nhưng cần cho phép đo 3'

Chủ dự án duyệt "3' cho search_documents tìm trong đoạn dán"; tin tôi gửi opus nói đổi câu "search_documents không tìm thấy
nó". (b) đi xa hơn: phiếu bảo **tìm trước** khi cần một chi tiết, đọc từ đoạn 0 chỉ khi cần cả văn bản hoặc tìm không ra.
Lý do opus/NV2 đúng về mặt đo: ở #3-C, 5/5 lần mở đầu làm đúng lệnh cụ thể duy nhất của phiếu; giữ lệnh (0, 3) làm lệnh
duy nhất thì model sẽ không tìm, và nhánh +1+3' chỉ đo "có BM25 mà không ai gọi". Hệ quả cần nói rõ trong bản đăng ký:
- nhánh +1+3' đo **cả gói** "BM25 + phiếu lái sang tìm", không tách được hai phần;
- bốn bài #3-C đạt nhờ đọc lần lượt (39, 41, 43, 46) nay đi đường tìm trước; doc-46 tìm yếu (bảng trên) nên có thể lùi;
  bản đăng ký phải dự đoán riêng từng bài này và luật "không bài nào đạt → trượt" sẽ bắt nó.
Tôi báo chủ dự án điều này; nếu chủ dự án không muốn phiếu lái sang tìm thì NV2 đổi (b) về một câu ngắn ("search_documents
tìm được trong văn bản dán, kết quả cho chunk_index để đọc") trước khi đăng ký.

## Nhỏ, không chặn

- Trích 400 ký tự + câu `read` ở mỗi kết quả: model có thể trả lời từ trích mà không đọc (bệnh của công cụ đọc tài liệu);
  bản đăng ký nên ghi riêng "trả lời sau khi tìm mà không đọc" ở nhánh +1+3'.
- Phiếu dài thêm ~245 ký tự ở mọi đoạn dán, kể cả bài trả lời được ngay từ mép; ghi `tokens_in` sẽ thấy.
- Nhánh nudge (2955861) đang CẦN SỬA một chỗ về `from_chunk` khi model nhảy bằng tìm rồi nói đã đọc hết; chỗ đó liên quan
  trực tiếp tới nhánh này nhưng sửa ở phía nudge.
