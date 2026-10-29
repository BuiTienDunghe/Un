GỘP ĐƯỢC (vào main, sau khi G1 của lần chạy đủ 66 bài đạt và báo cáo được duyệt; code đúng là nhánh N1 đã đo, không thêm một dòng nào)

# Duyệt diff gộp int/20-n1-main 717e4d3 vào main — fable 5.1, 29/10/2026

717e4d3 = merge(d40d4e0, 928f1cf). Đối chiếu bằng git, không chạy model.

| Kiểm | Kết quả |
|---|---|
| Code so với nhánh N1 đã đo | `git diff 32a2d50 717e4d3 -- backend/app backend/scripts` **rỗng**; so với d40d4e0 cũng rỗng ở `backend/` |
| Code so với main 928f1cf | chỉ `pastes.py` (+66 −…: phiếu #3-C y như 5d16c7b đã duyệt + N1 y như 32a2d50 đã duyệt), `agent_eval.py` +3 dòng khoá manifest `paste_inline` |
| Test so với nhánh N1 | chỉ `test_agent_eval.py`; patch-id của phần khác trùng đúng diff test của bài v0.8 0adc697 (`52b095f4…`), tức không có test nào mới ngoài hai thứ đã duyệt |
| Bộ bài | `tasks.jsonl` v0.7 → v0.8: +4 dòng, 0 dòng xoá; 62 bài cũ không đổi một byte |
| `agent_service.py`, guide, tools, grader | không đụng; `tools_sha256` 153209…a75e500 ghim bởi test |
| Test ở worktree `int-20-n1-main` (sạch, HEAD 717e4d3) | 265 xanh, 13 bỏ qua trên 18 tệp agent/chunk; không chạy bộ DB |

## Nhận xét

- Đây đúng là "đưa lên main thứ đã đo": không có thay đổi nào ngoài hai nhánh đã duyệt và bộ bài v0.8 đã duyệt. Mọi nhận xét
  cũ vẫn đứng: hằng 12 288 là số cứng theo num_ctx 16 384; #2 coi đoạn dán nguyên văn là đã thấy; Discord không bao giờ bật N1
  vì schema chặn 10 000.
- Điều kiện gộp nằm ở lần chạy 66 bài (G1), không ở diff này.
