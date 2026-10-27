# M3 — Đăng ký trước cho ticket 09 (hướng B, nhánh 0 trước)

Status: đăng ký trước, viết 27/10/2026 **trước khi đo bất cứ gì**. Các ô `⟨…⟩` điền từ kết quả
ticket 11 *trước* lần đo đầu tiên của 09; sau khi điền, không sửa ngưỡng nữa.
Viết bởi: fable 5.1 của Ún. Mọi lệnh ở đây đã đối chiếu với cờ thật trong code; chưa lệnh nào được chạy.

## Bản chất

Nhánh 0 không đổi model, chỉ đổi *cách hỏi* model: trước mỗi câu hỏi, gắn thêm một câu dặn "hãy tìm
văn bản khớp với câu hỏi của người dùng" — đúng kiểu câu dặn model này được dạy để nhận. Tài liệu
đã lập chỉ mục không đổi một byte. Ở bài thi công khai, câu dặn đó đã cho thêm gần 5 điểm; câu hỏi
của 09 là trong sản phẩm thật nó có cho thêm gì không — và vì trong sản phẩm, vị trí số một gần như
do tầng tìm theo từ khoá quyết định, câu trả lời rất có thể là "không thấy khác" ở đường đang ship,
dù thấy khác ở tầng vector. Cả hai kết quả đều được ghi.

## Sự thật đã kiểm trước khi viết (27/10)

| Điều | Bằng chứng |
|---|---|
| Chuỗi chỉ dẫn mà lần đo mteb 05/09 thật sự gửi | `run_mteb.py:125` template `Instruct: {instruction}\nQuery: `; `prompt_dict={}` nên `{instruction}` lấy từ `mteb.abstasks.abstask.get_abstask_prompt("VieQuADRetrieval")` = **`Retrieve text based on user query.`** (mteb 2.20.5, kiểm trong `.venv-eval`). Số +0,0467 / +0,0080 đo với đúng chuỗi này |
| Tiền tố chỉ phía truy vấn không đổi vector passage | `model_router.py:191` gắn `config[f"{side}_prefix"]`; đường truy vấn gọi `router.embed(query, side="query")` (`postgres_retrieval_service.py:41`) không qua cache; cache passage đọc `config_fingerprint` (`postgres_document_service.py:559-581`) |
| Registry **bắt buộc** phiên bản mới + `collection_suffix` mới cho mọi đổi tiền tố, kể cả chỉ phía truy vấn | `docs/model_registry.md:48`; hai phiên bản không được chung collection (`model_registry.py:474-478`). `m3-target.md` viết "không cần rebuild" — đúng về vector, **sai về quy tắc**; theo quy tắc |
| Sửa `embedding-v0.config` tại chỗ sẽ làm đỏ test | `test_model_registry.py:178` so `flat_models()` với một literal của models.yaml cũ |
| Bản ghi ứng viên dưới đây qua `--check` và `--show` | `--check --registry <bản sao trong scratchpad>` với **đúng chuỗi tiền tố dưới đây**: 0 lỗi, 4 cảnh báo (cùng 4 cảnh báo của main). `--show --no-probe` với `MODEL_VERSION_EMBEDDING=embedding-v0-qi`: `requested`/`loaded` = `embedding-v0-qi`, `source: env`, collection `documents_qi` / `memories_qi` |
| Cổng 82 câu không từ chối một phiên bản embedding khác | `evaluate_rag.py:188-199`: baseline hiện tại không có `versions` → in WARNING "NOT version-guarded", chấm theo số và theo từng câu. **Nếu** ai ghi lại baseline có stamp trước khi 09 chạy, nhánh (iii) sẽ bị từ chối ("Baseline embedding version embedding-v0 != current embedding-v0-qi") — khi đó chạy không `--baseline` và so từng câu bằng tay |
| Cờ `RAG_CONTEXTUAL_RETRIEVAL_ENABLED` chỉ tác động lúc lập chỉ mục | `main.py:174`, `workers/tasks.py:86` (ChunkContextService); lúc truy vấn không đọc. Trạng thái ctx của chỉ mục heldout là thứ quyết định, không phải cờ |
| Chế độ chỉ-dense chưa từng chạy | không có file `heldout-*dense*` trong `data/evaluation/heldout_retrieval_v1/results/` |
| Cờ thật của `eval_stack.py` | `--profile {lab,heldout,chunkexp}`, `--start/--stop/--status`, `--reranker/--no-reranker`, `--contextual/--no-contextual`, `--mode {dense,bm25,hybrid}`, `--model-version ROLE=ID` (lặp được); profile heldout mặc định ctx OFF, reranker OFF |

## Giả thuyết

**Nhánh 0** — phiên bản `embedding-v0-qi`: cùng weights `qwen3-embedding:0.6b`, thêm
`query_prefix = "Instruct: Retrieve text based on user query.\nQuery: "` (đúng chuỗi 05/09).

| Mã | Giả thuyết | Đo ở |
|---|---|---|
| H0-dense | Ở chế độ chỉ-dense, không reranker, chỉ dẫn nâng recall@5 trên 788 câu vượt ngưỡng | nhánh (i) |
| H0-ship | Ở đường ship (hybrid + reranker, ctx ON), chỉ dẫn không làm mất câu nào; **kỳ vọng ghi trước: không phân biệt được**, vì dense chỉ góp +0,004 Acc@1 trên luật (`m3-target.md`) | nhánh (ii) |
| H0-gate | Cổng 82 câu không mất câu nào | nhánh (iii) |

**B** — phiên bản `embedding-e5l-v1` (đã có record, thiếu Modelfile + `gguf_sha256`): `multilingual-e5-large`
Q8 qua `ollama create`, tiền tố `query: ` / `passage: ` hai phía.

| Mã | Giả thuyết | Đo ở |
|---|---|---|
| H-pack | Model đóng gói đúng: mteb VieQuAD nDCG@10 trong **±0,02 của 0,6112**. Lệch xa → thí nghiệm **vô hiệu** (không phải âm), dừng | bước đóng gói |
| H-EMB | Chỉ-dense, e5-large nâng recall@5 trên 788 vượt ngưỡng so với **cả** v0 lẫn v0-qi | nhánh (i) |
| H-EMB-ship | Đường ship không mất câu; cải thiện nếu có phải vượt ngưỡng | nhánh (ii) |
| H-EMB-gate | 82 câu không mất câu | nhánh (iii) |

Mỗi giả thuyết có hai kết quả đều được ghi vào `docs/RESULTS.md`.

## Control — cấu hình nào, vì sao

| Nhánh | Cấu hình | Control | Vì sao |
|---|---|---|---|
| (ii) đường ship | profile heldout, `--contextual --reranker`, hybrid, chỉ mục heldout **như đang có** (ctx ON, dựng 08/09) | **trung bình hai lần lặp của ticket 11** (cùng cấu hình `heldout-ctxON-rerankerON-20260908-055318`); sàn dao động = số câu đổi kết quả giữa hai lần | Đây là cấu hình đang ship, và là cấu hình duy nhất có sàn dao động. Không dùng 0,7843 (ctx OFF, spec reranker): chỉ mục đang ở trạng thái ctx ON, nạp lại ~1 giờ và sinh ngữ cảnh không tất định sẽ thêm một nguồn dao động thứ hai |
| (i) chỉ-dense | profile heldout, `--mode dense --no-reranker --contextual`, cùng chỉ mục | **một lần chạy v0** (mới, chưa có) | Chưa có số chỉ-dense nào. Lúc truy vấn không có bước sinh, nên dao động kỳ vọng ≤ sàn của (ii); **luật**: nếu sàn của ticket 11 > 2 câu ở hạng 1, chạy v0 chỉ-dense **hai lần** để có sàn riêng |
| (iii) cổng 82 | profile lab (ctx ON, reranker ON), chỉ mục lab + collection mới `documents_lab_qi` | `data/evaluation/rag_multidoc_baseline.json` (có hạng từng câu) | Cổng CI đang dùng; chỉ làm rào, không làm thước |

Nếu ticket 11 báo chỉ mục heldout **không** ở trạng thái ctx ON → dừng, viết lại mục này; không tự nạp lại.

## Sàn dao động (điền từ ticket 11, trước khi đo)

| Ký hiệu | Nghĩa | Giá trị |
|---|---|---|
| C-Acc1 | Acc@1 trung bình hai lần lặp | 0,7919 |
| C-R5 | recall@5 trung bình hai lần lặp | 0,9822 |
| F1 | số câu đổi kết quả ở hạng 1 giữa hai lần (đếm, không phải %) | 0 |
| F5 | số câu đổi kết quả ở top-5 giữa hai lần | 0 |
| p50-C | p50 `/rag/search` (ms) của lần lặp | 4 585 (trung bình 4 622 và 4 548; có thể đã bị Ollama dùng chung đẩy lên) |

N = 788. Ngưỡng McNemar cho N này: +0,032 (= 25 câu) — `.scratch/reranker-finetune/spec.md`.

**Điền 27/10 từ ticket 11 (opus 5.5), trước lần đo đầu tiên của 09.** Hai lần lặp cho hạng giống hệt trên
cả 788 câu, nên F1 = F5 = 0: các điều kiện dạng max(0,032 ; 2·F/N) thành 0,032, các điều kiện "không
tụt quá sàn" thành **không tụt câu nào**, và luật "sàn > 2 câu thì lặp v0" không kích hoạt. So với 08/09
có 2 câu đổi (không câu nào ở hạng 1), sau khi đổi code và Ollama: đó là trôi giữa hai phiên bản, không
phải dao động lặp lại; control của nhánh (ii) là các lần lặp 27/10, không phải file 08/09.

**Trần của recall@5, và luật chọn thước cho nhánh (i).** Ở đường ship recall@5 đã là 0,981–0,982: chỉ còn
~14 câu ngoài top-5, nên một ngưỡng 25 câu là **không thể đạt theo cấu trúc**. Nhánh chỉ-dense chưa có số
nào, nên không biết trần. Vì vậy thước chính của nhánh (i) được chọn **bằng luật, sau lượt v0 chỉ-dense
và trước lượt treatment**:

| Bước | Luật |
|---|---|
| 1 | Tính headroom của mỗi thước trên lượt v0 chỉ-dense: recall@5 → 1 − R5; Acc@1 → R5 − Acc@1 |
| 2 | Thước chính = thước **đầu tiên** trong thứ tự [recall@5, Acc@1] có headroom ≥ 2 × 0,032 = 0,064 |
| 3 | Không thước nào đủ → thước chính là MRR, điều kiện 1 thành "khoảng tin cậy 95% bootstrap theo cặp của ΔMRR không chứa 0" |

Thước đã chọn ghi vào Comments của 09 **trước** khi chạy lượt v0-qi. Luật này cơ học, nên chọn sau khi
thấy số control vẫn không phải chọn sau khi thấy số treatment.

## Điều kiện dừng — cố định trước khi đo

Với treatment T so với control C của **cùng nhánh**, so **từng câu**:

| # | Nhánh | Điều kiện | Ngưỡng |
|---|---|---|---|
| 1 | (i) dense | Δ của **thước chính** (chọn theo luật trên) | ≥ max(0,032 ; 2·F5/N); nếu thước chính là MRR: CI 95% bootstrap theo cặp không chứa 0 |
| 2 | (i) dense | thước còn lại (Acc@1 hoặc recall@5) | ≥ −F1/N (không tụt quá sàn) |
| 3 | (i) dense | câu từ tìm thấy → mất (top-5) | ≤ F5 |
| 4 | (ii) ship | ΔAcc@1 và ΔRecall@5 | ≥ −F1/N và ≥ −F5/N |
| 5 | (ii) ship | câu từ tìm thấy → mất | ≤ F5 |
| 6 | (ii) ship | "cải thiện" chỉ được tuyên bố khi | ΔAcc@1 ≥ max(0,032 ; 2·F1/N) |
| 7 | (iii) gate | `evaluate_rag --baseline` | qua, **0** câu từ tìm thấy → mất, không dùng `--allow-per-case-regressions` |
| 8 | mọi nhánh | p50 `/rag/search` | ≤ 2 × p50-C |
| 9 | B only | H-pack | nDCG@10 VieQuAD ∈ [0,5912 ; 0,6312], **trước** mọi nhánh |
| 10 | B only | VRAM đo từ GPU trống, điền `vram_mib` | tổng general + embedding + reranker ≤ 16 311 MiB (`--check` tự tính) |

Quyết định:

| Kết quả | Hành động |
|---|---|
| 1–3 qua **và** 6 qua, 4–5, 7–8 qua | Ship: theo runbook (dựng collection production, dời `active`, restart). Dòng RESULTS.md "dương" |
| 1–3 qua, 4–5, 7–8 qua, 6 **không** qua | **Không tự ship.** Ghi "dương ở tầng dense, không phân biệt được ở đường ship". Có ship hay không là chủ dự án quyết, và lý do phải khác "nó không hại gì" |
| 1 không qua | Âm. Record giữ làm candidate (`eval.reports` null, thêm `notes`), dòng RESULTS.md "âm" |
| 3, 5 hoặc 7 không qua | Âm bất kể các dòng khác (giống luật 07/09: không đổi hạng của câu đang đúng) |
| 9 không qua | Vô hiệu: sửa đóng gói rồi đo lại 9, không đo nhánh nào |

Không hạ ngưỡng, không thêm nhánh đo sau khi thấy số. Muốn đổi thì viết bản đăng ký mới có ngày.

## Cách ghi chỉ dẫn vào registry — đã qua `--check`

Thêm vào `roles.embedding.versions`, **sau** `embedding-v0` (sau active = ứng viên, không bao giờ tự
được phục vụ), trước hoặc sau `embedding-e5l-v1` đều được:

```yaml
      - id: embedding-v0-qi              # CANDIDATE (after active): v0's weights + a query-side instruction
        provider: ollama
        collection_suffix: qi            # -> documents_qi / memories_qi (documents_lab_qi, documents_drill_heldout_qi)
        vram_mib: null                   # same tag as v0 (2870 at ctx 8192); still measured once before promotion
        eval:
          reports:
            d1_multidoc: null
            heldout: null
            mteb: null
        config:
          provider: ollama
          name: qwen3-embedding:0.6b
          context: 32768
          revision: qwen3-embedding-0.6b-r1
          normalization: raw
          dimensions: 1024
          query_prefix: "Instruct: Retrieve text based on user query.\nQuery: "   # the exact string mteb sent on 05/09
```

Vì sao như vậy, không phải cách khác:

| Cách | Kết quả |
|---|---|
| Sửa `config` của `embedding-v0` tại chỗ | Đỏ `test_model_registry.py:178`; phá quy ước byte-identical; không có đường lùi |
| Phiên bản mới dùng chung collection với v0 (`collection_suffix: ""`) | `--check` từ chối: suffix trùng (`model_registry.py:474-478`) |
| **Phiên bản mới, suffix `qi`, rebuild** (chọn) | `--check` 0 lỗi (kiểm 27/10 trên bản sao); vector passage giống hệt v0 nhưng nằm ở collection riêng — tốn một lượt embed, đổi lại có đường lùi và cache không bị lẫn |

Chú ý: khoá YAML `query_prefix` phải nằm **trong** `config` và dùng dấu ngoặc kép để `\n` thành xuống
dòng thật (`--check` không kiểm nội dung chuỗi; Bước 1 mới là phép kiểm).

## Tập đo theo thứ tự — lệnh chính xác

Mọi lệnh chạy từ `C:\Users\dungbt06\local-ai-core` (hoặc `backend\` khi ghi rõ), Python của checkout
chính. Stack heldout do một người dùng một lúc (ticket 11 trước, 09 sau).

**Bước 0 — tiền đề (phải xanh, ghi vào Comments của 09)**

```bat
.venv\Scripts\python.exe -m training.common.split_manifest --check
.venv\Scripts\python.exe -m training.common.leak_check --construction-only
cd backend && ..\.venv\Scripts\python.exe -m app.config.model_registry --check
```

Ticket 11 xong và bảng sàn dao động ở trên đã điền. Commit thêm record `embedding-v0-qi` **trước** khi
chạy bất cứ lệnh embed nào (tương đương "script train commit trước GPU").

**Bước 1 — tiền tố có tới model không** (bẫy 05/09: hai lần "khác nhau" mà giống hệt)

Thêm và commit `backend/scripts/probe_embedding_prefix.py` (chưa chạy; import và chữ ký lấy từ
`rebuild_qdrant.py:33-38`, `settings.py:362-374`):

```python
"""Prove a query-side prefix reaches Ollama: query vectors differ, passage vectors do not."""
import json, math, os, subprocess, sys

TEXT = "thủ tục cấp lại căn cước công dân"


def vectors() -> dict[str, list[float]]:
    from app.config.settings import Settings
    from app.llm_clients.ollama_client import OllamaClient
    from app.services.model_router import ModelRouter
    s = Settings()
    resolved = s.resolve_models(allow_missing_collections=True)
    router = ModelRouter({"ollama": OllamaClient(s.ollama_base_url, s.ollama_chat_timeout_seconds, s.ollama_health_timeout_seconds, s.ollama_retry_count)},
                         s.load_models(), embedding_refusal=resolved.embedding_refusal())
    return {side: router.embed(TEXT, side=side)[0] for side in ("query", "passage")}


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


if __name__ == "__main__":
    if sys.argv[1:] == ["--one"]:
        print(json.dumps(vectors())); raise SystemExit(0)
    env = {**os.environ, "MODEL_STARTUP_PROBES": "false"}
    base = json.loads(subprocess.check_output([sys.executable, __file__, "--one"], env={**env, "MODEL_VERSION_EMBEDDING": ""}))
    pinned = json.loads(subprocess.check_output([sys.executable, __file__, "--one"], env={**env, "MODEL_VERSION_EMBEDDING": sys.argv[1]}))
    print(json.dumps({"query_cosine": cosine(base["query"], pinned["query"]), "passage_cosine": cosine(base["passage"], pinned["passage"])}))
```

```bat
cd backend
..\.venv\Scripts\python.exe -m scripts.probe_embedding_prefix embedding-v0-qi
```

Điều kiện đi tiếp: `query_cosine` **< 0,999** và `passage_cosine` **≥ 0,999999**. Ghi hai số vào Comments.
Không đạt → dừng (tiền tố chưa tới model, hoặc tới cả hai phía).

**Bước 2 — dựng collection `qi` cho chỉ mục heldout** (shell tạm, không đụng `.env`)

Chỉ bắt đầu khi ticket 11 đã có **cả hai** file kết quả: bước này không đụng API heldout nhưng chiếm
Ollama và Qdrant — đúng hai thứ ticket 11 đang đo p50 trên đó.

```bat
cd backend
set DATABASE_URL=<phần trước dấu / cuối của DATABASE_URL trong .env>/local_ai_core_drill_heldout
set QDRANT_DOCUMENTS_COLLECTION=documents_drill_heldout
set MODEL_VERSION_EMBEDDING=embedding-v0-qi
..\.venv\Scripts\python.exe -m scripts.rebuild_qdrant --dry-run
..\.venv\Scripts\python.exe -m scripts.rebuild_qdrant
..\.venv\Scripts\python.exe -m scripts.rebuild_memories
set MODEL_VERSION_EMBEDDING=
set QDRANT_DOCUMENTS_COLLECTION=
set DATABASE_URL=
```

Điều kiện đi tiếp: dòng `points_after == active_chunks` của `rebuild_qdrant`. Ghi `points_after` và
thời gian chạy vào Comments (đây là số đo đầu tiên cho chi phí re-embed 2 947 tài liệu).

**Bước 3 — nhánh (i) chỉ-dense, hai model** (mỗi lượt ~30 phút)

```bat
.venv\Scripts\python.exe -m training.common.eval_stack --profile heldout --start --mode dense --no-reranker --contextual
.venv\Scripts\python.exe -m training.common.eval_heldout --dataset data\evaluation\heldout_retrieval_v1\zalo-legal_subset.jsonl --base-url http://127.0.0.1:8200 --label v0-dense-ctxON-rerankerOFF
.venv\Scripts\python.exe -m training.common.eval_stack --profile heldout --stop

.venv\Scripts\python.exe -m training.common.eval_stack --profile heldout --start --mode dense --no-reranker --contextual --model-version embedding=embedding-v0-qi
.venv\Scripts\python.exe -m training.common.eval_heldout --dataset data\evaluation\heldout_retrieval_v1\zalo-legal_subset.jsonl --base-url http://127.0.0.1:8200 --label v0qi-dense-ctxON-rerankerOFF
.venv\Scripts\python.exe -m training.common.eval_stack --profile heldout --stop
```

Trước mỗi `eval_heldout`, mở `http://127.0.0.1:8200/models`: `registry.embedding.loaded` phải đúng id,
không `fallback` (script tự từ chối ghi nếu có fallback, nhưng đọc trước thì khỏi mất 30 phút).
Nếu luật "sàn > 2 câu" kích hoạt, chạy lượt v0 thêm một lần với nhãn `v0-dense-ctxON-rerankerOFF-rep2`.

**Bước 4 — nhánh (ii) đường ship, chỉ treatment** (control là hai lần lặp của ticket 11)

```bat
.venv\Scripts\python.exe -m training.common.eval_stack --profile heldout --start --reranker --contextual --model-version embedding=embedding-v0-qi
.venv\Scripts\python.exe -m training.common.eval_heldout --dataset data\evaluation\heldout_retrieval_v1\zalo-legal_subset.jsonl --base-url http://127.0.0.1:8200 --label v0qi-hybrid-ctxON-rerankerON
.venv\Scripts\python.exe -m training.common.eval_stack --profile heldout --stop
```

**Bước 5 — nhánh (iii) cổng 82 câu trên lab**

```bat
cd backend
set DATABASE_URL=<phần trước dấu / cuối>/local_ai_core_lab_20260821
set QDRANT_DOCUMENTS_COLLECTION=documents_lab
set MODEL_VERSION_EMBEDDING=embedding-v0-qi
..\.venv\Scripts\python.exe -m scripts.rebuild_qdrant
..\.venv\Scripts\python.exe -m scripts.rebuild_memories
set MODEL_VERSION_EMBEDDING=
set QDRANT_DOCUMENTS_COLLECTION=
set DATABASE_URL=
cd ..
.venv\Scripts\python.exe -m training.common.eval_stack --profile lab --start --model-version embedding=embedding-v0-qi
cd backend
..\.venv\Scripts\python.exe -m scripts.evaluate_rag --multidoc-dataset ..\data\evaluation\rag_multidoc_eval.jsonl --retrieval-only --baseline ..\data\evaluation\rag_multidoc_baseline.json --base-url http://127.0.0.1:8100
cd ..
.venv\Scripts\python.exe -m training.common.eval_stack --profile lab --stop
```

**Bước 6 — so từng câu và viết kết quả**

So từng câu giữa hai file kết quả của mỗi nhánh (trường per-query trong JSON của `eval_heldout`): đếm
tìm thấy→mất, mất→tìm thấy, lên/xuống hạng 1. Điền bảng điều kiện dừng. Dù kết quả nào: một dòng vào
`docs/RESULTS.md` (mục Held-out, cùng định dạng), file kết quả được trích dẫn chép vào
`data/evaluation/results/kept/`, Comments của ticket 09 ghi lệnh + đường dẫn. Qua → điền
`eval.reports.heldout` / `d1_multidoc`, đo `vram_mib`, rồi runbook ship. Không qua → record giữ nguyên
là candidate, thêm `notes` ghi ngày và kết quả.

**B đầy đủ — chỉ sau Bước 6 của nhánh 0, và chỉ khi chủ dự án xác nhận lại lượt tải**

1. Viết + commit `backend/scripts/build_embedding_model.py` (theo mẫu `build_ocr_model.py`: ghim sha nguồn
   HF và sha GGUF đích; `.[ocr-build]` đã có `gguf==0.19.0`, còn `convert_hf_to_gguf.py` là của llama.cpp —
   cần clone). Điền `data/models/embedding/embedding-e5l-v1/Modelfile` và `gguf_sha256`; `--check` xanh.
2. `run_mteb.py` hiện chỉ biết chỉ dẫn kiểu Qwen (`instruction_template`, không áp lên tài liệu); e5 cần
   tiền tố **hai phía** → thêm tuỳ chọn tiền tố query/passage, commit, rồi mới đo H-pack:
   `.venv-eval\Scripts\python.exe -m training.common.run_mteb --model local-ai/multilingual-e5-large:q8 --tasks VieQuADRetrieval <cờ tiền tố mới> --version-id embedding-e5l-v1`.
3. Lặp Bước 2–6 với `embedding=embedding-e5l-v1`, nhãn `e5l-…`; control của (i) là lượt v0 ở Bước 3, so
   thêm với v0-qi. Nhớ e5 chạy `context: 512` — chunk dài hơn 512 subword bị cắt ở tầng embedding;
   ghi tỉ lệ chunk bị cắt vào báo cáo (đo bằng tokenizer e5 trên chunk heldout, không cần GPU).

## Ước lượng

| Việc | Thời gian |
|---|---|
| Bước 1 | phút |
| Bước 2 (re-embed heldout, không sinh ngữ cảnh) | 10–30 phút (chưa đo; Bước 2 là lần đo) |
| Bước 3 | 2 × 30 phút (+30 nếu lặp v0) |
| Bước 4 | 30 phút |
| Bước 5 | ~10 phút |
| Tổng nhánh 0 | ~2–2,5 giờ GPU, một phiên, trong cửa sổ 05:00–21:00 |
| B thêm | 1 phiên đóng gói + ~2 giờ đo |

## Chưa kiểm

- `probe_embedding_prefix.py` chưa chạy (Ollama đang phục vụ ticket 11); `resolve_models` với
  `MODEL_STARTUP_PROBES=false` có cần Postgres không — nếu cần, chạy sau Bước 2 với env của Bước 2.
- Tên trường per-query trong JSON của `eval_heldout` (đọc khi có file đầu tiên).
- Trạng thái ctx của chỉ mục heldout — chờ ticket 11.
- `rebuild_memories` trên DB heldout: bảng `memories` có thể rỗng; nếu script từ chối vì rỗng thì ghi lại,
  không coi là lỗi của nhánh.

## Bổ sung trước khi đo (27/10, opus 5.5, theo rà soát của Nhân viên 2 — chưa lệnh đo nào chạy)

| # | Điểm | Quyết định |
|---|---|---|
| 1 | Chạy ở đâu | Worktree riêng `wip/09-model-experiment-run`, tạo từ `main` **ngay sau** khi gộp record + probe (vì editable trỏ về main: worktree phải trùng main thì hai nửa mới chạy cùng code). Không sửa code trong worktree đó. File kết quả commit trên nhánh này |
| 2 | Shell | Git Bash, đặt env theo từng lệnh (`VAR=... cmd`). **Không** dùng `set` trong PowerShell — ở đó `set` không đặt biến môi trường, rebuild sẽ ghi vào DB/collection production |
| 3 | Bước 2, số điểm | Điều kiện vẫn là `points_after == active_chunks`; với chỉ mục heldout con số kỳ vọng là **3 896** (phiên bản đang dùng), không phải 7 792 (collection v0 chứa cả 3 896 điểm của phiên bản đã bị thay; tìm kiếm lọc theo phiên bản đang dùng) |
| 4 | Trôi vector passage | **Bước 2b mới**, chỉ đọc: so cosine từng điểm giữa `documents_drill_heldout` (v0, nhúng 08/09) và `documents_drill_heldout_qi` (nhúng 27/10, Ollama 0.40.8) theo cùng id. Luật bậc, cố định trước khi đo: min ≥ 0,999999 → không nhiễu, đi tiếp; 0,9999 ≤ min < 0,999999 → đi tiếp, ghi là giới hạn (Δ gồm cả tiền tố lẫn nhúng lại; quyết định ship vẫn đúng vì ship cũng phải nhúng lại); min < 0,9999 → **dừng**, mở ticket dựng collection v0 nhúng mới làm control |
| 5 | Thời gian | Nhánh 0 ước 2,5–3 giờ (Bước 4 ≈ 62 phút, đo ở ticket 11). Chạy trọn một mạch khi GPU rảnh, nếu bắt đầu được trước 23:30 (để mọi stack dừng trước 02:45); không thì dời trọn sang 05:00. **Không** tách Bước 2–3 và 4–5 sang hai buổi (p50 đo khác giờ với p50-C). Cửa sổ 05:00–21:00 ở mục Ước lượng là vì bot Discord dùng GPU 22:00–04:00; tối 27/10 bot không chạy |
| 6 | Ghi chú | `memories` của heldout và lab đều 0 dòng → `rebuild_memories` không tạo `memories_qi`, là bình thường. `eval_stack` in sai "contextual=OFF" — đọc `/models` |

## Bổ sung 2 — sau khi luật trôi passage dừng nhánh 0 (27/10 ~20:15, opus 5.5; chưa lượt đo nào chạy)

Bước 2b đo được: so 3 896 / 3 896 điểm theo cùng id giữa `documents_drill_heldout` (nhúng 08/09) và
`documents_drill_heldout_qi` (nhúng 27/10): min 0,99911526, p1 0,99951999, trung vị 0,99970730; cả
3 896 điểm < 0,999999. Theo luật bậc (min < 0,9999) → **dừng**, không đo. Bước 1 cho thấy passage của
v0 và qi nhúng **cùng hôm nay** trùng nhau (0,9999999999999999), weights không đổi (digest
`ac6da0dfba84`), văn bản đầu vào và đường gọi nhúng không đổi từ f88380f. Nguyên nhân còn lại nằm ngoài
repo: Ollama 0.33.2 → 0.40.8, hoặc phần số học GPU/driver; chưa tách được.

Kế hoạch mới, cố định trước khi đo:

| # | Thay đổi |
|---|---|
| 1 | `eval_stack` thêm cờ đặt gốc tên collection (ví dụ `--collection-base`), commit + duyệt **trước** khi nhúng. Chỉ mục 08/09 và kết quả ticket 11 giữ nguyên, không ghi đè |
| 2 | Nhúng mới **cả hai** phía dưới cùng một gốc mới, trên cùng runtime, cùng buổi: v0 (suffix rỗng) và qi (suffix `qi`). `documents_drill_heldout_qi` nhúng 27/10 không dùng nữa |
| 3 | Chạy lại Bước 2b giữa hai collection mới: passage phải ≥ 0,999999 (cùng runtime). Không đạt → dừng |
| 4 | Control nhánh (ii) = **một lượt mới** v0 hybrid ctx ON reranker ON trên collection v0 mới (không dùng các lần lặp của ticket 11, vì chúng chạy trên vector 08/09). Sàn dao động lặp lại vẫn lấy từ ticket 11 (F1 = F5 = 0), vì đó là tính chất của đường truy vấn khi vector cố định |
| 5 | Mọi điều kiện dừng, luật chọn thước, tập đo giữ nguyên |
| 6 | Thời gian ~4 giờ GPU (2 lần nhúng ~18 phút + control ~62 phút + Bước 3–5). Không kịp trước 02:45 tối 27/10 → chạy trọn một mạch từ sáng 28/10 |

Hệ quả rộng hơn 09: mọi phép so A/B về embedding (kể cả B đầy đủ với e5) phải nhúng lại **cả hai** phía
trên cùng runtime; registry và manifest eval hiện không ghi phiên bản Ollama.
