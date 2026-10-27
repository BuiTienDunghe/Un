# Đợt đo GPU gom chung — kế hoạch chờ chủ dự án duyệt (opus 5.5, 28/10/2026 02:15)

## Thật ra chuyện này là gì

Đêm 28/10 chủ dự án dặn "xây trước, đo sau", nên mọi thay đổi đã gộp mà cần chạy model thật để kiểm đều được
**đăng ký trước** (viết ra dự đoán và luật quyết định trước khi thấy số) rồi để dành. Tệp này gom chúng lại thành
một đợt: chạy lần nào, trên phiên bản code nào, mất bao lâu, theo thứ tự nào. Chủ dự án duyệt một lần là chạy được
cả đợt. Các số này là của bộ bài nội bộ (test hồi quy), không phải bằng chứng chất lượng.

## Điều kiện trước khi chạy

- GPU rảnh: phiên Quản lý đã báo xong, hoặc chủ dự án cho dùng chung. Nhiệt độ GPU dưới 85 °C.
- Gỡ luật "Giữ im Ollama" (mục trong `coordination.md`) — chỉ chủ dự án hoặc opus khi chủ dự án đồng ý.
- Mỗi lần chạy: cây sạch trên đúng commit (worktree riêng), `ollama stop qwen3.5:9b` và ghi `/api/ps` ngay trước,
  `--probe --temperature 0 --seed 42`, chạy từng lần một. Một lần v0.3 lạnh mất khoảng **3–4 phút** (đo: 3 phút 11 giây
  ở `v0.3-read-B-r1-cold`).

## Đợt A — hồi quy harness (khoảng 25–30 phút GPU)

| # | Kiểm cái gì | Commit chạy | Số lần | Đăng ký trước | Luật ship tóm tắt |
|---|---|---|---|---|---|
| A1 | Ticket 20 #2: kiểm con số trong câu trả lời | 86c419c (gộp #2) | 2 lạnh | `kept/agent-eval-v0.3-answer-check/PREREGISTRATION.md` | không bài đạt nào ở #1-B thành trượt, doc-10 hết số bịa |
| A2 | Ticket 20 #3: đoạn dán dài | 80cd369 (gộp #3) | 2 lạnh | `kept/agent-eval-v0.3-pastes/PREREGISTRATION.md` | 47 bài kia không đổi chữ, doc-39 tới được agent và mở đoạn dán bằng `read_document` |
| A3 | Ticket 22 C4: registry cắm được | trước C4 = `79065d7^1`, sau C4 = 79065d7 | 1 + 1 lạnh, cùng buổi | `kept/agent-eval-v0.3-c4-registry/PREREGISTRATION.md` | cùng `tools_sha256`, 48/48 câu trả lời trùng từng chữ |
| — | Ticket 20 #4: báo tiến độ | — | 0 | không cần (fable): `on_step` không chạm prompt, `tools_sha256` không đổi | — |

Thứ tự A1 → A2 → A3 giữ đúng chuỗi so của các bản đăng ký (#1-B → #2 → #3). Nếu A1 trượt luật thì vẫn chạy A2, A3:
các bản đăng ký so với mốc của riêng chúng, và code đã nằm trên main — trượt nghĩa là opus đề xuất lùi hoặc sửa,
chủ dự án quyết.

## Đợt B — mốc v0.4 (khoảng 8 phút, khi Nhân viên 3 xong bộ chấm v0.4)

Hai lần lạnh (`v0.4-base-r1-cold`, `v0.4-base-r2-cold`) trên main có bộ chấm v0.4 (gộp 96f86a8), theo đăng ký trước
trong `issues/20-agent-capabilities.md` (Nhân viên 3, 02:00). Không có luật ship; dự đoán r1 trùng r2 và doc-39 lần đầu
đi qua phần dán dài của #3. Chưa có bài L-b, L-c (chủ dự án chọn).

## Đợt C — thí nghiệm model e5-large (khoảng 3 giờ GPU)

Ba nhánh của ticket 09 trên `wip/09-e5-full` (caa602d), theo `m3-preregistration.md`. Dài nhất, nên tách riêng
và cần hỏi khung giờ với phiên Quản lý.

## Đợt D — BFCL (chưa chạy được)

Chờ chủ dự án chọn chỗ cắm, nhiệt độ, và cho cài venv (`ticket24-design.md`). Mỗi lần tập con 33 bài ước khoảng
7 phút (chưa đo).

## Chưa làm / giới hạn

- Thời gian A, B là ước từ một lần đo v0.3; lần lạnh đầu mỗi buổi có thể lâu hơn vì nạp model.
- A1–A3 chạy trên commit cũ: số đo nói về đúng thay đổi đó, không phải về main hiện tại. Một lần v0.3 trên main mới
  nhất có thể thêm sau nếu chủ dự án muốn mốc tổng.
