# Đăng ký trước: model nhỏ, khi chạy trần và khi chạy trong harness (08/11/2026)

Tệp này được viết và commit trước khi chạy đo. Chưa có số nào ngoài 9 bài chạy thử ở mục "Chạy thử" dưới đây.

## Câu hỏi

1. LFM3-1.7B và Qwen3.5-2B, khi chạy trần và khi chạy trong harness của Ún, gọi công cụ đúng lúc đến đâu so với qwen3.5:9b, model đang ship?
2. Với từng model, harness nâng hay hạ điểm so với chạy trần?
3. Có model nhỏ nào đủ tốt để thử ở một vai trò của Ún (cách D: chia việc theo vai trò) không? Quyết định là của chủ dự án.

## Điều kiện

| | |
|---|---|
| Model | `qwen3.5:9b` 6488c96f (Q4_K_M); `lfm3:1.7b` b36a103f (Q4_K_M, Liquid AI, cần Ollama ≥ 0.40.13); `qwen3.5:2b` 324d162b (Q8_0) |
| Ollama | 0.40.13. Phiên bản được ghi lại trước và sau mỗi lần chạy |
| Sinh chữ | nhiệt độ 0, seed 42, ngữ cảnh 16 384, tắt suy nghĩ; gỡ model trước mỗi bài. Các tham số khác giữ mặc định của từng model, ví dụ LFM3 có repeat_penalty 1,1 và Qwen có presence_penalty 1,5 |
| Nhánh trần | `bfcl_bare.py --model`: vòng lặp gốc của BFCL, gọi qua `/v1` |
| Nhánh harness | `bfcl_run.py --model`: AgentService giữ nguyên như khi ship, gồm AGENT_GUIDE hiện tại (vẫn còn câu đã làm 9B tụt điểm, xem `docs/SO_DO.md` ngày 07/11), 3 vòng mỗi lượt, bộ kiểm số. Chỉ đổi model ở vai trò general |
| Bài | BFCL v4: simple_python 400, irrelevance 240, multi_turn_base 200. Agent Eval v0: 66 bài, chỉ chạy nhánh harness |
| 9B làm mốc | simple_python: chạy lại 81 bài ở mỗi nhánh. Nếu khác ngày 07/11 dù chỉ một bài, nhánh đó chạy lại đủ 400 bài. multi_turn_base nhánh harness: dùng 159 bài ngày 07/11, chạy nốt 41 bài, và chạy lại 20 trong 159 bài để kiểm. Phần còn lại chạy mới cùng đêm |
| Không probe | Stack Docker đang tắt, nên không dùng `--probe`. Model được xác định bằng tên và digest trong manifest |
| Bộ điều phối | `run_small_models.py` trong thư mục này. Một job chỉ coi là xong khi có đủ bài. Job harness hoặc Agent Eval từng bị tạm dừng thì chạy lại cả job |

## Chạy thử (08/11, trước khi đăng ký, không tính vào kết quả)

Mỗi model chạy 9 bài: simple_python 4, irrelevance 3, multi_turn_base 2. Mục đích là kiểm runner và định dạng lệnh gọi công cụ của LFM3. Ollama đọc đúng lệnh gọi của LFM3.

| | simple | irrelevance | multi |
|---|---|---|---|
| LFM3 trần | 4/4 | 1/3 | 1/2 |
| LFM3 harness | 4/4 | 1/3 | 0/2 |
| Qwen 2B trần | 1/4 (trả lời bằng chữ) | 3/3 | 0/2 |
| Qwen 2B harness | 4/4 | 0/3 | 0/2 |

## Dự đoán

Đơn vị là điểm %. Mốc 9B ngày 07/11 trên simple_python: trần 91,75, harness 88,0.

| Hạng mục | LFM3 trần | LFM3 harness | Qwen 2B trần | Qwen 2B harness |
|---|---|---|---|---|
| simple_python | 85–93 | 82–92 | 40–70 | 75–88 |
| irrelevance | 60–85 | 55–80 | 75–95 | 40–70 |
| multi_turn_base | 15–35 | 8–25 | 3–15 | 3–15 |
| Agent Eval (9B dự đoán 54–58/66) | — | 35–50/66 | — | 25–45/66 |

Lý do:
- LFM3 được hãng huấn luyện để gọi công cụ (hãng tự báo BFCL V4 71,39). Trong 4 bài chạy thử nó gọi đúng cả 4.
- Qwen 2B khi chạy trần hay tự giải bằng chữ. Harness kéo nó sang gọi công cụ, nên dự đoán harness giúp simple_python nhưng làm hại irrelevance.
- Ở nhiều lượt, model nhỏ yếu: hãng LFM3 tự dặn không dùng cho việc nhiều bước phức tạp. Harness 9B ở loại bài này hiện chỉ đạt 31/159.
- Agent Eval là bài tiếng Việt, dùng lời dặn dài. Model nhỏ làm theo lời dặn dài kém hơn.

## Phân tích

- **So sánh.** Mỗi cặp được so từng bài. Có 4 loại cặp: trần với harness của cùng model; model nhỏ với 9B ở cùng nhánh; LFM3 với Qwen 2B. Dùng McNemar chính xác, báo số bài chỉ bên này đạt và số bài chỉ bên kia đạt.
- **Agent Eval.** Báo số bài đạt và từng bài khác 9B. Đây là test hồi quy của dự án, không phải benchmark chính thống.
- **Thời gian.** Báo giây mỗi bài của từng nhánh, đo từ log.
- **Luật "đáng thử tiếp", đặt trước.** Một model nhỏ chỉ đáng thử ở một vai trò của Ún nếu nhánh harness của nó đạt cả bốn điều kiện sau:
  - simple_python ≥ 9B harness − 5 điểm;
  - irrelevance ≥ 9B harness − 5 điểm;
  - Agent Eval ≥ 9B − 6 bài;
  - không có bài Agent Eval loại no_tool nào gọi công cụ.

  Luật này chỉ để chọn ứng viên thử tiếp, không phải để ship. Ship còn cần đo D1 và bài chat tiếng Việt.

## Giới hạn đã biết

- BFCL là bài tiếng Anh. Phần tiếng Việt chỉ có Agent Eval, một bộ tự viết.
- Đo ở nhiệt độ 0, trong khi Ún ship ở 0,4.
- Lời dặn của harness được viết cho 9B, nên model nhỏ có thể thiệt.
- Ba model khác cách lượng tử: 2B là Q8_0, hai model kia là Q4_K_M. Đây là bản Ollama mặc định của từng model.
