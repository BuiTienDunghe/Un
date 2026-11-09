# Sổ đo

Mọi lần đo của dự án được ghi ở đây, kể cả những lần hỏng, bị dừng hoặc cho kết quả âm. Mỗi lần một mục, mục mới nhất ở trên cùng.

Thư mục `data/evaluation/results/kept/*/` vẫn là nơi giữ bằng chứng chi tiết. `docs/RESULTS.md` chỉ chép lại những số đủ chắc để đưa ra ngoài (README, CV), và mỗi số ở đó phải có mục tương ứng ở đây.

## Mẫu một mục

```
## dd/mm/yyyy — <đo cái gì, một dòng>

- **Câu hỏi:** điều muốn biết, một câu.
- **Điều kiện:** commit, model và digest, phiên bản Ollama, số bài/bộ dữ liệu, nhiệt độ/seed, đối chứng cùng ngày hay không.
- **Đăng ký trước:** đường dẫn, hoặc "không" (phép thử tìm nguyên nhân sau khi thấy số).
- **Kết quả:** bảng.
- **Kết luận:** một hai câu; dự đoán đúng hay sai.
- **Trạng thái:** xong / dừng giữa chừng / hỏng / chờ quyết định.
- **Bằng chứng:** đường dẫn; ghi "(chỉ trên máy)" nếu thư mục không nằm trong git.
```

---

## 10/11/2026 — Test sau khi gộp nhánh model nhỏ vào main, và migration database thật

- **Câu hỏi:** main sau khi gộp `c57aa3e` + sửa chốt chặn `5dc1407` (merge `4a57dfe`) có qua đủ bộ test, và database thật lên `20261109_39` có giữ nguyên dữ liệu cũ?
- **Điều kiện:** checkout chính tại `4a57dfe`. Test: container `postgres:16-alpine`/`redis:7-alpine`/`qdrant:v1.18.2` dùng một lần (cổng 55441/56381/56334), lần này đặt cả `REDIS_URL`; Ollama cổng chết, CUDA ẩn, migration tới head trên database trống. Database thật: sao lưu bằng `scripts.backup_worker --once --force` trước, rồi `alembic upgrade head` theo `.env`; Postgres thật bật rồi tắt lại, API/bot không khởi động.
- **Đăng ký trước:** không; kiểm thử hồi quy sau khi gộp.
- **Kết quả:**

  | Kiểm | Kết quả |
  |---|---|
  | Backend đủ bộ | 2.220 đạt, 0 hỏng (02:42–02:48) |
  | Bộ gốc | 242 đạt, 1 bỏ qua |
  | Chốt chặn với `.env` thật, không gọi mạng | qua; general `general-small-v1`, OCR `ocr-ovis-v1`, extractor tắt |
  | Bản sao lưu `local-ai-20261109-194042.dump` | 5,6 MB, 40 bảng có dữ liệu (`pg_restore --list`); bộ xoay vòng tự xoá bản 21/10 như thường lệ |
  | Database thật sau migration | `20261109_39`; 3 dòng mốc `source_memory_states`, 0 `source_memories`; giữ 24 `documents`, 3 `discord_memories`, 3 `memories` |
- **Kết luận:** gộp xanh; database thật đã lên phiên bản mới và còn nguyên dữ liệu cũ.
- **Trạng thái:** xong; chưa push, chưa khởi động API/bot bằng bản mới.
- **Bằng chứng:** `data/evaluation/results/kept/c57-compare-20261110/tests/main-backend-full.xml`, `main-root.xml`.

## 10/11/2026 — Bản cũ (main, 9B) so với bản mới của Codex (`c57aa3e`, chỉ model nhỏ)

- **Câu hỏi:** nhánh `codex/tool-state-continuity` (`c57aa3e`, đã push lên nhánh cùng tên) cải thiện được gì so với main `3eac7f6`, tách phần do đổi model khỏi phần do code?
- **Điều kiện:** Ollama 0.40.13; GPU RTX 5060 Ti rảnh, 40 °C lúc bắt đầu; API, bot và stack thật đang tắt. Bản mới chạy từ worktree tách riêng `local-ai-core-wt/check-c57aa3e` (detached), với `DISCORD_MEMORY_EXTRACTOR_MODEL=` rỗng trong tiến trình vì `.env` thật còn tag 9B làm chốt chặn từ chối khởi động; `.env` không bị sửa. Bản cũ chạy từ checkout chính (code `3eac7f6`, chỉ tài liệu bẩn). Mọi lượt tuần tự, dỡ mọi model giữa các lượt, dừng nếu GPU ≥ 85 °C hoặc có League.
  - Test: đủ bộ backend và bộ gốc trên `c57aa3e`, Postgres 16/Redis 7/Qdrant v1.18.2 trong container dùng một lần (cổng 55441/56381/56334), migration tới head.
  - Agent Eval v0 (66 bài, bộ chấm giống hệt ở hai bản), nhiệt độ 0, seed 42, dỡ model giữa từng bài: A = main + `qwen3.5:9b` (bản đang ship); C = main + `--model qwen3.5:2b` (chỉ đổi model); B = `c57aa3e`, model theo registry (`general-small-v1`, 2B). A–C là phần do model, C–B là phần do code/cấu hình mới.
  - OCR: 10 ảnh tiếng Việt tự tạo của Codex (`data/benchmarks/ocr_evidence/v1`, có văn bản chuẩn từng ảnh, 3 ảnh mới Codex đã xem để chỉnh cách gom cột). Mỗi bản OCR chép 10 ảnh ở 200 dpi: `ocr-v2` (9B) và `ocr-v1` (GLM) của main; `ocr-ovis-v1` và `ocr-small-v1` (GLM) của nhánh. Đo tỷ lệ ký tự sai so với văn bản chuẩn (sau chuẩn hoá NFC và gộp khoảng trắng) và giây/ảnh. 28 câu hỏi: bản mới chạy nguyên `ocr_evidence_eval` (Ovis + LFM3 đọc bằng chứng); bản cũ xấp xỉ bằng 9B đọc toàn văn bản OCR rồi trả lời — cách này rộng tay với bản cũ hơn đường RAG thật.
- **Đăng ký trước:** mục này, viết trước khi chạy. Dự đoán: A > C (model nhỏ yếu hơn, 08/11 là 57 so với 47); B ≈ C vì tính năng nhớ công cụ tắt; Ovis sai nhiều ký tự hơn `ocr-v2` nhưng nhanh hơn và ít VRAM hơn; mọi bản mới dùng ít VRAM hơn. Không chọn lại phép đo sau khi thấy số.
- **Kết quả:**

  Test trên `c57aa3e` (02:00–02:06):

  | Lượt | Đạt | Hỏng | Bỏ qua |
  |---|---:|---:|---:|
  | Backend đủ bộ, có Postgres/Redis/Qdrant tạm | 2.214 | 4 | 0 |
  | 4 bài hỏng chạy lại, thêm `REDIS_URL` trỏ container test | 5 (gồm bài cùng tệp) | 0 | 0 |
  | Bộ gốc (bot, launcher) | 242 | 0 | 1 |

  Cả 4 bài hỏng đều đọc `/health.status`: lượt đầu tôi chỉ đặt `REDIS_TEST_URL`, nên kiểm sức khoẻ gọi Redis mặc định ở cổng 6379 (đang tắt) và báo "degraded". Lỗi do môi trường của tôi, không phải code; Codex báo 2.217 đạt. Migration tới head `20261109_39` chạy sạch trên database trống.

  Database thật (chỉ đếm, không đọc nội dung; bật container rồi tắt lại): 3 `discord_memories` active, 3 `memories` (web), 10 `discord_condensation_propositions`, alembic ở `20261102_38`. Đây là cỡ phần trí nhớ cũ không chuyển sang v2.

  Đo trên GPU (02:04–02:28, không lượt nào dừng, nhiệt cao nhất 75 °C):

  | Agent Eval /66 | Đạt | Trung vị/bài | VRAM đỉnh |
  |---|---:|---:|---:|
  | A main + 9B | 57 | 4,4 s | 6.950 MiB |
  | C main + 2B | 47 | 2,1 s | 3.376 MiB |
  | B `c57aa3e` + 2B | 47 | 2,0 s | 3.376 MiB |

  C → B: 0 bài đổi. A → B: mất 15, được 5 (McNemar hai phía p ≈ 0,04); mất gồm nt-01, nt-02 (gọi công cụ khi không được gọi).

  | OCR, 7 ảnh có văn bản chuẩn | Sai chữ và số | Sai thô | Giây/ảnh | VRAM đỉnh |
  |---|---:|---:|---:|---:|
  | cũ `ocr-v2` 9B | 0/887 | 3,38% | 2,10 | 7.046 MiB |
  | mới `ocr-ovis-v1` | 2/887 | 41,86% | 1,79 | 1.658 MiB |
  | GLM (cũ `ocr-v1` / mới `ocr-small-v1`) | 83 / 88 trên 887 | 12,2 / 12,7% | 0,91 | 3.880 MiB |

  Sai thô là thước đã đăng ký; thước "chữ và số" thêm SAU khi thấy số, vì đọc văn bản thấy Ovis trả bảng dạng HTML và 9B tách cột bằng tab, còn văn bản chuẩn dùng `|`. Bỏ ký hiệu trình bày thì Ovis chỉ còn 2 lỗi dấu thật. VRAM là đỉnh của từng lượt riêng: bản cũ dùng lại 9B đã nạp cho OCR, bản mới nạp 2B, Ovis và LFM3 riêng; tổng khi chạy cùng lúc chưa đo. Câu hỏi trên 10 ảnh: cũ (9B đọc toàn văn OCR, xấp xỉ) 27/28, mới (Ovis + LFM3) 28/28.

  Kiểm khẳng định của Codex về câu phủ định: chốt cũ `auto_apply_allowed` = False cho "Tôi thích cà phê đen" từ "Hãy nhớ tôi không thích cà phê đen" (bước kiểm phủ định bắt được), tức chốt cũ không tự lưu câu sai đó.
- **Kết luận:** dự đoán đúng ở Agent Eval (A > C, B = C) và VRAM; sai ở OCR: Ovis gần bằng 9B về chữ (2 lỗi dấu trên 887), không kém rõ như dự đoán, lại nhanh hơn và chỉ cần 1/4 VRAM. Phần lợi của bản mới là tốc độ và bộ nhớ GPU; phần mất là năng lực trợ lý (10 bài), do đổi model chứ không do code. Bộ OCR và câu hỏi do Codex viết nên chỉ là kiểm hồi quy.
- **Trạng thái:** xong.
- **Bằng chứng:** `data/evaluation/results/kept/c57-compare-20261110/REPORT.md` cùng thư mục; bản thô `data/evaluation/results/c57-compare-20261110/` (chỉ trên máy).

## 09/11/2026 — Memory v2 source-backed trên nhánh tool-state-continuity

- **Câu hỏi:** có thể lưu/đọc/quên có kiểm nguồn mà bỏ hoàn toàn 9B khỏi đường chạy không?
- **Điều kiện:** baseline 966e6b7, PostgreSQL/Redis/Qdrant disposable; Qwen3.5:2b local, temp 0, seed 424242, context 16384. Không chạy 9B đối chứng hay teacher.
- **Đăng ký trước:** `data/evaluation/results/kept/memory-v2-source-20261109/PREREGISTER.md`.
- **Các vòng đầu:** source tests 24/24; hồi quy ban đầu 1684 pass/20 fail; targeted 215 pass/8 fail; hồi quy vòng hai 2136 pass/12 fail. Chi tiết và cả lỗi setup được ghi trong `RUN_HISTORY.md`.
- **Reader:** sáu ca tổng hợp: ban đầu 3/6 đáp án đầy đủ; chỉnh cách đọc lời tự khai rồi 6/6 trên CÙNG sáu ca. Chấm thủ công, không phải heldout, không chứng minh parity với model cũ.
- **Kiểm chứng cuối:** backend 2198 passed; bot/launcher 242 passed, 1 skipped; review 179 passed; post-review 85 passed gồm 12 vòng hai luồng. Schema không drift; registry 0 error/2 warning lịch sử. Có JUnit/log cho từng lượt.
- **Ca mới chưa chỉnh prompt:** 5/6 đúng ý chính, một ca vai trò Redis/PostgreSQL từ chối quá mức dù truy hồi đúng. Giữ nguyên kết quả âm, không chấm lại thành pass.
- **Kết luận:** lưu nguồn và trả lời là hai tiêu chí riêng. Cơ chế lưu/thu hồi đã kiểm được; reader nhỏ vẫn có giới hạn suy luận và chưa chứng minh parity toàn diện. Hoàn tất trên nhánh thử nghiệm; không triển khai vào dữ liệu thật.
- **Bằng chứng:** `data/evaluation/results/kept/memory-v2-source-20261109/`.

## 09/11/2026 — Phản biện bộ đo state, thêm đường BFCL và kiểm CPU v2

- **Câu hỏi:** bộ xác nhận có đang đo đúng code state sản phẩm, đủ tách khỏi các bài đã dùng chẩn đoán, và có bảo toàn lần đo dở không?
- **Điều kiện:** chỉ nhánh `codex/tool-state-continuity`, sau `5fd709a`, implementation `eef0988`; main vẫn `3eac7f6`, không merge/push. Feature OFF, guide/model/max_steps không đổi. Container test tạm, CUDA ẩn, Ollama cổng chết, cloud key trống, guard loopback chặn model; real-reranker test CPU cache offline. Không inference model sinh.
- **Đăng ký trước:** cập nhật v2 của `.scratch/tool-state-continuity/PREREGISTRATION.md` trước inference. Bộ tự viết là hồi quy; tập xác nhận công khai chọn ID bằng hash, không dùng điểm để chọn.
- **Kết quả:**

  | Kiểm | Kết quả |
  | --- | --- |
  | Nhóm BFCL/state v1; v2 | 95 đạt; 100 đạt, không lỗi/bỏ qua |
  | Full backend | 2.157 đạt, không lỗi/bỏ qua; 286,4 giây; còn 6 warning cũ |
  | Cú pháp/schema | 438 tệp Python hợp lệ; không drift |
  | Checker BFCL, model kịch bản | Oracle đạt, không làm gì trượt; không phải điểm model thật |
  | Chuẩn bị thực và dry-run | 512 ca, 18 lệnh; không Settings/.env/HTTP |
  | Provenance checker | 48 tệp code/dữ liệu liên quan trùng clone sau chuẩn hóa xuống dòng |
  | Script kiểm phụ đầu | FileNotFoundError do đường dẫn tương đối sau chdir; sửa resolve trước chdir, giữ bản ghi lỗi |
  | Xác nhận BFCL đã prepare | 300 ca/1.303 lượt người dùng mỗi nhánh; 3 loại ngoài multi_turn_base |
  | Pilot / chẩn đoán tùy chọn | 12 ca / 200 ca mỗi nhánh |

- **Kết luận:** BFCL có đường dùng chung recorder/budget/restore với sản phẩm, giữ executor/checker công khai. Runner không còn xóa trắng, resume không coi lỗi hạ tầng là hoàn tất và giữ attempts. Bộ ứng dụng không bị thổi thành bằng chứng chất lượng tổng quát; chưa có số thắng/thua hay latency GPU.
- **Trạng thái:** code/test/prepare v2 xong trên nhánh; chưa chạy GPU/model thật, chưa bật feature/chọn model, chưa gộp main. Không sửa dữ liệu timestamp cũ hoặc sổ main đang dở.
- **Bằng chứng:** `data/evaluation/results/kept/tool-state-validation-v2-2026-11-09/REPORT.md`, checks/XML/ID/verification/snapshot cùng thư mục; raw log `data/logs/tool-state-continuity-2026-11-09/review-*/` (chỉ trên máy). Lần script kiểm phụ lỗi vẫn được giữ.

## 09/11/2026 — Giữ kết quả công cụ qua lượt, kiểm cơ chế và chi phí CPU

- **Câu hỏi:** Web/Discord có giữ lại kết quả công cụ an toàn qua lượt và service restart, với overhead bao nhiêu? Chưa đo chất lượng model.
- **Điều kiện:** nhánh riêng `codex/tool-state-continuity`, base main `3eac7f6`; không sửa code main. Tính năng mặc định OFF. Giữ nguyên guide, model/registry, max_steps=3 và policy lookup/read-rest. PostgreSQL 16, Redis 7, Qdrant v1.18.2 tạm; CUDA ẩn, Ollama cổng chết, cloud key trống, guard loopback chặn cổng model. Real reranker sẵn có kiểm CPU offline; không chạy model sinh.
- **Đăng ký trước:** `.scratch/tool-state-continuity/PREREGISTRATION.md` trước inference; CPU là kiểm chức năng/overhead, không phải ngưỡng chất lượng. Chưa chọn model nhỏ, đã prepare cho 9B, LFM3 1.7B và Qwen 2B.
- **Kết quả:**

  | Lượt | Đạt / hỏng / bỏ qua |
  | --- | --- |
  | Small fixes | 65 / 0 / 2 |
  | State unit đầu | 72 / 1 / 9; sửa ghi envelope rỗng |
  | Focused v2 | 170 / 1 / 0; sửa fixture timestamp filesystem Windows |
  | Focused v3; v4 | 197 / 0 / 0; 202 / 0 / 0 |
  | Full v1 | 2.134 / 0 / 0; có cảnh báo reader thread cp1252 |
  | Full cuối | 2.139 / 0 / 0, 273,7 giây; còn 6 warning có sẵn |
  | Runner/grader cuối | 6 / 0 / 0; kiểm thay đổi cuối sau collection full |
  | Cú pháp/schema | 435 tệp Python hợp lệ; không drift |
  | Overhead OFF → ON, p50 / p95 | 23,39 → 35,97 ms / 29,68 → 43,10 ms |
  | SQL trung vị/lượt | 10 → 16 |
  | Ký tự message / schema, 72 lượt mỗi nhánh | 236.016 → 389.520 / 347.616 → 347.616 |
  | Lần gọi model giả | 144 → 144, cố định theo kịch bản |

- **Kết luận:** cơ chế giữ state, cô lập quyền, phiên bản tài liệu, receipt và quên dữ liệu đã qua CPU/DB tests. Trong fixture, ON thêm khoảng 12,58 ms ở p50 và 26,3% tổng ký tự message+schema. Không suy ra tăng chất lượng hay nhanh hơn trên model thật. State thêm có giới hạn mỗi conversation, không có migration/framework mới.
- **Trạng thái:** triển khai/test CPU xong; feature OFF; 26 ca/624 job mới chỉ prepare, chưa chạy inference; chưa ship hoặc thay model. Giữ mọi lượt lỗi.
- **Bằng chứng:** `data/evaluation/results/kept/tool-state-continuity-2026-11-09/REPORT.md`, checks/benchmark/manifest/XML cùng thư mục. Raw log dưới `data/logs/tool-state-continuity-2026-11-09/` (chỉ trên máy). Không đọc .env.

## 09/11/2026 — Test sau khi gộp `codex/backend-small-fixes` vào main

- **Câu hỏi:** main sau khi gộp (`3eac7f6`) có qua các test của nhánh, kể cả các bài database mà ba agent duyệt không chạy được?
- **Điều kiện:** checkout chính tại `3eac7f6`, `app` nạp từ checkout chính (đã in đường dẫn). GPU che, Ollama/Redis/Qdrant trỏ cổng chết, không ghi bytecode. Lượt 1: `POSTGRES_TEST_URL` gỡ, `DATABASE_URL` trỏ cổng chết. Lượt 2–3: container `postgres:16-alpine` dùng một lần, cổng 55692, database `review_merge_test`, migration tới head `20261102_38`, đã xoá container sau khi chạy. 01:38–01:42, máy rảnh.
- **Đăng ký trước:** không; kiểm thử hồi quy sau khi gộp.
- **Kết quả:**

  | Lượt | Tệp | Đạt | Bỏ qua | Hỏng |
  |---|---|---:|---:|---:|
  | 1. Unit, không database | 11 tệp Codex chạy + 5 tệp mới/đổi của nhánh (`test_source_page_counts`, `test_document_index_errors`, `test_database_url_contract`, `test_batched_document_listing`, `test_reranker_versions`) | 328 | 9 | 0 |
  | 2. Cùng 16 tệp, có Postgres | như trên | 335 | 2 | 0 |
  | 3. Database và migration | `test_batched_document_listing`, `test_worker_extractor_model`, `test_source_page_counts`, `test_database_url_contract`, 6 tệp discord memory/migration | 121 | 0 | 0 |

  2 bài bỏ qua ở lượt 2 cần Qdrant thật (`test_rebuild_scripts.py:113,155`). Có 3 cảnh báo luồng ở `test_bfcl_run` (tiến trình con đọc chữ UTF-8 bằng bảng mã cp1252); tệp test này không bị nhánh sửa, nên cảnh báo có từ trước.
- **Kết luận:** main sau khi gộp qua hết các test đã chạy. Đã chạy được bài "3 câu truy vấn cho 12 paper" mà ba agent phải bỏ qua. Chưa chạy toàn bộ bộ test.
- **Trạng thái:** xong.
- **Bằng chứng:** `data/evaluation/results/kept/codex-small-fixes-review-2026-11-08/` (`postmerge-focused.xml`/`.txt` cho lượt 2, `postmerge-sql.xml`/`.txt` cho lượt 3; đã bỏ tên máy và đường dẫn). Lượt 1 chỉ có dòng tổng kết trong phiên. Kết luận duyệt: `.scratch/arch-plan-review/reviews/codex-backend-small-fixes-405c7c5.md`.

## 09/11/2026 — Đối chiếu toàn pipeline cũ và ứng viên harness, kiểm chéo với ba subagent

- **Câu hỏi:** ứng viên giữ traffic + nới vòng + guide trung tính mạnh/yếu ở những bước nào so với cấu hình cũ; thay model general ảnh hưởng tới những pipeline nào khác?
- **Điều kiện:** đọc code/config tại head `c01d6dd`, báo cáo model nhỏ và chẩn đoán 08/11; không chạy inference/GPU hay benchmark latency mới, không sửa sản phẩm. Ba subagent đọc code, kiểm bằng chứng và đánh giá kiến trúc đã phản biện chéo cùng người tổng hợp. Các con số dưới đây chỉ được tính lại từ cùng 12 ca LFM3 cũ (48 lượt người dùng), không phải tập đánh giá mới.
- **Đăng ký trước:** không; đối chiếu code và số đếm dẫn xuất từ phép đo đã hoàn tất.
- **Kết quả:**

  | Cấu hình trên cùng mẫu | Đạt/12 | Request model | Tool call | Ép final do max_steps |
  |---|---:|---:|---:|---:|
  | Cũ: guide cũ/3 vòng/chỉ chữ | 4 | 113 | 67 | 6 |
  | Guide cũ/3 vòng/giữ traffic | 7 | 125 | 80 | 7 |
  | Guide cũ/10 vòng/chỉ chữ | 5 | 132 | 83 | 0 |
  | Guide cũ/10 vòng/giữ traffic | 8 | 143 | 95 | 0 |
  | Guide trung tính/10 vòng/giữ traffic | 9 | 134 | 86 | 0 |

  Tổng JSON messages cũ 316253 ký tự, tổ hợp tốt nhất 527764 (chưa gồm schemas). Đây là khối lượng request/context, không phải token/VRAM/latency. Việc tăng có cả phần công việc trước kia chưa hoàn tất.

- **Kết luận:** ứng viên cải thiện tiếp nối/làm nhiều bước trên mẫu, chưa phải pipeline sản phẩm mới. Không ghép 9/12 (LFM3 cả ba can thiệp), 11/16 Agent Eval (LFM3 chỉ đổi guide/cap3), và 0/8 irrelevance (Qwen2B chỉ đổi guide) thành điểm của cùng một cấu hình. Pipeline ingestion/retrieval/memory không được sửa bởi can thiệp harness; đổi general riêng lại tác động cả rewrite/RAG answer/ghi chú/research/contextual indexing, trong khi OCR/vision/extractor/verifier vẫn giữ9B nên chưa bảo đảm giảm residency. Context retention phải tích hợp cả Web và Discord cùng quyền, thu gọn theo loại tool và chống chạy lại hành động. Cơ chế thu gọn hiện có nhắc gọi lại tool cũ, không phù hợp để bật nguyên xi cho action history. Mô tả retrieval đã được kiểm lại: dense kiểm PostgreSQL trước RRF/rerank; BM25 dùng cache active snapshot, cập nhật chéo tiến trình theo TTL mặc định5s; không có kiểm active chung sau rerank.
- **Trạng thái:** xong; báo cáo phân biệt cấu hình hiện có, ứng viên đã đo và thiết kế đề xuất. Không kết luận nhanh hơn bao nhiêu hoặc VRAM giảm bao nhiêu khi chưa đo toàn tải.
- **Bằng chứng:** `data/evaluation/results/kept/harness-pipeline-comparison-20261109/REPORT.md`, `workload_comparison.json`, `config_snapshot.json`; nguồn số và request gốc trỏ về `harness-root-cause-20261108/` và `small-models/`. Các tệp đối chiếu chưa commit.

## 08/11/2026 — Cải tiến backend trên nhánh và xác nhận bằng CPU

- **Câu hỏi:** sửa cache số trang, bỏ SQL lặp khi liệt kê paper và phân loại lỗi index có giữ hồi quy, có hiệu quả so với base/main không?
- **Điều kiện:** chỉ worktree `codex/backend-small-fixes`, base `67260f3`; main tham chiếu `c01d6dd` không đổi code. Python 3.11.9, PostgreSQL 16 Alpine/Redis 7 Alpine/Qdrant v1.18.2 dùng một lần, không volume thật; database `backend_improve_test` và `backend_improve_perf_test`. CUDA ẩn; Ollama cổng chết; khóa cloud trống; guard chặn mạng ngoài loopback và cổng model. Reranker real từ cache chạy CPU offline.
- **Đăng ký trước:** phạm vi/phương pháp ở `.scratch/backend-small-fixes-followups/IMPLEMENTATION.md` trước lượt focused; không phải đăng ký ngưỡng chất lượng model.
- **Kết quả:**

  | Lượt / đường | Kết quả |
  | --- | --- |
  | Focused ban đầu | 99 đạt |
  | Full đầu | 2029 đạt, 1 hỏng do real reranker còn thử mạng |
  | Reranker chỉ đồng bộ cờ offline | 19 đạt, 1 hỏng |
  | Reranker tiến trình offline mới | 20 đạt |
  | **Full cuối** | **2033 đạt, 0 hỏng, 0 bỏ qua** |
  | Cú pháp / schema | 423 tệp Python không lỗi cú pháp; không schema drift |
  | 100 paper lạnh: main / base / sau sửa | 403 / 304 / 4 SELECT; trung vị 720,45 / 610,27 / 96,87 ms |
  | 100 paper ấm: main / base / sau sửa | 103 / 4 / 4 SELECT; 99,29 / 13,46 / 25,29 ms |
  | 100 paper có metadata: main / base / sau sửa | 103 / 4 / 4 SELECT; 97,52 / 13,10 / 26,44 ms |

- **Kết luận:** đường fallback lạnh nhanh hơn và bỏ query theo từng paper; nguồn ổn định cho payload giống nhau. Đường metadata/cache ấm chậm hơn base do kiểm filesystem để tránh cache cũ, vẫn nhanh hơn main trong fixture. Giữ đầy đủ các lượt lỗi; sửa test offline bằng tiến trình mới, không nới guard. Thay đổi source được kiểm bằng unit/SQL, không suy ra cải thiện chất lượng harness.
- **Trạng thái:** xong; không merge vào main. Khoảng chờ hạn mức duyệt không tính vào thời gian test.
- **Bằng chứng:** `data/evaluation/results/kept/backend-improvements-2026-11-08/REPORT.md`, XML/JSON kèm theo, script `.scratch/backend-small-fixes-followups/`; raw log/PDF tại `data/logs/backend-improvements-2026-11-08/` (chỉ trên máy).

## 08/11/2026 — Chẩn đoán harness: lịch sử công cụ, giới hạn vòng, system prompt và đọc văn bản dài

- **Câu hỏi:** vì sao model nhỏ chạy trong harness trượt những bài chạy trần làm được; lỗi ở code/prompt nào đã kiểm được bằng đối chứng?
- **Điều kiện:** head `c01d6dd`, không sửa code/cấu hình sản phẩm; giữ các thay đổi có sẵn của người dùng. Ollama 0.40.13; LFM3-1.7B `b36a103fe2f8` Q4_K_M và Qwen3.5-2B `324d162be6ca` Q8_0; nhiệt độ 0, seed 42, context 16384, think=false, gỡ/nạp từng bài. Bộ công cụ BFCL giả và fixture Agent Eval, không truy cập database thật. Trong một phần phiên có audit CPU/DB khác chạy đồng thời (mục dưới); không dùng thời gian để kết luận tốc độ. Không có turn mới dừng vì thời gian.
- **Đăng ký trước:** `data/evaluation/results/kept/harness-root-cause-20261108/PREREGISTRATION.md`; các phép bổ sung sau khi đọc dữ liệu ghi trước khi chạy trong `ADDENDUM.md`. Đây là mẫu chẩn đoán chọn sau khi thấy kết quả, không phải tập xác nhận để ship.
- **Kết quả:** 253 lượt bài trong 19 nhánh, không lỗi hạ tầng. Đối chứng LFM3 nhiều lượt mới tái lập đúng toàn bộ result (lệnh gọi và câu trả lời) 12/12 so với sáng. Hai đối chứng Agent Eval tái lập tập đạt/trượt cũ trên 16 ca/model.

  LFM3, cùng 12 ca chẩn đoán (8 ca trần đạt/harness trượt, 4 ca cùng đạt):

  | Guide | 3 vòng/chỉ chữ | 3 vòng/giữ công cụ | 10 vòng/chỉ chữ | 10 vòng/giữ công cụ |
  |---|---:|---:|---:|---:|
  | Cũ | 4/12 | 7/12 | 5/12 | 8/12 |
  | Trung tính theo tool thật | 5/12 | 7/12 | 8/12 | 9/12 |

  Prompt, cùng các ca đã chọn trước:

  | Phép thử | Guide cũ | Trung tính | Chỉ bỏ “hay kiến thức chung” |
  |---|---:|---:|---:|
  | 2B simple_python | 5/8 | 6/8 | 5/8 |
  | 2B irrelevance | 5/8 | 0/8 | 3/8 |
  | LFM3 Agent Eval | 6/16 | 11/16 | — |
  | 2B Agent Eval | 5/16 | 6/16 | — |
  | LFM3 nhiều lượt, 3 vòng/chỉ chữ | 4/12 | 5/12 | 3/12 |

  - Agent Eval 2B + chỉ thêm clock_note như chat thật: 7/16 (cứu nt-01, doc-31, hist-02; mất doc-25). Chỉ dùng persona bot thật ở task Discord: 6/16 (cứu hist-02). Eval vẫn khác tool registry/memory của sản phẩm; không gọi đây là production parity đầy đủ.
  - 2B doc-57, chỉ đổi prompt ghi chú: vẫn 0/1. Body HTTP trước cắt đã thiếu số đúng; không còn length stop ở bản focused nhưng vẫn ghi thiếu. Đối chứng định vị đưa đoạn nguồn 2000 ký tự: lấy được 265.000, vẫn chọn 330.000 của điều kiện khác và bỏ 870.000. Không chấm ca oracle thành bài Agent Eval đạt.
  - LFM3 doc-57 thực tế đạt cả bản cũ/mới và guide trung tính, dù ghi chú phần sau có nhiễu. Không gộp lỗi của 2B sang LFM3.
  - 6 cặp request cùng messages/schema/model alias qua `/api/chat` và `/v1/chat/completions`: 6/6 cùng call name/arguments. Chỉ kiểm được sáu request đó.
  - Probe không model tái hiện mất mã công cụ qua lượt, trần chuỗi thao tác, dict quá dài bị cắt hỏng JSON, và bộ kiểm số chấp nhận số đã xuất hiện trong lời model. Không có tool output bị cắt/bỏ mục trong các ca nhiều lượt cũ của hai model, nên không lấy lỗi JSON này giải thích cú tụt cũ.
  - Kiểm `test_bfcl_run.py`: lần đầu 20 đạt/1 trượt provenance vì Git sandbox khác chủ repo; chạy lại đúng bài với safe.directory trong môi trường tiến trình: 1/1 đạt. Clone BFCL được kiểm read-only đúng `6ea5797`, sạch; ba file checker/executor/trading_bot cài trong venv khớp byte clone. Manifest ghi bfcl_commit=unknown được giữ nguyên, xác minh bổ sung trong verification.json. Không đổi Git config toàn cục.
- **Kết luận:** mất state công cụ, prompt thiên hỏi đáp và cơ chế ép trả lời có tác động tương tác; tăng vòng riêng lẻ hoặc bỏ một câu không sửa hết, còn có hồi quy. Ca 138 nới vòng tự thêm watchlist dù chỉ được hỏi phân tích. Hai ca còn trượt ở bản tốt nhất (104,106) đạt trạng thái/nội dung cần nhưng thiếu response trung gian/đúng dạng BFCL; không gọi mọi bài trượt là không làm được việc. Đọc dài của 2B còn lỗi chọn dữ kiện/điều kiện áp dụng sau khi thử prompt và trích đoạn ngắn. Chưa sửa sản phẩm hoặc quyết định đổi model từ mẫu này.
- **Trạng thái:** xong; đã đọc độc lập lại số liệu và code. Các file nguồn không đổi hash; Ollama giữ phiên bản và đã gỡ model sau đo.
- **Bằng chứng:** `data/evaluation/results/kept/harness-root-cause-20261108/REPORT.md`, `new_analysis.json`, `ae_analysis.json`, `verification.json`, `prompt_inventory.json`, `baseline_reproduction.json`, `code_probe_results.json`, `endpoint_parity.json`, `oracle_excerpt.json`; request/body HTTP và kết quả từng bài ở `runs/*/` (chỉ trên máy, chưa commit).

## 08/11/2026 — Audit backend-small-fixes: hồi quy đầy đủ và so main trên database riêng

- **Câu hỏi:** nhánh có hồi quy mới không, và tối ưu listing có tốt hơn main trong phép đo trực tiếp không?
- **Điều kiện:** main `c01d6dd`, nhánh `67260f3`; Python 3.11.9; PostgreSQL 16 Alpine, Redis 7 Alpine, Qdrant v1.18.2 dùng một lần trên localhost cổng ngẫu nhiên, không volume dữ liệu thật. Ollama cổng chết, khóa cloud trống, GPU ẩn khỏi Python. Toàn bộ backend suite; benchmark service dùng cùng fixture, đảo thứ tự hai nhánh. Có phép chẩn đoán model khác chạy đồng thời: thời gian chỉ tham khảo, không khẳng định phép kia không chịu tranh tài nguyên.
- **Đăng ký trước:** không; kiểm hồi quy và đo chẩn đoán, không đánh giá chất lượng model.
- **Kết quả:**

  | Lượt/đường gọi | Kết quả |
  | --- | --- |
  | Backend đầy đủ, môi trường đầu | 1906 đạt, 8 hỏng, 66 lỗi thiết lập |
  | Chạy lại sau sửa tên database và cờ offline cho loader giả | 75 đạt; tổng trạng thái cuối 1980 ca duy nhất đều đạt |
  | Parse source Python / schema check | 258 tệp không lỗi cú pháp; Alembic check không có drift |
  | 500 tài liệu, main → nhánh | 1001 → 3 SELECT; trung vị 844,35 → 33,17 ms |
  | 500 paper biết số trang, main → nhánh | 503 → 4 SELECT; 441,59 → 36,69 ms |
  | 500 paper cache lạnh, main → nhánh | 2003 → 1504 SELECT; 3152,32 → 2767,08 ms; vẫn đọc 500 PDF |
  | Payload trên các cỡ/đường gọi | 20/20 cỡ/đường giống nhau |
  | Probe cache page count sau thay PDF | cả hai nhánh giữ 8 dù tệp mới có 12 trang |

- **Kết luận:** giảm truy vấn được kiểm trực tiếp, có lợi rõ cho listing lớn trong môi trường đo; chưa thấy hồi quy mới trong bộ kiểm đã chạy. Không phải một lượt backend xanh duy nhất: lỗi môi trường ban đầu được giữ trong hồ sơ. Benchmark đầu dừng do banner PDF phá JSON parser, đã sửa parser rồi chạy lại toàn bộ. Cache page count cũ và contextualization khác giữa API/worker là vấn đề có sẵn; agent loop/prompt/model giống main nên chưa có cải thiện chất lượng harness do nhánh.
- **Trạng thái:** xong; không sửa sản phẩm, không merge/commit.
- **Bằng chứng:** `data/evaluation/results/kept/backend-small-fixes-audit-2026-11-08/REPORT.md`, XML/JSON kèm theo; script `.scratch/backend-small-fixes-audit/`. Log gốc `data/logs/backend-small-fixes-audit/` (chỉ trên máy).

## 08/11/2026 — Chạy lại bài SQL của nhánh `codex/backend-small-fixes` trên Postgres riêng

- **Câu hỏi:** 9 bài SQL theo lô và wiring worker của nhánh có đạt khi người duyệt tự chạy không?
- **Điều kiện:** worktree nhánh tại `67260f3` (code giống `0062f9b`, chỉ commit tài liệu đổi). Container `postgres:16-alpine` dùng một lần, cổng 55691, database `review_smallfixes_test`, migration tới head `20261102_38`; đã xoá container sau khi chạy. `POSTGRES_TEST_URL` và `DATABASE_URL` đặt tường minh vào database đó. GPU che, Ollama/Redis/Qdrant trỏ cổng chết, không ghi bytecode. Khoảng 13:29, máy rảnh (lần đo model nhỏ đã xong, GPU 0 %).
- **Đăng ký trước:** không; kiểm thử hồi quy khi duyệt.
- **Kết quả:**

  | Lượt | `app` nạp từ | Đạt | Hỏng |
  |---|---|---:|---:|
  | 1 | checkout chính (lỗi của tôi: `PYTHONPATH` viết kiểu `/c/...`, Python Windows bỏ qua) | 6 | 3 |
  | 2 | worktree (đã in đường dẫn) | 9 | 0 |

- **Kết luận:** nhánh đạt 9/9, khớp lượt của Codex. Lượt 1 không nói gì về nhánh. Nó chỉ cho thấy 3 bài theo lô hỏng khi chạy trên code cũ, tức là các bài này thật sự kiểm thay đổi của nhánh. Tôi chỉ xem lý do hỏng của bài paper (5 câu SELECT thay vì 3). Hai bài còn lại chưa xem; đoán là do code cũ thiếu `latest_runs`.
- **Trạng thái:** xong.
- **Bằng chứng:** chỉ có dòng tổng kết pytest trong phiên này; kết luận duyệt ở `.scratch/arch-plan-review/reviews/codex-backend-small-fixes-67260f3.md`.

## 08/11/2026 — Test của Codex chồng lên lần đo model nhỏ: bài nào bị ảnh hưởng

- **Câu hỏi:** lượt test unit của Codex (02:47:41, 55 giây) và SQL (02:50:24, 5 giây) có làm đổi điểm của job đo nào không?
- **Điều kiện:** dựng lại thời điểm từng bài từ `logs/harness-qwen3-5-2b-simple_python.log` (thời gian chạy + thời gian nạp mỗi bài, chạy tuần tự), neo hai đầu: giờ bắt đầu job và giờ ghi tệp kết quả (02:48:05, lúc sinh xong). Đạt/hỏng lấy từ tệp điểm BFCL.
- **Đăng ký trước:** không; phép thử tìm nguyên nhân, làm sau khi Codex chỉ ra bản duyệt trước chưa kiểm độc lập.
- **Kết quả:**

  | Job | Chồng lên | Bài trong cửa sổ | Ảnh hưởng điểm |
  |---|---|---|---|
  | harness qwen3.5:2b simple_python | khoảng 24 giây cuối | neo đầu: 0; neo cuối: 6 (`394`–`399`), cả 6 đạt | không |
  | bare qwen3.5:2b simple_python | 02:48:21–02:50:29 (15 giây cuối lượt unit, Codex dựng container Postgres, lượt SQL), thêm 20 giây lượt test của tôi lúc ~02:57 | — | không thể: không có trần mỗi lượt, job 23 phút so với trần 267 phút, thoát 0, không bài lỗi |

  Ba bài hỏng ngay trước cửa sổ (`391`–`393`) hỏng vì sai nội dung (viết "British pounds" thay vì "GBP"), chạy 1,6–1,9 giây, không phải vì chậm.
- **Kết luận:** máy bận chỉ đổi được điểm khi làm một bài chạm trần thời gian, và không bài nào trong hai cửa sổ chạm trần. Cột "giây mỗi bài" của 2B chạy trần simple_python (3,4 giây, báo cáo model nhỏ) có lẫn khoảng 2 phút máy bận trong 23 phút; chưa đo lệch bao nhiêu.
- **Trạng thái:** xong.
- **Bằng chứng:** `data/evaluation/results/kept/codex-small-fixes-review-2026-11-08/` (`overlap.py`, `overlap_output.txt`); log gốc ở `data/evaluation/results/small-models-run/` (chỉ trên máy).

## 08/11/2026 — LFM3-1.7B và Qwen3.5-2B, chạy trần và trong harness, so với qwen3.5:9b

- **Câu hỏi:** model dưới 3B gọi công cụ tốt đến đâu so với 9B? Harness nâng hay hạ điểm của từng model? Có model nào đạt luật "đáng thử tiếp" đặt trước không?
- **Điều kiện:**
  - Code: runner giống nhau ở cả ba commit `b7457d5`, `eeb90be`, `ef0bc1f`; ba commit chỉ khác nhau ở bộ điều phối và đăng ký trước.
  - Model: `qwen3.5:9b` 6488c96f (Q4_K_M), `lfm3:1.7b` b36a103f (Q4_K_M), `qwen3.5:2b` 324d162b (Q8_0).
  - Chạy: Ollama 0.40.13 suốt lần đo; nhiệt độ 0, seed 42, ngữ cảnh 16 384, tắt suy nghĩ, gỡ model trước mỗi bài.
  - Bài: BFCL v4 gồm simple_python 400, irrelevance 240, multi_turn_base 200; Agent Eval v0 66 bài, chỉ chạy nhánh harness.
  - Thời gian: 08/11, 01:26–07:32, không lần tạm dừng nào. Bộ điều phối được khởi động lại lúc 02:06, đúng như kế hoạch trong phần bổ sung lúc 02:00. Manifest ghi `worktree_dirty: true` vì có tài liệu chưa commit; code không có gì chưa commit.
  - 9B simple_python dùng lại số ngày 07/11, vì chạy lại 81 bài cho kết quả giống hệt ở cả hai nhánh.
  - 9B multi_turn_base: nhánh harness là 159 bài ngày 07/11, không chạy lại để kiểm; nhánh trần không chạy, vì chủ dự án bỏ job 9B lúc 05:21.
  - 3 bài của 2B nhánh harness bị lỗi "Cannot connect to Ollama" (simple_python_71, multi_turn_base_40, multi_turn_base_102), tính là trượt.
- **Đăng ký trước:** `data/evaluation/results/kept/small-models/PREREGISTRATION.md`, gồm hai phần bổ sung lúc 02:00 và 05:21.
- **Kết quả** (số bài đạt):

  | | 9B trần | 9B harness | LFM3 trần | LFM3 harness | 2B trần | 2B harness |
  |---|---:|---:|---:|---:|---:|---:|
  | simple_python /400 | 367 | 352 | 359 | 363 | 287 | 341 |
  | irrelevance /240 | 197 | 201 | 135 | 166 | 179 | 82 |
  | multi_turn_base /200 | — | 31/159 | 103 | 38 | 43 | 29 |
  | Agent Eval /66 | — | 57 | — | 33 | — | 47 |

  So từng bài, McNemar chính xác. "A hơn" là số bài chỉ A đạt, "B hơn" là số bài chỉ B đạt:

  | A so với B | Bài | A hơn | B hơn | p |
  |---|---|---:|---:|---:|
  | LFM3: harness so với trần | multi_turn_base | 5 | 70 | <0,001 |
  | LFM3: harness so với trần | irrelevance | 63 | 32 | 0,002 |
  | 2B: harness so với trần | simple_python | 66 | 12 | <0,001 |
  | 2B: harness so với trần | irrelevance | 8 | 105 | <0,001 |
  | LFM3 harness so với 9B harness | simple_python | 33 | 22 | 0,18 |
  | LFM3 harness so với 9B harness | irrelevance | 15 | 50 | <0,001 |
  | LFM3 harness so với 9B harness | multi_turn_base (159 bài) | 18 | 18 | 1,0 |
  | LFM3 so với 9B | Agent Eval | 2 | 26 | <0,001 |
  | 2B so với 9B | Agent Eval | 5 | 15 | 0,04 |
  | 2B: harness so với trần | multi_turn_base | 15 | 29 | 0,049 |

  Cặp 2B nhiều lượt không đứng vững. Cả hai bài lỗi đều là bài 2B chạy trần làm đạt. Bỏ hai bài đó ra thì còn 15/28, p 0,07.

  Luật "đáng thử tiếp" (nhánh harness):

  | | simple ≥ 83,0 | irrelevance ≥ 78,75 | Agent Eval ≥ 51 | Không bài no_tool nào gọi công cụ | Đạt luật |
  |---|---|---|---|---|---|
  | LFM3 | 90,75 ✓ | 69,17 ✗ | 33 ✗ | ✓ | không |
  | 2B | 85,25 ✓ | 34,17 ✗ | 47 ✗ | nt-01, nt-02 ✗ | không |

- **Kết luận:**
  - Không model nhỏ nào đạt luật. Cả hai trượt ở irrelevance và Agent Eval.
  - Dự đoán: 7/15 khoảng dự đoán đúng. Hai dự đoán về hướng đều đúng: harness kéo 2B sang gọi công cụ, giúp simple_python và hại irrelevance. Sai nhiều nhất là LFM3 chạy trần multi_turn_base: dự đoán 15–35 %, đo được 51,5 %.
  - Phát hiện ngoài câu hỏi: harness làm LFM3 mất 70 bài multi_turn_base mà model chạy trần làm được.
- **Phép thử tìm nguyên nhân (không đăng ký trước, đếm sau khi thấy số):**
  - Bài LFM3 chạy trần đạt: ở những bài cần hơn 3 vòng gọi trong một lượt, harness làm mất 40/44; ở các bài còn lại, mất 30/59.
  - 24/70 bài bị mất không lần nào chạm trần 3 vòng. 13 bài trong số đó có một lượt bỏ trống, tức không gọi công cụ nào.
  - Tỉ lệ trượt khi có chạm trần so với khi không chạm: LFM3 94 % so với 59 %, 2B 90 % so với 76 %, 9B (159 bài) 88 % so với 73 %.
  - Ba nguyên nhân khả dĩ chưa tách được: trần 3 vòng, việc chỉ mang chữ sang lượt sau, và lượt bỏ trống.
  - Runner có sẵn `--max-steps` và `--carry-tool-traffic`, đêm nay đều để mặc định.
  - Đây là phép đếm, chưa phải phép thử nhân quả.
- **Trạng thái:** xong. Fable đã kiểm 08/11 và tính lại mọi số và mọi cặp so; không có số nào sai. Đã sửa 4 chỗ diễn giải (cặp 2B nhiều lượt, cách nói về trần vòng, ngày đo thời gian của 9B, các cặp còn thiếu). Chi tiết ở cuối `REPORT.md`.
- **Bằng chứng:**
  - `data/evaluation/results/kept/small-models/`: `analyze.py`, `analysis.json`, `diag_multi_turn.py`, `nine_harness_multi_turn_159_scores.json`, `REPORT.md`.
  - Kết quả thô ở `data/evaluation/results/small-models-run/` (chỉ trên máy): `progress.log`, và `<nhánh>/<model>/<bài>/scores.json`.

## 08/11/2026 — Chạy lại test chọn lọc khi duyệt nhánh `codex/backend-small-fixes`

- **Câu hỏi:** các test của nhánh có đạt khi người duyệt chạy lại không?
- **Điều kiện:** worktree nhánh tại `0062f9b`, Python 3.11 của `.venv`, `app` nạp từ worktree (đã kiểm đường dẫn). `POSTGRES_TEST_URL` gỡ, GPU che, Ollama và DB trỏ cổng chết, không ghi bytecode. Khoảng 02:57, chạy song song với job bare qwen3.5:2b của lần đo model nhỏ (nhánh bare không có giới hạn thời gian mỗi lượt).
- **Đăng ký trước:** không; kiểm thử hồi quy khi duyệt.
- **Kết quả:**

  | Tệp | Đạt | Bỏ qua | Hỏng |
  |---|---:|---:|---:|
  | `test_llm_factory`, `test_research_pure`, `test_research_api`, `test_model_router`, `test_discord_boundary`, `test_batched_document_listing` | 74 | 3 | 0 |

- **Kết luận:** khớp lượt của Codex. 3 bài bỏ qua là bài SQL theo lô (cần Postgres riêng), không chạy lại.
- **Trạng thái:** xong.
- **Bằng chứng:** chỉ có dòng tổng kết của pytest trong phiên này, không lưu tệp; kết luận duyệt ở `.scratch/arch-plan-review/reviews/codex-backend-small-fixes-0062f9b.md`.

## 08/11/2026 — Đếm commit để đánh giá plan "chia backend theo miền"

- **Câu hỏi:** nếu xếp file theo miền nghiệp vụ thay vì theo lớp, mỗi lần sửa có gọn vào ít chỗ hơn không; và file nào thực sự hay bị sửa?
- **Điều kiện:** `git log --since=2026-10-01 -- backend/app`, head `b7457d5`, 99 commit. "Thư mục" = thư mục cấp một dưới `backend/app/`. "Miền" = gán từng file theo từ khoá trong tên (luật trong `cochange.py`), thô, chưa kiểm tay từng file. Kèm một phép thử: gọi `ResearchService._json_call` với model general là `claude-haiku-5-5` (router giả, HTTP giả trả 404, không chạy Ollama thật).
- **Đăng ký trước:** không.
- **Kết quả:**

  | | Theo thư mục (hiện tại) | Theo miền (plan) |
  |---|---|---|
  | Trung bình chạm mỗi commit | 2,04 | 2,12 |
  | Commit chỉ chạm một chỗ | 54/99 | 52/99 |

  Commit chạm `models.py`/`settings`/`main.py`/`schemas` (vẫn dùng chung dù chia miền): 36/99. Số commit theo file: `agent_service.py` 44, `main.py` 27, `model_registry.py` 5, `postgres_document_service.py` 3, `research_service.py` 2, `chat.js` 3, `research.js` 2, `memory_repositories.py` 1. Phép thử research: tên model Claude được gửi tới `/api/chat` của Ollama, ra lỗi "Model claude-haiku-5-5 chưa có trong Ollama".

- **Kết luận:** xếp theo miền không làm lần sửa gọn hơn (cùng kết luận với đánh giá 27/10). Chỗ nóng duy nhất là vòng lặp agent và phần nối dây ở `main.py`. Phần tóm tắt paper sẽ hỏng nếu đổi general sang Claude.
- **Trạng thái:** xong.
- **Bằng chứng:** `data/evaluation/results/kept/cochange-2026-11-08/` (`cochange.py`, `output.txt`); đánh giá đầy đủ ở `.scratch/arch-plan-review/REVIEW.md`.

## 08/11/2026 — Kiểm thử các sửa nhỏ backend trong worktree riêng

- **Câu hỏi:** chặn research gửi model cloud nhầm sang Ollama, gom tạo client và truy vấn liệt kê theo lô có giữ đúng các hợp đồng đang dùng không?
- **Điều kiện:** gốc `eeb90be`, nhánh `codex/backend-small-fixes`, worktree riêng; model/HTTP giả. Lượt SQL dùng container PostgreSQL riêng, database `local_ai_smallfixes_test`, migration tới head. Không gọi model thật, không dùng database/Redis/Qdrant của các test đang chạy.
- **Đăng ký trước:** không; kiểm thử hồi quy, không đo chất lượng model hoặc độ trễ.
- **Kết quả:**

  | Lượt | Đạt | Bỏ qua | Hỏng |
  |---|---:|---:|---:|
  | Unit/API/provider/harness chọn lọc | 259 | 2 | 0 |
  | SQL theo lô và wiring worker | 9 | 0 | 0 |

- **Kết luận:** các kiểm thử đã chạy đều đạt. Hai bài rebuild cần PostgreSQL/Qdrant thật bị bỏ qua ở lượt unit. Bài SQL kiểm thứ tự, version active, ingestion mới nhất và truy vấn theo lô trên PostgreSQL riêng; chưa đo lợi ích thời gian. Research cloud trả lỗi chưa hỗ trợ rõ ràng; không bổ sung sinh JSON cloud. Bài router giả chỉ kiểm research dùng cấu hình được cung cấp, không kiểm quá trình fallback. Tổng truy vấn paper có thể tăng ở đường đọc tệp để lấy số trang. Worktree và database riêng vẫn dùng chung tài nguyên máy với lượt đo đang chạy; chưa chứng minh không có tranh tài nguyên.
- **Trạng thái:** xong.
- **Bằng chứng:** `data/evaluation/results/kept/backend-small-fixes-2026-11-08/` (`REPORT.md`, `unit.xml`, `postgres.xml`, `metadata-normalization.json`). XML công khai đã bỏ hostname và chuẩn hóa đường dẫn; kết quả testcase giữ nguyên, bản gốc giữ cục bộ trong thư mục bị Git bỏ qua. Đây là hiệu chỉnh báo cáo, không chạy thêm test.

## 07/11/2026 — Bỏ từng phần lời dặn của Ún trên các bài BFCL chênh

- **Câu hỏi:** phần nào của harness làm thua model trần ở simple_python (mục dưới)?
- **Điều kiện:** commit `9462fc5`, qwen3.5:9b `6488c96f`, Ollama 0.40.13, nhiệt độ 0, seed 42, gỡ model mỗi bài. 81 bài simple_python: 41 bài hai nhánh chênh nhau + 40 bài cả hai cùng đạt (chọn ngẫu nhiên, seed 42). Ba bản lời dặn chạy liền nhau 17:02–17:30, bản nguyên bản là đối chứng.
- **Đăng ký trước:** không. Đây là phép thử tìm nguyên nhân sau khi đã thấy kết quả.
- **Kết quả:**

  | Lời dặn | Đạt / 81 | 28 bài chỉ harness trượt | 13 bài chỉ trần trượt | 40 bài cùng đạt | Trả lời bằng chữ |
  |---|---|---|---|---|---|
  | Nguyên bản | 53 | 0 | 13 | 40 | 23 |
  | Bỏ hết (chỉ còn luật chống chèn lệnh) | 74 | 25 | 9 | 40 | 3 |
  | Chỉ bỏ câu "Chỉ gọi công cụ khi … kiến thức chung thì trả lời thẳng, không gọi gì." | 74 | 23 | 11 | 40 | 0 |

- **Kết luận:** câu "kiến thức chung thì trả lời thẳng" là nguyên nhân chính: bỏ câu đó thì không còn bài nào trả lời bằng chữ. Bản nguyên bản tái lập đúng từng bài của lần chạy lớn. Còn 4 bài sai giá trị (lãi suất 5,0 thay 0,05…) chỉ hết khi bỏ toàn bộ lời dặn, chưa tách được câu nào gây ra. Chưa đo tác động lên Ún khi chat thật (Agent Eval).
- **Trạng thái:** chờ chọn cách sửa lời dặn (bỏ / viết lại / giữ).
- **Bằng chứng:** `data/evaluation/results/bfcl-guide-ablation/` (chỉ trên máy): `ids.json`, `groups.json`, `guide_variant.py`, mỗi bản một thư mục có `guide.txt` và `scores.json`.

## 07/11/2026 — BFCL phạm vi lớn: model trần và harness (dừng sau 1/11 hạng mục)

- **Câu hỏi:** trên 2 190 bài BFCL không live và nhiều lượt, harness hơn hay kém model trần, theo từng hạng mục?
- **Điều kiện:** qwen3.5:9b `6488c96f`, Ollama 0.40.13 (không đổi suốt lần chạy), nhiệt độ 0, seed 42, ngữ cảnh 16 384, tắt suy nghĩ, gỡ model mỗi bài. Harness commit `2ddb14a` (14:55–15:46), trần `9462fc5` (15:47–16:14), cùng bộ chấm gốc của BFCL. Hai nhánh chạy xen kẽ theo hạng mục.
- **Đăng ký trước:** `data/evaluation/results/kept/bfcl-full/PREREGISTRATION.md` (`2ddb14a`).
- **Kết quả (simple_python, 400 bài):**

  | | Đạt | Tỉ lệ |
  |---|---|---|
  | Trần | 367 | 91,75 % |
  | Harness | 352 | 88,0 % |

  Bài chênh: 28 chỉ harness trượt, 13 chỉ trần trượt; McNemar chính xác hai phía p = 0,03. Trả lời bằng chữ thay vì gọi hàm: harness 25, trần 6; các lỗi khác 23 và 27.

- **Kết luận:** dự đoán "chênh trong ±3 điểm" **sai**: harness kém 3,75 điểm, có nghĩa thống kê. Nguyên nhân xem mục trên.
- **Trạng thái:** dừng theo lệnh chủ dự án lúc 17:00. multi_turn_base của harness dở 159/200, chưa chấm, nhánh trần chưa chạy; 9 hạng mục còn lại chưa chạy. Chạy lại cùng lệnh thì simple_python được bỏ qua.
- **Bằng chứng:** `data/evaluation/results/bfcl-full-run/` (chỉ trên máy): `progress.log`, `<nhánh>/<hạng mục>/scores.json`. Bộ điều phối: `data/evaluation/results/kept/bfcl-full/run_full_bfcl.py`.

## 06/11/2026 — Model trần trên BFCL so với harness, 33 bài

- **Câu hỏi:** cùng model, vòng lặp gốc của BFCL so với vòng lặp của Ún thì bên nào điểm cao hơn?
- **Điều kiện:** 33 bài `ids_v1.json`, qwen3.5:9b `6488c96f`, Ollama 0.40.13, nhiệt độ 0, seed 42, ngữ cảnh 16 384, tắt suy nghĩ. Trần 11:59–12:04, đối chứng harness `ctl2` 12:04–12:09.
- **Đăng ký trước:** `data/evaluation/results/kept/bfcl-bare/PREREGISTRATION.md` (`b712d26`).
- **Kết quả:**

  | | Harness `ctl2` | Trần |
  |---|---|---|
  | Tổng | 25/33 | 23/33 |

- **Kết luận:** chênh 2 bài, chưa phân biệt được. Dự đoán "trần 26–29" **sai**. Vòng lặp 20 bước của BFCL không cứu được bài 128 và 180.
- **Trạng thái:** xong.
- **Bằng chứng:** `data/evaluation/results/kept/bfcl-bare/REPORT.md` (`e04d26d`).

---

## Trước khi có sổ (ghi bù 07/11/2026)

Các lần đo dưới đây có trước khi có sổ này. Mỗi dòng tóm tắt một báo cáo trong `data/evaluation/results/kept/`. Muốn biết điều kiện đo đầy đủ thì mở báo cáo đó. Các số đo retrieval, embedding và chunker từ 08–09/2026 nằm ở `docs/RESULTS.md`.

| Ngày | Thư mục | Câu hỏi đo | Kết quả chính | Kết luận / trạng thái |
|---|---|---|---|---|
| 06/11/2026 | `forced-honesty` | Rà và sửa harness trước khi đo BFCL đầy đủ | BFCL 33 bài (bộ chạy v2) 25/33 → 25/33; Agent Eval 66 bài 57 → 57; nhắc việc hẹn nhầm 1/5 → 0/5 | Không bài nào đổi. Mốc BFCL đúng là 25/33 (26/33 cũ bị chấm sai). H1/H2 chờ chủ dự án |
| 03/11/2026 | `agent-eval-read-rest` | Code tự đọc nốt tài liệu trên v0-long.2 | ctx-01..07: 0/7 → 4/7 → 5/7 → 6/7; 66 bài v0: 55 → 56 | 6/7 chưa phải số trên dữ liệu chưa từng thấy. Báo cáo ghi `agent.read_rest` tắt |
| 02/11/2026 | `harness-fix-239b67` | Nguyên nhân các bài hỏng BFCL/Agent Eval; thử H1, H2, H3 | BFCL 26/33 → H1 27, H2 27, H1+H2 28/33; Agent Eval 54/66 → H3 55, H3b 55/66 | Dự đoán cho H2 sai. Cả ba cờ vẫn tắt, chờ chủ dự án quyết |
| 02/11/2026 | `agent-eval-v0.8-wave2` | Đợt 2: dọn ngữ cảnh (trần 4 000) và đọc văn bản dài | 66 bài: đối chứng 54, dọn 54, đọc dài 54; BFCL 26/33 | Không đổi điểm. Bộ bài gần như không chạm tới hai tính năng, chưa có bằng chứng lợi hay hại |
| 02/11/2026 | `agent-eval-v0.8-h3b-on` | H3b tắt và bật, đo cùng ngày | 66 bài: 54 → 55; 65/66 câu trùng chữ, chỉ doc-25 đổi | Mẫu nhận diện chỉnh trên chính bộ bài này, nên chưa nói được gì ngoài 66 bài |
| 02/11/2026 | `agent-eval-v0.8-bisect-41` | Vì sao mốc tụt từ 58 xuống 54? | 66 bài: cùng `717e4d3` cho 58 (29/10) và 55 (02/11); phần do code chỉ 55 → 54 | 3 bài tụt do môi trường đổi, không do code. Phần môi trường nào đổi thì chưa xác định |
| 02/11/2026 | `agent-eval-read-on` | Bước đọc tiếp và dọn ngữ cảnh trên v0-long.2 | Mọi nhánh 0/4 hoặc 0/3 bài đạt; dữ kiện ctx-01..04 0/13 → 4/13 (3 vòng), 5/13 (8 vòng); 66 bài v0: 55 và 55 | Đọc tiếp có ích ở ctx-01..04. Dọn ngữ cảnh chưa thấy lợi. Mẫu quá nhỏ |
| 02/11/2026 | `agent-eval-v0-long-first` | Lần đầu chạy v0-long: ticket 45 (đọc rất dài), ticket 44 (dọn ngữ cảnh) | end-*: 0/7 → 6/7; ctx-*: 0/7 → 0/7, dọn 0 lần | Ticket 45 có lợi rõ. Ticket 44 chưa đo được |
| 01/11/2026 | `agent-eval-v0.8-baseline-41` | Mốc Agent Eval v0.8 mới (ticket 41) | agent-eval-v0.8: 58/66 (`717e4d3`) → 54/66 (`bd27676`); chỉ 3/66 câu trùng chữ | Tụt điểm, chưa xác định thay đổi nào gây ra. Là số tự chấm |
| 29/10/2026 | `agent-eval-v0.8-n1-gate` | Gộp N1 lên main có làm đổi câu trả lời nào ngoài dự kiến không? | G1 66/66 giống mốc; 58/66 (agent-eval-v0.8); trên 62 bài v0.7: main 45/62, bản gộp 55/62 | Đạt G1, gộp lên main sau khi fable duyệt |
| 29/10/2026 | `agent-eval-v0.8-paste-arbitration` | Phân xử N1 (nạp nguyên văn bản) với C7 (cho lật 7 vòng) | agent-eval-v0.8, 19 bài: nền 10, N1 18, C7 14; trung vị độ trễ 5,5 s so với 11,8 s | Theo nhánh R2 của luật: chọn N1, bỏ C. Dự đoán p5 sai |
| 29/10/2026 | `agent-eval-v0.7-tool-call-parse` | Ticket 27: lệnh công cụ viết hỏng làm mất cả lượt | doc-44 không còn mất lượt; M1 trùng M0 62/62; main M0 45/62 (agent-eval-v0.7) | Đạt cả bốn điều, đề xuất gộp ticket 27 |
| 28/10/2026 | `agent-eval-v0.7-paste-nudge-search` | #3-D: nhắc lại khi chưa đọc (B) và tìm trong đoạn dán (C) | agent-eval-v0.7, 15 bài dán: nền 10, +1 10, +1+3' 9; nền đủ bộ 50/62 | Cả hai đề xuất trượt luật, không gộp gì. 50/62 là mốc cô lập đầu tiên |
| 28/10/2026 | `agent-eval-v0.6-paste-slip-c` | #3-C: lời phiếu lần hai, đo trên 9 bài | agent-eval-v0.6: 2/9 → 6/9; bài mới từ trượt thành đạt chỉ 1/3 | Điều 3 sai nên không đề xuất gộp. Dự đoán "doc-44, 46, 47 mở cả ba" sai |
| 28/10/2026 | `agent-eval-v0.5-paste-slip-b` | #3-B: lời phiếu đoạn dán mới, đo trên 5 bài | agent-eval-v0.5: mở đoạn dán 2/5 → 5/5; điểm 1/5 → 1/5 | Điều 4 sai (doc-42) nên không đề xuất gộp. Bài trượt chủ yếu vì model xin `n` vượt trần |
| 28/10/2026 | `agent-eval-v0.4-baseline-20261028` | Mốc trên main với bộ chấm v0.4 | agent-eval-v0.4: 39/48; 8 bài mới 4/8; so với C4 có 0/48 câu khác chữ | Là mốc hồi quy, không có luật ship. Dự đoán đúng |
| 28/10/2026 | `agent-eval-v0.3-c4-registry` | C4 dời `search_history` sang gói Discord: hành vi có giữ nguyên không? | agent-eval-v0.3: 48/48 câu trùng từng chữ; hai bên đều 39/48 | Cả ba dự đoán đúng, C4 giữ nguyên hành vi |
| 28/10/2026 | `agent-eval-v0.3-pastes` | #3: đoạn dán dài đến được agent dưới dạng phiếu | agent-eval-v0.3: 39/48 → 39/48; doc-39 gọi `read_document` 0 lần | Một điều trong luật sai nên không đề xuất giữ. Chủ dự án quyết |
| 28/10/2026 | `agent-eval-v0.3-answer-check` | #2: kiểm con số trong câu trả lời trước khi gửi | agent-eval-v0.3: 38 → 39/48; số không nguồn ở doc-10 từ 6 → 0 | Mọi dự đoán đúng, đề xuất giữ #2. Ở doc-22, lời tự sửa của model lộ ra cho người dùng |
| 28/10/2026 | `agent-eval-v0.3-read-B-20261028` | #1-B: có công cụ đọc nhưng giữ lời dặn cũ | agent-eval-v0.3: 38/48; 40 bài cũ 33; bài đọc dài 4/5 | Đạt luật, đề xuất ship #1-B. 40 bài cũ vừa đúng ngưỡng. doc-10 bịa số |
| 28/10/2026 | `agent-eval-v0.3-read-20261028` | #1 công cụ đọc theo handle: so trước và sau | agent-eval-v0.3: 35/48 → 34/48; 40 bài cũ 34 → 29; 8 bài mới 1/8 → 5/8 | Dự đoán "doc-33..37 đạt cả 5" sai (chỉ 4/5). Không tách được phần tụt thật khỏi xáo trộn do đổi lời dặn |
| 28/10/2026 | `agent-eval-v0.3-baseline-20261028` | Mốc v0.3, có thêm 8 bài đọc dài | agent-eval-v0.3: 35/48; 40 bài cũ 34/40; 8 bài mới 1/8 | Là mốc, không có luật ship. Dự đoán đúng. hist-11 bịa câu trả lời |
| 27/10/2026 | `agent-eval-v0.2-harness-controls-20261027` | Ticket 16 (đồng hồ, mã lỗi, trace) có làm điểm tụt không? | agent-eval-v0.2: A 34/40, B 34/40; hỏi lại "server nào": A 2/3, B 0/3 | Không tụt, dự đoán đúng. Đề xuất đóng ticket 16 |
| 27/10/2026 | `agent-eval-v0.2-1a-v2-20261027` | Lời dặn 1a-v2 (và 1a-v2 + 2b) có qua luật ship không? | agent-eval-v0.2: A 34/40, E 33, F 33; mục tiêu 1a 4/5; mất 3 bài theo dõi | Trượt luật: không ship E, không ship F |
| 27/10/2026 | `agent-eval-v0.2-harness-20261027` | Ticket 10: cách cắt kết quả công cụ mới (3a), lời dặn 1a và gợi ý 2b có giúp được không? | agent-eval-v0.2, lạnh: A 34/40, B(1a) 30/40, C(2b) 34/40, D(1a+2b) 30/40; mất trích dẫn: có 1a 32/36, không có 1a 5/45 | 1a có hại, 2b đứng một mình không đổi gì, chưa nên ship 1a. Điểm neo đáng tin: gỡ model trước mỗi lần đo |
| 27/10/2026 | `agent-eval-v0.1-baseline-20261027` | Mốc thăm dò đầu tiên của agent trên 40 bài; chạy lại có ra cùng kết quả không? | agent-eval-v0.1: r1 lạnh 33/40, r2 = r3 34/40, t0.4 29/40; đếm tay 35/40 (số chính thức vẫn 34/40) | Mới là thăm dò. Lỗi lớn nhất là agent "không chịu tra". Lần chạy lạnh khác lần nóng, nguyên nhân chưa đo |

Ghi chú về bảng:
- 6 mục ngày 02/11 không ghi giờ đo nên thứ tự giữa chúng trong ngày không rõ.
- `agent-eval-v0-long-2` (4 nhánh `a-off`, `a-on`, `b-off`, `b-on`) và `bfcl-v1-base` (điểm BFCL bộ chạy v1, 5 hạng mục) không có báo cáo; số của chúng được dẫn trong các báo cáo cùng thời.
- Nhật ký điểm Agent Eval dạng máy đọc `kept/agent-eval-scorecard-history.jsonl` vẫn được ghi tự động, và không thay cho sổ này.
