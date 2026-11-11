# Đăng ký trước: mốc 2B cùng ngày và bộ đo khớp đường chat

Viết 11/11/2026 bởi claude-fable-5-2, **trước mọi lần chạy**. Sửa lần hai cùng đêm theo bản duyệt của Opus 5.5 (`REVIEW-opus-eval-prep.md`), vẫn trước mọi lần chạy: chưa có con số nào tồn tại khi tệp này được viết hay sửa. Code, test và bộ điều phối dưới đây chưa từng được thực thi. Khi chủ dự án cho phép đo, người chạy ghi mục sổ đo trỏ về tệp này trước khi báo kết quả.

*Ghi thêm sáng 11/11/2026 (phiên điều phối, lúc commit, vẫn trước mọi lần đo):* bước 0 đã chạy và xanh (test, `--plan`; mục 11/11 trong `docs/SO_DO.md`). Hai script chuyển từ `.scratch/harness-research/` sang `backend/scripts/`; chỉ ba dòng lệnh đổi đường dẫn, nội dung đăng ký giữ nguyên. Tệp này vào git cùng commit đó.

## Bản chất

Trước khi sửa cách Ún quyết định dùng công cụ, cần một tấm ảnh chụp "hiện giờ nó làm thế nào", chụp trong cùng một buổi, trên đúng model đang dùng. Tấm ảnh có ba lớp: model tự làm một mình, model trong khung của Ún như bài thi vẫn chạy lâu nay, và model trong khung khi bài thi được cho thêm hai thứ mà một cuộc chat thật luôn có (dòng báo giờ và lời giới thiệu vai của bot Discord). Lớp thứ ba cho biết bao nhiêu lỗi "chào mà cũng đi tra" là lỗi thật của sản phẩm, bao nhiêu chỉ do bài thi thiếu ngữ cảnh. Mọi quyết định sau đó so với tấm ảnh này, không so với số cũ đo trên code và ngày khác.

## Câu hỏi

1. Trên main hiện tại, cùng ngày, 2B chạy trần và chạy trong harness khác nhau bao nhiêu ở ba hạng mục BFCL?
2. Bật hai lựa chọn khớp đường chat thì Agent Eval đổi bao nhiêu bài, bài nào?
3. Trên bộ bài Discord mới, 2B tự gọi công cụ ở bao nhiêu bài không được gọi, khi tắt và khi bật hai lựa chọn đó?

## Các nhánh

| Bộ bài | Trần | Harness, không khớp | Harness, chỉ giờ | Harness, có khớp |
|---|---|---|---|---|
| BFCL v2 simple_python 400 | có | có | **không có** | **không có** |
| BFCL v2 irrelevance 240 | có | có | **không có** | **không có** |
| BFCL v2 multi_turn_base 200 | có | có | **không có** | **không có** |
| Agent Eval v0 (66) | không tồn tại | có | có | có |
| Agent Eval v0-discord-chat (25) | không tồn tại | có | có | có |

Nhánh "có khớp" của BFCL không có vì `backend/scripts/bfcl_run.py` tự dựng tin nhắn và đêm viết tệp này nó là tệp chỉ đọc. Muốn có thì cần thêm vào `bfcl_run.py` một cờ `--clock-note` chèn `clock_note()` trước mỗi lượt người dùng; thay đổi đó **chưa làm**. BFCL không có persona Discord để khớp.

"Có khớp" = `--clock-note --discord-persona` của `scripts.agent_eval`; "chỉ giờ" = `--clock-note`. Nhánh chỉ giờ thêm vào để tách phần của dòng báo giờ khỏi phần của persona; nó chỉ để mô tả, không có luật quyết định riêng. "Có khớp" gần đường chat hơn, không bằng. Những chỗ còn lệch (bản duyệt đã đối chiếu với HEAD `69ca4ad`):

| Chỗ | Sản phẩm | Nhánh có khớp |
|---|---|---|
| Công cụ | Lõi + remember, remind, jokes, ask_user, web (theo cờ) | Lõi + `search_history` |
| Trí nhớ nguồn (mặc định bật) | Có receipt và dòng trí nhớ | Không có |
| Reply target, allowlist guild | Có | Không có |
| Dòng giới thiệu server | Tới 100 thành viên thật | Người có tin trong dữ liệu giả; v0 không có tên server nên dùng tên trung tính "Góc Nhỏ" (ghi trong manifest: `discord_guild_name`) |
| Đồng hồ | Đọc mỗi lượt | Đọc một lần cho cả lần chạy |
| Lấy mẫu | Nhiệt độ 0, không seed | Nhiệt độ 0, seed 42 |

## Điều kiện cố định

| Mục | Giá trị |
|---|---|
| Model | `qwen3.5:2b`; digest ghi vào `run_manifest.json` lúc bắt đầu (08/11 là `324d162be6ca`) |
| Lấy mẫu | nhiệt độ 0, seed 42, ngữ cảnh 16 384, tắt suy nghĩ |
| Cô lập | gỡ và nạp lại model trước **mỗi bài** ở mọi nhánh (`--unload-between-tasks`; nhánh trần tự làm) |
| Cùng ngày | mọi nhánh trong một lần chạy; nhánh xen kẽ trong từng hạng mục |
| Ollama | phiên bản ghi vào `run_manifest.json`, kiểm lại mỗi 15 giây; đổi thì dừng và lần chạy mất hiệu lực |
| Code | một commit, ghi vào `run_manifest.json`; các đường dẫn sản phẩm phải trùng HEAD (xem dưới) |
| GPU | không chia sẻ (`--gpu-shared no`); API, bot, worker tắt |
| Bộ chấm | BFCL: bộ chấm gốc qua `bfcl_score.py`; Agent Eval: `agent-eval-grader-v0.4` |
| Xác minh registry | Không chạy `--probe` (cần stack đang bật), nên manifest của Agent Eval ghi `verified: false`. Đây là mốc đo cùng ngày, **không** phải "mốc đã xác minh" theo nghĩa của `--probe` |

**Cây sạch — điều kiện đã thu hẹp** (quyết định của phiên điều phối, chủ dự án đổi được). Cả repo không thể sạch: `.scratch/` và các thư mục kết quả `kept/` chưa được track. Điều kiện là: mọi tệp, tracked lẫn untracked, dưới `backend/`, `discord_bot/`, `config/` và `data/benchmarks/` trùng HEAD (`config/` hiện không tồn tại ở gốc repo, bộ điều phối bỏ qua đường dẫn không có). `.scratch/` và mọi thứ ngoài bốn đường dẫn đó được bỏ qua. Bộ điều phối tự kiểm lúc bắt đầu; nếu có gì lệch, nó ghi danh sách tệp và băm SHA-256 của `git diff HEAD` vào `<out>/refused-dirty.json` rồi **từ chối chạy**. Hệ quả:

- Mốc chỉ chạy được **sau khi** các sửa review2 đang dở của phiên khác (khoảng 20 tệp dưới `backend/` và `discord_bot/`, gồm `chat_service.py`, `turn_service.py`, `discord_bot/main.py`) đã được test và commit, và sau khi các tệp của lần chuẩn bị này (`backend/scripts/agent_eval.py`, `backend/tests/test_agent_eval.py`, `data/benchmarks/agent_eval/v0-discord-chat/`) được commit. Người viết tệp này không được phép ghi vào git.
- Trường `worktree_dirty` trong manifest của từng lần Agent Eval vẫn xét cả repo nên sẽ ghi `true` vì `.scratch/`. Với mốc này, bằng chứng cây sạch là `run_manifest.json` (`product_paths_clean`) của bộ điều phối, không phải trường đó.

Dòng báo giờ là đồng hồ thật, đọc một lần khi mỗi lần chạy Agent Eval bắt đầu và ghi nguyên văn vào manifest (`clock_note`). Vì vậy hai lần chạy có dòng giờ không gửi cùng một chuỗi byte. Thêm một nguồn lệch: bộ kiểm số của agent coi mọi chữ số trong tin system là "đã thấy", kể cả giờ và ngày, nên một câu trả lời có bị trả về hay không có thể phụ thuộc giờ chạy. Muốn đóng băng giờ thì `agent_service.clock_note` cần nhận tham số `now=None`; thay đổi đó nằm ở tệp chỉ đọc, **chưa làm**.

## Lệnh

Bước 0 chạy trên CPU, không nạp model. Bước 1 mới dùng GPU. Mọi lệnh chạy từ gốc repo trừ khi ghi khác.

**Trước bước 0 — commit**, như mục "Cây sạch" ở trên. Bước 0 chạy được trên cây chưa sạch; bước 1 thì không.

**Bước 0 — kiểm code chưa từng chạy (CPU, PowerShell):**

```
Remove-Item Env:POSTGRES_TEST_URL -ErrorAction SilentlyContinue
$env:CUDA_VISIBLE_DEVICES = ""
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_agent_eval.py tests/test_agent_eval_long.py tests/test_agent_eval_record.py tests/test_bfcl_run.py tests/test_manifest_ollama_version.py -q -rs
..\.venv\Scripts\python.exe -X utf8 -c "from scripts.agent_eval import load_dataset, DATASET_DIR; h=load_dataset(DATASET_DIR).sha256; print(h); assert h=='35b39db48e7ce5600aecdf63d3009ff40629e36f7efe684f875640e23dc40212'"
..\.venv\Scripts\python.exe -X utf8 -c "from pathlib import Path; from scripts.agent_eval import load_dataset; d = load_dataset(Path('../data/benchmarks/agent_eval/v0-discord-chat')); print(d.version, len(d.tasks), d.sha256)"
..\.venv\Scripts\python.exe -X utf8 -c "from scripts.agent_eval import load_dataset, discord_persona_prompt; from pathlib import Path; print(discord_persona_prompt(load_dataset(Path('../data/benchmarks/agent_eval/v0-discord-chat')).guild)[1])"
..\.venv\Scripts\python.exe -X utf8 -m scripts.bfcl_run --dry-run --env-file ..\.env --model qwen3.5:2b
cd ..
.venv\Scripts\python.exe -X utf8 backend\scripts\run_2b_baseline.py data\evaluation\results\2b-baseline-<ngày> --plan
```

Hai dòng đầu gỡ `POSTGRES_TEST_URL` (nếu để, pytest dùng database chung) và ẩn GPU, chỉ trong cửa sổ đó. `-rs` để thấy test nào bị bỏ qua: nếu `test_the_persona_equals_what_the_real_bot_would_send…` bị bỏ qua thì phép so với bot thật chưa được kiểm. Dòng băm v0 xác nhận các tệp v0 không đổi (16 ký tự đầu của băm này có trong 81 manifest Agent Eval đã lưu trên máy). Bộ mới phải in 25 bài. Một lệnh hỏng ở bước 0 thì sửa trước, không sang bước 1. Nếu dòng `discord_persona_prompt` báo không import được `discord_bot.main` thì nhánh "có khớp" không chạy được trên máy đó.

**Bước 1 — đo (GPU), trong một cửa sổ PowerShell mới (không mang biến ẩn GPU của bước 0):**

```
.venv\Scripts\python.exe -X utf8 backend\scripts\run_2b_baseline.py data\evaluation\results\2b-baseline-<ngày>
```

**Bước 2 — đếm bài tự gọi (CPU, sau khi đo):**

```
.venv\Scripts\python.exe -X utf8 backend\scripts\count_self_chosen.py data\evaluation\results\2b-baseline-<ngày>\ae\discord-chat-parity-off data\evaluation\results\2b-baseline-<ngày>\ae\discord-chat-clock-only data\evaluation\results\2b-baseline-<ngày>\ae\discord-chat-parity-on
```

Nếu `scored.json` trỏ một job sang thư mục `-rerun` thì dùng thư mục đó.

Bộ điều phối chạy mười hai job sau theo đúng thứ tự, mỗi job là một trong ba dạng lệnh:

```
# trần (bfcl-venv, cwd = gốc repo)
C:\Users\dungbt06\tools\bfcl-venv\Scripts\python.exe -X utf8 backend\scripts\bfcl_bare.py --model qwen3.5:2b --ids <out>\ids\<hạng mục>.json <out>\bare\<hạng mục>
# harness BFCL (cwd = backend)
..\.venv\Scripts\python.exe -X utf8 -m scripts.bfcl_run --env-file ..\.env --model qwen3.5:2b --ids <out>\ids\<hạng mục>.json --run-id <hạng mục> --gpu-shared no --unload-between-tasks --out <out>\harness
# Agent Eval (cwd = backend); chỉ giờ thêm: --clock-note; có khớp thêm: --clock-note --discord-persona
..\.venv\Scripts\python.exe -X utf8 -m scripts.agent_eval --env-file ..\.env --model qwen3.5:2b --dataset <bộ bài> --temperature 0 --seed 42 --unload-between-tasks --gpu-shared no --out <out>\ae --run-id <nhãn>
# chấm BFCL (bfcl-venv): --model-dir un-harness, hoặc qwen3-5-2b-bare-ollama cho nhánh trần
C:\Users\dungbt06\tools\bfcl-venv\Scripts\python.exe -X utf8 backend\scripts\bfcl_score.py <thư mục job> --model-dir <tên>
```

| # | Job | Bài | Phút |
|---:|---|---:|---:|
| 1 | Agent Eval v0, không khớp | 66 | 6 (đo 08/11) |
| 2 | Agent Eval v0, có khớp | 66 | ~6 |
| 3 | Agent Eval v0, chỉ giờ | 66 | ~6 |
| 4 | Agent Eval v0-discord-chat, có khớp | 25 | ~2,5 |
| 5 | Agent Eval v0-discord-chat, không khớp | 25 | ~2,5 |
| 6 | Agent Eval v0-discord-chat, chỉ giờ | 25 | ~2,5 |
| 7 | trần simple_python | 400 | 23 (đo 08/11) |
| 8 | harness simple_python | 400 | 41 (đo 08/11) |
| 9 | harness irrelevance | 240 | 21 (đo 08/11) |
| 10 | trần irrelevance | 240 | 18 (đo 08/11) |
| 11 | trần multi_turn_base | 200 | 32 (đo 08/11) |
| 12 | harness multi_turn_base | 200 | 39 (đo 08/11) |
| | **Tổng, chưa kể chấm và chạy lại** | | **~200** |

Agent Eval chạy trước vì hai lựa chọn khớp là đoạn code duy nhất chưa từng chạy: nếu hỏng thì lộ trong nửa giờ đầu. Hai job "chỉ giờ" tốn thêm khoảng 9 phút.

Ước cả buổi: khoảng 3,7 giờ GPU nếu không job nào phải chạy lại; một job BFCL chạy lại thêm 18–41 phút.

## Dừng và chạy lại

| Tình huống | Bộ điều phối làm gì | Số liệu |
|---|---|---|
| GPU ≥ 85 °C | Giết job đang chạy, dừng cả lần đo (exit 3) | Thư mục job dở đổi tên `-aborted`, không chấm. Nối lại được nếu qua kiểm lúc bắt đầu (dưới) |
| Không đọc được nhiệt độ GPU ba lần liền | Như trên | Như trên. Nhiệt độ không đọc được không được coi là mát |
| Có tiến trình League | Như trên | Như trên |
| Phiên bản Ollama đổi (một chuỗi phiên bản khác thật) | Như trên, ghi `INVALID.json` | **Lần chạy mất hiệu lực, không nối lại được.** Mọi job đã xong cũng bỏ: mốc phải nằm trên một phiên bản. Bắt đầu thư mục mới |
| Ollama không trả lời bốn lần liền, cách nhau 5 giây | Như dừng vì nóng, ghi "unreachable" | Chưa biết có nối lại được không: có thể là Ollama tự cập nhật. Lần bắt đầu sau quyết định (dưới) |
| Job thiếu bài, hoặc có bài chưa đo được | Ghi `failed.json`, chạy lại **cả job** một lần ở cuối, vào thư mục `<job>-rerun` | Xem "bản nào được chấm" |
| Job hỏng hai lần | Ghi "GAVE UP" | Báo là **chưa đo được**, không tính trượt. Cái giá: một bài lỗi lặp lại (không phải hạ tầng) làm mất cả hạng mục của nhánh đó; khi ấy đọc lỗi của bài trước, chủ dự án quyết có chấm phần còn lại không |
| Job treo quá hạn mỗi bài | Giết, tính là hỏng | Như job hỏng |
| HEAD đổi, hoặc một đường dẫn sản phẩm lệch HEAD, trước hay sau một job | Job đó thành `-aborted`, ghi `INVALID.json`, dừng (exit 3) | **Lần chạy mất hiệu lực, không nối lại được** |
| Lỗi bất ngờ trong một job (không đổi tên được thư mục, bộ chấm vỡ…) | Đổi tên thư mục job thành `-aborted`, dừng cả lần đo (exit 4) | Không chấm job đó; đọc lỗi trước khi bắt đầu lại |

**"Bài chưa đo được" ở cả hai nhánh.** Nhánh harness ghi khoá `error` vào dòng kết quả. Nhánh trần (vòng lặp gốc của BFCL) không có khoá đó: nó ghi `result: "Error during inference: …"` kèm `traceback`. Bộ điều phối nhận cả hai dạng và xử lý như nhau: job có bất kỳ bài nào như vậy đều bị coi là hỏng và chạy lại. Lỗi hạ tầng không được chấm thành trượt ở nhánh nào.

Kiểm trước khi đặt luật này (11/11, chỉ đọc tệp): không tệp kết quả nhánh trần nào của ngày 08/11 (2B, LFM3, 9B) có dòng "Error during inference". Tức là tới nay một lệnh gọi hỏng của model chưa từng hiện ra dưới dạng đó, và số 08/11 của nhánh trần không chứa bài nào thuộc loại này. Nếu lần này một lỗi do chính model gây ra hiện dưới dạng đó, nó sẽ lặp lại y hệt ở lần chạy lại và job thành "chưa đo được"; khi ấy đọc thông báo lỗi và chủ dự án quyết, không tự chấm.

**Code đứng yên trong lúc đo.** Các phiên khác đang sửa chính checkout này, và mỗi job là một tiến trình mới đọc tệp đang có. Trước và sau **mỗi job**, bộ điều phối kiểm lại HEAD và các đường dẫn sản phẩm. Nếu HEAD đổi hoặc có tệp lệch, job vừa chạy thành `-aborted`, lần chạy mất hiệu lực (`INVALID.json`) và không nối lại được. Cách chắc hơn, do chủ dự án chọn: chạy mốc từ một worktree riêng ở đúng commit, để không phiên nào chạm vào được.

**Nối lại.** Mỗi lần bắt đầu trong một thư mục đã có `run_manifest.json`, bộ điều phối đọc lại phiên bản Ollama, digest của model và commit, rồi so với bản ghi. Nếu cả ba giống và đọc được, nó chạy tiếp: job có `done.json` được bỏ qua, job dở chạy lại từ đầu. Nếu **bất kỳ** giá trị nào khác, hoặc không đọc được (không biết thì coi như đã đổi), hoặc thư mục có `INVALID.json`, nó từ chối và báo "THIS RUN CANNOT BE RESUMED": các job đã xong được đo trên thứ khác và không được trộn với job mới. Khi đó bắt đầu thư mục mới và chạy lại toàn bộ. Người chạy còn phải tự giữ một điều bộ điều phối không kiểm: nối lại trong cùng một ngày.

**Bản nào được chấm.** Mỗi job có nhiều nhất hai thư mục hoàn chỉnh: `<job>` và `<job>-rerun`. Luật cố định: nếu `<job>-rerun` có `done.json` thì chấm nó; nếu không thì chấm `<job>` khi nó có `done.json`; nếu không cái nào có thì job chưa đo được. Một job đã có bản được chấm không bao giờ được chạy thêm. `<out>/scored.json` ghi thư mục được chấm của từng job; mọi phân tích đọc theo tệp đó. Thư mục có `failed.json`, `-partial` hay `-aborted` chỉ giữ để đối chiếu.

Ngày 08/11 ba bài của nhánh harness 2B hỏng vì "Cannot connect to Ollama" và bị tính trượt: `simple_python_71`, `multi_turn_base_40`, `multi_turn_base_102`. Cả ba là bài 2B chạy trần làm đạt. Lần này luật "không bài nào chưa đo được" buộc chúng được chạy lại; báo cáo phải nêu riêng kết quả của ba bài này.

Không chạy lại job nào vì điểm của nó. Không đổi bài, bộ chấm, lời dặn hay cấu hình giữa các job.

## So với số cũ

| Điều kiện | Được nói gì |
|---|---|
| Ollama vẫn 0.40.13 và digest vẫn `324d162be6ca` | Nhánh trần phải cho đúng số 08/11; lệch là tín hiệu môi trường đổi, phải tìm trước khi đọc tiếp |
| Ollama hoặc digest khác | Số 08/11 và 10/11 **không** là mốc so; chỉ so các nhánh của hôm đo với nhau |

## Dự đoán (viết trước khi đo)

| Phép đo | Số cũ | Dự đoán |
|---|---:|---|
| Trần simple_python /400 | 287 | 287 nếu Ollama không đổi; 275–299 nếu đổi |
| Harness simple_python /400 | 341 | 335–347 |
| Trần irrelevance /240 | 179 | 179 nếu Ollama không đổi; 170–188 nếu đổi |
| Harness irrelevance /240 | 82 | 74–90 |
| Trần multi_turn_base /200 | 43 | 43 nếu Ollama không đổi; 37–49 nếu đổi |
| Harness multi_turn_base /200 | 29 | 28–34 (hai bài lỗi nay được đo) |
| Agent Eval v0, không khớp /66 | 47 | 45–49 |
| Agent Eval v0, có khớp /66 | chưa có | 46–52; nt-01 hết gọi công cụ |
| Agent Eval v0, chỉ giờ /66 | chưa có | 46–51 |
| Discord-chat, 18 bài không được gọi, không khớp: bài **tự gọi** | chưa có | 3–9 bài |
| Discord-chat, 18 bài không được gọi, có khớp: bài **tự gọi** | chưa có | 1–7 bài |
| Discord-chat, 18 bài không được gọi, chỉ giờ: bài **tự gọi** | chưa có | 1–8 bài |
| Discord-chat, 18 bài: bài chỉ gọi sau khi harness trả về | chưa có | 0–4 bài mỗi nhánh |
| Discord-chat, 4 bài cần gọi, nhờ thẳng | chưa có | 3–4 đạt ở mọi nhánh |
| Discord-chat, 3 bài cần gọi, giọng trò chuyện | chưa có | 1–3 đạt ở mọi nhánh |

Hai dự đoán về hướng: bật khớp không làm bài "không được gọi" kém đi; khe hở irrelevance giữa trần và harness vẫn còn và vẫn lớn hơn khe hở nhiều lượt.

## Cách phân tích (cố định)

- Mỗi cặp nhánh so **từng bài**, McNemar chính xác hai phía; báo số bài chỉ bên này đạt, chỉ bên kia đạt, và p.
- Cặp so: trần / harness ở ba hạng mục BFCL; có khớp / không khớp ở hai bộ Agent Eval. Nhánh chỉ giờ được báo cạnh hai nhánh kia, không có phép thử riêng.
- Bộ Discord-chat báo tách ba nhóm: 18 bài không được gọi, 4 bài cần gọi nhờ thẳng (`hist-d01`, `hist-d02`, `stat-d01`, `doc-d01`), 3 bài cần gọi giọng trò chuyện (`hist-d03..05`).
- Ở 18 bài không được gọi, số chính là **bài tự gọi**, đếm bằng `count_self_chosen.py` (không đếm tay). Định nghĩa, theo thứ tự bước của bài trong `events.jsonl`:
  - **Bước harness trả về**: bước có `kind` là `answer_check` (con số lượt đó chưa thấy), `lookup_check` (nói không biết khi chưa tra; đang bật trong `models.yaml`), `read_on_check`, `promise_check` hoặc `read_rest`.
  - **Lượt tự gọi**: bước `tool_call` do model viết (không có `by_code`, không có `constrained`) mà trước nó **không có** bước harness trả về nào.
  - **Bài tự gọi**: bài có ít nhất một lượt tự gọi.
  - **Bài gọi sau khi harness trả về**: bài không có lượt tự gọi nào nhưng có lượt gọi do model viết đứng sau một bước harness trả về. Báo riêng, tách theo loại bước.
  - Lượt gọi do code tự làm không thuộc loại nào.
  - Lệnh gọi model viết mà Ollama không phân tích được (bước `tool_call_error`) là model đã chọn gọi: tính như một lượt gọi của model theo đúng luật trên, và các bài có nó được liệt kê riêng.
- Mọi ngưỡng về đề xuất 2 dưới đây đặt trên số **bài tự gọi**; số đạt/trượt của bộ chấm vẫn được báo bên cạnh.
- Agent Eval v0 có khớp / không khớp báo tách theo loại bài (documents, history, status, no_tool), không chỉ tổng.
- Nhiều lượt: đếm thêm, trong các bài trần đạt mà harness trượt, bao nhiêu bài chạm trần 3 vòng. Đây là phép đếm mô tả, không phải phép thử nguyên nhân.
- Bảng điểm (`agent_eval_scorecard`) không biết hai lựa chọn khớp; so các nhánh bằng `task_results.jsonl`, và chỉ so khi `clock_note`/`discord_persona_sha256` trong manifest đúng như nhánh đã định.

## Mỗi kết quả nghĩa là gì

Đề xuất 2 = sửa chính sách gọi công cụ cho 2B. Đề xuất 3 = bật giữ kết quả công cụ qua lượt và nới trần vòng. Đây là luật đọc kết quả; chọn làm gì vẫn là việc của chủ dự án. Mỗi bảng phủ mọi kết quả có thể xảy ra của phép đo đó.

**Irrelevance** (chênh ròng = số bài chỉ trần đạt trừ số bài chỉ harness đạt):

| Kết quả | Nghĩa |
|---|---|
| Chênh ròng ≥ 40 và p < 0,001 | Đề xuất 2 có khe hở đo được trên main hôm đo; bước kế là thang chẩn đoán (trần → harness rỗng → thêm luật chống chèn → thêm guide) |
| Chênh ròng < 15 (kể cả âm) hoặc p ≥ 0,05 | Khe hở đã khép vì lý do chưa biết; đề xuất 2 mất lý do chính, phải tìm nguyên nhân khép trước |
| Mọi trường hợp còn lại | Đề xuất 2 còn lý do nhưng yếu hơn số 08/11; giữ thứ hạng, ghi rõ cỡ mới |

**simple_python** (chênh ròng = chỉ harness đạt trừ chỉ trần đạt):

| Kết quả | Nghĩa |
|---|---|
| Chênh ròng ≥ 30 và p < 0,05 | Đánh đổi hai chiều vẫn đúng: mọi biến thể của đề xuất 2 phải chấm trên cả hai hạng mục |
| Chênh ròng 15–29 và p < 0,05 | Đánh đổi còn nhưng nhỏ hơn số 08/11; vẫn chấm biến thể trên cả hai hạng mục, ghi cỡ mới |
| Chênh ròng ≤ −15 và p < 0,05 | Harness nay làm hại cả gọi đơn giản: khác hẳn 08/11, dừng đọc và tìm nguyên nhân trước |
| Mọi trường hợp còn lại (chênh trong ±14, hoặc p ≥ 0,05) | Harness không còn giúp rõ ở gọi đơn giản; đề xuất 2 có thể chọn biến thể chỉ theo irrelevance và chat |

**Discord-chat, số bài tự gọi trong 18 bài không được gọi** (K = nhánh có khớp, O = nhánh không khớp):

| K | O | Nghĩa |
|---|---|---|
| ≥ 4 | bất kỳ | Lỗi có thật trên đường gần chat nhất mà bộ đo dựng được; đề xuất 2 gấp hơn, và cổng "chào hỏi gọi công cụ là loại" phải đổi thành "không kém đối chứng" vì đối chứng đã không sạch |
| 2–3 | bất kỳ | Lỗi có thật nhưng hẹp; đọc từng bài trước khi đặt cổng |
| ≤ 1 | ≥ 4 | Phần lớn lỗi "chào mà gọi công cụ" trong bộ này đến từ bài thi thiếu ngữ cảnh; cổng chặn chat của đề xuất 2 dùng nhánh có khớp làm đối chứng |
| ≤ 1 | 2–3 | Bật khớp có vẻ giúp, nhưng chênh nhiều nhất ba bài, chưa tách được khỏi nhiễu của dòng giờ: **không** kết luận lỗi là do bài thi. Vẫn dùng nhánh có khớp làm đối chứng cho cổng chat, và đọc tay các bài O tự gọi |
| ≤ 1 | ≤ 1 | Bộ này không bắt được lỗi ở 2B; không dùng nó để nói lỗi do bài thi, và cần bài khó hơn trước khi dùng làm cổng |

Nhánh chỉ giờ (G) chỉ để đọc thêm khi K < O: nếu G ≤ K + 1 thì phần giảm đi cùng dòng giờ; nếu G ≥ O − 1 thì nó đi cùng persona; ở giữa thì không tách được. Không quyết định nào dựa vào dòng này.

**Discord-chat, bài gọi sau khi harness trả về** (trong 18 bài, mỗi nhánh):

| Kết quả | Nghĩa |
|---|---|
| ≥ 3 bài ở một nhánh | Chính các bộ kiểm của harness đẩy chat sang gọi công cụ. Tách theo loại: do `answer_check` thì thuộc đề xuất 5 (nguồn gốc con số); do `lookup_check` thì mẫu chữ của bộ kiểm đó bắt nhầm lời trò chuyện, cần xét lại trước mọi sửa lời dặn |
| ≤ 2 bài ở mọi nhánh | Không đổi gì; ghi số |

**Discord-chat, bài cần gọi:**

| Kết quả | Nghĩa |
|---|---|
| Nhờ thẳng < 3/4 ở một nhánh | Bốn bài chốt chặn quá khó hoặc mơ hồ với 2B; đọc tay trước khi dùng bộ này làm cổng |
| Nhờ thẳng ≥ 3/4 ở mọi nhánh, giọng trò chuyện ≤ 1/3 ở mọi nhánh | 2B đã **thiếu** gọi khi lời hỏi không nhờ thẳng. Mọi biến thể của đề xuất 2 làm model bớt gọi phải được chấm trên ba bài này, và không được làm chúng kém đi |
| Nhờ thẳng ≥ 3/4 ở mọi nhánh, giọng trò chuyện ≥ 2/3 ở ít nhất một nhánh | Bảy bài dùng được làm chốt chặn "không được bớt gọi" cho đề xuất 2 |

**Agent Eval v0, có khớp / không khớp:**

| Kết quả | Nghĩa |
|---|---|
| ≥ 5 bài lệch hoặc p < 0,05 | Bộ đo cũ lệch sản phẩm đủ để đổi kết luận; mọi so sánh sau này nên chạy nhánh có khớp (chủ dự án quyết) |
| < 5 bài lệch và p ≥ 0,05 | Giữ nhánh không khớp làm mặc định để so được với số cũ; vẫn báo cả hai |

**Nhiều lượt** (sau khi các bài lỗi được đo):

| Kết quả | Nghĩa |
|---|---|
| Trần hơn harness, p < 0,05 | Đề xuất 3 có khe hở trên 2B; đáng chạy bốn nhánh (3 hoặc 10 vòng × giữ hoặc không giữ) |
| Harness hơn trần, p < 0,05 | Trái với 08/11; đề xuất 3 không có lý do trên 2B, và phải tìm vì sao đổi chiều |
| p ≥ 0,05 | Đề xuất 3 không có bằng chứng trên 2B, chỉ có trên LFM3; xếp sau đề xuất 4 cho tới khi có |

**Mọi hạng mục:** nhánh trần lệch số 08/11 dù Ollama và digest không đổi thì dừng đọc: môi trường khác theo cách chưa ghi được; tìm nguyên nhân trước mọi kết luận.

## Giới hạn

- Bộ Discord-chat do dự án tự viết (25 bài, bịa hoàn toàn): là bài hồi quy, không phải bằng chứng chất lượng. Người viết đã đọc các báo cáo 08–10/11 về 9B và 2B; bài được viết theo ý định sản phẩm, nhưng không thể cam đoan không bị ảnh hưởng.
- 18 bài là mẫu nhỏ: chênh 2–3 bài giữa hai nhánh không phân biệt được với nhiễu của dòng báo giờ. Ba bài giọng trò chuyện càng nhỏ: chỉ là chốt chặn, không phải thước đo.
- So có khớp / không khớp trên v0 bị lẫn một yếu tố: đồng hồ thật sẽ muộn hơn nhiều tuần so với ngày trong dữ liệu giả của v0 (`guild.now` 20/10, `checked_at` của trạng thái hệ thống). Bài lịch sử và trạng thái có thể đổi vì model thấy dữ liệu "cũ", không vì bộ đo khớp hơn. Vì vậy phải đọc tách theo loại bài, và không gộp bài history/status vào kết luận về lợi ích của dòng báo giờ. Bộ Discord-chat không có đáp án phụ thuộc ngày nên không dính yếu tố này.
- Nhiệt độ 0 nên không đo độ ổn định qua nhiều lần chạy.
- BFCL là tiếng Anh; phần tiếng Việt chỉ có Agent Eval.
- Giới hạn 100 tên thành viên trong dòng giới thiệu server được chép từ cấu hình bot (`discord_bot/main.py`), có thể lệch nếu bot đổi.
- Không đo tốc độ: mỗi bài đều nạp lại model.
- Import bot để lấy persona bật log mức INFO, nên log của nhánh có khớp dài hơn; không ảnh hưởng kết quả.
