# 13 — Chuẩn bị đóng gói e5-large cho B đầy đủ (chỉ code, không tải, không GPU)

Status: đã giao — Nhân viên của Ún 1
Type: task
Blocked by: — (chạy thật thuộc ticket 09, sau Bước 6 của nhánh 0)

## Vì sao

`m3-preregistration.md`, mục "B đầy đủ", đòi hai thứ commit **trước** khi tải hay đo e5: script đóng
gói ghim sha, và tuỳ chọn tiền tố hai phía cho `run_mteb.py`. Viết chúng lúc GPU đang bận cho nhánh 0
không làm lệch phép đo nào. Chủ dự án đã duyệt tải e5-large + llama.cpp **khi tới bước cần**; ticket
này không tải gì.

## Việc

1. `backend/scripts/build_embedding_model.py` theo mẫu `build_ocr_model.py`: nhận đường dẫn checkpoint
   HF đã tải và `convert_hf_to_gguf.py` của llama.cpp; ghim sha nguồn HF và sha GGUF đích; viết
   `data/models/embedding/embedding-e5l-v1/Modelfile`; in lệnh `ollama create`. Có `--dry-run`.
   Test với file giả, không cần mạng hay Ollama.
2. `training/common/run_mteb.py`: thêm tuỳ chọn tiền tố query/passage hai phía (e5 cần `query: ` /
   `passage: `), giữ nguyên hành vi mặc định (chỉ dẫn kiểu Qwen). Test rằng mặc định không đổi.
3. Ghi vào Comments: lệnh tải chính xác (repo HF, revision, kích thước ước lượng), để lúc tới bước chỉ
   cần chủ dự án xác nhận lại.

## Không làm

Không tải model, tokenizer hay llama.cpp; không gọi Ollama; không sửa `model_versions.yaml` (record
`embedding-e5l-v1` đã có).

## Comments
