# 09 — Thí nghiệm model M3: hướng B, bắt đầu bằng nhánh 0

Status: dừng ở Bước 2b theo luật (trôi passage 0,99912 < 0,9999); kế hoạch mới ở "Bổ sung 2" của đăng ký trước; chạy lại sáng 28/10
Type: task
Blocked by: 08 (xong), 11 (sàn dao động 788 câu); cần stack heldout + lab

## Quyết định của chủ dự án (27/10)

Chọn **B** (`m3-target.md`): bắt đầu bằng **nhánh 0** — thêm chỉ dẫn phía truy vấn cho model
embedding hiện tại, không tải gì (vẫn phải re-embed vào collection riêng theo quy tắc registry, xem `m3-preregistration.md`). Chủ dự án duyệt trước việc tải `multilingual-e5-large`
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

### 27/10 — Nhân viên của Ún 1: phần commit trước GPU (Bước 0–1), chưa đo gì

Bản chất: trước khi máy được dùng để đo, những gì sẽ đo phải được ghi cố định vào repo: phiên bản
model mới và script kiểm "chỉ dẫn có thật sự tới model". Như vậy, sau khi thấy số rồi thì không
sửa được nữa. Chưa có lệnh nào gọi Ollama: mọi phép kiểm dưới đây trỏ Ollama vào một cổng chết.

| Việc | Kết quả |
|---|---|
| Record `embedding-v0-qi` (trích bằng chương trình từ `m3-preregistration.md`, đặt ngay sau `embedding-v0`) | `--check`: 0 lỗi, 4 cảnh báo, đúng 4 cảnh báo của main |
| Chuỗi tiền tố đọc từ YAML | có xuống dòng thật giữa "query." và "Query: "; không có `passage_prefix` |
| `--show --no-probe` với `MODEL_VERSION_EMBEDDING=embedding-v0-qi` | requested/loaded = `embedding-v0-qi`, nguồn env, collection `documents_qi` / `memories_qi` |
| `backend/scripts/probe_embedding_prefix.py` | khớp từng byte với khối trong bản đăng ký trước; biên dịch được; **chưa chạy** |
| `tests/test_probe_embedding_prefix.py`: chỉ giả `OllamaClient.embed` | 3 xanh: ghim qi thì chỉ phía query có chỉ dẫn; ghim rỗng (như lần gốc của script) là bản active, không có tiền tố; điều kiện đi tiếp đọc đúng chiều |
| Cùng test đó, khi bỏ `query_prefix` khỏi record | 2 bài riêng của qi đỏ |
| `tests/test_model_registry.py` | xanh, cùng lượt với test trên (106 bài) |

Mục "Chưa kiểm" trong bản đăng ký trước: đọc code thì với `MODEL_STARTUP_PROBES=false`,
`resolve()` nhận `probes=None` (`model_registry.py:1119`), nên không chạm Ollama, Qdrant hay
Postgres; chỉ `Settings()` cần có `DATABASE_URL`. Test trên chạy với một `DATABASE_URL` trỏ vào
cổng chết, và xanh.

Lưu ý khi chạy Bước 1: lần chạy con của script dùng `[sys.executable, __file__, "--one"]`, tức chạy
dạng file. Vậy `import app` đi qua bản cài editable của `.venv`, và bản đó trỏ về checkout chính.
Hệ quả: phải chạy sau khi nhánh này đã gộp, từ `backend\` của checkout chính, đúng như bản đăng ký
trước ghi. Chạy từ worktree thì lần chạy con sẽ đọc registry của main, nơi chưa có `qi`.

### 27/10 — Nhân viên của Ún 2: chạy nhánh 0 (Bước 0–6)

Worktree `C:\Users\dungbt06\local-ai-core-wt\09-model-experiment-run`, nhánh
`wip/09-model-experiment-run`, tạo 19:18 từ main 4710ce4. Commit sau đó trên main (1068849) chỉ
đụng `.scratch/`, nên code trùng nhau. `.env` có 4 dòng chép từ `.env.example`. DATABASE_URL trùng
`.env` thật, đã so bằng máy, không in giá trị. Mọi lệnh dưới đây chạy bằng Git Bash, đặt env theo
từng lệnh. `PY` = `C:/Users/dungbt06/local-ai-core/.venv/Scripts/python.exe`.

Kiểm trước khi chạy (19:19): cổng 8100 và 8200 không ai nghe; GPU 0 MiB / 16 311 MiB, 0 %;
Ollama chưa nạp model nào; chưa có collection `*_qi`; `rag_multidoc_baseline.json` không có `versions`.

#### Bước 0 — xanh

```bash
cd $W && $PY -m training.common.split_manifest --check      # split_manifest OK: 12 artifacts, hashes match.
cd $W && $PY -m training.common.leak_check --construction-only   # leak_check OK.
cd $W/backend && $PY -m app.config.model_registry --check  # 0 error(s), 4 warning(s) — đúng 4 cảnh báo của main
```

Lần đầu `split_manifest --check` đỏ ở worktree với
`backend/tests/fixtures/discord_memory_extractor_benchmark_v1.json: content changed`, còn ở checkout
chính thì xanh. Nguyên nhân: `core.autocrlf=true` đổi LF thành CRLF khi tạo worktree. Blob trong git
vẫn LF (`git ls-files --eol`: `i/lf w/crlf`). Tôi lấy lại đúng byte của blob
(`rm <file> && git -c core.autocrlf=false checkout -- <file>`), chạy lại thì xanh. File này là
benchmark của extractor, 09 không dùng. Các file dữ liệu mà 09 dùng cũng là CRLF trong worktree,
y như ở ticket 11. Ticket 11 cho hạng trùng 08/09 trên cả 788 câu, nên chuyện xuống dòng không làm
lệch kết quả. Fixture `multidoc` của cổng 82 câu là CRLF ở cả main lẫn worktree, nên dedupe theo hash
khi upload vẫn khớp.

#### Bước 1 — probe, qua (19:20, từ `backend\` của checkout chính, chỉ in ra)

```bash
cd C:/Users/dungbt06/local-ai-core/backend && $PY -m scripts.probe_embedding_prefix embedding-v0-qi
# {"query_cosine": 0.9067410888197519, "passage_cosine": 0.9999999999999999}
```

Điều kiện đi tiếp: query_cosine < 0,999 và passage_cosine ≥ 0,999999. Cả hai đều đạt. Checkout chính
vẫn sạch sau khi chạy.

`backend/scripts/passage_drift.py` (Bước 2b) commit cùng với ghi chú này, trước khi chạy.

#### Bước 2 — qua (19:21–19:38)

```bash
cd $W/backend
DB_BASE=$($PY -c "from app.config.settings import Settings; print(str(Settings().database_url).rpartition('/')[0])")   # không in ra
DATABASE_URL="$DB_BASE/local_ai_core_drill_heldout" QDRANT_DOCUMENTS_COLLECTION=documents_drill_heldout MODEL_VERSION_EMBEDDING=embedding-v0-qi $PY -m scripts.rebuild_qdrant --dry-run
DATABASE_URL="$DB_BASE/local_ai_core_drill_heldout" QDRANT_DOCUMENTS_COLLECTION=documents_drill_heldout MODEL_VERSION_EMBEDDING=embedding-v0-qi $PY -m scripts.rebuild_qdrant
DATABASE_URL="$DB_BASE/local_ai_core_drill_heldout" QDRANT_DOCUMENTS_COLLECTION=documents_drill_heldout MODEL_VERSION_EMBEDDING=embedding-v0-qi $PY -m scripts.rebuild_memories
```

| Lệnh | Kết quả |
|---|---|
| `rebuild_qdrant --dry-run` | collection `documents_drill_heldout_qi`, 2 926 tài liệu, 3 896 mảnh |
| `rebuild_qdrant` | embedded 3 896; `points_after` 3 896 = `active_chunks` 3 896; **17 phút 41 giây** (lần đầu đo chi phí nhúng lại chỉ mục này) |
| `rebuild_memories` | `memories_rows` 0, embedded 0, `memories_qi` không được tạo |

#### Bước 2b — DỪNG theo luật bậc (19:39)

```bash
cd $W/backend && $PY -X utf8 -m scripts.passage_drift
```

| | Giá trị |
|---|---|
| Điểm của qi / ghép được với v0 theo id / không ghép được | 3 896 / 3 896 / 0 (so trên giao hai tập id) |
| cosine min · p1 · trung vị | **0,99911526** · 0,99951999 · 0,99970730 |
| Số điểm dưới 0,999999 | 3 896 (tất cả) |

Luật: min < 0,9999 → **dừng**, mở ticket dựng collection v0 nhúng mới làm control. Chưa chạy lượt đo
nào (Bước 3–5). Không stack nào được bật, GPU đã trả.

Nguyên nhân, kiểm chỉ đọc:
- Không phải ở chỗ tiền tố: probe ở Bước 1 cho thấy hôm nay passage của v0 và của qi trùng nhau (0,9999999999999999).
- Không phải weights: blob `qwen3-embedding:0.6b` có digest `ac6da0dfba84`, sửa lần cuối 11/07/2026, tức trước 08/09.
- Không phải văn bản đầu vào hay đường gọi: `combined_retrieval_text` không đổi từ f88380f. Các thay đổi ở `ollama_client.py` / `model_router.py` từ đó chỉ chạm chat/OCR (`seed`, `num_predict`, lỗi dừng sớm), không chạm phần nhúng.
- Còn lại là phần ngoài repo: Ollama (`docs/RESULTS.md:8` ghi 0.33.2 cho đầu tháng 9; bây giờ là 0.40.8) hoặc phần số học của GPU/driver. Chưa tách được hai khả năng này.

Hệ quả: so qi với v0 trên chỉ mục 08/09 thì Δ gồm hai thứ cùng lúc, chỉ dẫn và việc vector tài liệu bị
nhúng lại bằng runtime khác, nên không quy được cho chỉ dẫn. Theo luật thì phải dừng ở đây.
`documents_drill_heldout_qi` (3 896 điểm) để nguyên trong Qdrant, không xoá.

#### Sau khi dừng: cờ `--collection-base` cho eval_stack (27/10 tối, không dùng GPU)

Theo Bổ sung 2 (cách A): `eval_stack --collection-base NAME` đặt gốc tên collection tài liệu cho riêng
một stack. Registry nối hậu tố của phiên bản embedding đang ghim vào gốc đó, nên v0 tìm trong `NAME`
còn qi tìm trong `NAME_qi`. Hai bên được nhúng mới cạnh nhau, trên cùng runtime.

| Điểm | Cách làm |
|---|---|
| Mặc định | không có cờ (hoặc NAME trùng collection của profile) thì hành vi giữ nguyên |
| Vùng tên | NAME phải bắt đầu bằng `<collection của profile>_` (`documents_drill_heldout_r2`, `documents_lab_r2`). Tên khác bị từ chối trước khi bật tiến trình nào, nên stack đo không bao giờ tìm hay ghi vào collection của production |
| Tên trùng hậu tố một phiên bản (`…_qi`, `…_e5l`) | cờ cho qua vì vẫn trong vùng tên; registry từ chối lúc API boot (`docs/model_registry.md:75`), `start` in ra đuôi log. Có test ghim hành vi này |
| Dòng "san sang" | in gốc collection đang dùng; sửa luôn lỗi in "contextual=OFF" khi có `--contextual` (giờ in theo env thật của stack) |

Test (`backend/tests/test_eval_stack_model_version.py`, 19 xanh): mặc định của cả ba profile; tên ngoài
vùng bị từ chối; với gốc `_r2`, v0 và qi suy ra `NAME` / `NAME_qi` qua `Settings().qdrant_collections()`
cho cả heldout lẫn lab; gốc kết thúc bằng `_qi` bị registry từ chối. Kiểm đột biến: bỏ cờ khỏi
`stack_env` thì 2 bài đỏ; bỏ rào vùng tên thì 6 bài đỏ. CLI với `--collection-base documents` bị từ chối
ở cả heldout lẫn lab, không bật tiến trình nào.

**Đề xuất cho sau này (ngoài phạm vi 09): manifest của mỗi lần đo ghi phiên bản Ollama.** Lý do:
Bước 2b cho thấy cùng weights, cùng văn bản, cùng code nhưng nhúng ở hai thời điểm thì cosine thấp
nhất chỉ còn 0,99912, và không file nào ghi bản Ollama của lần 08/09. Có thể làm theo một trong ba
cách sau.

| Cách | Ưu | Nhược |
|---|---|---|
| `eval_heldout` / `evaluate_rag` đọc `GET /api/version` của Ollama và ghi vào JSON kết quả | rẻ, mọi file kết quả từ nay đều tự mang bản Ollama | file cũ vẫn thiếu |
| `/models` của API trả thêm bản Ollama; script đo chép từ `/models` như đang chép `versions` | một nguồn sự thật, xem được cả khi chạy production | đụng API, cần test cho trường mới |
| Registry ghi bản Ollama đã dùng khi nhúng mỗi collection (vd. trong `eval.reports` hoặc khi rebuild) | bắt được đúng chuyện vector cũ do runtime cũ sinh ra | phải đổi lược đồ registry, nặng nhất |
