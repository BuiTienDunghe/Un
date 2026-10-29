# 20 — Khả năng cơ bản cho agent: đọc dài, kiểm câu trả lời, báo tiến độ

Status: đang làm — cách A (chủ dự án 28/10 00:20): v0.3 → #1 → #2 → #3 → #4; bỏ #5. #3-B trượt luật (15:13); #3-C trượt điều 3 (19:02): 6/9 trên 9 bài đoạn dán (cũ 2/9), `n` sạch, nhưng bài mới chỉ 1/3; phiếu cũ giữ. Gói #3-D duyệt 21:20 (bước 1 nhắc lại + 3' tìm trong đoạn dán, ba nhánh, bài mới mù): dừng giữa lần đo (22:45), câu trả lời một bài phụ thuộc bài chạy trước nó; #3-D đo lại dưới cô lập (23:42): cả hai đề xuất trượt (B ở B3, C ở C2 + C3), không gộp gì; mốc mới nền 50/62 cô lập. 29/10 chủ dự án duyệt đợt đo phân xử N1 (nạp nguyên văn bản dán khi vừa cửa sổ) / C7 (7 vòng công cụ khi có đoạn dán) trên `int/20-arb` (08:55): NV1 hai nhánh, NV3 bài mù, opus đăng ký
Type: task
Blocked by: — (cần bộ bài v0.3 có bài đọc dài để đo)

## Vì sao

Chủ dự án (27/10 23:50): harness chưa có những khả năng cơ bản như "đọc chính xác input dài" hay "thêm
khả năng như một agent", và khảo sát trước chỉ xét 4 mục kiểm soát do điều phối tự chọn — **sai phạm vi**.
Khảo sát lại rộng hơn trên tài liệu chính thức: `harness-capabilities-survey.md` (cùng thư mục; 10 nhóm khả
năng, 7 harness, nguồn có ngày).

## Ún thiếu gì (kiểm code 27/10)

| Khả năng các harness có | Ún hiện tại | Bằng chứng |
|---|---|---|
| Đọc tài liệu dài theo trang / "đọc tiếp" qua một handle | Agent chỉ thấy 400 ký tự đầu của tối đa 5 đoạn mỗi lần tra; không có công cụ đọc tiếp | `agent_service.py` `_clip(content, 400)`; `models.yaml:24-25` |
| Input dài của người dùng (chia nhỏ, map-reduce, lưu thành tài liệu rồi đọc) | Tin nhắn > 10 000 ký tự bị từ chối | `chat_schema.py:5` |
| Đọc tin Discord quanh một tin (`read_messages_around`) | Không có | `agent_service.py` |
| Kiểm câu trả lời theo luật (đoạn trích phải có trong cái đã tra) | Có cho RAG và Nghiên cứu, **không** cho agent | `answer_grounding.grade_rag_answer` dùng ở `routers/rag.py:6`, `research.py:24` |
| Báo tiến độ khi agent chạy (stream các bước) | Chế độ agent không stream | `routers/chat.py:26` (`stream and not use_tools`) |
| Nén / tóm tắt hội thoại dài | Web chat bỏ tin cũ ngoài 40 tin; Discord có rút gọn tầng 3 | `settings.py:202` |
| Lập kế hoạch, agent con, tìm công cụ, chạy code, skills | Không có | — |

Nguyên liệu đã có sẵn: lớp chữ theo trang PDF (`routers/documents.py:144`), danh sách đoạn của tài liệu
(`:178`), kho tài liệu + upload (một đoạn dán dài có thể thành tài liệu tạm).

## Xếp hạng giá trị cho Ún (theo khảo sát; suy luận của agent phụ, điều phối đồng ý)

Ún bị giới hạn bởi cửa sổ 16k và ngân sách 90 s hơn là bởi cỡ 9B. "Code thường" = không tốn thêm lượt model.

| # | Khả năng | Loại | Đổi lời model đọc? | Rủi ro |
|---|---|---|---|---|
| 1 | `read_document(doc_id, from_chunk, n)` trả handle + xem trước; `read_messages_around` | code thường; model chỉ đưa số | có (thêm công cụ) | tốn một trong 3 vòng |
| 2 | Kiểm câu trả lời agent bằng `answer_grounding` sẵn có, thử lại 1 lần khi trượt | code thường | không (trừ khi thử lại) | thêm một lượt khi trượt |
| 3 | Input dài: đoạn dán > ngưỡng thành tài liệu tạm, agent đọc qua công cụ #1 | code thường | có | phải xoá tài liệu tạm |
| 4 | Stream tiến độ các bước agent tới web/Discord | code thường | không | không |
| 5 | Đặt tài liệu trước câu hỏi, trích trước khi trả lời | lời dặn | có | ticket 10 cho thấy đổi lời dặn xáo 38/40 câu |
| — | Agent con, tìm công cụ, lập kế hoạch, chạy code, skills | — | — | giá trị thấp với 3 công cụ, 1 GPU, model 9B (khảo sát §4, §6) |

## Đo

Agent Eval v0.2 không có bài nào đòi đọc quá 400 ký tự hay input dài → **v0.3 phải thêm bài đọc dài**
trước khi đo #1 và #3, cùng các sửa đã gom (doc-27, hist-07, NOT_FOUND, hist-08, "không hỏi lại server").
Luật đo: gỡ model trước mỗi lần, đăng ký trước, so từng bài chỉ tới chỗ khác đầu tiên.

## Comments
- 28/10 00:20 (chủ dự án): **cách A** — bộ bài v0.3 có bài đọc dài trước, rồi #1 đọc theo handle → #2 kiểm
  câu trả lời → #3 input dài thành tài liệu tạm → #4 stream tiến độ. Bỏ #5.
- Phân việc (opus 5.5): Nhân viên 3 làm v0.3 (gom các sửa bộ chấm đã ghi + bài đọc dài, theo giao diện công
  cụ của #1); Nhân viên 1 thiết kế #1 trước (schema công cụ, đường lấy dữ liệu, giới hạn kết quả, hợp đồng
  fixture cho eval), gửi cả điều phối lẫn Nhân viên 3; code #1 sau khi duyệt. #2–#4 nối tiếp, cùng
  `agent_service.py` nên một người làm lần lượt. Mỗi bước đo bằng v0.3, đăng ký trước, gỡ model trước mỗi lần.
- 28/10 00:40 (opus 5.5): #1 thêm 2 công cụ → agent có 5 công cụ, **chạm điều kiện mở lại registry** chủ dự án
  đặt ở ticket 16 ("chỉ khi có công cụ thứ 4"). `agent_service.py` 276 → 466 dòng trong ngày, bị đụng ở 8
  commit — điểm nóng duy nhất của `backend/app` hôm nay. Thiết kế #1 phải so (a) giữ một file / (b) registry
  tối thiểu trong file / (c) tách gói `app/agent/` (commit đầu chỉ dời code, kiểm bằng Agent Eval lạnh trùng
  40/40). Chủ dự án chọn.
- 28/10 01:20: bản thiết kế #1 của Nhân viên 1 lưu nguyên văn ở `ticket20-design-1.md` (cùng thư mục): schema 2
  công cụ mới, đường lấy dữ liệu, trần kết quả, hợp đồng fixture cho v0.3, 7 chỗ lựa chọn (H, A, P, L, R,
  tổ chức code (a)/(b)/(c), D). Chờ chủ dự án chốt. Phát hiện kèm theo về quyền đọc tài liệu → ticket 21.
- 28/10 01:35 (chủ dự án: "7 cái kia quá đơn giản" → điều phối quyết): phần tài liệu chốt H1, A2, P2, L2
  (`agent.read_result_max_chars` 6 000), tổ chức code (b) registry trong file. Phần Discord (`read_messages_around`,
  `message_id` trong `search_history`, R, D) **tạm giữ**: chủ dự án nêu ý tách bot Discord khỏi phần còn lại,
  đang hỏi lại phạm vi. Nhân viên 1 code (1) registry chỉ dời code → fable duyệt → (2) handle → (3) read_document.
- 28/10 00:10 (Nhân viên 3) — **Đăng ký trước baseline v0.3**, viết trước khi chạy.
  - Bộ bài `agent-eval-v0.3` (48 bài: 40 cũ đã sửa + 8 bài đọc dài), bộ chấm `agent-eval-grader-v0.3`. Code: main
    `f2af55e` cộng các commit eval của nhánh `wip/20-eval-v03`, không đổi `backend/app`. Truy xuất của 6 bài
    tài liệu mới ghi lúc 00:00 qua API lab (`retrieval_manifest.json`).
  - Quy trình: worktree `20-eval-v03`, cây sạch; trước MỖI lần đo gỡ `qwen3.5:9b` (không đụng model nhúng);
    t0, seed 42, `--probe`. Hai lần lạnh liên tiếp, `v0.3-base-r1-cold` và `v0.3-base-r2-cold`, để kiểm lặp lại
    trên bộ bài mới.
  - Đây là mốc, không có luật ship. Ghi: tổng; từng bài trong 8 bài mới; `by_check`; số lượt gọi công cụ ở doc-38.
  - Dự đoán (sai thì báo, không sửa bài sau khi thấy kết quả):
    - doc-33..37 và hist-11 trượt cả 6, vì đáp án nằm ngoài phần agent đọc được. Bài nào đạt thì đọc tay: nếu
      model đoán trúng thì ghi là lỗi của bài, không lặng lẽ bỏ bài.
    - doc-39 trượt với `INPUT_TOO_LONG`, 0 lượt gọi model.
    - doc-38 (đối chứng) đạt.
    - r1 trùng r2 từng chữ.
  - Chưa có: bài L-b (đáp án ở đoạn kề), vì với mọi câu hỏi tự nhiên, 5 đoạn trả về trên tài liệu 10 đoạn đã
    chứa đoạn có đáp án. Bài L-c (đọc theo số trang, P2) cũng chưa có, vì corpus lab chỉ có tệp txt/md, không
    có trang. Cả hai cần thêm tài liệu dài hơn hoặc có trang vào corpus lab, và một phiên bản bộ bài sau.
- 28/10 00:20 (Nhân viên 3) — **Kết quả baseline v0.3**, đo 00:04–00:11. Báo cáo:
  `data/evaluation/results/kept/agent-eval-v0.3-baseline-20261028/REPORT.md`.
  - Lạnh: r1 = r2 = 35/48, trùng từng chữ 48/48. Đúng cả bốn dự đoán: 6 bài đọc dài trượt; doc-39 bị từ chối
    `INPUT_TOO_LONG`; doc-38 (đối chứng) đạt với 1 lượt tra; r1 = r2.
  - 40 bài cũ: 34/40, trùng từng chữ với lần B của ticket 16 (22:57). Bộ chấm v0.3 không lật bài cũ nào.
  - Bài đọc dài: phần lớn nói thật là không thấy; doc-34 nhận ra bảng bị cắt; ba bài tra lại 2–3 lần.
    hist-11 bịa, ghép giờ họp và phòng B203 thành phương án dã ngoại.
  - Model nhúng 0.6B còn nạp lúc bắt đầu cả hai lần (giống lần 22:57); điều kiện "không có model nhúng" chưa đo.
  - Chờ v0.4: bài L-b, bài L-c, hist-11 cấm dữ kiện bịa, hist-03 cho tra tài liệu trước.
  - Chờ v0.4 (chủ dự án chốt 28/10, qua fable): tiêu chí "trả lời có số liệu mà không tra" — bài có `tools_required`
    mà agent không gọi công cụ và câu trả lời chứa con số hoặc đơn vị tiền. Định nghĩa ở
    `reviews/wip-20-agent-reading-8cc0f73.md`; hai lỗi regex (doc-12, doc-19) ở review cd99811. Cũng là cột "bịa" cho 23.
- 28/10 (Nhân viên của Ún 1): #1 phần tài liệu xong — wip/20-agent-reading 3d5927a (registry b, fable duyệt),
  3515226 (search_documents trả document_id/chunk_index/chars; read_document theo đoạn hoặc theo trang, chỉ mở tài
  liệu đã tra trong lượt, xếp đoạn nguyên vẹn vào trần 6 000 kèm next_from_chunk; DocumentReader =
  ChunkInspectionService.read_chunks/chunks_on_page; eval dùng FixtureDocuments trên documents.jsonl). 164 test xanh,
  kiểm ngược đỏ đúng chỗ. Chưa đo bằng eval (cần GPU). L-b, L-c, P2 chưa đo được vì v0.3 không có bài. Phần Discord
  (read_messages_around, message_id) tạm giữ chờ quyết định tách bot.
- 28/10 00:25 (opus 5.5): chủ dự án đã chọn tách mềm Discord (ticket 22) → `read_messages_around` và `message_id`
  sẽ do gói Discord đăng ký qua registry sau ticket 22, không vào lõi. Đo #1 bằng v0.3 tối nay (≈ 6 phút GPU,
  đăng ký trước theo đề xuất của Nhân viên 1, nêu rõ rủi ro doc-38 đọc thừa); kết quả là test hồi quy nội bộ, không
  phải khẳng định chất lượng (quy tắc benchmark của chủ dự án, ticket 24).
- 28/10 00:30 (Nhân viên 1, đo v0.3 sau #1, hai lần lạnh trùng 48/48; test hồi quy nội bộ): tổng 35 → 34. Bài đọc
  dài 0/5 → 4/5 (đúng việc của công cụ; 0/5 lần chép sai document_id; đối chứng doc-38 không đọc thừa). Nhưng 40
  bài cũ 34 → 29: 37/40 câu trả lời đổi chữ vì lời dặn và mô tả công cụ đổi; 7 tụt (3 thiếu tên tệp/trang, 2 viết
  "không thể tìm thấy" không khớp mẫu chấm — nghi lỗi bộ chấm, xét ở v0.4, hist-05, hist-08 lại hỏi "server nào"),
  2 lên. Không bài cũ nào gọi công cụ mới. doc-36 trượt: model đọc từ đoạn 0 thay vì đoạn 9.
- 28/10 00:35 (opus 5.5): chọn (B) — bỏ câu mới trong lời dặn, để mô tả công cụ tự nói, đo lại; quyết định đăng ký
  trước: #1-B giữ ≥ 4/5 bài đọc dài và 40 bài cũ ≥ 33 → đề xuất ship #1-B, không thì (C) nhiều seed.
- 28/10 00:55 (opus 5.5): #1-B gộp vào main bằng merge commit (2d4a830), fable duyệt GỘP ĐƯỢC (reviews/
  wip-20-agent-reading-8cc0f73.md). Luật đăng ký đạt: 38/48, đọc dài 4/5, bài cũ 33 (= ngưỡng). Còn: #2 kiểm câu trả
  lời, #3 input dài thành tài liệu tạm, #4 stream. doc-10 bịa số khi không tra → đưa vào lý do cần #2.
- 28/10 01:10 (Nhân viên 1 thiết kế #2, opus 5.5 duyệt): kiểm **con số**: mọi số ≥ 2 chữ số trong câu trả lời phải
  có trong câu hỏi + hội thoại + kết quả công cụ của lượt (K3). Đo trên 144 câu đã lưu: bắt 3 câu trượt (doc-10 bịa
  phụ cấp, doc-22, doc-33 ở A), **0** báo nhầm; bộ kiểm chữ sẵn có (K1) báo nhầm 7/28 câu đạt có tra (25%) nên chỉ ghi trace. Trượt
  → thử lại một lần có công cụ, kèm lời dặn nêu các số không có nguồn (T1), chỉ khi còn ≥ 20 s. Điểm mù: số tự tính,
  số viết bằng chữ, câu bịa không có số. Code chỉ `run()` + `answer_figures.py`; gộp trước C4 của ticket 22.
- 28/10 01:10 (opus 5.5): #2 gộp --no-ff 86c419c (fable GỘP ĐƯỢC ebf2686; đo hoãn), CHANGELOG 36e4766. #3 thiết kế của
  Nhân viên 1 duyệt: S1 (đoạn dán ở lại trong tin nhắn, chia đoạn lúc đọc, id `paste_`+sha256[:12], không migration,
  không lập chỉ mục), trần 100 000 ký tự ở chế độ công cụ (chat thường giữ 10 000, 422 INPUT_TOO_LONG), phiếu đầu-cuối
  ~600+600 ký tự. Chi tiết kỹ thuật do opus chốt; chủ dự án đổi được.
- 28/10 01:51 (opus 5.5): #4 thiết kế của Nhân viên 1 duyệt phần kỹ thuật: móc `on_step` không chứa nội dung, nhãn do
  công cụ mang, web W1 (luồng phụ + SSE `progress`; phải sao ContextVar hạn giờ sang luồng), kho tiến độ P-a (dict
  trong tiến trình API, xoá khi xong + trần giờ sống), endpoint tiến độ cho bot. Cách bot hiển thị (D1/D2/D3) chờ chủ dự án.
- 28/10 02:00 (Nhân viên 3) — **Agent Eval v0.4 sẵn sàng; đăng ký trước baseline v0.4.** Chưa chạy; lần chạy gom vào đợt
  đo chung. Nhánh `wip/20-eval-v04`, cắt từ main `a6b08ae`.
  - Thay đổi (chi tiết ở README của bộ bài, mục v0.4):
    - mục mới `figures_without_lookup`, khớp chấm tay 61/61 câu đã lưu;
    - `NOT_FOUND_PATTERN` nhận "không (thể|được) tìm (thấy|ra)";
    - regex riêng của doc-19 nhận "không trả về";
    - hist-11 cấm B203, 9h, 23/10;
    - hist-03 cho tra tài liệu trước;
    - khoảng `n` 1–3 của `read_document`.
    - Không thêm bài L-b, L-c.
  - Chấm lại 6 lần v0.3 đã lưu, chỉ để chẩn đoán: base 35→35; #1 34→35 (doc-12, doc-19 thành đạt; doc-33 thành trượt vì
    xin `n=5`); #1-B 38→38 (doc-19 thành đạt, doc-33 thành trượt). Mục mới bắt doc-10 và doc-22 ở #1-B.
  - **Đăng ký trước baseline v0.4:**
    - Code là main lúc chạy, ghi commit. Bộ bài `agent-eval-v0.4`, bộ chấm v0.4.
    - Gỡ `qwen3.5:9b` trước mỗi lần; t0, seed 42, `--probe`; hai lần lạnh `v0.4-base-r1-cold`, `v0.4-base-r2-cold`.
    - Khai `--gpu-shared` nếu runner đã có (ticket 23); nếu chưa thì ghi tay trạng thái GPU.
    - Chỉ chạy khi chủ dự án cho đo lại; luật giữ im Ollama vẫn giữ tới lúc đó.
    - Không có luật ship. Ghi: tổng; 8 bài đọc dài; số lượt `figures_without_lookup` và bài nào; `args_valid` của
      `read_document`; doc-39.
  - Dự đoán (sai thì báo, không sửa bài):
    - r1 trùng r2 từng chữ.
    - doc-39 **không còn bị từ chối**. #3 nâng giới hạn của `ChatRequest.message` ở chế độ công cụ lên `PASTE_MAX`
      100 000, và runner đọc giới hạn từ schema. Đoạn dán 10 164 ký tự sẽ đi qua phần xử lý dán dài trong `AgentService`
      (`take_pastes`), nên đây là lần đầu doc-39 đo được #3.
    - Không đưa con số dự đoán cho tổng. Code trên main khác mọi lần đã lưu (#2, #3, #4 vào sau #1-B), và mỗi lần đổi mô
      tả công cụ đã xáo 37–39/40 câu trả lời. Bảng chấm lại chỉ cho biết bộ chấm v0.4 xử lý câu cũ thế nào.
- 28/10 08:29 (opus 5.5) — **Đo #2, #3 và mốc v0.4 xong** (đợt A+B, chủ dự án duyệt 07:58; GPU không dùng chung).
  - #2 (`86c419c`): 39/48; mọi dự đoán đúng (46/48 câu trùng #1-B, không bài đạt nào thành trượt, doc-10 6 → 0 số không
    nguồn). **Đạt luật → giữ.** Ngoài luật: lần làm lại của doc-22 không tra, và câu cuối viết cho người dùng "tôi cần
    điều chỉnh lại câu trả lời". Chủ dự án quyết có sửa `retry_instruction` không. `kept/agent-eval-v0.3-answer-check/`.
  - #3 (`80cd369`): 39/48; 47/47 câu trùng #2; doc-39 tới agent nhưng gọi `search_documents` thay vì `read_document`,
    rồi hỏi lại người dùng. **Trượt 1/3 điều kiện → không đề xuất giữ.** Code đã trên main, nên bốn cách (giữ, sửa lời
    trong phiếu, harness tự đọc, lùi) chờ chủ dự án chọn. `kept/agent-eval-v0.3-pastes/`.
  - Mốc v0.4 (`7b44b03`): 39/48, r1 = r2; dự đoán đúng; 0/48 câu khác lần đo C4, nên #4 không đổi hành vi model.
    `kept/agent-eval-v0.4-baseline-20261028/`.
- 28/10 08:50 (opus 5.5) — **#3-B: sửa lời phiếu đoạn dán, cách B (chủ dự án chọn "Sửa lời phiếu" rồi "Tách hai
  người").** Lý do: #3 trượt vì doc-39 gọi `search_documents` rồi hỏi lại người dùng (`kept/agent-eval-v0.3-pastes/`).
  Chỉ có một bài đoạn dán, nên bài thi và lời phiếu phải do **hai người viết độc lập**, để không sửa khớp một bài.
  - **Nhân viên 3 — bài đoạn dán, nhánh `wip/20-paste-tasks` cắt từ main `60532ed`.**
    - Bộ bài `agent-eval-v0.5` = v0.4 + **4 bài mới**, tất cả `surface: web`, `long_input: true`, dài 10 001–30 000
      ký tự, nội dung hư cấu, tiếng Việt. Không sửa 48 bài cũ.
    - Vị trí đáp án (đo bằng `pastes._chunks` và `SLIP_EDGE_CHARS` trên main, ghi vào `note` chỉ số đoạn chứa đáp án):
      - (a) chỉ nằm ở phần giữa, một đoạn;
      - (b) ở phần giữa nhưng xa đầu (đoạn thứ 5 trở đi), để xem agent chọn `from_chunk` thế nào;
      - (c) nằm trong 600 ký tự cuối: không cần đọc;
      - (d) cần ghép hai đoạn giữa không liền nhau.
    - Mỗi bài có đoạn gây nhiễu như doc-39 (ngày, tên người khác). `expect` theo mẫu doc-39: `tools_forbidden`
      `search_history`, `system_status`; `must_mention` cho đáp án. **Không** cấm `search_documents`.
    - Nâng `dataset.json` lên `agent-eval-v0.5`, thêm mục v0.5 vào README của bộ bài, sửa test bộ bài nếu cần.
      Bộ chấm giữ v0.4, trừ khi runner bắt buộc đổi; nếu đổi thì nói lý do.
    - **Không mở nhánh `wip/20-paste-slip-b`, không hỏi ai lời phiếu mới.** Được đọc `pastes.py` trên main (phiếu cũ).
    - Không chạy `agent_eval` (luật giữ im). Test không model: chạy với bộ biến giữ im và bỏ `POSTGRES_TEST_URL`.
  - **Nhân viên 1 — lời phiếu, nhánh `wip/20-paste-slip-b` cắt từ main `60532ed`.**
    - Chỉ sửa `slip()` trong `backend/app/services/pastes.py` và test trong `backend/tests/test_agent_pastes.py`.
    - Mục tiêu:
      - không để model tưởng đoạn dán nằm trong kho tài liệu (phiếu cũ viết "tài liệu tạm", và doc-39 trả lời "Tôi đã
        tìm kiếm trong văn bản");
      - nói rõ `search_documents` không thấy đoạn dán;
      - dặn đọc bằng `read_document` trước khi trả lời hay hỏi lại, khi câu hỏi cần phần chưa thấy.
    - Không đổi `AGENT_GUIDE`, mô tả công cụ (`tools_sha256` phải còn `153209…a75e500`), `PASTE_THRESHOLD`,
      `SLIP_EDGE_CHARS`, `PASTE_MAX`, `paste_id`. Phiếu chỉ xuất hiện ở tin dài hơn 10 000 ký tự: thêm test giữ điều đó.
    - **Không mở nhánh `wip/20-paste-tasks`, không đọc bài đoạn dán mới.** Bằng chứng duy nhất được dùng là doc-39 và
      báo cáo A2.
    - Không chạy `agent_eval` (luật giữ im).
  - **fable**: duyệt hai nhánh theo giao thức tệp; không chuyển lời phiếu mới cho Nhân viên 3.
  - **opus**: khi cả hai nhánh có GỘP ĐƯỢC, gộp bài đoạn dán vào main trước, viết đăng ký trước (luật, dự đoán) **trước
    khi chạy**, nhờ fable duyệt bản đăng ký, rồi đo trên 5 bài đoạn dán (doc-39 + 4 bài mới): main (phiếu cũ) và
    `wip/20-paste-slip-b` rebase lên main (phiếu mới), mỗi bên 2 lần lạnh, `--tasks`. 48 bài cũ không cần chạy lại:
    phiếu chỉ thay tin dài, và ba băm trong manifest phải bằng nhau.
- 28/10 10:50 (Nhân viên 3) — **#3-B, bài đoạn dán: xong trên `wip/20-paste-tasks`** (cắt từ main `ad09916`). Không mở
  `wip/20-paste-slip-b`, không chạy `agent_eval`.
  - Bộ bài `agent-eval-v0.5` = v0.4 + doc-40..43; 48 bài cũ không đổi byte nào; bộ chấm giữ v0.4. Bảng vị trí và giới
    hạn ở README của bộ bài, mục v0.5.
  - Vị trí (đo bằng `pastes._chunks` và `SLIP_EDGE_CHARS` ở `ad09916`): (a) doc-40 đoạn 3/8; (b) doc-41 đoạn 6/15, đọc
    lần lượt từ 0 thì tới lượt công cụ thứ ba mới thấy; (c) doc-42 trong 600 ký tự cuối; (d) doc-43 đoạn 1 và 5/10.
    Dài 10 474–21 342 ký tự.
  - Test mới `test_paste_answers_lie_where_the_notes_say` tính lại vị trí mỗi lần chạy; kiểm ngược: trượt khi sai chỉ
    số, khi mép phiếu 2 000 ký tự, khi chunk 300 token. Thêm 8 câu đúng/sai vào bảng tiêu chí, và một test chạy qua
    runner (`839f3c7`): model thấy phiếu của doc-41, đọc đoạn 6, trả lời đạt. Trước đó runner chưa từng đọc đoạn dán.
  - Tự chọn, ticket không nói: câu hỏi của (a), (d) đặt ở đầu đoạn dán (doc-39, (b), (c) ở cuối), vì phiếu cho thấy cả
    hai mép; (b) ở đoạn 6 chứ không từ đoạn 9 trở đi, để bài làm được mà không phải đoán.
  - Không thêm vào `expect` ngoài mẫu doc-39. Có thể thêm nếu điều phối muốn: `must_not_mention` cho gây nhiễu thấy
    trong phiếu, `max_tool_calls: 0` cho (c) (đối chứng đọc thừa, như doc-38).
- 28/10 15:20 (opus) — **#3-B đo xong: trượt luật ở điều 4, không đề xuất gộp.** Báo cáo:
  `data/evaluation/results/kept/agent-eval-v0.5-paste-slip-b/REPORT.md`. Trước `8bb58e1`, sau `c54e3eb` (`int/20-3b`,
  chưa vào main), 2 lần lạnh mỗi phía, r1 = r2 từng chữ; điều kiện so đúng.
  - Phiếu mới làm model mở đoạn dán 5/5 (cũ 2/5), đọc tiếp đúng ở bài xa 2/3 (cũ 0/3). Đủ ý: sau 4/5 (39, 40, 41, 42),
    trước 1/5 (42).
  - Điểm vẫn 1/5 mỗi bên: doc-40, 41, 42 sau chỉ trượt `args_valid`, vì model xin `n` = số đoạn phiếu nêu (8, 15, 10…)
    thay cho `n=3`; công cụ tự cắt về 3 nên model vẫn nhận đúng. doc-42 đang đạt thành trượt chính vì thế (đọc thừa 3
    lần, câu trả lời vẫn đủ). doc-43 đọc một lần, thiếu ngày ở đoạn 5, nói "văn bản không nêu".
  - Ba dự đoán sai: doc-39 phía trước khác #3 từ ký tự 525 (cùng lệnh, cùng token; nghi thứ tự chạy, chưa kiểm);
    doc-40, 41 mở cả với phiếu cũ; doc-42 phía sau có mở.
  - Cách cho chủ dự án (chưa làm gì):
    - A. Dừng #3-B, giữ phiếu cũ.
    - B. #3-C: sửa phiếu thêm (nói trần 3 đoạn mỗi lần, bỏ hoặc đổi câu "Văn bản có N đoạn", đã thấy đủ thì trả lời
      luôn), đăng ký lại, đo lại 5 bài. Bài đã bị nhìn thấy nên nên có thêm bài mới chưa ai xem.
    - C. Gộp dù trượt luật (chủ dự án ghi đè luật).
    - D. Bộ chấm mới: `n` vượt trần thành ghi nhận, không chặn. Mất so sánh với mọi dòng v0.4.
    - E. Công cụ báo cho model khi `n` bị cắt. Sửa được lời "đã đọc toàn bộ 15 đoạn" (doc-41 phía trước), không ngăn
      lời xin; đổi kết quả công cụ của doc-33 nên phải đo đủ 52 bài.
- 28/10 15:40 (opus) — **Chủ dự án chọn B** (nguyên văn): "Chọn B: sửa phiếu thêm (nói trần 3 đoạn mỗi lần, bỏ câu số
  đoạn, đã thấy đủ thì trả lời luôn), có thêm bài mới chưa ai xem, đăng ký lại rồi đo lại." Làm như #3-B, hai người không
  thấy việc của nhau. Không ai sửa tệp ticket này ngoài opus (lần trước hai nhánh cùng sửa dòng Status nên xung đột);
  báo xong bằng một tin ngắn cho opus.
  - **Nhân viên của Ún 1 — lời phiếu #3-C**, nhánh `wip/20-paste-slip-c` cắt từ `int/20-3b` (`c54e3eb`, đã có phiếu
    #3-B), worktree `local-ai-core-wt/20-paste-slip-c`.
    - Chỉ sửa `slip()` trong `backend/app/services/pastes.py` và test trong `backend/tests/test_agent_pastes.py`.
    - Ba thay đổi chủ dự án nêu: (1) nói rõ mỗi lần `read_document` đọc tối đa 3 đoạn (`n` từ 1 đến 3); (2) bỏ câu nêu
      tổng số đoạn ("Văn bản có N đoạn…"); (3) nếu phần đầu và cuối đã thấy đủ để trả lời thì trả lời luôn, không đọc.
    - Bằng chứng: `kept/agent-eval-v0.5-paste-slip-b/REPORT.md`. Ở 4/5 bài model xin `n` đúng bằng số đoạn phiếu nêu;
      doc-42 đọc 3 lần dù đáp án đã nằm trong phần cuối phiếu cho thấy.
    - Giữ những gì #3-B làm được: không gọi đoạn dán là tài liệu, nói `search_documents` không thấy nó, cho lệnh
      `read_document` cụ thể từ đoạn 0, đọc tiếp bằng `next_from_chunk` tới khi null.
    - Không đổi `AGENT_GUIDE`, mô tả công cụ (`tools_sha256` phải còn `153209…a75e500`), `read_document`, `read_paste`,
      `PASTE_THRESHOLD`, `SLIP_EDGE_CHARS`, `PASTE_MAX`, `paste_id`. Test: phiếu không còn số đoạn, có nói trần 3, tin
      ≤ 10 000 ký tự đi qua y nguyên.
    - **Không mở nhánh `wip/20-paste-tasks-c`, không đọc bài mới.** Bài doc-39..43 đã công khai, đọc được.
    - Không chạy `agent_eval`; test với luật giữ im (`env -u POSTGRES_TEST_URL -u REDIS_TEST_URL`,
      `OLLAMA_BASE_URL=http://127.0.0.1:9`, `MODEL_STARTUP_PROBES=false`, `CUDA_VISIBLE_DEVICES=-1`).
  - **Nhân viên của Ún 3 — bài mới**, nhánh `wip/20-paste-tasks-c` cắt từ main `58b9ef9`, worktree
    `local-ai-core-wt/20-paste-tasks-c`.
    - Bộ bài `agent-eval-v0.6` = v0.5 + 4 bài đoạn dán doc-44..47; 52 bài cũ không đổi byte nào; bộ chấm giữ v0.4.
    - Bốn kiểu, chủ đề và cách hỏi khác doc-39..43, có gây nhiễu trong phần phiếu cho thấy:
      - (e) đáp án ở một đoạn giữa (đoạn 3–5), cần đọc tiếp ít nhất một lần;
      - (f) đáp án nằm trọn trong 600 ký tự **đầu** mà phiếu cho thấy, có `max_tool_calls: 0`: đo trực tiếp ý "đã thấy
        đủ thì trả lời luôn" (doc-42 có đáp án ở mép cuối và không có trần này);
      - (g) đáp án ở đoạn xa, vừa tới trong 3 lượt đọc lần lượt từ đoạn 0, mỗi lượt 3 đoạn (như doc-41);
      - (h) hai mảnh đáp án ở hai đoạn mà một lần đọc 3 đoạn không phủ hết (như doc-43).
    - Vị trí tính bằng `pastes._chunks` + `SLIP_EDGE_CHARS`, test tính lại mỗi lần chạy (mở rộng
      `test_paste_answers_lie_where_the_notes_say`). Dài 10 001–30 000 ký tự. Ở (e)(g)(h) không mẫu `must_mention` nào
      khớp phần đầu hay cuối mà phiếu cho thấy.
    - Ghi lại truy xuất như doc-39..43 để `--tasks` chạy được. README bộ bài thêm mục v0.6.
    - **Không mở nhánh `wip/20-paste-slip-c`, không đọc lời phiếu mới.** Không chạy `agent_eval`; test với luật giữ im.
  - **fable**: duyệt hai nhánh theo giao thức tệp; không chuyển lời phiếu cho NV3, không chuyển bài mới cho NV1. Sau đó
    duyệt bản đăng ký của opus.
  - **opus**: khi cả hai nhánh có GỘP ĐƯỢC, gộp bài mới vào main trước, viết đăng ký trước (luật, dự đoán) trước khi chạy,
    nhờ fable duyệt, rồi đo 9 bài đoạn dán (doc-39..47): main (phiếu cũ) so với main + phiếu #3-C, mỗi bên 2 lần lạnh.
    Luật sẽ đòi kết quả đứng được trên riêng bốn bài mới, không chỉ trên năm bài đã thấy.
- 28/10 19:10 (opus) — **#3-C đo xong: trượt luật ở điều 3, không đề xuất gộp.** Báo cáo:
  `data/evaluation/results/kept/agent-eval-v0.6-paste-slip-c/REPORT.md`. Đăng ký trước `9f2a23a`, fable duyệt. Trước
  `01daa42` (main), sau `ed210e4` (`int/20-3c`, chưa vào main), 2 lần lạnh mỗi phía, r1 = r2 từng chữ; điều kiện so đúng.
  - Điểm 9 bài: trước 2/9, sau 6/9; không bài nào đạt → trượt. Bài đã thấy từ trượt thành đạt 3/4 (39, 41, 43). Bài
    **mới** cần phần giữa từ trượt thành đạt **1/3** (doc-46, và ở phía trước nó đã đủ ý, chỉ trượt vì `n`).
  - `n` sạch: lần đọc đầu 5/5 ≤ 3, các lần sau 5/5 ≤ 3. Đọc tiếp đúng 3/6 (cũ 1/6). doc-42, doc-45 không đọc lần nào.
  - Mở đoạn dán trên 7 bài cần phần giữa: cũ 4/7, mới 5/7, nhưng doc-47 mở chỉ sau khi bị kiểm con số bác → của phiếu 4/7.
  - Ba bài trượt phía sau, ba cách: doc-40 hiểu sai phiếu (gọi `search_history` bị cấm, nói không dùng được
    `read_document` cho đoạn dán, nhờ người dùng dán phần giữa; ở #3-B nó có mở); doc-44 biết phần giữa chưa thấy mà vẫn
    nhờ người dùng dán lại; doc-47 đọc một lần, thấy một mảnh, nói "đã đọc… đầy đủ".
  - Dự đoán sai một: doc-44, 46, 47 mở cả ba. Dự đoán 1 đúng: phía trước doc-39..43 trùng từng chữ #3-B, ủng hộ giải
    thích "thứ tự chạy" cho lệch doc-39 lần trước.
  - Cách cho chủ dự án (chưa làm gì):
    - A. Dừng, giữ phiếu cũ trên main; `int/20-3c` giữ làm nhánh.
    - B. Gộp #3-C dù trượt điều 3 (chủ dự án ghi đè luật).
    - C. Sửa lời phiếu lần ba, thêm bài mới lần nữa (doc-44..47 đã bị nhìn thấy), đăng ký lại.
    - D. Harness nhắc một lần: câu trả lời nhờ người dùng dán phần giữa, hoặc nói đã đọc hết trong khi đoạn dán còn
      đoạn chưa đọc, thì trả lại model kèm lời nhắc đọc, như bước kiểm con số đã có. Cần bài mới để đo.
    - E. Harness tự tìm trong đoạn dán những đoạn hợp câu hỏi, đưa vào phiếu cùng phần đầu, cuối. Thay đổi lớn nhất,
      tốn nhúng mỗi lần dán.
  - Fable kiểm lại báo cáo: ĐÚNG SỐ (`reviews/report-20-3c-67c43e0.md`). Fable thêm một giả thuyết cho doc-40, chưa kiểm:
    mô tả công cụ `read_document` nói document_id lấy "trong kết quả search_documents" (`agent_service.py:88`, `:92`),
    còn phiếu nói search_documents không tìm thấy đoạn dán; model nối hai câu thành "không dùng được read_document". Hai
    câu đó có thật trong code; quan hệ nhân quả chưa đo. Thêm một cách:
    - F. Sửa mô tả `read_document` để nhận cả id `paste_…` trong phiếu. Đổi `tools_sha256`, nên phải đo đủ 56 bài; cũng
      cần bài mới chưa ai xem.
- 28/10 21:25 (opus) — **Chủ dự án duyệt gói #3-D** (qua fable; nguyên văn ở `paste-directions-2026-10-28.md`, mục
  "Quyết định chủ dự án"): "Duyệt gói: đo trên int/20-3c, không gộp #3-C trước; bước 1 nhắc lại một lần với lượt thử lại
  riêng; 3' cho search_documents tìm trong đoạn dán; một bản đăng ký ba nhánh; NV3 viết bài mới mù, có ít nhất một bài đáp
  án sau đoạn 8. Opus điều phối, fable duyệt." Ba việc song song, không ai thấy việc của người khác. Chỉ opus sửa tệp
  ticket này; xong thì báo opus bằng một tin ngắn.
  - **Nhân viên của Ún 1 — bước 1, nhắc lại khi đoạn dán còn đoạn chưa đọc**, nhánh `wip/20-paste-nudge` cắt từ
    `int/20-3c` (`ed210e4`), worktree `local-ai-core-wt/20-paste-nudge`.
    - Chỗ sửa: `AgentService.run`, ở nhánh model tự trả lời (`if not calls`), sau bước kiểm con số #2 khi #2 không thử
      lại. Không ở nhánh câu trả lời ép (hết lượt công cụ hay hết giờ, `agent_service.py:413–449`).
    - Bắn khi đủ cả hai: (a) đoạn dán của lượt còn đoạn chưa đọc, đếm từ các đoạn `read_document` thật sự trả về trong
      lượt (đoạn trích của `search_documents` không tính); (b) câu trả lời khớp mẫu chữ: nhờ người dùng dán, gửi, tải
      lên hay cung cấp văn bản hoặc một phần của nó; hoặc nói đã đọc hết, toàn bộ, đầy đủ văn bản.
    - Lượt thử lại **riêng**: cờ riêng, không dùng `retried` của #2 (bằng chứng: doc-47 phía sau #3-C, #2 tiêu lượt
      thử lại ở vòng 1 rồi vòng 3 nói "đã đọc đầy đủ"). Cho thêm đúng một vòng, chỉ khi còn ≥ `final_reserve_seconds`.
      Một lượt có thể có cả hai lần thử lại (#2 rồi bước 1), mỗi loại tối đa một.
    - Lời nhắc (tin system): đoạn dán đã nằm trong tin nhắn, đừng nhờ người dùng dán lại; tự đọc bằng một lệnh
      `read_document` cụ thể (document_id của đoạn dán, `from_chunk` = đoạn chưa đọc nhỏ nhất, `n=3`). Không nêu tổng số
      đoạn hay số đoạn còn lại (#3-B: nêu số thì model xin `n` bằng số đó).
    - Vết: một bước riêng như `answer_check`, không giữ chữ của câu bị trả lại (kind, mã lỗi, `arguments_shape` chỉ có số
      đếm và loại mẫu). Nhãn tiến độ riêng. Kiểm `agent_eval_scorecard.py` vẫn đếm đúng khi có kind mới.
    - Mẫu chữ viết được từ câu trả lời doc-40, doc-44, doc-47 trong `kept/agent-eval-v0.6-paste-slip-c/` (bài đã công
      khai); vì vậy ba bài đó thành bài đã thấy với bước này.
    - Không đổi `AGENT_GUIDE`, mô tả công cụ (`tools_sha256` phải còn `153209…a75e500`), `slip()`, bước kiểm #2, bộ
      chấm, bộ bài. Không đụng `_search_documents` (NV2 sửa ở đó).
    - Test: nhờ dán + còn đoạn chưa đọc → thêm một vòng có lời nhắc; nói đã đọc hết khi mọi đoạn đã đọc → không bắn;
      #2 thử lại rồi bước 1 trong cùng lượt; không có đoạn dán → các bước giống hệt trước; nhánh ép không bắn; thiếu
      giờ không bắn; lời nhắc không chứa tổng số đoạn.
  - **Nhân viên của Ún 2 — 3', `search_documents` tìm trong đoạn dán**, nhánh `wip/20-paste-search` cắt từ `int/20-3c`
    (`ed210e4`), worktree `local-ai-core-wt/20-paste-search`.
    - `_search_documents`: nếu lượt có đoạn dán, xếp hạng các đoạn của nó (`pastes._chunks`) theo truy vấn bằng BM25 viết
      thuần Python, không gọi model, không GPU. Gộp **trước** khi gọi backend: kết quả ở đoạn dán đứng đầu, rồi tới kết
      quả thư viện; câu "không tìm thấy" chỉ khi cả hai rỗng. `ReplayRetrieval` của eval không đổi.
    - Mỗi kết quả ở đoạn dán mang `document_id` = paste_id, `chunk_index`, đoạn trích như kết quả thư viện, và một câu
      "đọc trọn đoạn này bằng read_document(document_id=…, from_chunk=i)" (chữ trong kết quả công cụ, không đổi schema).
    - `slip()`: thay câu "search_documents không tìm thấy nó" bằng câu nói `search_documents` tìm được trong đoạn dán và
      trả `chunk_index` để đọc thẳng đoạn đó. Giữ phần còn lại của phiếu #3-C (trần 3 đoạn, đủ thì trả lời luôn, lệnh
      đọc từ đoạn 0). Không nêu số đoạn.
    - Không đổi `AGENT_GUIDE`, mô tả công cụ (`tools_sha256` còn `153209…a75e500`), `read_document`, `read_paste`,
      `PASTE_*`, `paste_id`. Không đụng `AgentService.run` (NV1 sửa ở đó).
    - Test: đoạn chứa từ của truy vấn đứng đầu; kết quả ở đoạn dán có paste_id + chunk_index và mở được bằng
      `read_document`; không có đoạn dán thì kết quả `search_documents` giống hệt trước; phiếu không có số đoạn.
  - NV1 và NV2: **không mở `wip/20-paste-tasks-d`, không đọc bài mới**, không mở nhánh của người kia. Không chạy
    `agent_eval`; test với luật giữ im (`env -u POSTGRES_TEST_URL -u REDIS_TEST_URL`, `OLLAMA_BASE_URL=http://127.0.0.1:9`,
    `MODEL_STARTUP_PROBES=false`, `CUDA_VISIBLE_DEVICES=-1`). Không push.
  - **Nhân viên của Ún 3 — bài mới mù**, nhánh `wip/20-paste-tasks-d` cắt từ main ngay sau commit này, worktree
    `local-ai-core-wt/20-paste-tasks-d`.
    - Bộ `agent-eval-v0.7` = v0.6 + 6 bài đoạn dán doc-48..53; 56 bài cũ không đổi byte nào; bộ chấm giữ v0.4.
    - Sáu kiểu; chủ đề và cách hỏi khác doc-39..47; có số gây nhiễu ở đoạn khác:
      - (i) đáp án ở một đoạn giữa (đoạn 3–6);
      - (j) đáp án ở đoạn ≥ 10 của đoạn dán ≥ 14 đoạn: đọc lần lượt từ đoạn 0, mỗi lần 3, không tới được (mọi lần thử
        lại đều tốn một vòng trả lời, nên lượt nào cũng đọc được nhiều nhất 3 lần);
      - (k) như (j), chủ đề khác, đoạn dán 30 000–60 000 ký tự;
      - (l) hai mảnh đáp án, một ở đoạn 0–2, một ở đoạn ≥ 5;
      - (m) đáp án nằm trọn trong mép đầu hoặc mép cuối mà phiếu cho thấy, `max_tool_calls: 0` (bài chứng: không đọc,
        không tìm khi không cần);
      - (n) đáp án ở đoạn 4–8, câu hỏi diễn đạt khác hẳn chữ trong đoạn đó (ít từ chung); có một đoạn khác nhiều từ chung
        với câu hỏi nhưng không chứa đáp án.
    - Vị trí tính bằng `pastes._chunks` + `SLIP_EDGE_CHARS`, test tính lại mỗi lần chạy (mở rộng
      `test_paste_answers_lie_where_the_notes_say`). Dài 10 001–60 000 ký tự. Trừ (m), không mẫu `must_mention` nào khớp
      mép đầu hay mép cuối.
    - Ghi lại truy xuất như doc-39..47 để `--tasks` chạy được. README bộ bài thêm mục v0.7.
    - **Không mở `wip/20-paste-nudge`, `wip/20-paste-search`, không đọc `paste-directions-2026-10-28.md`.** Không chạy
      `agent_eval`; test với luật giữ im. Không push.
  - **fable**: duyệt ba nhánh theo giao thức tệp; không chuyển code cho NV3, không chuyển bài mới cho NV1, NV2. Sau đó
    duyệt bản đăng ký.
  - **opus**: ba nhánh GỘP ĐƯỢC thì gộp bài mới vào main, dựng ba commit đo: nền = `int/20-3c` gộp main có bài mới;
    nền + bước 1; nền + bước 1 + 3'. Đăng ký trước trên 15 bài đoạn dán (doc-39..53), cùng `--tasks` cùng thứ tự, 2 lần
    lạnh mỗi nhánh, cộng một lần đủ 62 bài ở nền và ở nhánh đủ để chứng minh 47 bài không dán trùng nguyên. Luật phải
    đứng được trên riêng 6 bài mới và nói trước mục chấm nào quyết. Fable duyệt rồi mới chạy.
- 28/10 22:45 (opus) — **#3-D dừng giữa lần đo: câu trả lời của một bài phụ thuộc bài chạy ngay trước nó.** Đã chạy
  theo đăng ký (`347194a`, fable GỘP ĐƯỢC ở `73574da`): nền `73bb621` r1, r2 (9/15, r1 = r2); +1 `2866758` r1, r2 (10/15,
  r1 = r2); nền đủ 62 bài (50/62). +1+3' (`57c3961`) chưa chạy: chờ phiếu (b) và quyết định dưới. Lần chạy ở
  `kept/agent-eval-v0.7-paste-nudge-search/`; ba lần chẩn đoán không đăng ký ở `diagnostics/`.
  - Bằng chứng:
    - doc-41 chạy riêng: nền và +1 trùng từng chữ; nhưng khác doc-41 trong chuỗi 15 bài ở cả hai nhánh, và khác lần đủ 62 bài.
    - doc-51 chạy riêng ở nền: đạt, không lỗi. Trong chuỗi 15 bài ở nền nó hỏng cả hai lần.
    - Nền đủ 62 bài so với nền 15 bài: chỉ 3/15 câu trả lời đoạn dán trùng.
    - +1 so với nền: doc-39 (chạy trước mọi lần nhắc) trùng; doc-41, 42, 43, 46, 53 khác chữ dù lời nhắc không bật và chuỗi
      công cụ y hệt.
  - Hệ quả: "t0 + seed lặp lại được" chỉ đúng cho cùng một chuỗi bài. Từ bài đầu tiên hai nhánh khác nhau, các bài sau lệch vì
    trạng thái chứ không vì code. Lệch doc-39 ở #3-B là cùng hiệu ứng. Cơ chế nghi: Ollama chạy một slot llama-server và dùng
    lại phần đầu vào trùng với yêu cầu trước; chưa kiểm.
  - Điều gì còn đứng được: B4 và C4 (thay đổi phải thật sự bật ở cả hai lần) vẫn quy đúng nguyên nhân; doc-51 trượt → đạt ở
    +1 mà không có lời nhắc, nên không được tính. B2 và C2 (đạt → trượt) không còn tách được hại thật khỏi lệch thứ tự. Điều
    kiện 47 bài: 46 bài đứng trước doc-39 vẫn kiểm sạch; hist-11 (vị trí 47, ngay sau doc-39) có thể lệch vì thứ tự.
  - Dấu vết thật ở +1, đứng được dù có lệch:
    - doc-40: lời nhắc bật, đọc đoạn 0–5, câu trả lời đủ ý; vẫn trượt `tools_forbidden` vì vòng đầu đã gọi `search_history`.
    - doc-44: nhắc một lần, đọc 0–2, trả lời bằng con số ở mép; trượt.
    - doc-47: viết "cần xem lại văn bản", kiểu chữ mẫu không bắt; không đọc; trượt.
    - doc-49: hết lượt ở đoạn 8, câu trả lời ép nói "đã đọc toàn bộ văn bản (15 đoạn)"; lời nhắc không chạy ở nhánh ép.
    - doc-50: hết lượt ở đoạn 8, đoán theo "thông lệ chung".
  - Lỗi harness ngoài phạm vi: model viết lệnh công cụ hỏng, Ollama trả 500 "tool call parsing failed" ba lần,
    `ollama_client.py:129` báo "Cannot connect to Ollama", mất cả lượt. Việc riêng, không sửa trong #3-D.
  - Cách cho chủ dự án (chưa làm gì):
    1. Chạy +1+3' như đã đăng ký (khi có (b)); quyết B và C chỉ bằng điều quy nguyên nhân (B4, C4); phần còn lại báo kèm cảnh
       báo lệch thứ tự. Rẻ nhất (~8 phút GPU); kết luận hẹp hơn bản đăng ký hứa.
    2. Cô lập từng bài: runner gỡ model giữa các bài. Sửa riêng mục Quy trình của bản đăng ký (luật, dự đoán giữ nguyên), fable
       duyệt lại, chạy lại cả ba nhánh. Cần sửa runner nhỏ; GPU khoảng gấp đôi (~30 phút).
    3. Không sửa code: chạy từng bài riêng như lần chẩn đoán (15 bài × 3 nhánh × 2 lần, ~40 phút). Sửa đăng ký chỉ ở thủ tục.
    - Ý kiến opus: cách 2, vì lệch thứ tự đè lên mọi phép đo Agent Eval so hai nhánh, không riêng #3-D; sửa runner một lần
      thì các lần đo sau dùng được. Phiếu (b) gộp vào lần đăng ký lại.
- 28/10 23:05 (opus) — **Chủ dự án chọn cách 2** (qua fable, nguyên văn): "Chọn cách 2: runner gỡ model khỏi Ollama trước
  mỗi bài để mỗi bài chạy như chạy riêng; sửa riêng mục Quy trình của bản đăng ký, fable duyệt lại, chạy lại cả ba nhánh
  #3-D. Ghi rõ mọi số đo cũ là số theo chuỗi." Phiếu (b) của 3': "vậy bỏ". NV2 đã thu hẹp phiếu ở `92f5796` (lệnh cụ thể duy
  nhất vẫn là đọc từ đoạn 0, thêm một câu nói search_documents tìm được trong văn bản dán), chờ fable.
  - **Nhân viên của Ún 3 — runner cô lập từng bài**, nhánh `wip/20-eval-isolate` cắt từ main `7907260`, worktree
    `local-ai-core-wt/20-eval-isolate`.
    - `backend/scripts/agent_eval.py`: cờ `--unload-between-tasks`. Trước **mỗi** bài, kể cả bài đầu: gỡ model vai trò
      general khỏi Ollama (`/api/generate` với `keep_alive: 0`, như `run_cold.sh`), chờ `/api/ps` không còn model đó, rồi
      nạp lại (`/api/generate` không prompt) và đo thời gian nạp, để bài chạy trên model vừa nạp, chưa có gì trong bộ nhớ đệm.
    - Manifest luôn có `unload_between_tasks` (true/false). Mỗi dòng `task_results` có `reload_ms` (null khi tắt cờ).
    - Không đổi gì model thấy: `tools_sha256`, `agent_guide_sha256`, `system_prompt_sha256`, bộ bài, bộ chấm giữ nguyên.
    - Mặc định tắt, để lần chạy khác không đổi; so hai nhánh từ nay dùng cờ này.
    - Test với Ollama giả: thứ tự gỡ → chờ → nạp → chạy bài, cho từng bài kể cả bài đầu; manifest có trường mới; tắt cờ thì
      không gọi gỡ; `reload_ms` có mặt khi bật.
    - Không mở `wip/20-paste-nudge`, `wip/20-paste-search`. Không chạy `agent_eval` thật; test với luật giữ im. Không push.
  - **fable**: duyệt nhánh runner, `92f5796`, và phần sửa bản đăng ký.
  - **opus**: sửa mục Quy trình và các dự đoán bị ảnh hưởng của bản đăng ký #3-D, đăng ký lại phần +1+3' theo phiếu mới (C3,
    C4 giữ); thêm ghi chú "số theo chuỗi" ở `kept/README.md`; khi mọi thứ GỘP ĐƯỢC thì dựng lại ba commit đo trên main có
    runner mới và chạy lại cả ba nhánh với cờ. Các lần chạy 22:16–22:37 giữ làm bằng chứng "theo chuỗi", không dùng cho luật.
- 28/10 23:55 (opus) — **#3-D đo lại xong dưới cô lập: cả hai đề xuất trượt luật, không gộp gì.** Báo cáo:
  `kept/agent-eval-v0.7-paste-nudge-search/REPORT.md`; đăng ký bản sửa `28df7c7`, fable duyệt `b103ef3`. Nền `94e321f`,
  +1 `04b89a2`, +1+3' `2839b52` (`int/20-3d-iso`), 2 lần chạy cô lập mỗi nhánh, r1 = r2 cả ba; 47 bài không dán giống hệt
  giữa hai lần đủ bộ; hai lớp kiểm cô lập đều qua.
  - 15 bài: nền 10, +1 10, +1+3' 9. Bài mới: cả ba nhánh 4/6; doc-49, doc-50 (quá trần) trượt ở mọi nhánh.
  - B trượt B3: doc-48, 51, 53 đạt sẵn ở nền (k = 0). Lời nhắc chỉ bật ở doc-40: model đọc tới đáp án, nhưng bài vẫn trượt
    `tools_forbidden`, vì vòng đầu đã gọi `search_history`.
  - C trượt C2 và C3. doc-43 tụt: model tìm, đọc một cửa sổ, sót hạn nộp ở đoạn 5. doc-49, doc-50 không gọi tìm. Model gọi
    tìm ở 3/12 bài cần phần giữa; doc-41 đúng nhờ tìm, chỉ đọc một lần.
  - Ngoài luật:
    - doc-51 ở +1+3' đạt nhờ đoán "3-7 ngày" (mẫu `7\s*ngày` khớp).
    - doc-44 ở +1+3' mất lượt cả ba lần vì lệnh công cụ hỏng, nên đây là hành vi thật, không do thứ tự chạy.
    - doc-50 ở +1+3' nói ngược phiếu và nhờ người dùng copy lại văn bản.
  - Mốc mới: nền đủ 62 bài cô lập 50/62 (v0.7, `94e321f`). Mọi số trước là số theo chuỗi.
  - Cách cho chủ dự án (chưa làm gì):
    - A. Dừng nhánh đoạn dán ở đây, main giữ phiếu #3; giữ `int/20-3d-iso` làm nhánh.
    - B. Sửa lỗi lệnh công cụ hỏng: bắt Ollama 500 "tool call parsing failed", thử lại một lần không công cụ hoặc kèm lời
      nhắc, và báo đúng tên lỗi. Có ca tái hiện chắc (doc-44 ở +1+3', doc-51 theo chuỗi), đo được dưới cô lập.
    - C. Nới trần lượt công cụ khi lượt có đoạn dán (3 → 5 vòng, đọc tới đoạn 14). Nhắm thẳng doc-49, doc-50; tốn thêm
      độ trễ và token, có thể đổi bài đang đạt.
    - D. Cho phiếu lái sang tìm (bản (b) chủ dự án đã bỏ). Bằng chứng mới: khi model tìm thì 2/3 lần ra đúng đoạn, nhưng
      doc-43 tụt vì đọc một cửa sổ; hai bài quá trần không ai tìm.
    - E. Đo phiếu #3-C so với phiếu cũ dưới cô lập (chưa từng đo trên bài mới), rồi mới quyết gộp #3-C.
    - F. Sửa bộ chia đoạn bỏ dòng tiêu đề đánh số (việc riêng).
    - Ý kiến opus: B trước. Đó là lỗi làm người dùng mất câu trả lời, có ca tái hiện, và độc lập với chuyện đoạn dán. Sau đó C,
      vì trần 9 đoạn là nguyên nhân duy nhất còn lại của hai bài trượt chung.
- 29/10 08:55 (opus) — **Đợt đo phân xử N1 / C7.** Chủ dự án duyệt (qua fable, 06:xx), nguyên văn: "Duyệt đợt đo phân xử
  theo tong-hop.md: NV1 viết N1 (~20 dòng) và C7, NV3 viết ≥ 4 bài mù dài, opus đăng ký trước, fable duyệt, chạy cô lập sau
  khi Quản lý trả GPU; dừng nếu GPU ≥ 85 °C hoặc hạn tuần ≥ 35 %." Tổng hợp của fable và bốn báo cáo:
  `research-2026-10-29/` (chép vào main cùng commit này). GPU về lúc 05:33.
  - **Nền chung `int/20-arb` `62e7ca0`** = `94e321f` (phiếu #3-C) + main `b100d56` (thêm ticket 27). Khác main chỉ ở
    `pastes.py` và test của nó. Lý do: N1 đổi prompt cả 15 bài dán, C7 thêm vòng công cụ. Thiếu ticket 27 thì một lệnh công cụ
    hỏng làm mất lượt và lẫn vào kết quả. Hệ quả: nền chạy lại trên commit mới. Dự đoán: 15 bài cũ giống hệt
    `v0.7-3d-iso-base-r1`, vì ticket 27 chưa từng bắn ở nền (r1 không có lỗi nào). Test agent/paste/eval giữ im: 272 qua,
    8 hỏng cũ ở `test_eval_stack_model_version.py` (thiếu `DATABASE_URL` trong worktree, như trước).
  - **NV1**: hai nhánh, đều cắt từ `int/20-arb` `62e7ca0`.
    - `wip/20-paste-inline` (N1), trong `pastes.take_pastes`. Tin cuối của người dùng là đoạn dán, và ước token cả prompt ≤
      hằng mới → giữ nguyên văn: không thành phiếu, không vào `pastes`, nên không có id cho `read_document` mở. Đoạn dán cũ trong
      lịch sử vẫn thành phiếu. Không đụng `PASTE_THRESHOLD`.
      - Ước = phần cố định (hướng dẫn, system, schema công cụ) + tổng ký tự mọi tin model sẽ thấy (đoạn dán cũ tính theo phiếu,
        tin cuối tính nguyên văn) / 3,3. Tỉ lệ 3,3 đo từ 186 câu (`c-noi-tran-doc.md`). Phần cố định lấy từ `tokens_in` vòng đầu
        của một bài không dán trong lần chạy đã giữ (≈ 1,3k); ghi nguồn trong chú thích.
      - Ngưỡng = `num_ctx` 16 384 − 4 096 dự trữ (câu trả lời, một lần thử #2, một vòng công cụ) = 12 288. Cách tính ghi trong
        chú thích; không chỉnh theo bài.
      - Test: dán 31 681 ký tự không lịch sử → nguyên văn; 40 000 → phiếu; đoạn dán cũ trong lịch sử → phiếu; lịch sử dài đẩy
        một đoạn dán 30 000 qua ngưỡng → phiếu; tin không dán → messages model thấy giữ nguyên (ghim); `tools_sha256` giữ
        `153209…a75e500`.
      - Manifest ghi hằng mới. Báo opus con số ước cho 31 681 và 40 000 ký tự.
    - `wip/20-paste-rounds` (C7): `rounds = max_steps + 4` khi lượt có đoạn dán. Hai lần +1 (ticket 27, #2) vẫn cộng thêm.
      Manifest ghi khoá mới. Test: có dán → 7, không dán → 3, lần thử lại vẫn +1, bài không chạm trần giữ nguyên từng byte.
    - Không mở nhánh bài của NV3. Không chạy `agent_eval`. Test theo luật giữ im. Không push. Xong nhắn fable + opus.
  - **NV3**: `wip/20-paste-tasks-e`, cắt từ main `b100d56`, v0.8, bài doc-54 trở đi.
    - ≥ 3 bài giữa: văn bản 25 000–29 000 ký tự (cả câu hỏi). Mọi mảnh đáp án nằm ở 40–60 % chiều dài, ở đoạn ≥ 10 (bộ chia
      thật), ngoài 600 ký tự hai mép, không lặp ở chỗ khác. Kiểu khác nhau: một mảnh, hai mảnh, có số mồi kiểu doc-53 (ít
      nhất một bài).
    - ≥ 1 bài dài: ≥ 42 000 ký tự, đáp án ở đoạn 12–18. Bảy lần đọc của C7 tới được; ba lần của nền thì không.
    - Mẫu chấm chặt, đáp án khó đoán; tránh mẫu khớp câu đoán khoảng (doc-51 "3-7 ngày"). Không sửa 15 bài cũ và bộ chấm của
      chúng.
    - Mở rộng `paste_check_d.py` để kiểm vị trí bằng bộ chia thật. Gửi opus bảng chỉ có siêu dữ liệu: id, độ dài, số đoạn,
      đoạn đáp án, % vị trí, kiểu, có mồi không. Fable duyệt nội dung.
    - Không mở nhánh của NV1. Không chạy `agent_eval`. Không push.
  - **fable**: duyệt hai nhánh NV1, nhánh bài, bản đăng ký, báo cáo, qua tệp như cũ.
  - **opus**: gộp bài vào main và `int/20-arb`; dựng commit nền / N1 / C7; viết bản đăng ký và `analyze.py` trước khi chạy.
    Chạy cô lập, mỗi nhánh một lần: nền (15 cũ + bài mới), N1, C7. Thêm một lần N1 thứ hai trên các bài giữa, vì N1 đưa
    prompt lên ~11k token mà r1 = r2 mới chứng minh tới ~6,5k. GPU ước ~25 phút. Dừng nếu GPU ≥ 85 °C hoặc hạn tuần ≥ 35 %.
  - Luật, đăng ký chi tiết sau: theo `tong-hop.md`, thêm nhánh "không kết luận" để mọi kết quả có chỗ. Bài giữa = mọi mảnh
    đáp án ở 40–60 % chiều dài, làm tròn hai chữ số: bài cũ doc-39, 40, 41, 44, 46, 50 cộng bài mới. Chặn cắt ngữ cảnh: vòng
    nào có `tokens_in` > 14 500 thì bài đó tính riêng. Đây là phép thử cơ chế, không phải cổng gộp; N1 lên main sẽ đứng trên
    phiếu #3, trừ khi #3-C cũng gộp.
