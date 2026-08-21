# D1 — Bộ eval retrieval đa tài liệu

Gỡ khoảng trống G7 (bộ eval 1 tài liệu đã bão hòa 100%): bộ eval mới chạy trên
**toàn corpus, không lọc tài liệu** — chọn đúng tài liệu giữa các ứng viên chính
là năng lực được đo. Đây là thước đo cho mọi thí nghiệm P4 và các mục Track D
sau này (plan §4, §9b).

## Thành phần

| Phần | Vị trí |
| --- | --- |
| Corpus 5 tài liệu thật (snapshot bất biến) | `data/evaluation/fixtures/multidoc/` |
| Bộ câu hỏi (JSONL, tiếng Việt, nhóm `single` + `cross`) | `data/evaluation/rag_multidoc_eval.jsonl` |
| Baseline được ghi nhận | `data/evaluation/rag_multidoc_baseline.json` |
| Endpoint retrieval-only | `POST /rag/search` (đúng nguồn mà `/rag/chat` sẽ trích, không gọi model sinh) |
| Harness | `backend/scripts/evaluate_rag.py --multidoc-dataset …` |
| Gate CI | job `retrieval-eval` trong `.github/workflows/ci.yml` |

Corpus là **snapshot**: sửa tài liệu gốc trong `docs/` không làm trôi điểm eval.
Muốn đổi corpus thì thay fixture + sinh lại bộ câu hỏi + đo lại baseline (một
thay đổi có chủ đích, thấy được trong diff).

## Cách chấm

Mỗi câu hỏi khai báo `expected_docs` (tên fixture chứa bằng chứng) và
`expected_source_terms` (chuỗi **nguyên văn** từ tài liệu, cùng nằm trong một
đoạn). Chuỗi phải nằm trong **phần thân** văn bản: parser tách heading khỏi
thân khi chunk, nên chuỗi lấy từ tiêu đề sẽ không bao giờ khớp — mọi câu mới
thêm cần đối chiếu với nội dung chunk thực (bảng `document_chunks`), không chỉ
với file gốc. Một kết quả retrieval **trúng** khi chunk trả về thuộc đúng tài liệu
mong đợi **và** chứa nguyên văn tất cả các chuỗi. Số liệu:

- `recall_at_k` — tỷ lệ câu có ít nhất một chunk trúng trong top-5
- `mrr` — 1/hạng của chunk trúng đầu tiên, trung bình
- `doc_hit_rate` — tỷ lệ câu mà chunk hạng 1 thuộc đúng tài liệu
- nhóm `cross` được tách riêng trong `by_group` (câu bắc cầu/nhiễu giữa tài liệu)

Chế độ `--retrieval-only` chỉ cần **model embedding** (`qwen3-embedding:0.6b`),
không cần model sinh — đúng bất biến ngân sách inference và chạy được trong CI
không GPU. Bỏ cờ này để đo thêm `answer_pass_rate` bằng model sinh thật
(chỉ nên đo trên máy đích, cấu hình model cuối cùng).

## Ghi baseline (một lần, trên cấu hình model cuối — plan §9a.6)

```powershell
# API + Ollama đang chạy (launcher). Từ backend/:
python -m scripts.evaluate_rag --multidoc-dataset ..\data\evaluation\rag_multidoc_eval.jsonl `
  --retrieval-only `
  --write-baseline ..\data\evaluation\rag_multidoc_baseline.json
# rồi commit file baseline.
```

Baseline ghi kèm tên model embedding; gate từ chối so sánh nếu model hiện tại
khác model lúc ghi (đổi model là phải đo lại — đúng plan §9a.6).

## Gate trong CI

Job `retrieval-eval` dựng Postgres + Redis + Qdrant + Ollama (chỉ pull model
embedding 0.6b, có cache), chạy API thật, bootstrap corpus rồi chấm bộ câu hỏi:

- **Chưa có baseline** trong repo → chỉ báo cáo số liệu, job xanh (để hạ tầng
  eval vào được main trước khi máy đích ghi baseline).
- **Có baseline** → tụt quá `--tolerance` (mặc định 0.02, "không tụt quá 2
  điểm" — plan P4-1) ở `recall_at_k` hoặc `mrr` là job đỏ.

## Quan hệ với bộ eval cũ

Bộ 47 câu một-tài-liệu (`rag_eval.jsonl`) và bộ hội thoại condense
(`rag_conversation_eval.jsonl`) giữ nguyên, vẫn chạy được như trước — chúng đo
đường `/rag/chat` đầy đủ trên một tài liệu. Bộ multidoc bổ sung chiều đo mới,
không thay thế.
