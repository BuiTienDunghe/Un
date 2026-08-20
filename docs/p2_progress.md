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

## P2-1b — Extractor 9b + guard xác định — ✅ 20/08

**Ý tưởng một câu:** thi hành kết luận benchmark — extractor đổi sang `qwen3.5:9b`,
và điều kiện tự áp dụng không còn tin confidence mà tin **guard xác định**:
evidence phải nguyên văn trong tin gốc, fact phải trùng từ-nội-dung với tin gốc.

### Quyết định và lý do

| Quyết định | Lý do |
| --- | --- |
| Guard là module thuần (`discord_memory_guard.py`), thuật toán **y hệt** bản phân tích benchmark | Số đo 96,7% coverage / 21,6% poison chỉ có giá trị nếu code production và phép đo là một; test `test_production_guard_reproduces_the_measured_benchmark_policy` tái dẫn xuất hai con số từ kết quả 9b đã lưu bằng chính hàm production — chỉnh guard mà lệch trade-off là test đỏ |
| Guard chỉ chặn đường **tự hành**; người duyệt trên dashboard không qua guard | Con người chính là guard; đề xuất trượt guard rơi về hàng chờ, không mất gì |
| τ giữ nguyên vai công tắc chính sách (`off` = duyệt tay toàn bộ) | Đã đo: confidence là hằng 1.0 — không phải tín hiệu, chỉ còn là cần gạt |
| Model đổi ở mọi điểm cấu hình: settings default, `.env`, `.env.example`, launcher pull, docker-compose default | Một chỗ sót là một môi trường chạy nhầm 2b |
| Outcome mới `auto_apply_guard_rejected` | Nhìn được trong log worker vì sao một đề xuất chờ người thay vì tự áp dụng |

### Bằng chứng

- Test: 12 test guard + auto-apply (kể cả **hồi quy đúng ca bịa fact sống 19/08**:
  "prefers Vietnamese" confidence 1.0 → `auto_apply_guard_rejected`, nằm lại hàng chờ).
- **Phát hiện sống 20/08 — điểm mù xuyên ngữ:** lặp lại đúng tin nhắn 2b từng bịa
  ("muốn ví dụ minh họa"), 9b trích **đúng nội dung** (*"User always wants answers
  with specific illustrative examples"*) nhưng guard từ chối vì fact tiếng Anh
  không trùng từ nào với tin gốc tiếng Việt → rơi về hàng chờ. **Hướng rơi an
  toàn đúng thiết kế** (mất coverage, không nhiễm độc), một click duyệt là xong;
  hướng sửa thật nằm ở prompt extractor v6 (viết fact bằng ngôn ngữ tin gốc) +
  re-benchmark — đã ghi T12.

## P2-2 — Vòng lặp agent + tool use — ✅ 19/08

**Ý tưởng một câu:** chat trở thành agent — model tự quyết định gọi công cụ
(tìm tài liệu, đọc trí nhớ, xem trạng thái hệ thống) trước khi trả lời, mỗi
bước để lại vết trong bảng `agent_traces`.

### Quyết định thiết kế và lý do

| Quyết định | Lý do |
| --- | --- |
| Probe khả thi TRƯỚC khi thiết kế: gọi thử Ollama `/api/chat` với `tools` | `qwen3.5:9b` trả `tool_calls` chuẩn ngay lần thử đầu → dùng function calling native, không cần framework agent ngoài, không cần tự parse kiểu ReAct |
| Agent là **một vòng lặp bounded** trong `services/agent_service.py`; tools = 3 service có sẵn (retrieval, memory, health) | Đúng cam kết §5 của plan: "không thêm framework"; mọi tool đều là code đã test kỹ từ P0/P1, agent chỉ là người điều phối |
| Bật bằng cờ `use_tools` trên `/chat` thay vì endpoint mới | Contract cũ nguyên vẹn (frontend không được phá backend); web thêm một chip «Công cụ», Discord bật qua `DISCORD_AGENT_TOOLS_ENABLED` (mặc định bật — plan định `/ask` là cửa vào agent) |
| `max_steps: 3` trong models.yaml; hết ngân sách tool → ép trả lời thường bằng những gì đã gom | Mỗi vòng là một lần gọi 9b (~30–60s CPU); vòng lặp không bounded là vòng lặp treo máy |
| Trace: bảng `agent_traces` (migration `20260819_22`, additive + downgrade đủ), ghi **sau** khi message persist, `message_id` CASCADE | Bất biến agent-first: hành động tự hành phải audit được; không transaction nào ôm qua lời gọi model; trace không bao giờ sống lâu hơn câu trả lời nó giải thích. Xem lại: `GET /agent/traces/{message_id}` + hiện ngay dưới câu trả lời trên web |
| Tool lỗi → trở thành **dữ liệu** (`{"error": ...}`) đưa lại cho model, không ném exception | Một tool hỏng không được giết cả câu trả lời; model thấy lỗi và tự xoay xở (đã chứng minh sống — xem dưới) |
| SSE giữ một đường code: `use_tools`+`stream` → `meta` → `steps` → `token` (nguyên câu) → `done` | Agent chạy theo vòng nên không có token-stream thật; UI cũ chỉ thêm một handler `steps`, không cần đường gọi mới |
| Timeout bot Discord 180s → 360s | Một turn agent tối đa 4 lần gọi model trên CPU |

### Bằng chứng nghiệm thu (tiêu chí plan: *câu hỏi cần cả tài liệu lẫn memory —
### agent tự chọn tool, trả lời đúng, trace xem lại được*)

- **Test:** 6 test mới (`test_agent_service.py`): chọn tool rồi trả lời + trace
  replay được, câu chào không gọi tool, hết ngân sách ép trả lời, tool lỗi thành
  data, SSE đúng thứ tự sự kiện, thiếu agent thì degrade về chat thường. Suite
  **520 passed / 0 failed**; root 59; JS sạch.
- **Chuỗi sống 19/08, model 9b thật:** seed memory *"thích mở đầu bằng 'Tóm
  lại:'"*, hỏi *"backup PostgreSQL giữ bao lâu, tối thiểu mấy bản? Trả lời theo
  phong cách tôi đã dặn"* → agent tự chạy `search_documents` → `search_memory`
  (0.516) → `search_documents` (viết lại truy vấn) → trả lời **mở đầu "Tóm
  lại:"**, dẫn `local_ai_core_baseline.txt`, nêu đúng *02:15 hằng đêm* và *21
  bản gần nhất* — 7 bước trace, 93s, `GET /agent/traces/210` phát lại đủ. Chip
  «Công cụ» trên web toggle đúng trạng thái.
- **Bug bắt được nhờ chạy sống:** tool tài liệu ban đầu đọc key `text` trong
  khi retrieval trả `content` → excerpt rỗng. Điều giá trị: agent **không sập**
  mà trả lời trung thực "tài liệu không có thông tin" và đề nghị kiểm tra
  hệ thống — thiết kế error-as-data hoạt động đúng ngay lần đầu gặp sự cố thật.
  Đã sửa key và chạy lại: trích đoạn đầy đủ.
- Sửa kèm: test migration cũ ghim cứng head `20260818_21` (sẽ vỡ ở MỌI migration
  tương lai — đúng lớp lỗi từng gây 77 test đỏ hồi P0) → bỏ assert ghim, giữ
  các kiểm tra schema thật.
- **CI bắt được lỗi mà local che mất** (push đầu của P2-2 đỏ 3 test): (1) cờ
  `DISCORD_AGENT_TOOLS_ENABLED` mặc định bật khiến test Discord đi vào đường
  agent — local *vô tình xanh* vì Ollama đang chạy (suite phình 2:20 → 5:46 vì
  lén gọi 9b thật!), CI không có Ollama nên lộ → cô lập cờ trong conftest như
  các cờ memory; (2) hai test migration SQLite dùng id cố định 42/7 — khi tổng
  số message của các test chạy trước vượt 42, id đó bị chiếm → dời fixture lên
  vùng 900 triệu, hết đụng autoincrement vĩnh viễn. Suite sau sửa: 520/0 trong
  2:22 — đồng hồ suite chính là bằng chứng không còn gọi model thật.

### Giới hạn đã biết của P2-2 (không phải bug — đã ghi T12)

1. **Mở lại hội thoại cũ trên web không hiện lại khối «Agent đã dùng…»** — trace
   vẫn đủ trong DB và `GET /agent/traces/{id}`; UI lịch sử chưa fetch nó (cần
   messages trả kèm id).
2. **Discord không hiển thị tool đã dùng** — turn agent persist trace đầy đủ
   nhưng tin nhắn Discord chỉ có câu trả lời.
3. **Bấm Dừng ở web khi agent đang chạy** chỉ ngắt phía client; server chạy nốt
   vòng lặp và vẫn persist câu trả lời.
4. **`use_tools` với provider cloud** (gemini/deepseek làm general) sẽ 500 thay
   vì thông điệp rõ ràng — máy này luôn ollama nên chưa chạm.
5. **Latency Discord**: turn agent tốn 1–4 lần gọi 9b; nếu chậm quá thì
   `DISCORD_AGENT_TOOLS_ENABLED=false` là về lại chat thường ngay. Ngoài ra bật
   đồng thời «Ghi nhớ» + «Công cụ» có thể đưa memory vào ngữ cảnh hai lần (vô
   hại, chỉ tốn token).

## P2-3 — Bộ lệnh Discord chuyên nghiệp — ✅ 20/08

- 19/08: `/hoi` → `/docs` (tham số `tailieu` → `document`). Lý do chọn `/docs`
  thay vì `/ask`: bot **đã có** `/ask` (chat thường) từ trước — P2-2 đã biến
  `/ask` thành cửa vào agent tự chọn tool.
- 20/08: thêm **`/memory`** (điều agent đang nhớ về chính người gõ trong server
  đó — trả lời ephemeral chỉ người đó thấy, phân biệt 🤖 tự áp dụng / 👤 người
  duyệt, kèm chỉ dẫn thu hồi trên dashboard; backend là filter guild/subject
  trên `GET /api/memory-review/applied`) và **`/status`** (tóm tắt `/health`
  từng thành phần, ephemeral). Bộ lệnh chốt: `/ask · /docs · /memory · /status
  · /ping` — tên tiếng Anh chuẩn, mô tả tiếng Việt.
- Test: 6 test root (client gửi đúng filter + parse chống dữ liệu hỏng; hai
  formatter escape markdown, gắn nhãn reviewer, phân loại ok/disabled/lỗi).
- Bước người thật còn lại (như P1-1): gõ lệnh trong một server Discord thật —
  cần `DISCORD_TOKEN` và guild.

## P2-4 — Nhật ký hành động agent — ✅ 20/08

**Ý tưởng một câu:** một dòng thời gian trên dashboard trả lời "agent vừa làm
gì?" — nhớ/từ chối/thu hồi memory, trả lời bằng công cụ nào, việc nền chạy ra
sao — kèm nút Thu hồi ngay trên hàng còn gỡ được.

| Quyết định | Lý do |
| --- | --- |
| Không thêm bảng mới — timeline **đọc gộp** từ ba nguồn đã có sử liệu: quyết định memory (`discord_memory_candidates.reviewed_*`), câu trả lời agent (`agent_traces` kind `final` + đếm tool_call), việc nền (`jobs`) | Dữ liệu đã tồn tại đầy đủ nhờ các bất biến audit của P2-1/P2-2; thêm bảng ghi trùng là nợ đồng bộ |
| Phân biệt `memory_reject` với `memory_revert` bằng sự tồn tại của bản ghi memory | Từ chối trước khi áp dụng và thu hồi sau khi áp dụng là hai câu chuyện khác nhau trong sử liệu |
| Nút Thu hồi ngay trên timeline (chỉ hàng còn active) dùng đúng endpoint revert của P2-1 | Một đường ghi duy nhất; timeline là bề mặt thứ hai, không phải cơ chế thứ hai |

- Endpoint: `GET /agent/activity` (đọc, theo read-guard). Test: kiểm timeline
  trong test auto-apply (hàng `memory_apply` actor agent, revertable), test
  revert (`memory_revert`, hết revertable), test agent (hàng `agent_answer`
  kèm số lượt công cụ).

## Kiểm tra lại toàn bộ P2 — chuỗi sống 20/08, model thật

| Bước | Kết quả |
| --- | --- |
| Turn Discord (đúng tin nhắn 2b từng bịa) → agent mode trả lời | Câu trả lời ghi nhận yêu cầu; trace lưu |
| Extractor **9b thật** | Trích **đúng nội dung** (khác hẳn 2b), confidence 1.0, evidence nguyên văn |
| Guard xác định | Từ chối tự áp dụng (fact Anh / tin Việt — điểm mù xuyên ngữ) → **rơi đúng hướng an toàn: hàng chờ người** |
| Người duyệt 1 click | Mirror `mem_dc_*` vào kho chung |
| `/chat` bật «Công cụ» hỏi lại điều đã dặn | Agent **tự chọn** `search_memory`, tìm thấy (0.44), trả lời đúng: *"bạn luôn muốn câu trả lời đi kèm ví dụ minh họa cụ thể"* |
| Panel Nhật ký (P2-4) trên dashboard thật | Hiện đủ 4 hàng đúng thứ tự: agent trả lời → việc nền ingest → 🧠 Nhớ (kèm nút) → agent dùng trí nhớ |
| **Thu hồi từ chính timeline** | applied=0, hàng đổi thành `memory_revert`, search=0 — gỡ khỏi sử dụng, sử liệu còn |
| Suite chốt | Backend **527 passed / 0 failed** (2:18) · root **65** · JS/compile sạch · dọn sạch dữ liệu test |
