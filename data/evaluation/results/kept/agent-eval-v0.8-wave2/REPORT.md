# Đo đợt 2 cùng ngày (02/11/2026)

Commit `b3198ca`, Ollama 0.40.13, Qwen 9B, nhiệt độ 0, seed 42, gỡ model trước mỗi bài, 66 bài.

| Nhánh đo | Đạt | Trùng chữ với đối chứng | Tính năng chạy | Trung vị | Lâu nhất |
|---|---|---|---|---|---|
| Đối chứng | 54 | — | — | 4,4 s | 12,0 s |
| Dọn ngữ cảnh, trần 4 000 | 54 | 65/66 | 1 lần | 4,4 s | 12,0 s |
| Đọc văn bản dài | 54 | 65/66 | 2 phần | 4,4 s | 24,0 s |

Đối chứng trùng mốc 41 cả 66/66 câu, nên các nhánh đã gộp không đổi hành vi khi tắt.
Hai tính năng không đổi điểm, nhưng bộ bài gần như không chạm tới chúng nên chưa có bằng chứng lợi hay hại.
Trần 4 000 là cố ý thấp để ép chạm, không phải cấu hình dùng thật.
BFCL trên `b3198ca`: 26/33, giống lần chạy trên nhánh.
