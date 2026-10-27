# M3 — Chọn mục tiêu cho một thí nghiệm model

Status: đề xuất, chờ chủ dự án chọn (27/10/2026) — ticket 08, chỉ đọc, không GPU
Viết bởi: fable 5.1 của Ún. Mọi số đều đọc lại từ file trong repo, không đo mới trừ hai lệnh kiểm
ở cuối.

## Bản chất

Hệ có bốn chỗ có thể "dạy" cho khá hơn: cái xếp lại thứ tự kết quả tìm (reranker), cái biến chữ
thành vector để tìm (embedding), cái đọc tin Discord rồi quyết định có ghi nhớ không (extractor),
và cái đọc ảnh scan (OCR). Chỉ ba cái đầu có bài thi sẵn để biết làm xong là khá hay không. Trong
ba cái đó, reranker đã thử một lần và trượt đúng luật mình đặt; embedding thì đang thua một model
cùng cỡ ở bài thi công khai nhưng trong sản phẩm nó chỉ đóng góp rất ít ở vị trí số một; extractor
có giả thuyết sạch nhất nhưng tốn nhất và tính năng dùng nó hiện gần như chưa ai dùng. Không ứng
viên nào vừa rẻ, vừa chắc ra model tự train, vừa đổi được sản phẩm — nên phải chọn mất gì.

## Bộ đo nào phân giải được gì

Đây là cột quyết định: thí nghiệm chỉ có nghĩa khi bộ đo phân giải được mức thay đổi kỳ vọng.

| Bộ đo | Cỡ | Phân giải | Cần | Dùng cho |
|---|---:|---|---|---|
| Held-out Zalo Legal (`training/common/eval_heldout.py`) | 788 câu | McNemar 80%: +3,2–5,5 điểm Acc@1; 1 câu = 0,13 điểm | stack heldout (cổng 8200, Postgres + Qdrant + Redis) | reranker, embedding |
| Cổng 82 câu (`backend/scripts/evaluate_rag.py`) | 82 | bão hoà: recall@5 = 1,0; 1 câu = 1,22 điểm | stack lab (8100) | chỉ làm rào "không mất câu" |
| Benchmark extractor (`benchmark_discord_memory_extractor.py`) | 150 (~50 ca phải im lặng) | bootstrap ±0,12 trên no_op | **chỉ Ollama** | ship / không ship D2; không dùng cho ablation |
| Dev reranker (`data/evaluation/reranker_v1/dev_pool.jsonl`) | 134 | 1 câu = 0,75 điểm; trần pool 0,8433 | không cần stack | chọn checkpoint |
| mteb VieQuAD (`training/common/run_mteb.py`) | 2 490 tài liệu | số công bố để so (e5-large 0,6112) | `.venv-eval` + Ollama | kiểm model embedding đã đóng gói đúng |
| Dao động cùng cấu hình | — | 82 câu: re-index không đổi code −0,0010 MRR; **held-out: chưa có lần lặp nào cùng cấu hình** | — | — |

Dòng cuối là lỗ hổng: ticket 09 nói "chỉ giữ khi vượt mức dao động đã đo", nhưng trên 788 câu
chưa đo dao động bao giờ — ba lần chạy 07–08/09 (0,7843 / 0,7919 / 0,7906) là ba cấu hình khác nhau
(ctx OFF; ctx ON; heading-ctx), không phải ba lần lặp. Hai lần 08/09 chưa vào `docs/RESULTS.md`.

## Ứng viên

### A — Reranker lần 3 (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, 118M)

**Nút thắt (số + file).** 155/788 câu có đáp án trong top-5 nhưng không đứng đầu (recall@5 0,9810 −
Acc@1 0,7843, `results/kept/heldout-treat-rerankerON-20260906-185648.json`). Reranker đang ship đẩy
84 câu lên hạng 1 và đẩy 72 câu khỏi hạng 1 — gần tung đồng xu (`.scratch/reranker-finetune/spec.md`,
bảng "What the model actually learned").

**Giả thuyết.** Kết luận 07/09: lỗi của bản fine-tune là *hiệu chỉnh độ tự tin* (từ chối quá chắc:
13 câu từ tìm thấy thành mất, 12 trong đó đang ở hạng 1–3), không phải nhãn — lần 2 bỏ 8,6% âm khó
đã bác bỏ giả thuyết nhãn (dev 0,4179 < 0,5373 chưa train). Hai nhánh:

| Nhánh | Làm gì | Train? |
|---|---|---|
| A1 | Giữ checkpoint `reranker-vi-v1` (có trên đĩa, 470 MB), **trộn** điểm reranker với hạng RRF thay vì thay thế. α không chọn được trên dev 134 — pool dev là pool BM25 thô, không có hạng RRF — nên phải đăng ký trước một α, hoặc lấy pool hybrid từ stack heldout (cần stack) | không |
| A2 | Train lại chỉ học thứ tự *trong cùng pool* (pairwise/listwise), sửa cách gom batch để không tràn VRAM | có, 143 s/epoch, 3,1 GB |

**Tập đo.** dev 134 (không cần stack) → 788 (stack heldout) → 82 (stack lab).
**Điều kiện dừng.** Sáu điều kiện đã viết sẵn trong spec, không hạ: Acc@1 ≥ 0,8163; Acc@3 ≥ 0,9557;
0 câu từ tìm thấy thành mất; ≤ 100 ms/15 cặp; 82 câu 0 mất; nạp được dưới sentence-transformers 3.4.1.
**GPU/thời gian.** A1: ~0 GPU; test 788 câu ≈ 30 phút (2,3 s/câu) mỗi α. A2: vài epoch × 143 s; dev 6 s. 1–2 phiên.

| Ưu | Nhược |
|---|---|
| Dữ liệu, script, dev, ngưỡng đều có sẵn; rẻ nhất về GPU | Lần 1 đạt +0,019, ngưỡng cần +0,032: với cùng 2 168 câu, xác suất qua thấp |
| A1 kiểm thẳng chẩn đoán "hiệu chỉnh" mà không train | Đã quét 6 biến thể BCE: dev 0,5746–0,6269 = chênh 1–7 câu, trong nhiễu — không còn núm rẻ để vặn |
| Kết quả nào cũng thêm một dòng RESULTS.md | Kết quả âm thứ hai trên cùng mục tiêu ít giá trị CV hơn kết quả âm đầu |
| | Không đổi sang reranker tiếng Việt công khai được dễ dàng: bkai train trên 80% train split Zalo Legal — chính nguồn của 788 câu test (`docs/RESULTS.md`, mục Held-out; bkai model card) → nhiễm; AITeamVN **cần kiểm model card** trước khi loại trừ |

### B — Đổi embedding sang `multilingual-e5-large` (560M, dim 1024), kèm nhánh 0

**Nút thắt.** Trên VieQuAD — task duy nhất có 14 model công bố — model đang dùng 0,4848, thua
`multilingual-e5-small` 118M (0,5527); e5-large 0,6112 (+0,126). Chỉ dẫn phía truy vấn cho model
hiện tại +0,0467 miễn phí (`data/evaluation/mteb/vietnamese_native_summary.json`). Bảng biểu 0,3768.

**Nhưng** trong sản phẩm, tầng dense chỉ thêm **+0,004 Acc@1** và +0,033 recall@5 so với BM25 một
mình trên luật (0,7563 → 0,7602; 0,9150 → 0,9480; `heldout-bm25-rrno-20260905-044222.json` so với
`heldout-bare-20260904-220305.json`). Hạng 1 là của BM25. Đường ship (hybrid + reranker) có thể
không nhìn thấy đổi embedding; phải đo thêm ở chế độ chỉ-dense — cờ `RAG_RETRIEVAL_MODE=dense` có
sẵn (`backend/app/config/settings.py:141`, `training/common/eval_stack.py:114`) nhưng **chưa từng
chạy**.

**Giả thuyết H-EMB.** Ở chế độ chỉ-dense, e5-large nâng recall@5 trên 788 câu ≥ +0,032 so với
`qwen3-embedding:0.6b` chỉ-dense; ở hybrid không mất câu nào. Nếu dense tốt hơn mà hybrid không đổi:
kết luận "sản phẩm trên luật không nhìn thấy embedding" — đó là câu trả lời cần có *trước* khi
fine-tune e5 (bước kế theo hướng chủ dự án đã chốt 05/09).

**Tập đo, theo thứ tự.**

| # | Đo gì | Để làm gì |
|---|---|---|
| 1 | mteb VieQuAD với model *như Ollama phục vụ* (Q8, có tiền tố) | kiểm đóng gói: phải trong ±0,02 của 0,6112; lệch xa = đóng gói hỏng → thí nghiệm **vô hiệu**, không phải âm. Đây là đo model mình đóng gói, không đo lại số người khác |
| 2 | 788 chỉ-dense, hai model | H-EMB |
| 3 | 788 hybrid, ctx OFF, reranker ON (control 0,7843) | đường gần ship |
| 4 | 82 câu | rào |

**Điều kiện dừng (đề xuất, viết trước khi đo).** (2) recall@5 ≥ control + 0,032 và Acc@1 không giảm;
(3) 0 câu mất, Acc@1 ≥ control − 0,01; (4) 0 mất; VRAM đo từ GPU trống điền vào `vram_mib` (registry
từ chối null khi active); p50 `/rag/search` ≤ 2× hiện tại.

**GPU/thời gian.** Tải e5-large (~1,1 GB fp16, **cần duyệt**) → GGUF (cần `convert_hf_to_gguf.py`
của llama.cpp, chưa có trên máy; XLM-R được llama.cpp hỗ trợ — `bge-m3` cùng kiến trúc có trên Ollama
library) → `ollama create` → `rebuild_qdrant` với `MODEL_VERSION_EMBEDDING=embedding-e5l-v1`: embed
lại từ chunk đã lưu trong Postgres, **không parse lại file** (`backend/scripts/rebuild_qdrant.py:108`)
nên DB lab mất file gốc vẫn làm được; lab vài phút, heldout 2 947 tài liệu ~10–30 phút → 4 lần 788 câu
× ~30 phút. ≈ 2–3 phiên, GPU < 3 giờ.

**Nhánh 0 — chỉ dẫn truy vấn cho model hiện tại.** Không tải gì, và ghi chú 05/09 "không cần
re-index" **đúng** (kiểm 27/10): tiền tố chỉ phía truy vấn không đổi vector passage; `config_fingerprint`
chỉ được đọc bởi cache embedding phía passage (`postgres_document_service.py:559-581`,
`embedding_cache_store.py:84-92`), còn đường truy vấn gọi thẳng `router.embed(query, side="query")`
(`postgres_retrieval_service.py:41`) không qua cache. Hệ quả: thêm `query_prefix` chỉ làm cache
trượt ở lần index sau, không cần `rebuild_qdrant`. Chưa kiểm: ghi vào registry bằng cách nào — sửa
`config` của `embedding-v0` tại chỗ (phá quy ước "byte-identical") hay một phiên bản mới dùng chung
collection — `model_registry --check` chấp nhận cách nào. Chi phí: vài phút lab + 4 lần 788 câu. Là
đối chứng của B: nếu chỉ dẫn lấy được phần lớn lợi ích thì đổi model kém hấp dẫn.

| Ưu | Nhược |
|---|---|
| Rẻ nhất có kết quả hai chiều trên hai bộ đo độc lập | **Không ra model tự train** — không bù khoảng trống CV |
| Tập dượt chuỗi HF → GGUF → `ollama create` → registry → collection riêng mà D2 cũng cần | Rất có thể "không phân biệt được" trên đường ship vì hạng 1 là của BM25 |
| Đúng hướng chủ dự án đã chốt; registry đã có record `embedding-e5l-v1` + code tiền tố (`model_router.py:191`) | Record trỏ Modelfile chưa tồn tại (`data/models/embedding/` không có); Ollama nay 0.40.8, mọi hành vi Ollama trong ghi chú đo trên 0.33–0.34 |
| Trả lời "fine-tune embedding có chỗ để cải thiện sản phẩm không" trước khi tốn GPU fine-tune | Tiền tố e5 bất đối xứng: quên một phía là ra số thấp và kết luận sai |

### C — D2: chưng cất extractor `qwen3.5:9b` → Qwen3.5-2B (LoRA bf16)

**Nút thắt.** no_op 0,52 so với 0,86 (−0,34), fact 0,70/0,95, operation 0,69/0,86; nhưng schema,
grounding, adapter bằng hoặc hơn (`data/benchmarks/discord_memory_extractor_20260904_*_full150.json`).
2B gán đúng người 82/82 ca có bản ghi. Hình dạng lỗi này là **H-DATA**: lỗi ở dữ liệu dạy, không ở cỡ.

**Giả thuyết, 10 điều kiện dừng, ablation 4 giả thuyết** đã viết sẵn ở `.scratch/d2-distillation/spec.md`
(no_op ≥ 0,86, fact ≥ 0,95, ≤ 9 suy diễn, 0 forged, wall-clock ≤ 0,6× 9b, GGUF ≡ HF trên 30 ca, VMLU).

**Tập đo.** Gate 150 ca — **chỉ cần Ollama**, không cần Postgres (ưu thế lớn khi Docker đang bị chặn);
dev 1 000 ca sinh bằng Gemini (**chưa tồn tại**); held-out thật ~100 (cần Postgres để xuất, gán nhãn
tay); 50–100 câu bạn học viết (chưa có).

**GPU/thời gian.** Probe 100 mẫu trước (ngân sách 5 phiên); dán nhãn thầy 5 000 mẫu ≈ 5 giờ GPU;
ablation ≈ 10–14 lần train LoRA 2B (ước 5 GB; còn 6,2 GB khi 9b nằm) ≈ 10–20 giờ GPU ban ngày
(05:00–21:00). Tổng ≈ 10–15 phiên.

**Môi trường, đo 27/10.** `.venv-train` thiếu peft, trl, unsloth, bitsandbytes; HF cache không có
Qwen3.5-2B lẫn Nemotron-Personas-Vietnam — mỗi tải cần duyệt; Qwen3.5 trên Windows sm_120: fla /
causal_conv1d tuỳ chọn (chậm hơn, không chặn), bitsandbytes chưa thử.

| Ưu | Nhược |
|---|---|
| Ứng viên duy nhất ra **model tự train** với giả thuyết sạch | Đắt nhất; nhiều cổng chưa qua (probe, gói, dev set) |
| Gate chạy không cần stack | Tính năng trí nhớ Discord, tính đến 29/09: 33 tin / 2 người, 0 lượt dùng từ 29/08 → giá trị sản phẩm thấp, giá trị CV cao |
| Spec đầy đủ, viết trước 04/09 | Học trò 2B là **thêm** 3,1 GB VRAM, không bớt — 9b vẫn phải nằm cho đường trả lời |

### Không đủ điều kiện làm M3 — chưa có bộ đo

| Ứng viên | Vì sao chưa |
|---|---|
| OCR dấu tiếng Việt (~15% từ sai ở 200 dpi, 29/09) | chỉ có probe 1 trang; chưa có bộ scan tiếng Việt có đáp án; model vision, fine-tune ngoài ngân sách |
| Bảng biểu (mteb 0,3768) | chưa biết lỗi ở chunker hay embedding; sản phẩm không có bài nào về bảng; B đo được thêm ở tầng embedding (40 phút/task vì cạn cổng Windows) nhưng không là mục tiêu riêng |
| Verifier / grounding NLI (H3) | verifier 0 phán quyết trong production; e2e `--with-extractor` chưa chạy lần nào (`data/benchmarks/memory_e2e/` không tồn tại); grounding 0 ungrounded → recall chưa biết |
| Reranker to hơn (bge-reranker-v2-m3, 568M) | trái nguyên tắc "cùng cỡ, tốt hơn"; dữ liệu train không công khai → không loại trừ nhiễm Zalo; 39,5 ms → ước > 100 ms, vi phạm điều kiện 4 |

## Vì sao lần fine-tune 07/09 trượt, và điều kiện để không lặp lại

Trượt 4/6: Acc@1 0,8033 < 0,8163 (+0,019 thật nhưng dưới mức McNemar phân giải); Acc@3 thiếu 1 câu;
13 câu từ tìm thấy thành mất; cổng 82 câu mất 2. Cơ chế: BCE trên nhãn thưa (24 câu có đáp án *khác
nhau* ở train và test chứng minh nhãn thiếu) dạy model từ chối tự tin; lần 2 bỏ 8,6% âm khó còn tệ hơn
không train → lỗi hiệu chỉnh, không phải nhãn.

Bốn điều nữa, đọc ra từ file ngày 27/10, **chưa được ghi ở đâu**:

| Vấn đề | Bằng chứng | Điều kiện cho lần sau |
|---|---|---|
| So sánh loss bị lệch | `loss_comparison_sweep-20260907.json`: MNRL / Lambda / ListNet / RankNet ghi `peak_vram_mib 26798` trên card 16 311 MiB → tràn sang RAM, 2 200–5 700 s/epoch so với 143 s của BCE | "BCE tốt nhất" chưa được chứng minh; muốn so lại phải gom batch sao cho không tràn |
| Quét siêu tham số trong nhiễu | 6 biến thể BCE: dev 0,5746–0,6269 = chênh 1–7 câu trên 134 | Chọn bằng luật mà dev-134 phân giải được (≥ 6 câu = 4,5 điểm), hoặc đăng ký trước *một* cấu hình, không quét |
| Code train chính xác đã mất | `train.py` sửa 23:34 sau export 21:50 (ghi trong `model_versions.yaml` notes) | Commit script **trước** khi chạy GPU (ticket 09 đã ghi); ghi sha vào provenance *tại lúc chạy* |
| Dev và test không cùng thước | dev = pool BM25 thô 45 ứng viên; test = cả đường hybrid + reranker | Không đọc số dev như số test; dev chỉ để xếp thứ tự checkpoint |

Và điều chung cho mọi ứng viên: **chạy một lần lặp control cùng cấu hình trên 788 câu trước
treatment**, vì "vượt mức dao động đã đo" hiện không có số để so.

## Đề xuất — đây là ý kiến

Tôi nghiêng về **B, bắt đầu bằng nhánh 0**, vì ba lý do: (1) rẻ nhất có kết quả hai chiều và không
cần tải gì cho bước đầu; (2) câu nó trả lời — "sản phẩm có nhìn thấy embedding không" — là điều phải
biết *trước* khi fine-tune e5, mà fine-tune e5 là model tự train kế tiếp theo hướng chủ dự án chốt
05/09; (3) nó tập dượt đúng chuỗi đóng gói mà C cần.

Cái giá: M3 kết thúc **không có** model tự train. Nếu chủ dự án muốn M3 tự nó ra model train, chọn
**C**, không chọn A — A có xác suất qua thấp và một kết quả âm thứ hai cùng mục tiêu dạy ít; C có
spec, có gate không cần Docker, và là thứ CV cần. A1 (trộn điểm, không train) đáng chạy như thí nghiệm
phụ 30 phút bất cứ lúc nào stack heldout bật, nhưng không nên là M3.

Quyết định đứng của chủ dự án mà tôi không tự đảo: 05/09 đã chốt "đổi sang e5-large rồi fine-tune
nó", và "đừng đề xuất đo lại số đã công bố". B tôn trọng cả hai — bước 1 của B đo model *mình đóng
gói*, không đo lại model của người khác. Nếu quyết định đó đã đổi, C là lựa chọn thay thế.

## Điều kiện tiên quyết cho ticket 09 — trạng thái đo 27/10

| Điều kiện | Trạng thái | Ghi chú |
|---|---|---|
| `python -m training.common.split_manifest --check` | **xanh** (12 artifact, hash khớp) | chạy 27/10 từ `.venv` |
| `python -m training.common.leak_check --construction-only` | **xanh** | chạy 27/10 |
| Script train commit trước GPU | A: `training/reranker/train.py` có trong repo (30b3d42) nhưng không phải bản đã train vi-v1 · B: chưa có script đóng gói — viết `scripts/build_embedding_model.py` theo mẫu `build_ocr_model.py` và commit trước `rebuild_qdrant` · C: `training/d2_extractor/` chưa tồn tại | |
| Stack heldout (8200) + lab (8100) | **không bật được**: `edu-postgres-1` giữ 5432; container của Ún tắt ~5 ngày, volume còn hay không chưa kiểm | A, B, nhánh 0 đều chặn; chỉ gate 150 của C chạy được. Việc của chủ dự án (quyết định 22/10: tạm tắt edu) |
| Lần lặp control cùng cấu hình trên 788 | **chưa có** | làm đầu tiên khi stack bật |
| Chọn và ghi control | spec reranker: ctx OFF 0,7843; sản phẩm ship ctx ON 0,7919 (08/09, chưa vào RESULTS.md) | phải nói rõ trong spec của 09. Ngữ cảnh sinh lúc index (profile heldout mặc định `contextual: False`, `eval_stack.py:63`; lần 08/09 chạy `contextual_retrieval: True`) nên DB heldout hiện nhiều khả năng đang ở trạng thái ctx ON → lặp control ctx OFF có thể phải nạp lại ~1 giờ, không chỉ restart |
| Tải model / dữ liệu | B: e5-large + llama.cpp; C: Qwen3.5-2B, Nemotron-Personas-Vietnam, peft/trl/unsloth | mỗi tải cần chủ dự án duyệt (quy ước 14/09) |
| Môi trường | Ollama 0.40.8; sentence-transformers 3.4.1 (prod) / 5.7.0 (train) / 6.0.1 (eval); GPU rảnh 0 MiB lúc đo; cửa sổ train 05:00–21:00 | mọi hành vi Ollama ghi trong memory đo trên 0.33–0.34 — kiểm lại trước khi trích |

## Chưa kiểm

- Volume Docker của DB heldout và lab còn nguyên không, và DB heldout đang ở trạng thái ctx ON hay
  OFF (không được bật container để xem).
- Cách ghi nhánh 0 vào registry mà `model_registry --check` chấp nhận (xem nhánh 0).
- llama.cpp chuyển e5-large (XLM-R) sang GGUF chạy được trên Ollama 0.40.8: suy từ việc `bge-m3`
  cùng kiến trúc có trên Ollama library, chưa tự làm.
- Ước lượng VRAM/thời gian của C lấy từ spec D2 và tài liệu Unsloth, chưa đo trên máy này.
