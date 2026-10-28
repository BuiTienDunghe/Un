GỘP ĐƯỢC

# Duyệt wip/20-paste-tasks-c 36f8bd7 (ticket 20 #3-C: 4 bài đoạn dán chưa ai xem, bộ bài v0.6) — fable 5.1, 28/10/2026

Đã kiểm: diff fadc775..36f8bd7 (4 tệp: `tasks.jsonl` +4 dòng, `dataset.json` version, README mục v0.6, `test_agent_eval.py`
+65/−7; không chạm ticket). Mọi lệnh chạy với `env -u POSTGRES_TEST_URL -u REDIS_TEST_URL` và bộ giữ im Ollama/GPU; không
chạy model. Tệp này không nói gì về lời phiếu của NV1.

## Kiểm độc lập (script riêng, không dùng test của nhánh)

| Kiểm | Kết quả |
|---|---|
| 52 bài cũ so với main fadc775, từng dòng JSON chuẩn hoá | 52/52 giống hệt; bài mới đúng 4: doc-44..47 |
| Vị trí đáp án, tính lại bằng `pastes._chunks` + `SLIP_EDGE_CHARS` của main (mỗi regex `must_mention` nằm ở đoạn nào, có trong 600 ký tự đầu/cuối không) | trùng ghi chú và README từng số: doc-44 đoạn 4/8; doc-45 đoạn 0/10, cả hai regex trong 600 ký tự đầu (ký tự 259–322, dưới 350 như README nói); doc-46 đoạn 7/12; doc-47 đoạn 2 và 5/9, cách 3 = `READ_MAX_CHUNKS`. Ở (e)(g)(h) không regex nào khớp phần đầu hay phần cuối; mỗi regex khớp đúng một đoạn |
| Regex không khớp câu hỏi | đúng ở cả 4 bài (câu hỏi ở đầu với doc-44, 46; ở cuối với doc-45, 47) |
| Độ dài | 10 651–14 413, trong 10 001–30 000 |
| "Mọi lần đọc 3 đoạn liền nhau đều vừa trần 6 000" | tôi dựng JSON kết quả đọc theo đúng hình `_fit_chunks` (`read_paste` + `json.dumps`, đoạn dài nhất 1 964 < 2 400 nên không bị cắt) cho mọi cửa sổ 0/3/6/9: rộng nhất 5 759 (doc-44, cửa sổ 3–5). README ghi 5 769; chênh 10 ký tự không đổi kết luận, cả hai dưới trần → `next_from_chunk` nhảy đúng 3, bảng "lần đọc" đứng được |
| `max_tool_calls: 0` chỉ ở doc-45 | đúng; `expect` 4 bài theo mẫu doc-39 (cấm `search_history`, `system_status`; không cấm `search_documents`) |
| Bộ bài nạp | `load_dataset` OK: `agent-eval-v0.6`, sha `cd38e4d19a09…306ed`, 56 bài, bộ chấm vẫn v0.4; 4 bài mới không có mục truy xuất (như doc-39..43, không phải "pending") nên `--tasks` chạy được |
| Gây nhiễu README khai là phiếu cho thấy, soi trong 600 ký tự đầu/cuối | đều có mặt: doc-44 "Sương Mai", "420.000" ở cuối; doc-45 "nhà văn hóa", "thứ Sáu" ở cuối; doc-46 "5.000.000" ở cả đầu lẫn cuối, "Hải Đăng" ở đầu; doc-47 "30 ngày", "54.000.000" ở cuối |
| "Mỗi cặp thứ–ngày khớp lịch 2026" | 28/11 thứ Bảy, 29/11 Chủ nhật, 14/12 thứ Hai, 15/12 thứ Ba (nên "đêm thứ ba" đúng là hai nghĩa như README nói), 16/11 thứ Hai, 05/12 thứ Bảy |
| Test | 137 xanh (agent_eval, agent_eval_documents, agent_eval_record, agent_eval_scorecard, agent_pastes). Hai test runner mới: doc-46 đáp án tới ở lần đọc thứ ba với trần thật (`next_from_chunk` 3, 6, 9); doc-45 cùng câu trả lời, không đọc thì đạt, đọc một lần thì trượt riêng `tool_budget` |
| Độc lập | README/ghi chú không chứa câu nào của lời phiếu mới; cụm "không có trang" ở README dòng 25 đã có trên main từ v0.3 |
| Worktree | sạch, HEAD 36f8bd7 |

## Nhận xét

- Bốn kiểu đúng brief 15:40: (e) đoạn 4 trong khoảng 3–5; (f) trong mép đầu, cấm công cụ; (g) tới ở lượt công cụ cuối
  như doc-41; (h) hai đoạn cách đúng trần đọc như doc-43. Chủ đề và kiểu hỏi khác hẳn 5 bài cũ (soạn tin nhắn, kiểm
  điều nhớ sai, đối chiếu bảng hạng, hỏi hệ quả hợp đồng) — đúng ý "bài chưa ai xem, không cùng khuôn".
- doc-45 là bài duy nhất phạt đọc thừa; doc-42 cùng ý mà không phạt. Bản đăng ký phải nói trước cách đọc hai bài này
  cạnh nhau (đã ghi trong `report-20-3b-fadc775.md`).
- doc-46 chỉ đạt được khi model dùng trọn 3 lượt công cụ rồi trả lời ở lượt ép; trượt có thể là hết lượt chứ không phải
  không đọc, như doc-41. README đã ghi.
- Test `test_paste_answers_lie_where_the_notes_say` nay kiểm `max_tool_calls` theo vị trí ("head" ⇒ 0, còn lại ⇒ None)
  và khoảng cách hai đoạn ở mọi bài hai đoạn, không chỉ doc-43. Tốt hơn v0.5.

## Việc cho opus

- Gộp được; gộp trước nhánh lời phiếu như kế hoạch. Không xung đột ticket (NV3 không sửa tệp ticket).
- Băm bộ bài đổi (v0.5 → v0.6): bảng điểm không `--compare` chéo phiên bản; 52 bài cũ vẫn so được từng bài. Lần đo 9 bài
  (`--tasks`) không `--append-history` như lần đo đủ.
- Phía "trước" của #3-C phải đo lại cả doc-39..43 trên main + v0.6 (sha bộ bài khác #3-B), không lấy lại số #3-B.
