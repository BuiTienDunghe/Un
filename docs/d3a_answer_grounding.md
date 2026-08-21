# D3a — Self-check bám nguồn cho câu trả lời RAG (không dùng model)

**Trạng thái 21/08/2026: ✅ ĐÓNG.** Đo hai lần trên máy nặng `PC-dungbt` (trước và
sau khi sửa cap xuyên ngữ), đối chiếu tay hai vòng (10 + 8 câu): **cả hai vòng đều
0 dương tính giả về độ tin cậy**, và sau sửa các nhãn thấp đa số nói đúng bản chất
("không chấm được vì khác ngôn ngữ" thay vì "bịa"). Baseline faithfulness hiện hành:
`data/evaluation/rag_multidoc_grounding_baseline.json` (grounding_rate **0.9390**,
0 ungrounded, `language_mismatch` 3). Quyết định hành vi: **giữ "chỉ báo"** — lý do
bằng số ở mục "Đo lại" cuối tài liệu.
Mục Track D3a trong `docs/DEVELOPMENT_PLAN.md`; phân lane theo `docs/machine_split.md`.

## Nó là gì

Một bộ kiểm tra **0 lời gọi model** (bất biến ngân sách inference, plan §1) chạy ngay
sau khi câu trả lời RAG sinh xong: từng câu của câu trả lời được đối chiếu với **văn
bản trần (`content`) của các chunk đã trích** — đúng thứ người dùng mở ra xem được,
không bao giờ dùng `retrieval_context` sinh bởi P4-2. Tư duy lấy từ guard memory P2-1b
(`discord_memory_guard.py`): fold dấu, content-word overlap, bằng chứng nguyên văn.

| Thành phần | Vị trí |
| --- | --- |
| Bộ chấm | `backend/app/services/answer_grounding.py` |
| Schema báo cáo | `GroundingReport` trong `backend/app/schemas/rag_schema.py` |
| Điểm gắn | `POST /rag/chat`: field `grounding` (response thường) và sự kiện SSE `done` (stream) |
| Web UI | chip "bám nguồn x%" ở footer tin nhắn (tooltip liệt kê câu chưa đủ nguồn) |
| Harness | `evaluate_rag.py` chế độ full (không `--retrieval-only`): `grounding` summary + `grounding_rate` |
| Test | `backend/tests/test_answer_grounding.py` (10 test, không model) |

**Chỉ báo cáo.** Không chặn, không sửa câu trả lời — quyết định đó cần số đo thật ở dưới.

## Cách chấm (và lý do từng ngưỡng)

| Bước | Quy tắc | Lý do |
| --- | --- | --- |
| Tách câu | theo `.?!…` và xuống dòng; bỏ bullet/số thứ tự/`#` | câu trả lời Markdown |
| Bỏ qua | câu < 4 content-word, câu xã giao (chào, cảm ơn, "tóm lại") | không phải mệnh đề cần nguồn; đếm vào sẽ chỉ thêm nhiễu |
| `grounded` | ≥ 60% content-word của câu có trong nguồn, **hoặc** có chuỗi ≥ 4 content-word liên tiếp nguyên văn trong nguồn | 0.6 = câu chủ yếu dùng từ vựng của nguồn; chuỗi nguyên văn là "evidence verbatim" của guard memory |
| `weak` | 34% ≤ overlap < 60% | 0.34 là sàn đo được của guard memory (benchmark P2-1b) |
| `ungrounded` | overlap < 34% | dưới sàn: câu gần như không lấy gì từ nguồn |
| Xuyên ngữ | câu khác ngôn ngữ với **nguồn khớp nhất của chính câu đó** (không phải cả pool; hòa điểm mà có nguồn khác ngôn ngữ thì tính là khác) bị **trần ở `weak`** + cờ `language_mismatch`; câu không trùng từ nào với nguồn nào chỉ được cap khi **mọi** nguồn đều khác ngôn ngữ | kiểm tra từ vựng không nhìn xuyên ngôn ngữ được (điểm mù T12): kết luận đúng là "không chấm được", không phải "bịa". Sửa 21/08 sau đối chiếu tay: pool trộn Việt+Anh từng làm cap không bao giờ bật |
| Nhãn tổng | có câu `ungrounded` → `ungrounded`; ≥ 80% câu `grounded` → `grounded`; còn lại `weak`; không có câu nào chấm được → `unjudged` | một câu bịa là đủ để cả câu trả lời không đáng tin |
| Không có nguồn | mọi câu `ungrounded` | không nguồn thì không gì bám được, bất kể ngôn ngữ |

Điểm mù **có chủ đích**: diễn giải bằng từ khác với nguồn bị chấm thấp hơn thực tế.
Hướng thiết kế là **báo thiếu còn hơn chứng nhận nhầm** — `weak` là phía an toàn.

## Handoff cho máy MẠNH — đo `grounding_rate` trên bộ 82 câu

Chế độ full gọi model sinh cho 82 câu (lane nặng). Chạy khi API + Ollama đang chạy,
từ `backend/`:

```powershell
python -m scripts.evaluate_rag --multidoc-dataset ..\data\evaluation\rag_multidoc_eval.jsonl
# (KHÔNG --retrieval-only, KHÔNG --write-baseline: baseline D1 là retrieval-only, không đụng)
```

Báo cáo in `grounding` = `{graded, grounding_rate, ungrounded_rate, language_mismatch, labels}`
và liệt kê id các câu `ungrounded`; file kết quả có `grounding_label`, `grounded_ratio`,
`ungrounded_sentences` theo từng câu trong `data/evaluation/results/rag-multidoc-*.json`.

### Tiêu chí nghiệm thu D3a

1. **Đối chiếu tay 10 câu** (bắt buộc — kiểm tra guard không báo sai chiều): lấy 5 câu
   bị gắn `ungrounded` và 5 câu `grounded`, đọc câu trả lời cạnh nguồn và tự chấm.
   Đạt khi: không câu `grounded` nào chứa mệnh đề bịa rõ ràng (**không dương tính giả
   về độ tin cậy**), và ≥ 3/5 câu `ungrounded` thật sự có ý không có trong nguồn.
   Nếu đa số `ungrounded` chỉ là diễn giải đúng bằng từ khác → ngưỡng quá gắt, ghi lại
   và đề xuất hạ `GROUNDED_MINIMUM`/`WEAK_MINIMUM` kèm số liệu (không sửa ngay trong
   cùng lần đo).
2. Ghi `grounding_rate`, `ungrounded_rate`, phân phối nhãn, `language_mismatch` vào
   bảng dưới — đây là **baseline faithfulness** đầu tiên của dự án, thước đo cho
   mọi thay đổi prompt/model trả lời về sau.
3. Nhận định ngắn: các câu `ungrounded` rơi vào nhóm nào (single/cross), có trùng
   với 7 câu retrieval còn miss không (bịa vì không tìm thấy nguồn, hay bịa dù có nguồn).

## Kết quả đo (21/08/2026, máy nặng `PC-dungbt`, cấu hình ship: contextual ON + reranker ON)

Chạy full-mode trên 82 câu, `qwen3.5:9b` sinh + `qwen3-embedding:0.6b` embedding;
retrieval khớp baseline P4-3 từng con số (0.9756 / 0.8581 / 0.8537) — cùng-điều-kiện.

| Metric | Giá trị | Ghi chú |
| --- | --- | --- |
| graded (câu có câu trả lời) | **82/82** | không câu nào `unjudged` |
| grounding_rate | **0.9390** (77/82) | tỉ lệ nhãn tổng `grounded` |
| ungrounded_rate | **0.0122** (1/82) | `xd_point_index_version_cu_bi_bo_qua` |
| labels | 77 grounded / 4 weak / 1 ungrounded / 0 unjudged | 4 weak: `ca_ai_duoc_dung_sqlite3`, `ca_lam_moi_sau_phase`, `vi_bat_backend_postgres`, `vi_chuyen_sang_rq` |
| language_mismatch | **0** | nhưng xem điểm mù pool trộn ngôn ngữ ở dưới — 0 này là *thiếu nhạy*, không phải *sạch* |
| answer_pass_rate | 0.9390 (77/82) | trùng số với grounding_rate là **trùng hợp**: hai chiều lệch 5-5 bù nhau (bảng phân tích dưới) |
| Đối chiếu tay 10 câu | **0 dương tính giả về độ tin cậy** (tiêu chí chính ✅); nhãn thấp: 1/3 báo đúng, 2/3 báo oan kiểu xuyên ngữ (tiêu chí phụ ✗) | bảng đầy đủ dưới |

### Đối chiếu tay 10 câu (bắt buộc)

Per-case của run không lưu nguyên văn câu trả lời, mà re-ask sinh câu trả lời khác
(temperature 0.4) — nên mỗi câu được **gọi lại `/rag/chat` một lần** và người chấm
đối chiếu *câu trả lời + nhãn máy của chính lần gọi đó* (cặp tự nhất quán); nhãn của
run chỉ dùng để chọn mẫu. Hệ quả trung thực: 2/4 câu `weak` của run quay lại
`grounded` ở lần gọi mới (không xét vào nhóm nhãn-thấp nữa), nhóm nhãn thấp fresh còn
3 câu.

| # | id | nhãn run | nhãn máy (lần gọi chấm) | kết luận người | khớp? | ghi chú |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | br_backup_thu_cong | grounded | grounded | có nguồn | ✅ | lệnh `backup_worker --once` nguyên văn Source 5 |
| 2 | br_chu_ky_backup | grounded | grounded | có nguồn | ✅ | "24 giờ / `storage.backup_interval_hours`" nguyên văn bảng Source 1 |
| 3 | br_db_dien_tap | grounded | grounded | có nguồn | ✅ | `local_ai_restore_drill` + lệnh CREATE nguyên văn |
| 4 | br_doi_ten_db_hong | grounded | grounded | có nguồn, **kèm gloss suy diễn** | ⚠️ | lý do thật ("dữ liệu cứu được") không nằm trong chunk trích; model tự bù giải thích ("bảo toàn bằng chứng", "giúp phân biệt DB") — không bịa *sự kiện* nào, nhưng câu trộn nửa-verbatim nửa-suy-diễn được verbatim-run 4 từ đưa lên grounded |
| 5 | br_ghi_ket_qua_dien_tap | grounded | grounded | có nguồn | ✅ | `docs/phase6_operations.md` nguyên văn |
| 6 | xd_point_index_version_cu_bi_bo_qua | ungrounded | ungrounded (ratio 0.333; câu 0.19) | **CÓ nguồn** — dịch Việt trung thành từ nguồn tiếng Anh (`current_architecture.md`: "Cleanup planning and execution also exclude legacy Qdrant points; there is no legacy-qdrant cleanup domain") | ❌ máy báo oan | cờ `language_mismatch` KHÔNG bật: pool 5 nguồn trộn Việt+Anh → `looks_vietnamese(pool)=True` → câu Việt "cùng ngôn ngữ pool" → không cap, dù chunk bằng chứng là tiếng Anh |
| 7 | ca_ai_duoc_dung_sqlite3 | weak | grounded (1.0) | có nguồn | ✅ | dịch EN→VI nhưng thuật ngữ (CLIs, migration, archive path, sqlite3) giữ nguyên → overlap đủ |
| 8 | ca_lam_moi_sau_phase | weak | weak (câu 0.455) | **có mệnh đề không nguồn thật** | ✅ | trả lời "Phase 1 và P1-1..P1-3" — nguồn thật ghi "refreshed after **P0** and P1-1..P1-3", và chunk chứa câu đó không nằm trong nguồn trích |
| 9 | vi_bat_backend_postgres | weak | grounded (1.0) | có nguồn | ✅ | `DOCUMENT_DATABASE_BACKEND=postgres` + `DATABASE_URL` nguyên văn |
| 10 | vi_chuyen_sang_rq | weak | weak (câu 0.542) | **CÓ nguồn** — dịch trung thành "run in separate RQ worker processes… semantics are unchanged" | ❌ máy quá gắt | cùng kiểu điểm mù xuyên ngữ như #6, mức nhẹ hơn |

**Chấm theo tiêu chí đã chốt:**

1. **Dương tính giả về độ tin cậy = 0 ✅** — 7 câu máy chấm `grounded` (fresh) không
   câu nào chứa mệnh đề bịa *sự kiện* (số, tên, lệnh, hành vi sai). Một caveat ghi
   thẳng: #4 chứa *gloss suy diễn giải thích* không có trong chunk trích — đúng kiểu
   câu mà quy tắc verbatim-run 4 từ có thể "chứng nhận nhầm" khi câu trộn nửa trích
   nửa thêm. Chưa phải bịa sự kiện, nhưng là hồ sơ theo dõi cho lần tinh chỉnh sau.
2. **≥3/5 nhãn thấp thật sự có ý ngoài nguồn: ✗ KHÔNG ĐẠT trên mẫu này** — nhóm nhãn
   thấp fresh chỉ còn 3 câu (2 câu weak của run quay lại grounded khi re-ask), trong
   đó 1/3 báo đúng (#8), 2/3 báo oan (#6, #10) — và **cả hai câu oan cùng một kiểu**:
   nguồn bằng chứng là tiếng Anh, câu trả lời dịch sang tiếng Việt, overlap từ vựng
   thấp một cách *chính đáng* (0.19–0.54).

### Chẩn đoán: không phải ngưỡng — là cách phát hiện ngôn ngữ

Runbook dặn "đa số ungrounded chỉ là diễn giải đúng → ghi *ngưỡng quá gắt* + đề xuất
ngưỡng mới". Số đo nói khác một chút: **hạ `GROUNDED_MINIMUM`/`WEAK_MINIMUM` không
sửa được lỗi này.** Bằng chứng: #7 và #9 cũng dịch EN→VI mà đạt ratio 1.0 (thuật ngữ
kỹ thuật giữ nguyên qua bản dịch), còn #6/#10 là văn xuôi thuần → overlap 0.19–0.54;
không tồn tại một ngưỡng từ vựng nào tách được "dịch trung thành" khỏi "bịa" khi câu
và bằng chứng khác ngôn ngữ. Lỗi nằm ở **cap xuyên ngữ đo theo cả pool nguồn**
(`looks_vietnamese(" ".join(texts))`): pool trộn Việt+Anh bị coi là "tiếng Việt" nên
câu Việt không bao giờ được cap, kể cả khi chunk bằng chứng thật là tiếng Anh.

**Đề xuất (KHÔNG sửa trong lần đo này, đúng ràng buộc):** thay cap theo-pool bằng cap
**theo-nguồn-khớp-nhất** — khi câu bị chấm `ungrounded` mà nguồn có overlap cao nhất
với nó khác ngôn ngữ với câu, trần ở `weak` + `language_mismatch` (đúng triết lý "không
chấm được ≠ bịa" đã có). Giữ nguyên hai ngưỡng 0.60/0.34: mẫu tay không cho bằng chứng
nào chống lại chúng ở cặp cùng-ngôn-ngữ.

### Phân tích (bước 4 của runbook)

- **Nhãn thấp rơi vào đâu:** 4 weak đều `single`, 1 ungrounded là `cross`; điểm chung
  không phải nhóm câu mà là **nguồn bằng chứng tiếng Anh** (`current_architecture.md`,
  `versioned_ingestion.md` là hai fixture tiếng Anh trong corpus 5 tài liệu).
- **Đối chiếu 2 câu retrieval còn miss** (`p3_khoa_brute_force`, `p3_refresh_khong_xoay`):
  cả hai được chấm `grounded ratio=1.0` nhưng `answer_pass=False` — model trả lời
  **trung thành với chunk sai** (retrieval trả chunk lân cận đúng tài liệu). Nghĩa là:
  không bịa-vì-mất-nguồn; guard đo *faithfulness với cái đã trích*, không đo *đúng đáp
  án* — hai trục độc lập, và cặp số (grounded, answer_fail) chính là chữ ký của lỗi
  retrieval chứ không phải lỗi sinh.
- **language_mismatch = 0** và model không trả lời tiếng Anh câu nào — 82/82 câu trả
  lời tiếng Việt (prompt tiếng Việt hoạt động); số 0 này đồng thời che điểm mù pool
  trộn nói trên.
- **answer_pass vs grounding: lệch 10/82, đều 5-5 hai chiều** (nên hai rate trùng
  0.9390 chỉ là trùng hợp số học): 5 câu `answer_pass=False` nhưng `grounded` (2 câu
  retrieval miss + `br_doi_ten_db_hong`, `vi_reindex_that_bai_trang_thai`,
  `xd_an_han_xoa_vector_version_cu` — thiếu *từ khóa kỳ vọng* ≠ bịa); 5 câu
  `answer_pass=True` nhưng weak/ungrounded (đủ từ khóa kỳ vọng nhưng nhãn thấp vì
  điểm mù dịch). Hai thước đo bắt hai kiểu lỗi khác nhau — giữ cả hai.

### Quyết định bước kế tiếp của D3a

**Giữ "chỉ báo" (report-only), CHƯA thêm hành vi tự động.** Lý do bằng số: nhãn
`ungrounded` hiện có 2/3 xác suất là báo oan kiểu xuyên ngữ trên corpus này — gắn
hành vi "thú nhận thiếu nguồn" vào một tín hiệu như vậy sẽ làm model tự nghi ngờ
chính các câu dịch đúng. Thứ tự việc còn lại: (1) sửa cap theo-nguồn-khớp-nhất (lane
nhẹ, có test tái hiện #6/#10), (2) đo lại 82 câu trên máy nặng — kỳ vọng nhãn thấp
còn lại đều là báo đúng, (3) khi đó mới quyết định hành vi cho `ungrounded` và đóng
D3a hẳn.

## Sửa 21/08 (máy nhẹ) — cap xuyên ngữ theo nguồn khớp nhất

Thi hành đúng đề xuất ở trên, ngưỡng 0.60/0.34 **giữ nguyên**:

| Thay đổi | Lý do |
| --- | --- |
| `_source_index` giữ thêm **từng nguồn** (từ vựng + ngôn ngữ) bên cạnh pool chung | Pool quyết định nhãn (chunk nào cũng có thể đỡ câu); chỉ câu hỏi "câu này dựa vào chunk nào" mới cần nhìn từng nguồn |
| Với câu không `grounded`: nguồn bằng chứng = nguồn có **số từ trùng cao nhất** với câu đó; khác ngôn ngữ với câu → cap `weak` + `language_mismatch` | Tái hiện đúng #6 (legacy Qdrant points, `current_architecture.md`) và #10 (RQ worker, `versioned_ingestion.md`) bằng văn bản fixture thật trong test |
| **Hòa điểm** giữa nguồn cùng ngôn ngữ và nguồn khác ngôn ngữ → tính là khác | Hòa là không quy được bằng chứng (ví dụ thật: `.bat` fold trùng "bật"); "không chấm được" phải thắng "bịa" — cap chỉ hạ về weak, không bao giờ nâng lên grounded |
| Câu **không trùng từ nào** với nguồn nào → chỉ cap khi mọi nguồn đều khác ngôn ngữ | Không có bằng chứng để quy thì là câu không được đỡ, trừ khi cả pool là tiếng khác; test: câu bịa tiếng Việt trong pool trộn vẫn `ungrounded` |
| Câu bịa mà vài từ trùng rơi vào chunk tiếng Việt → vẫn `ungrounded` | Cap không được thành lý do bao che chung cho pool trộn (test riêng) |

Còn theo dõi (chưa sửa, chưa có bằng chứng đủ): caveat #4 — chuỗi nguyên văn 4 từ
chứng nhận cả câu nửa-trích nửa-suy-diễn. Chờ lần đo lại cho số liệu.

**Việc còn lại để đóng D3a (máy nặng):** đo lại 82 câu với bản sửa; kỳ vọng
`language_mismatch > 0` và nhãn thấp còn lại đều là báo đúng; rồi quyết định hành vi cho
`ungrounded`.


## Đo lại sau sửa cap (21/08/2026 lần 2, máy nặng `PC-dungbt`) — nghiệm thu ✅, D3a ĐÓNG

Cùng lệnh, cùng cấu hình ship; retrieval lại khớp baseline P4-3 từng con số
(0.9756 / 0.8581 / 0.8537) — hai lần đo cùng-điều-kiện.

| Metric | Trước sửa (11:57) | Sau sửa (19:36) | Ghi chú |
| --- | --- | --- | --- |
| grounding_rate | 0.9390 (77/82) | **0.9390** (77/82) | không đổi — sửa nhắm vào *chất* của nhãn thấp, không phải con số đầu bảng |
| labels | 77 g / 4 w / **1 u** | 77 g / 5 w / **0 u** | mức báo động `ungrounded` về 0; câu ungrounded-oan cũ (`xd_point_index_version_cu_bi_bo_qua`) giờ `weak + language_mismatch` |
| language_mismatch | 0 (thiếu nhạy) | **3** | đúng kỳ vọng >0: cờ giờ đánh dấu được câu dịch từ chunk tiếng Anh |
| answer_pass_rate | 0.9390 | 0.9390 | |
| Số câu nhãn thấp | 5 | 5 | **không giảm về lượng** — sinh nondeterministic đảo câu nào rơi weak giữa hai lần; cái giảm là *mức độ sai*: hết ungrounded, 3/5 mang cờ "không chấm được" |

Danh sách weak lần 2: `ca_audit_legacy_point`, `ca_duong_dan_archive_sqlite`,
`ca_khoi_phuc_qdrant_snapshot`, `ca_lam_moi_sau_phase`,
`xd_point_index_version_cu_bi_bo_qua`. Hai câu retrieval miss vẫn là
`p3_khoa_brute_force` / `p3_refresh_khong_xoay` — không liên quan grounding.

### Đối chiếu tay vòng 2 (toàn bộ nhãn thấp + 3 grounded ngẫu nhiên, seed 20260821)

Cùng quy cách vòng 1: mỗi câu gọi lại `/rag/chat` một lần, người chấm cặp
câu-trả-lời/nhãn của chính lần gọi đó.

| # | id | nhãn run | nhãn máy (lần gọi chấm) | kết luận người | khớp? | ghi chú |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | ca_audit_legacy_point | weak | weak (không cờ) | **có nguồn** — dịch từ "no automatic cleanup policy exists… separately approved policy" | ❌ báo oan nhẹ | cap trượt: từ trùng nhiều nhất của câu rơi vào chunk tiếng Việt khác ("chính sách", "phê duyệt" có trong fixture xưởng in) nên bằng chứng bị quy nhầm nguồn |
| 2 | ca_duong_dan_archive_sqlite | weak | grounded (1.0) | có nguồn — đường dẫn archive nguyên văn | ✅ | |
| 3 | ca_khoi_phuc_qdrant_snapshot | weak | grounded (1.0) | có nguồn — "retained Qdrant snapshot" | ✅ | |
| 4 | ca_lam_moi_sau_phase | weak | **weak + mismatch** | có nguồn — lần này model trả lời đúng "P0 và P1-1..P1-3", dịch từ chunk tiếng Anh | ✅ đúng thiết kế | máy nói đúng bản chất: "không chấm được vì khác ngôn ngữ", không phải "bịa" (vòng 1 câu này còn trả lời sai "Phase 1") |
| 5 | xd_point_index_version_cu_bi_bo_qua | weak | **weak + mismatch** | có nguồn — 4 câu đều dịch trung thành Source 1 tiếng Anh | ✅ đúng thiết kế | chính là câu #6 vòng 1 từng bị `ungrounded` không cờ |
| 6 | br_rebuild_qdrant | grounded | grounded | có nguồn (`rebuild_qdrant` nguyên văn) | ✅ | |
| 7 | xa_gpu_may_chu | grounded | grounded | có nguồn (RTX 4090 / 24 GB VRAM nguyên văn bảng) | ✅ | |
| 8 | p3_reset_mat_khau | grounded | grounded | có nguồn ("reset qua psql" nguyên văn) | ✅ | |

**Chấm theo tiêu chí:**

1. **Dương tính giả về độ tin cậy = 0 ✅** (vòng 2 tiếp tục sạch; cộng dồn hai vòng:
   15 câu grounded được người đọc kỹ, 0 mệnh đề bịa sự kiện). **Caveat #4 không tái
   xuất** — không câu nào nửa-trích nửa-suy-diễn được verbatim-run chứng nhận trong
   mẫu này; giữ hồ sơ theo dõi, chưa cần sửa.
2. **Nhãn thấp đa số báo đúng ✅** — 3 câu nhãn thấp fresh: #4 và #5 là `weak +
   language_mismatch`, tức máy tuyên bố đúng bản chất "không chấm được vì khác ngôn
   ngữ" (đúng triết lý thiết kế); #1 là báo oan còn sót (1/3), và nó ở mức `weak`
   không cờ — phía an toàn, không phải mức báo động. So với vòng 1 (2/3 báo oan ở
   mức nặng nhất `ungrounded`), chiều sai đã đổi hẳn.

### Vết còn lại ghi hồ sơ (không chặn đóng)

Trường hợp #1 chỉ ra giới hạn kế tiếp của attribution theo từ-trùng: câu dịch có
thể trùng *từ chức năng đã fold* với một chunk Việt không liên quan nhiều hơn là
trùng *thuật ngữ* với chunk Anh là bằng chứng thật. Đây là mức tinh vi mà một bộ
chấm không-model chấp nhận đánh đổi (plan §1: ưu tiên cơ chế không-LLM); sửa tiếp
chỉ đáng làm nếu số liệu tương lai cho thấy nó gây nhiễu thật — hiện tại 1/82 câu,
ở mức weak, phía an toàn.

### Quyết định hành vi cho `ungrounded`: GIỮ "CHỈ BÁO" — lý do bằng số

- Sau sửa, `ungrounded` bắn **0/82** trên corpus này; lần duy nhất nó từng bắn
  (vòng 1) là báo oan. Tức tín hiệu này **chưa có base-rate dương tính thật nào
  được đo** để thiết kế hành vi tự động quanh nó.
- Hai vòng đối chiếu tay không tìm thấy mệnh đề bịa sự kiện nào trong 15 câu
  grounded — trên corpus + model + prompt hiện tại, bịa thật là hiện tượng hiếm
  hơn độ phân giải của bộ 82 câu.
- Hành vi "thú nhận thiếu nguồn" hay "tìm thêm" kích hoạt bởi một tín hiệu như vậy
  sẽ chỉ chạy trên báo oan (xác suất đo được ≈ 100% các lần bắn tới nay) — model tự
  nghi ngờ câu trả lời đúng, trả giá UX thật để phòng một lỗi chưa quan sát được.
- Chip "bám nguồn x%" + tooltip câu chưa đủ nguồn trên web đã đưa đúng thông tin
  này cho người dùng — đúng tinh thần giám sát-thay-vì-chặn của plan.
- **Mở lại khi nào:** nếu đổi model sinh / prompt / corpus làm `ungrounded` bắn
  thật (baseline này là thước so), hoặc khi D5 red-team tạo được câu bịa có chủ
  đích — lúc đó có base-rate thật để cân hành vi.

**D3a đóng** với: bộ chấm không-model chạy trên mọi câu trả lời `/rag/chat` (0 lời
gọi model thêm), baseline faithfulness có theo dõi trong git, hai vòng đối chiếu tay
0 dương tính giả, và một quyết định hành vi có số liệu chống lưng.
