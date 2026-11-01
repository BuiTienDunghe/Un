GỘP ĐƯỢC

Nhánh `claude/harness-fix-239b67` (631bf2a), đọc `git diff main...` và chạy lại `analyze.py` trên chính số liệu trong nhánh, 02/11/2026.

## Bản chất

Nhánh này không sửa gì ở đường chạy thật khi cờ tắt. Nó thêm ba cái công tắc (hai ở bộ chạy BFCL, một ở vòng agent), đo từng cái cùng ngày với đối chứng, rồi để cả ba ở vị trí tắt. Phần lớn 110 tệp là kết quả đo; mã nguồn đổi ở 6 tệp, test ở 3 tệp.

## Đã kiểm, không thấy lỗi

| Mục | Kết quả |
|---|---|
| Số trong REPORT.md khớp số liệu | Chạy lại `analyze.py` trên 8 cặp: 26→27/27/28/26 BFCL, 54→54/55/55 Agent Eval, C2 trùng C 33/33 và 66/66, H3b chỉ bắn ở doc-25, H3 bắn ở doc-17/25/46, `max_steps` 3→1 ở H2, đỉnh token 7 515, +12 % token vào ở bài nhiều lượt (toàn bộ: +10,5 %) — đều khớp |
| Đối chứng cùng ngày | 10 manifest đều 02/11 (19:29–20:45 UTC), Ollama 0.40.13, `gpu_shared: true` |
| Đăng ký trước có trước lần đo | Commit 91562ce lúc 02:28 +07; `hf-c-bfcl` bắt đầu 02:29; code H1–H3 commit 02:39 (a2bc2c8); các nhánh thử chạy sau đó |
| Cờ tắt mặc định | `main.py:248` đọc `agent.lookup_check` mặc định False; `models.yaml` không đổi; `bfcl_run.py` hai cờ `--carry-tool-traffic`, `--max-steps` chỉ ở dòng lệnh; test `test_it_is_off_by_default` |
| Không gọt theo bộ chấm | H3 không sửa bộ chấm, không đụng `AGENT_GUIDE`; điều kiện bắn là "chưa gọi công cụ nào + có công cụ tra + nói ở ngôi thứ nhất là không có thông tin"; H1 là cách BFCL gốc vẫn làm; H2 chỉ là số đo |
| Dữ liệu riêng | Khớp `grep` chỉ là đường dẫn `C:\Users\dungbt06\...` trong manifest (các manifest đã có ở `kept/` trên main cũng vậy) và số tweet do model bịa (đã nêu trong báo cáo); bộ Agent Eval là dữ liệu bịa sẵn |
| Luật 5 README | `README.en.md:83-86` và docstring `call_budget.py` ghi ngoại lệ thứ năm, tắt, chờ chủ dự án |
| Test không DB | `test_agent_lookup_check`, `test_call_budget`, `test_bfcl_run`, `test_agent_answer_check`: 69 qua |

## Ghi chú, không chặn

- **thấp** — `backend/app/services/agent_service.py:218-221` (`LOOKUP_GAVE_UP`): câu đúng kiểu "Tôi không tìm thấy X trong văn bản bạn gửi" (trả lời về đoạn dán, không cần tra tài liệu) cũng khớp mẫu và tốn một vòng thử lại. Cờ đang tắt; bản đăng ký đã tự nêu mẫu regex là chỗ yếu.
- **thấp** — Mẫu H3b hẹp lại sau khi thấy H3 bắn nhầm trên chính 66 bài này (báo cáo đã nói rõ). H3 rộng cũng đã đủ luật quyết định đặt trước (0 bài đạt→hỏng, 1 bài hỏng→đạt) nên đây không phải cứu kết quả.
- Chưa kiểm: câu "`hf-c-ae` trùng `wave2-control` 66/66" (wave2-control không nằm trong nhánh); `hf-c-ae` có `worktree_dirty: true` ở commit 91562ce — báo cáo giải thích là do thư mục kết quả chưa commit, và `hf-c2-ae` (code đã commit, cờ tắt) trùng nó 66/66 nên không ảnh hưởng kết luận.
