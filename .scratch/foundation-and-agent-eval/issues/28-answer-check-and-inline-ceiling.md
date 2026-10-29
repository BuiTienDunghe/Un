# 28 — Đuôi ticket 20: bước soát số và ngưỡng nạp nguyên văn

Status: xong code — gộp main d1725b6 (30/10); mục 2 và 3 chưa đo
Type: task
Blocked by: —

## Vì sao

Sau khi N1 lên main (3a2b769, Release v1.5.0), còn bốn chỗ lỏng:

- Bước soát số (#2) bắt được một con số "không thấy ở đâu", nhưng vết chỉ ghi là bắt **bao nhiêu** con số, không
  ghi **con số nào**. Ở doc-47 dưới N1, #2 bắn một lần (`UNSUPPORTED_FIGURES`, 1 con số). Không ai biết đó là số nào,
  vì câu trả lời đầu bị loại không được giữ. 54.000.000 có nguyên văn trong đoạn dán, nên đó không phải lý do.
- Sau lần thử lại, model mở câu trả lời bằng "Xin lỗi, tôi đã nhầm lẫn…", và người dùng thấy câu đó
  (doc-47 v0.8-n1-gate; doc-22 v0.3, coordination 5c). Lời thử lại chỉ dặn "Rồi trả lời lại".
- Bộ soát đọc số theo dãy chữ số, nên "54 triệu" thành "54" và không khớp "54.000.000". Đây là điểm mù có sẵn.
  Chưa chứng minh được đó là nguyên nhân ở doc-47.
- `pastes.INLINE_MAX_TOKENS = 16_384 - 4_096` viết cứng. Ai đổi `context` của general trong `model_versions.yaml`
  mà quên hằng này thì N1 sai mà không báo.

## Việc (mỗi mục một commit, theo thứ tự này)

1. **Vết ghi con số bị bắt.** Bước `answer_check` lưu chính các con số #2 bắt, không chỉ số lượng.
   - Con số là nội dung, nên phải đi cùng đường với nội dung: xoá theo hội thoại, `forget_member` xử lý được.
   - Bảng trace rút gọn của ticket 16 (`agent_trace_summaries`) vẫn không chứa nội dung.
   - Không đổi hành vi.
2. **Lời thử lại không lộ ra người dùng.** Lời nhắn cho lần thử lại dặn thêm: viết lại câu trả lời như lần
   đầu, không xin lỗi, không nhắc tới việc vừa kiểm.
   - Mục này đổi hành vi. Commit riêng để gỡ riêng được.
3. **"N triệu / tỷ / nghìn / ngàn" bằng số đầy đủ.** "54 triệu" khớp "54.000.000" theo cả hai chiều, "1,5 tỷ"
   khớp "1.500.000.000".
   - Đây là sửa điểm mù, không phải sửa doc-47.
   - Đổi hành vi, vì #2 sẽ bắn ít hơn.
4. **Ngưỡng nạp nguyên văn lấy từ cấu hình model.**
   - Ngưỡng = `context` của phiên bản general đang active, trừ 4 096.
   - Bên gọi truyền ngưỡng vào, nên `pastes.py` không phải import cấu hình.
   - Manifest Agent Eval vẫn ghi `paste_inline.max_tokens`.
   - Một test chốt rằng với `model_versions.yaml` hôm nay ngưỡng vẫn là 12 288. Đó là bằng chứng mục này không
     đổi hành vi.

## Nghiệm thu

- Mỗi mục có test, và test đỏ khi gỡ phần sửa.
- Bộ test không DB xanh khi chạy im lặng. Bộ có DB do opus chạy sau khi gộp.
- Mục 2 và 3 chưa đo. Từ khi gộp, mốc cô lập 55/62 của v1.5.0 không còn áp cho main, cho tới lần chấm sau. Ghi
  rõ điều này trong CHANGELOG [Unreleased].

## Không làm

Đo Agent Eval, BFCL; văn bản dán trên khoảng 36k ký tự; lịch sử dài. Những việc này để tới lần chấm điểm.

## Comments
- 30/10 (opus 5.5): bốn commit `ff2f6ca`, `0cff26b`, `a2e2690`, `f348364`; gộp main `d1725b6`, fable GỘP ĐƯỢC.
  - #1: con số lưu ở `AgentTrace.arguments`, không ở `content`, vì `content` bị băm vào bảng rút gọn và băm một con số ngắn thì đoán ngược được.
  - #3: luật chỉ bớt bắt, không bắt thêm. Fable kiểm trên 147 câu trả lời đã giữ: không câu nào đổi. Số một chữ số kèm đơn vị ("2 triệu") vẫn không được kiểm; muốn kiểm thì là một thay đổi nhỏ, nhưng #2 sẽ bắn nhiều hơn.
  - #4: theo ghi chú của fable, `main.py` lấy config từ `router.models` (`f072e69`).
  - Chưa chạy với DB: phần đọc `answer_check` trong `forget_member`. Bộ DB sau gộp không có ca cho phần này.
