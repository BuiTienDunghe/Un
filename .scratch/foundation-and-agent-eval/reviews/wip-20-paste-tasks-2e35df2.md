GỘP ĐƯỢC

# Duyệt wip/20-paste-tasks 2e35df2 (ticket 20 #3-B: 4 bài đoạn dán, bộ bài v0.5) — fable 5.1, 28/10/2026

Đã kiểm: diff ad09916..2e35df2 (5 tệp: `tasks.jsonl` +4 dòng, `dataset.json` version, README mục v0.5, `test_agent_eval.py`
+75, ticket). Mọi lệnh chạy với `env -u POSTGRES_TEST_URL -u REDIS_TEST_URL` và bộ giữ im Ollama/GPU; không chạy model.
Tệp này không nói gì về lời phiếu mới của NV1.

## Kiểm độc lập (script riêng, không dùng test của nhánh)

| Kiểm | Kết quả |
|---|---|
| 48 bài cũ so với main, từng dòng JSON chuẩn hoá | 48/48 giống hệt; bài mới đúng 4: doc-40..43 |
| Vị trí đáp án, tính lại bằng `pastes._chunks` + `SLIP_EDGE_CHARS` của main (mỗi regex `must_mention` nằm ở đoạn nào, có trong 600 ký tự đầu/cuối không) | trùng ghi chú và README từng số: doc-40 đoạn 3/8; doc-41 đoạn 6/15; doc-42 đoạn 7/8 **và** trong 600 ký tự cuối; doc-43 đoạn 1 và 5/10. Ở (a)(b)(d) không regex nào khớp phần đầu hay phần cuối; mỗi regex khớp đúng một đoạn (không dính chồng lấn 80 token như "Thu Hà" của doc-39) |
| Độ dài | 10 474–21 342, trong 10 001–30 000; bài không phải đoạn dán dài nhất 204 ký tự, nên "chỉ tin dài mới đổi phiếu" là đúng cho cả bộ |
| "Mọi lần đọc 3 đoạn liền nhau đều vừa trần 6 000" | tôi dựng JSON kết quả đọc theo đúng hình `_fit_chunks` cho mọi cửa sổ 0/3/6/9/12: rộng nhất 5 745 (doc-41), 5 725 (doc-43) < 6 000 → mỗi lần đọc trả đủ 3 đoạn, `next_from_chunk` nhảy đúng 3; bảng "số lần đọc tối thiểu" đứng được |
| Bộ bài nạp | `load_dataset` OK: `agent-eval-v0.5`, sha `eb62c4f1…92ce7`, 52 bài, bộ chấm vẫn v0.4; 5 bài đoạn dán không có mục truy xuất (như doc-39, không phải "pending") nên `--tasks` chạy được và `search_documents` trả "không thấy" |
| Gây nhiễu nhìn thấy trong phiếu (tôi đọc 300 ký tự cuối và phần đầu) | doc-40: "06/01/2027", "Phí Văn Tùng", "Lâm Hữu Phước"; doc-43: "Nghiêm Thị Thu Vân"; doc-41: danh bạ quản lý bếp — model không đọc mà đoán sẽ trượt `must_mention`, đúng ý đề |
| Test | 113 xanh (agent_eval, eval_documents, scorecard, pastes); test runner đọc đoạn 6 của doc-41 qua `read_document` là lần đầu runner mở đoạn dán trong test — đúng lỗ hổng NV3 nêu |
| Độc lập | ghi chú/README chỉ nhắc "phiếu cho thấy 600 ký tự đầu và cuối" (chung cho cả phiếu cũ và mới); không dấu vết lời phiếu mới |

## Nhận xét

- Hai lựa chọn NV3 tự quyết (câu hỏi ở đầu cho (a)(d); (b) ở đoạn 6 chứ không từ 9) hợp lý và đã ghi lý do: từ đoạn
  9 trở đi, đọc lần lượt 3 lượt không tới, bài thành bài đoán. Hệ quả cần nói rõ khi đọc kết quả: doc-41 chỉ đạt
  được nếu model dùng **trọn** 3 lượt công cụ rồi trả lời ở lượt ép (`max_steps`), nên doc-41 trượt có thể là hết
  lượt chứ không phải không đọc; bản đăng ký của opus đã tách "mở" khỏi "đạt" nên điều này không làm hỏng luật.
- doc-42 không có `max_tool_calls`: agent đọc thừa vẫn đạt. Đúng như NV3 ghi; bản đăng ký ghi số lần đọc thừa mà
  không chặn. Không nên thêm bây giờ: đổi `expect` là đổi băm bộ bài và thêm một vòng duyệt, mà điều cần đo là "có
  mở không".
- Test `test_paste_answers_lie_where_the_notes_say` kiểm `"đoạn 1" in note`: khớp cả "đoạn 10"/"đoạn 12". Không sai ở
  bộ hiện tại (chỉ số đã kiểm bằng `found == [where]`), chỉ là nhánh kiểm ghi chú yếu; không chặn.
- README v0.5 và ghi chú bài ghi rõ vị trí đo ở `ad09916`, chunker 480/80, mép 600, và test tính lại mỗi lần chạy:
  đổi chunker hay mép là biết ngay. Tốt.

## Việc cho opus

- Gộp được; gộp trước nhánh lời phiếu như kế hoạch. Dòng Status của ticket 20 bị cả hai nhánh sửa: xung đột chữ
  một dòng.
- Băm bộ bài đổi (v0.4 → v0.5): bảng điểm 23 không `--compare` chéo phiên bản; 48 bài cũ vẫn so được từng bài. Lần
  đo 5 bài (`--tasks`) không nên `--append-history` như một lần đo đủ, hoặc phải đánh dấu là lần đo một phần.
