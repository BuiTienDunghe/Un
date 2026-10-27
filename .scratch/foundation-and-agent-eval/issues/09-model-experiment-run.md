# 09 — Thí nghiệm model M3: hướng B, bắt đầu bằng nhánh 0

Status: chờ — đăng ký trước đang viết (fable 5.1); chạy sau ticket 11
Type: task
Blocked by: 08 (xong), 11 (sàn dao động 788 câu); cần stack heldout + lab

## Quyết định của chủ dự án (27/10)

Chọn **B** (`m3-target.md`): bắt đầu bằng **nhánh 0** — thêm chỉ dẫn phía truy vấn cho model
embedding hiện tại, không tải gì, không re-index. Chủ dự án duyệt trước việc tải `multilingual-e5-large`
(Hugging Face, ~1,1 GB fp16) và llama.cpp (`convert_hf_to_gguf.py`) **khi tới bước cần** — tức chỉ sau
khi nhánh 0 có kết quả và bước đổi model thật sự được bắt đầu.

## Thứ tự

1. **Đăng ký trước** (fable 5.1 viết, trước khi đo bất cứ gì): giả thuyết của nhánh 0 và của B, tập đo,
   lệnh chạy chính xác, control (cấu hình nào, vì sao), điều kiện dừng dùng sàn dao động của ticket 11,
   cách ghi chỉ dẫn truy vấn vào registry mà `python -m app.config.model_registry --check` chấp nhận
   (sửa `embedding-v0` tại chỗ hay thêm phiên bản mới dùng chung collection — mục "Chưa kiểm" của
   `m3-target.md`). Ghi vào `.scratch/foundation-and-agent-eval/m3-preregistration.md`.
2. **Nhánh 0**: thực hiện theo đăng ký trước; báo kết quả cả hai chiều.
3. **B đầy đủ** (chỉ khi bước 2 xong): script đóng gói commit trước (`scripts/build_embedding_model.py`
   theo mẫu `build_ocr_model.py`), tải e5-large + llama.cpp, kiểm đóng gói bằng mteb VieQuAD (±0,02 của
   0,6112, lệch xa = thí nghiệm vô hiệu), rồi chạy theo đăng ký trước.

Chỉ giữ thay đổi nào vượt sàn dao động đã đo ở ticket 11.

## Comments
