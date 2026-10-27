# Khảo sát benchmark uy tín cho harness của Ún (agent phụ, nguồn chính thống, 28/10/2026)

Bản tóm tắt của báo cáo agent phụ (ticket 24). Mọi số dưới đây là số đã công bố đọc từ paper / leaderboard / repo
chính thức ngày 28/10; mục đánh dấu ⚠ là chưa kiểm được hoặc phụ thuộc phiên bản. Runtime/chi phí trên GPU 16 GB
**không benchmark nào công bố** — mọi ước lượng là suy luận.

## Điều quyết định

- Với agent và gọi công cụ, benchmark có điểm công bố đáng tin cho model 7–14B **chỉ có tiếng Anh**; tốt nhất là
  **BFCL**. Tiếng Việt: một benchmark gọi hàm (**MASSIVE-Agents**, vi-VN) và một benchmark truy xuất luật
  (**DRILL 2025**, VLSP). Không có benchmark tiếng Việt cho agent nhiều bước, ngữ cảnh dài có số đọc được, hay RAG
  trung thực.
- **Không leaderboard nào liệt kê qwen3.5:9b.** Số duy nhất là thẻ model của Qwen (tự báo: BFCL-V4 66,1; TAU2
  79,1; LongBench v2 55,2; không nêu cấu hình, khuyên 32k token đầu ra — vượt 16k/90 s của Ún).
- Vì vậy "tái lập trước" gồm hai bước: (1) kéo về Ollama một model mà leaderboard có liệt kê (qwen3:8b,
  qwen2.5:7b, llama3.1:8b) và khớp số đã công bố → chứng nhận đường đo của mình; (2) chạy qwen3.5:9b và so, ghi
  rõ mốc so là số tự báo. Lượng tử 4-bit mặc định của Ollama và template chat có thể làm lệch so với bản bf16/vLLM
  — ghi chênh như một phép đo, không coi là hỏng.

## Danh sách ngắn (xếp hạng là suy luận của agent phụ)

| # | Benchmark | Đo gì của harness | Mốc tái lập | Lưu ý |
|---|---|---|---|---|
| 1 | **BFCL V4**, phần chạy offline (non-live, live, multi-turn, relevance) — ICML 2025, Apache-2.0 | gọi hàm một lượt, nhiều lượt, biết khi nào không gọi | Qwen3-8B (FC): non-live 87,58; live 80,53; multi-turn 41,75 (gorilla.cs.berkeley.edu/leaderboard.html) | phần web-search cần DuckDuckGo thật → không tái lập được điểm tổng; Ollama không được tài liệu hoá, chạy qua endpoint kiểu OpenAI |
| 2 | **RAG nhiều bước** HotpotQA / MuSiQue / Bamboogle theo thiết lập Search-R1 / FlashRAG | cả vòng tra–suy luận, đúng thứ harness Ún làm | Qwen2.5-7B, top-3: RAG EM HotpotQA 0,299, MuSiQue 0,058; Search-o1 (agentic) HotpotQA 0,187 (Search-R1 Bảng 2, arXiv v5) | phải dùng đúng retriever của họ (E5 base, Wikipedia-2018) — kích thước index chưa kiểm ⚠ |
| 3 | **RULER** 4k/8k/16k (Apache-2.0) | đọc/truy vết/tổng hợp trong ngữ cảnh dài | Llama-3.1-8B: 95,5 / 93,8 / 91,6 | góc harness: model trần ở 32k/64k so với harness đọc theo trang ở cùng độ dài (suy luận) |
| 4 | **MASSIVE-Agents vi-VN** (EMNLP 2025 Findings, CC-BY-4.0) | gọi hàm tiếng Việt | Llama-3.1-8B vi-VN AST 9,57 (paper Bảng 5) | prompt > 12k token, sát 16k; tác giả chạy trên Bedrock |
| 5 | **DRILL 2025** (VLSP 2025) | truy xuất văn bản luật tiếng Việt (thành phần) | BM25 F2 0,3365 (private) / 0,2771 (public) | quyền lấy dữ liệu chưa kiểm ⚠ |

## Tránh

τ²-bench, SEATauBench, GAIA, FRAMES, CRAG, StableToolBench (cần judge API / user giả bằng model lớn / web thật → thay
bằng local là mất so sánh); AgentBench (Docker + Freebase online, mốc cũ); NexusRaven, API-Bank (cũ, NexusRaven do
vendor chạy); LongBench v2 trực tiếp, InfiniteBench, LOFT (cần ngữ cảnh ≫ 16k); VMLU, SEA-HELM, VN-MTEB (đo kiến thức
model / embedding, không đo harness — chỉ dùng kiểm tra model).

## Cờ ⚠

BFCL: trang ghi cập nhật 2026-04-12, một đoạn tìm kiếm ghi 2025-12-16. LongBench v2: paper Bảng 2 ghi Qwen2.5-7B
27,0, bảng xếp hạng ghi 30,0/35,6. Search-R1 chưa có hội nghị trên arXiv. MASSIVE-Agents: cột đọc từ tiêu đề trang 14;
không đọc được ngôn ngữ/số dòng trên HF (viewer hỏng).
