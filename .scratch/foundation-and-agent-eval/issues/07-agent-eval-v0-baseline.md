# 07 — Agent Eval v0: ghi truy xuất thật, chạy baseline 3 lần (M2)

Status: xong trên `wip/07-agent-eval-baseline` — truy xuất ghi + baseline 4 lần + chấm tay 16; doc-18 chốt (b), sửa ở v0.2; chờ fable duyệt rồi gộp
Type: task
Blocked by: 06 (đã gộp); phần chạy GPU chờ 11 (11 đang đo p50 /rag/search, mà 09 dùng số đó làm ngưỡng)

## Việc

1. Ghi kết quả truy xuất thật trên corpus lab cho 20 bài tài liệu một lần, theo định dạng fixture
   của 06. Ghi lại cấu hình retrieval vào manifest của bản ghi.
2. Baseline: 3 lần ở nhiệt độ 0 + seed, 1 lần ở 0.4. So theo từng bài; báo cáo dao động theo bài.
3. Chấm tay ít nhất 5 bài để đối chiếu bộ chấm tự động.
4. Báo cáo ghi rõ: "baseline thăm dò, chưa đủ chứng minh thống kê". Kết quả nào được trích dẫn thì
   promote vào `data/evaluation/results/kept/` và thêm một dòng vào `docs/RESULTS.md`.
5. Chạy với registry đã probe (`manifest.verified: true`) và cấu hình thật của máy, không dùng
   DATABASE_URL giữ chỗ như lần chạy thử của 06 — baseline phải gắn được với cấu hình đang ship.
6. Chạy với `PYTHONUTF8=1` (runner in tiếng Việt; console cp1252 vỡ ngay cả `--help` — fable kiểm 27/10).

## Comments
- 27/10 (opus 5.5): 20 bài tài liệu của v0 hỏi về tài liệu **giả**, không có trong corpus lab, nên
  không ghi truy xuất thật được cho chúng. Chốt cách (C): giữ viết tay cho 8 bài bẫy (doc-04, 10,
  11, 12, 17, 18, 19, 20); khoảng 12 bài tra cứu thường viết **mới** trên tài liệu thật của corpus
  lab, không lấy từ `rag_multidoc_eval.jsonl` (truy xuất đã được chỉnh theo bộ đó). Summary tách
  theo `retrieval_source`. Dataset nâng lên `agent-eval-v0.1`. Fable duyệt 12 bài mới trước khi ghi.
  top_k: nếu ghi được với 8 thì ghi 8, không thì 5 và ghi khác biệt vào manifest. Không chọn (A),
  nạp tài liệu giả vào corpus mà 09 dùng; không chọn (D), bỏ nhiễu truy xuất thật.

**27/10 — Nhân viên của Ún 3: phần code, chưa chạy gì trên GPU, Ollama hay API lab.**

- **Phát hiện trước khi viết code:** 20 bài tài liệu của v0 hỏi về tài liệu giả, không có trong
  corpus lab. Ghi truy xuất thật cho các câu đó sẽ làm mất đáp án. opus chốt phương án (C): giữ 8 bài
  bẫy viết tay, viết **mới** 12 bài tra cứu trên tài liệu thật của lab (doc-21 đến doc-32), không lấy
  câu từ `rag_multidoc_eval.jsonl`. Dataset nâng lên `agent-eval-v0.1`, sha256 `4e1c192b…`.
- Corpus lab (DB `local_ai_core_lab_20260821`, đọc chỉ-đọc 27/10): 5 tài liệu đang dùng với 27
  đoạn. Đó là `backup_restore.md`, `current_architecture.md`, `p3_progress.md`,
  `versioned_ingestion.md` và `xuong_in_anh_duong.txt` (hư cấu). Ngoài ra có 28 bản ghi `trap_*`
  đã xoá. 12 bài mới gồm 9 bài trên xưởng in, 2 bài trên `p3_progress.md`, 1 bài trên
  `versioned_ingestion.md` (hỏi tiếng Việt, tài liệu tiếng Anh).
- **Agent chỉ đọc 400 ký tự đầu của mỗi đoạn** (`agent_service._dump` → `_clip(content, 400)`).
  Cả 12 bài đều có đáp án hoặc `evidence` trong 400 ký tự đầu của đoạn nguồn, đã kiểm trên nội dung
  đọc từ DB lab. Công cụ ghi cũng kiểm đúng phần 400 ký tự này.
- **Ghi lại cho ticket 10:** 400 ký tự đầu của `backup_restore.md` đoạn 0–1 giống nhau, và của
  `p3_progress.md` đoạn 0–2 cũng giống nhau (cùng phần mở đầu tài liệu). Khi nhận các đoạn đó, agent
  chỉ thấy lại phần mở đầu; nội dung riêng của từng đoạn không bao giờ tới được model.
- top_k: `rag.max_context_chunks` chỉ đọc từ `models.yaml`, không có biến môi trường đổi được. Vì
  vậy bản ghi có tối đa 5 đoạn, agent xin 6 đến 8 đoạn sẽ chỉ nhận 5. Đã ghi vào README và
  `retrieval_manifest.json`.
- Code:
  - `agent_eval.py --probe [--env-file]`: dùng `ProductionProbes` thật, bật cả khi
    `MODEL_STARTUP_PROBES=false`. Từ chối chạy (exit 2) nếu `general` không phải con trỏ đã xác
    minh. Manifest ghi `probed`, `registry_fallback`, `env_file`.
  - `agent_eval_record_retrieval.py`: gọi `/rag/search` của API lab (cổng 8100) một lần cho mỗi bài
    `pending`, ghi `chunks` cùng `retrieval_manifest.json`. Một truy vấn hỏng là không ghi gì cả.
  - Runner từ chối chạy bài `pending`. Summary có thêm `by_retrieval_source`.
- Test: 63 passed (`test_agent_eval_record.py` + `test_agent_eval.py` + `test_model_router.py`),
  không cần stack, GPU hay Postgres.
- Chưa làm: ghi truy xuất, baseline 3 lần ở t0+seed và 1 lần ở t0.4, chấm tay ≥5 bài, RESULTS.md.
  Tất cả chờ fable duyệt 12 bài và opus báo 11 xong.

**27/10 — bổ sung (người duyệt + opus).**

- Công cụ ghi giờ từ chối `--tasks` nhắm vào bài viết tay (luôn luôn), và nhắm vào bài đã ghi nếu
  không có `--rerecord`. Ghi lại một bài đã ghi nghĩa là đổi hash dataset đang được trích dẫn, nên
  phải nâng version. Việc từ chối xảy ra trước mọi request. Test:
  `test_naming_a_trap_or_a_recorded_fixture_is_refused_before_any_request`. Tổng: 64 passed.
- **`--probe` không nhẹ, cần opus xác nhận cho baseline.** `ProductionProbes` làm những việc sau:
  - Gọi `/api/embed` một lần (embedding, chạy GPU).
  - Gọi `/api/chat` một lần lên mô hình OCR (GPU).
  - Đọc độ rộng vector và số điểm của các collection Qdrant.
  - Chạy 2 câu `COUNT` trên `DATABASE_URL` của `.env` thật, tức DB `local_ai_core` (dữ liệu
    thật, chỉ đọc).
  
  Ticket này mục 5 yêu cầu "cấu hình thật của máy", nên đó là chủ ý. Nhưng ticket 11 lại cấm dùng DB
  thật cho các lần chạy của nó, nên ghi rõ ra đây. Cũng vì vậy, không chạy thử `--probe` trước khi
  11 xong.
- Stack lab (`eval_stack --profile lab`, gồm uvicorn và worker, không phải container): Nhân viên 3
  bật để ghi, ghi xong thì `--stop`, kiểm không còn tiến trình trên cổng 8100. **Phải tắt trước khi
  chạy baseline**, vì reranker và embedding của lab chiếm GPU sẽ làm sai cột độ trễ của mô hình
  general.
- Sau khi ghi, chạy thêm một phép kiểm offline: mỗi bài recorded phải có ít nhất một đoạn từ đúng
  tệp `corpus_source.file`. `answer_in_chunks` chỉ chứng minh đáp án nhìn thấy được, không chứng
  minh nó đến từ đúng tệp mà `must_cite` đòi.
- Báo cáo baseline cần đếm hai thứ:
  - Số bài recorded nhận phải đoạn có phần đầu trùng nhau (opus yêu cầu, để biết lỗi 400 ký tự ảnh
    hưởng tới điểm cỡ nào).
  - Số `tool_result` bị cắt bởi `tool_result_max_chars` 2400. Giới hạn này được tính cho 4 trích
    đoạn, trong khi bản ghi có 5. Mục đích là tách "model trả lời sai" khỏi "model nhìn thấy JSON bị
    cắt".

**27/10 — opus xác nhận:** baseline chạy `--probe` với `.env` thật. Hai câu COUNT chỉ đọc, một lần
embed và một lần chat OCR đúng là những gì API làm mỗi lần khởi động. Lệnh cấm DB thật ở ticket 11 là
để không ghi dữ liệu eval vào đó. Điều kiện: chỉ chạy sau khi 11 xong. Manifest giờ có
`probe_read_database`, ví dụ `"local_ai_core (read-only: 2 COUNTs)"`; chỉ ghi tên DB, không ghi URL
(test `test_the_manifest_names_the_database_a_probe_reads_but_never_its_url`). 65 passed.

**27/10 — fable duyệt 12 bài: dùng được.** Đã sửa theo góp ý:
- A: nới 7 regex (doc-22, 24, 27, 28, 29, 31, 32), kèm test cho từng cách nói đúng mà fable nêu.
- B: công cụ ghi giữ `pending` cho bài mà đoạn ghi được không chứa đáp án trong 400 ký tự đầu.
  Mình thêm một điều kiện nữa: cũng giữ `pending` khi không đoạn nào đến từ `corpus_source.file`.
  Phép kiểm "đúng tệp nguồn" vốn được dự định chạy tay sau khi ghi, giờ chạy tự động. Manifest ghi
  `status`, `source_in_chunks`, và với bài giữ `pending` thì ghi thêm `retrieved`.
- C3: doc-31 có `must_not_mention` tên thư viện. Rủi ro trượt oan khi câu đúng nhắc tên theo kiểu
  phủ định đã ghi trong README.
- C4: README ghi rằng v0.1 đo "dùng kết quả để tính" bằng một bài, chỉ có tính chỉ báo.
- Dataset sha256 `6d3db491…`, vẫn là `agent-eval-v0.1` vì chưa gộp. Test: 74 passed. Đã kiểm lại
  `evidence` của 12 bài trên nội dung DB lab: đạt cả 12.

**27/10 tối — ghi truy xuất + baseline (GPU 18:40–18:54).**

- fable duyệt v0.1 ở `6896cf1`: đạt.
- Ghi truy xuất: stack lab chạy từ worktree, `DATABASE_URL` đọc từ `.env` thật mà không in ra. Kết
  quả 12/12 recorded, không bài nào giữ `pending`. Đoạn chứa đáp án luôn ở hạng 1–3. Đã tắt stack,
  cổng 8100 trống. Commit `6a2c3f9`, dataset sha256 `19d59249…`. Manifest của bản ghi thiếu tên
  model reranker (`/models` không có vai trò này), nhưng có cờ `rag.reranker: true`.
- Baseline (`--probe`, PYTHONUTF8=1, cây sạch, `verified: true`): r1 33/40 (model nạp lạnh), r2
  34/40, r3 34/40, t0.4 29/40. Báo cáo ở
  `data/evaluation/results/kept/agent-eval-v0.1-baseline-20261027/REPORT.md`, và có một mục trong
  `docs/RESULTS.md`.
- Hai con số opus yêu cầu:
  - Số bài recorded nhận phải đoạn có phần đầu trùng: 3 mỗi lần ở t0 (doc-23, 26, 28), 4 ở t0.4
    (thêm doc-25). Không đoạn nào là đoạn chứa đáp án.
  - Số `tool_result` bị cắt ở 2400 ký tự: r1 7, r2 6, r3 6, t0.4 7. Ở bài tài liệu, việc cắt không
    làm mất đáp án. Ở hist-05 thì có: chế độ "tin mới nhất" của `search_history` mất 8/18 tin, đúng
    những tin mới nhất.
- Chấm tay 16 lượt, khớp kết luận 15/16. Lệch duy nhất là doc-18, lỗi bộ chấm do regex quá hẹp.
- Phát hiện cho 09: r2 và r3 giống hệt nhau từng byte, còn r1 (lạnh) khác ở 15/40 câu trả lời. So
  trước/sau ở t0 + seed phải có một lần khởi động bỏ đi. Nguyên nhân chưa đo.
- Chờ chốt: doc-18 nên (a) sửa và chạy lại ngay, hay (b) để nguyên và sửa ở v0.2. Danh sách đầy đủ
  ở mục "Cần chủ dự án hoặc điều phối chốt" trong REPORT.md.

**27/10 — opus chốt doc-18: (b).** Baseline giữ đúng như đã đo (r2/r3 34/40). Số đếm tay 35/40 đã
ghi trong REPORT.md kèm lý do: doc-18 trượt oan vì regex chỉ nhận "ba ngày". doc-18, hist-05 ("tuần
này") và mẫu `no_access` sẽ sửa ở v0.2 rồi chạy lại một lần. README của bộ bài có thêm quy tắc: mọi
lần so trước/sau ở t0 + seed phải có một lần khởi động bỏ đi ở mỗi phía.
