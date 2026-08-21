# Phân lane hai máy — nhẹ vs nặng

Dự án chạy trên hai máy: một **máy nhẹ** (daily driver, dùng hằng ngày, GPU yếu) và
một **máy mạnh** (dùng ít hơn, để dành việc nặng). Tài liệu này quy định việc nào
chạy ở máy nào, và cách một phiên Claude Code **tự biết mình đang ở máy nào** để
nhận đúng phần việc.

Cơ chế này là hệ quả trực tiếp của bất biến *ngân sách inference cố định* (plan §1):
máy nhẹ không gánh nổi model sinh chạy nhiều lượt, nên việc nào cần model sinh phải
dồn sang máy mạnh — còn lại làm ở đâu cũng được, ưu tiên máy nhẹ vì đó là nơi ngồi
nhiều nhất.

## Câu hỏi thử duy nhất

> **Bước này có phải gọi model SINH (generation) hoặc chạy một vòng re-index / thí
> nghiệm nặng không?**

- **KHÔNG → lane NHẸ** — chạy máy nào cũng được, mặc định làm ngay trên máy nhẹ.
- **CÓ → lane NẶNG** — để dành máy mạnh (hoặc GPU cloud với việc train).

Chỉ một câu đó. Không cần bảng phân loại thuộc lòng — cứ hỏi câu này cho từng bước.

## Hai lane, ví dụ cụ thể

| Lane NHẸ (máy nhẹ / daily) | Lane NẶNG (máy mạnh) |
| --- | --- |
| Viết code + logic, unit test | Đo answer/faithfulness bằng model sinh |
| Xây harness, dataset, corpus bẫy | P4-2 contextual retrieval (sinh context mỗi chunk) |
| Eval **retrieval-only** (embedding 0.6b) | P4-3 reranker (warmup + rerank toàn bộ) |
| Guard/self-check **không-LLM** (D3a phần build) | Re-index toàn corpus, thí nghiệm P4 |
| Viết tài liệu, sửa plan, dọn nợ | Agent nhiều bước (D3c), digest nền chạy thật |
| Chạy CI, đọc kết quả gate | Ghi baseline **full** (có model sinh); D2 distillation (cloud/GPU) |

**Mẫu hình thường gặp — một mục chẻ đôi:** phần *xây* (author harness, guard, dataset)
là NHẸ; phần *đo* (chạy qua model sinh để lấy số) là NẶNG. Làm phần nhẹ trên máy nhẹ,
để lại một handoff sạch cho máy mạnh chỉ chạy phần đo. D3a và D5 đều theo mẫu này.

## Máy tự nhận diện — file `.machine-role`

Mỗi máy có một file `.machine-role` ở gốc repo (đã `.gitignore`, **không** đồng bộ qua
git — mỗi máy tự đặt một lần). Nội dung đúng một từ:

```
light
```

hoặc

```
heavy
```

Đặt một lần cho mỗi máy:

```bash
# trên máy nhẹ (daily driver)
echo light > .machine-role
# trên máy mạnh
echo heavy > .machine-role
```

| Máy | hostname | Dấu hiệu | `.machine-role` |
| --- | --- | --- | --- |
| Nhẹ (daily) | `hehehhe` | GTX 1650 Ti, Ryzen 5 4600H, 15GB | `light` |
| Mạnh | `PC-dungbt` | RTX 5060 Ti 16GB VRAM, Ryzen 7 7700 (16 luồng), 31GB RAM, Win 11 Pro | `heavy` (đặt 21/08/2026) |
| Cloud (Claude Code web) | `vm` (container phù du) | 4 vCPU, 15GB, **không GPU**, proxy chặn tải model (registry.ollama.ai/huggingface.co 403) → không chạy được model sinh lẫn embedding thật | `light` — chỉ lane nhẹ; số đo model thật lấy qua job CI `retrieval-eval` |

## Cấu hình khác nhau theo máy — override qua `.env`

`models.yaml` là file dùng chung (versioned), nên tính năng nào **tốn tài nguyên theo
máy** (model sinh lúc index, cross-encoder lúc hỏi, gói GPU tùy chọn) mà máy nhẹ không
kham nổi thì đè theo máy bằng `.env` (không commit), không sửa `models.yaml`. Launcher
`run-local-ai-core.bat` tự ghim `RAG_RERANKER_ENABLED=false` khi máy thiếu extra
`[rerank]` — quyết định theo máy được ghi rõ trong `.env` thay vì API từ chối khởi động:

| Biến `.env` | Máy nhẹ | Máy mạnh | Ý nghĩa |
| --- | --- | --- | --- |
| `RAG_CONTEXTUAL_RETRIEVAL_ENABLED` | `false` | *(không đặt → theo models.yaml = true)* | P4-2: sinh 1 lời gọi model/chunk lúc index. Máy nhẹ tắt để upload vẫn nhanh; đánh đổi: tài liệu index ở máy nhẹ không có context (vẫn tìm được kiểu trần, re-index ở máy mạnh là có) |
| `RAG_RERANKER_ENABLED` | `false` **hoặc** cài extra (xem dưới) | *(không đặt → theo models.yaml = true)* | P4-3: cross-encoder chấm lại 15 ứng viên **mỗi câu hỏi**. Không thêm lời gọi model sinh nào, nhưng thêm ~35ms/câu trên GPU và **~990ms/câu trên CPU** |

Log khởi động ghi rõ nguồn quyết định (`event=chunk_context_config` và
`event=reranker_config`, `source=env|models.yaml`).

### Máy nhẹ cần làm gì với P4-3

Reranker cần gói tùy chọn, và **bản mặc định trên PyPI là CPU-only** — bật cờ mà
dùng bản đó thì mỗi câu hỏi đắt thêm gần một giây. Hai lựa chọn:

```bash
# (a) Không cài gì — ghim tắt trong .env. Chất lượng về mức P4-2, tốc độ giữ nguyên.
echo RAG_RERANKER_ENABLED=false >> .env
```

```bash
# (b) Cài kèm bản CUDA (chỉ đáng làm nếu máy có GPU NVIDIA)
pip install -e ".[rerank]"
pip install --index-url https://download.pytorch.org/whl/cu128 "torch==2.9.1+cu128"
```

Bật cờ mà **không** cài extra thì API **từ chối khởi động** với
`RerankerUnavailableError` kèm đúng lệnh cần chạy — cố ý fail lúc dựng server
chứ không phải lúc người dùng hỏi. GTX 1650 Ti của máy nhẹ chạy được cross-encoder
này (4GB VRAM là dư), nhưng chưa ai đo trên đó; số trong `p4_progress.md` là của
RTX 5060 Ti.

## Một phiên Claude Code tự route thế nào

Đầu mỗi phiên làm việc, đọc `.machine-role`:

- File ghi **`light`** và việc được giao thuộc lane NẶNG → **dừng và báo**: "Việc này
  cần model sinh / re-index, để dành máy mạnh. Trên máy này tôi làm được phần NHẸ
  (xây harness/guard/test) rồi để handoff." Không tự chạy phần nặng trên máy yếu.
- File ghi **`heavy`** → làm được cả hai lane; ưu tiên vét các phần NẶNG đang chờ.
- Không có file → hỏi người dùng máy này là `light` hay `heavy` rồi tạo file.

Quy tắc này để trong prompt mỗi phiên (xem mẫu ở dưới) là đủ; không cần tự động hóa
thêm.

## Phân lane các mục Track D / P4 hiện tại

| Mục | Phần NHẸ (máy nhẹ làm ngay) | Phần NẶNG (để máy mạnh) |
| --- | --- | --- |
| D1 eval | ✅ đã xong (hạ tầng + baseline retrieval-only) | — (baseline full nếu cần, sau) |
| D3a self-check | Build guard bám-nguồn + unit test + field báo cáo | Đo faithfulness trên 82 câu (cần model sinh) |
| D5 red-team | Corpus tài liệu bẫy + harness + logic chấm | Chạy tấn công thật (agent sinh phản hồi) |
| D4 LLMOps | Hầu hết (chuẩn hóa trace, versioning prompt) | — |
| P4-2/P4-3/P4-4 | — | Toàn bộ (sinh context / rerank / re-index) |
| P4-5 chunk viz | Phần lớn (UI đọc chunk có sẵn) | — |
| D2 distillation | Chuẩn bị/ lọc dataset | Train (GPU cloud free) |
| D3c multi-step | — (gác tới khi có D2 + máy mạnh) | Toàn bộ |
