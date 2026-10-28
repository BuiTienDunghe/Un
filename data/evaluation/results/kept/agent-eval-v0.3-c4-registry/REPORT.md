# Agent Eval v0.3 — ticket 22 C4, registry cắm được (28/10/2026, 08:14–08:21)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Cách đo và luật được đăng ký trước khi chạy
(`PREREGISTRATION.md`, 01:50). Chạy trong đợt A+B chủ dự án duyệt lúc 07:58.

## Thật ra chuyện này là gì

C4 chỉ chuyển một công cụ (tra lịch sử Discord) từ lõi agent sang gói Discord, và gói đó tự đăng ký công cụ vào lõi.
Người dùng không được thấy bất kỳ khác biệt nào. Phép đo kiểm đúng điều ấy: chạy cùng bộ bài trước và sau C4, so từng
bước. Kết quả là giống hệt nhau, nên C4 giữ nguyên hành vi.

## Kết quả

| Điều kiện / dự đoán | Kết quả |
|---|---|
| `tools_sha256` hai bên bằng nhau và bằng `153209…a75e500` đã tính lúc code | **đúng** |
| `agent_guide_sha256`, `system_prompt_sha256` bằng nhau | **đúng** |
| 48/48 câu trả lời của C4 trùng A từng chữ | **đúng** (48/48) |
| Mọi bước trace trùng: công cụ, tham số, `tool_declared`, `arguments_shape`, mã lỗi | **đúng** (0 bài khác) |
| Bài hist gọi `search_history` như A; hist-08..10 (web) nhận `TOOL_UNAVAILABLE_HERE` | **đúng** (11/11 gọi; 3/3 nhận mã) |

**Luật: cả ba dự đoán đúng → C4 giữ hành vi.** Điểm cả hai bên 39/48.

## Điều kiện đo

| | |
|---|---|
| A | worktree sạch tách tại `ced5e0b` (= `79065d7^1`, main ngay trước C4) |
| C4 | worktree sạch tách tại `79065d7` (gộp C4) |
| Quy trình | cùng buổi, A rồi C4; gỡ `qwen3.5:9b` trước mỗi lần, ghi `/api/ps` (`ollama_ps.jsonl`); t0, seed 42, `--probe`, `--gpu-shared no`; A 08:14:46, C4 08:18:26 |
| GPU | không dùng chung (phiên Quản lý xác nhận); `qwen3-embedding:0.6b` còn nạp ở cả hai lần |
| Thêm | 48 câu của A cũng trùng từng chữ lần đo #3 (`../agent-eval-v0.3-pastes/v0.3-paste-r1-cold`): ticket 23 (bảng điểm) vào giữa hai commit đó và không đổi gì model thấy |

Mỗi phía chỉ một lần chạy, như bản đăng ký. Ở t0 với seed 42, các lần lặp trước đó đều trùng nhau từng chữ (#1-B, #2,
#3), nên một lần đủ để thấy khác biệt nếu có.

## Tệp

`v0.3-c4-{A,C4}-cold/`: bốn tệp mỗi lần chạy. `analyze.py` tính lại `analysis.json`.
