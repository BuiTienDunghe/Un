# 06 — Agent Eval v0: khung chạy và bộ bài (M2)

Status: đã giao — Nhân viên của Ún 3 (fable 5.1 duyệt bộ bài)
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
