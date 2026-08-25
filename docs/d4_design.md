# D4 — LLMOps / Observability: khảo sát và kế hoạch

**Ngày:** 25/08/2026 · **Trạng thái:** THIẾT KẾ — chưa có dòng code nào
**Phương pháp:** 5 agent khảo sát song song trên hệ thống thật (production DB, API sống, git history, log file), cộng một agent phản biện kế hoạch. Mọi con số dưới đây là **đo thật**, không ngoại suy; chỗ nào suy đoán đều ghi rõ.

---

## 0. Kết luận trước, lý lẽ sau

> **KHÔNG làm D4 như mô tả trong `DEVELOPMENT_PLAN.md` §4d#6.**
> Ước lượng 3–4 buổi được định giá cho một hệ thống **không tồn tại ở đây**. Chân "retrieval" của cái cây đã xây xong và bền vững; chân "tool call" cũng đã xây xong **và rỗng vĩnh viễn theo thiết kế**; còn bản ghi mà sự thiếu vắng của nó tốn nhiều thời gian nhất thì **D4 không hề nhắc tới** và nó dài khoảng 10 dòng.
>
> Đề xuất: **"D4-lite" ~1 buổi** (ba thay đổi nhỏ, **không thêm bảng nào**), cộng nửa buổi cho hai việc ngoài D4 có giá trị đo được cao hơn.

Điều quan trọng nhất trong tài liệu này, nói thẳng ở đây: **cái cây trace mà D4 lấy làm sản phẩm chủ lực sẽ KHÔNG bắt được lỗi lớn nhất lịch sử dự án.** Khi cross-encoder cắt cụt 65% kho, thời gian vẫn bình thường, số token thuộc về một model khác, và các chunk đã nằm sẵn trong `message_sources`. Cây trace không hiện gì bất thường cả. Thứ bắt được nó là **một dòng cảnh báo của thư viện** — thứ mà hệ thống này hiện đang vứt đi.

---

## 1. Mô tả gốc, và ba chỗ nó sai về chính dự án

§4d#6 viết: *"Hợp nhất sử liệu rời (`agent_traces`, `request_logs`, dashboard) thành trace một-câu-hỏi-một-cây… Prompt quản lý như code — mỗi version có số hiệu gắn điểm eval (extractor đã qua 5 đời prompt không sử liệu)."*

Đoạn đó viết nhiều tháng trước và chưa từng đối chiếu với code. Đo lại:

| Mô tả nói | Thực tế đo được |
| --- | --- |
| «hợp nhất 3 nguồn sử liệu» | Một nguồn (`agent_traces`) có **0 dòng** và được thiết kế để mãi mãi 0 dòng (§6.1). Một nguồn (`dashboard`) **không phải bản ghi**, nó là bộ hiển thị. Còn lại đúng **một** bảng thật: `request_logs`, 142 dòng, trong đó **65% là lời gọi của robot eval**, không phải của người. |
| «extractor đã qua 5 đời prompt **không sử liệu**» | Sai hai lần. Thứ nhất là **4 đời**, không phải 5 — nhãn `_V5` đang gắn lên **đúng văn bản của V4**, và không tồn tại thân `SYSTEM_PROMPT_V5` nào. Thứ hai, **sử liệu CÓ tồn tại**: `data/benchmarks/discord_memory_extractor/` giữ 8 file JSON, mỗi file đóng dấu `prompt_version` kèm toàn bộ chỉ số. |
| «tokens vào/ra, thời gian, prompt version» | Đã xây **trọn vẹn** — nhưng ở nhánh Discord extractor, ghi vào một bảng **0 dòng** mà **không có code nào đọc lại**. |

Chỗ thứ ba đáng dừng lại: dự án này đã từng xây một kho prompt-version-kèm-token rồi. Nó chưa bao giờ có dữ liệu. Xây cái thứ hai theo đúng hình dạng đó là lặp lại thí nghiệm đã thất bại.

---

## 2. Cái gì đã có sẵn — rủi ro lớn nhất là xây lại

| Điều khoản trong D4 | Trạng thái | Bằng chứng |
| --- | --- | --- |
| Chân **retrieval** của cây | ✅ **ĐÃ CÓ, bền vững, cùng transaction** | `message_sources`: chunk, điểm, trang, heading, trích đoạn, thứ tự trích dẫn — ghi trong **cùng transaction** với câu trả lời (`postgres_auxiliary_store.py:72-97`). Câu trả lời không thể tồn tại mà thiếu các đoạn đã căn cứ vào. |
| Chân **tool call** | ✅ Đã có bảng, writer, store, API, migration, `latency_ms` từng bước, test — ❌ và **rỗng** | `models.py:829-853`, `chat_service.py:143`. 0 dòng; `agent_traces_id_seq.last_value = 20` — **20 dòng đã từng tồn tại và đã bị xoá sạch**. |
| **Thời gian theo tầng** của một thao tác | ✅ Đã có **cho index** — đúng hình dạng "một thao tác một dòng" mà D4 muốn | `ingestion_runs`, 17 cột: stage, số trang, số chunk, attempt, error_code, started/completed. 13/13 version có đủ. |
| p50/p95 + lưu lượng theo thời gian | ✅ Đã có | `percentile_cont` trong Postgres, gom theo ngày địa phương (`routers/dashboard.py:31-75`). |
| «version gắn điểm eval» | ✅ Đã có dạng artifact | 8 file JSON trong `data/benchmarks/…`, gồm cả **cú sụt của v3** (schema compliance 1.0 → **0.05**). |
| «version + số trước/sau» | ✅ Đã có, dạng văn xuôi mà nhóm vẫn duy trì | Chú thích cờ trong `models.yaml`: contextual "MRR 0.734 → 0.797", injection defense "0.143 → 0.000", reranker "0.915 → 0.976". |

Trừ hết những thứ trên, phần D4 **thật sự còn thiếu** là: **một khoá join, hai cột số nguyên, và một hàm băm.** Đó không phải 3–4 buổi.

---

## 3. Phía cầu — những câu hỏi đã thật sự tốn thời gian

Observability chỉ đáng xây cho những câu ai đó **đã thật sự cần trả lời mà không trả lời được**. Xếp theo chi phí đo được:

### 3.1. "Thư viện đã cảnh báo gì trong lần chạy này?" — tốn 4 ngày

Cross-encoder chấm `(câu hỏi, nội dung)` mà không đặt `max_length`, nên **123/190 chunk production (65%)** bị chấm trên phần đầu bị cắt cụt. Bật mặc định 21/08 17:39 (`affa70a`) → sửa 25/08 19:07 (`aba731c`): **4 ngày, 93 request production**. Suốt 4 ngày đó, triệu chứng bị ghi nhầm sang phân hệ khác (`p4_progress.md:544` — "headroom cho P4-4/P4-5").

Tokenizer **in cảnh báo `778 > 512` ở mọi lời gọi**. Đã kiểm: **0 dòng khớp trong cả 8 file log 30 ngày**. Lý do: `logging_service.py:16-24` là toàn bộ cấu hình sink — chỉ có loguru. Không `InterceptHandler`, không `logging.captureWarnings`, không `logging.basicConfig` ở bất kỳ đâu trong `backend/app`. **Mọi cảnh báo của transformers, httpx, uvicorn đều chảy ra một cửa sổ console rồi biến mất khi đóng.**

> Đây là bản ghi mà sự thiếu vắng của nó tốn nhiều thời gian nhất trong lịch sử dự án. Nó **không nằm trong mô tả D4**. Nó dài khoảng 10 dòng.

### 3.2. "Câu hỏi này tốn thời gian ở tầng nào?" — không trả lời được

`request_logs` có **7 cột**: id, endpoint, model_used, latency_ms, status, error_code, created_at. **Một số nguyên cho cả request.** Không chia tầng, không token, không khoá nối sang câu trả lời.

Sáng 25/08 tôi phải **chạy tay lại** mới biết 2509 ms là do nạp model lần đầu chứ không phải hồi quy. Thời gian rerank có tồn tại — nhưng chỉ dưới dạng chuỗi đã định dạng trong một file log không ai đọc, và **không nối được** với request nào.

### 3.3. "Số đo này thuộc câu hỏi nào?" — khoá nối đã hỏng sẵn

**Không có correlation id ở bất kỳ đâu.** Thứ duy nhất nối `request_logs` với câu trả lời là **dấu thời gian lệch 19 ms**. Và phép nối đó **đã hỏng trong production**: **5/27 dòng câu hỏi (19%)** không còn message nào trong bán kính ±2 giây — hội thoại bị xoá, message cascade theo, số đo trở thành mồ côi.

> "Câu hỏi chậm nhất tuần trước là câu nào?" — không trả lời được, vì dòng đó có thể đã không còn câu hỏi gắn vào.

### 3.4. "16 giây là nạp prompt hay là sinh chữ?" — không trả lời được

Ollama **trả sẵn** `prompt_eval_count` và `eval_count` trong body. `ollama_client.py:57` lấy đúng `message.content` rồi **vứt phần còn lại**. `model_router.chat` trả tuple 2 phần tử, không có chỗ cho usage.

### 3.5. "Câu trả lời tệ đi từ thứ Ba — prompt có đổi không?" — không trả lời được

Không có định danh prompt trên bất kỳ câu trả lời nào. 12 chỗ có prompt, **4 chỗ còn khôi phục được văn bản**. Và đã có một lần trôi lặng lẽ: nhãn `_v5` đang gắn trên văn bản V4 — test đáng lẽ bắt được thì lại **so hằng số với chính nó** (`test_discord_memory_extractor.py:185`).

---

## 4. Phạm vi đề xuất — "D4-lite", theo thứ tự thi công

**Không thêm bảng nào. Không thêm panel nào. Không thêm lời gọi model nào.**

### #1 — Bắt cảnh báo của thư viện vào sink đã có *(~10 dòng, nửa giờ)*

`logging_service.py`: thêm `InterceptHandler`, `logging.basicConfig(handlers=[...], level=0, force=True)`, `logging.captureWarnings(True)`, và bổ sung `logger.remove()` còn thiếu (hiện mỗi tiến trình tự gắn thêm một sink vào **cùng một file**, và sink stderr mặc định chưa bao giờ bị gỡ nên mọi dòng đều bị nhân đôi).

**Nghiệm thu:** một lần gọi `/rag/chat` phải sinh ra **ít nhất một dòng không phải của app** trong file log của ngày. Kiểm bằng cách hạ `chunk_tokens` để cố tình kích hoạt lại cảnh báo `> 512` và xác nhận nó **có trong file**.

### #2 — Đóng khoá join bằng **một cột nullable additive** *(~20 dòng)*

`add_message` **đã trả về `int`** (`postgres_auxiliary_store.py:72`); `rag_service._persist_turn` (`:58-62`) trả `None`, **vứt id đúng một dòng trước** khi gọi `log_request` ở `:183`. Cho nó trả id và truyền xuống.

Thêm `request_logs.message_id` (nullable, additive, có `downgrade`) biến **ba bản ghi đã có sẵn** — `message_sources` (retrieval) + `messages` (câu trả lời) + `request_logs` (tổng thời gian) — thành đúng "một cây một câu hỏi" mà D4 mong muốn, **mà không cần bảng mới**.

Nhân tiện phải xử lý luôn: hiện `dashboard.py:50-53` gộp **bốn đại lượng khác nhau** vào một percentile — `rag_service.py:198` và `chat_service.py:148` chỉ đo phần streaming, các chỗ khác đo cả request. Hoặc dời mốc `started`, hoặc thêm cột `phase`.

> Ràng buộc bất biến #8 ("đo trước khi đổi schema") đã thoả: số đo nằm ở §3.3 — 19% mồ côi, 27 dòng câu hỏi trong toàn cửa sổ lưu trữ.

### #3 — Hai cột token và một hàm băm prompt *(~30 dòng)*

`ollama_client.py:37-60` **đã cầm sẵn body JSON**: trả kèm `prompt_eval_count`/`eval_count` và lưu vào cùng dòng `request_logs`. Riêng biệt: `sha256` của **prompt đã lắp ráp xong** — lưu ý `rag_service.py:38-39` bọc file `.md` qua `defense.system_prompt()`, nên **file không phải là prompt đã chạy**.

Băm trả lời được câu "prompt có đổi hôm thứ Ba không?" **mà không cần registry**, và nó là **cơ chế duy nhất** bắt được kiểu trôi nhãn-`_v5`-trên-văn-bản-V4.

### #4 — Đăng ký eval cấu hình-đang-chạy thành Scheduled Task *(một dòng lệnh)*

Baseline đã có và còn hiệu lực (`rag_multidoc_baseline.json`, 25/08, recall 0.9878 / mrr 0.9360, có đóng dấu tokenizer). CI **cố ý** chỉ đo đường trần (`ci.yml:264-289` ghim `contextual_retrieval` và `reranker` = false). Nghĩa là **không có gì tự động canh chất lượng của cấu hình mà production thật sự chạy**.

Đặt cạnh Scheduled Task `\LocalAICore Backup` 02:00 đã có. **Đây là thứ đáng lẽ đã báo động vụ reranker bằng chất lượng** — đúng cách nó rốt cuộc được tìm ra bằng tay.

### #5 — Làm cho một lỗi có thể được ghi lại *(~15 dòng)*

`select status, error_code, count(*) from request_logs group by 1,2` → **đúng một dòng: `('ok', None, 142)`**. Nhánh lỗi **chưa từng chạy một lần nào**.

Vì: `routers/rag.py:55,57,59,103,105,107,109` ném lỗi **không gọi** `log_request`; `rag_service.py:206-213` không ghi gì khi stream bị ngắt; `chat_service.py:176-182` ghi stream bị ngắt là **`"ok"`**. Chừng nào chưa sửa, mọi biểu đồ lỗi trong D4 đều là biểu đồ số không.

---

## 5. Loại khỏi phạm vi, và lý do

| Loại bỏ | Vì sao |
| --- | --- |
| Bảng trace/span mới | Thêm bảng vào chuỗi 27 migration để lưu ~3 cây/ngày, phần lớn mô tả robot. Một cột `message_id` cho kết quả tương đương với 1/10 công sức. |
| Bảng registry prompt | Sẽ là **lần thứ hai** repo này xây kho prompt-version không ai ghi vào. Và registry **không** bắt được lỗi đã thật sự xảy ra (nhãn lệch văn bản) — **băm thì bắt được**. |
| Panel cây trace trên dashboard | `GET /agent/traces/{message_id}` **đã tồn tại** để phục vụ đúng việc đó và có **0 caller** ngoài test. UI chat vẽ các bước từ sự kiện SSE trực tiếp, không đọc dòng đã lưu. Vẽ đẹp hơn cho một thứ không ai xem vẫn là không ai xem. |
| Hợp nhất `agent_traces` | 0 dòng, và **được thiết kế** để giữ nguyên như vậy (§6.1). |
| Kế toán chi phí token | Ollama chạy cục bộ, **không có chi phí mỗi token**. Quyết định duy nhất mà token phục vụ ở đây là "16 giây là nạp prompt hay sinh chữ" — giữ bản 5 dòng ở #3, bỏ mọi khái niệm ngân sách/chi phí. |
| Điều chỉnh retention vì dung lượng | 8 file log, **2,9 MB**, trên ổ 2 TB. Ai nêu dung lượng làm lý lẽ là đang giải một bài toán không tồn tại. |

---

## 6. Hai va chạm bất biến phải giải **trước** khi thêm bất kỳ bảng nào

### 6.1. Trace tự xoá lịch sử của chính nó

`agent_traces.conversation_id` và `message_id` đều `ondelete="CASCADE"`, và **chủ ý được viết thẳng vào docstring**: *"a trace never outlives the answer it explains"* (`models.py:834-835`). Hậu quả đo được: sequence ở **20**, bảng ở **0**. `evaluate_rag.py` xoá mọi hội thoại nó tạo (`:168, :294, :305, :397`); người dùng xoá một chat cũng vậy.

Bảng trace mới nào sao chép hình dạng đó sẽ **mất lịch sử của chính nó**. Còn phá cascade thì đổi lấy: dòng mồ côi, một job dọn dẹp, và **chính sách retention thứ ba** bên cạnh 7 ngày của `request_logs` (`settings.py:37`) và 30 ngày của file log (`logging_service.py:21`) — **hai chính sách vốn đã bất đồng về cùng một sự kiện**.

> Đây là **quyết định thiết kế cần mở lại**, không phải bug im lặng đi sửa.

### 6.2. Cách cài đặt tự nhiên nhất vi phạm bất biến #2

Một dòng span mở ở retrieval và đóng sau generation — cách cài đặt hiển nhiên — chính là **một vòng đời transaction/row bao quanh một lời gọi model**. Bất biến #2 cấm điều đó, và `rag_service.py:181-183` **cố ý viết ngược lại**: sinh trước, ghi sau, log sau cùng.

Đây là **việc thiết kế thật**, đang bị định giá nhầm thành việc sửa schema.

---

## 7. Ước lượng và chỗ tiêu thời gian tiết kiệm được

| | Ước lượng |
| --- | --- |
| D4-lite mục #1–#5 | **1 buổi + nửa buổi** |
| D4 như mô tả gốc | 3–4 buổi, phần lớn xây lại thứ đã có |

Hai buổi tiết kiệm được nên dồn vào **D2** (distillation, là điều kiện mở lại D3c) hoặc **D3b** — không phải xây lại `message_sources` với nhiều phép join hơn.

**Một việc vài phút, làm luôn khi đụng vùng:** đóng lại chú thích sai trong `DEVELOPMENT_PLAN.md` — "5 đời prompt không sử liệu" là **sai**; sử liệu nằm ở `data/benchmarks/discord_memory_extractor/` (8 file, gồm cả cú sụt v3 mà tài liệu lưu trữ nhảy cóc qua). Thứ thiếu là **một con trỏ từ code sang các file đó**, theo đúng định dạng chú thích `models.yaml` mà repo vẫn duy trì.

---

## 8. Phát hiện phụ đáng ghi (ngoài phạm vi D4)

| | |
| --- | --- |
| `check_operational_alerts.py` **không được lịch nào chạy** | Script có thật, chạy được. Scheduled Task duy nhất của dự án trên máy này là backup 02:00. |
| Biểu đồ 14 ngày **chỉ có thể hiện 7 ngày** | `REQUEST_LOG_RETENTION_DAYS=7` xoá cứng; `dashboard.py:32` mặc định `days=14`. 6/14 cột luôn rỗng. |
| `/api/ocr/system/metrics` — màn hình GPU/VRAM **không ai xem** | `monitoring_service.py:6-19` chạy tốt (psutil + `nvidia-smi`), là **nơi duy nhất** hệ thống đo GPU. Không màn hình nào hiển thị, trong khi dashboard hiện các số luôn bằng 0. |
| 11/17 khoá trong `/metrics` được tính mỗi 20 giây và **không hiển thị ở đâu** | |
| `backend/app/prompts/vision_system.md` là **file chết** | 0 tham chiếu trong toàn repo. |
| **DB lab KHÔNG rỗng** *(đính chính 25/08)* | `local_ai_core_lab_20260821`: **5 tài liệu, 54 chunk, 1.725 request_logs** — giữ toàn bộ lịch sử độ trễ của mọi thí nghiệm P4, và **không surface nào đọc nó**. Cái rỗng là `local_ai_core_test`, DB nháp của pytest. Một khảo sát trước đã kiểm nhầm DB và kết luận sai được chuyển tiếp trong hội thoại — ghi lại ở đây để không lặp lại. |
