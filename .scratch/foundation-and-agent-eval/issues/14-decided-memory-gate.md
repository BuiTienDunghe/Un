# 14 — Cắm model "decided" của chủ dự án làm cổng trí nhớ (để sau)

Status: chờ — chưa làm cho tới khi decided có đầu vào/đầu ra rõ (chủ dự án, 27/10)
Type: research
Blocked by: đầu vào/đầu ra của decided; sau M3/M4

## Vì sao

Chủ dự án (27/10) có thể đưa model "decided" của mình vào để quyết định tin nào vào phần trí nhớ
nào. Trong bốn tầng của `docs/memory_design.md`, tầng 1 (sổ gốc) chép mọi tin, không cần ai quyết; chỉ
tầng 3 (bản rút gọn) và tầng 4 (sổ cái sự việc) có chuyện chọn lọc. Nguyên tắc "tầng dưới không bao giờ
mất" làm việc cắm này ít rủi ro: decided quyết sai thì tin gốc vẫn còn ở sổ gốc.

**Chưa chọn cách cắm.** Ba cách (A gác cổng ghi/bỏ, B chọn ngăn, C thay bộ trích) thực chất là ba hình
dạng đầu ra; chọn trước khi biết decided ra gì là chọn ngược.

## Đã có sẵn khi tới lúc làm (kiểm 27/10)

| Thứ | Ở đâu | Đủ cho |
|---|---|---|
| 150 ca có nhãn: `expected_operation` (no_op 50, create 90, update 6, delete 4), `expected_fact_key` | `backend/tests/fixtures/discord_memory_extractor_benchmark_v1.json` | chấm mức "ghi/bỏ" ngay; mức "chọn ngăn" chỉ cho bộ khoá **v1** (thiếu 3 khoá v2: sinh nhật, đồ uống, món ăn) |
| Runner benchmark | `backend/scripts/benchmark_discord_memory_extractor.py` | đo bộ trích hiện tại làm control |
| Registry model (vai trò, phiên bản, `active`, fallback) | `backend/app/config/model_versions.yaml`, `docs/model_registry.md` | cắm decided thành một vai trò mới, đổi phiên bản bằng restart |
| Mốc 9b ở việc "biết im lặng" | `m3-target.md` (no_op 0,86 của 9b; 0,52 của 2B) | ngưỡng để decided phải vượt |

## Khi decided có đầu vào/đầu ra

1. Đối chiếu đầu ra của decided với ba hình dạng A/B/C, chọn một (chủ dự án quyết).
2. Đăng ký trước như `m3-preregistration.md`: control là bộ trích hiện tại trên 150 ca, ngưỡng theo cỡ
   mẫu, điều kiện dừng.
3. Nếu B: bổ sung nhãn cho 3 khoá v2, và gom bộ khoá đóng về một chỗ (hiện khai ở 3 file trong
   `backend/app`).

## Comments
