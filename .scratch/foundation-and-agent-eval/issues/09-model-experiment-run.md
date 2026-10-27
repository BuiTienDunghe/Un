# 09 — Thí nghiệm model M3: hướng B, bắt đầu bằng nhánh 0

Status: nhánh 0 chạy xong tối 27/10 theo Bổ sung 2: **âm** (điều kiện 1–5 không qua, 7–8 qua); chờ fable duyệt. B đầy đủ chưa bắt đầu
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
- 28/10 00:35 (opus 5.5): nhánh 0 **âm** theo đăng ký trước (Nhân viên 2 báo, chờ fable duyệt). Ba việc điều
  phối kiểm/ghi:
  1. **Nguồn tải GPU lạ trong hai lượt hybrid** (365 lệnh chat tới qwen3.5:9b + nạp glm-ocr): là Agent Eval
     của Nhân viên 3 (1a-v2 lúc 22:31–22:39; bước 5 của ticket 16 lúc 22:57–23:0x, `--probe` nạp cả OCR) — điều
     phối cho chạy song song lúc 22:28 sau khi đo GPU rỗi, nhưng **không báo Nhân viên 2**. Lỗi điều phối.
     Thứ hạng không đổi (đường truy xuất tất định); điều kiện p50 vẫn qua. Ghi vào báo cáo kết quả.
  2. **Production `memories` nguyên vẹn**: `rebuild_memories` của nhánh v0 không đặt
     `QDRANT_MEMORIES_COLLECTION` nên trỏ vào collection production; kiểm 00:30: Qdrant `memories` 3 điểm =
     bảng `memories` của DB thật 3 dòng. Cho B đầy đủ: bắt buộc đặt biến này, hoặc bỏ `rebuild_memories` khỏi
     các bước đo (DB heldout/lab có 0 dòng memories).
  3. Cho ticket 15: nhúng lại v0 trên runtime mới chỉ làm 1 câu lên hạng 1, 0 câu rời top-5 → vector cũ của
     production không lệch đo được trên tập này. p50 4,6 s của ticket 11 là do chia GPU; khi rỗi 1,9 s.

### 27/10 tối — Nhân viên của Ún 2: chạy lại nhánh 0 theo Bổ sung 2

GPU trống lúc 20:57, khi ticket 10 xong. 20:59 tôi reset worktree về main d1e2171 (`git reset --hard main`).
Từ 5a3291a tới d1e2171 chỉ có `.scratch/` đổi, không có code, còn `m3-preregistration.md` thì giữ
nguyên. `.env` 4 dòng vẫn còn. Fixture extractor là `i/lf w/lf`. Mọi lệnh chạy bằng Git Bash, đặt env
theo từng lệnh. `W` = worktree, `PY` = `C:/Users/dungbt06/local-ai-core/.venv/Scripts/python.exe`.
`DB_BASE` suy từ `.env` như ở trên, không in ra.

Kiểm trước khi chạy (21:00):

| Kiểm | Kết quả |
|---|---|
| Cổng 8100/8200/8300 | không ai nghe |
| GPU | 0 MiB / 16 311 MiB, 0 % |
| Model Ollama đang nạp | không có |
| Collection `*_r2*` | chưa có |
| Phiên bản Ollama (ticket 15) | `0.40.8` |
| `rag_multidoc_baseline.json` | không có `versions` |

#### Bước 2 (Bổ sung 2 mục 2) — qua (21:02–21:38)

```bash
cd $W/backend
DATABASE_URL="$DB_BASE/local_ai_core_drill_heldout" QDRANT_DOCUMENTS_COLLECTION=documents_drill_heldout_r2 $PY -m scripts.rebuild_qdrant --dry-run
DATABASE_URL="$DB_BASE/local_ai_core_drill_heldout" QDRANT_DOCUMENTS_COLLECTION=documents_drill_heldout_r2 MODEL_VERSION_EMBEDDING=embedding-v0-qi $PY -m scripts.rebuild_qdrant --dry-run
DATABASE_URL="$DB_BASE/local_ai_core_drill_heldout" QDRANT_DOCUMENTS_COLLECTION=documents_drill_heldout_r2 $PY -m scripts.rebuild_qdrant
DATABASE_URL="$DB_BASE/local_ai_core_drill_heldout" QDRANT_DOCUMENTS_COLLECTION=documents_drill_heldout_r2 $PY -m scripts.rebuild_memories
DATABASE_URL="$DB_BASE/local_ai_core_drill_heldout" QDRANT_DOCUMENTS_COLLECTION=documents_drill_heldout_r2 MODEL_VERSION_EMBEDDING=embedding-v0-qi $PY -m scripts.rebuild_qdrant
DATABASE_URL="$DB_BASE/local_ai_core_drill_heldout" QDRANT_DOCUMENTS_COLLECTION=documents_drill_heldout_r2 MODEL_VERSION_EMBEDDING=embedding-v0-qi $PY -m scripts.rebuild_memories
```

| Lệnh | Kết quả |
|---|---|
| hai lần `--dry-run` | đích `documents_drill_heldout_r2` (v0) và `documents_drill_heldout_r2_qi` (qi); 2 926 tài liệu, 3 896 mảnh mỗi bên, collection rỗng |
| `rebuild_qdrant` v0 | embedded 3 896; `points_after` 3 896 = `active_chunks` 3 896; 21:02:37–21:20:26 (**17 phút 49 giây**) |
| `rebuild_qdrant` qi | embedded 3 896; `points_after` 3 896 = `active_chunks` 3 896; 21:20:31–21:38:10 (**17 phút 39 giây**) |
| `rebuild_memories` hai lần | `memories_rows` 0, embedded 0. Lần v0 chỉ đếm `memories` của production: vẫn 3 điểm, không ghi gì, vì script chỉ upsert từng dòng của bảng. `memories_qi` không được tạo |

Lần v0 trỏ vào `memories` của production: đăng ký trước không đặt `QDRANT_MEMORIES_COLLECTION` cho
Bước 2. Lần này không hại gì, vì bảng heldout có 0 dòng và script không xoá điểm nào. Nhưng nếu một
chỉ mục đo có dòng memories thì lệnh này sẽ ghi vào collection của production. Lần sau nên đặt cả
`QDRANT_MEMORIES_COLLECTION`, hoặc bỏ `rebuild_memories` khỏi các bước đo.

#### Bước 2b (Bổ sung 2 mục 3) — sạch, bậc một (21:38)

```bash
cd $W/backend && $PY -X utf8 -m scripts.passage_drift documents_drill_heldout_r2 documents_drill_heldout_r2_qi
# qi points 3896 · paired with v0 3896 · unpaired 0
# cosine min 1.00000000 · p1 1.00000000 · median 1.00000000
# below 0.999999: 0
```

Đã so trên giao của hai tập id: 3 896 / 3 896, không điểm nào lẻ. Cosine thấp nhất 1,00000000, tức
bậc một (≥ 0,999999), không nhiễu. Đúng như kỳ vọng của Bổ sung 2 mục 3: nhúng cùng runtime, cùng buổi
thì passage của v0 và qi trùng nhau. Từ đây Δ giữa hai nhánh chỉ còn là chỉ dẫn ở phía truy vấn.

Kiểm Bước 0 lặp lại khi stack đang tắt (22:03): `split_manifest --check` → `OK: 12 artifacts, hashes match`;
`leak_check --construction-only` → `OK`. Registry được kiểm qua hai lần `--dry-run` ở trên: embedding
`verified`, probe dừng của OCR qua.

#### Bước 3, lượt control v0 chỉ-dense (21:38–22:03)

```bash
cd $W && $PY -m training.common.eval_stack --profile heldout --start --mode dense --no-reranker --contextual --collection-base documents_drill_heldout_r2
# [heldout] san sang tren cong 8200 · db=local_ai_core_drill_heldout · collection(goc)=documents_drill_heldout_r2 · contextual=ON · reranker=OFF · mode=dense
curl -s http://127.0.0.1:8200/models   # registry.embedding loaded embedding-v0, fallback False, collections.documents documents_drill_heldout_r2; rag.contextual_retrieval True, retrieval_mode dense
cd $W && $PY -m training.common.eval_heldout --dataset data/evaluation/heldout_retrieval_v1/zalo-legal_subset.jsonl --base-url http://127.0.0.1:8200 --label v0r2-dense-ctxON-rerankerOFF
cd $W && $PY -m training.common.eval_stack --profile heldout --stop
```

Log API của stack (`$W/data/logs/eval_heldout_api.log`) ghi `Qdrant collections documents_drill_heldout_r2 / memories`.
Trước lượt đo, GPU dùng 1 788 MiB, 0 %: đó là model nhúng còn nạp sau Bước 2.

| Lượt | Acc@1 | Acc@3 | Recall@5 | MRR | p50 / p95 |
|---|---|---|---|---|---|
| `v0r2-dense-ctxON-rerankerOFF` | 0,8223 | 0,9518 | 0,9619 | 0,8846 | 1 780 / 2 056 ms |

File: `data/evaluation/results/kept/heldout-v0r2-dense-ctxON-rerankerOFF-20261027-220250.json`.

**Thước chính của nhánh (i), chọn theo luật trước lượt qi** (`analyze.py headroom`):

| Thước | Khoảng trống | So với 0,064 |
|---|---|---|
| recall@5 | 1 − 0,9619 = 0,0381 | thiếu |
| Acc@1 | 0,9619 − 0,8223 = 0,1396 | đủ |

Thước chính là **Acc@1**. Ở nhánh (i), điều kiện 1 là ΔAcc@1 ≥ max(0,032 ; 2·0/788) = 0,032. Điều kiện 2
là Δrecall@5 ≥ −0/788 = 0, tức không tụt câu nào. Điều kiện 3: số câu chuyển từ tìm thấy sang mất ở top-5
phải ≤ 0. Điều kiện 8 so p50 của lượt qi với 2 × p50 của lượt control này, tức 2 × 1 780 = 3 560 ms. Con
số 9 170 ms của ticket 11 chỉ để tham khảo, vì đó là đường hybrid chạy trên vector 08/09.

Commit này có trước khi bật stack qi.

#### Bước 3, lượt treatment qi chỉ-dense (22:03–22:28) — nhánh (i) **không qua**

```bash
cd $W && $PY -m training.common.eval_stack --profile heldout --start --mode dense --no-reranker --contextual --collection-base documents_drill_heldout_r2 --model-version embedding=embedding-v0-qi
# phien ban ghim: MODEL_VERSION_EMBEDDING=embedding-v0-qi
curl -s http://127.0.0.1:8200/models   # embedding loaded embedding-v0-qi, fallback False, active; collections documents_drill_heldout_r2_qi / memories_qi; ctx True, mode dense
cd $W && $PY -m training.common.eval_heldout --dataset data/evaluation/heldout_retrieval_v1/zalo-legal_subset.jsonl --base-url http://127.0.0.1:8200 --label v0qir2-dense-ctxON-rerankerOFF
cd $W && $PY -m training.common.eval_stack --profile heldout --stop
python -X utf8 analyze.py compare <control> <treatment>   # script so từng câu trong scratchpad; McNemar chính xác, bootstrap theo cặp 10 000 lần, seed 20261027
```

Log API của stack ghi `Qdrant collections documents_drill_heldout_r2_qi / memories_qi`, tức lượt qi tìm
đúng trong collection mới.

| Thước | v0 | qi | Δ | Δ theo câu |
|---|---|---|---|---|
| Acc@1 (thước chính) | 0,8223 | 0,8312 | +0,0089 | +7 |
| Acc@3 | 0,9518 | 0,9480 | −0,0038 | −3 |
| recall@5 | 0,9619 | 0,9581 | −0,0038 | −3 |
| MRR | 0,8846 | 0,8893 | +0,0048 | +3,8 |
| p50 | 1 780 ms | 1 796 ms | | |

| Hạng | tìm thấy → mất | mất → tìm thấy | McNemar p |
|---|---|---|---|
| top-1 | 18 | 25 | 0,36 |
| top-3 | 6 | 3 | 0,51 |
| top-5 | 8 | 5 | 0,58 |

67 câu đổi hạng. ΔMRR +0,0048, CI 95% bootstrap theo cặp [−0,0043 ; +0,0139]. Tám câu mất khỏi top-5:
0cf099d9, 0ea914b9, 12aa2415, 19090d69, 1b590c52, 26e9e575, 9531e8d7, d6e0c0d1.

| # | Điều kiện | Ngưỡng | Đo | Kết quả |
|---|---|---|---|---|
| 1 | ΔAcc@1 | ≥ 0,032 | +0,0089 | **không qua** |
| 2 | Δrecall@5 | ≥ 0 (không tụt câu nào) | −3 câu | **không qua** |
| 3 | top-5 tìm thấy → mất | ≤ 0 | 8 | **không qua** |
| 8 | p50 | ≤ 2 × 1 780 = 3 560 ms | 1 796 ms | qua |

Theo bảng quyết định của đăng ký trước, nhánh 0 đã **âm**: điều kiện 1 không qua là âm, điều kiện 3 không
qua là âm bất kể các dòng khác. Đây là phán quyết về ứng viên, không phải lệnh ngừng đo. Đăng ký trước chỉ
viết "dừng" ở bậc ba của Bước 2b và ở điều kiện 9 ("không đo nhánh nào"). Nó cũng ghi mỗi giả thuyết đều
có kết quả được ghi, và Bổ sung 2 mục 5 giữ nguyên tập đo. Nên Bước 4–5 vẫn chạy như đã đăng ký, để đo
H0-ship và H0-gate, chứ không phải để tìm một kết quả dương. Câu hỏi của (ii) giờ cụ thể hơn: tầng từ
khoá và reranker có che được 8 câu mà tầng vector làm mất hay không.

Tải GPU: League of Legends chạy trên GPU khoảng 22:07–22:19, dùng khoảng 2 650 MiB, 19–29 %. Lúc đo
control nó không có mặt. p50 của hai lượt chỉ lệch 16 ms, nên nó không làm đổi độ trễ ở đây. Thứ hạng
không phụ thuộc tải, vì ticket 11 cho hạng trùng nhau giữa các lần lặp. Tôi lấy mẫu `nvidia-smi` mỗi phút
suốt các bước còn lại.

File: `data/evaluation/results/kept/heldout-v0qir2-dense-ctxON-rerankerOFF-20261027-222810.json`.

#### Bước 4 — nhánh (ii) đường ship (22:30–23:22)

```bash
cd $W && $PY -m training.common.eval_stack --profile heldout --start --reranker --contextual --collection-base documents_drill_heldout_r2
curl -s http://127.0.0.1:8200/models   # embedding-v0, reranker-v0 active, không fallback; documents_drill_heldout_r2; ctx True, mode hybrid
cd $W && $PY -m training.common.eval_heldout --dataset data/evaluation/heldout_retrieval_v1/zalo-legal_subset.jsonl --base-url http://127.0.0.1:8200 --label v0r2-hybrid-ctxON-rerankerON
cd $W && $PY -m training.common.eval_stack --profile heldout --stop
cd $W && $PY -m training.common.eval_stack --profile heldout --start --reranker --contextual --collection-base documents_drill_heldout_r2 --model-version embedding=embedding-v0-qi
curl -s http://127.0.0.1:8200/models   # embedding-v0-qi, reranker-v0 active, không fallback; documents_drill_heldout_r2_qi; ctx True, mode hybrid
cd $W && $PY -m training.common.eval_heldout --dataset data/evaluation/heldout_retrieval_v1/zalo-legal_subset.jsonl --base-url http://127.0.0.1:8200 --label v0qir2-hybrid-ctxON-rerankerON
cd $W && $PY -m training.common.eval_stack --profile heldout --stop
```

Mỗi lượt mất khoảng 25 phút, không phải 62 như ước tính. Log API ghi đúng collection cho từng lượt.

| Thước | v0 (control mới) | qi | Δ theo câu |
|---|---|---|---|
| Acc@1 | 0,7931 | 0,7931 | 0 (1 mất, 1 được) |
| Acc@3 | 0,9683 | 0,9657 | −2 |
| recall@5 | 0,9822 | 0,9797 | −2 (3 mất: 0cf099d9, 4173e375, 45bc9045; 1 được) |
| MRR | 0,8776 | 0,8775 | ΔMRR −0,0001, CI 95% [−0,0026 ; +0,0023] |
| p50 / p95 | 1 886 / 2 178 ms | 1 806 / 2 061 ms | |

Câu 0cf099d9 cũng mất ở nhánh (i).

Tải ngoài lúc đo: Ollama nhận các lệnh `/api/chat` tới `qwen3.5:9b` (220 lệnh trong khoảng 22:31–22:44,
145 lệnh trong khoảng 22:57–23:03), kèm nạp lại `glm-ocr`. GPU lúc đó dùng khoảng 9,8 GB, 90 %. Các lệnh
này không đến từ stack đo: log API chỉ có 788 lượt `/rag/search` cùng `/health` và `/models`, worker
không nhận việc nào, độ trễ từng câu đều nhau từ câu đầu tới câu cuối (trung vị theo từng khúc 100 câu
1 788–1 992 ms). Lúc đo hai lượt chỉ-dense thì không có lệnh chat nào. Không tính lệnh chat lúc stack
khởi động: đó là probe dừng của OCR.

**Nguồn tải là do điều phối** (opus 5.5 xác nhận 28/10): đó là Agent Eval của Nhân viên 3, gồm 1a-v2 lúc
22:31–22:39 và bước 5 của ticket 16 lúc 22:57–23:0x, trong đó `--probe` nạp cả OCR. Điều phối đo thấy GPU
rỗi lúc 22:28 nên cho chạy song song, nhưng không báo phiên đo này. Thứ hạng không bị ảnh hưởng vì đường
tìm không gọi model sinh, và các lần lặp cho hạng trùng nhau. Điều kiện p50 vẫn qua: 1 806 ≤ 2 × 1 886 ms.
Sau Bước 4 chỉ mục heldout vẫn nguyên: `rebuild_qdrant --dry-run` trả 3 896 mảnh, 3 896 điểm.

So riêng việc nhúng lại, cùng model (`heldout-ctxON-rerankerON-20261027-173610.json` của ticket 11 với
lượt control mới): 1 câu lên hạng 1, không câu nào rời top-5. Tức chỉ mục production, vốn nhúng bằng
runtime cũ, không lệch đo được trên tập này (ticket 15). p50 4 622 → 1 886 ms, khớp với giả thuyết
rằng số 4,6 s của ticket 11 là do Ollama đang bị dùng chung.

#### Bước 5 — nhánh (iii) cổng 82 câu trên lab (23:23–23:27)

```bash
cd $W/backend
DATABASE_URL="$DB_BASE/local_ai_core_lab_20260821" QDRANT_DOCUMENTS_COLLECTION=documents_lab_r2 $PY -m scripts.rebuild_qdrant --dry-run
DATABASE_URL="$DB_BASE/local_ai_core_lab_20260821" QDRANT_DOCUMENTS_COLLECTION=documents_lab_r2 MODEL_VERSION_EMBEDDING=embedding-v0-qi $PY -m scripts.rebuild_qdrant --dry-run
DATABASE_URL="$DB_BASE/local_ai_core_lab_20260821" QDRANT_DOCUMENTS_COLLECTION=documents_lab_r2 $PY -m scripts.rebuild_memories --dry-run
DATABASE_URL="$DB_BASE/local_ai_core_lab_20260821" QDRANT_DOCUMENTS_COLLECTION=documents_lab_r2 $PY -m scripts.rebuild_qdrant
DATABASE_URL="$DB_BASE/local_ai_core_lab_20260821" QDRANT_DOCUMENTS_COLLECTION=documents_lab_r2 $PY -m scripts.rebuild_memories
DATABASE_URL="$DB_BASE/local_ai_core_lab_20260821" QDRANT_DOCUMENTS_COLLECTION=documents_lab_r2 MODEL_VERSION_EMBEDDING=embedding-v0-qi $PY -m scripts.rebuild_qdrant
DATABASE_URL="$DB_BASE/local_ai_core_lab_20260821" QDRANT_DOCUMENTS_COLLECTION=documents_lab_r2 MODEL_VERSION_EMBEDDING=embedding-v0-qi $PY -m scripts.rebuild_memories
$PY -X utf8 -m scripts.passage_drift documents_lab_r2 documents_lab_r2_qi
cd $W && $PY -m training.common.eval_stack --profile lab --start --collection-base documents_lab_r2
cd $W/backend && $PY -m scripts.evaluate_rag --multidoc-dataset ../data/evaluation/rag_multidoc_eval.jsonl --retrieval-only --baseline ../data/evaluation/rag_multidoc_baseline.json --base-url http://127.0.0.1:8100
cd $W && $PY -m training.common.eval_stack --profile lab --stop
cd $W && $PY -m training.common.eval_stack --profile lab --start --collection-base documents_lab_r2 --model-version embedding=embedding-v0-qi
cd $W/backend && $PY -m scripts.evaluate_rag --multidoc-dataset ../data/evaluation/rag_multidoc_eval.jsonl --retrieval-only --baseline ../data/evaluation/rag_multidoc_baseline.json --base-url http://127.0.0.1:8100
cd $W && $PY -m training.common.eval_stack --profile lab --stop
```

| Kiểm | Kết quả |
|---|---|
| nhúng lab | v0 → `documents_lab_r2`, qi → `documents_lab_r2_qi`; mỗi bên 27 = `active_chunks` 27; memories 0 dòng, không ghi gì |
| trôi passage lab | 27 / 27 cặp, cosine thấp nhất 1,00000000 |
| `/models` hai lượt | embedding-v0 rồi embedding-v0-qi, reranker-v0, không fallback; log API ghi `documents_lab_r2` rồi `documents_lab_r2_qi` |
| v0 mới | recall 0,9878 · MRR 0,9360 · doc_hit 0,9268 · p50 330 ms; "gate passed"; trượt `br_backup_thu_cong` như baseline |
| qi mới | giống v0 tới từng chữ số; p50 349 ms; "gate passed" |
| **so từng câu qi với v0 (phép quyết định)** | 82 câu, 0 câu từ tìm thấy sang mất, 0 câu đổi hạng |
| so với baseline cũ (tham khảo) | cả hai lượt: 0 câu mất, 0 câu đổi hạng |

Baseline không có `versions` nên script in WARNING "NOT version-guarded", đúng như đăng ký trước dự đoán.

#### Bước 6 — điều kiện dừng và phán quyết

F1 = F5 = 0 (ticket 11), N = 788. p50-C lấy từ control của cùng nhánh.

| # | Nhánh | Điều kiện | Ngưỡng | Đo | Kết quả |
|---|---|---|---|---|---|
| 1 | (i) | ΔAcc@1 (thước chính) | ≥ 0,032 | +0,0089 | **không qua** |
| 2 | (i) | Δrecall@5 | ≥ 0 | −0,0038 (−3 câu) | **không qua** |
| 3 | (i) | top-5 tìm thấy → mất | ≤ 0 | 8 | **không qua** |
| 4 | (ii) | ΔAcc@1 · ΔRecall@5 | ≥ 0 · ≥ 0 | 0 · −0,0025 (−2 câu) | **không qua** (vế recall) |
| 5 | (ii) | tìm thấy → mất | ≤ 0 | 3 | **không qua** |
| 6 | (ii) | "cải thiện" | ΔAcc@1 ≥ 0,032 | 0 | không được tuyên bố |
| 7 | (iii) | cổng 82 câu, so từng câu với v0 mới | 0 câu mất | 0 câu mất, 0 câu đổi hạng | qua |
| 8 | (i) · (ii) · (iii) | p50 ≤ 2 × p50-C | 3 560 · 3 772 · 660 ms | 1 796 · 1 806 · 349 ms | qua |

**Phán quyết: âm.** Điều kiện 1 trượt nên âm; điều kiện 3 và 5 trượt nên âm bất kể các dòng khác.
H0-dense bị bác. H0-ship cũng không giữ nguyên: đăng ký trước kỳ vọng "không phân biệt được", nhưng
đường ship mất 3 câu khỏi top-5. H0-gate đứng. Bản ghi `embedding-v0-qi` giữ làm candidate,
`eval.reports` vẫn null, thêm `notes` ghi ngày và kết quả (`model_versions.yaml`; `--check` 0 lỗi, 4 cảnh
báo như main; `test_model_registry` cùng hai bộ test của 09 xanh 127/127). Dòng kết quả nằm trong
`docs/RESULTS.md`, mục Held-out.

File chép vào `data/evaluation/results/kept/`: bốn file heldout `v0r2-*` / `v0qir2-*`, hai file
`rag-multidoc-20261027-232528.json` (v0) và `rag-multidoc-20261027-232629.json` (qi).

Còn để nguyên trong Qdrant, không xoá: `documents_drill_heldout_r2`, `documents_drill_heldout_r2_qi`,
`documents_lab_r2`, `documents_lab_r2_qi`, và `documents_drill_heldout_qi` từ lần chạy đầu. Chủ dự án
quyết định sau.

Ghi chú quy trình: `rebuild_memories` ở Bước 2/5 không đặt `QDRANT_MEMORIES_COLLECTION`, nên lượt v0
trỏ vào `memories` của production. Lần này không hại gì vì bảng có 0 dòng, nhưng lần chạy B nên đặt
biến đó, hoặc bỏ lệnh này khỏi các bước đo.
