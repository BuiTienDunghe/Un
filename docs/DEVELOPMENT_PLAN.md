# Kế hoạch phát triển tổng thể — Local AI Core

**Phiên bản:** 1.3.1 · **Ngày:** 15/08/2026 · **Cập nhật:** 19/08 (agent-first) · 21/08 (track D + ngân sách inference) · 23/08 (đo trước khi đổi schema) · 24/08 (một môi trường vận hành duy nhất — gộp `machine_split.md`, nén lịch sử, liệt kê đầy đủ việc còn lại) · **24/08 v1.3.1 (T15 đóng kèm backfill; vá fallback BM25; sửa 5 lỗi tài liệu từ review đối kháng — KPI doc_hit, §3e, con trỏ §9x, §9.3 hàng 3, đối sách backup §8)** · **Trạng thái:** Đang hiệu lực

**Thay thế:** plan v1.2 và `docs/machine_split.md` (đã gộp vào §3, file đã xoá). Phần thiết kế memory của `docs/discord_memory_workflow_plan_v5_final.md` vẫn là spec cho P1-3..P1-5.

---

## 0. Đọc gì trước — bản đồ tài liệu

Tài liệu này là **nguồn sự thật duy nhất** cho định hướng và việc-cần-làm. Chi tiết thi công của từng mục đã đóng nằm ở nhật ký riêng; đừng nhân bản nội dung sang đây.

| Cần biết | Đọc |
| --- | --- |
| Định hướng, bất biến, việc còn lại | **Tài liệu này** — §1, §4 |
| Chạy/vận hành ở đâu, DB nào cho việc gì | **§3** của tài liệu này |
| Đã làm gì ở từng phase | `docs/p1_progress.md`, `p2_progress.md`, `p3_progress.md`, `p4_progress.md` |
| Số liệu eval retrieval | `docs/d1_retrieval_eval.md` |
| Grounding / faithfulness | `docs/d3a_answer_grounding.md` |
| Red-team injection | `docs/d5_redteam.md` |
| Backup & restore | `docs/backup_restore.md` |
| Kiến trúc hiện tại (mô tả code) | `docs/current_architecture.md` |
| P4-4b — thiết kế v1 và lý do hoãn | `docs/p4_4_design.md` + §9 của tài liệu này |
| Trí nhớ bot Discord — khảo sát Meta AI, thiết kế bốn tầng | `docs/memory_design.md` |

---

## 1. Tầm nhìn & định vị

> **Local AI Core là một agent AI cục bộ tự hành cho cá nhân và nhóm nhỏ: mọi dữ liệu ở trên máy của bạn, mọi câu trả lời có nguồn kiểm chứng được, các quy trình (ghi nhớ, index, dọn dẹp) do agent tự vận hành — con người giám sát thay vì duyệt tay. Vận hành bằng một cú click.**

### Nguyên tắc bất biến (không thương lượng khi thêm tính năng)

1. **PostgreSQL là nguồn sự thật duy nhất.** Qdrant và chỉ mục sparse là dẫn xuất, dựng lại được từ Postgres.
2. **Không transaction DB nào bao quanh một lời gọi model.** Sinh trước, ghi sau.
3. **Migration additive-only**, mỗi migration có `downgrade`, restore drill mỗi quý.
4. **Thay đổi chất lượng RAG chỉ thành mặc định sau khi eval đạt ngưỡng** — không có ngoại lệ "trông có vẻ tốt hơn".
5. **Launcher một-cú-click phải luôn chạy được** trên máy sạch: thiếu gói tùy chọn thì ghim cờ tắt, không để API từ chối khởi động vì lý do môi trường.
6. **Mọi hành động tự hành phải audit được và thu hồi được** (điều chỉnh 19/08 — agent-first).
7. **Ngân sách inference cố định** (điều chỉnh 21/08): không tính năng nào được tăng số **lời gọi model SINH** trên mỗi câu hỏi ở đường mặc định. Ollama một máy phục vụ một request một lúc — việc nền chạy sai lúc là chặn người dùng thật. Model chấm điểm nhỏ (cross-encoder, embedding) không tính vào ngân sách này nhưng phải đo độ trễ và có ngưỡng.
8. **Đo trước khi đổi schema** (điều chỉnh 23/08): thay đổi cấu trúc dữ liệu phải có số đo trên dữ liệu thật *trước* khi viết migration, không phải sau.

### Nhật ký điều chỉnh định hướng

| Ngày | Điều chỉnh | Hệ quả còn hiệu lực |
| --- | --- | --- |
| 19/08 | **Agent-first**: từ "workspace hai kênh" sang **một agent tự hành**; con người giám sát và thu hồi thay vì duyệt tay | Bất biến #6; phase P2 ra đời, các phase sau lùi số; nền human-review của P1-4 thành lưới giám sát |
| 21/08 | **Track D** (kỹ năng AI engineer) song song các phase sản phẩm; phân tích phần cứng cho thấy agent gọi model tuần tự nhiều lượt là điểm chết | Bất biến #7; D3c bị gác, D3a/D3b giữ |
| 23/08 | **Đo trước khi đổi schema** — thiết kế P4-4 v1 qua phản biện 5 tác nhân và không được chọn nguyên trạng; đo thật lật ngược hai ước tính dung lượng | Bất biến #8; P4-4b hoãn (§9); P4-4 tách thành P4-4a/P4-4b |
| **24/08** | **Một môi trường vận hành duy nhất** — mọi việc từ nay làm trên `PC-dungbt`. Xoá phân lane nhẹ/nặng, xoá `.machine-role`, gộp `machine_split.md` vào §3 | §3 là hợp đồng vận hành mới; §4 là danh sách việc phẳng, không còn cột "lane" |

---

## 2. Hiện trạng — đã đóng những gì

> Mỗi dòng một mục, giữ đúng số liệu chốt. Chi tiết thi công ở nhật ký tương ứng.

### 2a. Phase sản phẩm

| Phase | Trạng thái | Kết quả chốt |
| --- | --- | --- |
| **P0** — Nền móng tin cậy | ✅ | CI GitHub Actions (P0-1) · API key cho endpoint ghi/xoá (P0-2) · bảng `message_sources` giữ citation (P0-3) · backup tự động + restore drill (P0-4) · `pyproject.toml` + CHANGELOG (P0-5) · `alembic check` xanh trong CI (P0-6) |
| **P0.5** — Nợ audit 18/08 | Một phần | T1–T4, T6, T8, T11, T14, T15, T16, T17 ✅ đã trả. **Còn T5, T7, T9, T10, T12, T13** → §4 |
| **P1** — Một agent, hai kênh | ✅ 19/08 | `/docs` kèm nguồn · condense câu hỏi nối tiếp (eval 10/10, MRR 0.950 vs 0.787) · memory hub một kho hai kênh · pipeline người-duyệt end-to-end. Nhật ký: `docs/p1_progress.md` |
| **P2** — Agent tự hành | ✅ 20/08 | Memory tự áp dụng theo ngưỡng + guard xác định (extractor → `qwen3.5:9b`, poison 49% → 21.6%) · vòng lặp agent + tool use native, trace `agent_traces` · bộ lệnh `/ask` `/docs` `/memory` `/status` `/ping` · timeline hành động agent + thu hồi 1 click. Nhật ký: `docs/p2_progress.md` |
| **P3** — Đa người dùng & quản trị | ✅ 20/08 | Tài khoản + RBAC admin/member, JWT 15' + refresh thu-hồi-được · điều khiển bot Discord từ dashboard · biểu đồ thời gian · OCR console UI. Nhật ký: `docs/p3_progress.md` |
| **P4** — RAG nâng cao | Một phần | P4-1≡D1 ✅ · P4-2 ✅ · P4-3 ✅ · P4-4a(a,b) ✅ 25/08 · **P4-5 ✅ 25/08** · còn P4-4a(c)/B + P4-4b (gác chờ chuông 2 500 chunk) → §9. Nhật ký: `docs/p4_progress.md` |
| **P5** — Năng lực mở rộng | Chưa mở | Danh mục chọn lọc theo nhu cầu thật → §4f |

### 2b. Track D — kỹ năng AI engineer

| ID | Trạng thái | Kết quả chốt |
| --- | --- | --- |
| **D1** Eval engineering | ✅ 21/08 | Corpus 5 tài liệu + 82 câu (70 single, 12 cross) · endpoint `/rag/search` retrieval-only · job CI `retrieval-eval` chặn thoái lui. Baseline đo trong chính CI: **recall@5 0.866 · MRR 0.734 · doc_hit 0.768**. `docs/d1_retrieval_eval.md` |
| **D2** Distillation 9b → 2b | ⏳ Chưa làm | → §4d |
| **D3a** Self-check bám nguồn (không LLM) | ✅ 21/08 | `answer_grounding.py` chấm từng câu, **0 lời gọi model thêm**. grounding_rate **0.9390** (77/82), 0 ungrounded sau khi sửa cap xuyên ngữ, `language_mismatch` đánh dấu đúng 3 câu dịch. Hai vòng đối chiếu tay: **0 dương tính giả về độ tin cậy**. Quyết định: giữ ở mức **chỉ báo**, không tự động chặn. `docs/d3a_answer_grounding.md` |
| **D3b** Digest nền có luật nhường | ⏳ Chưa làm | → §4d |
| **D3c** Multi-step planning | ⛔ Gác | Điều kiện mở lại: **D2 đạt**. Độ trễ cộng dồn 5–8 lượt gọi/câu không cứu được bằng phần cứng |
| **D4** LLMOps / observability | ⏳ Chưa làm | → §4d |
| **D5** AI security — red-team injection | ✅ 22/08 | 6 tài liệu bẫy + 12 case + harness chấm marker xác định · `InjectionDefense` bọc passage/tool-result, **0 lời gọi model thêm**. attack_success **0.143 → 0.000**, benign **1.0** → cờ `rag.injection_defense` **BẬT mặc định**. D1/grounding không đổi. `docs/d5_redteam.md` |

### 2c. Khoảng trống còn lại

| # | Khoảng trống | Trạng thái |
| --- | --- | --- |
| G1–G6 | Auth · memory rời · Discord không dùng tài liệu · citation không lưu · câu nối tiếp · không CI | ✅ Đã đóng hết (P0–P3) |
| ~~G7~~ | Eval chỉ 1 tài liệu, đã bão hoà | ✅ Đóng bằng D1 (82 câu, 5 tài liệu, gate CI) |
| **G8** | **BM25 in-process**: RAM theo corpus · rebuild toàn bộ · chấm điểm O(corpus)/query · không nhất quán đa tiến trình | **Còn.** P4-4a xoá được nỗi đau rebuild; ba nỗi đau kia đợi P4-4b (đang hoãn — §9) |

---

## 3. Môi trường vận hành *(gộp từ `machine_split.md`, chốt 24/08)*

> **Từ 24/08 dự án chỉ còn MỘT môi trường thi công và vận hành: `PC-dungbt`.** Không còn phân lane nhẹ/nặng, không còn `.machine-role`, không còn handoff giữa hai máy. Mục này giữ lại mọi quy tắc vận hành đã trả giá để học được.

### 3a. Máy vận hành

| | |
| --- | --- |
| Hostname | `PC-dungbt` |
| Phần cứng | RTX 5060 Ti (16GB VRAM) · Ryzen 7 7700 (16 luồng) · 31GB RAM · Win 11 Pro |
| **Thư mục production** | **`C:\Users\dungbt06\local-ai-core`** — thuần ASCII, bắt buộc (§3b) |
| Khởi động | `run-local-ai-core.bat` (API + worker + backup worker). **Không** chạy `uvicorn` tay — backup worker chỉ sống trong phiên launcher |
| Cấu hình ship | Contextual retrieval **ON** · Reranker **ON** (`candidate_limit` 15) · Injection defense **ON** |
| Bot Discord | Bật/tắt từ dashboard (P3-2), qua `docker compose --profile discord` |

**Máy nhẹ `hehehhe`** giờ chỉ là **client LAN**: mở web UI qua trình duyệt trỏ vào `PC-dungbt`. Nó **không** chạy backend, worker, hay bot. Một quy tắc an toàn duy nhất còn lại:

> **Chỉ một máy được chạy bot Discord và chạm dữ liệu thật.** Hai instance cùng `DISCORD_TOKEN` = trả lời đúp; hai bản "dữ liệu thật" = hai nhánh rẽ (đã xảy ra 21/08).

### 3b. Thư mục production phải thuần ASCII — bài học 22/08

Production từng nằm ở `C:\Users\dungbt06\Ún promax\local-ai-core`. Chữ **"Ú"** gây ba lỗi độc lập, tất cả ở *ranh giới* giữa công cụ Unicode và công cụ mã hoá cũ:

| Lỗi | Cơ chế |
| --- | --- |
| Scheduled Task backup thất bại `0x80070002` (không tìm thấy file) ngay cả khi đường cũ còn | `schtasks` lưu/giải mã đường dẫn qua code page, dấu "Ú" bị mất |
| Gọi launcher qua đường 8.3 (`NPROMA~1\LOCAL-~1`) làm compose lập **project lạ `local-1`** (container/volume postgres rỗng) | compose lấy tên project từ tên thư mục; tên 8.3 khác tên thật |
| `pip install -r requirements.txt` chết `UnicodeDecodeError` (cp1252) | vá bằng requirements thuần ASCII + `PYTHONUTF8=1` trong launcher |

**Bài học**: đường dẫn có dấu không sai về nguyên tắc, nhưng mỗi công cụ hệ thống là một chỗ có thể mất dấu — production không nên đặt cược vào việc tất cả đều đúng.

Hai việc đi kèm còn hiệu lực:
- `git config --global safe.directory` phải trỏ đúng đường hiện tại (thư mục thuộc tài khoản `CodexSandboxOffline`).
- **Launcher phải khởi động qua `explorer.exe`** khi được gọi từ một phiên tự động — tiến trình con của phiên đó chết theo phiên (đã xảy ra 22/08).

### 3c. Lưới backup thứ hai — Scheduled Task (T14 ✅)

`backup-postgres-once.bat` ở gốc repo gọi `backup_worker --once --force`, độc lập launcher. Đăng ký một lần (người dùng tự chạy từ **Command Prompt có quyền admin** — tạo từ PowerShell nâng quyền rồi chạy lại từ cmd thường sẽ báo `Access is denied`):

```bat
schtasks /Create /TN "LocalAICore Backup" /SC DAILY /ST 02:00 /TR "\"C:\Users\dungbt06\local-ai-core\backup-postgres-once.bat\"" /F
```

Task chạy trong phiên đăng nhập (Docker Desktop phải đang chạy). Ghi chú: worker xét "backup gần đây" theo **mtime** của file, nên một dump *chép vào* thư mục trông như mới — `--force` là để lưới thứ hai không bị đánh lừa. Nghiệm thu: `/Run` thử → `Last Result: 0` + dump mới.

**Bổ sung 24/08 — một backup thành công giờ làm hai việc** (cùng một `run_once`, cả launcher lẫn Scheduled Task): dump Postgres → zip `data/documents/` kèm manifest SHA-256 vào `data/backups/sources/`. Việc thứ ba — mirror sang `BACKUP_MIRROR_DIR` — **có sẵn trong code nhưng đang tắt** (biến không đặt): máy chỉ có một SSD vật lý nên mọi đích trên máy này đều nằm cùng ổ với bản gốc; bật lại khi có ổ rời bằng cách bỏ comment một dòng trong `.env` (mirror hỏng chỉ ra warning, **không** làm hỏng backup chính). Chuông độc lập launcher: `python -m scripts.check_operational_alerts --fail-on-alert` (chạy từ `backend/`) kêu khi dump mới nhất quá **48h**, corpus vượt ngưỡng, hay job mất lease — đáng đăng ký thành Scheduled Task thứ hai lúc 08:00 để `Last Result` đỏ ngay buổi sáng. Sự cố có thật làm sinh ra chuông này: **02:00 các đêm 23–24/08 không ra dump** vì Docker Desktop tắt — task thất bại im lặng hai đêm liền, chỉ phát hiện khi tình cờ mở thư mục. `.env` (thứ duy nhất git lẫn dump đều không mang) giờ **tự vào backup mỗi đêm, dạng văn bản thường**, và **chỉ ghi khi nội dung đổi** nên thư mục là lịch sử chỉnh sửa chứ không phải 14 bản y hệt. Không mã hoá là **có chủ đích**: `.env` vốn đã nằm dạng thường ở gốc dự án, nên bản sao cạnh nó dưới `data/backups/` (gitignore chặn) **không hở thêm gì** — trong khi một passphrase lại thêm đúng một cách để mất backup vĩnh viễn, tức phá chính mục đích của backup. Khôi phục = chép file về, không cần công cụ gì.

**Chỉ khi bản sao rời khỏi máy này** (gửi cho ai, đẩy lên cloud, để trên ổ chung) mới cần mã hoá: bấm đúp `backup-env-once.bat` → `data/backups/env/.env.enc` (AES-256 + PBKDF2 200k), giải bằng `restore-env.bat` → ghi ra `.env.restored`, **không bao giờ đè `.env`**. `.bat` bọc `.ps1` vì bấm đúp `.ps1` mở Notepad và ExecutionPolicy có thể chặn — cùng lý do launcher là `.bat`.

### 3d. Cơ sở dữ liệu nào cho việc gì

| DB | Dùng cho | Quy tắc |
| --- | --- | --- |
| `local_ai_core` | **Production** — dữ liệu thật | Thí nghiệm **không được** xoá/sửa tài liệu thật. Corpus eval (5 fixture) được phép nằm chung (đã vậy từ D1) |
| `local_ai_core_lab_20260821` | **Đo đạc P4 / Track D** — đúng corpus 5 fixture như lúc ghi baseline | Trỏ `DATABASE_URL` sang đây trong phiên đo. Không drop |
| `local_ai_core_test` | Suite pytest | Tên **bắt buộc** kết thúc bằng `_test` |
| DB drill dùng-một-lần | Thí nghiệm phá hoại (đổi schema, xoá index) | Copy từ dump, xoá sau khi xong (ví dụ `local_ai_core_p44_test`, 23/08) |

Collection Qdrant đi theo cùng nguyên tắc qua `QDRANT_DOCUMENTS_COLLECTION`: `documents` (production) · `documents_lab` · `documents_test`.

**⚠ Cảnh báo đo lường trên DB production**: DB thật chứa `local_ai_core_baseline.txt` (tài liệu thật từ 14/08), mà tài liệu bẫy `xuong_in_anh_duong.txt` của bộ eval được viết nhái chính nó. Trong DB thật nó **chiếm hạng 1** ở mọi câu `xa_*`, đẩy chunk kỳ vọng xuống hạng 2 → recall không đổi nhưng MRR/doc_hit tụt. Đây là *môi trường đo* đổi, **không** phải retrieval thoái lui. Vì vậy: **đo trên DB lab, không dùng DB production làm thước**; không xoá tài liệu thật; không chỉnh dataset để "qua" sanity.

### 3e. Cờ cấu hình theo môi trường — **giữ nguyên cơ chế**

Phân lane hai máy đã bỏ, nhưng **CI vẫn là một môi trường thứ hai** không có GPU và không cài extra `[rerank]`. Cơ chế override qua `.env` vì thế **không được gỡ khỏi code**:

| Biến `.env` | Production | CI | Ý nghĩa |
| --- | --- | --- | --- |
| `RAG_CONTEXTUAL_RETRIEVAL_ENABLED` | *(không đặt → models.yaml = true)* | `false` | P4-2: 1 lời gọi model/chunk lúc index |
| `RAG_RERANKER_ENABLED` | *(không đặt → true)* | `false` | P4-3: cross-encoder 15 ứng viên/câu hỏi. +35ms trên GPU, **~990ms trên CPU** |
| `RAG_INJECTION_DEFENSE_ENABLED` | *(không đặt → true)* | *(theo mặc định)* | D5: bọc passage/tool-result, 0 lời gọi thêm |
| `QDRANT_DOCUMENTS_COLLECTION` | `documents` | `documents_test` | T11: cô lập vector index theo môi trường |

Ba cờ bật/tắt (contextual, reranker, injection defense) dùng chung một idiom `from_config(..., enabled_override=...)`; log khởi động ghi rõ nguồn quyết định (`source=env|models.yaml`). `QDRANT_DOCUMENTS_COLLECTION` là tên collection chứ không phải cờ — nó đọc thẳng từ `settings`, không qua resolver và không log nguồn (biến này từng gây trộn vector lab/prod — T11; thêm log khởi động cho nó gom vào T9). Launcher tự ghim `RAG_RERANKER_ENABLED=false` khi máy thiếu extra `[rerank]` — đúng bất biến #5.

Bật reranker mà **không** cài extra thì API **từ chối khởi động** với `RerankerUnavailableError` kèm đúng lệnh cần chạy. Bản `sentence-transformers` mặc định trên PyPI là **CPU-only**; máy có GPU NVIDIA cần:

```bash
pip install -e ".[rerank]" && pip install --index-url https://download.pytorch.org/whl/cu128 "torch==2.9.1+cu128"
```

### 3f. Quy tắc bảo mật (không thương lượng)

- Repo GitHub `BuiTienDunghe/Un` là **PUBLIC**. Tuyệt đối không commit: `.env`, `DISCORD_TOKEN`, `LOCAL_AI_API_KEY`, JWT secret, mật khẩu DB, dump backup, tài liệu người dùng thật.
- `data/` **không** đẩy lên git. Ngoại lệ đã theo dõi có chủ đích: `data/benchmarks/` và các baseline JSON nhỏ (`rag_multidoc_baseline*.json`, `rag_multidoc_grounding_baseline.json`, `redteam_baseline.json`).
- Những thứ git **không** mang theo khi dựng lại máy: `.env` và toàn bộ `data/` (gồm `data/qdrant/` bind-mount, `data/documents/`, `data/backups/postgres/`). Dữ liệu Postgres nằm trong named volume → phải restore từ dump theo `docs/backup_restore.md`, rồi `alembic upgrade head` (head hiện tại: `20260821_25`).

---

## 4. Việc còn lại — danh sách đầy đủ

> Không còn cột "lane". Thứ tự dưới đây là **thứ tự thi công khuyến nghị**, xếp theo: bug đang chảy máu → việc rẻ mở khoá việc khác → giá trị người dùng → nợ cấu trúc. Mỗi mục độc lập trừ chỗ ghi rõ phụ thuộc.

### 4a. Bảng tổng — thứ tự thi công

| # | Việc | Loại | Phụ thuộc | Ước lượng |
| --- | --- | --- | --- | --- |
| 0 | ~~**T17** — `DocxParser` mất bảng, textbox và heading (79–92% thân tài liệu)~~ | ✅ Đóng 24/08 | — | (xong, làm trước để đọc tài liệu đủ) |
| 1 | ~~**T15** — `replace_chunks` ghi thiếu 3 cột → citation mất `heading_path`~~ | ✅ Đóng 24/08 | — | (xong, kèm backfill 209 chunk) |
| 2 | ~~**Eval báo cáo độ trễ** + đo thật rebuild + đếm chunk active~~ | ✅ Đóng 24/08 | — | (xong: p50/p95/**max** trong eval · benchmark đo thật · `active_chunks` vào metrics + alert 2 500) |
| 3 | **P4-4a** — ~~(a) invalidate + (b) fingerprint~~ ✅ 25/08 (thiết kế TTL, xem §4c#3); (c)/B **gác chờ chuông 2 500 chunk** | ⚡ Hiệu năng | — | (phần còn lại: sau) |
| 4 | ~~**P4-5** — chunk visualization~~ | ✅ Đóng 25/08 (cả 2 phase — xem/đánh dấu; `docs/p4_5_design.md` + `p4_progress.md`) | — | (xong) |
| 4b | ~~**P4-6** — cross-encoder cắt cụt 65% chunk (778 token vs cửa sổ 512)~~ | ✅ Đóng 25/08 — cửa sổ trượt; MRR 0.858→0.936, doc_hit 0.854→0.927 | — | (xong) |
| 5 | ~~**T16** — ghim `pyvi` đúng version + `tokenizer_version`~~ | ✅ Đóng 25/08 — **nhưng cái ghim đo ra là vô hiệu** (pyvi 0.1.1 là bản duy nhất từ 2021); guard thật là **băm 2 file model**. Đọc §4b#5 trước khi tin là đã che chắn | — | (xong) |
| 6 | ~~**D4** — LLMOps / observability~~ | ✅ **D4-lite đóng 26/08** — cầu log thư viện; cây `request_logs.message_id`→`messages`→`message_sources` + token + băm prompt; 2 Scheduled Task (eval đêm 03:00 đã chạy thử thật, cảnh báo 09:30); lỗi ghi được. Kèm: bot Discord chạy image cũ 38 ngày, đã build lại. `docs/d4_design.md` | — | (xong, ~1 buổi) |
| 7 | **D3b** — digest nền có luật nhường | ✨ Track D | — | 3 buổi |
| 8 | ~~**T8** — tách `/ui/common.js`~~ | ✅ Đóng 25/08 — 4 bản chép hợp nhất còn 1; dashboard/ocr/chunks **có refresh token** lần đầu | — | (xong) |
| 9 | **T5** — Discord turn retry sau mất lease | 🐞 Nợ | — | 2 buổi |
| 10 | **T12 / T13** — đánh bóng agent P2 và auth P3 | 🔧 Nợ | — | 2–3 buổi mỗi mục |
| 10b | **MEM** — trí nhớ Discord theo `docs/memory_design.md` §13.6: **0a-0d** (khoá+protect · cửa sổ 40 · sửa đường đọc+xoá `search_memory` · key Gemini vào header+che secret log) → mở nghe 1 kênh đếm vài ngày → sổ gốc → BM25 theo-guild **rời đường đọc** → bộ eval 20 ca → verifier 3 trạng thái chạy đêm. Mục tiêu cỡ: **3 server × 100 tin/ngày, khởi đầu 1×30**. Tầng 3/Gemini giữ hoãn (3 chốt ở §12 tài liệu đó) | 🧠 **0-block ✅ · jobs 1-5 ✅ 28/08** (5 bước sau hội thoại guild 2 — memory_design.md §13.7: chống echo-lock, allowlist công cụ theo guild, từ vựng v2 + `user.birthday`, sổ cái nạp theo guild, sổ gốc + FTS `search_history`). **Benchmark đêm 28/08 ĐẠT gate §13.4** (P=0.94 · R=0.80 · forged=0 · verifier 16/16, sau khi vá think:false và mở 6 nhóm mẫu lọc) → verifier BẬT; tự-áp-dụng chờ chủ dự án đổi 1 dòng threshold. `search_history` thêm chế độ N-tin-mới-nhất. **Tầng 3 (việc 6) hạ cánh 28/08 tối** — 2 bảng lô+mệnh đề, worker nền, đường đọc §9.4, mục dashboard §9.7, cấm lời bot làm chủ thể (đo sống: 10 mệnh đề → 2); cần 2 công tắc mới chạy. Nợ sổ sách xong: 3 điểm soi-lỗi + `forget_member` + cảnh báo tồn đọng. Còn treo: tự-áp-dụng chờ 1 dòng .env, tripwire dense | 0a-0d ✅, jobs 1-6 ✅, benchmark ✅ | theo gate |
| 11 | **T7** — hợp nhất 2 pipeline ingestion | 🔧 Nợ lớn | — | 4–5 buổi |
| 12 | **D2** — distillation 9b → 2b | 🎓 Track D | GPU cloud | 4–6 buổi |
| 13 | **D3c** — multi-step planning | ⛔ Gác | **D2 đạt** | (sau) |
| 14 | **P4-4b** — chỉ mục sparse vào PostgreSQL | ⛔ Hoãn | Điều kiện mở lại ở §9 | (sau) |
| — | **T9** — gom mục nhỏ | 🔧 Nợ | Dọn khi đụng vùng | rải rác |
| — | **T10** — gỡ script migration SQLite | 🔧 Nợ | Sớm nhất 19/07/2027 | 1 buổi |
| — | **P5** — năng lực mở rộng | 🔭 Tương lai | Có use case thật | §4f |

### 4b. Bug và nợ đang chảy máu

**#0 · T17 — ✅ ĐÓNG 24/08. `DocxParser` chỉ đọc `document.paragraphs`.**

Phát hiện khi khảo sát 3 file docx thật (`data/uploads/`, không nạp vào DB). python-docx cố ý để bảng ở `document.tables` riêng, còn textbox nằm sâu trong `w:txbxContent` — parser cũ bỏ cả hai, và vứt luôn `paragraph.style.name` nên heading theo style của Word không bao giờ thành `#` mà chunker tìm.

| Đo trên thân tài liệu (`<w:t>`) | Sổ tay 45tr | Paper RAG | Paper Attention |
| --- | --- | --- | --- |
| Parser **cũ** | 78.7% | 90.1% | 92.3% |
| Parser **mới** | **100.3%** | **103.0%** | **103.3%** |
| Chunk bảng (cũ: 0) | 20 | 9 | 17 |

*(>100% vì thêm ký tự `#`, `|`, `---`. Đối chiếu Word: sổ tay 48.462/59.296 = 81.7% → khớp.)*

Ba bẫy đã xử lý: **(1)** duyệt `body` theo **đúng thứ tự tài liệu** thay vì hai danh sách rời (`.paragraphs` + `.tables` mất interleaving lẫn bảng lồng trong ô); **(2)** Word ghi shape **hai lần** — `mc:Choice` và bản VML `mc:Fallback` — lấy cả hai là nhân đôi nội dung (Attention: 44 `txbxContent` → **22 thật**); **(3)** ô bảng chứa `|` hoặc xuống dòng sẽ giả mạo cột / cắt sớm bảng, nên escape và làm phẳng.

**Bài học đo lường**: chỉ số "tỷ lệ chunk có heading" của bản cũ *cao hơn* bản mới (paper RAG 76% vs 46%) nhưng là **dương tính giả toàn phần** — cả 22 chunk mang đúng một nhãn sai `"Save the modified PDF document"` (dòng đánh số khớp nhánh số của `_HEADING_PATTERN`). Bản mới sinh 3 đường mục **đúng**. Đếm tỷ lệ mà không kiểm nội dung thì chọn nhầm phương án.

**Không sửa được, đã ghi rõ**: docx không có phân trang cố định và cả 3 file **không có page break nào** (`lastRenderedPageBreak` = 0) → `page_start` vẫn `None`, citation từ docx không nói được số trang. Ảnh trong docx cũng không qua OCR ([smart_parser.py:34](backend/app/parsers/smart_parser.py:34) chặn cứng chỉ `.pdf`) — để ngỏ, chưa có nhu cầu thật.

Test: 4 test dựng docx bằng python-docx ngay trong test (repo PUBLIC, không commit nhị phân bên thứ ba).

**#1 · T15 — ✅ ĐÓNG 24/08.** `replace_chunks` ghi đủ `locations`/`heading_path`/`token_count`; lệch kiểu chốt về **list** (chunker mang tuple heading parts, DB JSONB `list[str]`, Qdrant payload giữ dạng chuỗi join như mọi point cũ). `token_count` hoá ra **chưa từng được chunker tính** — đã thêm (`count_tokens(content)`). Test mới đi qua **đường ghi thật** (chunker → `replace_chunks` → BM25 đọc lại, fixture có heading) thay cho test dựng chunk bằng tay từng che lỗi. **Backfill production `scripts/backfill_chunk_metadata.py`**: dry-run rồi apply, 11 version khớp `content_hash` 100% (0 drift), 209/209 chunk điền `token_count`, 150 `heading_path`, 162 `locations`; 7 version page-mismatch (micro-drift T7: đường thread ghi page=None) chỉ điền heading/token, bỏ locations — đúng guard. **Không đụng** `retrieval_context`/embedding/Qdrant nên thứ hạng D1 không đổi. 75/118 chunk active giờ trả heading_path thật trong citation.

**#5 · T16 — ✅ ĐÓNG 25/08, nhưng KHÔNG phải vì lý do đã viết ban đầu. Đọc kỹ mục này trước khi tin là đã được che chắn.**

> **Bản ghi đính chính.** Bản đầu của mục này nói T16 chặn được chuyện «một bản `pyvi` khác sau khi cài lại sẽ đổi lexeme». **Điều đó sai**, và sai theo cách chỉ lộ ra khi đi đo. Giữ nguyên đoạn này thay vì xoá, vì cái bẫy nhận thức ở đây đáng nhớ hơn bản vá.

**Vì sao cái ghim không ghim được gì.** `pyvi 0.1.1` là bản **mới nhất** trên PyPI, phát hành **30/06/2021 — 1.882 ngày trước** — và là bản **duy nhất** thoả dải cũ `>=0.1.1,<1.0`. Dải cũ và ghim cứng vì thế trỏ vào **cùng một artifact, mỗi ngày, suốt 5 năm**. `pip install -U pyvi` là lệnh rỗng. Cái ghim chưa từng đổi một lần cài đặt nào và không thể, cho tới khi upstream sống lại.

**Thứ thật sự quyết định cách cắt từ thì chưa bao giờ được ghim.** Không phải số phiên bản, mà là **hai file dữ liệu nạp lúc import** — `pyvi/models/words.txt` (354.580 B; 22.705 bigram + 1.907 trigram) và `pyvi/models/pyvi3.pkl` (789.337 B trọng số CRF) — cộng một bộ giải mã C mà `requirements.txt` **không hề nhắc tới**: `python-crfsuite`, `sklearn-crfsuite`, `scikit-learn`, `numpy`. Không dòng nào, không `--hash`, không lockfile. Đã chứng minh chạy được: một `pyvi` đặt trước trên `sys.path` không kèm dist-info vẫn báo `0.1.1`, `TOKENIZER_VERSION` vẫn đọc `pyvi-0.1.1`, ghim vẫn sạch — trong khi `quản_lý_tài_liệu` đã vỡ làm hai.

**Test canary một câu là phép thử điểm, không phải hợp đồng.** Quét toàn bộ bigram của từ điển có mặt trong kho production: **468** cái nếu bị đụng sẽ cắt lại kho; canary bắt **3** trong 468 (**0,6%**), và đúng ba từ nó tự viết trong câu assert của chính nó. Một chỉnh sửa thực tế — thêm 8 từ ghép chuyên ngành mà một đội RAG tiếng Việt hoàn toàn có thể thêm — cắt lại **169/190 chunk** và dịch **3,11%** vị trí token trong khi mọi guard đều xanh.

**Nên guard thật là băm 2 file** (`test_the_segmenter_model_files_are_the_ones_the_baseline_was_measured_with`): phủ **toàn bộ** phần từ điển + trọng số thay vì 0,6%. Đổi hash **chỉ được phép** đi kèm ghi lại baseline eval — số retrieval đã đo trên đúng những byte đó.

**Thiệt hại nếu thật sự trôi, đã đo trên kho thật (190 chunk, 82 câu, hết đường ống):** 3/82 câu mất đoạn dẫn đầu chứa đáp án, **1/82 câu mất hẳn đáp án khỏi cửa sổ ngữ cảnh**, còn "đáp án nằm đâu đó trong 5 đoạn" thì hoà 79–79. Nhỏ, nhưng **im lặng tuyệt đối** — đó mới là lý do đáng canh.

**Giá phải trả của toàn bộ T16:** 4 ms một lần mỗi tiến trình (`importlib.metadata`), 0,03 ms mỗi lần dựng lại BM25 (dòng log), **0 ms mỗi câu hỏi**, ~30 byte trên `/models`. Canary tất định qua 5.012 lần chạy.

Các phần còn giữ và lý do giữ, dù phần lớn hiện chưa có tác dụng đo được:

1. **Ghim cứng `pyvi==0.1.1`** — là tờ bảo hiểm rẻ **đang không dùng đến**, không phải tờ bảo hiểm vô dụng: ngày upstream ra bản mới nó thành có tác dụng mà không cần ai nhớ đi ghim. Nâng dòng này **là một thay đổi retrieval**: chạy lại gate, ghi lại baseline.
2. **`TOKENIZER_VERSION` đọc ngược từ gói đã cài**, không hard-code. Nó **gọi tên cái hộp**, không xác thực thứ bên trong — đừng nhầm hai việc đó (chính là chỗ bản đầu đã nhầm).
3. **Đặt cạnh dữ liệu dẫn xuất**: log `bm25_rebuilt`, trường `tokenizer_version` ở `/models`, và trường trong baseline eval — `evaluate_rag.py` từ chối gate khi baseline đo bằng tokenizer khác, **và từ chối GHI** baseline khi máy chủ không báo trường này (nếu không, một baseline `tokenizer_version: null` sẽ qua gate vĩnh viễn mà trông y hệt baseline hợp lệ).
4. **Canary một câu** — yếu (0,6%) nhưng là guard **duy nhất** phủ đường bộ giải mã đổi, thứ mà băm file không thấy.

**Còn mở, là quyết định chính sách chứ không phải bản vá:** bốn gói bộ giải mã vẫn chưa ghim và vẫn ra bản mới (`python-crfsuite` 0.9.12 tháng 12/2025). Thay đổi gần đây của chúng chỉ là đóng gói, nên đây là đường có thật nhưng chưa gấp. Và nhánh tokenizer của gate ở CI **chưa được vũ trang**: job `retrieval-eval` dùng `rag_multidoc_baseline_bare.json` vốn không có con dấu, nên hiện chỉ in cảnh báo.

**#9 · T5 — Discord turn retry sau mất lease giữa chừng** *(2 buổi)*
Gọi model 2 lần và ghi trùng cặp message. Hướng: chỉ persist message sau khi `save_response` xác nhận ownership.

**#8 · T8 — ✅ ĐÓNG 25/08. Frontend fork đôi helper.**

Không phải hai bản mà **bốn**: `app.js`, `dashboard.js`, `ocr.js`, `chunks.js` mỗi file một bản `$`, `el`, theme và hàm gắn header — và bốn bản **không giống nhau**. Đó không phải chuyện thẩm mỹ: bản của dashboard từng quên hẳn `X-API-Key` (lỗi đã sửa), và đến hôm nay **vẫn** thiếu refresh token, nên access token hết hạn là văng thẳng về trang đăng nhập giữa lúc đang xem dù refresh token còn hạn.

`/ui/common.js` (158 dòng) giờ giữ bản chuẩn duy nhất: `$`, `el`, `esc`, `readStore`/`prefs`/`savePrefs`, theme, `getApiKey`/`setApiKey`, `authHeaders`, `refreshAccessToken`, `ERROR_HINTS`, `sendJson`, `requestJson`. Script thường, không build step, nạp **trước** script của trang (`defer` giữ thứ tự).

Hai quyết định đáng ghi:

- **`sendJson` và `requestJson` tách đôi.** Ba trang phụ dùng `requestJson` — tự thử refresh một lần rồi gửi lại. Trang chat không dùng được vì 401 ở đó phải hiện overlay đăng nhập **tại chỗ** chứ không chuyển trang, nên nó ghép `sendJson` + `refreshAccessToken` theo cách riêng. Phần khó (gom mọi lời gọi refresh vào **một** promise, tránh mười request cùng 401 xoay vòng refresh token mười lần) nằm ở bản dùng chung.
- **Bearer gắn vô điều kiện.** Bản cũ của `app.js` chỉ gắn khi `authState.enabled`; ba bản kia gắn luôn. Đã kiểm `app/security/auth.py`: máy chủ đọc header này **sau** khi kiểm `auth_enabled`, nên token cũ sót lại lúc chế độ tài khoản tắt bị bỏ qua hoàn toàn. Chọn bản đơn giản hơn, và là bản 3/4 trang vốn đã chạy.

**Thu được ngoài dự kiến**: món "dashboard 401 không refresh token" trong danh sách audit **tự đóng** — nó là hệ quả trực tiếp của việc bốn trang cùng dùng một đường gọi API.

Thi hành: test đọc khai báo top-level của cả 5 file, đòi **giao rỗng** giữa mỗi trang và `common.js`. Đây là lỗi thật chứ không phải luật phong cách — hai script cổ điển chung phạm vi global **không thể** cùng `const $`, trang sẽ chết ngay. Cộng test mỗi trang phải nạp `common.js` **trước** script của mình.

Kiểm chứng trình duyệt thật, cả 4 trang: chat (30 nút hội thoại, gửi tin chạy), dashboard (6 thẻ số liệu, 10 lời gọi API 200), chunks (37 đoạn + POST/GET/DELETE feedback trọn vòng, 204 và 404 đều xử đúng), ocr (lịch sử tải được). Console sạch.

**#11 · T7 — `PostgresDocumentService` chứa 2 bản sao pipeline ingestion** *(4–5 buổi)*
Bản thread và bản RQ đồng bộ tay, đã có micro-drift. Hướng: tách `IngestionPipeline` một bản duy nhất tham số hoá bằng checkpoint hook; tách upload-conflict thành service riêng.

**#10 · T12 — Đánh bóng agent P2** *(2–3 buổi)*
UI hiện lại trace khi mở hội thoại cũ (messages cần trả kèm id) · footer tool cho tin Discord · huỷ vòng lặp khi client ngắt · map lỗi tools-với-provider-cloud thành 502 rõ nghĩa · tránh nạp memory hai lần khi bật cả «Ghi nhớ» lẫn «Công cụ» · **guard xuyên ngữ**: fact tiếng Anh vs tin Việt bị từ chối oan (an toàn nhưng mất coverage; hướng: prompt extractor v6 viết fact bằng ngôn ngữ tin gốc + re-benchmark).

**#10 · T13 — Đánh bóng auth P3-1** *(2–3 buổi)*
Đổi mật khẩu + admin reset qua UI · trang quản lý user trên dashboard (hiện chỉ API) · token localStorage → cân nhắc cookie httpOnly nếu mở ra ngoài LAN · member-role staleness 15' ở surface thường · ẩn/hiện điều khiển theo role còn thiếu chỗ nào thì server vẫn chặn.

**T9 — Gom mục nhỏ đã xác nhận** *(rải rác, dọn khi đụng vùng)*
DashboardService thay SQL trong router · đảo phụ thuộc parsers→services · `ConversationLifecycle` chung cho chat/rag · gom wiring OCR router · race trùng tên file khi upload đồng thời · fencing ownership cho `fail_job`/`mark_cancelled` · fixture `memory_transport` đếm job memory-ingest toàn cục, scope theo prefix.

**T10 — Gỡ script migration SQLite** *(1 buổi, sớm nhất 19/07/2027)*
`migrate_sqlite_to_postgres.py`, `migrate_sqlite_documents_to_postgres.py`, `migrate_document_storage.py`, `audit_sqlite_readonly.py` + 2 test bị ghim bởi cam kết giữ SQLite archive read-only 1 năm.

### 4c. P4 — RAG nâng cao, phần còn lại

**#2 · Eval báo cáo độ trễ** *(0.5 buổi)*

`run_multidoc_mode` hiện **không** báo cáo độ trễ, trong khi P4-4a hứa cải thiện đúng thứ đó. Không có thước thì không nghiệm thu được. Thêm `p50_latency_ms` / `p95_latency_ms` vào summary. Làm **trước** #3.

**#3 · P4-4a — Gỡ tắc nghẽn rebuild BM25** *(0.5–1 buổi, không đụng schema)*

Ba việc:

| | Việc | Hiện trạng đã xác minh |
| --- | --- | --- |
| (a) | ✅ **25/08**: `on_corpus_change` trên `PostgresDocumentService` → `bm25.invalidate` (main.py nối dây) | Gọi sau activate (cả hai đường), delete, remove_source — ghi **cùng tiến trình** thấy ngay ở câu hỏi kế tiếp |
| (b) | ✅ **25/08 — chọn TTL thay vì bỏ hẳn**: fingerprint chạy tối đa 1 lần/5 s thay vì mỗi câu hỏi | Bỏ hẳn + invalidate-only sẽ **mù vĩnh viễn** với ghi từ tiến trình khác (RQ worker, cleanup container) — thiết kế TTL không cần chốt từ-chối-khởi-động nào, an toàn với mọi hình dạng triển khai; ghi ngoài tiến trình được thấy trong ≤5 s |
| (c) | Dựng lại chỉ mục ở luồng nền, phục vụ chỉ mục cũ trong lúc dựng | Hiện dựng lười ở câu hỏi đầu tiên sau mỗi lần khởi động — cả request phải chờ. **Cân nhắc phương án B trước** (xem dưới) |
| (d) | ✅ **Đã vá 24/08**: đường fallback token-overlap tách từ lại **toàn corpus mỗi query** zero-score (câu hỏi ngoài corpus) | `search()` giờ dùng lại `doc_freqs` BM25Okapi đã dựng — cùng token, cùng công thức, thứ hạng giữ nguyên từng điểm; test khoá "1 lời gọi tokenizer mỗi query" |

Vì sao đáng làm — **đo thật 24/08 trên corpus production 118 chunk** (`scripts/benchmark_bm25_rebuild.py`, chỉ đọc; nhật ký đầy đủ ở `p4_progress.md` mục "P4-4a — số nền"). Số cũ từ fixture 27 chunk đã bị thay: tỷ lệ pyvi thật là **92.9%** (từng ghi 98.1%), chấm điểm warm thật **~3.8 ms** (ngoại suy cũ ~1.2 ms — lệch ~3×, đúng kiểu lỗi fixture-27 mà §6 cảnh báo):

| Corpus | Câu hỏi đầu sau khởi động (cold, gồm pyvi init) | Rebuild steady-state | Chấm BM25 warm mỗi query |
| --- | --- | --- | --- |
| **118 (đo thật 24/08)** | **0.48–0.52 s** | **0.383 s** = tokenize 0.356 s (**92.9%**) + snapshot 12.4 ms + fingerprint 5.7 ms + build 8.9 ms | **3.6–4.3 ms** |
| 1 000 *(ngoại suy tuyến tính từ hàng trên)* | ~4 s | ~3.2 s | ~32 ms |
| 5 000 *(ngoại suy)* | ~20 s | ~16 s | **~160 ms** |

Đường fallback all-zero (câu ngoài corpus) sau bản vá 24/08: **4.5 ms** — trước vá nó trả nguyên một lần rebuild (~0.38 s @118, lớn dần theo corpus). Hàng RAM đã bỏ: chưa từng là nỗi đau (bảng cũ tự xác nhận ~26 MB @10 000).

Hai hệ quả của số mới: **(1)** chấm warm @5 000 chunk ~160 ms ≈ **26% của p50 622 ms** — lớn hơn nhiều so với ước cũ (~50 ms), nên "phần BM25 trong tổng độ trễ" là cò súng đúng cho P4-4b (§9.5) và sẽ kêu quanh ~2 500–3 000 chunk, khớp ngưỡng cảnh báo đã đặt; **(2)** cột giữa vẫn là nỗi đau P4-4a nhắm — và **p95 không nhìn thấy nó** (một câu chậm trong 82 câu nằm ở max, không ở p95), nên eval giờ báo cả `max_latency_ms`.

Nghiệm thu (a)+(b) đã đạt 25/08: mỗi query trong cửa sổ TTL bớt 1 truy vấn DB (đo: 5.7 ms/lần) · ghi cùng tiến trình thấy ngay (test wiring thật: delete → search kế tiếp trống dù TTL 1 giờ) · **D1 Δ = 0** hiển nhiên — không đổi thuật toán xếp hạng, chỉ đổi *khi nào* kiểm tra thay đổi. Ràng buộc từ-chối-khởi-động cũ **không còn cần**: TTL giữ fingerprint sống ở mọi cấu hình. Còn lại của mục này: (c) dựng nền vs **B** — gác chờ chuông 2 500 chunk (cold hiện chỉ ~0.5 s).

**Phương án B — lưu lexeme pyvi xuống DB** *(1–1.5 buổi, một migration additive)*: nhật ký đo 23/08 kết luận "vẫn nên làm" cả A lẫn B (`p4_progress.md`), và §9.1 xếp B **xoá** 98.1% chi phí rebuild trong khi A(c) chỉ **giấu** nó sau một bài toán concurrency. §4e cũ loại B vì muốn "không đụng schema" — lý do đó phải được cân nhắc tường minh khi làm #3, không được im lặng. B phụ thuộc T16 (`tokenizer_version` phải nằm cạnh lexeme đã lưu).

**#4 · P4-5 — Chunk visualization** *(3 buổi, học RAGFlow)*

Xem chunk của tài liệu trong UI, đánh dấu chunk kém, để người dùng tự chẩn đoán "tại sao trả lời sai".

**Đính chính 23/08: KHÔNG phụ thuộc P4-4.** `docs/p4_4_design.md` §12 nói ngược, nhưng cả 8 cột màn hình cần — `content`, `retrieval_context`, `chunk_index`, `page_start`, `page_end`, `section_title`, `block_type`, `content_hash` — **đã có sẵn** trong bảng `document_chunks`. ~~Chỉ cần #1 (T15) xong trước~~ **T15 đã đóng 24/08** — `heading_path`/`locations`/`token_count` giờ có dữ liệu thật (75/118 chunk active mang heading), màn hình dùng được **9 cột** (thêm `locations` để tô vị trí trong tài liệu gốc).

Nghiệm thu P4-5: `GET /documents/{id}/chunks` phân trang trả đủ 9 cột, `heading_path` khác `null` với tài liệu có heading · UI hiện chunk theo `chunk_index`, tô vùng `page_start`–`page_end` · "đánh dấu chunk kém" chốt nơi lưu (cột `status` hay bảng mới) **trước khi code** · test 3 tầng theo §6 · **0 lời gọi model thêm** (bất biến #7). Nếu phần "đánh dấu" kéo ước lượng quá 3 buổi thì tách nó thành mục riêng, ship phần chỉ-đọc trước.

**#14 · P4-4b — Chỉ mục sparse vào PostgreSQL** — ⛔ **HOÃN**, xem §9 (thiết kế, số đo, điều kiện mở lại).

### 4d. Track D — phần còn lại

**#6 · D4 — LLMOps / observability** — ⚠️ **ĐÃ KHẢO SÁT 25/08. Ước lượng và phạm vi cũ đều sai. Đọc `docs/d4_design.md` trước khi bắt tay.**

> *Mô tả gốc, giữ lại để đối chiếu:* «Hợp nhất sử liệu rời (`agent_traces`, `request_logs`, dashboard) thành **trace một-câu-hỏi-một-cây**: retrieval → tool call → generation, kèm token vào/ra, thời gian, prompt version. Prompt quản lý như code — mỗi version có số hiệu gắn điểm eval (extractor đã qua 5 đời prompt không sử liệu). Chỉ ghi metadata, không thêm lời gọi model.» *(3–4 buổi)*

Khảo sát trên hệ thống thật lật ba giả định của đoạn trên:

- **«Hợp nhất 3 nguồn»** — `agent_traces` có **0 dòng** và được thiết kế để mãi mãi 0 dòng (cascade xoá theo hội thoại; sequence đã ở 20, bảng ở 0). `dashboard` không phải bản ghi mà là bộ hiển thị. Chỉ còn **một** bảng thật, `request_logs` 142 dòng, **65% là lời gọi của robot eval**.
- **«5 đời prompt không sử liệu»** — thực ra là **4 đời** (nhãn `_V5` gắn trên đúng văn bản V4, không tồn tại thân V5), và **sử liệu CÓ tồn tại**: 8 file trong `data/benchmarks/discord_memory_extractor/`, gồm cả cú sụt v3 (schema compliance 1.0 → 0.05).
- **«token + prompt version»** — đã xây **trọn vẹn** ở nhánh Discord extractor, ghi vào bảng 0 dòng mà không code nào đọc lại. Xây bản thứ hai cùng hình dạng là lặp lại một thí nghiệm đã thất bại.

**Và điều đáng kể nhất:** cây trace — sản phẩm chủ lực của D4 — **sẽ không bắt được lỗi lớn nhất lịch sử dự án**. Khi cross-encoder cắt cụt 65% kho suốt 4 ngày, thời gian vẫn bình thường và các chunk đã nằm sẵn trong `message_sources`; cây trace không hiện gì bất thường. Thứ bắt được nó là **một dòng cảnh báo `778 > 512` của tokenizer** — mà hệ thống hiện vứt đi, vì `logging_service.py` chỉ cấu hình loguru, không có `InterceptHandler` cũng không `captureWarnings`. **0 dòng khớp trong cả 8 file log 30 ngày.**

Phạm vi chốt lại — **D4-lite, ~1,5 buổi, không thêm bảng nào**: (1) bắt cảnh báo thư viện vào sink đã có; (2) thêm **một cột** `request_logs.message_id` để nối ba bản ghi đã có sẵn thành cây — hiện **19% dòng câu hỏi đã mồ côi** vì khoá nối duy nhất là dấu thời gian lệch 19 ms; (3) hai cột token (Ollama đã trả sẵn, `ollama_client.py:57` vứt đi) + **băm prompt đã lắp ráp**; (4) đăng ký eval cấu hình-đang-chạy thành Scheduled Task — CI cố ý chỉ đo đường trần nên **không gì đang canh cấu hình production thật sự chạy**; (5) làm cho một lỗi có thể được ghi (142/142 dòng đều `status='ok'` — nhánh lỗi chưa từng chạy).

**Hai va chạm bất biến phải giải trước khi thêm bất kỳ bảng nào** — trace tự xoá lịch sử qua cascade, và span bao quanh lời gọi model vi phạm bất biến #2. Chi tiết ở `docs/d4_design.md` §6.

**#7 · D3b — Digest nền có luật nhường** *(3 buổi)*

Agent tự tổng hợp định kỳ (tài liệu mới, memory đáng chú ý, việc nền lỗi) gửi Discord. **Luật nhường bắt buộc** theo bất biến #7: chỉ chạy khi hệ rảnh ≥ N phút · tự dừng ngay khi có request tương tác · kích hoạt tay được (`/digest`) · máy tắt thì bỏ lượt, không dồn. Audit + thu hồi theo bất biến #6.

**#12 · D2 — Distillation extractor 9b → 2b** — ⚠️ **SPEC ĐÃ VIẾT 04/09: `.scratch/d2-distillation/spec.md`. Đọc trước khi bắt tay; ba chi tiết của mô tả cũ đã sai.**

> *Mô tả gốc, giữ lại để đối chiếu:* «(QLoRA, 4–6 buổi, GPU cloud free) 9b làm teacher sinh vài nghìn cặp (tin nhắn → fact), lọc bằng guard sẵn có; fine-tune 2b trên Colab/Kaggle (đủ cho 2b, không đụng máy nhà). Nghiệm thu bằng chính benchmark 19/08.»

Ba chỗ sai và số đo lật chúng:

- **Không QLoRA.** Hướng dẫn Qwen3.5 của Unsloth khuyến cáo không dùng 4-bit cho họ model này → **bf16 LoRA r=16–32**. Kéo theo: **không Colab T4** (T4 không có bf16); train tại nhà trong cửa sổ ban ngày, vì 9b nạp rồi vẫn còn ~9,3 GB VRAM (đo 04/09).
- **Nghiệm thu không thể lấy mốc 19/08.** Lần đó 9b chỉ chạy 75/150 ca và dùng prompt v5, còn 2b chạy đủ 150 ca — hai mẫu số, hai prompt, không so được. Đã đo lại cả hai ngày 04/09 trên đúng 150 ca, đúng prompt v6: `data/benchmarks/discord_memory_extractor_20260904_*.json`. Ngưỡng nghiệm thu chốt theo bộ số mới, nằm trong spec.
- **Động cơ không phải độ trễ.** Số cũ (61 s/lời gọi) là số CPU; trên GPU 9b p50 3,8 s và 2b 1,9 s, tức chỉ ~2×. Lý do thật nằm ở khoảng cách hành vi: 2b **ngang hoặc hơn** 9b về schema compliance, evidence grounding và acceptance, nhưng kém 0,34 ở no_op accuracy và 0,25 ở fact content — tức nó biết viết đúng định dạng, chỉ không biết khi nào nên im lặng. Giả thuyết H-DATA trong spec kiểm chính điều đó, và có ô đối chứng dung lượng để nó có thể sai.

Thất bại cũng chốt được bằng số liệu, và spec bắt buộc phải công bố kết quả âm.

Vai trò chiến lược: **lối thoát phần cứng** — bước phụ của agent giao được cho model nhỏ. Là **điều kiện mở lại D3c**.

**#13 · D3c — Multi-step planning** — ⛔ **GÁC**

Phân rã câu hỏi đa tài liệu thành nhiều lượt retrieval (đúng điểm yếu cross-doc thấy khi test 2 paper 20/08). Gác vì độ trễ cộng dồn 5–8 lượt gọi/câu không cứu được bằng phần cứng. Điều kiện mở lại: **D2 đạt**. Khi mở cũng chỉ dạng **có điều kiện** (heuristic rẻ phát hiện câu cần phân rã, ~90% câu single-hop đi đường cũ) + **cap cứng** tổng lượt gọi mỗi câu.

### 4e. Thứ tự đề xuất cho phiên làm việc tới *(mục lịch sử — cả bốn việc đã đóng 24–25/08)*

1. **#1 T15** — bug production, rẻ nhất, mở khoá #4.
2. **#2 độ trễ trong eval** — cần trước để nghiệm thu #3.
3. **#3 P4-4a** — xoá triệu chứng "câu hỏi đầu sau khởi động bị treo".
4. **#4 P4-5** — mục có giá trị người dùng lớn nhất trong danh sách.

~~Bốn việc gộp ~5 buổi~~ **Cập nhật 24/08: #0 (T17 docx), #1 (T15 + backfill), #2 (thước đo: eval p50/p95/max · benchmark rebuild đo thật · đếm chunk active + cảnh báo) và §4c#3(d) (vá fallback) đã xong.** Còn lại theo thứ tự: #3 (P4-4a — số đo mới nghiêng về giữ (a)+(b) rẻ, còn (c) vs B cân bằng số: cold chỉ 0.5 s hôm nay, 16–20 s @5 000) → #4 (P4-5). Còn lại: #2 (thước đo, kèm **đo thật rebuild trên corpus production** thay hàng ngoại suy 118) → #3 (P4-4a, chọn giữa (c) và phương án B bằng số của #2) → #4 (P4-5). Không mục nào đụng schema trừ khi #3 chọn B (một migration additive).

### 4f. P5 — Năng lực mở rộng *(chỉ làm khi có use case thật)*

> Tool use cơ bản đã lên P2-2 (thành lõi agent). **Quyết định 20/08: GÁC OCR và vision** — OCR console (P3-4) giữ nguyên như đã ship, không đầu tư thêm; bộ eval chỉ dùng tài liệu text-native. Cấu hình `ocr.enabled` giữ nguyên (chỉ chạy khi gặp tài liệu thiếu text layer).

- **Tool bên ngoài cho agent** (tra cứu ERP xưởng?) — chỉ khi có use case cụ thể.
- **Vision attachments**: đính ảnh vào chat (nền `vision_chat` đã có; endpoint `/vision/chat` đang 501).
- **Web search opt-in** cho câu hỏi ngoài tài liệu (mặc định tắt vì định vị riêng tư).
- **MCP client** nếu hệ sinh thái nội bộ cần nối tool ngoài.
- Fork/branch hội thoại; resumable streams đa tab.

---

## 5. Kiến trúc đích *(không đổi xương sống, chỉ bồi)*

```
Web UI ─┐                                  ┌─ Qdrant (vector index)
        ├─ FastAPI ── services ── Postgres ┤
Discord ─┘    │                            └─ BM25 in-process (rank_bm25) — P4-4b hoãn
              ├─ Auth layer (P0-2 → P3-1)
              ├─ Memory hub (P1-5): một kho, hai kênh đọc/ghi
              ├─ Agent core (P2-2): planner + tools (RAG/memory/status), trace từng bước
              └─ RQ workers (ocr/index/memory) + outbox + cleanup
```

Đường truy xuất hiện tại, đã xác minh từ code: câu hỏi → condense (nếu là lượt nối tiếp) → embed (`qwen3-embedding:0.6b`) → **Qdrant search (limit 180) + BM25 (rank_bm25 trong RAM, token pyvi)** → **RRF** (k=60, dedup theo document_id/version_id/chunk_id) → **cross-encoder rerank** (15 ứng viên → 5) → clip `max_context_chunks=5` → `wrap_passage` (D5) → `qwen3.5:9b`.

- **API versioning**: giữ endpoint hiện tại; breaking change đầu tiên mở namespace `/api/v1/`, alias cũ giữ 1 minor version.
- **Agent core**: vòng lặp plan→act→observe trong `services/`, dùng lại retrieval/memory/health có sẵn làm tool — không thêm framework agent ngoài.
- **Cấu trúc code**: giữ `routers → services → repositories/stores`; không thêm framework.
- **Plugin-lite**: chưa làm hệ plugin tổng quát cho tới khi có ≥ 2 nhu cầu mở rộng thật.

---

## 6. Chất lượng & quy trình

| Mảng | Chuẩn áp dụng |
| --- | --- |
| Test | 3 tầng (unit service / integration repository / endpoint); mục tiêu coverage 80% cho `services/` |
| Eval | Là **gate chất lượng RAG**: mọi thay đổi retrieval/prompt phải chạy eval trước-sau, ghi kết quả vào PR. Job CI `retrieval-eval` chặn thoái lui |
| Review | Thay đổi lớn qua review đối kháng — đã chứng minh hiệu quả hai lần: 17 lỗi thật (UI, 08/18) và 6 lỗi thiết kế + 3 số sai (P4-4, 23/08) |
| Release | Tag `vX.Y.Z` + CHANGELOG; mỗi phase đóng = một minor version |
| Migration | Additive-only; mỗi migration có `downgrade`; restore drill mỗi quý |
| **Đơn vị** | Bài học 25/08 (P4-6): `chunk_tokens: 480` đếm bằng thước **đếm-từ regex** của chunker, cross-encoder đếm bằng **subword** — tiếng Việt nở ~1.6× giữa hai thước, và 65% chunk vượt cửa sổ model mà không ai biết. Mọi giới hạn độ dài phải ghi rõ **đơn vị của bộ phận nào**; cảnh báo `N > max` của thư viện phải được đọc, không để chìm trong log. |
| **Số liệu** | Mọi con số trong tài liệu phải ghi rõ **đo thật** hay **ngoại suy**, và trên corpus nào. Bài học 23/08: hai ước tính dung lượng sai 2–3 lần vì bỏ quên index và suy từ fixture 27 chunk |
| **Ghim** | Bài học 25/08 (T16): một **số phiên bản gọi tên cái hộp, không xác thực thứ bên trong**. Ghim `pyvi==0.1.1` hoá ra vô hiệu (đó là bản duy nhất tồn tại từ 2021), trong khi hợp đồng thật — hai file dữ liệu 354 KB + 789 KB và bốn gói giải mã — chưa hề được ghim. Khi ghim một phụ thuộc **sinh ra dữ liệu**, hãy hỏi «cái gì thực sự quyết định đầu ra?» rồi ghim **thứ đó** (băm nội dung), không ghim cái nhãn. |
| **Nghiệm thu** | Bài học 25/08: một guard chỉ đáng tin khi **đã bị phá thử**. Ba lưới viết trong ngày đều xanh và đều thủng — regex bị `var`/thụt lề/`async function` lách, canary phủ 0,6% chứ không phải 100%, gate tự tháo ngòi khi ghi baseline `null`. Không cái nào lộ ra bằng cách đọc code; tất cả lộ ra khi cố tình phá. **Guard mới phải kèm bằng chứng nó bắt được đúng thứ nó nói.** |

---

## 7. KPI theo dõi

| KPI | Baseline D1 (21/08) | Sau P4-2+P4-3 | Mục tiêu |
| --- | --- | --- | --- |
| recall@5 | 0.866 | **0.988** | ≥ 0.95 ✅ |
| MRR | 0.734 | **0.936** | ≥ 0.90 ✅ |
| doc_hit | 0.768 | **0.927** | ≥ 0.90 ✅ |
| MRR cross-doc | 0.590 | **0.861** | ≥ 0.85 ✅ |
| Grounding rate (D3a) | — | **0.9390** | giữ ≥ 0.90, 0 dương tính giả |
| Attack success rate (D5) | 0.143 (defense OFF) | **0.000** | giữ 0.000 |
| `/rag/search` p50 | 587 ms | **341 ms** (đo lại 26/08, §7b) | ≤ 900 ms ✅ |
| `/rag/search` p95 | 617 ms | **358 ms** (đo lại 26/08, §7b) | ≤ 1 200 ms ✅ — lưới an toàn chung, bắt mọi thoái lui bất kể nguồn |
| `/rag/search` max | — | **614 ms** (26/08) | theo dõi. Câu **nguội** giờ đã tách ra và đo riêng: **6,8 s** cho `/rag/chat` đầu tiên sau khởi động (§7b) — p95 vẫn mù với nó, nên đọc hai số cùng nhau |
| Phần BM25 trong p50 (warm ms ÷ p50) | — | **~0.6%** (3.8/622, đo 24/08) | **≥ 15% → xét mở P4-4b** (§9.5) — cò súng đúng: canh chính chi phí P4-4b chữa |
| Chunk active | 118 | **190** (`metrics.active_chunks`, 26/08) | cảnh báo **2 500** (`check_operational_alerts --chunk-warn`) · xét P4-4b ở **5 000** |
| Memory bị thu hồi | — | — | < 30% |
| CI | ✅ 3 job + eval gate | | xanh trên main |

### 7b. Bảng độ trễ tham chiếu — đo lại sạch 26/08/2026

> **Vì sao phải đo lại.** Mọi con số độ trễ dự án từng trích đều lấy từ `request_logs` của **tuần phát triển**: đầy khởi động nguội, thí nghiệm đổi cấu hình, một reranker cắt cụt 65% kho (sửa 25/08), và một lỗi ghi độ trễ theo lịch của bộ dọn rác (sửa 26/08). Chúng mô tả một hệ thống không còn tồn tại. Bảng cũ nói `/chat` p95 = **80 giây** và `/rag/chat` max = **219 giây**; đo lại trên chính máy đó, sau một lần khởi động sạch, sai lệch **10–70 lần**.

Điều kiện đo: corpus **production 190 chunk**, API vừa khởi động lại, 5 câu hỏi cố định mỗi mặt, cấu hình đúng như đang chạy (contextual retrieval + reranker BẬT, agent tools BẬT trên đường Discord).

| Mặt người dùng chạm vào | Trung vị | Dải | Ghi chú |
| --- | --- | --- | --- |
| Khởi động API → `/health` ok | **3,9 s** | — | đã gồm nạp cross-encoder (`warmup()`) |
| **Nguội**: câu `/rag/chat` đầu sau khởi động | **6,8 s** | — | dựng chỉ mục BM25 + nhân đầu tiên. Một lần mỗi lần khởi động, **không** phải mỗi câu |
| `/rag/search` (chỉ truy xuất) | **367 ms** | 334–368 | |
| `/rag/chat` (truy xuất + sinh) | **1,8 s** | 1,1–2,0 | |
| **UI web · `/chat` — chữ đầu tiên** | **289 ms** | 285–541 | *đây là thứ người dùng cảm nhận* |
| UI web · `/chat` — trọn câu trả lời | 6,0 s | 4,9–8,0 | ~375 token sinh ra |
| **UI web · `/rag/chat` — chữ đầu tiên** | **683 ms** | 646–1008 | |
| UI web · `/rag/chat` — trọn câu trả lời | 1,4 s | 1,1–1,5 | ~29 token: trả lời ngắn, có căn cứ |
| **Discord** · lượt đầy đủ 4 chặng | **1,7 s** | 1,4–7,2 | resolve → xếp lượt → thực thi → hoàn tất |

**Discord đo trên lưu lượng THẬT** (13 lượt của người dùng, 25/08 19:55–20:02, đường phiên bền vững, đọc từ log container):

| | Trung vị | Dải |
| --- | --- | --- |
| Chờ trả lời | **2,6 s** | 1,7–7,2 s (lượt 7,2 s là câu đầu sau khởi động) |
| Khoảng cách giữa hai lần trả lời | **27 s** | 11–72 s |

> Khoảng cách giữa các lượt (11–72 s) **luôn lớn hơn nhiều** thời gian trả lời (1,7–7,2 s): hàng đợi FIFO của kênh chưa bao giờ có quá một lượt. So với ngân sách chờ 180 giây thì lượt chậm nhất còn **dư 25 lần** — kịch bản "kẹt vì quá hạn" mà §4 từng nêu là **không có cơ sở thực nghiệm**; xem §7c.

**Token mỗi lượt** — lần đầu tiên đo được (cột `request_logs.tokens_in/out`, có từ 26/08):

| Đường | Token vào | Token ra |
| --- | --- | --- |
| `/rag/chat` | 2 099 – 2 711 | 30 – 50 |
| `/chat` (không prompt hệ thống riêng) | 47 – 51 | 319 – 544 |
| **Discord (agent tools)** | **1 154 – 2 652** | 53 – 125 |

> Prompt Discord nặng gấp **25–50 lần** chat thường ở phía đầu vào — prompt hệ thống của bot + ngữ cảnh thành viên + định nghĩa công cụ. Đây là thứ chi phối chi phí đường Discord, và trước 26/08 **không nhìn thấy được**.

**Chất lượng RAG, đo lại cùng ngày** trên corpus lab (đúng luật §3d), 82 câu, retrieval-only: recall@5 **0.9878** · MRR **0.9360** · doc_hit **0.9268** · truy xuất p50 **341 ms** / p95 **358 ms** / max **614 ms** · `qwen3-embedding:0.6b` · `pyvi-0.1.1`. Gate đạt.

### 7c. Kỷ luật rút ra

| | |
| --- | --- |
| **Số cũ là số của tuần phát triển** | Đừng trích `request_logs` gộp nhiều ngày rồi gọi đó là hiệu năng. Tách **nguội/ấm**, tách **cấu hình**, và từ 26/08 thì lọc luôn theo `status` — dòng lỗi mang `latency_ms=0` và dòng `stopped` mang thời gian bị cắt ngang. |
| **p95 trên mẫu nhỏ là số vô nghĩa** | 47 lượt trong 7 ngày cho "p95 = 80 giây" chỉ vì cái đuôi là vài lần khởi động nguội. Đo lại có kiểm soát: p95 thật nằm dưới 8 giây. |
| **Trung vị không mô tả trải nghiệm streaming** | Người dùng cảm nhận **chữ đầu tiên** (289 ms), không phải câu trọn vẹn (6 s). Đo sai đại lượng thì tối ưu sai chỗ. |
| **Đo lại sau mỗi lần sửa lớn** | Bảng này được sinh lại bằng `scripts/nightly_eval.py` (chất lượng) và một lần chạy có kiểm soát (độ trễ). Lần đo tiếp theo nên là **sau một tuần dữ liệu thật**, giờ mỗi dòng đã có `message_id` + token + băm prompt để truy nguyên. |

> **Đóng 25/08 — cả hai ô đã đạt (P4-6).** Chẩn đoán 24/08 đoán sai thủ phạm: không phải *biên chunk* mà là **cross-encoder cắt cụt passage** — chunk đúng dài 778 token, cụm mang đáp án nằm ở token 583–743, tức sau điểm cắt 512. Chunker, BM25, dense và RRF đều xếp nó hạng 1–2; chỉ tầng chấm lại đánh rơi. Chính màn hình chunk (P4-5) là thứ dẫn tới phép đo này. Sửa bằng **cửa sổ trượt ở tầng rerank**: MRR 0.858→0.936, doc_hit 0.854→0.927, recall 0.976→0.988; 11 câu tốt lên, 2 xấu đi. ⚠ Đánh đổi có ghi chép: điều kiện nghiệm thu tự chốt bị vi phạm ở đúng một câu — xem `p4_progress.md` mục P4-6.

---

## 8. Rủi ro & đối sách

| Rủi ro | Mức | Đối sách |
| --- | --- | --- |
| Một người bảo trì | Cao | Automation trước tính năng (CI, backup, eval gate) — đã có đủ ba |
| Scope creep từ cảm hứng dự án lớn | Trung | Mục "cố tình KHÔNG theo" ở §10; mỗi mục P4/P5 cần use case thật |
| Extractor tự áp dụng memory sai → trí nhớ bẩn | **Cao — đã đo 19/08**: confidence là hằng 1.0 ở mọi lỗi (τ vô nghĩa); 2b lọt 49% độc, 9b + guard còn 21.6% | Extractor 9b + guard evidence/overlap; giám sát + thu hồi 1 click là lưới chính; benchmark lại sau mỗi thay đổi extractor |
| Việc nền của agent chặn request tương tác (Ollama 1 slot/máy) | Trung — tăng nếu thêm D3b | Bất biến #7; luật nhường của D3b là điều kiện nghiệm thu, không phải tuỳ chọn |
| Prompt injection qua tài liệu/tin nhắn | Trung — tăng theo multi-user | ✅ D5 đóng: defense BẬT mặc định, attack 0.000. Đo lại khi đổi model sinh hoặc prompt hệ thống |
| **Chỉ còn một máy — chết ổ SSD là mất sạch dữ liệu** | **Cao — CHẤP NHẬN CÓ Ý THỨC (25/08)** | **Quyết định 25/08: backup ở lại trong dự án, không mua USB, không đẩy cloud.** Mọi thứ nằm dưới `data/backups/` (gitignore chặn, đi theo folder dự án khi copy đi nơi khác). Hệ quả phải nói thẳng: **chết thanh SSD là mất sạch** — dump, tài liệu, `.env` cùng một chỗ. Đây là *đánh đổi đã cân nhắc* (giữ riêng tư + không tốn phần cứng) chứ không phải việc chưa làm. Cái thực sự bảo vệ được, đã có: xoay vòng 14 ngày/giữ 3 · zip `data/documents/` kèm manifest SHA-256 mỗi đêm · **bản sao `.env` mỗi đêm, ghi-khi-đổi** (dạng thường — xem §3c về lý do không mã hoá mặc định) · **chuông độc lập launcher** `check_operational_alerts --dump-max-age-hours 48` (bắt đúng sự cố 2 đêm 23–24/08). Nghĩa là **ba thứ một máy dựng lại cần đều nằm trong `data/backups/`**: dữ liệu, tài liệu gốc, cấu hình. Chúng chống **xoá nhầm, ghi hỏng, backup chết im lặng** — không chống chết đĩa. Cơ chế mirror giữ nguyên trong code, tắt bằng một dòng comment: cắm ổ rời bất kỳ vào là bật lại được ngay. Code luôn ở GitHub |
| Corpus lớn dần làm BM25 in-process chậm | Thấp hôm nay (118 chunk), tăng dần | P4-4a xoá tắc nghẽn rebuild; theo dõi p95 `/rag/search` sau khi có #2; P4-4b mở lại theo điều kiện §9 |

---

## 9. Phụ lục — P4-4b: hai phương án và lý do hoãn

> Giữ lại đầy đủ để khi mở lại không phải làm lại từ đầu. Thiết kế v1 nguyên vẹn ở `docs/p4_4_design.md` (đọc kèm 8 đính chính ở banner đầu file). Toàn bộ số đo: `docs/p4_progress.md`, mục "P4-4b — chọn phương án bằng số đo".

### 9.1 — Bốn nỗi đau G8 và không gian lựa chọn

| | G8-1 RAM theo corpus | G8-2 Rebuild chặn câu hỏi đầu | G8-3 Chấm điểm O(corpus)/query | G8-4 Đa tiến trình (`--workers`) |
| --- | --- | --- | --- | --- |
| **A — P4-4a** (§4c#3, không đụng schema) | ❌ | ✅ *giấu* độ trễ (dựng nền) | ❌ | ❌ |
| **B — chỉ lưu token xuống DB**, vẫn `rank_bm25` trong RAM | ❌ | ✅ *xoá* 98.1% chi phí | ❌ | ❌ |
| **v1 — mảng `text[]` + GIN** | ✅ | ✅ | ⚠️ **lý thuyết có, đo thật thì không** | ✅ |
| **v2 — vá lỗi + giải bài toán chọn lọc** | ✅ | ✅ | ✅ *nếu* bộ lọc thật sự lọc | ✅ |

### 9.2 — Ba ứng viên, ưu và nhược

**v1 — ba cột trên `document_chunks`** (`retrieval_lexemes text[]` + GIN, `retrieval_tf jsonb`, `retrieval_len int`), ứng viên lọc bằng `&&`, DF tính trong truy vấn, BM25 chấm trong app.

*Ưu*: schema nhỏ nhất (3 cột, không bảng mới) · ghi cùng transaction với chunk nên không có trạng thái dẫn xuất lệch pha · đọc dễ · rollback = tắt cờ.
*Nhược*: bộ lọc **không lọc** (đo: kéo 97.5% corpus, 59/82 câu kéo 100%) · dùng toán tử `text[] & text[]` **không tồn tại** trong PostgreSQL · `N`/`df`/`avgdl` lấy từ ba tập khác nhau khi backfill dở → **sai âm thầm** · thiếu `tokenizer_version` · ~214.7 mục GIN mỗi chunk khi ghi.

**v2-A — v1 đã vá + cắt lexeme phổ quát theo DF.**
*Ưu*: rẻ nhất, giữ hình dạng mảng, **thử được trước khi đổi schema** (mô phỏng trên chỉ mục RAM).
*Nhược*: thêm một siêu tham số phải chỉnh theo corpus; đo thật cho thấy ngưỡng an toàn không hạ selectivity xuống đủ thấp.

**v2-B — bảng posting** `chunk_lexemes(lexeme, chunk_ref, tf)` + index theo lexeme.
*Ưu*: giải **cấu trúc** bài toán chọn lọc, DF có sẵn từ `count(*)`.
*Nhược*: dung lượng đảo ngược hoàn toàn ưu thế của v1 (đo: **12.3×**) · bảng dẫn xuất tách rời thêm một bất biến phải giữ · rollback phải dọn bảng.

### 9.3 — Kết quả đo 23/08 → **HOÃN**

Đo trên `PC-dungbt` (production chỉ đọc; thí nghiệm ghi trong DB dùng-một-lần `local_ai_core_p44_test`, đã xoá). Quy tắc chọn được chốt **trước** khi đo và không sửa sau.

**Cắt DF (số #2, đo thật):**

| Ngưỡng `df/N` | Production 118 chunk (trung vị / p95) | câu MẤT | Lab 27 chunk | câu MẤT |
| --- | --- | --- | --- | --- |
| không cắt (v1) | 100.0% / 100.0% | 0 | 100.0% | 0 |
| 0.10 | 19.5% / 29.7% | 1 | 18.5% | 23 |
| 0.15 | 28.4% / 38.1% | 0 | 33.3% | 1 |
| **0.20** | **34.7% / 47.5%** | **0** | **40.7%** | **0** |
| 0.30 | 43.2% / 57.6% | 0 | 63.0% | 0 |
| 0.50 | 57.6% / 72.0% | 0 | 85.2% | 0 |

**Dung lượng và planner (số #3/#4/#5, đo thật; hàng 1k/5k là corpus nhân bản):**

| | 118 chunk | 1 000 | 5 000 |
| --- | --- | --- | --- |
| v2-A (3 cột + GIN) | 3.65× | 2.08× | 1.89× |
| v2-B posting | 12.64× | 12.38× | 12.32× |
| Planner chọn | Seq Scan 3.0 ms | Seq Scan 24 ms | Seq Scan 126.9 ms |

**Áp quy tắc chọn:**

| Nhánh | Điều kiện | Đo | Phán |
| --- | --- | --- | --- |
| v2-A | < 30% & 0 câu mất | 34.7% / 40.7% | ✗ |
| v2-B | posting ≤ 3× | 12.3× | ✗ |
| **hoãn** | #2 trượt & #4 ≫ ước tính | #4 = 12.3× | **✓** |

**Ba chỗ plan từng ghi sai** (số liệu thắng):

| Từng ghi | Đo thật | Nguyên nhân |
| --- | --- | --- |
| v1-đã-vá "~1.06× corpus" | **3.65×** @118, **1.89×** @5 000 | **bỏ quên index GIN** (riêng nó 2.29×); `text[]` thật 1.21× chứ không phải 0.68× (suy từ fixture 27 chunk) |
| posting "~7× (ước tính)" | **12.32–12.64×** | ước tính bỏ qua chuỗi `lexeme` lặp mỗi hàng + B-tree (40% tổng) |
| v2-A "*có thể* giải G8-3" | chưa kết luận được | phán quyết cũ dựa trên số #5 — §9.4#1 chỉ ra EXPLAIN thiếu `ANALYZE` và truy vấn không đại diện; giữ trạng thái *chưa chứng minh* |

### 9.4 — Hai chỗ số liệu yếu hơn kết luận của nó

Ghi lại để không mang đi làm căn cứ về sau. **Không** làm đổi quyết định hoãn.

1. **Truy vấn dùng cho số #5 không đại diện cho workload.** `EXPLAIN` chạy trên một câu 5 từ chọn tay, và chính log cho thấy nó **chọn lọc ~7%** (GIN chạm 8 heap block / 247 buffer) — trong khi số #1 đo workload thật ở **97.5–100%**. Ở 7% mà planner vẫn chọn Seq Scan là dấu hiệu **thống kê chưa cập nhật** (không thấy `ANALYZE` sau khi nạp corpus 1k/5k), chứ chưa chắc là tính chất của thiết kế. Câu "planner không dùng GIN ở **bất kỳ** quy mô nào" vì thế là suy rộng từ một câu. Muốn dùng lại con số 126.9 ms làm căn cứ thì phải đo lại bằng một câu D1 thật sau khi cắt DF, và chạy `ANALYZE` trước.
2. **Corpus nhân bản là "chặn dưới" cho dung lượng, nhưng *bi quan* cho selectivity.** Nhân bản giữ `df/N` **không đổi** theo N; corpus thật lớn lên thì từ nội dung loãng ra còn hư từ vẫn phổ quát, nên selectivity thật ở 5 000 chunk nhiều khả năng **tốt hơn** 34.7%.

**Kết luận vẫn giữ nguyên, và nó đứng trên số #1 chứ không phải số #5**: ở ngưỡng DF an toàn duy nhất dùng chung được, bộ lọc còn để lại **34.7% corpus** — chỉ cắt được ~3 lần khối lượng chấm điểm. Ba lần không đủ trả cho một thay đổi schema + một siêu tham số phải chỉnh theo corpus + chi phí ghi GIN.

### 9.5 — Điều kiện mở lại

Mở lại P4-4b khi corpus active vượt **~5 000 chunk** *và* **phần BM25 trong p50 `/rag/search` vượt ~15%** (warm ms từ `benchmark_bm25_rebuild.py` chia p50 từ eval), **hoặc** khi có cách chọn lọc đo được **< 30% ổn định trên ≥ 2 corpus đủ lớn** (corpus lab 27 chunk quá nhỏ để `df` mang nghĩa thống kê — nó không phải phép thử hợp lệ).

*Sửa 24/08 — vế cũ "p95 vượt ngân sách" là cò súng câm, hai lỗi đo được:* **(1)** BM25 warm chỉ chiếm ~0.6% p50 hôm nay và ~26% ở 5 000 chunk (ngoại suy từ số thật) — tổng p95 622→~780 ms vẫn dưới mọi ngân sách hợp lý rất lâu sau khi chính BM25 đã thành vấn đề; canh tổng để phát hiện một thành phần là canh nhiệt độ ngoài trời để biết bếp cháy. **(2)** cơn treo rebuild là **một** câu trong 82 — nó nằm ở `max_latency_ms`, p95 không chạm tới theo cấu trúc. p95 ≤ 1 200 ms vẫn giữ ở §7 nhưng với vai trò lưới an toàn chung, không phải điều kiện P4-4b.

Khi mở lại: **đo lại cả năm số**, vì tỷ lệ dung lượng lẫn lựa chọn của planner đều phụ thuộc quy mô. **v1 nguyên bản không được chọn trong mọi trường hợp** — nếu số liệu ủng hộ hình dạng mảng thì đó là v2-A. Ràng buộc chung: phải qua **D1 Δ ≤ 0.02** trên cả ba chỉ số, và đường `inprocess` sống song song cho tới khi baseline mới được ghi.

---

## 10. Đối chiếu thị trường — học ai, học gì, bỏ gì

Khảo sát 15/08/2026:

| Dự án | Stars | Điều đáng học nhất |
| --- | --- | --- |
| [Open WebUI](https://github.com/open-webui/open-webui) | ~148.8k | RBAC + user groups; hybrid search (BM25+vector) mặc định — xác nhận hướng đã đi; model evaluation arena; hệ plugin Pipes/Filters/Tools |
| [RAGFlow](https://github.com/infiniflow/ragflow) | ~88.3k | **Chunking giải thích được** (visualization cho người duyệt → P4-5); traceable citations; fused re-ranking |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | ~54k | UX "document-first workspace" |
| [LibreChat](https://github.com/danny-avila/LibreChat) | ~42k | Agents + MCP + tool use; fork/branch hội thoại; resumable streams |
| [Onyx (Danswer)](https://github.com/onyx-dot-app/onyx) | ~13k | Connectors doanh nghiệp; trợ lý theo team |

**Cố tình KHÔNG theo** (giữ định vị tối giản): hỗ trợ 9 vector DB / đa provider phức tạp — giữ Qdrant + Ollama (+ Gemini/DeepSeek tùy chọn) · code interpreter sandbox đa ngôn ngữ · connector SaaS — dữ liệu ta là file cục bộ, đúng định vị riêng tư.

### Nguồn tham khảo

- [Anthropic — Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval): −49% retrieval failure, −67% kèm reranking (cơ sở của P4-2/P4-3)
- [Searching for Best Practices in RAG (arXiv 2407.01219)](https://arxiv.org/pdf/2407.01219)
- Chuẩn FastAPI production 2026: cấu trúc domain, JWT + refresh, test 3 tầng ([tổng hợp](https://dev.to/datanestdigital/production-ready-fastapi-project-structure-2026-guide-b1g))
- So sánh phân khúc: [OpenWebUI vs LibreChat vs Onyx](https://onyx.app/insights/openwebui-vs-librechat-vs-onyx), [AnythingLLM vs Open WebUI vs LibreChat](https://runaihome.com/blog/anythingllm-vs-open-webui-vs-librechat-2026/)
