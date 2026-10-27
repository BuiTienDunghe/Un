# 13 — Chuẩn bị đóng gói e5-large cho B đầy đủ (chỉ code, không tải, không GPU)

Status: đã gộp vào main (27/10), fable 5.1 duyệt
Type: task
Blocked by: — (chạy thật thuộc ticket 09, sau Bước 6 của nhánh 0)

## Vì sao

`m3-preregistration.md`, mục "B đầy đủ", đòi hai thứ commit **trước** khi tải hay đo e5: script đóng
gói ghim sha, và tuỳ chọn tiền tố hai phía cho `run_mteb.py`. Viết chúng lúc GPU đang bận cho nhánh 0
không làm lệch phép đo nào. Chủ dự án đã duyệt tải e5-large + llama.cpp **khi tới bước cần**; ticket
này không tải gì.

## Việc

1. `backend/scripts/build_embedding_model.py` theo mẫu `build_ocr_model.py`: nhận đường dẫn checkpoint
   HF đã tải và `convert_hf_to_gguf.py` của llama.cpp; ghim sha nguồn HF và sha GGUF đích; viết
   `data/models/embedding/embedding-e5l-v1/Modelfile`; in lệnh `ollama create`. Có `--dry-run`.
   Test với file giả, không cần mạng hay Ollama.
2. `training/common/run_mteb.py`: thêm tuỳ chọn tiền tố query/passage hai phía (e5 cần `query: ` /
   `passage: `), giữ nguyên hành vi mặc định (chỉ dẫn kiểu Qwen). Test rằng mặc định không đổi.
3. Ghi vào Comments: lệnh tải chính xác (repo HF, revision, kích thước ước lượng), để lúc tới bước chỉ
   cần chủ dự án xác nhận lại.

## Không làm

Không tải model, tokenizer hay llama.cpp; không gọi Ollama; không sửa `model_versions.yaml` (record
`embedding-e5l-v1` đã có).

## Comments

### 27/10 — Nhân viên của Ún 1: đã làm (không tải gì, không gọi Ollama)

Bản chất: hai việc chuẩn bị để lúc được phép tải e5 thì chỉ còn bấm chạy, không còn chỗ nào phải
đoán. Script đóng gói ghi lại chính xác nó được dựng từ đâu ở lần đầu, và từ chối mọi lần sau
nếu đầu vào khác đi. Công cụ đo mteb thì giờ gửi được tiền tố cho cả hai phía, như e5 cần. Lúc làm
tôi phát hiện chính mteb sẽ lặng lẽ bỏ qua tiền tố nếu chỉ khai báo nó theo cách thông thường,
tức lại đúng kiểu bẫy 05/09.

**1. `backend/scripts/build_embedding_model.py`.** Nhận checkpoint HF đã tải cùng
`convert_hf_to_gguf.py`, đổi sang Q8_0, viết Modelfile, in lệnh `ollama create` (không chạy). Có
`--dry-run`. Ghim hai đầu theo kiểu "ghi lần đầu, kiểm từ lần sau", giống
`training/reranker/export_checkpoint.py --record` và `export.json`:
- Lần đầu (registry chưa có `gguf_sha256`): băm từng file nguồn, đổi, băm GGUF, rồi ghi
  `export.json` cạnh Modelfile. File này được theo dõi nhờ luật `!data/models/**/export.json` đã
  có. Nó ghi repo, revision, sha từng file nguồn, commit llama.cpp, interpreter, outtype và sha GGUF.
  Script in sẵn dòng `gguf_sha256:` để dán vào `model_versions.yaml`.
- Mỗi lần sau: nguồn, commit converter hay outtype khác `export.json` thì bị từ chối trước khi đổi.
  GGUF khác sha đã ghim thì bị xoá, và không ghi gì khác.
- Không commit Modelfile lúc này, vì chưa có lần dựng nào sinh ra nó. `--check` vẫn xanh: bản ứng
  viên chưa active nên được phép thiếu Modelfile.

**2. `training/common/run_mteb.py`.** Thêm `--query-prefix` / `--passage-prefix`, loại trừ với
`--instruction`. Đo trên mteb 2.20.5 trong `.venv-eval`, với HTTP giả:

| Cách gọi wrapper | Phía query nhận | Phía passage nhận |
|---|---|---|
| chỉ `prompt_dict` | `xin chao` (**không có tiền tố**) | `xin chao` |
| `prompt_dict` + gán `model_prompts` (cách đã làm) | `query: xin chao` | `passage: xin chao` |
| `--instruction` (giữ nguyên) | `Instruct: Retrieve text based on user query.\nQuery: xin chao` | `xin chao` |

Nguyên nhân: wrapper chọn tên prompt qua `self.model_prompts` (`abs_encoder.py:57`, mặc định `None`)
rồi mới tra `prompts_dict`, mà nó không bao giờ tự gán `model_prompts`. Mặc định không đổi: kwargs
và các khoá trong `summary.json` giữ y như cũ; hai khoá tiền tố chỉ xuất hiện khi được dùng.

| Kiểm | Kết quả |
|---|---|
| `tests/test_build_embedding_model.py` (converter giả, checkpoint giả) | 6 xanh: dry-run không ghi gì; thiếu file thì từ chối; lần đầu ghi đủ; khớp ghim thì qua; lệch ghim thì không để lại gì; nguồn đổi thì từ chối trước khi đổi; không bao giờ chạy `ollama` |
| `tests/test_run_mteb_prefixes.py`, 3 bài không cần mteb (chạy được ở CI) | xanh: kwargs mặc định và `--instruction` khớp từng giá trị; tiền tố đặt cả `prompt_dict` lẫn `model_prompts`; không cho trộn hai quy ước |
| Bài thứ 4 (mteb thật, HTTP giả), chạy trong `.venv-eval` | xanh; bỏ dòng gán `model_prompts` thì đỏ. `.venv-eval` không có pytest và tôi không cài vào đó, nên chạy thân bài test qua một runner tạm |
| Bộ test ở gốc / backend (đóng gói + registry) | 74 xanh, 1 skip (bài mteb, vì `.venv` không có mteb) / 109 xanh |
| `model_registry --check` | 0 lỗi, 4 cảnh báo; `model_versions.yaml` không đổi |

**3. Lệnh tải, để chủ dự án xác nhận lúc tới bước.** Revision và tag dưới đây chưa điền; xác nhận
lúc tải, không đoán.

```bat
REM checkpoint: chỉ các file converter đọc, để không kéo cả pytorch_model.bin / onnx/
.venv-eval\Scripts\huggingface-cli.exe download intfloat/multilingual-e5-large --revision <commit, xác nhận lúc tải> --local-dir C:\Users\dungbt06\hf\multilingual-e5-large --include config.json model.safetensors sentencepiece.bpe.model tokenizer.json tokenizer_config.json special_tokens_map.json modules.json "1_Pooling/config.json"

REM converter
git clone https://github.com/ggml-org/llama.cpp C:\Users\dungbt06\llama.cpp
git -C C:\Users\dungbt06\llama.cpp checkout <tag, xác nhận lúc tải>

REM đóng gói (dry-run trước)
cd backend
..\.venv\Scripts\python.exe -m scripts.build_embedding_model --checkpoint C:\Users\dungbt06\hf\multilingual-e5-large --converter C:\Users\dungbt06\llama.cpp\convert_hf_to_gguf.py --python <interpreter> --revision <commit> --dry-run
```

Kích thước: ticket 09 ước ~1,1 GB fp16; con số thật đọc trên trang HF lúc tải.

Còn mở, cần xác nhận lúc tải:
- Không venv nào có `sentencepiece` (kiểm 27/10: cả `.venv`, `.venv-eval` lẫn `.venv-train` đều
  thiếu). Converter có lẽ cần nó để đọc `sentencepiece.bpe.model`, nên sẽ phải cài thêm vào venv
  chạy converter. Việc này cần chủ dự án duyệt.
- Interpreter chạy converter (`--python`): `.venv-eval` hoặc `.venv` đều có torch và transformers.
  Converter dùng `gguf-py` đi kèm llama.cpp, không dùng `gguf==0.19.0` của `.venv`.
- Danh sách `SOURCE_FILES` viết theo cấu trúc repo, chưa đối chiếu với nhánh XLM-RoBERTa của
  `convert_hf_to_gguf.py` (cần tải llama.cpp mới đối chiếu được).
- Có cần gọi API metadata của HF (chỉ JSON, không tải model) để điền revision ngay bây giờ không?
- 27/10 (fable, khi duyệt): gợi ý không chặn — `converter_commit` là None (tải zip thay vì clone)
  thì nên từ chối ghi lần đầu, thay vì so None == None. Làm khi tới bước tải thật.
