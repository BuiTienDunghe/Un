# Nhật ký thi công Phase P3 — Đa người dùng & quản trị

> Ghi lại **quyết định + lý do** từng hạng mục, theo nếp `p1_progress.md`/`p2_progress.md`.
> Điểm khác biệt quy trình của phase này: thiết kế P3-1 (auth) được viết ra
> TRƯỚC rồi đưa qua **hội đồng phản biện đối kháng** (3 agent độc lập: tấn công
> bảo mật / tương thích-vận hành / lỗ hổng hiện thực) — 34 phát hiện, trong đó
> 8 chí mạng, tất cả được xử lý trong thiết kế v2 trước khi viết dòng code đầu.

---

## P3-1 — Tài khoản + RBAC tối giản (JWT + refresh) — ✅ 20/08

**Ý tưởng một câu:** bật `LOCAL_AI_AUTH_ENABLED=true` là hệ thống thành nhiều
người dùng — người đầu tiên đăng ký là quản trị viên, member chỉ thấy hội thoại
của mình và không đụng được vào tài nguyên chung; tắt cờ là trở về đúng máy
đơn người dùng một-cú-click như cũ.

### Quyết định thiết kế và lý do (sau phản biện)

| Quyết định | Lý do (phát hiện phản biện tương ứng) |
| --- | --- |
| Validator: bật auth **bắt buộc** có cả `LOCAL_AI_JWT_SECRET` (≥32) lẫn `LOCAL_AI_API_KEY`; guard **fail-closed** khi auth bật | Phát hiện chí mạng: cấu hình tự nhiên "bật auth, quên API key" sẽ vừa giết lane dịch vụ (bot/eval/smoke) vừa để đường fail-open cũ mở toang toàn bộ surface trong khi UI hiện màn đăng nhập trấn an |
| Ba loại danh tính: `service` (X-API-Key, tương đương admin) / `user` (Bearer JWT) / `anonymous` | Bot Discord, eval, smoke test giữ nguyên không sửa một dòng; máy đơn người dùng giữ nguyên hành vi |
| `require_admin` wire **tường minh** vào router (dashboard, memory-review, agent, bot, discord-sessions) + endpoint phá hủy (xóa/replace/index tài liệu, sửa/xóa memory chung, xóa lịch sử OCR, `/metrics`) | Phản biện chứng minh "chỉ mở rộng 2 guard cũ" là bất khả thi — thiếu wire thì member điều khiển được cả pipeline turn Discord |
| `require_admin` đọc role từ **DB** mỗi lần, không tin claim trong token | Giáng chức có hiệu lực tức thì thay vì đợi token hết hạn 15 phút |
| Refresh token **không xoay vòng** (một token dài hạn, băm khi lưu, thu hồi được; login cấp mới, logout thu hồi) | Rotation + reuse-detection nghe "chuẩn" nhưng biến race refresh đa tab thành đăng xuất hàng loạt — quá đắt cho công cụ LAN; đơn giản mà thu hồi được là đủ |
| Đăng ký **chỉ mở khi chưa có user nào** (bootstrap admin, khóa advisory PostgreSQL chống race hai admin); sau đó admin tạo tài khoản qua `/auth/users` | Đăng ký mở trên LAN là land-grab: ai vào link trước thành admin |
| Chống dò: hash bcrypt giả cho username không tồn tại (chống timing), khóa 60s sau 5 lần sai (chống brute-force), 401 chung chung | Phát hiện user-enumeration + brute-force |
| Không giáng chức được **admin cuối cùng** | Chống tự khóa cửa không đường cứu |
| Ownership hội thoại đi qua **một cửa duy nhất** `ensure_conversation_access` (dùng ở conversations + /chat + /rag/chat); người khác nhìn vào → **404, không phải 403** | Rải check khắp nơi là lộ một đường quên một đường; 404 để không lộ cả sự tồn tại |
| Alias `POST /api/login` → login | Bot's api_client đã có sẵn lane JWT fallback gọi đúng đường này từ P0 — phản biện tìm ra, thiết kế gốc không biết |
| Frontend: overlay đăng nhập/bootstrap trong app chat; dashboard.js cũng gắn Bearer, 401 → về trang đăng nhập | Phát hiện chí mạng: dashboard là mặt admin mà bản thiết kế đầu quên — sẽ chết toàn trang với user JWT |

### Bằng chứng nghiệm thu

- **Test:** 7 test mới (`test_auth_api.py`): bootstrap-đóng-đăng-ký, vòng đời
  login/refresh/logout + alias bot, **ma trận RBAC đủ 4 danh tính** (anonymous
  401; member chat được nhưng 403 ở 7 surface chung; admin mở; service key
  nguyên vẹn), **cách ly ownership** (B nhìn/A chen/B xóa hội thoại của A đều
  404, admin thấy hết, A tự quản lý được), khóa brute-force 429, admin cuối
  không giáng được. Suite backend **544 passed / 0 failed**, root 65 — mọi test
  cũ giữ nguyên vì auth mặc định tắt (cô lập thêm trong conftest).
- **Sống 20/08 (trình duyệt thật):** backend bật auth → mọi endpoint 401 khi
  nặc danh → mở `/ui/` overlay tự nhận chế độ **"Tạo tài khoản quản trị"** →
  đăng ký `dung-admin` → reload tự đăng nhập, mục Tài khoản hiện tên + vai trò
  → tạo `dung-member` qua API → member: dashboard **403**, xóa tài liệu **403**,
  danh sách hội thoại **rỗng**. Dọn sạch user test sau đó.

### Đánh đổi chấp nhận (ghi T13, không chặn dùng)

Token trong localStorage (XSS-exfiltrable — chấp nhận cho công cụ LAN, app
render markdown đã escape); role trong access token member có thể cũ tối đa 15
phút (surface admin thì đọc DB rồi); memory/tài liệu là workspace chung nên
member đọc được của nhau (đúng thiết kế «nhóm nhỏ»); chưa có đổi/quên mật khẩu
(quản trị viên reset qua psql).

## P3-2 — Điều khiển bot Discord từ dashboard — ✅ 20/08

- Bot xưa nay chạy qua `docker compose --profile discord up discord-bot`
  (run-discord-bot.bat) → service điều khiển gọi **đúng cơ chế đó**
  (`BotControlService`): status = `compose ps --format json` (không thể lệch
  thực tế), start = `up -d` (kiểm tra DISCORD_TOKEN trước, y như file .bat),
  stop = `compose stop`. Nút trên dashboard (panel Mô hình & tác vụ nền), 
  admin-only khi auth bật.
- Test: parse status các trạng thái, start thiếu token → 409, đúng args compose,
  endpoint map lỗi. Sống: dashboard hiển thị "⚪ đang tắt" từ compose ps thật,
  nút Bật/Tắt đúng trạng thái. *Chưa bấm Bật sống* — cần DISCORD_TOKEN thật và
  build image lần đầu (bước người thật, như /hoi của P1-1).

## P3-3 — Biểu đồ 14 ngày trên dashboard — ✅ 20/08

- `GET /api/dashboard/timeseries`: gộp `request_logs` theo **ngày địa phương**
  (dịch offset trước khi date() — DB chạy UTC), đếm câu hỏi (/chat + /rag/chat),
  lỗi (mọi endpoint), p50/p95 (`percentile_cont`), zero-fill ngày trống.
- Hai biểu đồ **SVG tự vẽ** (không thư viện, đúng tinh thần không-build):
  cột câu hỏi + cột lỗi đỏ; đường p50/p95. Chữ dùng `currentColor` nên theo
  theme tự động. Sống: 14 cột hiện đúng trên dashboard thật.

## P3-4 — OCR Console UI — ✅ 20/08

- Trang mới `/ui/ocr.html` + `ocr.js` trên API có sẵn từ lâu: upload (chọn DPI)
  → theo dõi job (poll 2.5s, progress + events) → xem kết quả từng trang → 
  **Đưa thành tài liệu** (promote) / tải zip / hủy / lịch sử + xóa. Link từ
  dashboard. Không cần curl nữa — đúng nguyên văn tiêu chí.
- Bug bắt khi chạy sống: trang gọi `/ocr/...` trong khi router mount ở
  `/api/ocr/...` → sửa + bump version cache. Sống: trang tải, lịch sử trống
  hiển thị đúng trạng thái rỗng dưới auth.

## Kiểm tra chốt phase — 20/08

| Hạng mục | Kết quả |
| --- | --- |
| Suite backend | **544 passed / 1 skipped / 0 failed** (3:32) |
| Suite root | 65 passed |
| Migration | `20260820_23` up cả 2 DB; `alembic check` + schema-drift test xanh; downgrade đủ |
| Sống | Chuỗi auth đầy đủ trên trình duyệt thật + RBAC 3 danh tính + charts + bot status + OCR console (bảng trên) |
| Zero-setup | Auth mặc định tắt: launcher, bot, tool, toàn bộ test cũ — không đổi hành vi |
