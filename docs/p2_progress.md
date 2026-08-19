# Nhật ký thi công Phase P2 — Agent tự hành

> Ghi lại **quyết định + lý do** của từng hạng mục, theo đúng nếp của
> `docs/p1_progress.md`. Phase P2 hiện thực hóa điều chỉnh định hướng 19/08/2026:
> agent tự vận hành quy trình, con người giám sát và thu hồi thay vì duyệt tay.

---

## P2-1 — Memory tự áp dụng theo ngưỡng tin cậy — ✅ 19/08

**Ý tưởng một câu:** đề xuất memory có confidence ≥ ngưỡng được worker tự approve
qua **đúng đường duyệt của P1-4** (`reviewed_by="agent"`); dashboard đổi vai từ
cửa duyệt thành màn giám sát với nút Thu hồi 1 click.

### Quyết định thiết kế và lý do

| Quyết định | Lý do |
| --- | --- |
| Ngưỡng là setting `DISCORD_MEMORY_AUTO_APPLY_THRESHOLD`, mặc định `0.8`, giá trị `off`/rỗng để tắt | Plan định 0.8. `.env` không có literal null nên nhận từ khóa "off"; validator chặn ngoài (0, 1] |
| Auto-apply chạy trong worker **ngay sau khi job extraction đã commit**, ngoài mọi transaction | Giữ bất biến *không transaction nào ôm qua lời gọi model* (mirror phải embed). Mọi lỗi ở bước này chỉ làm candidate rơi về hàng chờ người duyệt — extraction không bị retry, không mất gì |
| Tái dùng nguyên `approve()` của P1-4 với `reviewed_by="agent"` thay vì viết đường ghi thứ hai | Một đường ghi duy nhất → audit trail và mirror web y hệt người duyệt; dashboard chỉ cần phân biệt 🤖 agent / 👤 người. Không tồn tại code path "agent lách qua kiểm soát" |
| `approve()` mở rộng định tuyến 3 nhánh: identity chưa có gì → `create`; đang có bản active → `supersede`; có lịch sử nhưng không còn bản active → `revive` (hàm repository mới) | Autonomy phơi ra lỗ hổng có sẵn từ P1-4: approve chỉ biết `create_active_version`, nên fact **cập nhật lần thứ hai sẽ 409 vĩnh viễn**, và sau thu hồi thì identity **chết hẳn** (create từ chối vì có history, supersede từ chối vì không có bản active). Không vá thì "agent tự học" kẹt ngay ở kịch bản đời thường nhất: người dùng đổi ý |
| Supersede/revive thay mirror web: upsert bản mới **và xóa mirror bản cũ** trong cùng pha | Web store không bao giờ được phục vụ fact đã lỗi thời. Id định danh `mem_dc_<memory>` làm cả hai bước idempotent — retry sau lỗi mirror chạy lại y nguyên |
| Thu hồi = `status='deleted'` + `deleted_at`, **không DELETE row**; candidate ghi `rejected` + ai thu hồi, lúc nào | Bất biến mới của plan: hành động tự hành phải audit được và thu hồi được — thu hồi cũng phải để lại sử liệu. Trạng thái `deleted` có sẵn trong schema từ Sprint 2B, không cần migration |
| Đề xuất `operation='delete'` **không bao giờ** auto-apply, kể cả confidence 1.0 | Quên là hành động phá hủy theo nghĩa vận hành — giữ cho người quyết định. Ranh giới an toàn rẻ nhất của cả tính năng |
| Panel "Memory đang hiệu lực" trên dashboard: nội dung, nguồn, ai duyệt (🤖/👤 + %), nút Thu hồi | Đây chính là "dashboard đổi vai" mà điều chỉnh định hướng hứa: người không còn là cổng chặn, nhưng luôn thấy agent đang nhớ gì và gỡ được ngay |

### Bằng chứng nghiệm thu

- **Test:** 5 test mới trong `backend/tests/test_memory_auto_apply.py` — auto-apply
  trên ngưỡng (audit `reviewed_by="agent"` + mirror), dưới ngưỡng chờ người,
  delete-proposal và ngưỡng tắt không bao giờ tự áp dụng, supersede thay mirror
  đúng, revert + học lại (revive ra version 2). Suite backend **514 passed /
  1 skipped / 0 failed**; root 59 passed; `node --check` sạch.
- **Chuỗi sống 19/08 21:30, model thật, không mock** (stack: uvicorn + outbox
  dispatcher + memory worker):

| Bước | Kết quả đo được |
| --- | --- |
| Turn Discord thật (API session) → `qwen3.5:9b` trả lời → complete | outbox → RQ → worker nhận job |
| Extractor `qwen3.5:2b` thật | Proposal confidence 1.0 ≥ 0.8 |
| **Agent tự áp dụng** | `applied_by="agent"`, hàng chờ duyệt **trống**, xuất hiện trong `/api/memory-review/applied` sau ~20s, mirror `index_status=indexed` |
| `/memory/search` câu hỏi khác hẳn văn bản lưu | Hạng 1, score 0.534 — semantic thật, web dùng được không một cú click nào |
| **Nút Thu hồi trên dashboard thật** | applied=0, search=0; DB: memory `deleted` + `deleted_at` + `not_required`, candidate `rejected` bởi `dashboard` — sử liệu còn nguyên |

- **Phát hiện sống đắt giá:** extractor 2b **bịa sai nội dung** — tin nhắn dặn
  "muốn câu trả lời có ví dụ minh họa" nhưng nó trích thành *"User dung-live
  prefers Vietnamese"* với confidence **1.0**. Đây chính xác là rủi ro ở §8 của
  plan (extractor 2B tự áp dụng memory sai), và vòng giám sát + Thu hồi vừa chứng
  minh nó xử lý được sự cố thật trong một cú click. Hệ quả thực tế: **confidence
  của 2b không đáng tin như một thước đo đúng/sai nội dung** — trước khi nâng/hạ
  ngưỡng cần chạy benchmark 150 case (đã có sẵn từ P1-3) để đo tỷ lệ fact sai ở
  từng mức confidence.

### Ghi chú vận hành

- Một lần chạy full suite thấy `test_first_completion_atomically_creates_delivery_job_and_outbox`
  fail rồi **không tái hiện** (pass khi chạy riêng và khi chạy lại nguyên suite).
  Fixture `memory_transport` đếm job `discord_memory_ingest` **toàn cục** nên nhạy
  với dữ liệu sót giữa các lần chạy — đã ghi vào T9 (gom mục nhỏ) hướng sửa: scope
  câu đếm theo prefix của test.

## Benchmark extractor 19/08 — "harness cho 2b mạnh hơn, hay bắt buộc đổi model?"

Câu hỏi đặt ra sau sự cố sống của P2-1 (2b bịa fact sai với confidence 1.0). Lần
**đầu tiên** dataset 150 case được chạy đo thật (`benchmark_discord_memory_extractor.py`,
prompt v5, chế độ JSON-schema). Raw kết quả: `data/benchmarks/discord_memory_extractor_20260819_*.json`.

### Thông số chính

| Chỉ số | `qwen3.5:2b` (150 case) | `qwen3.5:9b` (75 case phân tầng) |
| --- | --- | --- |
| JSON hợp lệ / đúng schema | 99,3% / 96,7% | 100% / 92% |
| Mạo subject / target ngoài allowlist | 0 / 0 | 0 / 0 |
| Đáng lẽ im thì im (no_op) | **44%** | 60% (17/25 trên tập chung) |
| Fact đúng nội dung | **66%** | 74% |
| Latency TB / tốc độ | 12,2s · 23,4 tok/s | 59,2s · 4,1 tok/s |
| Lặp lại y hệt (temp 0 + seed) | 100% | — (không đo) |

### Trục confidence — tín hiệu của ngưỡng τ: **chết ở cả hai model**

Mọi proposal sai nghiêm trọng của cả 2b (72/72) lẫn 9b (17/17) đều khai
`confidence = 1.0`. Confidence của extractor là hằng số trang trí, không phải
xác suất — **τ không lọc được gì bất kể đặt bao nhiêu**.

### Mô phỏng chính sách auto-apply trên cùng 75 case (độc = sai nội dung /
### viết khi phải im / gán nhầm người / sai fact_key)

| Chính sách | 2b: coverage · độc lọt | 9b: coverage · độc lọt |
| --- | --- | --- |
| A — chỉ `conf ≥ 0.8` (P2-1 hiện tại) | 100% · **49,2%** | 100% · 36,2% |
| C — A + evidence nguyên văn + fact trùng từ-nội-dung với tin gốc | 53,3% · 36,0% | **96,7% · 21,6%** |

Đọc số: guard C gần như **miễn phí** với 9b (fact của 9b thật sự phản ánh tin
gốc nên không bị guard chém) nhưng chém nửa coverage của 2b mà vẫn để lọt hơn
1/3 độc. Họ lỗi còn lại của cả hai là lỗi **phán đoán**: gán fact người thứ ba
nói cho người dùng tin cậy, tin nguồn không đáng tin, nhận nhầm kẻ trùng display
name. Đánh đổi của 9b: bỏ sót 11 fact thật (dè dặt hơn + 6 lần trượt schema) —
chấp nhận được vì bỏ sót rẻ hơn nhiều so với nhớ bậy (người dùng nói lại là
xong; memory độc thì agent tự tin nói sai mãi).

### Kết luận

1. **Harness thuần cho 2b: không cứu được** — guard xác định tốt nhất vẫn lọt
   36% độc với nửa coverage; vote nhiều lần vô dụng (100% lặp y hệt); prompt đã
   qua 5 vòng. Mọi đường harness còn lại đều cần model lớn hơn tham gia.
2. **Không model nào đủ an toàn để tự hành mù**: kể cả 9b + guard C còn 21,6%
   độc. Vòng giám sát + thu hồi của P2-1 vì thế **không phải tạm bợ mà là kiến
   trúc đúng**: autonomy có giám sát.
3. **Khuyến nghị (P2-1b)**: đổi extractor sang `qwen3.5:9b` (1 dòng `.env`,
   kiến trúc đã tham số hóa; 59s/lần chấp nhận được vì extraction chạy nền) +
   đưa guard C thành điều kiện auto-apply trong worker; τ giữ làm công tắc
   chính sách nhưng docs phải nói rõ tín hiệu thật là guard, không phải
   confidence. Đường ép độc xuống nữa (9b thẩm định chéo đề xuất) để ngỏ, phải
   benchmark riêng trước khi tin.

## P2-2 — Vòng lặp agent + tool use — ⏳ chưa bắt đầu

## P2-3 — Bộ lệnh Discord chuyên nghiệp — 🔶 một phần (19/08)

- `/hoi` → `/docs` (tham số `tailieu` → `document`) đã đổi cùng ngày với điều
  chỉnh định hướng; bộ lệnh hiện tại `/ask · /docs · /ping`. Lý do chọn `/docs`
  thay vì `/ask`: bot **đã có** `/ask` (chat thường) từ trước — P2-2 sẽ biến
  `/ask` thành cửa vào agent tự chọn tool.
- Còn lại: `/memory`, `/status`.

## P2-4 — Nhật ký hành động agent — ⏳ chưa bắt đầu

- Panel "Memory đang hiệu lực" của P2-1 là viên gạch đầu; P2-4 mở rộng thành
  dòng thời gian mọi hành động tự hành (index, cleanup, backup, memory apply).
