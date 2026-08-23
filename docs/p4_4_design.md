# P4-4 — Chỉ mục sparse trong PostgreSQL (thay BM25 in-process) · P4-5 — Chunk visualization

> 📄 **TRẠNG THÁI 23/08/2026 (chiều): đây là BẢN v1 — một trong HAI phương án đang cân
> nhắc, chưa chọn.** Bản này đã qua vòng phản biện đối kháng 5 tác nhân và **không được
> chọn nguyên trạng**, nhưng vẫn giữ nguyên vẹn ở đây để so sánh. Bảng ưu/nhược v1 vs v2,
> năm số phải đo và quy tắc chọn nằm ở `docs/DEVELOPMENT_PLAN.md` **§9d**. Khi hai tài
> liệu mâu thuẫn, **plan thắng**.
>
> **Đọc tài liệu này với 8 đính chính sau** — đây là những chỗ đã biết là sai, và là lý do
> v1 không được chọn nguyên trạng:
>
> 1. `retrieval_tf jsonb` → phải là `int[]` song song với `retrieval_lexemes` (dung lượng **1.90× → 1.06×** corpus trần; bản gốc đo **2.28×** ở cấu hình ship, vượt chính ngưỡng dừng 2× của tài liệu này).
> 2. Bộ lọc ứng viên `retrieval_lexemes && $1` **không lọc**: đo thật kéo trung bình **97.5%** corpus, **59/82** câu kéo 100% (hư từ tiếng Việt gần như phổ quát) ⇒ G8-3 chưa được giải.
> 3. Toán tử `text[] & text[]` **không tồn tại** trong PostgreSQL (`&` giao mảng chỉ có ở extension `intarray`, chỉ cho `int[]`).
> 4. `N` / `df` / `avgdl` lấy từ ba tập hàng khác nhau khi backfill còn dở → điểm BM25 **sai âm thầm**, gate D1 không đủ nhạy để bắt.
> 5. Thiếu `tokenizer_version` cạnh lexeme (⇒ nợ **T16**: ghim `pyvi` đúng version).
> 6. Corpus lab là **27** chunk, không phải 273.
> 7. `top_k` là **15** ở lane nhẹ/CI, không phải 45.
> 8. §12 nói **P4-5 phụ thuộc P4-4** — **sai**: cả 8 cột P4-5 cần đã có sẵn trong `document_chunks`, P4-5 làm được ngay và độc lập.

**Trạng thái ban đầu 23/08/2026: THIẾT KẾ — chưa có dòng code nào.** Tài liệu này là bản
chốt kỹ thuật để máy nặng/máy nhẹ thi công; mọi con số "sau" đều là **giả thuyết cần đo**,
không phải kết quả. Nhật ký thi công sẽ ghi vào `docs/p4_progress.md` như P4-2/P4-3.

Cơ sở: bản audit đường retrieval ngày 23/08 (hội thoại) — mọi khẳng định "hiện tại" dưới
đây đã được xác minh trực tiếp từ code, có trích dẫn file:line.

---

## 0. Vấn đề đang giải (G8) — và những gì P4-4 KHÔNG giải

Hiện trạng đã xác minh:

| Sự thật | Bằng chứng |
| --- | --- |
| Chỉ mục sparse là `BM25Okapi` nằm **trong RAM tiến trình API** | `postgres_bm25_service.py:44,90` |
| **Không token nào được lưu xuống PostgreSQL** — pyvi chạy lại toàn corpus mỗi lần rebuild | `postgres_bm25_service.py:90` |
| Mỗi lần search tốn **một truy vấn fingerprint**; corpus đổi → rebuild O(corpus) chặn ngay câu hỏi đó | `postgres_bm25_service.py:83-92`, `repositories.py:223-248` |
| Chấm điểm quét **toàn corpus** mỗi query (`get_scores` trên mọi chunk) | `postgres_bm25_service.py:115` |
| Mỗi tiến trình một chỉ mục riêng; `invalidate()` **không có caller nào** (code chết) | `postgres_bm25_service.py:79`, `main.py:145` |

Hệ quả: RAM và thời gian rebuild tăng tuyến tính theo corpus; nhiều worker API thì mỗi
worker có thể đang phục vụ một ảnh chụp corpus khác nhau.

**P4-4 KHÔNG giải**: hai câu retrieval còn miss (`p3_khoa_brute_force`,
`p3_refresh_khong_xoay`) — máy nặng đã truy nguyên 21/08: chunk đúng *có* trong ứng viên,
cross-encoder đẩy chunk lân cận lên trên. Đó là việc ở tầng rerank, không phải sparse.
Đừng gắn hai câu đó vào tiêu chí nghiệm thu của P4-4.

---

## 1. Quyết định thiết kế

| Quyết định | Lý do |
| --- | --- |
| Lưu lexeme thành **`text[]` + GIN `array_ops`**, **KHÔNG dùng `tsvector`** | pyvi trả về từ ghép nối bằng `_` (`danh_thiếp`, `tiêu_chuẩn` — xác minh bằng chạy thật). Parser mặc định của Postgres coi `_` là dấu cách và sẽ **tách đôi đúng thứ pyvi vừa ghép**. Mảng text giữ lexeme nguyên khối, không parser nào đụng vào, và vẫn có `&&` (giao) để lọc ứng viên + `@>` (chứa) để đếm DF |
| **Chấm điểm BM25 trong app**, không dùng `ts_rank_cd` | `ts_rank_cd` không có IDF: từ hiếm ("brute-force") và từ phổ biến ("hệ thống") cân nhau. Đổi một thuật toán đã đo (0.9756/0.8581) lấy thứ yếu hơn về nguyên lý là lỗ vốn |
| **DF tính ngay trong truy vấn** cho đúng các từ của câu hỏi — KHÔNG bảng `lexeme_df`, KHÔNG materialized view | DF chỉ cần cho 5–10 từ của câu hỏi, không cần cả từ vựng. Với GIN, `count(*) WHERE lexemes @> ARRAY['x']` là index scan rẻ. Tính tại chỗ ⇒ **đúng theo định nghĩa**, không có hook nào để quên, **không còn rủi ro "DF trôi"** — rủi ro lớn nhất của bản thiết kế nháp đầu tiên biến mất |
| Ghi lexeme/tf/len **cùng transaction với chunk row**, tại `replace_chunks` | `repositories.py:97-104` là **điểm ghi chunk duy nhất** mà cả hai đường index (thread `_run_index` và RQ `index_for_worker`) đều đi qua. Một điểm ghi ⇒ không thể có "chunk active mà chưa có token", và không nhân đôi logic (tránh nới rộng nợ T7) |
| Giữ **nguyên interface** `PostgresBm25Service.search(question, top_k, document_id) -> list[dict]` | Mọi thứ hạ nguồn (RRF, rerank, context builder, citation) chỉ thấy `list[dict]` với cùng field. Không tầng nào khác phải sửa |
| Cờ `rag.sparse_backend: inprocess \| postgres`, **mặc định `inprocess`** cho tới khi eval chứng minh | Đúng bất biến §1 ("thay đổi chất lượng RAG chỉ thành mặc định sau eval") và đúng khuôn P4-2/P4-3: cờ + override theo máy + resolver `from_config` |
| pyvi vẫn là bộ tách từ duy nhất, dùng **cùng hàm** ở index-time và query-time | `tokenize_vietnamese` (`vi_tokenizer.py:6`). Hai phía lệch tokenizer là lỗi câm nguy hiểm nhất của mọi hệ sparse |

---

## 2. Schema (migration additive `20260823_26`)

Ba cột trên `document_chunks` + một index:

| Cột | Kiểu | Ý nghĩa |
| --- | --- | --- |
| `retrieval_lexemes` | `text[]` NULL | lexeme pyvi của `combined_retrieval_text(retrieval_context, content)`, đã lowercase, **có lặp bị loại** (chỉ để lọc/đếm DF) |
| `retrieval_tf` | `jsonb` NULL | `{lexeme: tần suất}` — tần suất trong chunk, dùng để chấm điểm |
| `retrieval_len` | `integer` NULL | tổng số token (kể cả lặp) — mẫu số `b`-normalization của BM25 |

```
CREATE INDEX ix_document_chunks_retrieval_lexemes
    ON document_chunks USING GIN (retrieval_lexemes array_ops);
```

- **NULL = chunk chưa được index sparse** (bản cũ trước migration). Truy vấn phải coi NULL
  là "chưa sẵn sàng" và **báo được ra ngoài**, không im lặng bỏ qua — nếu không, backfill
  thiếu sẽ biểu hiện thành "tự nhiên tìm kém đi" mà không ai biết.
- `downgrade()` drop index + 3 cột. Không đụng dữ liệu nào khác.
- Chi phí dung lượng: **CHƯA ĐO** — phải đo thật trên corpus 273 chunk của DB lab trước khi
  chốt (ước lượng thô 1–1.5× kích thước text, cần số thật).

---

## 3. Đường ghi (index time)

```
chunks (đã có retrieval_context từ P4-2)
  → với mỗi chunk:  tokens = tokenize_vietnamese(combined_retrieval_text(ctx, content))
                    lexemes = sorted(set(tokens))
                    tf      = Counter(tokens)
                    len     = len(tokens)
  → DocumentChunk(..., retrieval_lexemes=lexemes, retrieval_tf=tf, retrieval_len=len)
  → session.add_all  (CÙNG transaction với chunk row — repositories.py:104)
```

- **Không lời gọi model nào** — pyvi là hàm cục bộ ⇒ bất biến "ngân sách inference" không bị
  chạm, và bất biến "không transaction ôm lời gọi model" cũng không bị chạm.
- Chi phí thêm ở index-time: pyvi mili-giây/chunk — không đáng kể so với 3–7 giây/chunk
  sinh context của P4-2 (số đo thật 21/08).
- **Activate/supersede/xóa không cần làm gì thêm**: truy vấn đọc đã join
  `documents.active_version_id` như `repositories.py:204` đang làm, nên version cũ tự động
  ngừng được tìm thấy.

---

## 4. Đường đọc (query time)

```
query → tokenize_vietnamese → terms (5–10 lexeme)
      → SQL (một round-trip, 3 CTE):
          active     : chunk của active version, lọc document scope nếu có
          candidates : active WHERE retrieval_lexemes && :terms        ← GIN
          df         : với mỗi t ∈ terms, count(*) FROM active WHERE lexemes @> ARRAY[t]  ← GIN
          stats      : count(*) N, avg(retrieval_len) avgdl FROM active
      → app: BM25(tf, len, df, N, avgdl) trên CHỈ candidates
      → sort desc → top_k (45)
```

Công thức chấm (mỗi từ `t` của câu hỏi, mỗi ứng viên `d`):

```
idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))          ← luôn > 0
score(d) = Σ_t  idf(t) · ( tf(t,d)·(k1+1) ) / ( tf(t,d) + k1·(1 - b + b·len(d)/avgdl) )
k1 = 1.5, b = 0.75      (giữ đúng tham số rank_bm25 đang chạy)
```

**Giới hạn ứng viên**: nếu `candidates` quá lớn ở corpus lớn, cắt sơ bộ bằng số từ khớp
(`cardinality(lexemes & terms)`) trước khi chấm — ngưỡng cắt phải **log ra** khi có hiệu
lực, không được cắt im lặng.

---

## 5. Parity với `rank_bm25` — điều KHÔNG đảm bảo được

Phải nói thẳng: **bản mới không thể trùng điểm tuyệt đối với `rank_bm25`.**

`BM25Okapi._calc_idf` (`.venv/Lib/site-packages/rank_bm25.py:85-98`) dùng
`idf = ln(N - df + 0.5) - ln(df + 0.5)` — **có thể âm** khi từ xuất hiện ở hơn nửa corpus —
rồi thay mọi IDF âm bằng sàn `epsilon × average_idf`, với `average_idf` là **trung bình IDF
trên toàn bộ từ vựng**. Đại lượng đó là thống kê toàn corpus, không tính được từ một truy
vấn theo-từ-của-câu-hỏi.

Quyết định: **dùng IDF dạng luôn dương** (công thức mục 4, kiểu Lucene), **bỏ epsilon**, và
**đo lại D1** thay vì giả vờ parity.

Hệ quả kéo theo — **nhánh fallback token-overlap** (`postgres_bm25_service.py:131-141`) tồn
tại chỉ vì `rank_bm25` cho điểm 0/âm khi từ có mặt ở mọi chunk (corpus nhỏ). Với IDF luôn
dương, mọi chunk có ít nhất một từ khớp đều có điểm > 0 ⇒ **nhánh này trở nên vô nghĩa và
được bỏ ở backend mới** (backend `inprocess` giữ nguyên để còn so sánh).

Đây là thay đổi hành vi có chủ đích, phải ghi vào `p4_progress.md` và CHANGELOG khi làm.

---

## 6. Cờ và lộ trình bật

| Bước | Nội dung |
| --- | --- |
| 1 | Code + migration + backfill script, cờ `inprocess` (mặc định) — **không ai bị ảnh hưởng** |
| 2 | Backfill toàn bộ chunk hiện có; xác nhận **0 chunk active có `retrieval_lexemes IS NULL`** |
| 3 | Đo D1 với `sparse_backend: postgres` trên **DB lab** (máy nhẹ chạy được bản retrieval-only) |
| 4 | Đạt ngưỡng (mục 7) → đổi mặc định trong `models.yaml`, giữ `inprocess` làm đường lui **một minor version** |
| 5 | Sau một minor version không sự cố → gỡ backend cũ + `rank_bm25` khỏi requirements |

Override theo máy: `RAG_SPARSE_BACKEND` trong `.env`, cùng khuôn resolver
`from_config(..., enabled_override=...)` như `ChunkContextService`/`RerankerService`/
`InjectionDefense` — một idiom duy nhất cho mọi cờ theo máy (`docs/machine_split.md`).

---

## 7. Kế hoạch đo và ngưỡng nghiệm thu

Chốt **trước** khi đo (không sửa sau khi thấy số):

| Phép đo | Ngưỡng đạt |
| --- | --- |
| D1 retrieval-only, `sparse_backend=postgres` vs `inprocess`, **cùng máy cùng corpus** | `recall_at_k`, `mrr`, `doc_hit_rate` **không tụt quá 0.02** ở cả ba |
| Latency `/rag/search` p50 / p95 | không tăng quá **50 ms p50** ở corpus hiện tại |
| Dung lượng DB | ghi lại số thật; > 2× kích thước text ⇒ dừng, xem lại thiết kế |
| Chunk chưa backfill | **0** chunk active có `retrieval_lexemes IS NULL` |
| Rebuild | không còn khái niệm rebuild; xác nhận **0 truy vấn fingerprint** trong log một phiên hỏi |

Nơi đo: **DB lab** (`local_ai_core_lab_20260821` + collection `documents_lab`) theo cảnh báo
đo lường trong `docs/machine_split.md` — DB vận hành có `local_ai_core_baseline.txt` làm
lệch `xa_*`, không dùng làm thước.

Đặc biệt: **đây là mục P4 đầu tiên mà máy nhẹ tự đo được** (retrieval-only chỉ cần embedding
0.6b), và **CI cũng gate được trọn vẹn** bằng `rag_multidoc_baseline_bare.json`. Máy nặng chỉ
xác nhận lần cuối trên cấu hình ship (contextual + rerank).

---

## 8. Test bắt buộc

**Mới:**

| Test | Nội dung |
| --- | --- |
| tokenize → tf/len | `Counter` đúng, `len` đếm cả lặp, lexeme đã khử lặp |
| chấm điểm | so với công thức tính tay trên corpus 3 chunk dựng sẵn (số cứng, không dùng model) |
| **parity hai backend** | trên corpus tổng hợp, `inprocess` và `postgres` phải trả **cùng tập top-k** (không đòi cùng điểm — mục 5) |
| document scope | lọc theo `document_id` / `document_ids` / list rỗng |
| version | version mới tìm thấy, version cũ superseded thì không |
| xóa tài liệu | chunk của tài liệu đã xóa không còn được trả |
| **chunk chưa backfill** | `retrieval_lexemes IS NULL` không được biến thành "im lặng biến mất" — phải đếm và báo |

**Phải sửa:** `test_postgres_retrieval_preparation.py:67,73,79` ghim `rebuild_count == 1/2/3`
— khái niệm này biến mất ở backend mới. Đây là **test duy nhất** trong suite bị phá bởi
P4-4 (các test khác chỉ dùng `search()` qua interface). Viết lại thành: version mới có
token và tìm được, version cũ không.

---

## 9. Rủi ro và đối sách

| Rủi ro | Mức | Đối sách |
| --- | --- | --- |
| Không parity điểm với `rank_bm25` | **Cao — chấp nhận có chủ đích** | Nêu rõ ở mục 5, đo lại D1, ghi baseline mới nếu lệch trong ngưỡng nhưng khác số |
| Backfill thiếu → chunk "biến mất" khỏi sparse | Cao nếu quên | NULL là trạng thái phát hiện được; test riêng; script backfill idempotent chạy lại được |
| Truy vấn SQL nặng làm chậm p95 | Trung | Ngưỡng latency ở mục 7; cờ lùi về `inprocess` |
| Ở corpus nhỏ, bản mới **chậm hơn** bản RAM | Trung — dự kiến xảy ra | Nói trước trong báo cáo: P4-4 mua trần mở rộng + tính đúng đắn, không mua tốc độ ở quy mô hiện tại |
| Hai đường index ghi token khác nhau | Thấp | Điểm ghi duy nhất `replace_chunks`; test đi qua cả đường thread lẫn RQ |
| Quên dựng lại chỉ mục sau restore | **Thấp hơn hiện tại** | Token nằm **trong bản dump Postgres** ⇒ tự khôi phục. Chỉ Qdrant cần `rebuild_qdrant` (bài học 22/08) |

---

## 10. Điều KHÔNG đổi

Dense (embed → Qdrant 180 → đối chiếu PostgreSQL → 45), RRF (k=60, dedup theo
`document_id/version_id/chunk_id`), cross-encoder (15 → 5, chấm trên `content` trần),
context builder, prompt, delimiter D5, grounding D3a, `RagSource` (không thêm/bớt field ⇒
frontend, bot Discord, harness eval **không phải sửa gì**), và mọi bất biến §1.

---

## 11. Phân lane thi công

| Phần | Lane | Ghi chú |
| --- | --- | --- |
| Migration, ghi lexeme/tf/len, backend `postgres`, backfill script, toàn bộ test | **NHẸ** | Không cần model sinh, không cần GPU |
| Đo D1 retrieval-only so `bare` baseline | **NHẸ** | Máy nhẹ tự làm được (embedding 0.6b) |
| Đo trên cấu hình ship (contextual + rerank) + latency p50/p95 + quyết định đổi mặc định | **NẶNG** | DB lab, không đụng production |

Thứ tự: nhẹ (1–3) → nặng (4) → nhẹ (gỡ backend cũ sau một minor version).

---

## 12. P4-5 — Chunk visualization (phụ thuộc P4-4)

Học từ RAGFlow: cho người dùng **tự chẩn đoán "vì sao trả lời sai"**.

- **Chỉ đọc, không đụng pipeline retrieval.** Thêm endpoint liệt kê chunk của một version +
  trang UI hiển thị: nội dung, `page_start/end`, `heading_path`, `section_title`,
  `block_type`, `extraction_method`, số token, và `retrieval_context` (P4-2).
- **Vì sao đi sau P4-4**: hôm nay token chỉ tồn tại trong RAM giữa hai lần rebuild ⇒ không
  có gì để hiển thị. Sau P4-4, `retrieval_lexemes`/`retrieval_tf` nằm trong DB ⇒ màn hình
  chunk lần đầu trả lời được **"từ nào của câu hỏi khớp chunk này, đóng góp bao nhiêu điểm"**.
  Đó là giá trị thật của P4-5, và nó chỉ tồn tại nhờ P4-4.
- Nghiệm thu: mở một tài liệu trong UI, thấy đủ chunk theo thứ tự, đánh dấu được chunk kém
  (rỗng/quá ngắn/thiếu context), và với một câu hỏi cụ thể thấy được từ khớp.
- Bảo mật: endpoint đọc ⇒ đi qua `require_api_key_for_read`; member/admin theo RBAC P3-1.

---

## 13. Ghi chú: dòng P4-4 trong plan đã lỗi thời

`docs/DEVELOPMENT_PLAN.md` ghi P4-4 là *"Postgres FTS thay BM25 in-process (tsvector + GIN +
unaccent)"* và §9b ghi *"P4-4 FTS + pyvi"*. Audit 23/08 cho thấy: **pyvi đã dùng từ lâu**
(`vi_tokenizer.py:8`, gọi ở `postgres_bm25_service.py:90,114`), nên vế "thêm pyvi" là mô tả
sai hiện trạng; và `tsvector` là lựa chọn sai kỹ thuật cho lexeme có `_` (mục 1). Dòng plan
sẽ được sửa để trỏ vào tài liệu này.
