GỘP ĐƯỢC (bản sửa đúng quyết định chủ dự án, luật không đổi chữ, `analyze.py` chạy trọn trên dữ liệu thử; chạy lại chỉ sau khi nhánh runner `wip/20-eval-isolate` được duyệt và gộp)

# Duyệt bản sửa đăng ký #3-D — `kept/agent-eval-v0.7-paste-nudge-search/PREREGISTRATION.md` + `analyze.py` + `kept/README.md`, commit 28df7c7 — fable 5.1, 28/10/2026

Đối chiếu diff 347194a..28df7c7 với quyết định chủ dự án (cách 2, nguyên văn ở `paste-directions-2026-10-28.md`), với
quyết định "vậy bỏ" và bài duyệt `wip-20-paste-search-92f5796.md`, với bài duyệt bản gốc `prereg-20-3d-347194a.md`. Không
chạy model.

## Từng chỗ đổi so với bản đã duyệt

| Chỗ đổi | Kiểm | Kết quả |
|---|---|---|
| Luật B1–B4, C1–C4 | diff phần luật | **không đổi chữ**; chỉ thêm câu "B đạt nghĩa là gộp cả phiếu #3-C…" đúng ghi chú 1 của tôi |
| Quy trình: gỡ model trước **mỗi** bài kể cả bài đầu, chờ `/api/ps` trống, nạp lại không prompt; manifest `unload_between_tasks: true`, mỗi dòng `reload_ms`; tên lần chạy `v0.7-3d-iso-*`; ~45 phút | đúng cách 2 chủ dự án chọn; ước lượng hợp lý (214 bài × vài giây gỡ/nạp cộng ~25 phút cũ) | đúng; **phụ thuộc nhánh runner chưa duyệt** (xem dưới) |
| Điều kiện mới `unload_between_tasks: true` ở mọi manifest | `analyze.py` `preconditions["unload_between_tasks"]` kiểm `is True` ở cả 8 manifest | khớp |
| Nhánh +1+3' dùng 92f5796; dự đoán viết lại: tìm được gọi ở dưới nửa 12 bài cần phần giữa; doc-49/50 vẫn trượt (C3 sai); doc-53 cùng đạt/trượt với +1; báo cáo tách "không gọi tìm" khỏi "tìm không ra" | so với ghi chú ở bài duyệt 92f5796 | đúng từng ý; C3/C4 giữ nguyên nên "C trượt vì không ai gọi tìm" là kết quả dự đoán, không phải thất bại của phép đo |
| Bỏ dự đoán "nền trùng #3-C phía sau"; thay bằng "nền doc-41, doc-51 trùng hai lần chạy riêng trong `diagnostics/`" | #3-C là số theo chuỗi; lần chạy riêng đã dùng đúng quy trình "gỡ rồi nạp" | đúng; đây là phép kiểm **chính** cho câu "gỡ rồi nạp = chạy riêng" |
| Điều kiện 47 bài không ngoại lệ | script so cả 47 câu trả lời + chuỗi công cụ | đúng; với cô lập từng bài không còn lý do cho ngoại lệ |
| Kiểu trượt "mất lượt vì lệnh công cụ hỏng" | `lost_turn_errors` đọc trường `error`; vẫn tính trượt | đúng; doc-51 theo chuỗi là ví dụ |
| Ghi chú "số theo chuỗi" ở `kept/README.md` | đoạn mới | đủ ý: mọi lần trước là số theo chuỗi, "r1 = r2" chỉ đúng cùng chuỗi, so nhánh chỉ sạch tới bài đầu tiên khác, không so với lần chạy có cờ; mốc 62 bài mới là lần đủ bộ ở nền |
| `analyze.py` chạy trọn | tôi sao chép 5 lần chạy theo chuỗi vào scratchpad, đổi tên thành `iso-*` (nhánh +1+3' và lần đủ +1+3' dùng bản sao làm chỗ giữ), gắn cờ giả, chạy | exit 0, in đủ điều kiện, luật, dự đoán, `lost_turn_errors`, `reload_ms` (None khi thiếu trường). Trên dữ liệu theo chuỗi, B4 bác đúng ca doc-51 trượt→đạt không có lời nhắc — bộ chặn quy nguyên nhân làm việc |

## Ghi chú

1. **Chạy lại chỉ sau khi nhánh runner được duyệt.** Bản này hứa ba điều runner phải làm (gỡ trước mỗi bài kể cả bài đầu,
   chờ `/api/ps` trống, nạp lại không prompt) và hai trường mới (`unload_between_tasks`, `reload_ms`). Tôi sẽ kiểm ở
   `wip/20-eval-isolate`: đúng ba điều đó; không đổi gì model thấy (`tools_sha256`, `AGENT_GUIDE`, prompt); `--probe` chạy
   trước lần gỡ đầu hay sau, phải ghi rõ vì dự đoán "trùng lần chạy riêng" phụ thuộc vào đó; test cho thứ tự gỡ/nạp theo bài.
2. **Hai tầng kiểm cô lập, đọc theo thứ tự:** (a) nền doc-41/doc-51 trùng lần chạy riêng; (b) +1 sáu bài không bật lời nhắc
   trùng nền từng byte. (a) sai thì "gỡ rồi nạp" chưa bằng "chạy riêng", nhưng ba nhánh vẫn so được với nhau vì cùng quy
   trình — không phải điều kiện dừng, báo cáo nói rõ. (a) đúng mà (b) sai thì nhánh +1 đổi thứ model thấy ở bài không bật
   lời nhắc — khi đó dừng và tìm nguyên nhân trước khi đọc luật. r1 ≠ r2 trong cùng nhánh dưới cô lập là một nguồn ngẫu nhiên
   mới, luật "lần tệ hơn" vẫn xử được nhưng phải báo.
3. Số theo chuỗi: khi báo cáo trích bất kỳ số nào trước 29/10 (kể cả 9/15, 10/15, 50/62 trong thư mục này), kèm hai chữ
   "theo chuỗi" ngay cạnh số.

## Nhỏ, không chặn

- `agent-eval-run-conditions.json` (điều kiện các lần chạy cũ) có thể thêm một dòng trỏ tới đoạn README mới; tuỳ opus.
- `__pycache__` như mọi lần.
