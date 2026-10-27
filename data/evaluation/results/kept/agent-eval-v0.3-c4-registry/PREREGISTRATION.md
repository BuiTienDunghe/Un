# Agent Eval v0.3 — ticket 22 C4 (registry cắm được): đăng ký trước (28/10/2026, 01:50, trước mọi lần chạy)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** C4 chỉ dời code: công cụ `search_history`
sang gói Discord và đăng ký vào registry của agent. Phép đo này hỏi đúng một điều: model có thấy và làm
y hệt như trước không.

**Lần đo HOÃN** vì cần GPU (luật đêm 28/10); gom vào đợt đo chung. Bản này viết lúc code xong (`84a44de`)
và ràng buộc lần đo đó.

## So cái gì (thiết kế ticket 22, dòng C4)

| | Code |
|---|---|
| A | `main` ngay trước C4, tức merge-base của `wip/22-c4-registry` (`ec4d843` hoặc main lúc đo, nếu C4 được rebase) |
| C4 | `wip/22-c4-registry` |

Hai lần **cùng buổi**: một lần lạnh trên A, rồi một lần lạnh trên C4. Gỡ `qwen3.5:9b` trước mỗi lần và ghi
`/api/ps`; t0, seed 42, `--probe`; cây sạch; chạy từng lần một, đọc tin giữa hai lần. Chỉ chạy khi điều
phối báo GPU dùng được và luật "Giữ im Ollama" đã gỡ.

## Điều kiện phải đúng trước khi so (sai thì dừng, không so)

- `tools_sha256` của hai manifest bằng nhau và bằng `153209652c0672a2337be105bd711a1e343a9c7bdf93911e7d14dba18a75e500`,
  giá trị đã tính trên cả main lẫn C4 lúc code (registry lõi + `search_history` của gói ra schema trùng từng
  byte). Nếu một commit khác đổi mô tả công cụ trước lần đo, thì hai bên vẫn phải bằng nhau, giá trị mới ghi
  vào báo cáo.
- `agent_guide_sha256` và `system_prompt_sha256` bằng nhau.

## Dự đoán (sai thì báo; không sửa gì sau khi thấy kết quả)

| Dự đoán | Lý do |
|---|---|
| **48/48 câu trả lời của C4 trùng A từng chữ** | prompt (lời dặn, mô tả công cụ, thứ tự) trùng từng byte; thân hàm `search_history` trùng từng chữ (chỉ `self` thành `service`); t0, seed 42 |
| Mọi bước trace trùng: cùng công cụ, cùng tham số, cùng `tool_declared`, cùng `arguments_shape` | `declared()` của registry trùng `_DECLARED` cũ (đã so lúc code) |
| Các bài hist (Discord) gọi `search_history` y như A, và hist-08..10 (web) vẫn nhận `TOOL_UNAVAILABLE_HERE` | handler giữ nguyên nhánh "không có guild" |

## Luật quyết định

C4 giữ hành vi nếu cả ba dự đoán đúng. So từng bài, dừng ở chỗ khác đầu tiên của bài đó và báo kèm câu
trả lời. Nếu khác, không gộp cho tới khi tìm ra nguyên nhân.

## Đã kiểm lúc code (không cần GPU)

| Kiểm | Kết quả |
|---|---|
| Schema và `declared` của registry (lõi + gói) so với `AGENT_TOOLS` / `_DECLARED` trên main | trùng hệt; `tools_sha256` 153209… |
| Thân `SearchHistory.__call__` so với `AgentService._search_history` trên main | trùng từng chữ sau khi đổi `self.` thành `service.` |
| Bộ test backend không DB, trên C4 so với một worktree sạch | cùng 14 test hỏng ở cả hai, đều do worktree thiếu `.env`; trên main checkout cả bộ xanh |
