# Sổ đo

Mọi lần đo của dự án được ghi ở đây, kể cả những lần hỏng, bị dừng hoặc cho kết quả âm. Mỗi lần một mục, mục mới nhất ở trên cùng.

Thư mục `data/evaluation/results/kept/*/` vẫn là nơi giữ bằng chứng chi tiết. `docs/RESULTS.md` chỉ chép lại những số đủ chắc để đưa ra ngoài (README, CV), và mỗi số ở đó phải có mục tương ứng ở đây.

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
