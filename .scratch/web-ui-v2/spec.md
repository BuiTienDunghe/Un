# Web UI v2 — spec thực thi

Status: done (16/09/2026) — 10 màn + khung app đã dựng, kiểm và sửa.
Việc backend còn thiếu: `backend-todo.md`. Chỗ chờ chủ dự án chốt: `decisions-open.md`.

Nguồn thiết kế duy nhất: `design_handoff_local_ai_core_v2/README.md` + prototype
`Local AI Core v2.dc.html` (tham chiếu, không chép mã). Ảnh đối chiếu:
`design_handoff_local_ai_core_v2/screenshots/` (gói zip không có thư mục này — ảnh do
agent chụp lại từ prototype, xem `INDEX.md` trong đó). Cả gói nằm ngoài repo (gitignore từ
29/09/2026), chỉ có trên máy chủ dự án.

## Quyết định đã chốt

| Việc | Quyết định | Lý do |
|---|---|---|
| Font | Font hệ thống: `"Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, Roboto, "Noto Sans", "Helvetica Neue", Arial, sans-serif` — KHÔNG self-host Be Vietnam Pro | Chủ dự án chọn "chủ động đổi font" thay vì tải font. Máy nào trong LAN cũng có sẵn, đủ dấu tiếng Việt, chạy offline. Ảnh so pixel dùng bản prototype đã vá cùng font này. |
| CSS | `styles.css` = tokens + base + primitives + khung app; mỗi màn hình một file `views/<tên>.css` nạp trong `index.html` | Mỗi màn hình một chủ sở hữu file, không ai sửa đè ai; README chỉ đề xuất, không cấm tách |
| Kiểm tra | Máy chủ giả (dữ liệu mẫu của prototype) để so pixel + bấm thử; API thật thứ hai ở `127.0.0.1:8765` (không khóa, CHỈ ĐỌC) để kiểm khuôn dữ liệu thật | Chủ dự án chọn; không ghi/xóa gì trên dữ liệu thật |

## Cấu trúc file

```
backend/app/frontend/
  index.html        shell duy nhất: sprite SVG, sidebar, header, <main id="view">, gốc toast/dialog/login
  styles.css        tokens (:root / [data-theme="dark"]) + base + primitives + shell + @keyframes + motion-off
  common.js         GIỮ NGUYÊN (không sửa)
  components.js     primitives dựng DOM: h, icon, toast, dialog, dropdown, segmented, pill, skeleton, …
  router.js         hash router (global `Router`)
  shell.js          khung app: boot, đăng nhập, nav, header, chuông, health, theme, vai trò (global `Shell`)
  views/<v>.js      một IIFE mỗi màn hình, tự Router.register(...)
  views/<v>.css     style riêng của màn hình đó
  dashboard.html, ocr.html, chunks.html   redirect 1 dòng sang hash route
```
Xóa: `app.js`, `dashboard.js`, `ocr.js`, `chunks.js` (logic chuyển vào views).

Thứ tự nạp trong `index.html` (tất cả `defer`, thứ tự là hợp đồng):
`common.js → components.js → router.js → shell.js → views/chat.js … views/chunks.js`.
`shell.js` khởi động ở `DOMContentLoaded` (khi mọi view đã register).
Cache-busting: mọi asset dùng cùng `?v=2.0.0`.

## Phạm vi global (script cổ điển dùng chung một phạm vi)

- `common.js` sở hữu: `$ el esc readStore prefs savePrefs systemDark applyTheme getApiKey setApiKey authHeaders refreshInFlight refreshAccessToken ERROR_HINTS sendJson requestJson`. KHÔNG file nào khai báo lại.
- `components.js`: hàm top-level (danh sách ở mục Components). `router.js`: chỉ `Router`. `shell.js`: chỉ `Shell`.
- `views/*.js`: bọc toàn bộ trong `(() => { "use strict"; … })();` — KHÔNG có khai báo top-level nào.
- Test ghép MỌI file JS của trang theo đúng thứ tự nạp rồi `node --check` để bắt trùng tên.

## Router

```
#/chat                 #/chat/<conversationId>
#/documents[?doc=<id>] #/memory[?tab=pending|applied|condense]
#/dashboard            #/ocr[?job=<id>]         #/bot
#/models               #/users                  #/settings
#/chunks/<documentId>
```
- `''`, `#`, `#/` → `#/chat`. Route lạ → `#/chat`.
- Link cũ `#c=<id>` → `history.replaceState` sang `#/chat/<id>`.
- Route admin (`ocr`, `bot`, `models`, `users`): member bị đưa về `#/chat` kèm toast "Chỉ quản trị viên xem được trang này.".

```js
Router.register(name, {
  admin: false,               // true = chỉ admin
  mount(ctx) {},              // có thể async
  update(ctx) { return false },// tùy chọn: cùng view, đổi params/query; true = đã tự xử lý, false = router mount lại
  unmount() {},               // tùy chọn
});
// ctx = { root, name, params: string[], query: URLSearchParams, signal: AbortSignal,
//         every(fn, ms), after(fn, ms), on(target, type, fn, opts),
//         setHeader(title, sub), setActions(nodes[]) }
// signal abort + mọi every/after/on tự gỡ khi rời view. Router.go(hash), Router.replace(hash), Router.current.
// Bổ sung sau vòng soát khung (16/09): update(ctx, {same, signal}) — signal bị hủy khi có update/teardown mới;
// update bị bỏ qua (mount lại) nếu mount() async chưa xong. Router.pause({unmount}) / resume({force}) / paused
// — shell dùng khi hết phiên / đăng xuất: hashchange bị bỏ qua, every() ngừng tick, after() hoãn tới resume.
// Đăng ký every/after/on sau khi view đã rời là no-op. Router.reload(), Router.has(name).
```

## Shell

```js
Shell.user            // {id, username, role} | null khi tắt tài khoản
Shell.authEnabled     // bool
Shell.isAdmin()       // tắt tài khoản → true (backend require_admin là no-op)
Shell.setHeader(title, sub) / Shell.setHeaderActions(nodes)
Shell.setSidebarPanel(node|null)    // khối "HỘI THOẠI" của chat
Shell.setNavBadge("memory", n)      // 0 = ẩn
Shell.health / Shell.onHealth(fn)   // poll /health 60s
Shell.refreshNotifications()
Shell.logout()
Shell.motionOn()      // prefs.motion !== false && !prefers-reduced-motion
```
- Tắt tài khoản: footer hiện icon người dùng trong avatar, tên "Người dùng cục bộ", vai trò "Toàn quyền · chưa bật tài khoản", ẩn nút đăng xuất.
- Bật tài khoản: `/auth/config` → `enabled`, `has_users` → màn hình đăng nhập/tạo quản trị viên; lưu `lac.access`/`lac.refresh` như cũ; `/auth/me` → `role`.
- Hiệu ứng động: `prefs.motion` (mặc định bật) → `html[data-motion="off"]` tắt mọi animation/transition; `prefers-reduced-motion: reduce` cũng tắt; đếm số (count-up) nhảy thẳng tới giá trị cuối.
- Pref mới không cần sửa common.js: đọc `prefs.motion !== false`, `prefs.showGrounding !== false`.

## Components (components.js — hàm top-level, view dùng trực tiếp)

```js
h(tag, props?, ...children)          // props: class (str|arr), text, style (obj|str), dataset, on<Event>: fn,
                                     // mọi khóa khác → attribute (aria-*, role, title, type, href, disabled, hidden, value, checked…)
                                     // children: Node | string | number | array | null/false (bỏ qua). Không nhận HTML thô.
icon(name, {size = 16, sw, cls})     // <svg class="ico"><use href="#i-name"/></svg>; sw = stroke-width (mặc định 2)
toast(text, kind = "ok" | "danger", {duration = 2800})
dialog({tone: "accent"|"warn"|"danger", icon, title, body, input?, fields?, options?,
        confirmLabel, confirmTone: "accent"|"danger", cancelLabel = "Hủy", validate?}) → Promise<kết quả | null>
        // input → string; fields → {name: value}; options → value được chọn; xác nhận trơn → true; Hủy/Esc/overlay → null
confirmDialog({title, body, confirmLabel = "Xóa", tone = "danger", icon = "trash"}) → Promise<bool>
dropdown(anchor, items | (close) => Node, {align = "end", width}) → {close}
        // items: [{label, icon, tone: "danger", onSelect, disabled, separator, hint}]
segmented(options, value, onChange, {variant: "plain"|"bordered", size: "sm"|"md"|"lg", label}) → el (+ el.setValue(v))
        // options: [{value, label, icon, count, badge}]
pill(text, tone: "ok"|"warn"|"danger"|"accent"|"muted", {dot = true, size: "md"|"sm"})
chip(label, {icon, active, onClick, title})     typeBadge(filenameOrExt, size = 28)
switchEl({checked, onChange, size: "md"|"sm", disabled, label}) → el (+ el.checked get/set)
skeleton({w, h, r})   emptyState({icon, title, text, action})   errorState(error, onRetry)
missingApiState({feature, endpoint})            // "Máy chủ chưa hỗ trợ <feature>." + endpoint mono
isMissingApi(error)                             // 404/405/501 không mã lỗi (hoặc HTTP_ERROR)
isUnsupportedField(error)                       // 422 INVALID_INPUT (PATCH mang khóa backend chưa biết)
countUp(el, to, {duration = 1100, format})      // tôn trọng Shell.motionOn()
fmtNumber fmtBytes fmtRelative fmtClock fmtDate fmtDuration debounce copyText initials avatarColor
```
Bổ sung sau vòng soát khung: `dialog`/`confirmDialog` nhận `signal` (view nên truyền `ctx.signal`), tự đóng
(→ null) khi Back/Forward; mở dialog thì đóng menu đang mở; field `required`/`minlength` được kiểm khi xác nhận;
`dropdown` không còn đóng khi trang cuộn, tự giới hạn chiều cao trong viewport, `handle.close({restoreFocus})`.
Shell thêm: `Shell.api(path, options)` = `requestJson` + khi bật tài khoản mà refresh hỏng → màn đăng nhập
(signal bị hủy → reject `AbortError`);
`Shell.fetchBlob(path)` = tải nhị phân có header xác thực (ảnh trang PDF, ảnh OCR, zip) → `Blob`.
Chỉ 2 chỗ được `fetch(` thô ngoài common.js: `Shell.fetchBlob` (shell.js) và luồng SSE (views/chat.js).

## Hành vi cũ: giữ hay sửa

Giữ nguyên mọi hành vi trong checklist `research/old-*.md`, trừ các lỗi rõ ràng sau (sửa và báo lại):
renderer treo tab với dòng ```` ```c++ ```` (D1); `#c=` chỉ đọc lúc nạp (D2 — router nghe hashchange);
chú thích đổi tên sai chỗ lưu (D3); xung đột thứ 4 `content_owned_by_another_document` bị hủy câm (D4 — hiện
dialog giải thích, chỉ nút Hủy); thông báo lỗi mạng tiếng Anh "Failed to fetch" (D8); U+2028 làm hỏng lượt (D9);
`lac.docsel` hỏng làm chết trang (D14); tiêu đề hội thoại mới không cập nhật theo máy chủ (D12).
Giữ như cũ (quyết định sản phẩm, liệt kê cho chủ dự án): thử lại = thêm lượt mới (D13); ghi nhớ bật/tắt theo
phiên; chip Công cụ vẫn hiện ở chế độ Tài liệu (prototype cũng vậy); luồng đứt không có `done` vẫn coi là xong (D10).

## API chưa có

`isMissingApi(error)` = `error.status ∈ {404, 405, 501}` và mã lỗi là rỗng hoặc `HTTP_ERROR`.
View gọi đúng endpoint đề xuất trong README; nếu thiếu thì hiện trạng thái rỗng/khóa có câu giải
thích "Máy chủ chưa hỗ trợ …" và KHÔNG giả vờ thành công. Danh sách endpoint → mục cuối báo cáo.

## Hợp đồng API đề xuất (UI gọi đúng như sau; máy chủ giả mô phỏng khi bật `future`)

Nguồn: bảng "API cần bổ sung" của README + chỗ trống phát hiện khi đọc backend
(`research/api-core.md` §11, `research/api-admin.md` §7b). Mục có dấu ＋ là ngoài bảng README.

| # | Chức năng | Endpoint | Hợp đồng |
|---|---|---|---|
| F1 | Ghim / thư mục hội thoại | `PATCH /conversations/{id}` | body có thể chứa `title?`, `pinned?: bool`, `folder_id?: str\|null` (ít nhất 1 khóa) → 204. Hiện backend bắt buộc `title` → 422 `INVALID_INPUT`: UI coi 422 trên request KHÔNG có `title` là "chưa hỗ trợ". KHÔNG BAO GIỜ gửi kèm `title` khi chỉ ghim (sẽ đổi tên). |
| F1 | | `GET /conversations` | mỗi dòng thêm `pinned: bool`, `folder_id: str\|null` |
| F1＋ | Biểu tượng hội thoại RAG | `GET /conversations` | mỗi dòng thêm `has_sources: bool` (true khi có tin trợ lý mang trích dẫn) — điều khiển icon sách 12px ở thanh bên |
| F1 | | `GET/POST/PATCH/DELETE /folders[/{id}]` | `{id, name, color}`; POST `{name, color}` → 201; PATCH `{name?, color?}` → 200; DELETE → 204 (hội thoại về `folder_id:null`) |
| F2 | Tag tài liệu | `PATCH /documents/{id}/tags` | `{tags: [str]}` → 200 Document; `GET /documents?tag=<t>` lọc |
| F2＋ | Thông tin tệp | `GET /documents` | mỗi Document thêm `tags: [str]`, `file_size: int`, `total_pages: int\|null`, `created_at`, `updated_at` (đã có trong DB, chưa trả ra) |
| F3 | Xem trước trang | `GET /documents/{id}/pages/{n}.png` | ảnh PNG; `GET /documents/{id}/pages/{n}/boxes?chunk_id=` → `{boxes:[{x,y,w,h}]}` tỉ lệ 0..1 (tùy chọn) |
| F3＋ | Version + lịch sử + tệp gốc | `GET /documents/{id}/versions` | `[{version_id, index_version, content_hash, created_at, status: "active"\|"archived"\|"staging"\|"failed", chunks_count}]` |
| | | `GET /documents/{id}/history` | `[{at, kind: "upload"\|"extract"\|"ocr"\|"index"\|"replace"\|"failed", title, detail, ok: bool}]` mới nhất trước |
| | | `GET /documents/{id}/source` | tải tệp gốc (Content-Disposition) |
| F4 | Thông báo | `GET /notifications?unread=1` | `{items:[{id, kind, tone: "ok"\|"accent"\|"danger"\|"muted", title, detail, created_at, read, link?}], unread_count}` |
| | | `POST /notifications/read` | `{ids?: [..]}` (bỏ trống = tất cả) → 204 |
| F5 | Người dùng | `PATCH /auth/users/{id}` | nhận thêm `password?`, `disabled?: bool` (hiện chỉ `role`, thiếu → 422); user public thêm `disabled: bool` |
| F5＋ | Đổi mật khẩu của mình | `POST /auth/me/password` | `{current_password, new_password}` → 204 |
| F6 | Model | `POST /models/{role}/promote` `{version}`, `POST /models/{role}/revert`, `GET /models/check` | promote/revert → 200 registry row (hiệu lực sau khi khởi động lại); check → `{ok, problems:[str], output}` |
| F6＋ | Danh sách version | `GET /models` | `registry[role].versions: [{id, name, status}]` |
| F7 | Bot | `POST /api/bot/restart`; `/api/bot/status` thêm `started_at`, `uptime_seconds`, `guild_count`, `member_count` | |
| F7＋ | Cấu hình bot | `GET /api/bot/config` | `{persistent_sessions: bool, memory_ingestion: bool, member_context_limit: int}` |
| F8＋ | Badge chờ duyệt | `GET /api/memory-review/count` | `{pending: int}` (hiện UI đếm trang đầu `candidates?limit=100`) |
| F9＋ | Thành viên xem chỉ đọc | (không endpoint mới) | mở `GET /api/dashboard/*`, `/metrics`, `/agent/activity`, `/api/memory-review/applied` cho member; hiện 403 |
| F10＋ | Thành viên tải lên | (không endpoint mới) | tải lên xong tự lập chỉ mục, hoặc cho member gọi `POST /documents/index` với tài liệu mình vừa tải; hiện 403 → tài liệu kẹt `uploaded` |

## Kiểm tra mỗi màn hình

1. `node --check` từng file + ghép theo thứ tự nạp.
2. Chụp màn hình bản dựng (máy chủ giả, 1440×900, tắt animation) so với ảnh prototype cùng trạng thái
   (prototype đã vá cùng font) → `imgdiff.py` + nhìn → sửa lệch.
3. Đối chiếu checklist hành vi cũ (`research/old-*.md`) và khuôn API thật (`127.0.0.1:8765`, chỉ GET).
4. `pytest backend/tests/test_frontend.py`.
