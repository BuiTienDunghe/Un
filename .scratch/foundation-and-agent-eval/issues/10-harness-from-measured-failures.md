# 10 — Nâng harness theo lỗi đo được (M4)

Status: đã giao — Nhân viên của Ún 3; phần GPU sau 09
Type: task
Blocked by: 07

Đọc lỗi trong baseline 07, rồi chỉ làm phần nào mà lỗi chỉ ra: registry công cụ có schema, ngân sách
token/thời gian, chuẩn hoá lỗi/thử lại, tracing. Chạy lại đúng bộ đo sau mỗi thay đổi. Báo cáo tách
lợi ích kiểm soát (registry, ngân sách) khỏi lợi ích chất lượng (chọn đúng công cụ, trả lời đúng).
Tiêu chí nghiệm thu theo `spec.md` Mốc 4.

## Comments
- 27/10 (từ Nhân viên 3, ticket 07): `search_documents` chỉ đưa cho model 400 ký tự đầu của mỗi
  đoạn. Ở corpus lab, 400 ký tự đầu của `backup_restore.md` đoạn 0–1 và `p3_progress.md` đoạn 0–2
  giống hệt nhau (cùng phần mở đầu), nên khi nhận các đoạn này model chỉ thấy phần mở đầu, nội dung
  riêng của từng đoạn không tới được. Ứng viên số một cho M4 nếu baseline 07 cho thấy nó làm mất
  điểm (07 sẽ đếm số bài bị ảnh hưởng).
- 27/10 (opus 5.5, chốt theo phân tích của Nhân viên 3 trên baseline 07): lỗi đo được, xếp theo số bài
  mất ở lần nóng t0 / t0.4: (1) không gọi `search_documents` 3/2; (2) chọn sai công cụ ở bài Discord
  1/2; (3) `search_history` cắt mất tin mới nhất ở 2 400 ký tự (hist-05 mất 8/18 tin; không đổi điểm
  vì bài còn trượt ở author_id, nhưng là mất dữ liệu thật); (4) phần đầu 400 ký tự trùng: 0 bài.
  Làm: Bước 0 v0.2 + mốc v0.2 trên harness hiện tại; Bước 1 3a (cắt theo phần tử, kiểm soát); Bước 2
  1a (lời dặn tra tài liệu, chất lượng) rồi 2b (gợi ý khi `search_documents` rỗng ở lượt có guild,
  kiểm soát), đo riêng từng cái, mỗi phía một lần khởi động bỏ đi. Không làm: 1c, 2c, lỗi 4; registry
  và ngân sách token/thời gian chưa có lỗi đo được nào đòi tới.
- 27/10 (Nhân viên 3) — Bước 0, bộ bài v0.2: doc-18, hist-05 ("tuần này" → bỏ), mẫu `no_access`;
  `GRADER_VERSION` lên `agent-eval-grader-v0.2`; dataset `agent-eval-v0.2`, sha256 `99b2e915…`.
  Từ v0.2, bộ bài trong repo là nguồn sự thật: script sinh dữ liệu ở scratchpad không còn dùng được,
  vì chạy lại sẽ xoá các đoạn đã ghi thật.
- 27/10 (Nhân viên 3) — Bước 1 (3a), commit riêng `2d6c247`. `_dump` bỏ trọn từng phần tử, không
  cắt giữa JSON, và ghi `{"omitted": N, "note": "đã bỏ N mục …"}`. Chế độ "tin mới nhất" bỏ tin cũ
  nhất trước; danh sách xếp hạng bỏ từ cuối. Thứ gì không chia được thành phần tử thì vẫn cắt theo
  ký tự như cũ. Chạy lại bằng đầu vào của baseline: hist-05 giữ 9 tin mới nhất (tới 20/10), có ghi
  "đã bỏ 9 mục cũ nhất". `top_k=5` trên 12 bài ghi thật: 0/12 JSON gãy (trước là 12/12). Test
  `tests/test_agent_tool_results.py` không cần stack. Chưa đo với model; việc đó nằm trong lần chạy
  GPU.
- 27/10 — Theo góp ý của fable cho REPORT v0.1: ghi thêm giả thuyết "embedding + OCR nằm cạnh
  trên GPU"; `analyze.py` tự tính tập đoạn trùng từ `retrieval.jsonl`. **Đính chính:** "400 ký tự đầu
  giống hệt" chỉ đúng với p3_progress 0–2. Ở backup_restore, đoạn 0 dài 388 ký tự và đoạn 1 chỉ thêm
  11 ký tự. Vì vậy định nghĩa là chung ≥ 350/399 ký tự đầu; với định nghĩa này, kết quả phân tích
  giống hệt bản đã commit.
- 27/10 — opus chốt: không đo riêng tác dụng của 3a. Báo cáo phải ghi đúng câu: **"mốc v0.2 = bộ bài
  v0.2 + 3a; tác dụng của 3a lên điểm chưa đo"**. Lý do thật: lợi ích của 3a đã được kiểm tất định,
  còn GPU tối nay dành cho 1a và 2b. Lý do mình nêu trước đó ("3a không đổi hành vi model") là sai:
  3a CÓ đổi những gì model thấy ở 6–7 lượt mỗi lần chạy (JSON không còn gãy, giữ tin mới nhất).
- 27/10 — Cụm 3a hoàn chỉnh theo fable và opus: `2d6c247` (cắt theo phần tử) + `57d9535` (khi tràn
  trả `{"omitted", "note", "items"}`, khi vừa vẫn là danh sách, giữ nguyên từng byte) + `e904dd8`
  (3a-bis: nội dung mỗi tin Discord tối đa 800 ký tự, để luôn có đơn vị vừa). Ba commit chỉ đụng
  `agent_service.py` và `tests/test_agent_tool_results.py`. Test 3a-bis được kiểm là TRƯỢT khi bỏ
  trần (JSON gãy) và đạt khi có trần. Cả cụm phải gộp trước lần đo mốc v0.2.
- 27/10 — Theo fable và opus, trước lần đo mốc v0.2: mô tả `search_history` thêm "(mỗi tin tối đa
  800 ký tự)", con số lấy từ `HISTORY_MESSAGE_MAX_CHARS`, có test giữ hai thứ khớp nhau.
  `tools_sha256` đổi (`872acc92…`), nên thay đổi này thuộc mốc v0.2: **mốc v0.2 = bộ bài v0.2 + 3a +
  mô tả này.**
- 27/10 20:07 — **Đăng ký trước cách đo 1a và 2b**, viết TRƯỚC khi chạy 1a hay 2b. Mốc v0.2 (A =
  `d434c82`) đã chạy xong:
  - r1 lạnh (gỡ mọi model): 34/40.
  - r2, r3 nóng: 31/40, giống hệt nhau từng byte.
  - r4 (chỉ gỡ OCR và embedding): 31/40, giống hệt r2.
  
  Lỗi bộ chấm đã biết, sửa ở v0.3, không sửa giữa chừng: câu "kết quả tìm kiếm không trả về thông tin
  về ngân sách…" của doc-19 là câu đúng nhưng `NOT_FOUND_PATTERN` chưa nhận.
  - Điều kiện: A = mốc v0.2; B = A + 1a; C = B + 2b. **Luật chồng:** nếu B làm mất nhiều bài ngoài
    mục tiêu hơn số bài mục tiêu nó cứu được, thì 2b đo trên A chứ không trên B.
  - Giao thức đã duyệt: mỗi điều kiện 1 lần khởi động bỏ đi + 1 lần đo nóng, t0, seed 42. Commit trước
    khi đo, để `worktree_dirty` = false.
  - Hai phép kiểm, chạy trước khi đăng ký:
    - **Seed không có tác dụng ở t0**: r5 (seed 43) giống hệt r2 (seed 42), 40/40 câu trả lời. Đo nhiều
      seed ở t0 không cho thêm thông tin.
    - **Chỉ gỡ model chính** (r6) cho kết quả giống hệt r1 lạnh, 40/40. Nguyên nhân lạnh/nóng đã khoanh
      vào lần nạp đầu tiên của model chính; cơ chế chưa được chỉ ra. Quy tắc "khởi động bỏ đi" vì vậy
      có bằng chứng.
  - Phần bổ sung, ghi rõ là bổ sung: 3 lần ở nhiệt độ 0.4 (như ship, không seed) cho mỗi điều kiện A,
    B, C, để có độ dao động thật của từng điều kiện.
  - Mục tiêu của 1a: các bài ở mốc A nóng trượt vì KHÔNG gọi công cụ khi cần, gồm doc-10, doc-22,
    doc-25, doc-30 (`search_documents`) và stat-02 (`system_status`), tổng 5 bài. Mục tiêu của 2b:
    hist-07 (và hist-03 nếu chạy ở 0.4).
  - Báo cáo mỗi điều kiện theo thứ tự: (1) số bài mục tiêu đạt, trước và sau; (2) số bài NGOÀI mục
    tiêu được thêm hoặc bị mất (đây là sàn nhiễu do đổi prompt; ở mốc A, chỉ đổi mô tả công cụ và
    hình dạng kết quả khi tràn mà đã lật 5 bài không liên quan); (3) tổng điểm, sau cùng.
  - Mốc A ở 0.4 (bổ sung, đã chạy trước khi đăng ký): 31, 29, 33/40, tức dao động khoảng ±2 bài chỉ do lấy mẫu.
- 27/10 20:41 — **Đo xong** (GPU 19:42–20:41, không còn tiến trình nào chạy). Báo cáo:
  `data/evaluation/results/kept/agent-eval-v0.2-harness-20261027/REPORT.md`.
  - Lạnh/nóng: seed không có tác dụng ở t0. Gỡ OCR và embedding không đổi kết quả; chỉ gỡ model chính
    thì tái tạo đúng lần lạnh. Một lời dặn mới cũng làm lần đầu khác đi. Khớp giả thuyết "dùng lại
    phần đầu prompt", chưa chứng minh. Hệ quả: khởi động bỏ đi cho **mỗi** biến thể prompt mới.
  - Luật chồng kích hoạt (1a: mất 5 bài ngoài mục tiêu, cứu 3 bài mục tiêu), nên C = A + 2b. D = A + 1a
    + 2b là phần bổ sung.
  - Kết quả t0 / 0.4: A 31 / 31,29,33. B 31 / 28,31,27. C 32 / 30,32,31. D 31 / 29,30,29; D đếm tay
    (hist-03/07 trả lời đúng 8/8, trượt chỉ vì tiêu chí cấm search_documents) là 31,32,31.
  - KS (3a): 0/748 kết quả công cụ bị cắt giữa JSON, 85 lần bỏ bớt theo mục. Tác dụng lên điểm chưa đo.
  - Chưa làm registry, ngân sách token/thời gian, chuẩn hoá lỗi, tracing: không lỗi đo được nào đòi.
  - Nhánh hiện ở trạng thái D (`4beb9ba`: 1a + 2b). Chưa có quyết định ship thay đổi chất lượng nào;
    các phương án nằm trong REPORT.
- 27/10 20:55 — **Đính chính báo cáo `8848e67`** (sau khi người duyệt gợi ý kiểm mã băm):
  - A-r2 nóng và C-t0 nóng có cùng mọi mã băm prompt (2b không đổi prompt của bài web), nhưng chỉ
    trùng 3/33 câu trả lời bài web, và 7 bài lật. Vậy các lần đo nóng ở t0 của A, B, C, D ở bốn trạng
    thái máy chủ khác nhau, không so với nhau được. Bản đầu đọc nhầm thành tác dụng của việc đổi prompt.
  - Lần chạy lạnh mới lặp lại được: r1 = r6; A lạnh = C lạnh trên 33/33 bài web. Bổ sung đã chạy: B,
    C, D mỗi cái một lần lạnh, checkout đúng commit (20:47–20:55).
  - So sánh lạnh: A 34, B 30, C 34, D 30 (D đếm tay 32). Mục tiêu 1a: 2/5 → 4/5, nhưng mất 6–7 bài
    ngoài mục tiêu, chủ yếu do thiếu tên tệp khi trích nguồn. 2b một mình không đổi gì (C = A).
  - Quy tắc trong README của bộ bài đã sửa: so sánh ở t0 thì **gỡ model chính trước mỗi lần đo**;
    "khởi động bỏ đi" một mình là không đủ. Seed không có tác dụng ở t0.
  - Đề xuất đổi từ "cân nhắc" sang (c): chưa ship 1a hay 2b, thử 1a-v2. Chi tiết trong REPORT.
- 27/10 21:00 (opus 5.5, chốt theo báo cáo 59aed01 của Nhân viên 3): **không ship 1a hay 2b**. 1a cứu
  bài "không tra" (lạnh 2/5 → 4/5) nhưng mất 6–7 bài khác, chủ yếu vì thiếu tên tệp khi trích nguồn
  (lạnh 34 → 30); 2b một mình không đổi gì (model đọc gợi ý rồi hỏi xin phép). Chỉ gộp d434c82 (mô tả
  800 ký tự) và 59aed01 (báo cáo + quy tắc README); code 1a/2b ở lại trên nhánh làm hồ sơ. Thử tiếp
  1a-v2 (giữ "đừng hỏi xin phép, cứ tra", bỏ liệt kê dài, giữ câu trích nguồn) — đo sáng 28/10.
  **Đính chính quy tắc đo:** "bỏ một lần khởi động" là SAI — lần nóng không lặp lại được (cùng mọi
  hash prompt mà chỉ trùng 3/33 câu trả lời), lần lạnh thì lặp lại được (r1 = r6). Quy tắc đúng: gỡ model
  chính trước MỖI lần đo; seed không có tác dụng ở t0. Áp dụng cho bước 5 của ticket 16.
- 27/10 21:15 — **Đăng ký trước phép đo 1a-v2**, viết trước khi chạy. GPU: sáng 28/10, khi opus báo.
  Nhánh `wip/10-1a-v2` tạo từ `wip/10-keep`; code ở đó chính là mốc A nên không cần revert.
  - Điều kiện:
    - A = `9aaa75d` (mốc v0.2).
    - E = `5ed9d5a` (A + 1a-v2: chỉ đổi đúng một câu "chỉ gọi công cụ khi thật sự cần" thành "câu hỏi
      về tài liệu, quy định hay hệ thống của chính người dùng thì gọi công cụ phù hợp trước khi trả
      lời; đừng hỏi người dùng có muốn tra không, cứ tra", và "luôn nêu tên tệp (và số trang nếu có)").
    - F = `1434c6c` (E + 2b).
  - Quy trình (quy tắc mới): mỗi điều kiện checkout đúng commit, gỡ model chính, chạy một lần t0. Ba
    lần, khoảng 8 phút. A chạy lại làm đối chứng; lần lạnh của A ở tối 27/10 là 34/40.
  - Mục tiêu (như 1a): doc-10, doc-22, doc-25, doc-30, stat-02. Danh sách theo dõi (những bài 1a đã
    làm mất): doc-17, doc-19, doc-26, doc-27, doc-28, hist-03, hist-05. Mục tiêu 2b: hist-03, hist-07.
  - **Luật quyết định:**
    - Đề xuất ship E nếu cả ba điều cùng đúng: tổng lạnh của E ≥ tổng lạnh của A; mục tiêu 1a của E ≥
      mục tiêu của A + 1; và số bài trong danh sách theo dõi bị mất ≤ 1.
    - Đề xuất ship F thay E chỉ khi tổng của F ≥ tổng của E, hoặc F hơn E ở mục tiêu 2b khi đếm tay mà
      không mất bài nào khác.
    - Ngoài ba trường hợp đó: không ship, báo lại số đo.
    - Mỗi điều kiện chỉ có một lần chạy ở một trạng thái: đây là ngưỡng cho một quyết định thăm dò,
      không phải phép thử thống kê.
  - Lệnh (từ `C:\Users\dungbt06\local-ai-core-wt\10-harness`, mỗi commit một lần):
    `git checkout -q <commit>` rồi
    `bash <scratchpad>/gpu10.sh 1a-v2 "v0.2-<X>-cold-0328|general|--temperature 0 --seed 42"`, cuối cùng
    `git checkout -q wip/10-1a-v2`.
- 27/10 21:40 (Nhân viên 3) — Sửa REPORT v0.2 theo bản duyệt của fable (nhánh `wip/10-report-fix`):
  - Thêm bằng chứng trích nguồn: doc-26/27/28 mất trích dẫn ở 32/36 lượt có 1a, so với 5/45 lượt không
    có 1a.
  - "8/8 đúng người, đúng thời gian" → "10/10 đúng người và nội dung, 8/10 đúng thời điểm đăng". Bộ chấm
    không chấm thời điểm đăng, ghi cho v0.3.
  - "0/748" ghi rõ là đếm ở máy chạy, còn `kept/` giữ 253 kết quả, cũng 0.
  - Câu hỏi 2 thêm phân tích "mục tiêu 2b bất khả thi từ lúc đăng ký" và hai cách (a)/(b).
- 27/10 21:45 — **Bổ sung đăng ký trước 1a-v2**, vẫn TRƯỚC mọi lần chạy, theo bằng chứng fable nêu khi
  duyệt (trích nguồn ở doc-26/27/28 mất ở 32/36 lượt có 1a, so với 5/45 không có):
  - Chỉ số chính cho cái giá của 1a-v2: số bài trong doc-26/27/28 trượt mục `citation` ở lần lạnh.
    Đối chứng tối 27/10: A lạnh 0/3, C lạnh 0/3, B lạnh 3/3, D lạnh 3/3.
  - Luật ship của E thêm một điều kiện: E mất trích dẫn ở ≤ 1/3 bài này.
  - A chạy lại lạnh làm đối chứng, đồng thời kiểm xem lần lạnh có lặp lại qua ngày và qua khởi động lại
    Ollama không (tối 27/10: A lạnh = 34/40). Ticket 16 sẽ dựa vào điều này.
  - Sáng 28/10 có hai việc GPU (09 nhúng lại, và 1a-v2): chạy nối tiếp, không xen kẽ.
- 27/10 22:50 (Nhân viên 3) — **Kết quả 1a-v2**, đo 22:31–22:39 cùng lúc 09 chạy (opus đổi lịch; đăng ký
  ghi sáng 28/10, nối tiếp). Báo cáo: `data/evaluation/results/kept/agent-eval-v0.2-1a-v2-20261027/REPORT.md`.
  - Lạnh: A 34, E 33, F 33. E đạt 4/5 mục tiêu (A 2/5), mất 3 bài theo dõi (doc-17, doc-26, doc-27),
    mất trích dẫn 1/3. Mã băm lời dặn: A trùng lần 19:43, E = F, khác B.
  - Theo luật: E trượt 2/4 điều kiện (tổng 33 < 34; mất 3 > 1) → **không ship E**. Điều khoản F là
    "thay E" nên không áp khi E trượt; F cũng trượt đúng hai điều kiện đó → **không ship F**.
  - So với 1a đầu: mất 7 → 4, mất trích dẫn 3/3 → 1/3. Ngoài danh sách: hist-10 mất (kiểu hỏng mới),
    doc-29 được. doc-27 trượt vì bộ chấm đòi chữ "2 tiếng" (ghi cho v0.3); tính nó là đạt thì luật vẫn trượt.
  - A lặp lại 40/40 câu trả lời so với 19:43: qua 3 giờ, cùng một tiến trình Ollama. Chưa kiểm qua khởi
    động lại Ollama hay qua ngày. Run-id lệch mẫu đã đăng ký (`v0.2-1a2-<X>-cold`).
  - Code E, F ở lại nhánh `wip/10-1a-v2` làm hồ sơ; nhánh `wip/10-1a-v2-result` chỉ mang ticket và báo cáo.
  - `docs/RESULTS.md` sửa luôn câu cũ "cần một lần khởi động bỏ đi" thành quy tắc gỡ model trước mỗi lần đo.
- 27/10 23:00 (opus 5.5): 1a-v2 đo lạnh 33 vs 34, mất 3 bài theo dõi > 1 → không ship theo luật đã đăng
  ký (`ccc6136`). Đóng hướng 1a: đổi một câu lời dặn làm 38/40 câu trả lời đổi chữ, nên 40 bài không tách
  được tác dụng nhỏ của prompt. Sửa bộ chấm (doc-27 "2 tiếng", hist-07 cho phép tài liệu trước rồi lịch
  sử, NOT_FOUND "không trả về thông tin", ghi chú hist-08) gom vào v0.3, làm sau. Ticket 10 xong.
- 27/10 23:15 (opus 5.5, theo duyệt của fable): **đính chính** dòng đóng ticket: doc-27 không phải lỗi bộ
  chấm — ghi chú bài nói "phải tự tính ra 2 giờ", tức bài cố ý thử phép tính. v0.3 phải chọn có ý thức:
  giữ phép tính, hoặc bỏ và sửa ghi chú. Thêm vào README quy tắc đo: trong một lần chạy lạnh, so từng bài
  giữa hai điều kiện chỉ chắc cho các bài đứng **trước** chỗ khác đầu tiên (E/F: 0 lệch trước hist-07,
  12/13 lệch sau, dù prompt giống hệt). Lệch lan không do 09 (lượt cuối của 09 xong 22:28:10, 1a-v2 chạy
  22:31–22:39); khác biệt còn lại là model nhúng còn nạp cùng Ollama — chưa tách.
