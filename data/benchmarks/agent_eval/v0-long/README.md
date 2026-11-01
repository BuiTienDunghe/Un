# Agent Eval — bộ bài v0-long

14 bài cho hai ticket của kế hoạch tương lai: **45** (đáp án ở cuối một văn bản dán rất dài) và **44** (kết quả công
cụ của một lượt không vừa cửa sổ). Là bộ riêng: 66 bài của `../v0` không đổi một byte, id không trùng. Định dạng
tệp, khoá `expect` và bộ chấm giống `../v0/README.md`. Dữ liệu hoàn toàn bịa (người, công ty, số tiền, ngày); câu
đáp án viết tay, câu độn sinh từ mẫu bằng `backend/scripts/agent_eval_build_long.py` với hạt giống cố định, nên
chạy lại cho đúng các tệp này (`python -m scripts.agent_eval_build_long --check`).

## Hai loại bài

| Bài | Ticket | Dựng thế nào | Đo gì |
|---|---|---|---|
| end-01..07 | 45 | Đoạn dán 41 000–95 600 ký tự (quá ngưỡng ~36 400 mà N1 đọc nguyên), câu hỏi ở đầu hoặc cuối; mọi mẫu `must_mention` khớp đúng một lần, trong 14 % cuối văn bản (từ 86 %), cách cuối ít nhất 1 200 ký tự (ngoài 600 ký tự cuối của phiếu), và trong phần cuối khi code cắt phần | Lượt đọc từng phần (`agent.long_input`) có tới được cuối văn bản không. Đọc lần lượt từ đoạn 0 mỗi lần 3 đoạn không tới được (đáp án ở đoạn 27 trở đi, mà ba lượt chỉ tới đoạn 8) |
| ctx-01..04 | 44 | Lịch sử 22 000–26 000 ký tự về chuyện khác, một tài liệu 12 đoạn có ba dữ kiện cách nhau từ 4 đoạn: cần ba lần đọc | Có tới trần không: lời nhắc cuối (sau tìm và ba lần đọc) ước 14 400–15 600 token, trần 12 288 |
| ctx-05..07 | 44 | Ba báo giá (8 đoạn mỗi báo giá), đơn giá ở một đoạn và thời hạn giao ở đoạn cách ít nhất 3: sáu lần đọc, lịch sử ~10 000 ký tự | Như trên, nặng hơn (ước ~16 000 token trước khi dọn) |

## Điều kiện đo

- Bài end: bật `AGENT_LONG_INPUT_ENABLED=true` cho nhánh thử, tắt cho đối chứng. Hiệu ứng thấy được khi tắt thì
  trượt (phiếu không có đáp án), khi bật thì đạt nếu model ghi chú đúng phần cuối.
- Bài ctx: `--context-budget` (hoặc `--context-ceiling N`) cho nhánh thử. Khi bật, kết quả đọc cũ bị thay bằng
  ghi chú; nếu model cần một dữ kiện nằm ở kết quả đã bị dọn mà không gọi lại thì sai. Đó là điều bài đo, không
  phải lỗi bài. Đo trên đường ngắn nhất (tìm, các lần đọc song song, trả lời) với ngân sách mặc định
  (`keep_recent` 2): ctx-01..04 dọn 2 trong 4 kết quả (kết quả tìm và lần đọc đầu), ctx-05..07 dọn 3–4 trong 7, nên
  kết quả đọc mà model còn cần có thể đã bị dọn trước vòng trả lời.
- `retrieval.jsonl` là viết tay: `search_documents` trả đoạn xem trước (400 ký tự đầu, không có đáp án), buộc phải
  `read_document`. Bộ chạy cho phép chạy không cần ghi truy xuất.

## Kiểm tra bằng máy (`backend/tests/test_agent_eval_long.py`, không model, không GPU)

Bộ nạp nhận được; tệp trên đĩa khớp bộ sinh; hình học của từng bài (độ dài, vị trí đáp án, đoạn, kích thước đoạn,
lần đọc vừa trần 6 000 ký tự); đường lý tưởng chạy qua `AgentService` thật với router giả vượt trần khi không có
ngân sách và dọn kết quả cũ khi có; bộ chấm cho đạt câu mẫu và trượt câu gần đúng ở cả 14 bài.

## Chưa kiểm

- Chưa chạy model nào trên bộ này: không biết số đạt của mốc. Số đạt đầu tiên phải đo cô lập, cùng ngày, có đối chứng.
- Ước lượng token là của code (`CHARS_PER_TOKEN` 3,3), không phải của tokenizer thật.
- Mẫu số chỉ nhận chữ số ("90 phút", không phải "chín mươi phút"), như v0.
- Văn bản độn lặp mẫu câu, nên model có thể nhận ra chỗ khác thường; đo "đọc dài" bằng văn bản tự nhiên cần dữ liệu thật.

## Giả định về cửa sổ

Bài ctx chạm trần **khi general có `context: 16384`** (đang là `general-v0`, trần N1 = 12 288 token). Ước lượng
của đường ngắn nhất là 14 400–16 200 token; với cửa sổ 32 768 (trần 28 672) không bài nào chạm và bộ không đo gì
cho ticket 44. Muốn ép trần ở máy khác: `--context-ceiling N`. Bài ctx cũng thưởng model gọi các lần đọc song song
trong một vòng; model đọc lần lượt hết `max_steps` (3 vòng) trước khi đủ dữ kiện, đó là tính chất của bài, không
phải lỗi. Khoá `context_ceiling` và `long_input` trong tệp bài chỉ là nhãn, bộ nạp và bộ chấm không đọc.

## Lệnh đo (PowerShell, từ `backend`)

```powershell
# Đối chứng, cả bộ (end tắt long_input, ctx không ngân sách)
python -m scripts.agent_eval --dataset ../data/benchmarks/agent_eval/v0-long --temperature 0 --seed 42 --unload-between-tasks
# Ticket 45: bật đọc theo phần, chỉ 7 bài end
$env:AGENT_LONG_INPUT_ENABLED='true'; python -m scripts.agent_eval --dataset ../data/benchmarks/agent_eval/v0-long --tasks end-01,end-02,end-03,end-04,end-05,end-06,end-07 --temperature 0 --seed 42 --unload-between-tasks; Remove-Item Env:AGENT_LONG_INPUT_ENABLED
# Ticket 44: bật ngân sách ngữ cảnh, chỉ 7 bài ctx
python -m scripts.agent_eval --dataset ../data/benchmarks/agent_eval/v0-long --tasks ctx-01,ctx-02,ctx-03,ctx-04,ctx-05,ctx-06,ctx-07 --context-budget --temperature 0 --seed 42 --unload-between-tasks
```

Theo `.scratch/future-plan/map.md`: so nhánh với đối chứng cùng ngày, cùng phiên bản Ollama.
