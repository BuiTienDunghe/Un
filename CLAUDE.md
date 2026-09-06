# CLAUDE.md

Hướng dẫn cho coding agent làm việc trong repo này.

`local-ai-core` — hệ AI cục bộ: backend FastAPI, Discord bot, pipeline ingestion và
retrieval. Xem `README.md` để biết cách chạy, `docs/current_architecture.md` để biết
kiến trúc hiện tại.

## Cách viết khi trả lời chủ dự án

Viết tiếng Việt. Ngắn, và **có lập luận** — đây là hai yêu cầu riêng biệt, thiếu cái
nào cũng hỏng.

**Có lập luận nghĩa là:** mỗi khẳng định phải kèm lý do và bằng chứng, và mỗi phương án
phải kèm hệ quả. Không phải là chốt thay chủ dự án.

**Quyết định là của chủ dự án, không phải của agent.** Khi có nhiều cách làm, hãy liệt
kê **tất cả các cách khả thi**, mỗi cách một mục có **ưu điểm và nhược điểm rõ ràng**,
kèm chi phí và rủi ro. Được phép nói mình nghiêng về cách nào và vì sao — nhưng phải nói
đó là ý kiến, và phải trình bày các cách còn lại đủ công bằng để chủ dự án chọn khác.
Không tự chốt rồi chỉ trình bày một đường.

**Mỗi báo cáo phải có một đoạn giải thích bản chất bằng ngôn ngữ thông thường.** Không
thuật ngữ trần, không tên thư viện, không con số. Đoạn đó trả lời "thật ra chuyện này là
gì" theo cách một người ngoài ngành đọc cũng hiểu. Đặt nó **trước** phần số liệu, không
phải sau.

**Ngắn nghĩa là:** bỏ bớt nội dung, không phải nén chữ. Một ý một câu. Cắt mọi câu chỉ
nhắc lại điều vừa nói, mọi lời rào đón, mọi đoạn giải thích thứ người đọc đã biết. Nếu
một mục không đổi được quyết định của người đọc thì xoá nó.

**Số liệu vào bảng, không vào câu văn.** Một bảng ba cột hơn ba đoạn văn. Chỉ đưa con số
nào thay đổi kết luận.

**Vẫn giữ:** giải thích bằng lời logic thay vì thuật ngữ trần, nêu rõ điều kiện đo của
mỗi con số, và nói thẳng khi một phép đo sai hoặc chưa làm. Sự trung thực về giới hạn
không phải là dài dòng — nhưng nó phải nằm trong một câu, không phải một đoạn.

**Không làm:** mở đầu bằng tóm tắt lại câu hỏi; kết bằng lời đề nghị giúp thêm; lặp lại
kết luận ở cuối bài; dùng ba câu để nói điều một câu nói được.

## Agent skills

Repo dùng bộ [engineering skills của Matt Pocock](https://github.com/mattpocock/skills),
vendored tại `.claude/skills/` — xem `.claude/skills/README.md` để biết đã cài những gì
và cách cập nhật.

### Issue tracker

Issue và spec là file markdown trong `.scratch/<feature-slug>/`, không dùng GitHub Issues.
Xem `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: một `CONTEXT.md` ở gốc repo, ADR trong `docs/adr/`. Cả hai được tạo lười
bởi `/domain-modeling` khi thực sự cần, nên đừng coi việc chúng chưa tồn tại là thiếu sót.
Xem `docs/agents/domain.md`.
