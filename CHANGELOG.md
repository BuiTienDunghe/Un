# Changelog

Mọi thay đổi đáng chú ý của Local AI Core được ghi tại đây.

Định dạng theo [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/);
phiên bản tuân theo [Semantic Versioning 2.0.0](https://semver.org/lang/vi/).

Quy ước version của dự án: `1.0.0` là **ảnh chụp nền** của hệ thống tại thời điểm
có kế hoạch phát triển chính thức. Mỗi phase trong `docs/DEVELOPMENT_PLAN.md`
đóng lại thì tăng một minor version.

## [Unreleased]

### Added
- **P4-5 đóng cả hai phase — mở hộp đen chunking** (25/08, thiết kế `docs/p4_5_design.md` duyệt
  nguyên trạng). Trang mới «Đoạn» cạnh mỗi tài liệu: xem tài liệu bị cắt thành đoạn nào đúng như bộ
  truy xuất index (chỉ version active), mỗi thẻ hiện trang/mục/token/loại, khối context P4-2 tách
  nền riêng, và **phần overlap với chunk trước tô xám** — chỗ nhìn ra bệnh biên chunk đang kìm
  MRR/doc_hit. Đánh dấu «đoạn kém» lưu ở bảng mới `chunk_feedback` (migration `20260825_26`,
  additive + downgrade đã drill), **cố ý không** nằm trên `document_chunks` vì `replace_chunks`
  xoá-tạo-lại hàng mỗi re-index — cột ở đó sẽ mất sạch đánh dấu im lặng (họ lỗi T15); cầu nối qua
  re-index là `content_hash`, có test đi qua đường ghi thật chứng minh: re-index cùng nội dung →
  đánh dấu còn, đổi nội dung → thôi áp. API `GET /documents/{id}/chunks` + `POST/DELETE
  .../feedback` (idempotent); service riêng, không SQL trong router. Xác minh bằng mắt trên
  production: 50 chunk của `1409.3215v3.pdf`, 49/50 hiện overlap, lọc client-side chạy. 6 test mới;
  0 lời gọi model thêm.
- **P4-4a (a)+(b) đóng — bớt một truy vấn DB mỗi câu hỏi, bằng TTL chứ không bằng niềm tin**
  (25/08). Trước: mỗi `/rag/*` bắn một truy vấn fingerprint chỉ để hỏi "corpus có đổi không" (đo
  24/08: 5.7 ms), gần như luôn trả lời không. Thiết kế chọn **hai lớp**: ghi **cùng tiến trình**
  (activate đường thread, delete, remove_source) gọi `invalidate()` qua callback `on_corpus_change`
  mới trên `PostgresDocumentService` — thấy ngay ở câu hỏi kế tiếp, giữ trải nghiệm upload-rồi-hỏi;
  ghi **khác tiến trình** (RQ worker, cleanup container) được fingerprint bắt như cũ nhưng chạy tối
  đa **1 lần/5 s** thay vì mỗi câu. Cố ý KHÔNG chọn bỏ-hẳn-fingerprint như phác thảo cũ: invalidate-
  only sẽ mù vĩnh viễn với ghi ngoài tiến trình ở bất kỳ cấu hình đa tiến trình nào — lỗi im lặng,
  không tự lành; TTL xoá luôn nhu cầu "từ chối khởi động khi cấu hình rq" mà phác thảo cũ phải kèm.
  Test: TTL 1 giờ + ghi ngoài → không thấy (đúng thiết kế), `invalidate()` → thấy ngay; wiring thật
  delete→search-kế-tiếp-trống. Phần đắt của P4-4a — (c) dựng nền vs phương án B — **gác chờ chuông
  2 500 chunk** (cold đo được chỉ ~0.5 s, chưa ai đau). **P4-5 có bản thiết kế chờ duyệt**
  (`docs/p4_5_design.md`): 2 phase (chỉ-xem không đụng schema · đánh dấu qua bảng `chunk_feedback`
  mới — cột trên `document_chunks` sẽ mất sạch mỗi lần re-index vì `replace_chunks` xoá-tạo-lại),
  API + UI + nghiệm thu ghi sẵn, **chưa code dòng nào** đúng bất biến #8.
- **Lưới backup vá xong ba lỗ — rủi ro một-máy hạ Cao → Trung** (24/08). Trước đó: dump nằm
  **cùng ổ đĩa** với database, `backup_sources.py` tồn tại nhưng **0 nơi gọi**, `.env` không có bản
  sao nào — và khi kiểm tra thật thì phát hiện **02:00 hai đêm 23–24/08 không ra dump** (Docker
  Desktop tắt, Scheduled Task thất bại im lặng, `/health` chỉ sống cùng launcher nên không ai hay).
  Giờ mỗi backup thành công làm hai việc trong cùng `run_once` (launcher lẫn Scheduled Task dùng
  chung): dump → **zip toàn bộ `data/documents/` kèm manifest SHA-256** (455 nguồn, xoay vòng
  14 ngày/giữ 3 như dump). Cơ chế **mirror sang `BACKUP_MIRROR_DIR`** (chép thiếu-theo-tên, kỷ luật
  `.part`-rồi-đổi-tên, mirror chết chỉ ra warning không làm hỏng backup chính) đã viết và có test,
  nhưng **để TẮT**: máy chỉ có một SSD vật lý (C: và D: là hai partition của cùng thanh KIOXIA
  1863 GB), nên mọi đích trên máy là bản sao giả — thà biết mình có một bản còn hơn tin có hai.
  Bật lại khi có USB/NAS: bỏ comment một dòng trong `.env`.
  Chuông độc lập launcher: `check_operational_alerts --dump-max-age-hours 48` — thử trên chính sự
  cố thật: đỏ (55.2h, exit 2) trước khi vá, xanh (0.0h) sau khi backup chạy lại. `.env` có cặp
  `backup-env-once.ps1`/`restore-env.ps1` (AES-256 + PBKDF2 200k, round-trip và sai-passphrase đều
  có kiểm). **Nói thật giới hạn**: C: và D: là hai partition của cùng một đĩa vật lý — mirror hiện
  tại chống hỏng filesystem/xoá nhầm, không chống chết đĩa — nên rủi ro một-máy ở plan §8 **giữ
  mức Cao**, không hạ. **Quyết định 25/08**: backup ở lại trong dự án (`data/backups/`, gitignore
  chặn, đi theo folder khi copy), không USB, không cloud — chết SSD là mất sạch, và đó là đánh đổi
  đã cân nhắc chứ không phải việc chưa làm. Mirror giữ trong code, bật lại bằng một dòng comment.
  **`.env` tự vào backup mỗi đêm dạng văn bản thường, chỉ ghi khi nội dung đổi** — bỏ yêu cầu
  passphrase khỏi đường mặc định sau khi nhận ra nó thừa: `.env` vốn đã nằm dạng thường ở gốc dự án
  nên bản sao cạnh nó dưới `data/backups/` (gitignore chặn) không hở thêm gì, trong khi passphrase
  thêm đúng một cách để mất backup vĩnh viễn — phá chính mục đích backup. Khôi phục = chép file về.
  Ghi-khi-đổi biến thư mục thành lịch sử chỉnh sửa thay vì 14 bản y hệt; test bắt được lỗi hai lần
  sửa trong cùng một giây trùng tên file (bản sau đè bản trước, mất đúng bản cũ người ta cần) — đã
  thêm hậu tố đếm. `backup-env-once.bat` / `restore-env.bat` giữ lại cho trường hợp bản sao **rời
  khỏi máy** (gửi đi, cloud, ổ chung); bấm-đúp-là-chạy, bọc `.ps1` vì ExecutionPolicy và vì bấm đúp
  `.ps1` chỉ mở Notepad. 8 test mới.
- **Việc #2 đóng — đặt thước trước khi tối ưu** (24/08, ba phần). **(1)** Eval multidoc tổng hợp
  độ trễ đã thu sẵn từng câu thành `latency: {measured, p50, p95, max}` — **report-only, không vào
  gate CI, không vào baseline** (bài học P4-3: đo latency trên runner không GPU là đo sai cấu hình);
  `max` đi kèm vì cơn treo rebuild là *một* câu trong 82 — p95 không chạm tới nó theo cấu trúc.
  **(2)** `scripts/benchmark_bm25_rebuild.py` (chỉ đọc) thay con số nền "98.1% rebuild là pyvi"
  (ngoại suy fixture 27 chunk, không có mục đo nào) bằng số thật trên production 118 chunk:
  cold **0.48–0.52 s** · rebuild steady-state **0.383 s** trong đó pyvi **92.9%** · chấm warm
  **3.6–4.3 ms** (ngoại suy cũ ~1.2 ms — **lệch ~3×**) · fallback all-zero sau bản vá **4.5 ms**
  (trước vá ≈ nguyên một lần rebuild). Hệ quả: ở 5 000 chunk BM25 warm ~160 ms ≈ 26% p50 — cò súng
  mở lại P4-4b đổi từ "p95 vượt ngân sách" (câm: BM25 hôm nay 0.6% tổng, và treo rebuild nằm ở max)
  sang "**phần BM25 trong p50 ≥ ~15%**" (plan §9.5), sẽ kêu quanh 2 500–3 000 chunk. **(3)** Số
  chunk active giờ nhìn thấy được: `metrics.active_chunks` (đúng predicate BM25 snapshot, có test
  khoá tương đương) + `check_operational_alerts.py --chunk-warn` (mặc định **2 500** = nửa ngưỡng
  P4-4b, exit 2 khi chạm) — điều kiện §9.5 thôi là "khi nào ai đó chợt nhớ ra". Plan §7 thêm bốn
  hàng theo dõi (p95 ≤ 1 200 ms làm lưới chung; max chốt ngưỡng sau P4-4a; BM25-share; chunk active).

### Fixed
- **T17 đóng — `DocxParser` đọc thiếu 1/5 tài liệu** (24/08, làm **trước** mọi việc khác vì thước đo
  chất lượng vô nghĩa nếu tầng đọc bỏ mất nội dung). Parser cũ chỉ lấy `document.paragraphs`:
  python-docx để bảng ở `document.tables` riêng và textbox nằm trong `w:txbxContent`, nên cả hai bị
  bỏ; `paragraph.style.name` cũng bị vứt nên heading theo style của Word không bao giờ thành `#` mà
  chunker tìm. Đo trên 3 tài liệu thật, phần thân phục hồi được: **78.7 → 100.3 %** (sổ tay 45 trang),
  **90.1 → 103.0 %** (paper RAG), **92.3 → 103.3 %** (paper Attention); chunk bảng từ **0 → 20/9/17**.
  Phần mất không ngẫu nhiên — nó là bảng kết quả và khung tóm tắt, thứ mật độ thông tin cao nhất, và
  vì cả embedding lẫn BM25 index `retrieval_context + content` nên nội dung đó trước đây **không tìm
  được bằng bất kỳ đường nào**. Ba bẫy đã xử lý: duyệt `body` đúng thứ tự tài liệu (hai danh sách rời
  làm mất interleaving lẫn bảng lồng trong ô) · Word ghi shape **hai lần** `mc:Choice` + `mc:Fallback`
  nên lấy cả hai là nhân đôi (Attention 44 `txbxContent` → **22 thật**) · ô bảng chứa `|` hoặc xuống
  dòng bị escape/làm phẳng để không giả mạo cột hay cắt sớm bảng. **Bài học đo lường**: tỷ lệ chunk
  có heading của bản CŨ *cao hơn* bản mới (76 % vs 46 % ở paper RAG) nhưng là **dương tính giả toàn
  phần** — 22 chunk cùng mang một nhãn sai `"Save the modified PDF document"` (dòng đánh số khớp
  nhánh số của `_HEADING_PATTERN`); bản mới sinh 3 đường mục đúng. **Không sửa được, ghi rõ**: docx
  không có phân trang cố định, cả 3 file đều `lastRenderedPageBreak = 0`, nên `page_start` vẫn `None`
  — citation từ docx không nói được số trang; ảnh trong docx cũng chưa qua OCR. Test dựng docx bằng
  python-docx ngay trong test, không commit nhị phân bên thứ ba (repo PUBLIC).
- **T15 đóng — citation production hết `heading_path: null`** (24/08). `replace_chunks` giờ ghi đủ
  `locations`/`heading_path`/`token_count` mà chunker vẫn tính rồi vứt; `token_count` hoá ra **chưa
  từng được chunker tính** — đã thêm (`count_tokens(content)`). Lệch kiểu chốt về **list**: dataclass
  chunker mang tuple heading parts, cột JSONB nhận `list[str]`, Qdrant payload giữ nguyên dạng chuỗi
  join (mọi point cũ đã ở dạng đó); `rebuild_qdrant.py` sửa theo. Test mới đi qua **đường ghi thật**
  (chunker → `replace_chunks` → BM25 đọc lại, fixture có heading) thay cho test dựng chunk bằng tay
  từng che lỗi. **Backfill production** `scripts/backfill_chunk_metadata.py` (dry-run mặc định,
  `--apply` để ghi, guard `content_hash` từng chunk): 11 version khớp hash **100 %** (0 drift),
  209/209 chunk điền `token_count`, 150 `heading_path`, 162 `locations`; 7 version page-mismatch
  (micro-drift T7: đường thread ghi page=None) chỉ điền heading/token, **bỏ** locations đúng guard.
  Không đụng `retrieval_context`/embedding/Qdrant — thứ hạng D1 không đổi; 75/118 chunk active giờ
  trả heading thật trong citation.
- **BM25 fallback không còn tách từ lại toàn corpus mỗi query** (24/08). Đường token-overlap (chạy
  khi mọi điểm BM25 ≤ 0 — điển hình là câu hỏi ngoài corpus) gọi `tokenize_vietnamese` trên **từng
  chunk mỗi lần hỏi**, tức trả nguyên chi phí một lần rebuild (~98 % là pyvi) ngay trong đường trả
  lời, lớn dần theo corpus. Giờ dùng lại `doc_freqs` mà `BM25Okapi` đã dựng từ đúng token đó lúc
  index — cùng phép đếm, thứ hạng giữ nguyên từng điểm; test khoá bất biến "mỗi query tokenize đúng
  một chuỗi: câu hỏi".

### Changed
- **Plan v1.3.1 — sửa 5 lỗi tài liệu tìm ra qua review đối kháng 2 agent** (24/08): (1) KPI §7
  `doc_hit` 0.842 là số P4-2 chép nhầm → **0.854** (baseline JSON 0.8537); (2) §3e "cả bốn cờ dùng
  chung idiom" → đúng là **ba** (`QDRANT_DOCUMENTS_COLLECTION` là tên collection đọc thẳng từ
  settings, không log nguồn — biến từng gây trộn vector lab/prod ở T11); (3) toàn bộ con trỏ
  `§9a/§9b/§9c/§9d` chết sau lượt đánh số lại 24/08 đã vá ở `p4_4_design.md` (banner "plan thắng"
  trỏ vào mục không tồn tại), `d1_retrieval_eval.md`, `p4_progress.md`, CHANGELOG; (4) §9.3 hàng
  "v2-A không giải được G8-3" hạ xuống **chưa kết luận được** — phán quyết cũ đứng trên số #5 mà
  chính §9.4 đã vô hiệu (EXPLAIN thiếu `ANALYZE`, truy vấn không đại diện); (5) §8 ô đối sách rủi ro
  một-máy viết đúng thực tế: dump nằm **cùng ổ** với DB, `backup_sources.py` tồn tại nhưng 0 nơi
  gọi, `.env` không có bản sao — mức rủi ro nâng Trung → **Cao**, kèm danh sách việc phải làm. Kèm
  ba bổ sung: §7 **tuyên bố tường minh** hai KPI trượt (MRR/doc_hit) được chấp nhận chu kỳ này và
  đường gián tiếp qua P4-5; §4c#3 giữ **phương án B** (lưu lexeme xuống DB — nhật ký 23/08 ghi "vẫn
  nên làm" nhưng §4 cũ làm rơi) làm ứng viên cạnh (c), kèm ràng buộc (b) chỉ hợp lệ ở backend
  `thread`; nghiệm thu P4-5 (trước đây không có dòng nào).

- **Plan v1.3 — một môi trường vận hành duy nhất; `docs/machine_split.md` đã gộp và xoá**
  (24/08). Dự án thôi phân lane nhẹ/nặng: mọi việc từ nay làm trên `PC-dungbt`. Hợp đồng
  vận hành (thư mục production thuần ASCII, Scheduled Task backup, DB nào cho việc gì,
  cảnh báo đo lường trên DB thật, cờ cấu hình theo môi trường, quy tắc bảo mật) chuyển
  nguyên vẹn vào plan **§3**; 20 tham chiếu tới `machine_split.md` trong code/test/docs/
  CHANGELOG đã trỏ lại đúng mục. **Cơ chế override `.env` GIỮ NGUYÊN trong code** — CI
  vẫn là môi trường thứ hai không GPU, không có extra `[rerank]`. `.machine-role` ngừng
  dùng (vẫn gitignore để marker cũ không lọt vào git). Máy nhẹ `hehehhe` còn đúng vai
  trò client LAN; quy tắc an toàn duy nhất còn lại: chỉ một máy chạy bot Discord và chạm
  dữ liệu thật. Plan cũng nén lịch sử đã đóng còn một dòng mỗi mục (chi tiết ở
  `p1..p4_progress.md`) và bổ sung **§4 — danh sách đầy đủ 14 việc còn lại** kèm thứ tự
  thi công, phụ thuộc và ước lượng, để không mục nào rơi khi đổi phiên làm việc.
- **Sửa hai chỗ số liệu yếu hơn kết luận trong báo cáo P4-4b** (plan §9.4): truy vấn dùng
  cho `EXPLAIN` chỉ chọn lọc ~7% (GIN chạm 8/247 buffer) nên không đại diện cho workload
  đo được ở 97.5–100%, và không thấy `ANALYZE` sau khi nạp corpus 1k/5k — con số 126.9 ms
  vì thế không dùng làm căn cứ được. Corpus nhân bản giữ `df/N` không đổi nên là ước lượng
  **bi quan** cho selectivity, không phải chặn dưới. Quyết định hoãn **không đổi**: nó đứng
  trên số #1 (bộ lọc còn để lại 34.7% corpus ở ngưỡng an toàn — chỉ cắt ~3 lần).
- Thứ tự mục trong plan: §9d.6 từng bị chèn trước §9d.5; đã sắp lại theo đúng số *(24/08: phụ lục đánh số lại thành §9.1–§9.5)*.

### Added
- **Hai nợ kỹ thuật mới từ vòng phản biện P4-4** (plan §4b): **T15** — `replace_chunks`
  ghi thiếu `locations`/`heading_path`/`token_count` nên **mọi citation production trả
  `heading_path: null`** (`chunking.py:240-252` tính rồi vứt ở `repositories.py:97-104`;
  kèm lệch kiểu chuỗi vs JSONB `list[str]`). **T16** — `pyvi` chỉ ghim dải `>=0.1.1,<1.0`.
- **P4-4b: HOÃN — quyết định bằng số đo, không viết migration** (máy vận hành, 23/08).
  Năm số ở plan §9d.4 (nay §9.3) đo xong trước khi đụng schema (đúng bài học P4-3): bộ lọc
  `retrieval_lexemes && $1` của v1 kéo **trung vị 100%** corpus (xác nhận G8-3 không được
  giải); cắt DF có ngưỡng an toàn **không ổn định giữa corpus** (production an toàn từ 0.15
  → 28.4%, lab 0.15 mất một câu, an toàn từ 0.20 → 40.7%) nên v2-A trượt mốc 30%; bảng
  posting v2-B đo **12.3–12.6× corpus** (plan ước tính ~7×) nên trượt trần 3×. Số phủ quyết:
  `EXPLAIN ANALYZE` cho thấy planner chọn **Seq Scan ở mọi quy mô đã đo**, **126.9 ms** ở
  5 000 chunk — tại đúng ngưỡng kích hoạt của §1, v2-A **chậm hơn** BM25 in-process (~50 ms).
  Ba con số trong plan sai và đã sửa (v1 "1.06×" bỏ quên index GIN — thật là 1.89–3.65×;
  posting "~7×" → 12.3×; "v2-A có thể giải G8-3" → không). Giữ P4-4a + hướng "chỉ lưu token";
  điều kiện mở lại ghi trong `docs/p4_progress.md`. Không đổi schema, code retrieval hay
  cấu hình vận hành.

### Documentation
- **Thiết kế P4-4 + P4-5 chốt** (`docs/p4_4_design.md`): chỉ mục sparse chuyển vào PostgreSQL bằng
  lexeme pyvi dạng `text[]` + GIN (không `tsvector` — parser tách đôi từ ghép), tf/len theo chunk,
  DF tính trong truy vấn (bỏ bảng DF ⇒ hết rủi ro DF trôi), BM25 chấm trong app. Nêu rõ điều
  KHÔNG đảm bảo được: parity điểm với `rank_bm25` (sàn epsilon theo từ vựng) ⇒ đo lại D1. Đính
  chính hiện trạng: pyvi đã dùng từ trước; P4-4 không nhắm 2 câu miss cuối.

### Changed
- **D5 ✅ ĐÓNG — `rag.injection_defense` BẬT mặc định** sau lần đo 2 trên máy nặng (phiên lab,
  fixture bẫy có dấu, 12 case): attack_success_rate **0.143 → 0.000** (OFF → ON, lặp lại y hệt
  lần 1; vector thủng duy nhất khi tắt là `language_flip` — lần này model in token **và** đổi
  sang tiếng Anh), benign_pass_rate **0.8 → 1.0** (5/5, trong đó 3 control agent đều kéo đúng
  tài liệu bẫy). Chất lượng với ON không cần đo lại: prompt phòng thủ không đổi so lần 1, nơi D1
  và grounding đã Δ 0. Chi phí: 0 lời gọi model, chỉ thêm delimiter + 1 quy tắc vào prompt; có
  hiệu lực khi API khởi động lại, không re-index. Baseline hai lần:
  `data/evaluation/redteam_baseline.json`; đọc tay: `docs/d5_redteam.md`. Production không bị đụng.

### Fixed
- **D5: fixture bẫy viết lại có dấu** (5/6 tài liệu từng không dấu → BM25/pyvi không khớp câu hỏi,
  control agent hỏng ở cả hai vòng đo 22/08); guard test chặn tái diễn; thêm 2 control agent;
  harness thăm dò `/rag/search` sau khi xóa để chứng minh trap chunk không còn retrieval được.
  Máy nặng đo lại hai vòng để quyết định bật `injection_defense` mặc định.

### Changed
- **D5 red-team đo trên máy nặng (phiên lab :8001, DB lab + `documents_lab`)**: phòng thủ
  `injection_defense` đưa attack_success_rate **0.143 → 0.000** (7 tấn công; lần thủng duy nhất
  khi tắt là `language_flip` — model in token xác nhận dù vẫn trả lời tiếng Việt), D1
  retrieval-only và grounding full-mode với defense ON **không đổi một chữ số** (0.9756 /
  0.8581 / 0.8537; grounding 0.939), hai control RAG byte-identical OFF/ON. `benign_pass_rate`
  0.667 ở **cả hai** vòng: control agent `benign_dat_coc_agent` không đo được vì 5/6 fixture
  bẫy viết không dấu (agent tìm toàn corpus không khớp token) — artifact dữ liệu, không phải
  thoái lui do phòng thủ. Theo ngưỡng đã chốt (benign ≥ 0.9) → **cờ vẫn TẮT**; việc còn lại là
  fixture có dấu + đo lại. Baseline hai vòng: `data/evaluation/redteam_baseline.json`;
  bảng đọc tay + chẩn đoán: `docs/d5_redteam.md`. Production :8000 không bị đụng.

### Fixed
- **`scripts/rebuild_qdrant.py` chạy lại được và dựng đúng chỉ mục contextual**: script vỡ ở
  ba chỗ (gọi `ModelRouter` với một client thay vì dict; đưa ORM chunk vào `upsert_chunks`;
  embed `content` trần thay vì `combined_retrieval_text(context, content)` — nếu chạy được
  sẽ âm thầm dựng chỉ mục kém P4-2, kể cả bước 6 `backup_restore.md` sau restore thật).
  Bằng chứng sửa đúng: `documents_lab` dựng bằng script cho D1 Δ 0.0000 so baseline.
- Runbook D5: `DELETE /documents/{id}` chỉ soft-delete, phiên lab không có cleanup worker
  nên phải chạy `cleanup_worker --once --domain documents` sau mỗi vòng (harness in "Trap
  corpus removed" dựa vào 404 của `/status`, chưa đếm chunk/điểm Qdrant).

### Changed
- **Thư mục production dời sang đường dẫn thuần ASCII** `C:\Users\dungbt06\local-ai-core` (từ `C:\Users\dungbt06\Ún promax\local-ai-core`): chữ "Ú" làm
  Scheduled Task backup thất bại `0x80070002` ngay cả khi đường cũ còn, đường 8.3 làm compose
  lập project lạ, pip/cp1252 từng chết. Dời có kiểm tra trước/sau (backup `--force`, `compose
  down` không `-v`, đếm DB 8/2/209 bằng nhau, project + volume postgres không đổi, torch CUDA
  giữ nguyên); downtime ~12 phút. Scheduled Task phải tạo lại với đường mới. Chi tiết và bài
  học: `docs/DEVELOPMENT_PLAN.md` §3.

### Added
- **T14 đóng — lưới backup thứ hai chạy thật**: Scheduled Task `LocalAICore Backup` (02:00 hằng ngày,
  user `dungbt06`, đường dẫn ASCII `C:\Users\dungbt06\local-ai-core`, tạo từ prompt admin) chạy thử
  `Last Result: 0` và ra dump mới; cùng backup worker của launcher thành hai lưới độc lập.
- **T11 đóng — collection Qdrant `documents` cấu hình theo môi trường** (`QDRANT_DOCUMENTS_COLLECTION`):
  suite dùng `documents_test`; phiên đo trên DB lab (`DEVELOPMENT_PLAN.md` §3) dùng `documents_lab` +
  `rebuild_qdrant` nên vector lab và vector vận hành không còn trộn lẫn. Harness D5 **xóa vĩnh viễn
  corpus bẫy khi kết thúc** (kể cả khi lỗi; exit 1 nếu còn sót) — tài liệu chứa chỉ thị độc không
  được sống sót sau một lần chạy; test đầu-cuối bootstrap→bị lừa→dọn sạch→404.
- **D5 red-team prompt injection (phần xây)**: 6 tài liệu bẫy (`data/evaluation/fixtures/redteam/`)
  phủ 6 vector (ghi đè chỉ dẫn, giả [SYSTEM], rò rỉ link, đổi ngôn ngữ, bịa citation, lạm dụng tool)
  + 10 case (`redteam_injection.jsonl`) + harness `scripts/redteam_rag.py` chấm marker xác định
  (attack_success_rate + benign_pass_rate + by_type). Phòng thủ `InjectionDefense` (cờ
  `rag.injection_defense`, override `RAG_INJECTION_DEFENSE_ENABLED`, mặc định TẮT): bọc mỗi passage
  và kết quả tool trong delimiter "dữ liệu không phải chỉ dẫn" + 1 quy tắc trong RAG prompt & agent
  guide; 0 lời gọi model thêm; cờ TẮT = prompt cũ nguyên byte. 10 test không-model. Chạy tấn công
  thật trước/sau là việc máy nặng (`docs/d5_redteam.md`).
- **Máy nặng `PC-dungbt` thành máy vận hành (22/08)**: restore dữ liệu thật từ dump
  `local-ai-20260821-131518.dump` (3 tài liệu, 1 hội thoại, 91 chunk; DB lab cũ giữ
  lại dưới tên `local_ai_core_lab_20260821`), khởi động bằng launcher — `/health` `ok`
  toàn bộ lần đầu, re-index 3 tài liệu thật với cấu hình ship (91 chunk / 451s / 0 lỗi),
  bot Discord chạy ở đây (máy nhẹ không chạy bot nữa). **`backup-postgres-once.bat`**
  (T14, `backup_worker --once --force`) làm lưới backup thứ hai cho Scheduled Task —
  chạy thử ra dump + drill restore đạt. Phát hiện: DB thật chứa tài liệu song sinh của
  fixture bẫy `xuong_in_anh_duong.txt` nên D1 sanity trên DB vận hành tụt MRR/doc_hit
  (recall giữ nguyên) → thí nghiệm đo trên DB lab, không dùng DB vận hành làm thước
  (`docs/DEVELOPMENT_PLAN.md` §3).

### Fixed
- **Suite backend không còn dừng bot Discord thật**: `test_api_key_auth.py` đi qua mọi
  write-endpoint với key đúng, trong đó `POST /api/bot/stop` chạy `BotControlService`
  thật → `docker compose stop discord-bot` trên Docker của máy đang chạy. Máy nhẹ không
  có bot nên không thấy; trên máy vận hành 22/08 bot chết (exit 137) đúng lúc suite kết
  thúc. Fixture `client` trong `conftest.py` nay thay `app.state.bot_control_service` bằng
  stub trơ cho cả suite; test cần hành vi riêng vẫn monkeypatch stub của mình. Nghiệm
  thu: bật bot → chạy trọn suite (603 passed) → bot vẫn `running`.
- **D3a cap xuyên ngữ theo nguồn khớp nhất** (thay cho theo cả pool): đối chiếu tay trên máy nặng
  cho thấy pool nguồn trộn Việt+Anh làm cap không bao giờ bật → câu dịch trung thành từ chunk
  tiếng Anh bị gắn `ungrounded` oan (2/3 nhãn thấp). Giờ bằng chứng của từng câu là nguồn trùng
  nhiều từ nhất (hòa → tính là khác ngôn ngữ), ngưỡng 0.60/0.34 giữ nguyên; 4 test tái hiện bằng
  fixture thật. Cần đo lại 82 câu trên máy nặng trước khi đóng D3a.
- `requirements.txt` về ASCII thuần và launcher đặt `PYTHONUTF8=1`: pip trên Windows đọc file
  bằng cp1252 và chết ở comment tiếng Việt có dấu trước khi launcher kịp chạy (bẫy do máy
  nặng phát hiện khi kiểm tra chéo).
- **Launcher không còn vỡ trên máy cài mới sau P4-3**: `run-local-ai-core.bat` tự ghim
  `RAG_RERANKER_ENABLED=false` vào `.env` khi máy thiếu extra `[rerank]` (một lần, idempotent,
  ghi rõ lý do), và báo lỗi + dừng màn hình khi uvicorn thoát lỗi thay vì đóng cửa sổ sau
  khi đã mở trình duyệt. Phát hiện bởi hội đồng kiểm chứng đối kháng (`docs/p4_progress.md`).
- `RerankerService` tắt không còn cắt kết quả theo `candidate_limit` (slice chạy trước kiểm tra
  `enabled` từ 07/2026; mặc định `RerankerService(False, "", 1)` cắt còn 1 dòng). Test hồi quy.

### Changed
- **P4-3 reranker BẬT mặc định** (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`,
  `candidate_limit` 15) sau khi thí nghiệm D1 trên máy nặng đạt cả ba điều kiện
  chốt trước khi đo: recall@5 0.9146 → **0.9756**, MRR 0.7967 → **0.8581**, MRR
  cross 0.7986 → **0.8611**; **cả 7 câu miss còn lại của P4-2 thành hit**, đổi
  lại 2 câu tụt khỏi top-5 (vẫn trúng đúng tài liệu, chỉ trượt chunk mang nguyên
  văn — headroom P4-4). Chi phí là **độ trễ chứ không phải lời gọi model sinh**:
  `/rag/search` p50 587 → 622ms (**+35ms**, trần 300ms), riêng bước rerank p50
  65ms; số lượt gọi model sinh của một câu hỏi **không đổi**, bất biến ngân sách
  inference còn nguyên. Đo `candidate_limit` 30 thì kém hơn 15 ở mọi chỉ số
  xếp hạng (MRR/doc_hit; recall@5 hòa) lẫn tốc độ, nên giữ 15. Chi tiết: `docs/p4_progress.md`.
- **Baseline D1 ghi lại vì P4-3** (`rag_multidoc_baseline.json`, cấu hình
  contextual ON + reranker ON). Gate CI vẫn dùng `rag_multidoc_baseline_bare.json`;
  bước ghim cờ trong job `retrieval-eval` nay tắt **cả hai** cờ và **fail nếu
  không tìm thấy khoá**, nên đổi tên hoặc di chuyển cờ làm job đỏ chứ không lặng
  lẽ đo sai cấu hình. Tolerance vẫn 0.02, dataset không đổi.

### Changed
- **D3a ✅ ĐÓNG — đo lại sau sửa cap xuyên ngữ, baseline faithfulness cập nhật**:
  82 câu full-mode lần 2 trên máy nặng, cùng điều kiện (retrieval khớp baseline P4-3
  từng số). grounding_rate giữ **0.9390** nhưng chất nhãn thấp đổi hẳn: **0 ungrounded**
  (trước 1 — và lần bắn duy nhất đó là báo oan), `language_mismatch` 0→**3** (cờ giờ
  đánh dấu đúng câu dịch từ chunk tiếng Anh). Đối chiếu tay vòng 2 (toàn bộ 5 nhãn
  thấp + 3 grounded ngẫu nhiên): tiếp tục **0 dương tính giả về độ tin cậy** — cộng
  dồn hai vòng 15 câu grounded không mệnh đề bịa nào; caveat verbatim-run không tái
  xuất; còn 1 báo oan nhẹ mức weak (attribution trượt khi câu dịch trùng từ chức năng
  với chunk Việt không liên quan — ghi hồ sơ, 1/82, phía an toàn). Quyết định hành vi:
  **giữ "chỉ báo"** vì `ungrounded` chưa từng có dương tính thật để đáng gắn hành vi
  tự động; mở lại khi baseline này bị vượt hoặc D5 tạo được câu bịa chủ đích.
  Bảng đầy đủ: `docs/d3a_answer_grounding.md`.

### Added
- **Baseline faithfulness đầu tiên (D3a, đo trên máy nặng)**:
  `data/evaluation/rag_multidoc_grounding_baseline.json` — 82 câu full-mode với cấu
  hình ship (contextual + reranker ON): grounding_rate **0.9390** (77 grounded / 4
  weak / 1 ungrounded), answer_pass_rate 0.9390 (trùng số là trùng hợp — lệch 5-5 hai
  chiều). Đối chiếu tay 10 câu: **0 câu `grounded` chứa mệnh đề bịa sự kiện**; nhưng
  2/3 nhãn thấp là báo oan xuyên ngữ (câu Việt dịch trung thành từ chunk bằng chứng
  tiếng Anh — cap ngôn ngữ đo theo cả pool nên không bật khi pool trộn Việt+Anh).
  Kết luận: giữ mức "chỉ báo"; việc còn lại trước khi đóng D3a là cap theo-nguồn-khớp-nhất
  (giữ nguyên ngưỡng 0.60/0.34) rồi đo lại. Hai câu retrieval miss được chấm
  `grounded` + `answer_pass=False` — chữ ký "trung thành với chunk sai": guard đo
  faithfulness, không đo correctness. Bảng đầy đủ: `docs/d3a_answer_grounding.md`.
- **D3a self-check bám nguồn (không model)**: `answer_grounding.py` chấm từng câu của
  câu trả lời RAG theo văn bản trần của chunk đã trích (fold dấu, content-word overlap,
  chuỗi nguyên văn — tư duy guard memory P2-1b); nhãn grounded/weak/ungrounded, câu
  khác ngôn ngữ nguồn trần ở weak + `language_mismatch`. Báo cáo qua field `grounding`
  của `/rag/chat` (response thường và SSE `done`) và chip "bám nguồn" trên web — chỉ
  báo, không chặn. `evaluate_rag` chế độ full thêm `grounding_rate`; 0 lời gọi model
  thêm. Đo trên bộ 82 câu là việc máy mạnh (`docs/d3a_answer_grounding.md`).
- **Override reranker theo máy**: biến `.env` `RAG_RERANKER_ENABLED` (không đặt =
  theo `models.yaml`) qua `RerankerService.from_config` — cùng khuôn resolver với
  P4-2. Kèm **warmup lúc khởi động**: máy bật cờ mà thiếu `pip install -e .[rerank]`
  bị từ chối dựng server với `RerankerUnavailableError` chỉ rõ lệnh cần chạy,
  thay vì hỏng lúc người dùng hỏi; warmup cũng gánh phần nạp model để nó không
  rơi vào một câu hỏi xui và bóp méo p95. Log `reranker_config` (nguồn quyết
  định) và `rerank_done` (số ứng viên, ms) mỗi câu.
  **Lưu ý cài đặt:** extra `[rerank]` kéo về bản **torch CPU-only** trên PyPI —
  đo trên đó thì mỗi câu hỏi đắt thêm ~990ms (28× so với GPU). Máy có GPU NVIDIA
  cài thêm torch từ index `cu128`; máy không có thì ghim `RAG_RERANKER_ENABLED=false`
  (`docs/DEVELOPMENT_PLAN.md` §3).
- **Override contextual retrieval theo máy**: biến `.env` `RAG_CONTEXTUAL_RETRIEVAL_ENABLED`
  (không đặt = theo `models.yaml`; `true`/`false` = máy này tự quyết) qua
  `ChunkContextService.from_config` dùng chung cho API lẫn RQ worker — máy nhẹ tắt
  sinh context lúc index, máy mạnh giữ bật (`docs/DEVELOPMENT_PLAN.md` §3). Test cô lập
  cờ này (`false`) để suite chạy đường index trần trừ khi test bật tường minh.

### Changed
- **P4-2 contextual retrieval BẬT mặc định** sau khi thí nghiệm D1 trên máy nặng
  đạt ngưỡng đã chốt trước khi đo: recall@5 0.8659 → **0.9146**, MRR 0.7341 →
  **0.7967**, doc_hit 0.7683 → **0.8415**; riêng nhóm cross-doc recall 0.7500 →
  **1.0000** và MRR 0.5903 → **0.7986**. 4 câu miss→hit, **0 câu hit→miss**.
  Chi phí nằm trọn ở lúc index — 1 lời gọi model general/chunk (corpus 5 tài
  liệu: 27 chunk, 144.0s, 0 lỗi), đường hỏi-đáp **không thêm lời gọi model nào**
  nên bất biến ngân sách inference còn nguyên. Số liệu đầy đủ, bảng chi phí và
  danh sách câu đổi hạng: `docs/p4_progress.md`.
- **Baseline D1 ghi lại vì P4-2** và tách làm hai mốc: `rag_multidoc_baseline.json`
  là cấu hình đang ship (contextual BẬT, đo trên máy nặng), còn
  `rag_multidoc_baseline_bare.json` là bản trần cho gate CI. Job `retrieval-eval`
  nay tắt cờ tường minh rồi gate bản trần — runner không tải nổi model sinh 6.6GB
  để dựng chỉ mục contextual, nên so cùng-điều-kiện là cách duy nhất giữ gate có
  nghĩa. Tolerance vẫn 0.02, dataset không đổi. Chi tiết: `docs/d1_retrieval_eval.md`.

### Added
- **P4-2 contextual retrieval — phần code, cờ TẮT mặc định** (lane nhẹ): cột
  `document_chunks.retrieval_context` (migration `20260821_25`), service sinh
  50–100 token ngữ cảnh/chunk bằng model general **ngoài mọi transaction**,
  dùng chung cho cả hai đường index; embedding và BM25 cùng index
  context+content qua một helper duy nhất, citation vẫn là nguyên văn `content`;
  lỗi model ở chunk nào thì chunk đó index bản trần, ingestion không fail; chi
  phí ghi log (giây, số lời gọi). Bật qua `rag.contextual_retrieval.enabled` —
  chỉ thành mặc định sau khi thí nghiệm D1 trên máy nặng đạt ngưỡng
  (`docs/p4_progress.md`).
- **Bộ eval retrieval đa tài liệu** (D1, gỡ G7): corpus 5 tài liệu thật snapshot
  trong `data/evaluation/fixtures/multidoc/`, bộ câu hỏi tiếng Việt
  `rag_multidoc_eval.jsonl` (nhóm single + cross-doc) chấm trên **toàn corpus
  không lọc tài liệu** — trúng khi chunk thuộc đúng tài liệu và chứa nguyên văn
  `expected_source_terms`. Endpoint mới `POST /rag/search` trả đúng nguồn mà
  `/rag/chat` sẽ trích nhưng **không gọi model sinh** (retrieval-only, đúng
  ngân sách inference); job CI `retrieval-eval` dựng Ollama chỉ với embedding
  0.6b và gate theo baseline đã ghi (chưa có baseline thì chỉ báo cáo; tụt quá
  2 điểm recall/MRR là đỏ; đổi model embedding buộc đo lại). Cách dùng:
  `docs/d1_retrieval_eval.md`.
- **Chế độ tài khoản admin/member** (P3-1): bật `LOCAL_AI_AUTH_ENABLED` (kèm
  `LOCAL_AI_JWT_SECRET` ≥32 ký tự và `LOCAL_AI_API_KEY` — validator ép đủ, mặt
  HTTP fail-closed) là web thành nhiều người dùng: người đầu tiên đăng ký làm
  quản trị viên rồi tạo tài khoản cho người khác; đăng nhập JWT (access 15
  phút + refresh thu hồi được); hội thoại thuộc về từng người (người khác nhìn
  vào là 404), member không xóa/sửa được tài nguyên chung (tài liệu, memory,
  các trang quản trị — 403). Bot Discord, eval và smoke test giữ nguyên lane
  X-API-Key. Tắt cờ là trở về đúng chế độ một-người-dùng zero-setup như cũ.
  Migration `20260820_23` (users, refresh_tokens, conversations.user_id).
- **Điều khiển bot Discord từ dashboard** (P3-2): nút Bật/Tắt + trạng thái đọc
  thẳng từ `docker compose ps` — cùng cơ chế run-discord-bot.bat nên không thể
  lệch thực tế.
- **Biểu đồ 14 ngày trên dashboard** (P3-3): câu hỏi/lỗi mỗi ngày và độ trễ
  p50/p95 từ `request_logs`, SVG tự vẽ không cần thư viện.
- **OCR Console** (P3-4): trang `/ui/ocr.html` — upload, theo dõi tiến độ theo
  trang, xem kết quả, đưa thành tài liệu, tải zip, quản lý lịch sử; không cần
  curl. **Phase P3 (Đa người dùng & quản trị) đóng.**
- **Guard xác định cho memory tự áp dụng** (P2-1b): tự áp dụng đòi evidence
  trích **nguyên văn** từ tin gốc và fact **trùng từ-nội-dung** với tin gốc —
  benchmark chứng minh confidence là hằng 1.0 kể cả khi sai nên ngưỡng τ chỉ còn
  là công tắc. Extractor mặc định chuyển `qwen3.5:2b` → `qwen3.5:9b` (2b để lọt
  ~49% fact độc, không harness nào cứu được — xem `docs/p2_progress.md`).
  Đề xuất trượt guard chờ người duyệt, không mất gì.
- **Lệnh Discord `/memory` và `/status`** (P2-3): xem điều agent đang nhớ về
  chính mình trong server (ephemeral, phân biệt 🤖/👤) và sức khỏe hệ thống rút
  gọn. Bộ lệnh chốt: `/ask · /docs · /memory · /status · /ping`.
- **Nhật ký hành động agent** (P2-4): panel dòng thời gian trên dashboard +
  `GET /agent/activity` — quyết định memory (nhớ/từ chối/thu hồi), câu trả lời
  dùng công cụ, việc nền; hàng còn gỡ được có nút Thu hồi ngay tại chỗ.
  **Phase P2 (Agent tự hành) đóng.**
- **Chế độ agent — tool use** (P2-2): bật chip «Công cụ» trên web (cờ `use_tools`
  của `/chat`) hoặc `DISCORD_AGENT_TOOLS_ENABLED` cho bot — model tự quyết định
  gọi công cụ (tìm tài liệu kèm nguồn, đọc trí nhớ dài hạn, xem trạng thái hệ
  thống) trước khi trả lời, tối đa `agent.max_steps` vòng. Mỗi bước lưu bảng
  `agent_traces` (migration `20260819_22`) gắn với câu trả lời, xem lại qua
  `GET /agent/traces/{message_id}` và hiện ngay dưới câu trả lời trên web.
  Tool lỗi trở thành dữ liệu cho model xoay xở, không làm hỏng câu trả lời.
- **Memory tự áp dụng theo ngưỡng tin cậy** (P2-1): đề xuất có confidence ≥
  `DISCORD_MEMORY_AUTO_APPLY_THRESHOLD` (mặc định 0.8, `off` để tắt) được agent
  tự approve qua đúng đường duyệt (`reviewed_by="agent"` — audit và mirror y hệt
  người duyệt); dưới ngưỡng vẫn chờ trên dashboard; đề xuất xóa luôn chờ người.
  Panel mới «Memory đang hiệu lực» cho biết ai duyệt (🤖/👤) kèm nút **Thu hồi**
  1 click (giữ nguyên sử liệu). Approve giờ định tuyến create/supersede/revive:
  fact đổi ý ra version mới + gỡ mirror cũ, và học lại được sau thu hồi — trước
  đó fact cập nhật lần hai kẹt 409 vĩnh viễn.
- **Discord RAG — lệnh `/docs`** (P1-1, ra mắt với tên `/hoi`): hỏi đáp tài liệu ngay trong Discord, chọn tài liệu
  bằng autocomplete hoặc bỏ trống để tìm tất cả; câu trả lời kèm footer nguồn gọn
  (`[1,3] file.pdf · trang 5`) giữ nguyên ánh xạ `[Source n]`. Gọi thẳng `/rag/chat` với
  timeout dài; lượt hỏi persist vào hội thoại session của kênh nên sidebar web không rác.
- **Condense-question trước retrieval** (P1-2): câu hỏi nối tiếp được model viết lại thành
  câu độc lập rồi mới retrieval; lượt đầu và mọi lỗi condense đều rơi về nguyên trạng.
  Bản viết lại phơi ra trường `retrieval_question`; công tắc `rag.condense_enabled`.
  Kèm bộ eval hội thoại 10 cặp tiếng Việt và chế độ `--conversation-dataset` trong
  harness, tự đo cả baseline không-condense để chứng minh mức cải thiện.
- **Memory extractor chế độ đề xuất** (P1-3): bật qua `.env`, launcher tự pull
  `qwen3.5:2b`, khởi động outbox dispatcher + memory worker trên host
  (`scripts/memory_worker.py`, SimpleWorker vì Windows không fork). Candidate nằm ở
  `pending/deferred` chờ duyệt — không tồn tại đường code nào tự áp dụng memory.
- **Duyệt memory trên dashboard** (P1-4): panel "Đề xuất ghi nhớ chờ duyệt" với nút
  Duyệt/Từ chối; API `/api/memory-review/*` (approve/reject là endpoint ghi, cần
  `X-API-Key` khi bật khóa); audit trail đầy đủ (`reviewed_at`, `reviewed_by`,
  decision) — từ chối chỉ ghi lại, không xóa gì.
- **Hợp nhất kho memory** (P1-5): duyệt một đề xuất Discord thì `canonical_fact`
  được mirror (idempotent, id `mem_dc_*`) vào kho `/memory` mà web chat «Ghi nhớ»
  sử dụng — trợ lý web dùng được điều học từ Discord. Phase P1 đóng.
- Nhật ký thi công P1 kèm lý do từng quyết định: `docs/p1_progress.md`.
- CI GitHub Actions chạy trên mọi pull request và push vào `main`: static check,
  bộ test backend với service container PostgreSQL 16 + Redis 7 + Qdrant, và bộ
  test bot/tools trên Windows (P0-1).
- Citation của câu trả lời RAG được lưu cùng tin nhắn trong bảng `message_sources`,
  nên mở lại hội thoại cũ vẫn thấy đủ nguồn như lúc trả lời (P0-3, migration `20260818_20`).
- Backup PostgreSQL tự động: worker định kỳ gọi `backup_postgres.py`, xoay vòng theo
  hạn lưu trữ, phơi độ tươi của bản backup ra `/health`; kèm tài liệu diễn tập restore
  `docs/backup_restore.md` (P0-4).
- `pyproject.toml` và `CHANGELOG.md`; `pip install -e .` hoạt động với layout hai gốc
  import của dự án (P0-5).
- Test chặn hồi quy schema: `alembic check` chạy trong CI và một test tương đương chạy
  cục bộ (P0-6).
- Xác thực lớp 1: header `X-API-Key` bảo vệ mọi endpoint ghi/xóa, cấu hình bằng
  `LOCAL_AI_API_KEY`; tùy chọn `LOCAL_AI_PROTECT_READS` khóa cả endpoint đọc. Giao diện web,
  bot Discord, bộ eval và smoke test đều gửi khóa (P0-2).

### Changed
- `sentence-transformers`/PyTorch (~650MB–2.5GB) rời khỏi phụ thuộc bắt buộc
  (T6): chỉ tính năng reranker (đang tắt, chờ P4-3) cần nó — cài bằng
  `pip install -e .[rerank]`; CI bỏ bước cài torch CPU.
- **Định hướng agent-first** (19/08, plan bản 1.1): thêm phase P2 «Agent tự hành» — memory
  tự áp dụng theo ngưỡng tin cậy (người giám sát + thu hồi thay vì duyệt tay), vòng lặp
  tool-use, nhật ký hành động agent. Lệnh Discord `/hoi` đổi tên **`/docs`** (tham số
  `document`) cho bộ lệnh tiếng Anh nhất quán với `/ask`, `/ping`.
- Outbox dispatcher đòi lại event kẹt `processing` quá hạn (T4): dispatcher chết giữa
  mark và publish không còn làm kẹt job vĩnh viễn; re-publish an toàn nhờ dedupe.
- Model SQLAlchemy và migration đã khớp nhau: tạo 13 index mà model khai báo nhưng chưa
  migration nào tạo, sửa 17 khai báo model nói sai về database (P0-6, migration `20260818_21`).
- `outbox_events.idempotency_key` chuyển sang `NOT NULL` — giá trị NULL vô hiệu hóa
  chống trùng lặp vì PostgreSQL coi các NULL là khác nhau trong unique index.
- Phiên bản ứng dụng đọc từ `app.__version__` thay cho chuỗi cứng.

### Fixed
- **Gói trả nợ pipeline tài liệu 21/08 (T1–T3)**: upload lại nội dung của tài
  liệu đã xóa không còn 500 vĩnh viễn (unique `content_hash` giờ chỉ tính bản
  ghi còn sống — migration `20260820_24`); hủy ingestion ở chế độ RQ khi chưa
  worker nào nhận job được chốt ngay thay vì kẹt `processing` mãi mãi; thay
  nguồn tài liệu giờ nguyên tử — hash mới và run reindex commit cùng một
  transaction nên database không bao giờ nói khác với chỉ mục, replace giữa
  chừng indexing bị chặn 409, còn run mới xếp hàng chưa chạy thì được thay thế
  êm (mỗi lần thay nguồn ra một version mới).
- Bộ test không còn làm bẩn Qdrant dùng chung: collection memory của test tách riêng
  (`QDRANT_MEMORIES_COLLECTION=memories_test`); trước đó embed mock 3 chiều đã tạo
  collection `memories` sai chiều, khiến mọi thao tác ghi memory thật (1024 chiều)
  thất bại với dimension mismatch. Collection bẩn đã được xác minh toàn rác test và xóa.
- Ba test migration khôi phục database về revision ghim cứng thay vì `head`, khiến toàn bộ
  test chạy sau đó thất bại khi có migration mới.
- Từ audit toàn dự án 18/08 (58 phát hiện, xác minh đối kháng): dashboard gửi kèm
  `X-API-Key` (trước đó vỡ hoàn toàn khi bật `LOCAL_AI_PROTECT_READS`); ô nhập khóa dùng
  đúng design token (trước đó tham chiếu 5 biến CSS không tồn tại); race khi chuyển hội
  thoại giữa lúc đang stream không còn ghi đè/xóa nhầm ID và kẹt skeleton; cache tiêu đề
  cục bộ được dọn theo danh sách server và không còn che tên đã đổi trên server; launcher
  khởi động cleanup worker (trước đó xóa tài liệu kẹt `deleting` vĩnh viễn ở bản cài mặc
  định); trạng thái `cancel_requested` trả về giá trị thật thay vì luôn `false`;
  `enqueue_in` dùng `timedelta` đúng chuẩn RQ 2.x; chat thường không còn rò vỏ hội thoại
  rỗng khi model lỗi ở lượt đầu; hai nhánh stream/non-stream của `/rag/chat` dùng chung
  một mapping nguồn qua schema.

### Removed
- Chuyển 29 báo cáo lịch sử (migration SQLite→PostgreSQL, sprint Discord memory) vào
  `docs/archive/`; xóa 1 tài liệu prompt đã thực thi và 2 script one-shot hết nhiệm vụ.
  `docs/` giờ chỉ còn tài liệu sống mô tả hệ thống hiện tại.

## [1.0.0] - 2026-08-18

Ảnh chụp nền của hệ thống đang vận hành: kiến trúc PostgreSQL-only đã hoàn tất, RAG có
dẫn nguồn đã đo được chất lượng, hai kênh web và Discord dùng chung backend.

### Added
- **Trợ lý AI cục bộ**: chat với model chạy trên máy qua Ollama, lưu toàn bộ lịch sử
  hội thoại, tiêu đề hội thoại sinh tự động, giao diện web không cần bước build.
- **Quản lý tài liệu có version**: upload PDF/DOCX/TXT/Markdown, nhận diện trùng lặp bằng
  SHA-256, mỗi tài liệu nhiều version, version cũ vẫn phục vụ tới khi version mới index xong.
- **OCR và ingestion bất đồng bộ**: OCR khi tài liệu thiếu text layer, chunking, embedding
  và index chạy qua hàng đợi Redis + RQ với transactional outbox, lease/heartbeat và
  idempotency key.
- **RAG có dẫn nguồn**: tìm kiếm lai dense (Qdrant) + BM25 tiếng Việt (pyvi) hợp nhất bằng
  RRF; câu trả lời trích dẫn theo tên tệp và số trang.
- **Bot Discord Ún**: cùng backend, phiên hội thoại bền qua khởi động lại, pipeline lượt
  FIFO đảm bảo thứ tự và không giao trùng.
- **Dashboard quản trị**: thống kê agent web và Discord, tình trạng dịch vụ, model và hàng đợi.
- **Vận hành**: `/health` theo dõi FastAPI, PostgreSQL, Redis, Qdrant, Ollama và các worker;
  cleanup worker theo retention policy; launcher một cú click cho Windows.
- **Bộ eval RAG tiếng Việt** 47 câu hỏi, dùng làm cửa kiểm soát chất lượng retrieval.

### Security
- Ở phiên bản 1.0.0 hệ thống **chưa có xác thực**: mọi endpoint mở với bất kỳ ai truy cập được
  cổng 8000. Xác thực lớp 1 được thêm sau đó (xem mục Unreleased). Dù vậy, đây vẫn là một khóa
  dùng chung chứ không phải phân quyền nhiều người dùng; đừng expose ra Internet.

### Giới hạn đã biết
- Trí nhớ web và Discord là hai hệ rời nhau (G2).
- Bot Discord chưa dùng được tài liệu, chỉ gọi `/chat` (G3).
- Câu hỏi nối tiếp chưa được viết lại trước khi retrieval, nên RAG hụt hơi trong hội thoại
  nhiều lượt (G5).
- Bộ eval mới phủ một tài liệu và đã bão hòa ở 100%, chưa đo được tiến bộ tiếp theo (G7).
- BM25 chạy trong tiến trình, giới hạn quy mô corpus (G8).

[Unreleased]: https://github.com/BuiTienDunghe/Un/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/BuiTienDunghe/Un/releases/tag/v1.0.0
