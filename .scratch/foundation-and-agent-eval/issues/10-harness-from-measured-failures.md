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
