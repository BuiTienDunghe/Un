# Điều phối — nền + Agent Eval

Chủ dự án giao (27/10/2026): "opus 5.5 của Ún" và "fable 5.1 của Ún" tự điều phối cho tới khi xong
`spec.md` (đạt hiệu quả), hoặc tới một ngưỡng dừng ở mục "Hạn mức" (đổi 28/10 01:11). Có ba phiên thực
hiện: "Nhân viên của Ún 1", "Nhân viên của Ún 2", "Nhân viên của Ún 3".

## Ưu tiên (chủ dự án, 28/10)

**Harness là điểm nổi bật nhất của dự án** — xử lý tốt, hiệu quả. Khi phải chọn, việc harness (ticket 20, 22, và
mọi khả năng agent) đi trước thí nghiệm model (M3). Mọi cải tiến harness phải có số đo trên Agent Eval.

**Benchmark phải uy tín, có điểm công bố** (chủ dự án, 28/10 00:30): mọi khẳng định chất lượng dùng benchmark có
paper/leaderboard chính thống, và tái lập một số đã công bố trước rồi mới đo thay đổi. Agent Eval tự viết chỉ là
test hồi quy (bắt thoái lui, so trước/sau), không phải bằng chứng chất lượng. Đang khảo sát benchmark phù hợp (ticket 24).

## Vai trò

| Phiên | Việc |
|---|---|
| opus 5.5 của Ún | Điều phối chính: giao ticket, gộp nhánh vào `main`, chạy bộ test đầy đủ, commit gộp, báo chủ dự án |
| fable 5.1 của Ún | Đồng điều phối: duyệt diff mỗi nhánh trước khi gộp; giữ chất lượng bộ bài Agent Eval; chọn mục tiêu M3 (ticket 08) |
| Nhân viên 1–3 | Mỗi phiên làm một ticket một lúc, trong worktree riêng |

## Quy tắc cho nhân viên

1. **Không bao giờ sửa file trong `C:\Users\dungbt06\local-ai-core` (checkout chính).** Cả bốn phiên
   đang dùng chung thư mục đó. Làm trong worktree riêng:
   ```
   git -c core.longpaths=true worktree add C:\Users\dungbt06\local-ai-core-wt\<NN-slug> -b wip/<NN-slug> main
   ```
2. Dùng Python của checkout chính: `C:\Users\dungbt06\local-ai-core\.venv\Scripts\python.exe`. Đã
   kiểm 27/10: chạy từ `<worktree>\backend` thì `import app` lấy code của worktree, không lấy code
   của checkout chính (venv không che gói cục bộ).
3. Commit trên nhánh `wip/<NN-slug>` của mình, theo kiểu message của repo (một câu tả hành vi mới,
   chữ thường, xem `git log`). **Không push, không merge, không đổi nhánh của checkout chính.**
4. Chỉ đụng đúng các file mà ticket liệt kê. Cần đụng thêm file khác thì hỏi điều phối trước.
5. Hiện chưa có stack Docker cho Ún: container đã tắt, còn `edu-postgres-1` (dự án khác) đang giữ
   cổng 5432. **Không bật, tắt hay xoá container nào.** Test cần Postgres thì ghi "chưa chạy, cần
   stack" — điều phối sẽ chạy sau.
6. Không đọc hay in `.env` (có khoá). Cần một biến thì đọc đúng dòng đó, che giá trị.
7. Xong thì gửi điều phối (`opus 5.5 của Ún`) một tin gồm: tên nhánh, các commit, lệnh test đã chạy
   kèm kết quả, những gì chưa kiểm, và nơi lệch khỏi ticket. Cập nhật `Status:` trong file ticket
   **ngay trên nhánh của mình**.
8. Bị chặn thì báo ngay, không đoán. Bị từ chối quyền thì báo lại, không nhờ phiên khác làm thay.

## Stack Docker

Chủ dự án cho phép (27/10): khi cần bật stack của Ún, **opus** được `docker stop edu-postgres-1`
(không xoá), xong việc thì `docker start edu-postgres-1`. Chỉ opus làm việc này; nhân viên và fable
không bật/tắt container. Stack chưa bật cho tới khi ticket 01 tái hiện xong cảnh "stack tắt".

## GPU

Mỗi lúc chỉ một việc nặng trên GPU, vì 07 và 09 đều ghi độ trễ và 09 có điều kiện dừng theo p50.
Thứ tự từ 27/10 18:45: **07** (ghi truy xuất lab + baseline) → **09** nhánh 0. Cập nhật 20:15: 09 dừng ở 2b,
GPU tối 27/10 cho phần đo của **10**; 09 chạy lại trọn một mạch sáng 28/10. Mọi eval stack
(`eval_stack --profile lab|heldout`) phải **dừng trước 02:45**: eval đêm 03:00 tự bật lab API ở
cổng 8100 và cần GPU; đêm 27→28/10 là đêm nghiệm thu của ticket 01.

## Đêm 28/10: chủ dự án đi ngủ (01:16)

"tôi đi ngủ, bạn chủ động được chứ — không tự ý xoá những thứ quan trọng; không tự tải những thứ nặng về." Áp cho mọi
phiên Ún tới khi chủ dự án nhắn lại:
- **Không xoá**: dữ liệu, DB (thật lẫn test, trừ dọn dẹp mà bộ test tự làm), collection Qdrant, model Ollama, tệp
  ngoài repo, nhánh `wip/*`, tag `eval-src/*`, thư mục `kept/`. Được xoá: worktree tích hợp tạm của opus sau khi gộp;
  code trong phạm vi ticket (vd shim theo C6).
- **Không tải nặng**: tổng một lần cài/tải trên 200 MB thì dừng, ghi số vào tệp, chờ sáng. Không `ollama pull`, không
  tải model/dataset HF.
- Không push, không đổi cấu hình máy; quyết định của chủ dự án (chỗ cắm BFCL, ticket 21…) để sáng.

## DB test dùng chung: chỉ opus chạy (28/10 01:25)

Hai lượt chạy bộ test đầy đủ của opus (01:09 và 01:13) đều đỏ 14 bài, mỗi lần một bộ khác nhau: một phiên Ún khác
(claude.exe opus, chạy `pytest … tests` qua PowerShell lúc 01:16) cũng dùng `local_ai_core_test` cùng lúc, và các
bài migration hạ/nâng schema giẫm lên nhau (lúc 01:19 DB đang ở revision 18, thiếu `conversations.title`). Từ giờ:
**chỉ opus chạy test có DB** (đặt `POSTGRES_TEST_URL`). Gốc rễ (01:27): `POSTGRES_TEST_URL` nằm sẵn trong biến môi
trường người dùng của Windows (`HKCU\Environment`), nên pytest của **mọi** phiên đều tự dùng DB test; lượt 01:21 của opus
cũng bị giẫm (30 bài đỏ, 01:23 có thêm một cặp pytest). Phiên khác chạy test phải bỏ biến: PowerShell
`$env:POSTGRES_TEST_URL=$null; $env:REDIS_TEST_URL=$null;`, bash `env -u POSTGRES_TEST_URL -u REDIS_TEST_URL`. Không
xoá biến khỏi máy (luật đêm: không đổi cấu hình) — chủ dự án quyết sáng. Phiên khác cần thì ghi vào tệp duyệt hoặc ticket, opus chạy
giúp khi gộp. Đính chính: lần nạp glm-ocr 00:54 là từ lượt test `after20` của chính opus (Ollama còn sống); lần 00:57
chưa rõ phiên nào.

## Sáng 28/10 — chờ chủ dự án

| # | Việc | Ghi chú |
|---|---|---|
| 1 | BFCL: cắm vào vòng lặp hay bước gọi model | `ticket24-design.md` có bảng; opus nghiêng vòng lặp |
| 2 | BFCL: nhiệt độ khi đo | NV3 đề xuất 0, chạy lạnh; Ún đang dùng 0,4 |
| 3 | BFCL (nếu cắm vòng lặp): ba công cụ của Ún ở lại hay bị thay trong lượt BFCL | |
| 4 | BFCL: cài venv | phiên NV3 bị bộ phân loại quyền chặn `pip install`; 119 gói, 94,5 MB; hai lệnh ở mục 1 của thiết kế. Opus không chạy thay |
| 5 | Đợt đo GPU gom lại | #2, #3 (Agent Eval v0.3, ~7 phút mỗi lần), ba nhánh e5 (~3 giờ) |
| 6 | Ticket 25 — nợ Discord sau 22 (3 món, mỗi món 2–3 cách) | `issues/25-discord-debt.md`; NV2 nghiêng 1B (test chặn lõi đọc thêm `discord_*`), 2A, 3A (để nguyên) |
| 7 | Ticket 20 #4 — Discord hiện tiến độ thế nào: D1 giữ "đang nhập", D2 một tin "⏳ Ún đang làm…" sửa dần rồi thay bằng câu trả lời, D3 đổi emoji trên tin người hỏi (👀→🔎→✅) | NV1 nghiêng D2. Đêm nay chỉ code móc lõi + web (SSE `progress`) + endpoint tiến độ, chưa code phía bot |
| 8 | Việc cũ còn treo | push, bot B1/B2, ticket 21 (tài liệu chưa có chủ), 5 collection Qdrant đo, v0.4 (L-b, L-c), 14/15 |

## Giữ im Ollama đêm 28/10 (phiên Quản lý xin, 01:00)

Từ khoảng 02:00 Quản lý đo độ trễ, cần GPU sạch tuyệt đối. Lúc 00:54 và 00:57 có hai lần glm-ocr được nạp, mỗi lần
khoảng 6 giây: đó là bước kiểm tra model khi app khởi động (`model_startup_probes`), do một phiên Ún bật app hoặc
chạy test. **Đến khi chủ dự án cho đo lại**, mọi lần chạy test hay bật app phải kèm
`OLLAMA_BASE_URL=http://127.0.0.1:9 MODEL_STARTUP_PROBES=false CUDA_VISIBLE_DEVICES=-1` (Ollama trỏ vào cổng chết như
CI; reranker chạy PyTorch ngay trong tiến trình python nên phải giấu GPU khỏi nó — đây là python.exe Quản lý thấy). Không chạy
`agent_eval`, `run_mteb`, `eval_stack`, `ollama run/pull`. Eval đêm 03:00 vẫn chạy (Quản lý tránh 03:00–03:05).
Backup 02:00 chỉ dùng đĩa và CPU (`pg_dump`).

## Xây trước, đo sau (chủ dự án, 28/10 00:58)

"Hôm nay chưa cần chạy GPU nhiều quá, hãy xây dựng trước đã." Từ giờ: ưu tiên code (ticket 20 #2–#4, 22, 23,
dựng BFCL); **hoãn** các lượt đo GPU dài (ba nhánh e5 của 09 ≈ 3 giờ, chạy BFCL). Các lần đo hồi quy Agent Eval
(~7 phút) gom lại chạy một đợt khi chủ dự án cho. Eval đêm 03:00 vẫn chạy (nghiệm thu ticket 01, ~3 phút).

## Nhường GPU cho dự án khác (chủ dự án, 28/10 00:45)

Một dự án khác của chủ dự án cũng dùng GPU này. Quy tắc:
- Phiên của dự án đó xin GPU thì **nhường**; họ báo xong thì dùng tiếp.
- Yêu cầu nhường gửi tới **opus** (điều phối), không tới từng nhân viên. Opus báo nhân viên đang giữ GPU dừng ở
  ranh giới an toàn (hết một lần đo, không bỏ dở giữa lần), gỡ model (`ollama stop`) để trả VRAM.
- Opus **được từ chối** khi đang có một lần đo mà dừng giữa chừng sẽ làm hỏng kết quả, hoặc việc thật sự cần
  thiết; khi đó trả lời rõ còn bao lâu xong.
- Khi không có GPU, các phiên làm việc không cần GPU (code, test không model, thiết kế, tài liệu).
- Mọi số độ trễ đo trong lúc dự án kia dùng GPU phải ghi là "GPU dùng chung", không so với mốc đo lúc GPU rỗi.

## Đóng băng main

**Gỡ lúc 22:35** (chủ dự án hỏi lại, đo lại): lý do 2 sai — Nhân viên 1 kiểm, API boot được trên schema cũ và
`/rag/search` không đụng bảng mới; lý do 1 yếu — diff của 16 không đụng đường truy xuất/embedding/eval_stack
(chỉ chat/chat_tools trong ollama_client). GPU lúc đó 0% tải, 1,8/16 GB. Bản gốc:
Từ 27/10 21:15 tới sau eval đêm 03:00 ngày 28/10: KHÔNG gộp code vào main (chỉ `.scratch`). Lý do: 09 đang
chạy và đòi worktree trùng main (editable trỏ về main); eval đêm bật lab API bằng code của main. Ghi chú:
lúc 21:10 đã gộp wip/10-keep (chỉ đổi mô tả công cụ trong `agent_service.py` + tài liệu) sau khi 09 bắt
đầu từ d1e2171 — không nằm trên đường đo của 09 (eval_stack, rag, embedding không đổi). Ticket 16 gộp
sáng 28/10, cần xét `alembic upgrade head` cho các DB.

## Tin nhắn

Ứng dụng giữ lại tin của một phiên khi nó gửi quá nhiều tin liên tiếp: khoảng **10 tin sau mỗi lần chủ
dự án gõ** (fable 5.1 đếm được, 27/10). Ban đêm không có người gõ, nên mỗi phiên chỉ còn ít tin; báo một
lần khi xong việc, không báo tiến độ. Lần đầu bị giữ (fable 5.1 sau khoảng 10
tin, 27/10; chủ dự án phải mở lại). Gom kết luận: mỗi nhánh một tin, đủ để không cần hỏi lại.

## Duyệt qua tệp thay vì tin nhắn (28/10 00:55)

Giới hạn khoảng 10 tin của mỗi phiên không chỉnh được từ đây (không có trong cài đặt của app; nó đặt lại khi chủ
dự án gõ vào chính phiên đó). Để fable không cạn lượt: fable ghi mỗi kết luận duyệt vào
`reviews/<nhánh>-<sha ngắn>.md` (trong checkout chính, chỉ thư mục này), dòng đầu là **GỘP ĐƯỢC** hoặc **CẦN SỬA**.
Nhân viên tự đọc tệp đó; điều phối đọc trước khi gộp. Fable chỉ nhắn khi có điều chặn hoặc cần quyết định.

## Gộp

Nhánh → fable 5.1 duyệt diff (đúng ticket? có hồi quy? test có kiểm đúng điều cần kiểm?) → opus gộp
vào `main` ở checkout chính → chạy test → xoá worktree. Chỉ một phiên (opus) ghi vào `main`.

## Hạn mức

Chủ dự án (28/10 01:11): "dừng khi đạt hiệu quả hoặc đạt ngưỡng: nhiệt độ gpu > 85%, limit tuần của tôi ? 90%,
limit fable > 90%". Đọc là ba ngưỡng, chạm cái nào cũng dừng:

| Ngưỡng | Đo bằng | Lúc ghi |
|---|---|---|
| Nhiệt độ GPU > 85 °C | `nvidia-smi` (opus chạy một bộ canh nền, báo khi vượt) | 60 °C, 41% tải lúc 01:11 (phiên Quản lý đang dùng) |
| Hạn mức tuần, tất cả model ≥ 90% | thẻ hạn mức của app (`get_usage`) | 45%, đặt lại 10:00 28/10 |
| Hạn mức tuần riêng Fable > 90% | như trên | 30%, đặt lại 10:00 28/10 |

Mỗi lần giao việc hay gộp, opus kiểm hai hạn mức. Chạm ngưỡng thì: không giao việc mới; các phiên dừng ở ranh giới an
toàn (commit việc dở lên nhánh `wip/`, không gộp nửa vời); `ollama stop` nếu Ún đang giữ GPU; opus báo chủ dự án.
GPU nóng do dự án khác thì opus báo cả phiên Quản lý. Thay ngưỡng 85% hạn mức tuần cũ (27/10).

## Bảng ticket

| # | Ticket | Phụ thuộc | Giao cho | Trạng thái |
|---|---|---|---|---|
| 01 | Eval đêm dừng sớm, báo rõ (M1a) | — | Nhân viên 1 | **đã gộp** — còn một đêm 03:00 thật |
| 02 | Một cách cài, xoá hack sys.path (M1b) | — | Nhân viên 1 | **đã gộp** |
| 03 | Compose chỉ chuyển tiếp, Docker sang v2 (M1c) | — | Nhân viên 2 | **đã gộp** |
| 04 | Một cơ chế bật bot + panel 401 (M1d) | 05 đã gộp | Nhân viên 1 | **đã gộp** |
| 05 | Dời job_*, query dashboard vào service (M1d) | 02 đã gộp | Nhân viên 1 | **đã gộp** |
| 06 | Agent Eval v0: khung chạy + bộ bài (M2) | — | Nhân viên 3 | **đã gộp** — chưa chạy lại với model thật |
| 07 | Agent Eval v0: ghi truy xuất thật + baseline 3 lần (M2) | 06 gộp; GPU sau 11 | Nhân viên 3 | **đã gộp** — 34/40 nóng, 29/40 t0.4 |
| 08 | Chọn mục tiêu thí nghiệm model (M3) | — (chỉ đọc) | fable 5.1 | xong — chọn B, nhánh 0 trước |
| 09 | Thí nghiệm B, nhánh 0 trước (M3) | 11 | Nhân viên 1 chuẩn bị, Nhân viên 2 chạy | nhánh 0 **âm**; B đầy đủ đang làm (đã duyệt tải) |
| 10 | Nâng harness theo lỗi đo được (M4) | 07 gộp | Nhân viên 3 | **xong** — 3a, v0.2, mô tả 800 đã gộp; 1a, 2b, 1a-v2 đo xong, không ship (luật đăng ký); sửa bộ chấm để v0.3 |
| 11 | Đo dao động 788 câu held-out (tiền đề M3) | stack | Nhân viên 2 | **đã gộp** — sàn = 0 câu |
| 12 | Dọn nhỏ sau 03 (được phép trượt) | — | Nhân viên 3 | **đã gộp** |
| 13 | Chuẩn bị đóng gói e5-large (chỉ code) | — | Nhân viên 1 | **đã gộp** |
| 14 | Cắm model decided làm cổng trí nhớ | I/O của decided | — | để sau (ngoài kế hoạch này) |
| 15 | Ghi phiên bản runtime embedding, nhúng lại sau khi nâng Ollama | — | — | để sau M3 |
| 16 | Kiểm soát harness: ngân sách cả lượt, lỗi có mã, trace bền (M4 cách B) | 10 gộp | Nhân viên 1, 3 | **xong** — không suy giảm 34/34 |
| 17 | forget_member xoá cả trích đoạn thành viên trong agent_traces | 16 gộp | Nhân viên 1 | **đã gộp** |
| 18 | test_debt_t1_t2_t3 tự deadlock lúc teardown | — | Nhân viên 1 | **đã gộp** |
| 19 | forget_member bước 6 xoá turn ở mọi guild | 17 | Nhân viên 1 | **đã gộp** (cả test bổ sung) |
| 20 | Khả năng cơ bản cho agent: đọc dài, kiểm câu trả lời, báo tiến độ | — | NV3 (v0.3), NV1 (#1–#4) | #1 (2d4a830), #2 (86c419c), #3 (80cd369) đã gộp, đo hoãn; còn #4 stream tiến độ |
| 21 | Tài liệu không có chủ: agent đọc mọi tài liệu, kể cả PDF Nghiên cứu của người khác | — | — | chờ chủ dự án |
| 22 | Tách mềm Discord: lõi không import Discord; Discord tự cắm qua registry | 20 #1 (1) | NV2 (C1–C3, C5–C6), NV1 (C4) | C1–C3 + tài liệu C6 gộp d1711e7; còn C4 (NV1), xoá shim/allowlist sau C4 (NV2) |
| 23 | Bảng điểm harness: đúng, hiệu quả, bền, minh bạch + lịch sử | — | Nhân viên 3 | gộp 2818573 (tới 059edf3); 2eec41f (cột số liệu không tra) chờ fable |
| 24 | Đo harness bằng benchmark uy tín có điểm công bố | — | Nhân viên 3 | BFCL cách A; thiết kế gộp 2f362cd; chờ chủ dự án: chỗ cắm, nhiệt độ, cài venv |

## Mốc so sánh của bộ test

27/10, main ed51b4b, stack Ún bật, DB `local_ai_core_test` + Redis DB 15: backend 1045 xanh / 1 đỏ /
1 skip (2 phút 45 giây); root 65 xanh. Cái đỏ có sẵn trên main, không do nhánh nào gây ra:
`test_postgres_cleanup_lifecycle.py::test_postgres_log_and_ocr_retention_execute_only_due_rows`
(`assert 3 == 1`). DB test còn sót bản ghi OcrRun cũ, mà test lại đếm cả bản ghi không phải của nó.

Sau khi gộp 03 (main 9e00ed5): backend 1049 xanh / 0 đỏ / 1 skip; root 65 xanh. Test cleanup đỏ ở lần
trước giờ xanh — đúng với giải thích "bản ghi sót": lần chạy trước đã xoá chúng (ticket 12 mục 4 vẫn
cần, vì DB test sẽ lại có rác khi một test bị ngắt giữa chừng).

Sau khi gộp 01 (main 4844878): backend 1060 xanh / 0 đỏ / 1 skip (3 phút 10 giây); root 65 xanh.

Sau khi gộp 06 (main 7c645ec): backend 1104 xanh / 0 đỏ / 1 skip (3 phút 16 giây); root 65 xanh.

Sau khi gộp 12 (main 1c78054): backend 1106 xanh / 1 lỗi teardown / 1 skip. Lỗi là deadlock khi
DELETE documents trong `test_debt_t1_t2_t3.py`: lúc 17:59 Nhân viên 1 chạy chen một bài redteam trên
cùng DB test. Chạy lại riêng hai file đó (debt + redteam) trên main: 18 xanh. Không phải hồi quy.

Sau khi gộp 02 (main 73e3faa): backend 1107 xanh / 0 đỏ / 1 skip; root 65 xanh.

Sau khi gộp 05 (main 9d3fbe8): backend 1109 passed, 1 skipped, 5 warnings; root 65 xanh.

Sau khi gộp 09-prep + 04 + 07 (main 457c7c1): backend 1140 xanh / 0 đỏ / 1 skip; root 71 xanh.

Sau khi gộp phần không-GPU của 10 (main d825aed): backend 1148 xanh / 0 đỏ / 1 skip; root 71 xanh. Ghi chú: test_agent_service.py CÓ dùng Postgres (skipif theo POSTGRES_TEST_URL) — fable đính chính.

Lưu ý trước khi push: `data/evaluation/results/kept/` giờ 4,1 MB (ticket 07 + 10 thêm 27 lần chạy Agent
Eval, mỗi lần có manifest/task_results/events/summary). Quy ước của chủ dự án: hỏi trước file lớn (ghi
nhớ "Không đưa data train/thiết kế lên GitHub").

## Việc sáng 28/10 (theo thứ tự)

1. Đọc kết quả eval đêm 03:00 (`data/logs/nightly_eval.log`): exit 0 là nghiệm thu ticket 01.
2. Đọc báo cáo ticket 09 của Nhân viên 2 (hoặc chỗ nó dừng); fable duyệt; gộp.
3. Ticket 16 (fable đã duyệt dceaaab; chủ dự án đã cho phép nâng DB test 27/10 22:10): nâng DB test → chạy
   riêng test_agent_trace_summaries.py → gộp → chạy bộ đầy đủ. Không nâng DB thật (launcher tự nâng).
4. GPU, mỗi lần đo gỡ model chính trước: 1a-v2 của ticket 10 (`wip/10-1a-v2`, ~8 phút) → bước 5 của 16.
5. Hỏi chủ dự án: push (kept/ 4,6 MB). edu-postgres-1: chủ dự án nói **không cần mở lại** (27/10 23:00) — giữ stack Ún chạy;
   bot chạy kiểu nào (B1 chỉ Docker / B2 chỉ trên máy).

Sau khi gộp 16 (main 001966b, DB test ở 20261027_35): backend 1205 xanh / 1 lỗi teardown / 1 skip; root 74 xanh + 1 skip. Lỗi là `test_debt_t1_t2_t3` tự deadlock (đỏ 1/3 khi chạy riêng, không ai dùng chung DB) — **đính chính** ghi chú "va chạm" lúc 18:02 ở trên; ticket 18.

## Nguồn gốc của các lần đo (28/10 00:25)

Gộp bằng cherry-pick làm commit mà manifest eval ghi lại biến khỏi lịch sử main. Đã kiểm mọi `commit` trong
manifest ở `kept/` và `heldout_retrieval_v1/results/`: 7 commit không thuộc main (07 baseline `6a2c3f9` — nhánh đã
xoá; các lần đo của ticket 10 trên `wip/10-harness`, `wip/10-1a-v2`). Đã gắn tag `eval-src/<sha>` cho cả 7 để không
mất khi dọn nhánh. **Từ nay: nhánh nào có lần đo được trích dẫn thì gộp bằng merge commit (`--no-ff`), không
cherry-pick** (v0.3 đã gộp như vậy).

## Nhật ký nhường GPU

| Lúc | Ai xin | Khung | Ghi chú |
|---|---|---|---|
| 28/10 00:35 | phiên "Quản lý" (dự án decision model, `C:\Users\dungbt06\Fine-tune`) | ~00:40 → 02:55 (≈ 2 giờ) | chấm Qwen3.5-4B, đo độ trễ batch 1. Ún: Nhân viên 1 chạy xong `v0.3-read-B-r1-cold` rồi gỡ model; r2 chạy sau. Eval đêm 03:00 vẫn chạy (đã báo bên kia) |
