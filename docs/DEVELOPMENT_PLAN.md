# Kế hoạch phát triển tổng thể — Local AI Core

**Phiên bản:** 1.0 · **Ngày:** 15/08/2026 · **Trạng thái:** Đang hiệu lực
**Thay thế:** các định hướng rải rác trong README và `discord_memory_workflow_plan_v5_final.md` (phần roadmap)

---

## 1. Tầm nhìn & định vị

> **Local AI Core là "AI workspace cục bộ" cho cá nhân và nhóm nhỏ: mọi dữ liệu ở trên máy của bạn, mọi câu trả lời có nguồn kiểm chứng được, vận hành bằng một cú click.**

So với các sản phẩm cùng phân khúc (Open WebUI, AnythingLLM, LibreChat), khác biệt chúng ta chọn để giữ và đào sâu:

1. **Tiếng Việt là công dân hạng nhất** — BM25 với pyvi, bộ eval tiếng Việt riêng, UI thuần Việt. Không dự án lớn nào làm tốt điều này.
2. **Citation-grounded triệt để** — câu trả lời tài liệu luôn có nguồn theo trang/đoạn; version tài liệu bất biến (Postgres là source of truth duy nhất).
3. **Hai kênh, một agent** — Web và Discord dùng chung backend, tiến tới chung một bộ nhớ.
4. **Vận hành tối giản** — một máy Windows + Docker + Ollama; không dịch vụ cloud bắt buộc.

### Nguyên tắc bất biến (không thương lượng khi thêm tính năng)

- PostgreSQL là nguồn dữ liệu chuẩn duy nhất; Qdrant chỉ là chỉ mục.
- Không transaction DB nào ôm qua lời gọi model.
- Migration chỉ additive; version tài liệu cũ sống tới khi version mới thành công.
- Mọi thay đổi chất lượng RAG phải qua bộ eval trước khi thành mặc định.
- Tính năng mới không phá đường "một cú click" (`run-local-ai-core.bat`).

---

## 2. Hiện trạng — đánh giá có số liệu (08/2026)

### Điểm mạnh đã kiểm chứng

| Hạng mục | Bằng chứng |
| --- | --- |
| Chất lượng RAG | Baseline đo ngày 14/08: **hybrid pass 100%, recall@5 100%, MRR 0.933** trên bộ 47 câu tiếng Việt (dense: 97.9% / MRR 0.810 → hybrid là mặc định có căn cứ) |
| Độ bền dữ liệu | Versioned ingestion + SHA-256 dedup + transactional outbox + lease/heartbeat worker |
| Discord pipeline | FIFO durable per-session, idempotent delivery, speaker attribution, đã bật persistent sessions |
| UI/UX | App chat hiện đại + dashboard quản trị, đã qua 2 vòng review đối kháng (17 lỗi xác nhận đã sửa) |
| Kiểm thử | 178 test backend + 45 test bot + bộ integration RQ; eval harness tự động |

### Khoảng trống chính (xếp theo độ đau)

| # | Khoảng trống | Hệ quả |
| --- | --- | --- |
| G1 | **Không có xác thực** | Ai trong LAN cũng xóa được dữ liệu; chặn đường mở cho nhóm |
| G2 | **Trí nhớ hai hệ rời** (web `/memory` thủ công · Discord pipeline dry-run) | "Agent có trí nhớ" mới chỉ tồn tại trên giấy |
| G3 | **Discord chưa dùng được tài liệu** (bot chỉ gọi `/chat`) | Nửa giá trị RAG không đến được kênh chat chính |
| G4 | **Citation không lưu vào lịch sử** | Mở lại hội thoại là mất nguồn — đứt cam kết kiểm chứng |
| G5 | **Câu hỏi nối tiếp không được viết lại** trước retrieval | RAG hụt hơi trong hội thoại thật |
| G6 | **Không CI** | Chất lượng phụ thuộc kỷ luật tay; test Postgres ít khi được chạy |
| G7 | Eval mới 1 tài liệu (đã bão hòa ở 100%) | Không đo được tiến bộ tiếp theo |
| G8 | BM25 in-process (RAM + rebuild theo process) | Trần khả năng mở rộng corpus |

---

## 3. Đối chiếu thị trường — học ai, học gì, bỏ gì

Khảo sát 15/08/2026 trên các dự án mã nguồn mở uy tín nhất phân khúc:

| Dự án | Stars | Điều đáng học nhất cho chúng ta |
| --- | --- | --- |
| [Open WebUI](https://github.com/open-webui/open-webui) | ~148.8k | **RBAC + user groups** làm chuẩn mực admin; hybrid search (BM25+vector) mặc định — xác nhận hướng ta đã đi; **model evaluation arena** trong admin; hệ plugin Pipes/Filters/Tools |
| [RAGFlow](https://github.com/infiniflow/ragflow) | ~88.3k | **Chunking giải thích được** (template + visualization cho người duyệt); **traceable citations**; fused re-ranking |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | ~54k | UX "document-first workspace" — người không kỹ thuật dùng được ngay |
| [LibreChat](https://github.com/danny-avila/LibreChat) | ~42k | **Agents + MCP + tool use**; fork/branch hội thoại; resumable streams |
| [Onyx (Danswer)](https://github.com/onyx-dot-app/onyx) | ~13k | Connectors nguồn dữ liệu doanh nghiệp; trợ lý theo team |

**Kỹ thuật RAG đáng áp dụng nhất:** [Contextual Retrieval của Anthropic](https://www.anthropic.com/engineering/contextual-retrieval) — prepend ngữ cảnh tài liệu vào từng chunk trước khi embed/index: giảm 49% retrieval failure, **giảm 67% khi kết hợp reranking**; khuyến nghị luôn đi đôi contextual embedding + contextual BM25. Với hệ local, chi phí sinh context chỉ là thời gian index (chấp nhận được), không tốn tiền API.

**Những thứ cố tình KHÔNG theo** (giữ định vị tối giản):
- Hỗ trợ 9 vector DB / đa provider phức tạp kiểu Open WebUI — ta giữ Qdrant + Ollama (+ Gemini/DeepSeek đã có làm tùy chọn).
- Code interpreter sandbox đa ngôn ngữ kiểu LibreChat — ngoài trọng tâm.
- Connector SaaS kiểu Onyx — dữ liệu ta là file cục bộ, đúng định vị riêng tư.

---

## 4. Lộ trình theo phase

> Mỗi phase **tự ship được** và có tiêu chí nghiệm thu đo được. Ước lượng theo buổi làm việc (~3h). Không phase nào phá nguyên tắc bất biến ở mục 1.

### P0 — Nền móng tin cậy *(1–2 tuần · mở khóa mọi thứ sau)*

| ID | Hạng mục | Tiêu chí nghiệm thu | Ước lượng |
| --- | --- | --- | --- |
| P0-1 ✅ | **CI GitHub Actions**: pytest (kèm Postgres+Redis service container), compileall, chạy trên PR + main | Badge xanh; test Postgres chạy mỗi commit thay vì "khi nhớ ra" | 2 buổi |
| P0-2 | **Xác thực lớp 1**: API key qua header cho mọi endpoint ghi/xóa (endpoint đọc công khai trong LAN tùy config); bot dùng luồng JWT có sẵn khi nâng cấp lớp 2 | Không có key → 401 ở endpoint ghi; UI tự đính key từ Settings | 2–3 buổi |
| P0-3 | **Lưu citation vào lịch sử**: bảng `message_sources` (message_id, chunk_id, filename, page, excerpt, score) | Mở lại hội thoại RAG vẫn thấy đủ nguồn như lúc trả lời | 2 buổi |
| P0-4 | **Backup tự động**: task định kỳ gọi `backup_postgres.py` + xoay vòng; hướng dẫn restore drill | Bản backup mới nhất < 24h tuổi; restore thử thành công 1 lần/quý | 1 buổi |
| P0-5 | `pyproject.toml` (requires-python, metadata) + CHANGELOG.md khởi tạo | `pip install -e .` hoạt động; phiên bản đầu tag `v1.0.0` | 1 buổi |
| P0-6 | **Đồng bộ model ↔ migration**: `alembic check` hiện báo drift thật (một loạt index khai báo trên model nhưng chưa migration nào tạo, vài lệch `nullable`/unique-constraint). Cần một migration bù rồi bật lại bước `alembic check` trong CI | `alembic check` xanh và chạy trong CI mỗi commit | 1–2 buổi |

### P1 — Một agent, hai kênh *(2–3 tuần · giá trị người dùng lớn nhất)*

| ID | Hạng mục | Tiêu chí nghiệm thu | Ước lượng |
| --- | --- | --- | --- |
| P1-1 | **Discord RAG**: lệnh `/hoi` (câu hỏi + chọn tài liệu hoặc all) gọi `/rag/chat`, trả lời kèm nguồn rút gọn | Hỏi tài liệu trong Discord nhận câu trả lời có `[Source]` + tên file/trang | 2–3 buổi |
| P1-2 | **Condense-question**: trước retrieval, dùng model general viết lại câu hỏi nối tiếp thành câu độc lập (bỏ qua khi là lượt đầu) | Bộ eval hội thoại mới (10 cặp câu nối tiếp) đạt ≥ 80% recall | 2 buổi |
| P1-3 | **Bật memory extractor Discord** (`DISCORD_MEMORY_EXTRACTOR_ENABLED=true`) ở chế độ đề xuất | Candidate xuất hiện trong DB với proposal; không memory nào tự áp dụng | 1 buổi |
| P1-4 | **Duyệt memory trên dashboard**: bảng candidate (nội dung đề xuất, nguồn, độ tin) + nút duyệt/từ chối | Admin duyệt được từ UI; audit trail đầy đủ | 3 buổi |
| P1-5 | **Hợp nhất kho memory**: memory duyệt từ Discord đổ vào kho `/memory` (Qdrant) mà web chat dùng | Bật "Ghi nhớ" ở web → trợ lý dùng được điều học từ Discord | 2 buổi |

### P2 — Đa người dùng & quản trị *(3–4 tuần · khi mở cho nhóm)*

| ID | Hạng mục | Tiêu chí nghiệm thu | Ước lượng |
| --- | --- | --- | --- |
| P2-1 | **Tài khoản + RBAC tối giản** (admin/member — học mô hình Open WebUI, không sao chép độ phức tạp): JWT + refresh theo chuẩn FastAPI production | Hội thoại thuộc user; member không xóa được tài liệu chung | 5–6 buổi |
| P2-2 | **Điều khiển bot từ dashboard**: start/stop/status (thay control panel Tkinter) | Nút hoạt động; trạng thái đúng với thực tế process | 3 buổi |
| P2-3 | **Biểu đồ thời gian trên dashboard**: câu hỏi/ngày, latency p50/p95, lỗi — từ `request_logs` có sẵn | 2 chart 14 ngày, cập nhật cùng auto-refresh | 2 buổi |
| P2-4 | **OCR console UI** (backend API đã đủ từ lâu) | Upload → theo dõi job → xem kết quả → promote thành tài liệu, không cần curl | 3–4 buổi |

### P3 — RAG nâng cao, có đo lường *(chạy nền liên tục, mỗi mục một thí nghiệm)*

| ID | Hạng mục | Giả thuyết cần kiểm chứng bằng eval | Ước lượng |
| --- | --- | --- | --- |
| P3-1 | **Mở rộng bộ eval**: 3–5 tài liệu thật + 30 câu đa tài liệu + eval trong CI (gate: không tụt quá 2 điểm) | Baseline mới thay bộ 1-tài-liệu đã bão hòa | 2 buổi |
| P3-2 | **Contextual retrieval** (Anthropic): sinh 50–100 token ngữ cảnh/chunk lúc index bằng model local | MRR đa tài liệu tăng ≥ 5 điểm (kỳ vọng theo paper: −49% failure) | 3 buổi |
| P3-3 | **Bật reranker** (đã có sẵn `RerankerService`, warmup lúc startup) | Kết hợp P3-2 hướng tới mức −67% failure của paper | 1–2 buổi |
| P3-4 | **Postgres FTS thay BM25 in-process** (tsvector + GIN + unaccent) | Không tụt chất lượng; RAM không tăng theo corpus; nhất quán đa process | 3–4 buổi |
| P3-5 | **Chunk visualization** (học RAGFlow): xem chunk của tài liệu trong UI, đánh dấu chunk kém | Người dùng tự chẩn đoán được "tại sao trả lời sai" | 3 buổi |

### P4 — Năng lực agent mở rộng *(tương lai, chọn lọc theo nhu cầu thật)*

- **Tool use / function calling** qua Ollama (thời tiết nội bộ? tra cứu ERP xưởng?) — chỉ khi có use case cụ thể.
- **Vision attachments**: đính ảnh vào chat (nền `vision_chat` đã có; endpoint `/vision/chat` đang 501).
- **Web search opt-in** cho câu hỏi ngoài tài liệu (học Open WebUI, mặc định tắt vì định vị riêng tư).
- **MCP client** nếu hệ sinh thái nội bộ cần nối tool ngoài (LibreChat là tham chiếu tốt).
- Fork/branch hội thoại; resumable streams đa tab (LibreChat).

---

## 5. Kiến trúc đích (không đổi xương sống, chỉ bồi)

```
Web UI ─┐                                  ┌─ Qdrant (vector index)
        ├─ FastAPI ── services ── Postgres ┤
Discord ─┘    │                            └─ FTS (tsvector, P3-4)
              ├─ Auth layer (P0-2 → P2-1)
              ├─ Memory hub (P1-5): một kho, hai kênh đọc/ghi
              └─ RQ workers (ocr/index/memory) + outbox + cleanup
```

- **API versioning**: giữ endpoint hiện tại; breaking change đầu tiên (P2-1) mở namespace `/api/v1/`, alias cũ giữ 1 minor version.
- **Cấu trúc code**: giữ `routers → services → repositories/stores` (đã khớp chuẩn FastAPI production); không thêm framework.
- **Plugin-lite**: chưa làm hệ plugin tổng quát (Pipes kiểu Open WebUI) cho tới khi có ≥ 2 nhu cầu mở rộng thật — tránh over-engineering.

## 6. Chất lượng & quy trình

| Mảng | Chuẩn áp dụng |
| --- | --- |
| Test | 3 tầng (unit service / integration repository / endpoint) — đã có nền; mục tiêu coverage 80% cho `services/` khi CI chạy (P0-1) |
| Eval | Là **gate chất lượng RAG**: mọi thay đổi retrieval/prompt phải chạy eval trước-sau, ghi kết quả vào PR |
| Review | Thay đổi lớn qua review đối kháng (đã chứng minh hiệu quả: 17 lỗi thật bị bắt trong 2 vòng) |
| Release | Tag `vX.Y.Z` + CHANGELOG (P0-5); mỗi phase đóng = một minor version |
| Migration | Additive-only; mỗi migration có downgrade; restore drill mỗi quý |

## 7. KPI theo dõi (đo trên dashboard + eval)

| KPI | Hiện tại | Mục tiêu cuối P1 | Mục tiêu cuối P3 |
| --- | --- | --- | --- |
| Answer pass rate (eval) | 1.00 (1 tài liệu — bão hòa) | ≥ 0.90 bộ đa tài liệu mới | ≥ 0.95 |
| MRR | 0.933 | ≥ 0.85 (bộ mới, khó hơn) | ≥ 0.90 |
| Câu hỏi nối tiếp đạt (bộ eval hội thoại) | chưa đo | ≥ 0.80 | ≥ 0.90 |
| Kênh Discord dùng tài liệu | 0% | có, kèm nguồn | — |
| Memory được duyệt đưa vào dùng | 0 | pipeline chạy end-to-end | tự đề xuất chất lượng ≥ 70% được duyệt |
| CI | không có | xanh trên main | eval gate trong CI |

## 8. Rủi ro & đối sách

| Rủi ro | Mức | Đối sách |
| --- | --- | --- |
| Model 9B chạy nhiều trên CPU (máy phụ) → latency ~45s/câu RAG | Chấp nhận (quyết định 15/08) | Kiến trúc không giả định latency thấp; nếu chuyển máy chính: chỉ cần đổi `models.yaml` |
| Một người bảo trì | Cao | P0 dồn vào automation (CI, backup, eval gate) trước tính năng |
| Scope creep từ cảm hứng dự án lớn | Trung | Mục "cố tình KHÔNG theo" ở §3; mỗi mục P4 cần use case thật mới làm |
| Bảo mật khi mở LAN cho nhóm | Cao nếu bỏ qua | P0-2 là điều kiện tiên quyết của P2; không mở nhóm trước khi có auth |
| Chất lượng extractor memory (model 2B) | Trung | Chế độ đề xuất + người duyệt (P1-3/P1-4); benchmark 150 case đã có sẵn để đo |

## 9. Việc bắt đầu ngay (tuần tới)

1. ~~**P0-1 CI**~~ — ✅ xong (`.github/workflows/ci.yml`, 3 job: static / backend+PostgreSQL+Redis / bot trên Windows).
2. **P0-3 lưu citation** — nhỏ, người dùng thấy ngay, gỡ G4.
3. **P0-2 API key** — mở khóa mọi kế hoạch nhóm.
4. **P0-6 đồng bộ migration** — phát sinh khi làm P0-1; nhỏ nhưng chặn việc bật `alembic check` làm cửa hồi quy schema.

---

## Nguồn tham khảo

- [Open WebUI — GitHub](https://github.com/open-webui/open-webui) (~148.8k★): RBAC, hybrid search, evaluation arena, plugin system
- [RAGFlow — GitHub](https://github.com/infiniflow/ragflow) (~88.3k★): explainable chunking, traceable citations
- [AnythingLLM — GitHub](https://github.com/Mintplex-Labs/anything-llm) (~54k★): document-first UX
- [LibreChat — GitHub](https://github.com/danny-avila/LibreChat) (~42k★): agents/MCP, conversation branching
- [Anthropic — Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval): −49% retrieval failure, −67% kèm reranking
- [Searching for Best Practices in RAG (arXiv 2407.01219)](https://arxiv.org/pdf/2407.01219)
- Chuẩn FastAPI production 2026: cấu trúc domain, JWT + refresh, test 3 tầng ([tổng hợp](https://dev.to/datanestdigital/production-ready-fastapi-project-structure-2026-guide-b1g))
- So sánh phân khúc: [OpenWebUI vs LibreChat vs Onyx](https://onyx.app/insights/openwebui-vs-librechat-vs-onyx), [AnythingLLM vs Open WebUI vs LibreChat](https://runaihome.com/blog/anythingllm-vs-open-webui-vs-librechat-2026/)
