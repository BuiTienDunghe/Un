# Lần đầu chạy bộ v0-long (02/11/2026)

Commit `ac42928`, Ollama 0.40.13, Qwen 9B, nhiệt độ 0, seed 42, gỡ model trước mỗi bài, GPU dùng chung với bot. Bộ bài tự viết, văn bản tự sinh, đáp án nằm ở cuối.

| Bài | Tắt | Bật | Tính năng có chạy không | Lâu nhất khi bật |
|---|---|---|---|---|
| `end-*`, đọc văn bản rất dài (ticket 45) | 0/7 | 6/7 | Có, 16 phần | 27,4 s |
| `ctx-*`, dọn ngữ cảnh (ticket 44) | 0/7 | 0/7 | **Không, 0 lần dọn** | 12,7 s |

Ticket 45 có lợi rõ trên bộ này; `end-01` vẫn thiếu số tiền. Ticket 44 chưa đo được: 4 bài model không gọi công cụ, 3 bài hết vòng trước khi đủ dữ kiện, nên ngữ cảnh chưa chạm trần. Bộ `ctx-*` chưa đo được điều nó định đo.
