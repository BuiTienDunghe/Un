GỘP ĐƯỢC

# Duyệt wip/20-paste-slip-c 5d16c7b (ticket 20 #3-C: lời phiếu đoạn dán, lần hai) — fable 5.1, 28/10/2026

Đã kiểm: diff c54e3eb..5d16c7b (2 tệp: `slip()` trong `pastes.py` +22/−6, `test_agent_pastes.py` +21/−2; không chạm
ticket). Mọi lệnh chạy với `env -u POSTGRES_TEST_URL -u REDIS_TEST_URL` và bộ giữ im Ollama/GPU; không chạy model.
Tệp này không nói gì về bài mới của NV3 (tôi chưa mở nhánh đó). Bằng chứng dùng chung: doc-39..43 và
`kept/agent-eval-v0.5-paste-slip-b/`.

## Kiểm độc lập

| Kiểm | Kết quả |
|---|---|
| Ba thay đổi chủ dự án chọn, dựng phiếu trên doc-39..43 bằng `slip()` của nhánh | (1) có câu "read_document chỉ nhận n từ 1 đến 3, tức mỗi lần đọc tối đa 3 đoạn" và "muốn đọc tiếp thì gọi lại với from_chunk bằng next_from_chunk"; (2) không phiếu nào còn số đoạn hay "từ 0 đến": số duy nhất trong lời dặn là 0, 1, 3 và các số trong id; (3) câu "đã đủ để trả lời thì trả lời luôn" đứng trước lệnh `read_document(` — đủ 5/5 bài |
| Những gì #3-B làm được còn nguyên | không gọi "tài liệu"; "search_documents không tìm thấy nó"; lệnh `read_document(document_id="paste_…", from_chunk=0, n=3)` đúng chữ; "không có trang"; dừng khi `next_from_chunk` là null; không có `read_document` ở phần trên đầu văn bản |
| Khung lời phiếu | 780 ký tự ở cả 5 bài (#3-B: 646); phiếu doc-39 1 979 ký tự |
| `most = 3` so với `READ_MAX_CHUNKS` | bằng; test ghim bằng `READ_MAX_CHUNKS` import từ `agent_service` (đúng chiều import) |
| `tools_sha256` tính như runner (`core_tools` + `agent_tools.register`) ở 5d16c7b và c54e3eb | cùng `153209652c0672a2337be105bd711a1e343a9c7bdf93911e7d14dba18a75e500` |
| `AGENT_GUIDE` thô | diff không chạm `agent_service.py`; băm thô bằng nhau hai phía |
| Test nhánh `test_agent_pastes.py` | 16 xanh |
| Kiểm ngược: test của nhánh chạy trên phiếu c54e3eb (chạy từ scratchpad, `PYTHONPATH` trỏ worktree `meas-c54e3eb`, không sửa worktree nào) | 3 đỏ đúng ba test NV1 nêu (lệnh gọi viết lại; trần + không số đoạn; "đủ thì trả lời luôn" đứng trước), 13 xanh; test ngưỡng 10 000 xanh cả hai bản |
| Nhận xét của NV1 "lần đọc sau xin n = total_chunks − from_chunk ở 4/5" | đúng theo `task_results` phía sau của #3-B: doc-40 (3, 5) = 8−3; doc-41 (3, 12) = 15−3, nhưng (6, 10) ≠ 15−6; doc-42 (3, 5), (6, 2) = 8−3, 8−6. Mọi kết quả đọc đều mang `total_chunks` (`agent_service.py:564, 589`; `pastes.py:96`), ticket giữ nguyên phần đó |

Tôi đọc 300 ký tự cuối của 5 phiếu: không phiếu nào bị cắt hay mất câu hỏi.

## Nhận xét

- **Phiếu nói đúng điều công cụ làm.** `n` 1–3 là schema thật; "gọi lại với from_chunk bằng next_from_chunk" là đúng
  cách `_fit_chunks` đặt `next_from_chunk`; "không có trang" đúng `read_paste`. Không câu nào hứa thứ code không làm.
- **Rủi ro của thay đổi (3), để bản đăng ký dự đoán chứ không phải để sửa:** câu "đã đủ thì trả lời luôn" đứng trước
  câu "cần phần chưa thấy thì đọc". Ở #3-B phía trước, doc-43 không đọc và hỏi lại; doc-39 ở #3 trích phần cuối rồi hỏi
  lại. Cả hai đều là ca model *tưởng* mép đủ. Câu mới có thể kéo chúng về lại cách đó; doc-39 và doc-43 là hai bài cho
  thấy điều này, nên bản đăng ký nên dự đoán riêng cho chúng thay vì gộp.
- **Điều phiếu không chạm được (NV1 nêu, tôi xác nhận):** số đoạn vẫn hiện trong mỗi kết quả đọc (`total_chunks`),
  nên từ lần đọc thứ hai model vẫn có con số để xin `n` lớn. Chỉ câu trần trong phiếu nói tới các lần đó. Nếu lần đọc
  đầu xin `n` ≤ 3 mà các lần sau vẫn xin quá 3, thì nguyên nhân nằm ở kết quả công cụ, không ở phiếu — và bộ chấm v0.4
  vẫn trượt `args_valid`. Bản đăng ký nên tách "`n` lần đọc đầu" khỏi "`n` các lần sau" khi báo, và nói trước điều đó
  có chặn luật không. Đây là quyết định của chủ dự án nếu muốn đổi luật; phiếu này không làm gì hơn được.

## Việc cho opus

- Gộp được. Nhánh cắt từ `int/20-3b` (c54e3eb), chứa cả phiếu #3-B; gộp `--no-ff` lên main sau khi gộp bài mới, như
  kế hoạch 15:40. Không xung đột ticket lần này (NV1 không sửa tệp ticket).
- Bản đăng ký #3-C: ngoài các ghi chú trong `report-20-3b-fadc775.md`, thêm hai điều trên — dự đoán riêng cho doc-39 và
  doc-43 về chuyện "trả lời luôn" sai, và tách `n` lần đầu / lần sau.
