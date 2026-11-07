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

## Bổ sung 08/11, khoảng 02:00, sau khi Fable duyệt commit b7457d5

Lúc viết phần này mới có ba kết quả: hai lần kiểm 81 bài của 9B đều cho ra đúng như ngày 07/11 ở cả 81/81 bài, và LFM3 chạy trần simple_python đạt 359/400. Những thay đổi dưới đây không chạm tới ba kết quả đó.

- **Kiểm 20 bài multi_turn_base của 9B.** Nếu có bài nào khác ngày 07/11, nhánh harness của 9B chạy lại đủ 200 bài và không dùng lại 159 bài cũ. Luật này giống luật của phép kiểm 81 bài.
- **Bài lỗi.** Một job có hơn 5 % số bài mang trường `error` thì bị coi là hỏng và chạy lại một lần. Số bài lỗi của mỗi job được báo kèm kết quả.
- **Giới hạn thời gian mỗi job.** Khoảng 10 lần thời gian 9B cần. Quá giới hạn thì job bị huỷ, coi là hỏng và chạy lại một lần.
- **Digest.** Manifest của Agent Eval không ghi digest. Bộ điều phối ghi digest của cả ba model vào `progress.log` khi bắt đầu.
- **Tham số.** Nhánh harness gửi `top_p 0.9` lấy từ cấu hình của 9B cho mọi model. Ở nhiệt độ 0, model luôn chọn chữ có xác suất cao nhất, nên `top_p` không đổi kết quả. Câu "các tham số khác giữ mặc định của từng model" ở trên chỉ đúng với nhánh trần.
- **Khởi động lại bộ điều phối** để nạp các thay đổi trên. Job đang chạy dở sẽ được chạy lại từ đầu; job đã xong được bỏ qua.

## Bổ sung 08/11, 05:21: bỏ các job 9B nhiều lượt

Chủ dự án yêu cầu: "không cần chạy 9B". Lúc đó 9B đã xong các job sau, và các job này được giữ: kiểm 81 bài ở cả hai nhánh, irrelevance ở cả hai nhánh, Agent Eval (57/66). Chưa có số nào của model nhỏ trên multi_turn_base.

- **Bỏ ba job.** Ba job còn lại của 9B là multi_turn_base nhánh trần (200 bài), 41 bài còn thiếu của nhánh harness, và 20 bài kiểm. Mỗi job được đánh dấu bằng một `done.json` có `"status": "skipped"`. Bộ điều phối bỏ qua job khi gặp tệp này, nên không phải khởi động lại, và Agent Eval của 2B đang chạy không bị mất.
- **Hệ quả cho multi_turn_base:**
  - Model nhỏ ở nhánh harness chỉ so được với 9B trên 159 bài đo ngày 07/11. 159 bài này không có phép kiểm 20 bài. Căn cứ để dùng chúng: phép kiểm 81 bài cho kết quả giống hệt ngày 07/11, cùng Ollama 0.40.13 và cùng digest.
  - Không có 9B chạy trần, nên câu hỏi 2 (harness nâng hay hạ điểm) không trả lời được cho 9B ở loại bài này. Model nhỏ chạy trần cũng không có mốc 9B để so.
- **Luật "đáng thử tiếp" không đổi.** Luật này không dùng multi_turn_base.

## Giới hạn đã biết

- BFCL là bài tiếng Anh. Phần tiếng Việt chỉ có Agent Eval, một bộ tự viết.
- Đo ở nhiệt độ 0, trong khi Ún ship ở 0,4.
- Lời dặn của harness được viết cho 9B, nên model nhỏ có thể thiệt.
- Ba model khác cách lượng tử: 2B là Q8_0, hai model kia là Q4_K_M. Đây là bản Ollama mặc định của từng model.
