CẦN SỬA

# Duyệt wip/31-model-switch-ui d9bf55c (so với main eba3794) — fable 5.1, 30/10/2026

Cơ chế lõi đúng và tôi đã chạy thử được phần lớn: trình khởi động đọc tệp lựa chọn đúng trong 5 trạng thái tệp,
không bài đánh giá nào nhìn thấy lựa chọn, danh sách tag cần tải không đổi khi ghim Haiku, cổng bảo vệ đúng theo
đọc mã, 145 test không cần DB xanh. Ba chỗ phải sửa đều nhỏ và cùng một gốc: mã không phân biệt được "ghim từ tệp
lựa chọn" với "ghim từ shell", nên màn hình và lời hướng dẫn sửa lỗi nói sai ở đúng trạng thái chủ dự án đang
dùng hôm nay (`run-un-haiku.bat`, còn nằm untracked ở main, không được bản này gỡ).

## Bản chất

Trước đây muốn đổi model trả lời phải mở một tệp khởi động khác. Bản này cho bấm trên màn hình: lựa chọn được ghi
vào một tệp nhỏ, trình khởi động bình thường đọc tệp đó và đặt thành biến môi trường trong cửa sổ của nó, nên mọi
tiến trình khởi động từ cửa sổ đó dùng lựa chọn, còn bài đánh giá (khởi động bằng đường khác, hoặc tự gỡ biến đó)
không thấy. Vấn đề: máy chủ chỉ biết "đang có ghim" chứ không biết ghim đến từ tệp hay từ shell, nên khi ghim đến
từ shell nó vẽ như thể có một lựa chọn chờ áp dụng, và khi lựa chọn hỏng nó bảo người vận hành đi gỡ biến trong
một shell không tồn tại.

## Đã kiểm

| Việc | Cách | Kết quả |
|---|---|---|
| Khối `for /f` của launcher | Chép nguyên khối vào `t.bat`, chạy `cmd` với 5 trạng thái tệp (CRLF, rỗng, dòng trống + `;`, không có tệp, LF) | CRLF không để lại `\r` (len 16); tệp rỗng/không có → giữ nguyên giá trị của shell cha; dòng trống và `;` bị bỏ qua |
| Trạng thái màn hình | Gọi thẳng `_registry_view` với probe giả (không mạng, không GPU) ở 7 trạng thái A–G | bảng dưới; A, B, D, E, F đúng; C và G sai (mục chặn 1) |
| Văn bản ATTENTION khi lựa chọn hỏng | `attention_text()` của trạng thái E | "unset MODEL_VERSION_GENERAL in this shell" (mục chặn 2) |
| Bài đánh giá có thấy lựa chọn không | Đọc `nightly_eval.lab_environment`/`registry_verdict`, `eval_stack.stack_env`, `agent_eval.build_settings`, `memory_e2e_eval`, `evaluate_rag.version_gate` | Không: nightly gỡ `MODEL_VERSION_*`, verdict chỉ nhìn `source`/`fallback`; các bài khác dựng env riêng từ `.env`; `version_gate` đọc `requested` |
| Tiến trình launcher dùng `general` | grep `["general"]`/`model_name("general")` trong `scripts/`, `app/` | Chỉ API; backup/cleanup/outbox/memory/condenser không gọi `general`, nên worker chạy sót với env cũ vô hại |
| Danh sách tag cần tải khi ghim Haiku | `--ollama-pull-list` không ghim / ghim `general-haiku-v1` / ghim id không có | giống nhau 3 tag (`qwen3.5:9b` vẫn còn vì chuỗi lùi haiku→v0); id lạ → exit 1 (mục không chặn 1) |
| `check_registry()` trên worktree | gọi trực tiếp | 0 lỗi, 4 cảnh báo (khớp docs) |
| Test | `pytest tests/test_model_choice.py tests/test_frontend.py tests/test_model_registry.py` với env coordinator cho | 145 xanh, 11 skip (mọi test cần `client`) |
| `node --check models.js` | | xanh |
| Compose | grep `MODEL_VERSION` trong `docker-compose.yml` | chỉ EXTRACTOR/VERIFIER/EMBEDDING được truyền; container không nhận `MODEL_VERSION_GENERAL` |

Ma trận trạng thái (`versions[].status` mà màn hình vẽ; `chosen` = lựa chọn trên đĩa, `loaded` = bản đang chạy):

| # | Trạng thái | requested / loaded / source | chosen | v0 | haiku | Đúng? |
|---|---|---|---|---|---|---|
| A | chưa chọn gì | v0 / v0 / registry | v0 | active | candidate | đúng |
| B | chọn Haiku, chưa khởi động lại | v0 / v0 / registry | haiku | serving | pending | đúng |
| C | ghim shell (`run-un-haiku.bat`), có khóa, KHÔNG có tệp | haiku / haiku / env | **v0** | **pending** | serving | **sai** |
| D | chọn Haiku, đã khởi động lại, có khóa | haiku / haiku / env | haiku | candidate | active | đúng |
| E | chọn Haiku, khởi động lại, không khóa → lùi | haiku / v0 / env | haiku | serving | failed | đúng |
| F | như E nhưng `MODEL_STARTUP_PROBES=false` | haiku / haiku / env | haiku | candidate | active | đúng (probe tắt thì không biết thiếu khóa — hành vi sẵn có) |
| G | đã chọn Haiku, bấm Về mặc định, backend còn ghim | haiku / haiku / env | v0 | pending | serving | đúng theo launcher thường |

## Chặn

1. **`backend/app/routers/models.py:40` — "không chọn gì" bị gộp thành "chọn bản mặc định".** `chosen = choices.get(role) or row["active"]`; khi không có tệp mà `source == "env"` (ghim shell), `_version_status` (dòng 29) gắn `pending` cho `general-v0`. Kịch bản: chủ dự án mở bằng `run-un-haiku.bat` như hôm nay rồi vào `#/models` → Qwen hiện "chờ khởi động lại" dù chưa ai bấm gì; nút "Về mặc định" bấm xong cũng không đổi gì (xem mục 3). Đây là trạng thái "pinned from the shell" brief yêu cầu kiểm, trả lời là sai. Đã chạy: ma trận dòng C. Hướng sửa: `chosen = choices.get(role)` (None khi không có lựa chọn) và chỉ gắn `pending` khi thật có lựa chọn khác bản đang chạy; test `test_models_offers_the_switch_only_on_the_answer_role` hiện ghim `chosen == QWEN` nên phải đổi theo.

2. **`backend/app/config/model_registry.py:913-915` (`_revert_lines`) và `docs/model_registry.md:351` nói ngược với dòng 72 mới.** Khi lựa chọn là Haiku mà chưa có `ANTHROPIC_API_KEY`, backend lùi về Qwen và ghi `data/logs/ATTENTION_model_fallback.txt`: `revert: unset MODEL_VERSION_GENERAL in this shell (or set it to general-v0), then restart run-local-ai-core.bat`. Không có shell nào để gỡ; khởi động lại thì launcher nạp lại tệp y nguyên; `check_operational_alerts` gấp dòng này vào báo cáo sáng (`model_fallback_alert`, exit 2 với `--fail-on-alert`) mỗi ngày cho tới khi người vận hành tự tìm ra "Về mặc định". Ghi chú trên thẻ (`models.js:235`) cũng nói "Bản active hỏng" trong khi bản hỏng là bản được chọn. Đã chạy: `attention_text()` trạng thái E. Lưu ý `test_a_pinned_candidate_that_falls_back_tells_the_operator_to_unset_the_pin` ghim nguyên văn câu hiện tại cho reranker, nên sửa theo kiểu nối thêm ("…hoặc bấm Về mặc định trên /ui/#/models, hoặc xoá data/model_choice.env"), đừng thay. Bảng §Revert dòng 351 thêm cùng ý.

3. **`backend/app/services/model_choice.py:40` — "Về mặc định" ghi tệp rỗng, nên ghim thừa hưởng từ shell cha vẫn thắng.** Đã chạy: `cmd` trạng thái tệp rỗng → `VALUE=[from-parent-shell]`. Kịch bản: còn dùng `run-un-haiku.bat` (untracked ở main, bản này không gỡ, CHANGELOG không dặn xoá) thì bấm "Về mặc định" rồi khởi động lại vẫn ra Haiku, trái câu "Bỏ lựa chọn riêng… dùng lại bản mặc định" trong UI/CHANGELOG. Điều khoản "lựa chọn được nhớ dù mở launcher cách nào" vẫn đúng cho *chọn* (tệp có giá trị thì thắng shell cha — đã chạy, trạng thái 1), chỉ hỏng cho *bỏ chọn*. Các cách, chủ dự án chọn:
   - (a) revert ghi dòng `MODEL_VERSION_GENERAL=` (giá trị rỗng): launcher chạy `set "MODEL_VERSION_GENERAL="` → gỡ ghim thừa hưởng; Settings đã coi "" là chưa đặt (`_empty_pin_is_unset`). Ưu: tệp trở thành nguồn duy nhất, một dòng + một test. Nhược: `read_choices` phải tiếp tục bỏ qua giá trị rỗng (hiện đã vậy), và phải sửa `test_a_pick_round_trips_and_can_be_dropped` (hiện kỳ vọng `read_choices == {}` — vẫn đúng — nhưng không kiểm nội dung tệp sau revert).
   - (b) không sửa mã; CHANGELOG/docs dặn xoá `run-un-haiku.bat` và không `set MODEL_VERSION_GENERAL` trong shell khi mở launcher. Ưu: không đụng mã. Nhược: dựa vào thói quen; mục 1 vẫn vẽ sai nếu ai đó ghim shell.
   - (c) cả hai.
   Tôi nghiêng (a)+dặn xoá tệp cũ, vì rẻ và khép kín; đây là ý kiến.

## Không chặn

1. **Lựa chọn trỏ id không còn trong registry → không khởi động được, lời báo không chỉ về tệp.** `--ollama-pull-list` exit 1 (`run-local-ai-core.bat:143` không kiểm mã thoát của lệnh trong backtick, nên bước tải tag im lặng bỏ qua), rồi uvicorn từ chối boot với `MODEL_VERSION_GENERAL='…' names no version…`; chỉ dòng `[MODEL] … (chosen on the Model screen)` ở trên gợi ý tệp. UI lúc đó chết nên không bấm "Về mặc định" được; nên ghi vào docs dòng 72: "xoá `data/model_choice.env` nếu backend từ chối boot vì id này".
2. Khi chọn Haiku mà chưa có khóa, `POST /models/general/promote` vẫn nhận (không kiểm `settings.anthropic_api_key`), hộp xác nhận không nhắc khóa; hậu quả là trạng thái E + báo động sáng. Một kiểm tra 409 `PROVIDER_NOT_REGISTERED` lúc bấm sẽ chặn sớm; đổi lại khóa thêm vào `.env` sau khi boot sẽ không được thấy cho tới lần khởi động lại.
3. `test_api_key_auth.WRITE_REQUESTS` chưa thêm hai route POST mới; `test_model_choice` đã kiểm 401 riêng (qua `get_settings()`, cùng đối tượng với `app.state.settings`, main.py:49/117) nên không hở, chỉ lệch quy ước.
4. `README.md:127` và `.env.example:121-122` vẫn chỉ mô tả cách ghim shell; không sai nhưng thiếu cách mới.
5. Nút "Về mặc định" bật cả khi chưa chọn gì (ghi tệp rỗng, toast "Đã chọn lại bản mặc định"); vô hại, có thể khoá khi `chosen == active`.
6. Nút Promote/Revert biến mất trên các thẻ không phải `general` — khớp câu CHANGELOG "Vai trò khác vẫn chưa đổi được từ giao diện"; `versionRows`/`cardNotes` các thẻ khác không đổi đường đi (`switchable`/`chosen` vắng → về `row.active` như cũ).
7. `evaluate_rag`/`redteam_rag` mặc định `--base-url 127.0.0.1:8000`: chạy tay vào production khi đang chọn Haiku sẽ chấm Haiku — không mới (ghim shell cũng vậy), nhưng giờ ghim là lâu dài; docs đã dặn đo trên lab stack.
8. `.gitignore` `data/model_choice.env*` phủ cả `.tmp`; mã hoá ASCII an toàn vì id khớp `[A-Za-z0-9._-]+`; `os.replace` nguyên tử và launcher chỉ đọc trước khi API lên nên không đụng nhau.

## Không kiểm được

- Mọi test cần `client` (11 skip, không DB) — gồm 401, 404/409, `/models/check` qua HTTP; coordinator chạy bộ DB riêng.
- Đường bật tài khoản (`require_admin` tra DB): chỉ đọc mã (service key qua, member 403, nặc danh 401).
- Hiển thị thật trên trình duyệt: kết luận màn hình suy từ `_registry_view` + ánh xạ `versionRows`/`VERSION_KINDS`, không chụp màn hình; không chạy launcher thật, không đụng cổng 8000.
