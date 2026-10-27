# Ticket 24 — đo harness Ún bằng bài BFCL (thiết kế, chưa có runner)

Nhân viên 3, 28/10/2026. Bản clone BFCL: `C:\Users\dungbt06\tools\gorilla-6ea5797`, commit `6ea5797`, không sửa gì.
Cách A của chủ dự án: không tái lập Qwen3-8B; chỉ so trước/sau trên cùng thước.

## Thật ra chuyện này là gì

BFCL là một bộ bài công khai về gọi công cụ: người hỏi một việc, model phải gọi đúng hàm với đúng tham số, có
khi qua nhiều lượt hội thoại liên tiếp. Bộ chạy có sẵn của BFCL gửi bài thẳng cho model, nên nó đo model.
Muốn đo harness của Ún thì bài phải đi qua Ún. Có hai chỗ để cắm: chỉ thay cách Ún trình bày công cụ và đọc lệnh
gọi (rẻ, nhưng không đo được phần lớn kiểm soát của harness), hoặc cho mỗi lượt BFCL chạy thành một lượt agent
Ún thật (đắt hơn, nhưng đo được ngân sách thời gian, giới hạn vòng, mã lỗi, cắt kết quả). Điểm ra chỉ dùng để so
hai phiên bản harness với nhau, không đặt cạnh bảng xếp hạng.

## 1. Venv — bị chặn ở bước cài

| Bước | Kết quả |
|---|---|
| sentence-transformers và faiss có import lười không | **Có.** Chỉ `func_source_code/memory_vector.py:13-14` import chúng. Backend được nạp bằng `importlib` theo lớp mà bài cần (`multi_turn_utils.py:2`, `constants/executable_backend_config.py:28-30`), nên chỉ hạng mục `memory_vector` cần |
| Tạo `C:\Users\dungbt06\tools\bfcl-venv` (Python 3.11.9) | xong, mới chỉ có pip |
| Giải phụ thuộc (dry-run), bỏ sentence-transformers và faiss-cpu | 119 gói, **94,5 MB**, không có torch hay transformers. Lớn nhất: botocore 16,2; numpy 1.26.4 15,8; pandas 9,9; pillow 7,3; qwen-agent 7,1 MB |
| Cài | **bộ phân loại quyền từ chối** lệnh `pip install` ("code từ nguồn ngoài"). Không cài gì, không thử đường vòng |

Vì sao cần đủ 119 gói dù chỉ chấm: `bfcl evaluate` và cả `ast_checker` import `constants/model_config.py`, mà
tệp này import handler của mọi model ở đầu tệp (`model_config.py:4-70`), kéo theo SDK của mọi hãng (openai,
anthropic, cohere, mistralai, google-genai, qwen-agent, writer, boto3). Cài `bfcl_eval` với `--no-deps` từ một
bản chép của clone, để pip không ghi `egg-info` vào clone.

Cần chủ dự án: cho phép lệnh cài, hoặc tự chạy hai lệnh sau. Danh sách gói ở `ticket24-bfcl-reqs.txt` (cùng thư
mục), bằng `pyproject.toml` bỏ sentence-transformers và faiss-cpu.

```bash
C:/Users/dungbt06/tools/bfcl-venv/Scripts/python.exe -m pip install -r C:/Users/dungbt06/local-ai-core/.scratch/foundation-and-agent-eval/ticket24-bfcl-reqs.txt
```

```bash
C:/Users/dungbt06/tools/bfcl-venv/Scripts/python.exe -m pip install --no-deps <bản chép của berkeley-function-call-leaderboard>
```

## 2. Xác minh (dòng code ở `berkeley-function-call-leaderboard/bfcl_eval/`)

**(a) Tệp kết quả mà bộ chấm đọc.**
- Mỗi dòng có `id` và `result` (`eval_checker/eval_runner.py:559-560`); `inference_log` thì tuỳ chọn (`:577`).
- Với multi-turn, `result` là danh sách theo **lượt**, mỗi lượt là danh sách theo **bước**. Mỗi bước được giải mã
  bằng `handler.decode_execute(item, has_tool_call_tag=False)` thành danh sách chuỗi lệnh gọi; bước rỗng hay
  không giải mã được thì bị bỏ qua, không làm trượt (`eval_runner.py:218-232`).
- Số lượt phải bằng số lượt của đáp án, nếu không thì bài trượt với `multi_turn:force_terminated`
  (`eval_runner.py:200-210`).
- Bộ chấm chạy lại từng bước đã giải mã từ `initial_config`, trên một instance mới, rồi so trạng thái và kết quả
  thực thi với đáp án (`eval_checker/multi_turn_eval/multi_turn_checker.py:28-55`, `state_checker :162`,
  `response_checker :197`).
- Hệ quả cho runner: mọi lệnh agent gọi lúc chạy phải được ghi đúng thứ tự theo lượt và bước, dưới dạng mà
  `decode_execute` của handler đọc được. Trạng thái lúc chạy phải đến từ `execute_multi_turn_func_call`, thì lần
  chạy lại lúc chấm mới trùng.
- Vị trí tệp: `result_dir/<thư mục model>/**/BFCL_v4_<hạng mục>_result.json` (`eval_runner.py:770-803`,
  `constants/eval_config.py:36`). `RESULT_PATH` = `BFCL_PROJECT_ROOT/result`, mặc định nằm cạnh gói
  (`eval_config.py:20-22`), và bị tạo ngay lúc import (`:41`). Phải đặt `BFCL_PROJECT_ROOT` ra ngoài clone.

**(b) `bfcl evaluate` có bắt tên model phải nằm trong `model_config.py` không. Có.**
- `--model X` mà X không có trong `MODEL_CONFIG_MAPPING` thì báo `ValueError` (`eval_runner.py:844-845`).
- Không truyền `--model` thì `get_handler` tra `MODEL_CONFIG_MAPPING[model_name]` (`eval_runner.py:25-26`) và báo
  `KeyError`. Phần dựng bảng điểm cũng tra lại (`eval_runner_helper.py:198, 301`).
- Cách khỏi sửa clone: một script nhỏ trong bfcl-venv thêm một `ModelConfig` (handler của Ún) vào dict lúc chạy,
  rồi gọi hàm chấm của BFCL trong cùng tiến trình.

**(c) `multi_turn_utils` và `func_source_code` có import được trong venv của Ún không.**
- `multi_turn_utils.py` chỉ dùng thư viện chuẩn, cộng `executable_backend_config` (tệp hằng số, không import gì).
  Các `__init__.py` trên đường đi đều rỗng, nên không kéo theo `model_config`.
- Các backend:

| Backend | Phụ thuộc ngoài thư viện chuẩn | Venv của Ún |
|---|---|---|
| gorilla_file_system, message, posting, ticket, trading_bot, travel_booking, vehicle_control, long_context | không (gorilla_file_system có `import subprocess` nhưng không dùng) | được |
| math_api | mpmath | có (1.3.0) |
| memory_kv, memory_rec_sum | overrides, rank_bm25 | thiếu overrides |
| memory_vector | sentence_transformers, faiss, numpy | không (bỏ) |
| web_search | requests, bs4, html2text, serpapi; cần mạng | không (bỏ) |

- Kết luận **từ đọc code, chưa chạy thử**: các hạng mục trong tập con dưới đây import được trong venv Ún. Cần
  đặt `sys.dont_write_bytecode` để không ghi `__pycache__` vào clone. numpy của Ún là 2.4.6 so với bản BFCL ghim
  1.26.4; điều này không ảnh hưởng các backend trên.

**(d) Số bài mỗi hạng mục** (`bfcl_eval/data/`, đếm dòng):

| Hạng mục | Bài | Hạng mục | Bài |
|---|---:|---|---:|
| simple_python | 400 | live_simple | 258 |
| simple_java | 100 | live_multiple | 1 053 |
| simple_javascript | 50 | live_parallel | 16 |
| multiple | 200 | live_parallel_multiple | 24 |
| parallel | 200 | live_irrelevance | 884 |
| parallel_multiple | 200 | live_relevance | 16 |
| irrelevance | 240 | memory | 155 |
| multi_turn_base | 200 | web_search | 100 |
| multi_turn_miss_func | 200 | format_sensitivity | 10 |
| multi_turn_miss_param | 200 | multi_turn_long_context | 200 |

- Multi-turn base: trung bình 3,67 lượt (tối đa 7), 5,7 lệnh gọi đúng mỗi bài. Miss_func và miss_param: 4,67 lượt.
- Đề xuất tập con cố định, 33 bài. Seed 20261028; mỗi hạng mục rút `random.Random("bfcl-ticket24:20261028:<hạng
  mục>").sample(id theo thứ tự số, k)`. Tệp viết theo định dạng `test_case_ids_to_generate.json` của BFCL:

```json
{"simple_python": ["simple_python_6", "simple_python_14", "simple_python_40", "simple_python_90", "simple_python_119",
   "simple_python_138", "simple_python_219", "simple_python_231", "simple_python_315", "simple_python_335"],
 "multiple": ["multiple_10", "multiple_35", "multiple_51", "multiple_67", "multiple_69", "multiple_129", "multiple_170", "multiple_188"],
 "irrelevance": ["irrelevance_0", "irrelevance_70", "irrelevance_151", "irrelevance_155", "irrelevance_195", "irrelevance_199", "irrelevance_228"],
 "multi_turn_base": ["multi_turn_base_77", "multi_turn_base_113", "multi_turn_base_128", "multi_turn_base_153", "multi_turn_base_180"],
 "multi_turn_miss_func": ["multi_turn_miss_func_143", "multi_turn_miss_func_157", "multi_turn_miss_func_174"]}
```

- Thời gian **ước tính, chưa đo** (tối nay không được chạy GPU): một lượt agent Ún khoảng 4 s (bảng điểm v0.3,
  trung vị). 25 bài một lượt ≈ 1,7 phút. 8 bài multi-turn × 3,7 lượt × ~10 s ≈ 5 phút. Tổng khoảng 7 phút.
- Chọn hạng mục theo thứ harness quyết định: multi_turn_base (nhiều bước, trạng thái), miss_func (hàm thiếu, rồi
  được thêm lại giữa chừng), simple/multiple (cách trình bày và đọc lệnh gọi), irrelevance (biết không gọi).
- Bỏ: memory và web_search (cần sentence-transformers hay mạng), java/javascript (không phải công cụ thật của Ún),
  live_* (lớn và thường dài).
- Cỡ mẫu nhỏ: 1 bài multi-turn bằng 20 điểm % của hạng mục đó. Chỉ là thước thăm dò.

## 3. Chỗ cắm nào đo được kiểm soát nào

- **Handler**: kế thừa `BaseHandler`, ghi đè `_query_FC`, `_compile_tools`, `_parse_query_response_FC`,
  `_add_execution_results_FC`, `decode_*`. Vòng lặp của BFCL là `inference_multi_turn_FC`, bị khoá `@final`
  (`model_handler/base_handler.py:94`), tối đa 20 bước mỗi lượt (`constants/default_prompts.py:1`).
- **Vòng lặp**: ghi đè `inference()`, vốn không bị khoá (`base_handler.py:68`). Mỗi lượt BFCL thành một lần
  `AgentService.run()`.

| Kiểm soát của harness | Chỗ cắm handler | Chỗ cắm vòng lặp |
|---|---|---|
| Cách trình bày công cụ cho model | đo được | đo được |
| Cách đọc lệnh gọi từ phản hồi của model | đo được | đo được |
| Giới hạn 3 vòng công cụ mỗi lượt | không (BFCL cho 20 bước) | đo được |
| Ngân sách 90 s cả lượt, chừa 20 s cho câu trả lời | không | đo được |
| Lỗi công cụ có mã (`BAD_ARGUMENTS`, `UNKNOWN_TOOL`, `TOOL_FAILED`) | chỉ phần định dạng, nếu tự chép cách Ún bọc lỗi vào `_add_execution_results_FC` | đo được (`_run_tool` thật) |
| Cắt kết quả theo mục (`omitted`), trần 2 400 ký tự | chỉ phần định dạng, như trên | đo được |
| Bọc kết quả chống chèn lệnh (injection defense) | chỉ phần định dạng | đo được |
| Kiểm số liệu của câu trả lời, thử lại một lần (#2) | không | đo được, nhưng BFCL chỉ chấm lệnh gọi và trạng thái, không chấm câu chữ |
| Đọc theo handle (`read_document`, #1) | không | không: bài BFCL không có tài liệu |
| Trace rút gọn, bảng điểm (ticket 23) | không | đo được (các bước của `run()`) |
| **Chi phí xây** | khoảng 200 dòng: một handler gọi Ollama qua `ModelRouter`, đăng ký model lúc chạy. Chạy trong bfcl-venv, nên phải import được `app` của Ún từ đó, hoặc chép lại phần định dạng | khoảng 500 dòng. Chuyển tài liệu hàm BFCL thành schema công cụ; vòng theo lượt có thêm lại hàm thiếu (miss_func) giữa chừng; giữ instance qua các lượt; ghi kết quả theo định dạng (a). Chạy trong venv Ún, rồi chấm bằng script đăng ký model ở bfcl-venv. Thêm một chỗ nối trong `agent_service`: hôm nay `REGISTRY` và `AGENT_TOOLS` là biến module đọc lúc import (`agent_service.py:671-682`), `run()` dùng thẳng `AGENT_TOOLS`. Cần một tham số `registry=` (khoảng 20 dòng, có test), hoặc vá biến module lúc chạy (không đổi app, nhưng dễ vỡ vì `TOOL_NAMES` và `_DECLARED` cũng suy ra từ đó) |

Câu hỏi đi kèm cách cắm vòng lặp: trong lượt BFCL, ba công cụ của Ún (tra tài liệu, lịch sử, trạng thái) ở lại
hay bị thay hẳn bằng hàm của bài? Ở lại thì đo đúng harness như đang ship, nhưng có thêm nhiễu. Thay hẳn thì sạch
hơn, nhưng lời dặn của agent vẫn nói về ba công cụ không còn ở đó.

## 4. Những thứ phải ghim để so trước/sau

| Ghim | Giá trị đề xuất | Lý do |
|---|---|---|
| Model | `qwen3.5:9b`, ghi digest từ `/api/tags` vào manifest | đổi lượng tử hay bản thì số không so được |
| Nhiệt độ | **0**, seed 42 | Ở 0 và lạnh, Agent Eval lặp lại từng chữ (ba lần: 19:43, 22:31, 22:57), nên mọi chênh là do code. BFCL mặc định 0,001; trên Ollama thì coi như bằng 0. 0,4 là mức Ún ship, nhưng phải chạy ít nhất 3 lần mỗi bên, tức gấp ba thời gian GPU |
| Song song | `--num-threads 1` | một GPU, một Ollama; tránh xen kẽ làm lệch thứ tự và độ trễ |
| Trạng thái model | gỡ `qwen3.5:9b` trước mỗi lần chạy; ghi `ollama_loaded_at_start` | luật đo của ticket 10 |
| GPU dùng chung | khai báo `--gpu-shared` | luật nhường GPU; độ trễ chỉ so khi giống nhau |
| Bài | 5 hạng mục, 33 id, seed 20261028, tệp id được track | |
| Phiên bản | BFCL `6ea5797`, commit của Ún, sha256 của tệp id, phiên bản Ollama | |
| Chấm | bộ chấm của BFCL ở `6ea5797`, gọi qua script đăng ký model | khỏi sửa clone |

## 5. Dự đoán, ghi trước mọi lần chạy

- Ý của điều phối: ngân sách 90 s sẽ chặn các bài nhiều bước.
- Ước tính của Nhân viên 3, khác: giới hạn chặn trước sẽ là **3 vòng công cụ mỗi lượt**, không phải 90 s. Một
  lượt BFCL cần trung bình 5,7 / 3,67 ≈ 1,6 lệnh gọi, nhưng có lượt cần 3–5 lệnh, cộng các lệnh dò như `ls`,
  `cd`. Mỗi vòng model khoảng 3–5 s, nên một lượt hiếm khi gần 90 s.
- Kiểm bằng: số `stop_reason` = `max_steps` so với số `turn_budget`/`turn_budget_exhausted` ở các bài multi-turn
  (bảng điểm ticket 23 đọc được trực tiếp, nếu chọn cách cắm vòng lặp).
- Với cách cắm handler thì không kiểm được, vì hai giới hạn đó không chạy.

## 6. Cần chủ dự án chọn

1. Chỗ cắm: handler (rẻ, chỉ đo trình bày và đọc lệnh gọi) hay vòng lặp (đo cả harness, cần chỗ nối `registry=`
   trong `agent_service`).
2. Cho phép lệnh `pip install` vào `bfcl-venv` (94,5 MB, không có torch), hoặc tự chạy hai lệnh ở mục 1.
3. Nhiệt độ: 0 (đề xuất) hay 0,4 × 3 lần.
4. Nếu cắm vòng lặp: công cụ của Ún ở lại hay bị thay trong lượt BFCL.
