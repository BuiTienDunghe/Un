# Kế hoạch và ticket đã xong

Đã gỡ khỏi cây thư mục ngày 30/10/2026 vì việc đã xong hoặc không còn dùng. Đọc lại một tệp: `git show archive/before-cleanup-2026-10-30:<đường dẫn>`. Mọi nhận xét trong code trỏ tới `.scratch/...` mà không còn tệp thì tra ở đây.

| Tệp | Trạng thái lúc gỡ |
|---|---|
| `chunker-numbered-clause/spec.md` | rule pre-registered 04/09/2026, before any measurement of the change |
| `chunker-overlap-containment/spec.md` | **T3 adopted by the owner 07/09/2026**, labels remapped; measured on both eval surfaces |
| `five-steps-hardening/SPEC.md` |  |
| `foundation-and-agent-eval/coordination.md` |  |
| `foundation-and-agent-eval/issues/01-nightly-eval-fail-fast.md` | đã gộp vào main (27/10), fable 5.1 duyệt — còn: một đêm 03:00 thật exit 0 |
| `foundation-and-agent-eval/issues/02-one-install-path.md` | đã gộp vào main (27/10), fable 5.1 duyệt |
| `foundation-and-agent-eval/issues/03-compose-pass-through-v2.md` | xong — đã gộp vào main (27/10), fable 5.1 duyệt |
| `foundation-and-agent-eval/issues/04-bot-control-one-mechanism.md` | đã gộp vào main (27/10), fable 5.1 duyệt |
| `foundation-and-agent-eval/issues/05-layer-cleanups.md` | đã gộp vào main (27/10), fable 5.1 duyệt |
| `foundation-and-agent-eval/issues/06-agent-eval-v0-harness.md` | đã gộp vào main (27/10), fable 5.1 duyệt — **chưa chạy lại với model thật sau khi đổi tiêu chí** (ticket 07 ch |
| `foundation-and-agent-eval/issues/07-agent-eval-v0-baseline.md` | đã gộp vào main (27/10), fable 5.1 duyệt |
| `foundation-and-agent-eval/issues/08-model-experiment-target.md` | xong — chủ dự án chọn B, nhánh 0 trước (27/10) |
| `foundation-and-agent-eval/issues/10-harness-from-measured-failures.md` | đã giao — Nhân viên của Ún 3; phần GPU sau 09 |
| `foundation-and-agent-eval/issues/11-heldout-noise-floor.md` | đã gộp vào main (27/10), opus 5.5 duyệt (chỉ dữ liệu + RESULTS.md); số đã điền vào m3-preregistration.md |
| `foundation-and-agent-eval/issues/12-small-cleanups.md` | đã gộp vào main (27/10), fable 5.1 duyệt |
| `foundation-and-agent-eval/issues/13-e5-packaging-prep.md` | đã gộp vào main (27/10), fable 5.1 duyệt |
| `foundation-and-agent-eval/issues/16-harness-controls.md` | **xong** (27/10 23:35) — commit 1–4 gộp; bước 5 không suy giảm (A 34/40, sau 16 34/40; hist-08..10 thôi hỏi lạ |
| `foundation-and-agent-eval/issues/17-forget-member-agent-traces.md` | đã gộp vào main (27/10 23:45), fable 5.1 duyệt |
| `foundation-and-agent-eval/issues/18-flaky-debt-teardown.md` | đã gộp vào main (27/10 23:10), fable 5.1 duyệt; chạy lại 5/5 xanh trên main |
| `foundation-and-agent-eval/issues/19-forget-member-guild-scope.md` | đã gộp vào main (28/10 00:05), fable 5.1 duyệt; còn một test bổ sung (lọc quá hẹp ở bước 2) theo gợi ý fable |
| `foundation-and-agent-eval/issues/20-agent-capabilities.md` | đang làm — cách A (chủ dự án 28/10 00:20): v0.3 → #1 → #2 → #3 → #4; bỏ #5. #3-B trượt luật (15:13); #3-C trượ |
| `foundation-and-agent-eval/issues/22-discord-soft-split.md` | thiết kế xong (fable, `ticket22-design.md`); 5 lựa chọn điều phối chốt; C1 giao Nhân viên 2, C2–C3 sau khi gộp |
| `foundation-and-agent-eval/issues/25-discord-debt.md` | xong — 1B gộp main 9a46f54 (30/10); 2A, 3A để nguyên theo lựa chọn của chủ dự án |
| `foundation-and-agent-eval/issues/26-anthropic-provider.md` | đã gộp main 8f61012 (30/10), chưa bật — chủ dự án chọn "gộp, chưa bật"; promote là quyết định riêng |
| `foundation-and-agent-eval/issues/27-malformed-tool-call.md` | xong — gộp main `5f60277` (29/10, chủ dự án duyệt); còn mở: hai cột bảng điểm, mã log riêng, chữ lỗi parser kh |
| `foundation-and-agent-eval/issues/29-docs-match-code.md` | xong — gộp main 5d670ea (30/10); bốn nghi lỗi code chờ chủ dự án |
| `foundation-and-agent-eval/issues/30-docs-guild-gate.md` | xong code — gộp main, đã push eba3794 (30/10); chưa thử trên Discord thật |
| `foundation-and-agent-eval/issues/31-34-model-screen-local-ocr-vision.md` | xong code — gộp main (30/10); chưa thử ảnh và `/docs` trên Discord thật, chưa push |
| `foundation-and-agent-eval/issues/35-agent-memory-web.md` | xong code — gộp main (30/10); chưa thử trên Discord thật, chưa push |
| `foundation-and-agent-eval/joint-measurement-plan.md` |  |
| `foundation-and-agent-eval/paste-directions-2026-10-28.md` |  |
| `foundation-and-agent-eval/research-2026-10-29/c-noi-tran-doc.md` |  |
| `foundation-and-agent-eval/research-2026-10-29/harness-tim-ho.md` |  |
| `foundation-and-agent-eval/research-2026-10-29/phan-bien.md` |  |
| `foundation-and-agent-eval/research-2026-10-29/tim-trong-doan-dan.md` |  |
| `foundation-and-agent-eval/research-2026-10-29/tong-hop.md` |  |
| `foundation-and-agent-eval/reviews/22-discord-split-a8433f7.md` | GỘP ĐƯỢC — với MỘT điều kiện trước khi g |
| `foundation-and-agent-eval/reviews/int-20-n1-main-717e4d3.md` | GỘP ĐƯỢC (vào main, sau khi G1 của lần c |
| `foundation-and-agent-eval/reviews/int-26-main-1c7f73e.md` | GỘP ĐƯỢC (merge sạch, chỉ dời mục CHANGE |
| `foundation-and-agent-eval/reviews/prereg-20-3b-073d152.md` | GỘP ĐƯỢC (bản đăng ký đủ, chạy được như  |
| `foundation-and-agent-eval/reviews/prereg-20-3c-9f2a23a.md` | GỘP ĐƯỢC (bản đăng ký đủ, `analyze.py` đ |
| `foundation-and-agent-eval/reviews/prereg-20-3d-28df7c7.md` | GỘP ĐƯỢC (bản sửa đúng quyết định chủ dự |
| `foundation-and-agent-eval/reviews/prereg-20-3d-347194a.md` | GỘP ĐƯỢC (bản đăng ký đủ, `analyze.py` đ |
| `foundation-and-agent-eval/reviews/prereg-27-26616b3.md` | GỘP ĐƯỢC (bản đăng ký đủ, `analyze.py` đ |
| `foundation-and-agent-eval/reviews/prereg-arb-9062a9e.md` | CẦN SỬA (một chỗ: R2 đếm cả doc-57, bài  |
| `foundation-and-agent-eval/reviews/prereg-arb-e6666c0.md` | GỘP ĐƯỢC (chỗ CẦN SỬA ở 9062a9e đã sửa đ |
| `foundation-and-agent-eval/reviews/prereg-gate-0de310f.md` | GỘP ĐƯỢC (bản đăng ký kiểm 66 bài đủ, mố |
| `foundation-and-agent-eval/reviews/report-20-3b-fadc775.md` | ĐÚNG SỐ (báo cáo khớp dữ liệu thô ở mọi  |
| `foundation-and-agent-eval/reviews/report-20-3c-67c43e0.md` | ĐÚNG SỐ (báo cáo khớp dữ liệu thô ở mọi  |
| `foundation-and-agent-eval/reviews/report-20-3d-c240256.md` | ĐÚNG SỐ (báo cáo khớp dữ liệu thô ở mọi  |
| `foundation-and-agent-eval/reviews/report-27-3fdb452.md` | ĐÚNG SỐ (báo cáo khớp dữ liệu thô ở mọi  |
| `foundation-and-agent-eval/reviews/report-arb-e707140.md` | ĐÚNG SỐ (số liệu và bốn lần chạy không đ |
| `foundation-and-agent-eval/reviews/report-arb-f535414.md` | ĐÚNG SỐ (mọi con số tôi tính lại từ tệp  |
| `foundation-and-agent-eval/reviews/report-gate-23d7029.md` | ĐÚNG SỐ (66/66 câu trả lời và chuỗi lệnh |
| `foundation-and-agent-eval/reviews/wip-20-agent-reading-8cc0f73.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-20-agent-reading-cd99811.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-20-answer-check-ebf2686.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-20-discord-progress-634a60b.md` | GỘP ĐƯỢC (hai chỗ opus hỏi đều ổn: không |
| `foundation-and-agent-eval/reviews/wip-20-eval-isolate-c33dffc.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-20-eval-v04-83b3440.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-20-paste-inline-32a2d50.md` | GỘP ĐƯỢC (vào int/20-arb cho nhánh đo N1 |
| `foundation-and-agent-eval/reviews/wip-20-paste-nudge-2955861.md` | CẦN SỬA (một chỗ nhỏ, trước khi đo: `fro |
| `foundation-and-agent-eval/reviews/wip-20-paste-nudge-5e69dbe.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-20-paste-rounds-bc2b8f9.md` | GỘP ĐƯỢC (vào int/20-arb cho nhánh đối c |
| `foundation-and-agent-eval/reviews/wip-20-paste-search-92f5796.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-20-paste-search-c270ded.md` | GỘP ĐƯỢC (với một điều cần chủ dự án biế |
| `foundation-and-agent-eval/reviews/wip-20-paste-slip-b-563ccfe.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-20-paste-slip-c-5d16c7b.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-20-paste-tasks-2e35df2.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-20-paste-tasks-c-36f8bd7.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-20-paste-tasks-d-a755981.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-20-paste-tasks-e-0adc697.md` | GỘP ĐƯỢC (vào int/20-arb trước khi đo; b |
| `foundation-and-agent-eval/reviews/wip-20-pastes-a07d7f7.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-20-progress-8adcd02.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-22-c4-registry-e252459.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-23-scorecard-2eec41f.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-23-scorecard-31b92bf.md` | GỘP ĐƯỢC (commit 31b92bf). Lưu ý: cây là |
| `foundation-and-agent-eval/reviews/wip-23-scorecard-b50982c.md` | CẦN SỬA (nhỏ, một chỉ số) — hoặc GỘP ĐƯỢ |
| `foundation-and-agent-eval/reviews/wip-25-config-guard-d8d3bf8.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-27-tool-call-parse-c144999.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-28-answer-check-f348364.md` | GỘP ĐƯỢC (bốn mục đúng spec; #3 đúng là  |
| `foundation-and-agent-eval/reviews/wip-29-docs-sync-f1a9e03.md` | GỘP ĐƯỢC (0 câu sai trong hơn 60 câu khẳ |
| `foundation-and-agent-eval/reviews/wip-30-docs-guild-gate-09e2658.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-31-34.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-31-model-switch-ui-d9bf55c.md` | CẦN SỬA |
| `foundation-and-agent-eval/reviews/wip-35.md` | GỘP ĐƯỢC |
| `foundation-and-agent-eval/reviews/wip-36.md` | CẦN SỬA |
| `foundation-and-agent-eval/spec.md` | đang làm (27/10/2026) — điều phối và ticket: `coordination.md`, `issues/` |
| `foundation-and-agent-eval/ticket20-design-1.md` |  |
| `foundation-and-agent-eval/ticket22-design.md` |  |
| `model-registry/codebase-map.md` |  |
| `model-registry/design.md` |  |
| `model-registry/spec.md` | acceptance rule fixed 07/09/2026, before implementation; design in `design.md` |
| `reranker-finetune/spec.md` | rule pre-registered 05/09/2026, before the treatment arm exists; **control re-based 07/09/2026** on the correc |
| `research-space/spec.md` | in progress (11/10/2026). Phần 1 của gói thiết kế (app chính, 10 màn) đã ship từ 16/09 (`cccea32`). |
| `tier3-condensation/PLAN.md` |  |
| `web-ui-v2/spec.md` | done (16/09/2026) — 10 màn + khung app đã dựng, kiểm và sửa. |
