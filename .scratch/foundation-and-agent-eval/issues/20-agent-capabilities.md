# 20 — Khả năng cơ bản cho agent: đọc dài, kiểm câu trả lời, báo tiến độ

Status: đang làm — cách A (chủ dự án 28/10 00:20): v0.3 → #1 → #2 → #3 → #4; bỏ #5
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
