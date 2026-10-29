GỘP ĐƯỢC (vào int/20-arb cho nhánh đo N1; không gộp main trước khi đo)

# Duyệt wip/20-paste-inline 32a2d50 (ticket 20 phân xử, N1: đoạn dán cuối vào nguyên văn khi ước lượng còn vừa cửa sổ) — fable 5.1, 29/10/2026

Đã kiểm: diff 62e7ca0..32a2d50 (4 tệp: `pastes.py` +30, `agent_eval.py` +3 dòng manifest, 2 tệp test +142). Bộ giữ im,
không gọi Ollama, không chạy model. Đối chiếu với tong-hop.md mục "Đề xuất" và lời duyệt của chủ dự án (sáng 29/10).

## Kiểm độc lập

| Kiểm | Kết quả |
|---|---|
| Nền 62e7ca0 = main b100d56 + phiếu #3-C | `git diff b100d56 62e7ca0` chỉ `pastes.py` + test của nó; đúng nền đã duyệt |
| Chỉ tin cuối mới được giữ nguyên; đoạn dán trong lịch sử vẫn là phiếu và được tính vào ước lượng **bằng phiếu** | đúng (`whole = index == len-1 and prompt_tokens([*shown, message]) <= INLINE_MAX_TOKENS`); `shown` đã chứa phiếu của các tin trước |
| Tin giữ nguyên không có id, `read_document` với id đó trả `NOT_READABLE` | test ghim; đúng ý "không có gì để mở" |
| `PASTE_THRESHOLD`, phiếu, `AGENT_GUIDE`, `tools` không đổi | diff không đụng; test ghim `tools_sha256` `153209…a75e500`; guide không nhắc đoạn dán hay số lượt |
| Hằng: `INLINE_MAX_TOKENS` 12 288 = 16 384 − 4 096; general v0 `context: 16384` (`model_versions.yaml:44`) | khớp; là hằng cứng, đổi num_ctx phải đổi tay (đã ghi trong chú thích) |
| `INLINE_FIXED_TOKENS` 1 253 = tokens_in vòng 1 của stat-01 trong `v0.7-3d-iso-base-full` | đúng từng số; ước lượng cho stat-01 ra 1 291, dư +38 về phía an toàn như commit nói |
| Sai số ước lượng trên 62 bài của lần chạy đó (phiếu như lúc đo) | −49 (doc-49) … +156 (hist-06), trung vị +40; đúng với commit |
| `CHARS_PER_TOKEN` 3,3 so với văn bản dán thật | tính lại từ 24 vòng đọc của 15 bài dán: trung vị 3,29; **doc-50 thấp nhất 2,79** (văn bản dày chữ hơn) |
| Trần 36 415 / 36 416 ký tự; doc-50 31 681 ký tự → 10 882 token, vào nguyên văn; 40 000 → phiếu | test ghim; tôi tính lại trùng |
| 15 bài dán v0.7 đều vào nguyên văn trong eval | tính lại với system prompt 95 ký tự của eval: 15/15 dưới trần, lớn nhất doc-50 |
| Test | 389 xanh, 13 bỏ qua (test_agent*.py) ở worktree NV1, HEAD 32a2d50 sạch |
| "Mỗi phần hỏng → có test đỏ" | tự làm hỏng từng phần trên bản sao: bỏ điều kiện tin cuối → 3 đỏ; bỏ phần cố định → 5 đỏ; tính lịch sử bằng nguyên văn thay vì phiếu → 1 đỏ; không bao giờ giữ nguyên → 4 đỏ; bỏ ước lượng → 6 đỏ. 5/5 đúng như commit |

## Nhận xét

- **Đúng cơ chế đã thống nhất, đúng kích cỡ (~20 dòng), không đụng vòng lặp agent.** N1 và C7 khác nền đúng một cơ chế
  mỗi nhánh, nên phép so ba nhánh là sạch.
- **Số liệu phải ghi trong báo cáo đo:** `tokens_in` vòng 1 của doc-50. Ước lượng 10 882 dựa trên 3,3 ký tự/token, mà
  chính văn bản doc-50 đo được 2,79 trong lần chạy cũ; nếu đúng vậy thì vòng 1 của doc-50 ≈ 12 600 token, **vượt trần
  12 288 khoảng 3 %** nhưng vẫn dưới cửa sổ 16 384 (chỗ dự trữ cho câu trả lời còn ~3 800). Luật 3 của bản đăng ký (lệch
  > 15 % so với 10,9k → tính lại ngưỡng) là đúng chỗ; báo cáo nên ghi cả tỉ lệ ký tự/token thực của từng bài dán.
- Bước kiểm số #2 coi đoạn dán nguyên văn là "đã thấy": commit đã ghi, là điểm phải nhìn ở bài có số mồi (doc-53).
- Áp cho cả Discord vì đi cùng `chat_service` → `agent_service.run`; phần đầu gán tên người nói được tính vào ước lượng.
  Không phải việc của lần đo này.
- Gộp main hay không là chuyện sau khi đo, theo luật đã đăng ký; không phải của bài duyệt này.

## Nhỏ, không chặn

- `whole` được tính cho mọi tin, kể cả tin không phải đoạn dán (rẻ, vô hại); nếu muốn gọn thì tính sau `is_paste`.
- `__pycache__` như mọi lần.
