GỘP ĐƯỢC (vào int/20-arb cho nhánh đối chứng C7; không gộp main trước khi đo)

# Duyệt wip/20-paste-rounds bc2b8f9 (ticket 20 phân xử, C7: lượt có đoạn dán được 7 vòng công cụ) — fable 5.1, 29/10/2026

Đã kiểm: diff 62e7ca0..bc2b8f9 (4 tệp: `agent_service.py` +9 trong đó 1 dòng logic, `agent_eval.py` +4 dòng manifest,
2 tệp test +85). Bộ giữ im, không gọi Ollama, không chạy model. Đối chiếu với tong-hop.md mục "Đề xuất".

## Kiểm độc lập

| Kiểm | Kết quả |
|---|---|
| Nền 62e7ca0 | như bài duyệt N1 |
| `rounds = max_steps + 4` khi lượt có đoạn dán (tin cuối hoặc lịch sử, tức `pastes` không rỗng); lượt thường vẫn 3 | đúng; `pastes` lấy từ `take_pastes` ngay đầu `run` |
| Thử lại của ticket 27 và của #2 vẫn cộng thêm một vòng mỗi cái | đúng; test ghim 7 + 1 cho từng loại; tối đa 3 + 4 + 1 + 1 = 9 vòng |
| Lượt kết thúc trong 3 vòng: gửi model đúng những tin như trước | test chạy cùng lượt với hằng 4 và 0, kết quả trùng |
| Guide, tools, phiếu không đổi; guide không nêu số lượt | diff không đụng; test ghim `tools_sha256`; câu ép "Đã dùng tối đa số lượt công cụ" giữ nguyên |
| Test | 389 xanh, 13 bỏ qua ở worktree NV1, HEAD bc2b8f9 sạch; test doc-49 "đáp án ở lần đọc thứ tư" chạy thật qua runner |
| "Mỗi phần hỏng → có test đỏ" | tự làm hỏng 3 trong 6 phần trên bản sao: cộng vòng cho mọi lượt → 1 đỏ; 3 vòng thay vì 4 → 4 đỏ; chỉ khi tin cuối là đoạn dán → 1 đỏ. 3/3 đúng |
| Cửa sổ 16 384 có chứa 7 lần đọc không | từ lần chạy cô lập cũ: vòng 1 ≈ 1 850, mỗi lần đọc 3 đoạn ≈ 1 650 → 7 lần ≈ 13,4k; 8 lần ≈ 15,1k; **9 lần (cả hai thử lại) ≈ 16,7k, quá cửa sổ** |
| Hạn 90 s mỗi lượt có đủ 7 vòng không | độ trễ cũ: vòng đọc 2–5 s, vòng chốt 6–10 s → 7 vòng ≈ 30–40 s, dưới 70 s dùng được; không chạm `turn_budget` trong điều kiện thường |

## Nhận xét

- **Đúng vai nhánh đối chứng cơ chế:** một dòng logic, đúng chỗ, và chỉ bật khi lượt có gì để đọc tiếp. Không kết hợp
  với N1 trong lần đo này; nếu sau này gộp cả hai thì ở bài dán vừa cửa sổ `pastes` rỗng nên C7 tự tắt, nhất quán.
- **Ca 9 vòng là điểm phải nhìn trong báo cáo:** khi cả thử lại ticket 27 lẫn #2 cùng bật, prompt có thể vượt 16 384 và
  Ollama cắt phần đầu (system prompt, guide) mà không báo. Hiếm, nhưng báo cáo nên liệt kê mọi bài có `tokens_in` vòng
  nào > 16 384 và mọi lượt dừng vì `turn_budget`, tách riêng khỏi `max_steps`.
- Đọc 7 lần tới đoạn 20 (~27 000 ký tự): bài mù > 40 000 ký tự của NV3 sẽ vẫn ngoài tầm cả hai nhánh, đúng chủ ý "để thấy
  nhánh dự phòng".

## Nhỏ, không chặn

- Test `Router` giờ ném được exception theo kịch bản: hữu ích cho cả test ticket 27 sau này.
- `__pycache__` như mọi lần.
