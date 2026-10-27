# 15 — Ghi phiên bản runtime embedding, nhúng lại sau khi nâng Ollama (để sau)

Status: chờ — ngoài phạm vi 09; làm sau M3
Type: task
Blocked by: —

## Vì sao

Ticket 09 (27/10) đo được: cùng model `qwen3-embedding:0.6b` (digest `ac6da0dfba84`), cùng văn bản, cùng
đường gọi, nhưng vector passage nhúng 27/10 lệch bản 08/09 (min cosine 0,99912 trên 3 896 đoạn). Nghi
nguyên nhân là Ollama 0.33.2 → 0.40.8 hoặc số học GPU/driver. Production đang ở trạng thái "passage nhúng
runtime cũ, truy vấn nhúng runtime mới"; ticket 11 thấy 2 câu đổi hạng so với 08/09 là cùng hiện tượng.
Không hỏng, nhưng không ai biết khi nào nó xảy ra, vì không nơi nào ghi phiên bản runtime.

## Việc

1. `rebuild_qdrant` và manifest/report eval (`eval_heldout`, `evaluate_rag`, `agent_eval`) ghi phiên bản
   Ollama (`/api/version`).
2. Một kiểm tra rẻ: khi phiên bản Ollama lúc chạy khác phiên bản ghi lúc nhúng collection, in cảnh báo.
3. Quy trình (docs): sau mỗi lần nâng Ollama, nhúng lại collection production rồi chạy cổng 82 câu.

## Comments
