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

## 12/11/2026 — Chạy cả bộ test cho đợt 1 công cụ đọc tệp, chưa commit

- **Câu hỏi:** với database thật, phần sửa chung (vòng lặp agent, chat, đường `/chat`) có làm hỏng test nào đang có không? Và cả bộ có ra đúng số đã dự đoán không?
- **Điều kiện:**
  - Code: cùng cây làm việc với mục test nhẹ bên dưới, trên `b0f146d`, chưa commit.
  - Python 3.11.9 trên Windows.
  - Container dùng một lần: `chk-lf1-*` (`postgres:16-alpine`, `redis:7-alpine`, `qdrant/qdrant:v1.18.2`). Đã migrate tới head. Chạy xong đã gỡ.
  - Ollama giả, ẩn CUDA, không đụng database thật.
  - Chủ dự án cho phép: "Chạy cả bộ".
- **Đăng ký trước:** `tests/prediction-full.md`, viết trước khi chạy. Dự đoán: backend 2.400 đạt, 14 xfail, 1 bỏ qua; gốc 250 đạt, 1 bỏ qua.
- **Kết quả:**

  | Bộ | Kết quả | Thời gian |
  |---|---|---|
  | Backend đủ bộ | 2.400 đạt, 14 xfail, 1 bỏ qua (symlink), 0 hỏng | 6 phút 30 giây |
  | Gốc đủ bộ | 250 đạt, 1 bỏ qua (thiếu `mteb`) | 25 giây |

- **Kết luận:** đúng dự đoán, khớp từng con số. Lần 11/11 backend có 2.341 bài đạt; lần này nhiều hơn 59 bài, đúng bằng số bài đạt của tệp test mới.
- **Trạng thái:** xong.
- **Bằng chứng:** `data/evaluation/results/kept/local-files-batch1-20261112/tests/` gồm `prediction-full.md`, `alembic.log`, `backend-full.log`, `root-full.log`.

## 12/11/2026 — Test nhẹ đợt 1 công cụ đọc tệp (list_files, read_file), chưa commit

- **Câu hỏi:** code đợt 1 (agent cục bộ được đọc tệp trong thư mục chủ máy chọn) có đạt bộ test mới của nó không? Có làm hỏng các test agent và chat đang có không?
- **Điều kiện:**
  - Code: cây làm việc trên `b0f146d`, chưa commit.
    - Tệp mới: `backend/app/services/local_files.py`, `backend/tests/test_local_files.py`.
    - Tệp sửa: `agent_service.py`, `chat_service.py`, `routers/chat.py`, `settings.py`, `main.py`, `.env.example`.
    - Đã qua 2 vòng duyệt của Fable (`.scratch/laptop-agent/reviews/`). Phần sửa R1 làm sau vòng 2, chưa ai duyệt lại.
  - Môi trường: Python 3.11.9 trên Windows.
    - **Không có database**: bỏ `POSTGRES_TEST_URL` và `REDIS_TEST_URL`, nên các test cần database tự bỏ qua.
    - Ollama giả (cổng chết), ẩn CUDA, không nạp model.
    - GPU trống (0 MiB, 42 °C) lúc bắt đầu.
  - Chủ dự án cho phép: "Chạy test nhẹ".
- **Đăng ký trước:** không. Không ghi dự đoán trước khi chạy.
- **Kết quả:**

  | Lần chạy | Kết quả | Thời gian |
  |---|---|---|
  | Test mới + `test_agent_*` + `test_ask_user` + `test_chat_api` + `test_api_key_auth` + `test_tool_state*` (33 tệp) | 665 đạt, 102 bỏ qua (cần database), 0 hỏng | 37 giây cả khởi động |
  | Riêng `test_local_files.py`, có tên từng bài | 59 đạt, 1 bỏ qua | dưới 1 giây |

- **Kết luận:** xanh. Lần nào cũng chạy lần đầu đã xanh, không phải sửa gì.
  - Bài bỏ qua trong tệp mới là test lối tắt kiểu symlink: máy này không cho tạo symlink nếu không có quyền.
  - Test junction (cùng loại rủi ro) có chạy và đạt.
  - Bộ đủ có database chưa chạy, nên các đường chat cần database (trí nhớ v2, lưu kết quả công cụ) chưa được kiểm với phần sửa này.
- **Trạng thái:** xong (mức nhẹ). Bộ đủ chờ cho phép.
- **Bằng chứng:** `data/evaluation/results/kept/local-files-batch1-20261112/tests/` (`run1-light.log`, `run2-local-files-verbose.log`).

## 11/11/2026 — Chạy lại đủ bộ test trên đầu nhánh `4936223` trước khi push

- **Câu hỏi:** sau khi tách thành 5 commit, đúng commit sẽ push có còn xanh như cây làm việc buổi sáng không?
- **Điều kiện:**
  - Commit `4936223` checkout riêng thành worktree tách rời trong scratchpad. Đã in đường dẫn để chắc `app` và `discord_bot` được nạp từ worktree.
  - Python 3.11.9 trên Windows.
  - Container dùng một lần như mục dưới, đã migrate tới head.
  - Ollama giả, ẩn CUDA, không đụng database thật.
  - Chủ dự án cho phép: "Chạy lại test rồi push".
- **Đăng ký trước:** `tests-tip-4936223/prediction.md`, viết khi test đang chạy, trước khi thấy kết quả: backend 2.341 đạt + 14 xfail, gốc 250 đạt + 1 bỏ qua.
- **Kết quả:**

  | Bộ | Kết quả | Thời gian |
  |---|---|---|
  | Backend đủ bộ | 2.341 đạt, 14 xfail, 0 hỏng, 0 bỏ qua | 7 phút 17 giây |
  | Gốc đủ bộ | 250 đạt, 1 bỏ qua (thiếu `mteb`) | 27 giây |

- **Kết luận:** đúng dự đoán, giống hệt lần chạy sáng.
  - Backend có 6 cảnh báo, sáng nay có 4. Hai cảnh báo thêm là `\o` trong chuỗi của `test_backup_worker.py:201`: bản checkout mới phải dịch lại tệp Python nên cảnh báo này hiện ra. Test đó có từ trước, không thuộc loạt sửa này.
- **Trạng thái:** xong. Được phép push.
- **Bằng chứng:** `data/evaluation/results/kept/review2-fixes-20261111/tests-tip-4936223/`, gồm log hai bộ, log migrate, chỗ nạp code và bản dự đoán.

## 11/11/2026 — Test các bản sửa review2 (Discord, OCR, auth, web) và phần chuẩn bị đo mốc 2B

- **Câu hỏi:** đêm 10→11/11, agent viết các bản sửa review2 và phần chuẩn bị đo mốc 2B, chỉ kiểm bằng cách đọc. Khi chạy thật, chúng có đạt bộ test không? Có đúng dự đoán đã ghi trước "bộ review2 ra 107 đạt và 14 xfail (F ×6, E ×8)" không?
- **Điều kiện:**
  - Code: cây làm việc trên `69ca4ad`, chưa commit. Diff ở `.scratch/review2-fixes/*/changes.diff` và `.scratch/harness-research/changes.diff`.
  - Môi trường: Python 3.11.9 trên Windows. Container dùng một lần: `postgres:16-alpine` (16.15), `redis:7-alpine`, `qdrant/qdrant:v1.18.2`, đã migrate tới head `20261109_39`.
  - Ollama giả (`OLLAMA_BASE_URL` trỏ cổng chết), ẩn CUDA, không nạp model, không đụng database thật.
  - Chủ dự án cho phép lúc sáng 11/11: "Cho chạy test".
- **Đăng ký trước:** dự đoán ở `.scratch/review2-fixes/RUN-PLAN.md`, mục "Dự đoán cho bước 1–2", viết trước lần chạy.
- **Kết quả:**

  | Lần chạy | Kết quả | Thời gian |
  |---|---|---|
  | Nhóm backend (review2 + Discord + OCR + auth + eval, 34 tệp) | 535 đạt, 14 xfail, 0 hỏng, 0 bỏ qua | 2 phút 40 giây |
  | Trong đó review2 backend | 99 đạt, 14 xfail (clocks F ×6, ocr_access E ×8) | — |
  | review2 gốc (`tests/test_review2_bot_turns.py`) | 8 đạt | — |
  | **review2 tổng** | **107 đạt, 14 xfail: đúng dự đoán** | — |
  | Nhóm bot ở gốc (6 tệp) | 103 đạt | 7 giây |
  | R6-1 + R7-5 (Windows nhả tệp), chạy lặp 3 lần | lần nào cũng 3/3 | — |
  | R5-1 + A-5…A-8, chạy lặp 3 lần | lần nào cũng 6/6 | 8,3–8,5 giây mỗi lần |
  | Backend đủ bộ | 2.341 đạt, 14 xfail, 0 hỏng | 5 phút 56 giây |
  | Gốc đủ bộ | 250 đạt, 1 bỏ qua (`test_run_mteb_prefixes`: thiếu `mteb`) | 23 giây |
  | Bước 0 của PREREG mốc 2B | Băm v0 vẫn là `35b39db4…`; bộ `v0-discord-chat` có 25 bài; persona dựng được; `bfcl_run --dry-run` chạy; `run_2b_baseline.py --plan` in 12 lượt chạy | — |

- **Kết luận:** mọi bản sửa đều chạy đúng như lần đọc dự đoán; không ca nào hỏng, không ca nào bất ngờ đạt. 41 dấu xfail đã gỡ đều chuyển sang đạt. 14 ca còn lại đúng là các lỗi chưa sửa: F (đồng hồ) và E (OCR không có chủ).
- **Còn thiếu:**
  - Chưa chạy với Ollama thật hay Discord thật.
  - Bot chạy trong container phải build lại image mới dùng code mới.
  - Lần đo mốc 2B (bước 7) chưa chạy.
- **Trạng thái:** xong. Sáng 11/11 chủ dự án cho commit; code vào 5 commit liền nhau trên `69ca4ad`, mục này đi cùng commit cuối. Test chạy trên cây làm việc trước khi tách commit. Sau đó đã chạy lại trên đầu nhánh (mục trên) nhưng chưa chạy trên từng commit.
- **Bằng chứng:**
  - `data/evaluation/results/kept/review2-fixes-20261111/tests/` gồm log của 4 lần chạy, danh sách tệp nhóm, và kết quả các lần chạy lặp. Commit cùng mục này.
  - Báo cáo và bản duyệt: `.scratch/review2-fixes/` (chỉ trên máy).

## 10/11/2026 — Fable 5.2 duyệt lại phần sửa bộ test review2; sửa theo 3 điểm và chạy lại

- **Câu hỏi:**
  - 4 chỗ Opus sửa, cộng chỗ thứ năm ngoài phạm vi, có bịt đúng lỗ hổng không?
  - Có làm ca nào đỏ oan khi lỗi được sửa đúng cách không?
- **Điều kiện:**
  - Code: main `ed60401`, cộng phần sửa lỗi B và bộ test review2, chưa commit.
  - Người duyệt: Fable `claude-fable-5-2`, container `chk-r2g-*`.
  - Phiên điều phối `claude-opus-5-5` sửa theo, chạy lại trên container mới `chk-r2w-*`.
  - Ollama cổng chết, CUDA ẩn, Windows.
- **Đăng ký trước:** không. Đây là lần duyệt, rồi kiểm lại sau khi sửa.
- **Kết quả:**

  | Lần chạy | Kết quả |
  |---|---|
  | Fable: bộ review2 | 53 + 55 xfail; 3 đạt (khớp Opus) |
  | Fable: bản vá phía backend / phía bot của Opus | 10/10, 3/3 lật |
  | Fable: bản vá phía bot mới cho A-7 ("thôi chờ thì huỷ lượt") | **đỏ oan** vì ca đòi lượt còn ở trạng thái chờ |
  | Fable: A-5 gửi lại với cách đánh số cũ | đỏ vì trùng mã, nghĩa là chỗ sửa thứ năm là cần |
  | Sau sửa: bộ review2 | 53 đạt, 55 xfail, 137,6 giây; 3 đạt |
  | Sau sửa: bản vá phía bot A-7, A-5 ×2, A-6 ×2 | đều lật |
  | Sau sửa: đột biến R5 cả hai bị từ chối | đỏ ở dòng mới; trước là xfail |
- **Kết luận:**
  - Fable kết luận GỘP ĐƯỢC.
  - Fable đồng ý cả ba chỗ Opus làm khác đề xuất, và xác nhận chỗ thứ năm là cần.
  - Fable lật lại nhận định "đọc code là đủ" của chính mình ở lần duyệt trước: A-7 cần chạy thử mới thấy đỏ oan.
  - Sửa ba điểm:
    - A-7 nhận lượt bị huỷ;
    - thêm dòng canh thuộc tính đánh số của Discord giả;
    - R5-1 đỏ khi cả hai lần hạ quyền bị từ chối.
- **Trạng thái:** xong; chưa commit. Chưa chạy đủ bộ backend: chỉ ba tệp review2 đổi, và ngoài review2 không tệp nào import chúng.
- **Bằng chứng:** `data/evaluation/results/kept/review2-test-suite-20261110/` (`REVIEW-fable-fix4.md`, `fix4-review/`, `fix5/run.txt`, `fix5/changes.diff`, mục cuối `RUN-LOG.md`). Đã commit ở `69ca4ad`.

## 10/11/2026 — Sửa 4 chỗ Fable nêu trong bộ test review2 (Opus 5.5 xhigh), phiên điều phối chạy lại

- **Câu hỏi:** sau khi siết 4 chỗ bắt lỗi quá rộng, mỗi ca có còn ra đúng kết quả cũ không, có còn lật khi lỗi được vá không, và có đỏ thật khi gặp sự cố không liên quan không?
- **Điều kiện:**
  - Code: main `ed60401`, cộng phần sửa lỗi B và bộ test review2, tất cả chưa commit.
  - Người sửa: Opus `claude-opus-5-5`, mức xhigh. Chỉ sửa `review2_support.py`, `test_review2_bot_backend.py`, `test_review2_auth.py`, `test_review2_discord_turns.py`.
  - Container dùng một lần (`chk-r2u-*` cho Opus, `chk-r2v-*` cho phiên điều phối), migrate tới head, Ollama cổng chết, CUDA ẩn, Windows.
  - Mỗi chỗ chạy ba lần: (a) code hôm nay; (b) bản vá tạm ở `flip/`; (c) một đột biến mà kiểm tra mới nhắm vào.
  - Phiên điều phối chạy lại (a) trên container mới. Với (b), (c), phiên này chỉ đối chiếu tệp kết quả thô, không chạy lại. Đã xác nhận: ô "đỏ" hỏng đúng ở dòng kiểm mới, hoặc ở lỗi `RuntimeError` được ném lại, chứ không phải dòng `XPASS(strict)`. Diff thật khớp `changes.diff`.
- **Đăng ký trước:** brief giao việc ghi trước kỳ vọng (a) không đổi, (b) vẫn lật, (c) phải đỏ thật; với N4-1 là không được lật.
- **Kết quả:**

  | Chỗ | (a) | (b) | (c) bản cũ → bản mới |
  |---|---|---|---|
  | A-5…A-8 (bot ném lỗi lạ) | 5 xfail | vá backend 5/5 lật; vá phía bot 3/3 lật | tin 2: 5 xfail → 5 đỏ; tin 1: 4 xfail → 4 đỏ |
  | R5-1 (lỗi lạ khi hạ quyền) | xfail | lật | một luồng lỗi lạ: lật nhầm → đỏ; hai luồng lỗi kết nối: xfail → đỏ |
  | R3-1, R3-2 (mã HTTP) | 2 xfail | 2/2 lật | trả 500: lật nhầm → đỏ; trả 409: vẫn lật (từ chối là sửa hợp lệ) |
  | N4-1 (câu báo cũ) | xfail | lật | câu báo cũ kèm "đã quên": lật nhầm → xfail |

  | Chạy cả bộ review2 | Kết quả |
  |---|---|
  | Opus, 8 tệp backend | 53 đạt, 55 xfail, 132,4 giây |
  | Phiên điều phối chạy lại, container mới | 53 đạt, 55 xfail, 132,8 giây |
  | `tests/test_review2_bot_turns.py` (cả hai lần) | 3 đạt |
  | Opus, không có `POSTGRES_TEST_URL` | 30 đạt, 20 xfail, 58 bỏ qua, 0 lỗi |
- **Kết luận:**
  - Đúng dự đoán ở cả 4 chỗ; tổng vẫn 56 đạt + 55 xfail.
  - Opus sửa thêm chỗ thứ năm, ngoài phạm vi được giao: Discord giả của mỗi tin giờ đánh số tin trả lời từ một số riêng. Trước đó hai tin cùng được trả lời thì trùng mã, và bản cũ nuốt lỗi này. Vì thế một trong ba lần lật "phía bot" trước đây thật ra đã hỏng ở bước báo giao tin.
  - Khác đề xuất của Fable ở hai điểm:
    - kiểm tra lỗi lạ nằm trong helper `BotOnApp.ask`, không đặt ở từng chỗ gọi;
    - N4-1 kiểm "không chứa câu báo cũ" thay vì "khác câu báo cũ".
  - R5-1 giờ chỉ nhận một kiểu từ chối: lỗi "quản trị viên cuối cùng". Nếu bản sửa để bên thua hỏng vì một lỗi database khác, ca sẽ đỏ chứ không lật.
  - Fable duyệt GỘP ĐƯỢC trên bản trước khi sửa; các thay đổi này chưa ai duyệt lại.
- **Trạng thái:** xong; chưa commit. Chưa chạy đủ bộ backend, vì không tệp nào ngoài review2 import helper. Chưa chạy trên Linux. A-5, A-7 chưa có bản vá phía bot để thử lật.
- **Bằng chứng:** `data/evaluation/results/kept/review2-test-suite-20261110/fix4/` (`changes.diff`, `test_review2_tmp_fix4.py`, `run_c.sh`, kết quả thô a/b/c, `final-review2.txt`, `coordinator-rerun.txt`); mục cuối `RUN-LOG.md`. Đã commit ở `69ca4ad`.

## 10/11/2026 — Bộ test hồi quy review2 (111 test): Opus 5.5 xhigh viết, Fable 5.2 duyệt

- **Câu hỏi:**
  - Bộ test chuẩn có phủ đủ 52 ca đã họp chốt không?
  - Test cũ có còn xanh không?
  - Mỗi ca "lỗi đã biết" có hỏng đúng vì lỗi đó, và có lật khi lỗi được sửa không?
- **Điều kiện:**
  - Code: main `ed60401`, cộng phần sửa lỗi B chưa commit, cộng 10 tệp test mới chưa commit.
  - Kế hoạch: `meeting/test-plan.md`, do Fable gộp, Opus ký kèm sửa, chốt theo `DECISIONS.md`.
  - Người viết: Opus `claude-opus-5-5`, mức xhigh. Người duyệt: Fable `claude-fable-5-2`. Hai bên chạy lần lượt.
  - Container dùng một lần `postgres:16-alpine`/`redis:7-alpine`/`qdrant:v1.18.2`, migrate tới head. Ollama cổng chết, CUDA ẩn, Windows.
  - Lỗi chưa sửa đánh dấu `xfail(strict=True, raises=KnownBug)`.
- **Đăng ký trước:** kế hoạch ca `meeting/test-plan.md`, viết trước khi viết test.
- **Kết quả:**

  | Lần chạy | Opus | Fable chạy lại |
  |---|---|---|
  | Bộ review2 | 56 đạt, 55 xfail, 0 xpass, 0 hỏng | 56 đạt, 55 xfail |
  | Backend đủ bộ | 2.283 đạt, 55 xfail | 2.283 đạt, 55 xfail; 7 phút 51 giây |
  | Bộ gốc `pytest tests` | 245 đạt, 1 bỏ qua (thiếu `mteb`) | 245 đạt, 1 bỏ qua |
  | Chạy lặp | 3 lần, kết quả giống hệt | đảo thứ tự tệp, kết quả giống |
  | Không có `POSTGRES_TEST_URL` | — | 58 bỏ qua sạch, 0 lỗi |
  | Vá tạm cho từng ca xfail | 55/55 lật thành XPASS | 51/51 lật (14 mã); chưa chạy lại A-5, A-6, A-8 |
  | Cố ý làm hỏng hành vi đang đúng | — | 10 hành vi; 30 ca canh đỏ đúng chỗ |
  | Nhóm A (bot nối backend thật) | khoảng 80 giây | 80,9 giây; 75 giây là chờ hết hạn, chỉ tốn khi lỗi A còn |
- **Kết luận:**
  - Bộ test đủ 52 ca, không làm hỏng test cũ. Mỗi ca "lỗi đã biết" lật khi lỗi được vá.
  - Fable kết luận GỘP ĐƯỢC, kèm 4 chỗ nên sửa:
    - bắt lỗi quá rộng ở bộ nối bot của A-5…A-8;
    - bắt lỗi quá rộng ở R5-1;
    - R3-1 và R3-2 không kiểm mã HTTP;
    - N4-1 thiếu một khẳng định.
  - R4 và D không có ca tự động, vì đang chờ chủ dự án chọn cách sửa.
  - Chưa chạy trên Linux.
- **Trạng thái:** xong; chưa commit. 4 chỗ nên sửa đã làm ở mục "Sửa 4 chỗ Fable nêu…" phía trên. Trong các lần thử lật bằng bản vá phía bot, có một ca của A-6 hỏng ngầm; mục đó giải thích.
- **Bằng chứng:** `data/evaluation/results/kept/review2-test-suite-20261110/` (`RUN-LOG.md`, `REVIEW-fable.md`, `flip/`, `fable-review/`, `meeting/`). Đã commit ở `69ca4ad`.

## 10/11/2026 — Kiểm độc lập bản sửa bot tự sửa/xóa tin, working tree trên ed60401

- **Câu hỏi:** bản vá chưa commit có sửa đúng việc bot tự sửa/xóa tin làm mất lịch sử và còn đường nào chưa được xử lý?
- **Điều kiện:** snapshot HEAD ed60401 cộng toàn bộ thay đổi tracked trên đĩa lúc bắt đầu; manifest giữ hash. Bản đối chứng là HEAD với chính test mới. PostgreSQL/Redis/Qdrant dùng một lần không volume thật (53588/53589/53590), database probes riêng. Không .env thật; CUDA ẩn, model URL cổng chết, Python chặn mạng ngoài/cổng model. Chỉ thêm tệp audit và mục đo này theo CLAUDE.md; không sửa mã nguồn sản phẩm. Mục đo được ghi vào sổ chính khi hoàn tất.
- **Đăng ký trước:** không; kiểm hồi quy và tìm lỗi, không đánh giá chất lượng model.
- **Kết quả:**

  | Bộ kiểm | Kết quả từ JUnit |
  |---|---|
  | backend | tests=2230, failures=0, errors=0, skipped=0 |
  | baseline-new-tests | tests=3, failures=3, errors=0, skipped=0 |
  | patched-new-tests | tests=3, failures=0, errors=0, skipped=0 |
  | probes | tests=11, failures=0, errors=0, skipped=0 |
  | root | tests=243, failures=0, errors=0, skipped=1 |

  Bài baseline hỏng là kết quả mong đợi để xác nhận test bắt lỗi cũ. PASS ở probes nghĩa là tái hiện được lỗi chưa sửa, không phải đã sửa. Lần xác minh nguồn import ban đầu dừng vì dùng __file__ trên namespace package tools; đã đổi sang module cụ thể và chạy lại trước khi chạy test. Container PostgreSQL ban đầu chưa sẵn sàng, đã xác minh ready trước migration.

- **Kết luận:** bản vá sửa đường đã có raw ledger và sửa không đổi chữ. Xóa trước khi ledger nhận được tin bot vẫn tạo hàng is_bot=false, dời mốc và mất lịch sử. Các lỗi trước vẫn tái hiện, gồm reply AttributeError để lại lượt running và tin tiếp theo queued.
- **Trạng thái:** xong.
- **Bằng chứng:** data/evaluation/results/kept/bot-edit-review-20261110/; snapshot và bản đối chứng ở .scratch/bot-edit-review-20261110/. Chỉ trên máy.

## 10/11/2026 — Test cho sửa lỗi B, cách a (bot sửa/xoá tin của mình, sửa không đổi chữ)

- **Câu hỏi:** test mới có bắt được lỗi B trên code cũ không, và bản sửa có giữ toàn bộ test khác xanh không?
- **Điều kiện:**
  - Code: main `ed60401` cộng phần sửa chưa commit ở `history_service.record_edit`/`record_delete`.
  - Container dùng một lần: `postgres:16-alpine`, `redis:7-alpine`, `qdrant:v1.18.2` (cổng 55441/56381/56334, có `REDIS_URL`), migrate tới head.
  - Ollama cổng chết, CUDA ẩn.
- **Đăng ký trước:** không; kiểm thử hồi quy.
- **Kết quả:**

  | Lượt | Kết quả |
  |---|---|
  | 3 test mới, code cũ | 3/3 hỏng: mốc kênh dời sau khi bot sửa, sau khi bot xoá, và sau khi có lần sửa không đổi chữ |
  | Nhóm trí nhớ và sổ lịch sử, code mới | 56 đạt |
  | Backend đủ bộ | 2.230 đạt, 0 hỏng (5 phút 26 giây) |
  | Bộ gốc `pytest tests` | 242 đạt, 1 bỏ qua |
  | Bộ gốc chạy `pytest` không chỉ thư mục | 193 lỗi khi gom test. Lỗi do tôi gọi sai: pytest gom cả bản sao repo trong `.scratch/`. Chạy lại đúng lệnh thì xanh (dòng trên) |
- **Kết luận:**
  - Test mới bắt đúng lỗi, và đủ bộ vẫn xanh.
  - Phần chưa phủ: một lần xoá đến trước khi tin được ghi vào sổ thì không biết tin đó của ai, nên vẫn dời mốc như cũ.
  - Phía Discord thật chưa chạy.
- **Trạng thái:** xong; chưa commit.
- **Bằng chứng:** chỉ có dòng tổng kết trong phiên (scratchpad `rv2/fixb-*.txt`, không giữ).

## 10/11/2026 — Opus 5.5 và Fable 5.2 duyệt độc lập 9 lỗi; tái hiện "bot tự sửa tin làm mất lịch sử kênh"

- **Câu hỏi:** hai người duyệt độc lập có xác nhận 9 lỗi và các hướng sửa không, có tìm thêm lỗi không? Lỗi mới nặng nhất (bot sửa tin "⏳" của chính nó làm dời mốc kênh) có thật khi chạy không?
- **Điều kiện:**
  - main `ed60401`.
  - Hai agent chỉ đọc repo, chạy song song. Model tự báo: `claude-opus-5-5` và `claude-fable-5-2`.
  - Mỗi agent tự kết luận trước, rồi mới đọc bằng chứng và các hướng sửa trong brief.
  - Hai agent chỉ chạy Python thuần, không database, không GPU: Fable `fable52_check.py`, Opus `opus55_check_pure.py`. Thời gian đo của họ chậm hơn bình thường.
  - Lần tái hiện của tôi: test tạm `test_tmp_bot_edit_barrier.py` trên container dùng một lần, migrate tới head, Ollama giả. Lần ghi sổ và lần sửa tin của bot được gọi thẳng vào API, giả vai trò bot.
- **Đăng ký trước:** không; duyệt và tìm lỗi.
- **Kết quả:**

  | Mục | Opus 5.5 | Fable 5.2 | Tôi kiểm lại |
  |---|---|---|---|
  | 9 lỗi có thật | 9/9 (chạy 1, 9; đọc phần còn lại) | 9/9 (chạy 1, 9; đọc phần còn lại) | khớp |
  | Lượt bị bot bỏ (5xx, timeout, giao tin hỏng) chặn kênh, không riêng lỗi 1 | có (A) | có (N1) | khớp code: `fail_turn` trả về `queued`, không ai gọi lại |
  | Thử lại lượt "quên" nhận câu "tin đã bị xoá/sửa" | có | có (N4) | khớp code `prepare_turn` |
  | OCR `page_range` dựng hết tập trang trước khi kiểm | `1-5000000`: 6 s, đỉnh 281 MiB (bật `tracemalloc`) | `1-20000000`: 1,2 s | khớp code |
  | OCR không có chủ; thành viên đọc được job của người khác | có (E) | có (N6) | khớp: các route GET chỉ có `read_guard` |
  | Ba đồng hồ (ứng dụng, Postgres, Discord) so với mốc | có (F) | có (N3) | khớp; lệch sau khi máy ngủ chưa đo |
  | Bot sửa tin "⏳" của chính nó làm dời mốc kênh | có (B, chỉ đọc) | gần như vậy (N7: sửa tin không so nội dung) | **chạy: có** (bảng dưới) |
  | Lỗi 4 nên lấy giờ gửi từ database (4b) | nghiêng 4b | nghiêng 4b | đổi ý theo |

  | Tái hiện B | Kết quả |
  |---|---|
  | Lịch sử có lượt trước, trước khi bot sửa tin | có |
  | Ghi tin "⏳" của bot (`is_bot=true`), rồi sửa tin đó | 200, 200 |
  | Mốc của kênh | không có → 09:49:12 UTC |
  | Lịch sử có lượt trước, sau khi bot sửa tin | **không** |
  | Biến thể: người thường (`is_bot=false`, người khác) sửa một tin không liên quan | mốc dời, lịch sử cũng mất (`test_tmp_human_edit_barrier.py`) |
  | Database thật, chỉ đếm (bật rồi tắt): tin trong sổ theo loại | 2 server, 2 kênh; tin người 45, có sửa 0; tin bot 39, **có sửa 23**; tin mới nhất 03/11 |
- **Kết luận:**
  - Hai người duyệt xác nhận cả 9 lỗi và đồng ý gần hết các hướng sửa đang nghiêng. Cả hai nghiêng 4b thay vì 4a.
  - Lỗi mới nặng nhất là B: sự kiện sửa tin không phân biệt ai sửa, cũng không so nội dung, nên mỗi lần sửa đều dời mốc của cả kênh.
  - Trên server thật, sự kiện bot tự sửa tin đã đến sổ: 23/39 tin của bot có bản ghi sửa. Vì vậy với v1.6.0, mỗi câu trả lời có tin "⏳" sẽ xoá lịch sử kênh với Ún.
  - Người thường sửa một tin cũng xoá lịch sử kênh. Đó là thiết kế hiện tại, không phải lỗi gõ nhầm; giữ hay đổi là câu hỏi thiết kế.
- **Trạng thái:** xong; chưa sửa.
- **Bằng chứng:** `data/evaluation/results/kept/review2-second-opinion-20261110/`, gồm brief, script của hai agent, kết luận Opus viết trước khi đọc đề xuất, test tạm và `output.txt`. Đã commit ở `69ca4ad`.

## 10/11/2026 — Kiểm ý kiến thứ hai về 9 lỗi: lượt reply hỏng có chặn kênh không, đồng hồ app/DB

- **Câu hỏi:** sau khi lượt reply ném `AttributeError`, lượt đó nằm ở trạng thái nào và tin thường gửi tiếp trong cùng kênh có chạy được không? Đồng hồ ứng dụng và đồng hồ Postgres lệch nhau bao nhiêu (cách sửa "so giờ gửi với mốc" dựa vào hai đồng hồ này)?
- **Điều kiện:** main `ed60401`. Một tệp test tạm (đã gỡ khỏi cây; bản giữ ở scratchpad phiên `rv2/test_tmp_reply_block.py`) trên container `postgres:16-alpine`/`redis:7-alpine`/`qdrant:v1.18.2` dùng một lần, migrate tới head, Ollama giả. Mốc `__history__` đặt bằng đúng câu lệnh của migration `20261109_39` dòng 38. Hết hạn lease mô phỏng bằng cách lùi `lease_expires_at` 1 giây. Đồng hồ: 5 lần `SELECT clock_timestamp()` so với giờ Python lấy giữa hai đầu lượt gọi. Python chạy từ venv trên Windows, Postgres trong một container Docker vừa khởi động; đây cũng là bố trí của máy thật.
- **Đăng ký trước:** không; phép thử tìm nguyên nhân theo một ý kiến thứ hai.
- **Kết quả:**

  | Loại tin được reply | Lỗi | Lượt reply sau lỗi | Tin thường kế tiếp, cùng kênh | Sau khi lease hết + 3 lần gọi | Kênh khác |
  |---|---|---|---|---|---|
  | tin người | `ReplyTargetContext` không có `created_at` | `running`, lần thử 1 | `queued`, model không được gọi | reply `queued`/1, tin thường vẫn `queued` | chạy được |
  | tin của bot | `BotReplyTargetContext` không có `created_at` | như trên | như trên | như trên | chạy được |
  | không tìm thấy | `ReplyTargetContext` không có `created_at` | như trên | như trên | như trên | chạy được |

  | Đồng hồ | Kết quả |
  |---|---|
  | Postgres trừ ứng dụng, 5 lần | −0,2 đến −3,0 ms; thời gian một lượt gọi 1,3–6,3 ms |

  Đọc code đi kèm, phần chạy thử không phủ:
  - Bot gặp lỗi 5xx thì báo lỗi rồi bỏ lượt, không gọi lại execute. Xem `api_client.py` `_authorized_post` và `main.py` `answer_mention` (bắt `BackendClientError` rồi `return`).
  - Không tiến trình nào khác gọi execute cho lượt đang chờ.
  - Phiên Discord không tự đóng khi rảnh. `session_service.resolve` giữ phiên cũ chừng nào hội thoại gốc còn.
  - Lượt chỉ được dọn khi bật, tắt hoặc cập nhật bot qua bảng điều khiển: `control.py` gọi `cancel-open`, và lúc bật thì `cancel_previous_open` mặc định là có.
  - Đường gọi model hỏng thì khác: lượt trả `queued` với HTTP 200, bot gọi lại, và sau 3 lần thì thành `failed`.
- **Kết luận:**
  - Phần chạy thật cho thấy một tin reply hỏng chặn kênh đó cả sau khi lease hết hạn. Đọc code thì việc chặn kéo dài tới khi bot được bật, tắt hoặc cập nhật qua bảng điều khiển. Các kênh khác không bị ảnh hưởng.
  - Mục dưới chỉ nói tới lượt hỏng, nên đánh giá ở đó thấp hơn thực tế.
  - Đồng hồ được đo trên container vừa khởi động. Phép đo này chỉ cho biết hai đồng hồ lệch nhau bao nhiêu, không đo khe giữa lệnh "nhớ" và lệnh "quên". Lệch sau khi máy ngủ chưa đo.
  - Đính chính mục dưới: "cửa sổ vài mili giây" là suy đoán, chưa đo. Tỉ lệ 5/83 là số lịch sử, không phải dự báo.
- **Trạng thái:** xong; chưa sửa.
- **Bằng chứng:** `data/evaluation/results/kept/review2-second-opinion-20261110/` (test tạm, script đồng hồ, kết quả in ra). Đã commit ở `69ca4ad`.

## 10/11/2026 — Tái hiện bản nhận xét thứ hai (9 lỗi) trên main `ed60401`

- **Câu hỏi:** 9 lỗi bản nhận xét thứ hai nêu có thật trên main hiện tại không, và lỗi nào chạm người dùng ngay?
- **Điều kiện:** main `ed60401`. Một tệp test tạm (đã gỡ sau khi chạy) trên container `postgres:16-alpine`/`redis:7-alpine`/`qdrant:v1.18.2` dùng một lần, Ollama giả. Database thật bật để đếm (không đọc nội dung) rồi tắt.
- **Đăng ký trước:** không; phép thử tìm lỗi sau khi đọc bản nhận xét.
- **Kết quả:**

  | Lỗi | Cách kiểm | Kết quả |
  |---|---|---|
  | Reply Discord đọc `created_at` trên `ReplyTargetContext` | chạy: tạo mốc trong server, gửi lượt reply | `AttributeError` trước khi gọi model |
  | Mốc có sẵn trên database thật | đếm `source_memory_states` | 2 server Discord + 1 web đều có mốc từ migration; 5/83 lượt Discord cũ là reply |
  | Phát lại đáp án của tin đã sửa (`_safe_replay`) | chạy: lượt xong, sửa tin, gọi lại execute | trả nguyên đáp án cũ |
  | Câu hỏi điện thoại + email | chạy `read_evidence` | chỉ khối điện thoại được đưa cho model |
  | Số quốc tế `+1 415 …` | chạy `read_evidence` | báo `requested_field_missing` |
  | Route OCR nhận DPI bất kỳ | chạy `POST /api/ocr/jobs?dpi=50000` | 201, service nhận 50000 |
  | Admin bị hạ quyền vẫn đọc hội thoại người khác | đọc code: `ensure_conversation_access`, `conversations`, `research` lấy vai trò từ token (sống 15 phút), chỉ `require_admin` đọc lại database | có, theo code; code từ 20/08 |
  | Lưu "nhớ" khi "quên" chen trước snapshot | đọc code `chat_service` | có, cửa sổ vài mili giây |
  | Hai lần hạ quyền đồng thời | đọc code `auth_service.set_role`: đếm admin rồi cập nhật, không khoá | có (write skew) |
  | Xoá job OCR đang chạy; xoá sau khi khởi động lại | đọc code `ocr_job_service.delete`: worker còn `_save`; `root` chỉ có khi job đã nạp vào RAM | có cả hai |
- **Kết luận:** cả 9 có thật. Nặng nhất là reply Discord: không cần thao tác quên, vì migration đã đặt mốc cho mọi server cũ, nên khoảng 1/16 lượt Discord sẽ hỏng ngay khi chạy v1.6.0. Lỗi quyền admin có thật nhưng cũ, chỉ tác dụng khi bật đăng nhập và có nhiều tài khoản, cửa sổ ≤ 15 phút.
- **Trạng thái:** xong; chưa sửa.
- **Bằng chứng:** tệp test tạm đã gỡ; nội dung sẽ thành test hồi quy khi sửa.

## 10/11/2026 — Test cho bốn sửa theo bản nhận xét (quên trên Web, lượt Discord cũ, bảng OCR, bộ đo OCR)

- **Câu hỏi:** các test mới có tái hiện lỗi trên code cũ, và bản sửa có giữ xanh đủ bộ?
- **Điều kiện:** code sửa chưa commit trên `a5b653e`. Container `postgres:16-alpine`/`redis:7-alpine`/`qdrant:v1.18.2` dùng một lần (55441/56381/56334, có `REDIS_URL`), Ollama cổng chết, CUDA ẩn. Lượt "code cũ": `git stash` riêng 9 tệp nguồn, giữ test mới.
- **Đăng ký trước:** không; kiểm thử hồi quy.
- **Kết quả:**

  | Lượt | Kết quả |
  |---|---|
  | Test mới trên code cũ | hỏng hết: Web 1/1, bảng OCR 4/4 (gồm test TSV cũ đổi kỳ vọng), Discord 3/3. Discord hỏng một phần vì code cũ chưa có câu trả lời cố định để test nhập, nên bằng chứng chính cho lỗi Discord là đọc code |
  | Nhóm trí nhớ, code mới | 38 đạt (lần đầu 4 hỏng do test của tôi: mã người dùng không có trong bảng `users`, lượt cũ chưa đóng; và lộ thêm lỗi lịch sử giữ lời cũ của tin đã sửa, đã sửa luôn) |
  | Backend đủ bộ | 2.227 đạt, 0 hỏng (05:02) |
  | Bộ gốc | 242 đạt, 1 bỏ qua |
- **Kết luận:** test mới bắt đúng lỗi và đủ bộ xanh.
- **Trạng thái:** xong.
- **Bằng chứng:** chỉ dòng tổng kết trong phiên; JUnit ở scratchpad phiên (không giữ).

## 10/11/2026 — Hỏi đáp OCR sau khi sửa cách gắn nhãn bảng (cùng chữ OCR, phát lại)

- **Câu hỏi:** đổi luật tiêu đề bảng (chỉ nhận `<thead>`/`<th>`/`|---|`; bảng không chắc thì giữ bảng gốc làm bằng chứng) có làm 28 câu hỏi OCR kém đi với người chọn 2B?
- **Điều kiện:** code sửa chưa commit trên `a5b653e`; `scripts.ocr_evidence_eval --replay` lấy nguyên chữ OCR của lượt 2B ngay dưới (03:4x), nên chỉ phần dựng bằng chứng và lần chọn của 2B chạy lại; người chọn mặc định giờ là `general` (`qwen3.5:2b`). Ollama 0.40.13.
- **Đăng ký trước:** mục này, viết trước khi chạy. Dự đoán 27/28 như lượt gốc (câu trượt do OCR đọc "Liên Chiếu", phát lại vẫn giữ lỗi đó); bảng Ovis có `<thead>` nên hàng nay mang nhãn cột thay vì trần. Kém hơn 27/28 thì không gộp phần bảng mà báo lại.
- **Kết quả:**

  | Lượt, cùng chữ OCR | Đạt | Hồi quy | Mới |
  |---|---:|---:|---:|
  | Luật bảng cũ, 2B (03:4x) | 27/28 | 17/18 | 10/10 |
  | Luật bảng mới, 2B, phát lại (04:3x) | 27/28 | 17/18 | 10/10 |

  Câu trượt vẫn là "Tuyến Miền Trung xuất từ kho nào?": hàng được chọn đúng và nay mang nhãn ("Tuyên: Miền Trung | Kho xuất: Liên Chiếu | Số kiện: 63"), lỗi dấu là của OCR.
- **Kết luận:** dự đoán đúng; luật bảng mới không làm bộ này kém đi. Bộ ảnh không có bảng không tiêu đề hay nhiều tầng tiêu đề, nên lợi của bản sửa chỉ được kiểm bằng test đơn vị, không bằng số đo này.
- **Trạng thái:** xong.
- **Bằng chứng:** `data/evaluation/results/c57-compare-20261110/ocr/ocr-tablefix-2b-replay/report.json` (chỉ trên máy).

## 10/11/2026 — Hỏi đáp OCR với model mặc định của API (Qwen 2B) thay vì LFM3

- **Câu hỏi:** 28 câu hỏi trên 10 ảnh OCR có còn đạt khi người chọn bằng chứng là `general` mặc định (`qwen3.5:2b`) như API `ocr_job_service.ask`, thay vì LFM3 mà `ocr_evidence_eval` dùng mặc định?
- **Điều kiện:** main `a5b653e`, `scripts.ocr_evidence_eval --answer-model qwen3.5:2b`, OCR `ocr-ovis-v1` chạy lại cùng lúc, cùng manifest `data/benchmarks/ocr_evidence/v1`; Ollama 0.40.13; đối chứng là lượt LFM3 cùng ngày (28/28, mục 10/11 bên dưới).
- **Đăng ký trước:** mục này, viết trước khi chạy, sau khi một bản nhận xét chỉ ra API dùng `general` chứ không phải LFM3. Dự đoán: 2B đạt 25–28/28; CHANGELOG v1.6.0 ghi "LFM3 trả lời" là sai với cấu hình mặc định bất kể kết quả.
- **Kết quả:**

  | Người chọn bằng chứng | Đạt | Hồi quy | Mới |
  |---|---:|---:|---:|
  | LFM3 (lượt 02:2x cùng đêm) | 28/28 | 18/18 | 10/10 |
  | Qwen 2B, mặc định API (03:4x) | 27/28 | 17/18 | 10/10 |

  Câu trượt: "Tuyến Miền Trung xuất từ kho nào?" — 2B chọn đúng hàng, nhưng lần OCR này Ovis đọc "Liên Chiếu" (lượt OCR trước cùng đêm đọc đúng "Liên Chiểu"). Lỗi ở OCR, không ở người chọn; Ovis không cho cùng chữ giữa hai lần chạy cùng ảnh.
- **Kết luận:** dự đoán đúng; 2B chọn bằng chứng ngang LFM3 trên bộ này. CHANGELOG v1.6.0 nói "LFM3 trả lời câu hỏi về ảnh" là sai: API dùng `general` (2B). Bộ ảnh do Codex viết, chỉ là kiểm hồi quy.
- **Trạng thái:** xong.
- **Bằng chứng:** `data/evaluation/results/c57-compare-20261110/ocr/ocr-new-evidence-2b/report.json` (chỉ trên máy).

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
