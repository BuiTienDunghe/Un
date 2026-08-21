# D1 — Bộ eval retrieval đa tài liệu

Gỡ khoảng trống G7 (bộ eval 1 tài liệu đã bão hòa 100%): bộ eval mới chạy trên
**toàn corpus, không lọc tài liệu** — chọn đúng tài liệu giữa các ứng viên chính
là năng lực được đo. Đây là thước đo cho mọi thí nghiệm P4 và các mục Track D
sau này (plan §4, §9b).

## Thành phần

| Phần | Vị trí |
| --- | --- |
| Corpus 5 tài liệu thật (snapshot bất biến) | `data/evaluation/fixtures/multidoc/` |
| Bộ câu hỏi (JSONL, tiếng Việt, nhóm `single` + `cross`) | `data/evaluation/rag_multidoc_eval.jsonl` |
| Baseline cấu hình đang ship (contextual BẬT) | `data/evaluation/rag_multidoc_baseline.json` |
| Baseline bản trần cho gate CI (contextual TẮT) | `data/evaluation/rag_multidoc_baseline_bare.json` |
| Endpoint retrieval-only | `POST /rag/search` (đúng nguồn mà `/rag/chat` sẽ trích, không gọi model sinh) |
| Harness | `backend/scripts/evaluate_rag.py --multidoc-dataset …` |
| Gate CI | job `retrieval-eval` trong `.github/workflows/ci.yml` |

Corpus là **snapshot**: sửa tài liệu gốc trong `docs/` không làm trôi điểm eval.
Muốn đổi corpus thì thay fixture + sinh lại bộ câu hỏi + đo lại baseline (một
thay đổi có chủ đích, thấy được trong diff).

## Cách chấm

Mỗi câu hỏi khai báo `expected_docs` (tên fixture chứa bằng chứng) và
`expected_source_terms` (chuỗi **nguyên văn** từ tài liệu, cùng nằm trong một
đoạn). Chuỗi phải nằm trong **phần thân** văn bản: parser tách heading khỏi
thân khi chunk, nên chuỗi lấy từ tiêu đề sẽ không bao giờ khớp — mọi câu mới
thêm cần đối chiếu với nội dung chunk thực (bảng `document_chunks`), không chỉ
với file gốc. Một kết quả retrieval **trúng** khi chunk trả về thuộc đúng tài liệu
mong đợi **và** chứa nguyên văn tất cả các chuỗi. Số liệu:

- `recall_at_k` — tỷ lệ câu có ít nhất một chunk trúng trong top-5
- `mrr` — 1/hạng của chunk trúng đầu tiên, trung bình
- `doc_hit_rate` — tỷ lệ câu mà chunk hạng 1 thuộc đúng tài liệu
- nhóm `cross` được tách riêng trong `by_group` (câu bắc cầu/nhiễu giữa tài liệu)

Chế độ `--retrieval-only` chỉ cần **model embedding** (`qwen3-embedding:0.6b`),
không cần model sinh — đúng bất biến ngân sách inference và chạy được trong CI
không GPU. Bỏ cờ này để đo thêm `answer_pass_rate` bằng model sinh thật
(chỉ nên đo trên máy đích, cấu hình model cuối cùng).

## Baseline hiện hành (21/08/2026) — **đổi vì P4-3**

> **Baseline được ghi lại lần thứ hai trong ngày, sau khi P4-3 reranker bật mặc
> định** (lần trước là vì P4-2 contextual retrieval — bảng ngay dưới). Đây là
> thay đổi có chủ đích, không phải trôi số: cờ `rag.reranker.enabled` chuyển
> sang `true` sau khi thí nghiệm đạt cả ba điều kiện đã chốt trước khi đo, nên
> mọi phép so sánh về sau phải lấy mốc mới. Số liệu, ngưỡng, chi phí độ trễ và
> so sánh `candidate_limit`: `docs/p4_progress.md`.
>
> Cấu hình đo: contextual retrieval ON + reranker ON (`candidate_limit` 15,
> `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`), embedding `qwen3-embedding:0.6b`,
> trên máy nặng `PC-dungbt` với `torch 2.9.1+cu128` — **không** phải trong CI;
> xem lưu ý ở cuối mục. Máy đo lại baseline này phải có GPU và bản CUDA của
> torch: trên CPU chất lượng giống hệt nhưng độ trễ khác 28×, và baseline chỉ
> ghi chất lượng nên số sẽ trùng — đừng lấy đó làm bằng chứng cấu hình đúng.

| Metric | Toàn bộ (82) | single (70) | cross (12) |
| --- | --- | --- | --- |
| recall@5 | **0.9756** | 0.9714 | 1.0000 |
| MRR | **0.8581** | 0.8576 | 0.8611 |
| doc_hit_rate | **0.8537** | 0.8571 | 0.8333 |

Còn 2 câu miss (trước P4-3 là 7): `p3_khoa_brute_force`, `p3_refresh_khong_xoay`
— cả hai vẫn trúng đúng tài liệu, chỉ trượt chunk mang nguyên văn; headroom cho
P4-4 (Postgres FTS + pyvi).

**Baseline trước đó (P4-2, contextual ON + reranker OFF)** — mốc mà P4-3 được đo
so với:

| Metric | Toàn bộ (82) | single (70) | cross (12) |
| --- | --- | --- | --- |
| recall@5 | 0.9146 | 0.9000 | 1.0000 |
| MRR | 0.7967 | 0.7964 | 0.7986 |
| doc_hit_rate | 0.8415 | 0.8571 | 0.7500 |

Ở mốc này còn 7 câu miss (trước P4-2 là 11); P4-3 gỡ trọn cả 7. Không chỉnh
dataset để làm đẹp số ở bất kỳ mốc nào: baseline là hiện trạng thật.

**Baseline trước đó (nền bản trần, để đối chiếu lịch sử)** — đo bởi chính job CI
`retrieval-eval` (run #15 trên main, commit `2f0ddfa`), cùng model
`qwen3-embedding:0.6b`:

| Metric | Toàn bộ (82) | single (70) | cross (12) |
| --- | --- | --- | --- |
| recall@5 | 0.8659 | 0.8857 | 0.7500 |
| MRR | 0.7341 | 0.7588 | 0.5903 |
| doc_hit_rate | 0.7683 | 0.8000 | 0.5833 |

**Lưu ý về môi trường đo:** baseline cũ ghi trong CI, baseline mới ghi trên máy
nặng — vì P4-2 cần model sinh để index, thứ CI không có. Cả hai dùng cùng model
embedding nên gate vẫn so được, nhưng nếu job `retrieval-eval` báo lệch có hệ
thống (không phải một câu lẻ) thì nghi ngờ khác biệt môi trường trước khi nghi
ngờ thoái lui, và đo lại một lượt trên máy nặng để phân định.

## Ghi lại baseline (chỉ khi đổi model embedding hoặc corpus — plan §9a.6)

```powershell
# API + Ollama đang chạy (launcher). Từ backend/:
python -m scripts.evaluate_rag --multidoc-dataset ..\data\evaluation\rag_multidoc_eval.jsonl `
  --retrieval-only `
  --write-baseline ..\data\evaluation\rag_multidoc_baseline.json
# rồi commit file baseline.
```

Baseline ghi kèm tên model embedding; gate từ chối so sánh nếu model hiện tại
khác model lúc ghi (đổi model là phải đo lại — đúng plan §9a.6).

## Gate trong CI — đo **bản trần**, gate theo baseline trần

Job `retrieval-eval` dựng Postgres + Redis + Qdrant + Ollama (chỉ pull model
embedding 0.6b, có cache), chạy API thật, bootstrap corpus rồi chấm bộ câu hỏi:

- **Chưa có baseline** trong repo → chỉ báo cáo số liệu, job xanh (để hạ tầng
  eval vào được main trước khi máy đích ghi baseline).
- **Có baseline** → tụt quá `--tolerance` (mặc định 0.02, "không tụt quá 2
  điểm" — plan P4-1) ở `recall_at_k` hoặc `mrr` là job đỏ.

**Từ P4-2, CI đo một cấu hình khác với cấu hình đang ship**, và P4-3 làm khoảng
cách đó rộng thêm. Mặc định của hệ thống là contextual retrieval BẬT (cần model
sinh lúc *index* — 6.6GB và 27 lượt sinh trên CPU, quá sức một job 30 phút)
**và** reranker BẬT (cần extra `[rerank]`, tức PyTorch, mà job này không cài —
và trên CPU runner sẽ đắt thêm ~1 giây mỗi câu trong 82 câu). Nên job có một
bước tắt **cả hai** cờ tường minh rồi gate bản trần theo
`rag_multidoc_baseline_bare.json`. Bước đó fail nếu không tìm thấy khoá, nên đổi
tên hay di chuyển cờ sẽ làm job đỏ chứ không lặng lẽ đo sai cấu hình:

| Tệp baseline | Cấu hình | Đo ở đâu | Ai dùng |
| --- | --- | --- | --- |
| `rag_multidoc_baseline.json` | contextual BẬT + reranker BẬT (mặc định đang ship) | máy nặng, có GPU | mốc chất lượng của sản phẩm; thí nghiệm P4 sau này |
| `rag_multidoc_baseline_bare.json` | cả hai TẮT | CI | gate chặn thoái lui embedding + BM25 + RRF |

Tách đôi vì một con số chỉ có nghĩa khi so cùng-điều-kiện. CI vẫn bảo vệ được
đúng phần nó chạy được — tầng lấy ứng viên; phần contextual và rerank do máy
nặng đo và ghi. Khi đổi model embedding hoặc corpus thì **cả hai** phải đo lại —
bản trần bằng cách tắt cả hai cờ trong `models.yaml` rồi re-index, bản đầy đủ
theo runbook P4-2 (re-index) rồi P4-3 (không cần re-index).

## Quan hệ với bộ eval cũ

Bộ 47 câu một-tài-liệu (`rag_eval.jsonl`) và bộ hội thoại condense
(`rag_conversation_eval.jsonl`) giữ nguyên, vẫn chạy được như trước — chúng đo
đường `/rag/chat` đầy đủ trên một tài liệu. Bộ multidoc bổ sung chiều đo mới,
không thay thế.
