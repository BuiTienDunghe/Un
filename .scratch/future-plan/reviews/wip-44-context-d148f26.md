GỘP ĐƯỢC

# Duyệt `wip/44-context` (d148f26) — ticket 44, dọn kết quả công cụ cũ khi sát trần

**Bản chất.** Mỗi vòng, Ún gửi lại cho model cả cuộc trò chuyện. Nhánh này, khi bật, trước mỗi lần
gửi sẽ ước lượng độ dài; nếu quá trần thì thay kết quả công cụ cũ nhất bằng một dòng ghi chú "đã bỏ,
muốn xem lại thì gọi lại", nhưng chỉ thay trong *bản gửi đi*, không đụng vào danh sách gốc. Tắt (mặc
định) thì bản gửi đi chính là danh sách gốc, không có gì thêm bớt.

**Đã kiểm.**

| Điều phải đúng | Kết quả | Cách kiểm |
|---|---|---|
| Tắt thì y hệt cũ | Đúng | `ContextWindow(None).view` trả về chính `working`; `observe` thoát sớm; `context_cleared` chỉ thêm khi >0 |
| Mỗi lệnh gọi vẫn đi kèm kết quả | Đúng | Chỉ thay `content`, không xoá/đổi chỗ; `checked_out` giữ nguyên vị trí |
| Ghi chú đọc lại được | Đúng với Ollama, **sai với Anthropic** (mục 2) | Chạy thử `_calls_by_result` với tool_calls dạng khối Anthropic |
| Đoạn dán N1 / tài liệu đọc được | Ổn | Tin nhắn user không bao giờ bị dọn; `readable_documents`, `web_urls`, `pastes` sống hết lượt nên gọi lại được |
| Kiểm tra số liệu trong câu trả lời | Dùng `working` đầy đủ, nên khoan dung với số đã bị dọn — đúng như docstring đã nói | Đọc `_check_answer` |
| Cấu hình hỏng | Tắt + cảnh báo, không sập API | `enabled: "yes"`, `keep_recent: 0`, `ceiling_tokens: True` đều về None |
| Ước lượng token | Lệch có hệ thống nhưng thiên an toàn (mục 3) | Đo `AGENT_GUIDE` = 675 ký tự ≈ 205 token |

Test: toàn bộ test của nhánh (`test_context_budget.py`, `test_manifest_ollama_version.py`) cùng
`test_call_budget.py`, `test_agent_service.py` chạy trong worktree: 43 pass, 9 skip. 9 bài skip là
`test_agent_service.py` (cần DB), nên "tắt y hệt" chỉ được chứng bằng test giả của chính nhánh, chưa
chạy trên vòng lặp thật với DB.

## Phát hiện

### 1. Hệ số hiệu chỉnh bị reset bởi một lần đọc thấp — `context_budget.py:176-181` — **trung bình, sửa trước khi đo**

Ghi chú ở dòng 39 nói số đo "chỉ được phép nâng ước lượng lên". Nhưng `observe` là phép gán:
`self._scale = min(2.0, max(1.0, tokens_in / estimated))`. Chạy thử: `observe(1500)` với ước lượng
1000 → scale 1,5; `observe(100)` ngay sau → scale về 1,0.

Kịch bản: vòng 1 lạnh, Ollama báo đủ `prompt_eval_count` → scale 1,4 → vòng 2 dọn N kết quả. Vòng 2
Ollama phục vụ prefix từ cache, báo số thấp → scale về 1,0 → vòng 3 dọn ít hơn vòng 2: kết quả model
vừa thấy bị thay bằng ghi chú nay **hiện lại**, prompt lại vượt trần. Test
`test_a_measured_reading_above_the_estimate_tightens_it_and_one_below_changes_nothing` chỉ thử "thấp sau
không có gì", không thử "thấp sau cao". Sửa: `self._scale = max(self._scale, …)`. Không chặn gộp vì
mặc định tắt, nhưng phải sửa trước bước đo cô lập của ticket, nếu không số đo sẽ nhiễu theo vòng.

### 2. Với provider Anthropic, ghi chú không có tham số — `context_budget.py:81-96` — **trung bình**

`_calls_by_result` chỉ đọc `call["function"]`. `anthropic_client.chat_tools` (dòng 305) trả
`raw_tool_calls` là các khối `{"type": "tool_use", "name", "input"}` — không có khoá `function`. Chạy
thử: ghi chú ra "[Kết quả cũ của read_document đã được bỏ … gọi lại công cụ này với đúng tham số
trên.]" mà không có tham số nào. Kịch bản: bật `general-haiku-v1` (ticket 26) + bật budget → model
được bảo "gọi lại với đúng tham số trên" nhưng không thấy tham số, phải đoán lại `document_id`,
`from_chunk`. Thêm nhánh đọc `call["name"]`/`call["input"]` khi `type == "tool_use"` là đủ.

### 3. Ước lượng đếm hướng dẫn agent hai lần — `context_budget.py:69-78` — **thấp**

`INLINE_FIXED_TOKENS` (1 253) đã gồm hướng dẫn agent và lược đồ công cụ (đo thực trên stat-01);
`estimate_tokens` chạy trên `working`, trong đó có `guide`, nên cộng thêm ~205 token nữa. Hệ quả là
dọn sớm hơn cần ~205 token (1,7 % trần 12 288). Thiên an toàn, không hỏng gì; ghi để khi đo khỏi
tưởng trần thực là 12 288. (Cùng chỗ: `context_budget_from_config` nhận `general` nhưng không đọc —
trần không lấy từ đó.)

## Chưa kiểm được

Không có GPU/DB: chưa chạy vòng lặp thật, chưa biết `prompt_eval_count` của Ollama bản hiện tại
có trừ prefix cache hay không (quyết định mục 1 nặng tới đâu).
