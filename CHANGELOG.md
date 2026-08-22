# Changelog

Mọi thay đổi đáng chú ý của Local AI Core được ghi tại đây.

Định dạng theo [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/);
phiên bản tuân theo [Semantic Versioning 2.0.0](https://semver.org/lang/vi/).

Quy ước version của dự án: `1.0.0` là **ảnh chụp nền** của hệ thống tại thời điểm
có kế hoạch phát triển chính thức. Mỗi phase trong `docs/DEVELOPMENT_PLAN.md`
đóng lại thì tăng một minor version.

## [Unreleased]

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
  học: `docs/machine_split.md`.

### Added
- **T14 đóng — lưới backup thứ hai chạy thật**: Scheduled Task `LocalAICore Backup` (02:00 hằng ngày,
  user `dungbt06`, đường dẫn ASCII `C:\Users\dungbt06\local-ai-core`, tạo từ prompt admin) chạy thử
  `Last Result: 0` và ra dump mới; cùng backup worker của launcher thành hai lưới độc lập.
- **T11 đóng — collection Qdrant `documents` cấu hình theo môi trường** (`QDRANT_DOCUMENTS_COLLECTION`):
  suite dùng `documents_test`; phiên đo trên DB lab (`machine_split.md`) dùng `documents_lab` +
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
  (`docs/machine_split.md`).

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
  (`docs/machine_split.md`).
- **Override contextual retrieval theo máy**: biến `.env` `RAG_CONTEXTUAL_RETRIEVAL_ENABLED`
  (không đặt = theo `models.yaml`; `true`/`false` = máy này tự quyết) qua
  `ChunkContextService.from_config` dùng chung cho API lẫn RQ worker — máy nhẹ tắt
  sinh context lúc index, máy mạnh giữ bật (`docs/machine_split.md`). Test cô lập
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
