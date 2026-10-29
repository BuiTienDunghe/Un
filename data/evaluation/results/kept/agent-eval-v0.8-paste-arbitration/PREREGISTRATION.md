# Ticket 20 — đợt đo phân xử N1 / C7 (Agent Eval v0.8): đăng ký trước

Viết trước mọi lần chạy. Chủ dự án duyệt 29/10 (qua fable, nguyên văn ở ticket 20, 08:55). Cơ sở: `research-2026-10-29/tong-hop.md`.

## Bản chất

Model đang đọc văn bản dán dài bằng cách lật từng trang, mỗi lượt được lật ba lần, nên không bao giờ tới trang xa. Có hai
cách sửa. Cách thứ nhất (N1) đặt cả văn bản trước mặt model một lần, khi văn bản còn vừa trí nhớ làm việc của nó. Cách thứ
hai (C7) giữ lối lật trang nhưng cho lật bảy lần. Câu hỏi của đợt này: khi đáp án nằm giữa một văn bản dài, model có bỏ sót nó
khi nhận cả văn bản một lúc không. Nếu có, lật trang thắng ở những bài đó và N1 phải lùi ngưỡng. Nếu không, N1 đơn giản và
nhanh hơn, thì bỏ C. Đây là phép thử cơ chế trên nhánh có phiếu #3-C, không phải cổng gộp vào main.

## Nhánh và commit

| Nhánh | Commit | Khác nền ở |
|---|---|---|
| nền | `613f0b2` (`int/20-arb`) = `62e7ca0` + bài v0.8 `0adc697` | — |
| N1 | `d40d4e0` (`int/20-arb-n1`) = nền + `wip/20-paste-inline` `32a2d50` | `pastes.take_pastes`: tin cuối là đoạn dán và ước cả prompt ≤ 12 288 token → nguyên văn |
| C7 | `bc93975` (`int/20-arb-c7`) = nền + `wip/20-paste-rounds` `bc2b8f9` | lượt có đoạn dán được `max_steps` + 4 = 7 vòng công cụ |

Ba commit đều qua test agent/paste/eval/chunk theo luật giữ im (323, 330, 330 qua). Riêng 8 test hỏng sẵn ở
`test_eval_stack_model_version.py`, vì worktree thiếu `DATABASE_URL`.

Ước của N1 = 1 253 + tổng ký tự / 3,3. 1 253 là vòng đầu của stat-01 (bài ngắn nhất) ở `v0.7-3d-iso-base-full`. Theo NV1:
doc-50 ước 10 882 token → nguyên văn; 40 000 ký tự ước 13 403 → phiếu; trần ≈ 36 320 ký tự trong eval.

`int/20-arb` = `94e321f` (phiếu #3-C, nền của #3-D) + main `b100d56` (thêm ticket 27). Không có ticket 27 thì một lệnh công cụ
hỏng làm mất lượt, và N1 đổi prompt cả 15 bài, C7 thêm vòng: lỗi đó sẽ lẫn vào kết quả.

**Nền chạy lại cả 15 bài cũ, không dùng lại `v0.7-3d-iso-base-r1`.** Lý do: nền mới khác `94e321f` ở ticket 27, nên so ba
nhánh trên cùng một commit mới sạch. Giá: khoảng 5 phút GPU. Ticket 27 chưa từng bắn ở r1 cũ, nên dự đoán p1 là 15 câu trả
lời giống hệt; trật thì đó là một phát hiện, và luật vẫn đọc trên lần chạy mới.

## Cách chạy

- qwen3.5:9b, nhiệt độ 0, seed 42, `num_ctx` 16 384, `--probe --gpu-shared no --unload-between-tasks`, GPU riêng.
- Mỗi lần chạy trong một worktree sạch tách ra từ đúng commit (`local-ai-core-wt/meas-<sha>`), qua `run_cold.sh` như #3-D:
  `run_cold.sh <sha> <run_id> ollama_ps.jsonl --tasks <bài> --unload-between-tasks`. Kết quả chép nguyên vào thư mục này.
  Bài của ba lần đủ: doc-39..doc-57 theo thứ tự số. Lần N1 thứ hai: doc-39, 40, 41, 44, 46, 50, 54, 55, 56.
- Thứ tự: nền → N1 → C7 → N1 lần 2. Trước mỗi lần chạy đọc nhiệt độ GPU và hạn tuần; dừng nếu GPU ≥ 85 °C hoặc hạn tuần ≥ 35 %.

| Lần chạy | Bài | Ước thời gian |
|---|---|---|
| `v0.8-arb-base` | 15 bài dán cũ (doc-39..53) + bài mới | ~7 phút |
| `v0.8-arb-n1` | như trên | ~5 phút |
| `v0.8-arb-c7` | như trên | ~9 phút |
| `v0.8-arb-n1-r2` | chỉ bài giữa | ~3 phút |

N1 có lần thứ hai vì nó đưa prompt lên ~11k token. Đến nay r1 = r2 dưới cô lập mới được chứng minh ở prompt ≤ ~6,5k.
Không chạy đủ 62 bài: N1 chỉ chạm tin cuối là đoạn dán, C7 chỉ chạm lượt có đoạn dán, và test đơn vị của NV1 ghim cả hai
(47 bài không dán giữ nguyên messages, `tools_sha256` giữ nguyên).

## Bài

- Cũ: doc-39..53, như v0.7, không đổi một byte (điều kiện P).
- Mới: NV3 viết, NV1 không thấy, `wip/20-paste-tasks-e` `0adc697`. Số liệu theo bảng siêu dữ liệu của NV3:

| Bài | Ký tự | Đoạn | Đoạn đáp án | Vị trí | Kiểu | Đọc lần lượt từ đoạn 0 thì tới ở lần |
|---|---|---|---|---|---|---|
| doc-54 | 27 076 | 19 | 10 | 0,56 | một mảnh, câu hỏi ở đầu | 4 |
| doc-55 | 28 596 | 21 | 10 và 12 | 0,47 và 0,58 | hai mảnh, câu hỏi ở cuối | 4 và 5 |
| doc-56 | 28 058 | 20 | 10 | 0,55 | có mồi ở đoạn 4 (30 ngày, 150.000), câu hỏi ở đầu | 4 |
| doc-57 | 45 166 | 33 | 13 | 0,38 | dài, quá ngưỡng N1, câu hỏi ở cuối | 5 |

  - doc-57 cố ý đặt ở 0,38, ngoài bài giữa. Ở bài này N1 đi đường phiếu như nền, nên nếu tính vào bài giữa thì phép so N1 với
    C7 ở bài giữa bị loãng. C7 đọc tới đáp án ở lần thứ năm; nền và N1 thì không bao giờ tới.
  - Mẫu chấm mới không khớp số đứng sau "-", "–", "~", nên câu đoán khoảng kiểu doc-51 ("3-7 ngày") trượt. Không bài nào có
    `must_not_mention`: ở doc-56, câu nêu cả số mồi lẫn số đúng vẫn đạt. Số mồi vì vậy chỉ ghi riêng.
- **Bài giữa** = mọi mẫu `must_mention` khớp lần đầu ở 40–60 % chiều dài, làm tròn hai chữ số. `analyze.py` tính lại từ tệp bài.
  Bài cũ: doc-39, 40, 41, 44, 46, 50. Bài mới: doc-54, 55, 56. Tổng 9 bài.
  - **R1 chỉ đếm ba bài giữa mù doc-54, 55, 56** (theo bài duyệt của fable về `0adc697`). Mọi người viết code đã thấy sáu bài
    giữa cũ, nên chúng chỉ được báo bên cạnh. N1 lần 2 vẫn chạy cả 9 bài.
  - doc-57 không phải bài giữa.

## Điều kiện trước (P)

Thiếu một điều thì không đọc luật, chỉ báo cáo.

- Ba băm `tools_sha256` (`153209…a75e500`), `agent_guide_sha256`, `system_prompt_sha256` giống nhau ở cả bốn lần chạy.
- Bộ bài `agent-eval-v0.8`, cùng một sha; 15 bài cũ giống hệt v0.7.
- Cả bốn lần chạy có `unload_between_tasks`.
- Manifest phân biệt nhánh: N1 có `paste_inline.max_tokens` = 12 288, C7 có `paste_extra_rounds` = 4, nền không có khoá nào.
- Tập bài giữa tính lại khớp danh sách trên.
- N1 thật sự nạp nguyên: mọi bài trừ bài dài có vòng đầu nhiều hơn nền ≥ 1 000 token. Bài dài: vòng đầu N1 bằng đúng nền.

## Luật

Chặn cắt ngữ cảnh: bài có một vòng nào `tokens_in` > 14 500 ở bất kỳ nhánh nào thì không tính vào luật, báo riêng. Ở mức đó
Ollama có thể đã cắt đầu prompt, và mất câu hỏi trông giống hệt "bỏ sót khúc giữa".

N1 đạt một bài giữa chỉ khi đạt ở cả hai lần chạy.

| Mã | Điều kiện | Kết luận |
|---|---|---|
| R1 | Ở ≥ 2 trong 3 bài giữa mù (doc-54, 55, 56) được tính: C7 đạt, N1 trượt | "Bỏ sót khúc giữa" có thật với 9B: giữ C cho khúc giữa, hạ ngưỡng N1 |
| R2 | Trong 18 bài N1 áp dụng được (trừ doc-57): không bài nào C7 đạt mà N1 trượt. Trong cả 19 bài: không bài nào nền đạt mà N1 trượt | Chọn N1, bỏ C |
| R0 | Không R1, không R2 | Không kết luận; báo cáo kèm vết từng bài, chủ dự án quyết |
| R3 | Vòng đầu N1 ở doc-50 lệch > 15 % so với 10 900 token (ngoài 9 265–12 535) | Tính lại mọi ngưỡng trước khi bàn tiếp; R0–R2 vẫn báo nhưng gắn cờ |

R1 và R2 loại trừ nhau, nên mỗi kết quả rơi vào đúng một trong R1, R2, R0.

Sửa trước lần chạy, theo bài duyệt của fable về `9062a9e`:
- R2 không đếm doc-57. Bài này vượt trần N1 nên N1 đi đúng đường của nền: C7 đọc tới đáp án còn N1 thì không, theo cách dựng.
  Nếu đếm thì R2 gần như không thể xảy ra, và luật trộn câu "N1 có bỏ sót khúc giữa không" với câu "quá trần thì làm gì".
  doc-57 được báo riêng: nhánh nào tới được đáp án.
- Điều kiện "N1 nạp nguyên" chỉ xét token. Một lần đọc đoạn dán dưới N1 (model bịa ra id chưa từng thấy) chỉ được báo, không
  làm hỏng cả đợt.
- Báo cáo in danh sách bài bị loại vì gần cửa sổ ngay cạnh R1/R2, vì bài bị loại dễ là bài khó nhất.

**Kiểm nguồn gốc**: mọi bài đổi đạt/trượt giữa hai nhánh được đọc vết. Một lần đạt mà chuỗi khớp chỉ nằm trong một khoảng đoán
hay câu rào ("khoảng", "tầm", "có thể"), không nêu là số của văn bản, thì ghi là đoán; fable xác nhận. Bài đoán tính là trượt.

## Dự đoán của opus (ý kiến, ghi để đối chiếu)

| Mã | Dự đoán | Lý do |
|---|---|---|
| p1 | Nền: 15 bài cũ giống hệt `v0.7-3d-iso-base-r1` | chỉ khác ticket 27 (r1 không có lỗi nào) và dữ liệu bài |
| p2 | Nền trượt mọi bài mới | đáp án ở đoạn ≥ 10, ba lần đọc chỉ tới đoạn 8 |
| p3 | N1 đạt ≥ 2 bài giữa mới | đoán; rủi ro chính của đợt nằm ở đây |
| p4 | C7 đạt doc-49 và doc-50 | hai bài trượt ở nền chỉ vì hết lượt |
| p5 | N1: bước kiểm số #2 không bắn ở bài nạp nguyên | mọi số trong văn bản đều tính là đã thấy |
| p6 | N1, bài dài: câu trả lời và lệnh công cụ giống hệt nền | cùng đường phiếu, cùng 3 vòng |
| p7 | Không bài nào dừng vì hết 90 giây | ước C7 ~30 s/bài |
| p8 | Trung vị độ trễ N1 < C7 | một vòng so với nhiều vòng |
| p9 | N1 lần 1 = lần 2 trên bài giữa | cô lập; chưa thử ở 11k token |
| p10 | C7: bài nền dừng trước trần thì giống hệt nền | C7 chỉ đổi số vòng, không đổi chữ |

## Ghi riêng (không vào luật)

Số lần #2 bắn mỗi nhánh. Câu trả lời có số mồi (doc-53: 300.000; doc-56: 30 ngày, 150.000). Lỗi lệnh công cụ hỏng. `tokens_in` lớn
nhất mỗi vòng. Độ trễ. Lý do dừng.

Theo hai bài duyệt của fable (29/10 09:20):
- Tỉ lệ ký tự/token thật ở vòng đầu N1 của từng bài. Lần đọc cũ của doc-50 ra 2,79 chứ không phải 3,3. Nếu đúng vậy thì vòng
  đầu doc-50 ≈ 12 600 token, quá trần ước 3 %, và R3 sẽ bật.
- Mọi bài có một vòng > 16 384 token, ở bất kỳ nhánh nào. C7 cộng cả hai lần thử lại thì được 9 vòng ≈ 16,7k, quá cửa sổ.
- Dừng vì `turn_budget` tách riêng khỏi `max_steps`.

## Giới hạn đã biết

- 15 bài cũ đã lộ với mọi người viết code; chỉ bài mới là mù.
- Một lần chạy cho nền và C7. Bài giữa có thêm lần thứ hai cho N1.
- Khoảng 19 bài chỉ bắt được chênh lệch lớn.
- Gộp N1 vào main thì nó đứng trên phiếu #3, trừ khi #3-C cũng gộp.

`analyze.py` cùng thư mục tính mọi điều trên từ các lần chạy.
