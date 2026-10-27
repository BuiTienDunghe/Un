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
