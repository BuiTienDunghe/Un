# 06 — Agent Eval v0: khung chạy và bộ bài (M2)

Status: khung chạy + bộ bài nháp xong trên `wip/06-agent-eval-v0`; chờ fable 5.1 duyệt bộ bài
Type: task
Blocked by: —

## Vì sao

Ún đã có agent ([agent_service.py](../../../backend/app/services/agent_service.py): một vòng lặp tối
đa 3 bước, 3 công cụ), nhưng chưa có bài thi nào đo xem agent giải việc tốt đến đâu. 9 test hiện có
chỉ kiểm cơ chế chạy.

Quyết định (theo uỷ quyền 27/10):
- Q2 (i): theo quy ước sẵn có — code ở `backend/scripts/`, bài ở `data/benchmarks/agent_eval/`, kết
  quả ở `data/evaluation/results/agent_eval/<run_id>/` (đã bị gitignore, `.gitignore:52-58`).
- Q3 (c): so trước/sau ở nhiệt độ 0 có seed; thêm một lượt ở 0.4 (như ship) để kiểm thực tế.
- Q4 (b): bài tài liệu dùng kết quả truy xuất thật được ghi lại một lần rồi phát lại. Việc ghi cần
  stack nên để sang ticket 07; ticket này chỉ định dạng fixture sao cho bản ghi thả vào được ngay.

## Việc

1. Runner `backend/scripts/agent_eval.py` (chạy bằng `python -m scripts.agent_eval` từ `backend/`):
   gọi `AgentService.run()` với 3 backend giả theo Protocol (`agent_service.py:23-47`; mẫu
   `_bare_agent` trong `backend/tests/test_agent_service.py`), model thật qua `ModelRouter` dựng từ
   cấu hình đang active.
2. Bọc router để sau **mỗi** lượt `chat_tools` gọi `consume_usage()` — ContextVar chỉ giữ lượt cuối
   (`backend/app/llm_clients/usage.py:20-35`).
3. Nối `seed` cho chat: `model_router.py:81` hiện chỉ lấy temperature/top_p. Mặc định giữ nguyên
   (không seed nếu cấu hình không đặt). Runner ghi đè được nhiệt độ và seed **chỉ trong tiến trình
   eval**, không sửa `models.yaml` hay `model_versions.yaml`.
4. Mỗi lần chạy ghi `manifest.json` (commit, version id của general, model, nhiệt độ, top_p, seed
   hoặc "không seed", max_steps, `tool_result_max_chars` = 2400 ghi tường minh, hash prompt sau khi
   bọc injection-defense, phiên bản + sha256 của dataset, phiên bản bộ chấm), `task_results.jsonl`,
   `events.jsonl` (lấy từ `steps` mà `run()` trả, không đọc `agent_traces`), `summary.json`.
5. Bộ bài `data/benchmarks/agent_eval/v0/` khoảng 40 bài: 20 tài liệu, 10 lịch sử (guild giả cố
   định, có bài không guild — agent phải nhận lỗi "chỉ dùng được trong kênh Discord" và không bịa),
   5 trạng thái hệ thống (snapshot giả), 5 không cần công cụ hoặc phải từ chối. Mỗi bài có: đầu vào
   + môi trường, đáp án hoặc tiêu chí chấm, công cụ được phép + hành vi mong đợi. Chỉ dữ liệu giả
   hoặc đã khử thông tin nhạy cảm. Thiếu tiêu chí chấm tốt thì giảm số bài, không nhồi cho đủ.
6. Bộ chấm v0 tất định: có gọi / không gọi công cụ, tham số hợp lệ, có các ý bắt buộc (từ khoá /
   regex theo tiêu chí), có từ chối khi phải từ chối. Không dùng model để chấm ở v0.
7. Test (không cần stack, không cần Ollama): runner với router giả ghi đủ 4 file; bộ chấm trên vài
   câu trả lời mẫu; seed được truyền đi khi có, vắng khi không có.

## File được đụng

Mới: `backend/scripts/agent_eval.py` (tách module chấm điểm nếu cần), `data/benchmarks/agent_eval/v0/**`,
`backend/tests/test_agent_eval*.py`. Sửa: `backend/app/services/model_router.py` (chỉ phần seed) và
test của nó.

## Nghiệm thu

- Test mới xanh; `backend/tests/test_agent_service.py` và test của model_router vẫn xanh.
- Nếu Ollama đang có `qwen3.5:9b`: chạy thử 3 bài từ đầu đến cuối, đủ artifact (ghi lệnh + đường dẫn
  run trong Comments). Không có thì ghi "chưa chạy với model thật".
- fable 5.1 đã duyệt bộ bài (ghi trong Comments).

## Comments

**27/10 — Nhân viên của Ún 3: bản nháp.**

- Chạy thử với model thật, 3 bài, nhiệt độ 0, seed 42 (từ `backend/`):
  `python -m scripts.agent_eval --tasks doc-04,hist-04,hist-08 --temperature 0 --seed 42 --run-id smoke-20261027-t0-seed42`.
  Artifact ở `data/evaluation/results/agent_eval/smoke-20261027-t0-seed42/` trong worktree (gitignore,
  không commit). Kết quả 2/3 đạt; hist-04 trượt vì **lỗi bộ chấm**: model thuật lại lời chèn lệnh,
  không làm theo, nhưng tiêu chí cấm chữ "HACK" đánh trượt nó. Đã sửa tiêu chí của doc-04, doc-20
  và hist-04 sang "làm theo hay không", có test giữ lại điều này. Chấm lại offline câu trả lời cũ:
  3/3 đạt. Chưa chạy lại model vì đã dùng hết hạn mức 3 bài.
- Bộ bài có 40 bài: tài liệu 20, lịch sử 10 (7 Discord có guild, 3 web không guild), trạng thái 5,
  không công cụ hoặc từ chối 5.
- Chỗ lệch ticket hoặc thêm vào:
  - Thêm mục chấm `citation` (`must_cite`: tên tệp + số trang, vì guide của agent yêu cầu).
  - Bài Discord dùng nhãn người nói thật cộng `DISCORD_SPEAKER_SYSTEM_INSTRUCTION`, không có persona
    và khối trí nhớ (spec ghi là không đo).
  - Runner không probe registry (`verified: false` trong manifest). Nó dựng `Settings` với
    `DATABASE_URL` giữ chỗ, vì worktree không có `.env` và eval không mở DB nào.
  - Seed chỉ đi qua Ollama (`_ollama_options`); `_cloud_kwargs` không đổi.
  - `FixtureHistory` import `_SAFE_LEXEME` (tên private) từ `discord_history_service` để tách từ
    giống hệt bản thật.
- Duyệt bộ bài: (chờ fable 5.1)
