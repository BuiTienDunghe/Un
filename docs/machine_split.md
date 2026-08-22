# Phân lane hai máy — nhẹ vs nặng

Dự án chạy trên hai máy: một **máy nhẹ** (daily driver, dùng hằng ngày, GPU yếu) và
một **máy mạnh** (dùng ít hơn, để dành việc nặng). Tài liệu này quy định việc nào
chạy ở máy nào, và cách một phiên Claude Code **tự biết mình đang ở máy nào** để
nhận đúng phần việc.

Cơ chế này là hệ quả trực tiếp của bất biến *ngân sách inference cố định* (plan §1):
máy nhẹ không gánh nổi model sinh chạy nhiều lượt, nên việc nào cần model sinh phải
dồn sang máy mạnh — còn lại làm ở đâu cũng được, ưu tiên máy nhẹ vì đó là nơi ngồi
nhiều nhất.

## Vận hành ở đâu — quyết định 21/08/2026

**Máy nặng `PC-dungbt` = máy VẬN HÀNH (production)**: giữ dữ liệu thật (Postgres +
`data/documents` + Qdrant), chạy launcher (API + worker + **backup worker**), chạy bot
Discord, cấu hình ship đầy đủ (contextual + reranker). **Máy nhẹ `hehehhe` = máy VIẾT
PLAN / CODE / TEST**: lane nhẹ, suite, tài liệu; dùng hệ thống như *client* qua LAN
(trình duyệt / Discord trỏ vào máy nặng). Lý do: production phải hưởng P4-2/P4-3 (máy
nhẹ không chạy nổi reranker: +990ms CPU) và backup phải sống cùng launcher trên một máy.

Hệ quả bắt buộc:

| Quy tắc | Vì sao |
| --- | --- |
| **Dữ liệu thật chỉ tồn tại ở máy nặng.** DB/Qdrant trên máy nhẹ là dữ liệu dev, bỏ được | Hai bản "thật" là hai nhánh rẽ — đã xảy ra 21/08 (máy nặng restore nhầm dump 18/08) |
| Snapshot chỉ đi **một chiều: nặng → nhẹ** (dump → restore làm dữ liệu dev khi cần) | Không bao giờ copy ngược; thứ máy nhẹ tạo ra là code + tài liệu, đi qua git |
| **Chỉ một máy chạy bot Discord** (máy nặng). Máy nhẹ không đặt `DISCORD_TOKEN` hoặc không bật profile `discord` | Hai instance cùng token = trả lời đúp |
| Máy nặng khởi động **bằng launcher** (không chạy uvicorn tay) + Scheduled Task `backup_worker --once` hằng ngày làm lưới thứ hai | Backup worker chỉ sống trong phiên launcher — đó là cách dump 18/08 thành điểm phục hồi duy nhất |
| Thí nghiệm trên máy nặng **không được xóa/sửa tài liệu thật**; corpus eval (5 fixture) được phép nằm chung DB (đã vậy từ D1); thí nghiệm phá hoại (đổi schema, xóa index) chạy trên DB drill copy từ dump | Production và phòng thí nghiệm chung một máy thì ranh giới phải nằm ở quy tắc |
| Máy nhẹ giữ `.env` với `RAG_*_ENABLED=false` và DB test riêng (`local_ai_core_test`) cho suite | Đúng lane nhẹ |

Bàn giao 21/08: dump cuối của dữ liệu thật từ máy nhẹ `local-ai-20260821-131518.dump`
(3 tài liệu, 1 hội thoại, 91 chunk, head `20260821_25`; đã drill restore thành công) +
`data/documents/` → máy nặng restore theo mục "Khôi phục thật" trong `docs/backup_restore.md`.

**Đã thực hiện 22/08 trên `PC-dungbt`** — nghiệm thu từng bước:

| Bước | Kết quả |
| --- | --- |
| Restore | DB lab đổi tên `local_ai_core_lab_20260821` (giữ); DB mới khớp dump: alembic `20260821_25`, 3 tài liệu, 1 hội thoại, 91 chunk; cả 3 file gốc có trong `data/documents/<doc_id>/` |
| Launcher | `run-local-ai-core.bat` lên đủ (pip qua PYTHONUTF8 OK, pull `glm-ocr` lần đầu ~15 phút); `.env` không bị ghim reranker; log `Contextual retrieval ON` + `Reranker ON` (models.yaml); `/health` **`ok` toàn bộ** lần đầu — backup/cleanup/outbox/memory worker đều `ok` |
| Re-index 3 tài liệu thật (cấu hình ship) | 91 chunk, 451s sinh context, 91 lời gọi, 0 lỗi (3.4–7.0 s/chunk); mỗi tài liệu v2 active có context 91/91, v1 superseded |
| RAG thật | Hỏi Transformer (1706.03762): đúng h=8 / d_model=512, 5 nguồn có số trang, v2, không rò context; chip bám nguồn `weak + language_mismatch` (paper tiếng Anh — cap D3a nói đúng) |
| D1 sanity trên DB thật | recall@5 **0.9756 (Δ 0)**, cùng 2 miss; nhưng MRR −0.0435, doc_hit −0.0610 — xem cảnh báo dưới |
| Lưới backup T14 | `backup-postgres-once.bat` (`--once --force`) chạy thử ra dump mới 1.3MB, drill restore đạt (8 docs / 209 chunk / 118 có context) |
| Bot Discord | bật từ endpoint dashboard, `Ún#0490` connected, bot→API host OK qua `api:host-gateway` |

**Cảnh báo đo lường trên máy vận hành:** DB thật chứa `local_ai_core_baseline.txt`
(tài liệu thật từ 14/08) — tài liệu bẫy `xuong_in_anh_duong.txt` của bộ eval được viết
nhái chính nó, nên trong DB thật nó **chiếm hạng 1** ở mọi câu `xa_*`, đẩy chunk kỳ vọng
xuống hạng 2 (recall không đổi, MRR/doc_hit tụt). Đây là *môi trường đo* đổi, không phải
retrieval thoái lui. Hệ quả: **đo thí nghiệm P4/Track D trên DB lab
`local_ai_core_lab_20260821`** (đúng corpus 5 fixture như lúc ghi baseline — trỏ
`DATABASE_URL` sang nó trong phiên đo), không dùng DB vận hành làm thước; không xóa tài
liệu thật, không chỉnh dataset để "qua" sanity.

### Thư mục production thuần ASCII — di dời 22/08/2026

Production từng nằm ở `C:\Users\dungbt06\Ún promax\local-ai-core`. Chữ **"Ú"** trong đường dẫn gây ra ba lỗi độc lập, tất cả đều
ở *ranh giới* giữa công cụ Unicode và công cụ mã hoá cũ:

| Lỗi | Cơ chế |
| --- | --- |
| Scheduled Task `LocalAICore Backup` thất bại `0x80070002` (không tìm thấy file) **ngay cả khi đường cũ còn** | `schtasks` lưu/giải mã đường dẫn qua code page, dấu "Ú" bị mất |
| Gọi launcher qua đường 8.3 (`NPROMA~1\LOCAL-~1`) làm compose lập **project lạ `local-1`** (container/volume postgres rỗng, đã dọn) | compose lấy tên project từ tên thư mục; tên 8.3 khác tên thật |
| `pip install -r requirements.txt` chết `UnicodeDecodeError` (cp1252) | đã vá bằng ASCII + `PYTHONUTF8=1`, nhưng cùng họ lỗi |

Quyết định: **thư mục production phải thuần ASCII** — `C:\Users\dungbt06\local-ai-core`. Quy trình dời đã thực hiện
(downtime ~12 phút, phần lớn là chờ đóng IDE đang giữ thư mục): backup `--force` →
`stop-local-ai-core.bat` → `docker compose down` (**không** `-v`) → `Move-Item` (rename
cùng ổ, tức thì) → `pip install -e .[rerank]` đăng ký lại editable (torch CUDA giữ nguyên) →
`compose up --force-recreate` (project/volume không đổi, bind Qdrant tự trỏ đường mới) →
launcher. Đếm DB trước/sau bằng nhau từng số. Hai việc đi kèm: ngoại lệ `git config
--global safe.directory` chuyển sang đường mới (thư mục thuộc tài khoản `CodexSandboxOffline`),
và **launcher khởi động qua `explorer.exe`** khi được gọi từ một phiên tự động — tiến trình
con của phiên đó chết theo phiên (đã xảy ra 22/08 trưa).

Bài học: đường dẫn có dấu không sai về nguyên tắc, nhưng mỗi công cụ hệ thống (schtasks,
cmd 8.3, pip/cp1252) là một chỗ có thể mất dấu — production không nên đặt cược vào việc tất
cả đều đúng. Thư mục cũ `…\Ún promax\` vẫn còn các thứ khác của người dùng (`.git`,
`.agents`, `hehe.md`), không thuộc dự án, không tự xóa.

### Lưới backup thứ hai — Scheduled Task (T14)

`backup-postgres-once.bat` ở gốc repo gọi `backup_worker --once --force` (độc lập
launcher). Đăng ký một lần trên máy vận hành (người dùng tự chạy — thay đổi hệ thống):

```bat
schtasks /Create /TN "LocalAICore Backup" /SC DAILY /ST 02:00 /TR "\"C:\Users\dungbt06\local-ai-core\backup-postgres-once.bat\"" /F
```

Task chạy trong phiên đăng nhập (Docker Desktop phải đang chạy). Lưu ý nhỏ ghi lại:
worker xét "backup gần đây" theo **mtime** của file, nên một dump *chép vào* thư mục trông
như mới — `--force` trong bat là để lưới thứ hai không bị cái đó đánh lừa.

## Câu hỏi thử duy nhất

> **Bước này có phải gọi model SINH (generation) hoặc chạy một vòng re-index / thí
> nghiệm nặng không?**

- **KHÔNG → lane NHẸ** — chạy máy nào cũng được, mặc định làm ngay trên máy nhẹ.
- **CÓ → lane NẶNG** — để dành máy mạnh (hoặc GPU cloud với việc train).

Chỉ một câu đó. Không cần bảng phân loại thuộc lòng — cứ hỏi câu này cho từng bước.

## Hai lane, ví dụ cụ thể

| Lane NHẸ (máy nhẹ / daily) | Lane NẶNG (máy mạnh) |
| --- | --- |
| Viết code + logic, unit test | Đo answer/faithfulness bằng model sinh |
| Xây harness, dataset, corpus bẫy | P4-2 contextual retrieval (sinh context mỗi chunk) |
| Eval **retrieval-only** (embedding 0.6b) | P4-3 reranker (warmup + rerank toàn bộ) |
| Guard/self-check **không-LLM** (D3a phần build) | Re-index toàn corpus, thí nghiệm P4 |
| Viết tài liệu, sửa plan, dọn nợ | Agent nhiều bước (D3c), digest nền chạy thật |
| Chạy CI, đọc kết quả gate | Ghi baseline **full** (có model sinh); D2 distillation (cloud/GPU) |

**Mẫu hình thường gặp — một mục chẻ đôi:** phần *xây* (author harness, guard, dataset)
là NHẸ; phần *đo* (chạy qua model sinh để lấy số) là NẶNG. Làm phần nhẹ trên máy nhẹ,
để lại một handoff sạch cho máy mạnh chỉ chạy phần đo. D3a và D5 đều theo mẫu này.

## Máy tự nhận diện — file `.machine-role`

Mỗi máy có một file `.machine-role` ở gốc repo (đã `.gitignore`, **không** đồng bộ qua
git — mỗi máy tự đặt một lần). Nội dung đúng một từ:

```
light
```

hoặc

```
heavy
```

Đặt một lần cho mỗi máy:

```bash
# trên máy nhẹ (daily driver)
echo light > .machine-role
# trên máy mạnh
echo heavy > .machine-role
```

| Máy | hostname | Dấu hiệu | `.machine-role` |
| --- | --- | --- | --- |
| Nhẹ (daily) | `hehehhe` | GTX 1650 Ti, Ryzen 5 4600H, 15GB | `light` |
| Mạnh — **ĐANG VẬN HÀNH từ 22/08/2026** (quyết định 21/08) | `PC-dungbt` | RTX 5060 Ti 16GB VRAM, Ryzen 7 7700 (16 luồng), 31GB RAM, Win 11 Pro. **Thư mục production: `C:\Users\dungbt06\local-ai-core`** (dời 22/08 chiều từ `C:\Users\dungbt06\Ún promax\local-ai-core` — xem "Thư mục production thuần ASCII"). Dữ liệu thật restore từ `local-ai-20260821-131518.dump` + `data/documents/`; DB lab cũ giữ lại dưới tên `local_ai_core_lab_20260821` (corpus eval + các run grounding, không drop); launcher + backup worker + bot Discord chạy ở đây | `heavy` (đặt 21/08/2026) |
| Cloud (Claude Code web) | `vm` (container phù du) | 4 vCPU, 15GB, **không GPU**, proxy chặn tải model (registry.ollama.ai/huggingface.co 403) → không chạy được model sinh lẫn embedding thật | `light` — chỉ lane nhẹ; số đo model thật lấy qua job CI `retrieval-eval` |

## Cấu hình khác nhau theo máy — override qua `.env`

`models.yaml` là file dùng chung (versioned), nên tính năng nào **tốn tài nguyên theo
máy** (model sinh lúc index, cross-encoder lúc hỏi, gói GPU tùy chọn) mà máy nhẹ không
kham nổi thì đè theo máy bằng `.env` (không commit), không sửa `models.yaml`. Launcher
`run-local-ai-core.bat` tự ghim `RAG_RERANKER_ENABLED=false` khi máy thiếu extra
`[rerank]` — quyết định theo máy được ghi rõ trong `.env` thay vì API từ chối khởi động:

| Biến `.env` | Máy nhẹ | Máy mạnh | Ý nghĩa |
| --- | --- | --- | --- |
| `RAG_CONTEXTUAL_RETRIEVAL_ENABLED` | `false` | *(không đặt → theo models.yaml = true)* | P4-2: sinh 1 lời gọi model/chunk lúc index. Máy nhẹ tắt để upload vẫn nhanh; đánh đổi: tài liệu index ở máy nhẹ không có context (vẫn tìm được kiểu trần, re-index ở máy mạnh là có) |
| `RAG_RERANKER_ENABLED` | `false` **hoặc** cài extra (xem dưới) | *(không đặt → theo models.yaml = true)* | P4-3: cross-encoder chấm lại 15 ứng viên **mỗi câu hỏi**. Không thêm lời gọi model sinh nào, nhưng thêm ~35ms/câu trên GPU và **~990ms/câu trên CPU** |

Log khởi động ghi rõ nguồn quyết định (`event=chunk_context_config` và
`event=reranker_config`, `source=env|models.yaml`).

### Máy nhẹ cần làm gì với P4-3

Reranker cần gói tùy chọn, và **bản mặc định trên PyPI là CPU-only** — bật cờ mà
dùng bản đó thì mỗi câu hỏi đắt thêm gần một giây. Hai lựa chọn:

```bash
# (a) Không cài gì — ghim tắt trong .env. Chất lượng về mức P4-2, tốc độ giữ nguyên.
echo RAG_RERANKER_ENABLED=false >> .env
```

```bash
# (b) Cài kèm bản CUDA (chỉ đáng làm nếu máy có GPU NVIDIA)
pip install -e ".[rerank]"
pip install --index-url https://download.pytorch.org/whl/cu128 "torch==2.9.1+cu128"
```

Bật cờ mà **không** cài extra thì API **từ chối khởi động** với
`RerankerUnavailableError` kèm đúng lệnh cần chạy — cố ý fail lúc dựng server
chứ không phải lúc người dùng hỏi. GTX 1650 Ti của máy nhẹ chạy được cross-encoder
này (4GB VRAM là dư), nhưng chưa ai đo trên đó; số trong `p4_progress.md` là của
RTX 5060 Ti.

## Một phiên Claude Code tự route thế nào

Đầu mỗi phiên làm việc, đọc `.machine-role`:

- File ghi **`light`** và việc được giao thuộc lane NẶNG → **dừng và báo**: "Việc này
  cần model sinh / re-index, để dành máy mạnh. Trên máy này tôi làm được phần NHẸ
  (xây harness/guard/test) rồi để handoff." Không tự chạy phần nặng trên máy yếu.
- File ghi **`heavy`** → làm được cả hai lane; ưu tiên vét các phần NẶNG đang chờ.
- Không có file → hỏi người dùng máy này là `light` hay `heavy` rồi tạo file.

Quy tắc này để trong prompt mỗi phiên (xem mẫu ở dưới) là đủ; không cần tự động hóa
thêm.

## Phân lane các mục Track D / P4 hiện tại

| Mục | Phần NHẸ (máy nhẹ làm ngay) | Phần NẶNG (để máy mạnh) |
| --- | --- | --- |
| D1 eval | ✅ đã xong (hạ tầng + baseline retrieval-only) | — (baseline full nếu cần, sau) |
| D3a self-check | Build guard bám-nguồn + unit test + field báo cáo | Đo faithfulness trên 82 câu (cần model sinh) |
| D5 red-team | Corpus tài liệu bẫy + harness + logic chấm | Chạy tấn công thật (agent sinh phản hồi) |
| D4 LLMOps | Hầu hết (chuẩn hóa trace, versioning prompt) | — |
| P4-2/P4-3/P4-4 | — | Toàn bộ (sinh context / rerank / re-index) |
| P4-5 chunk viz | Phần lớn (UI đọc chunk có sẵn) | — |
| D2 distillation | Chuẩn bị/ lọc dataset | Train (GPU cloud free) |
| D3c multi-step | — (gác tới khi có D2 + máy mạnh) | Toàn bộ |
