# 20 — Khả năng cơ bản cho agent: đọc dài, kiểm câu trả lời, báo tiến độ

Status: chờ chủ dự án chọn phạm vi (28/10)
Type: task
Blocked by: — (cần bộ bài v0.3 có bài đọc dài để đo)

## Vì sao

Chủ dự án (27/10 23:50): harness chưa có những khả năng cơ bản như "đọc chính xác input dài" hay "thêm
khả năng như một agent", và khảo sát trước chỉ xét 4 mục kiểm soát do điều phối tự chọn — **sai phạm vi**.
Khảo sát lại rộng hơn trên tài liệu chính thức: `harness-capabilities-survey.md` (cùng thư mục; 10 nhóm khả
năng, 7 harness, nguồn có ngày).

## Ún thiếu gì (kiểm code 27/10)

| Khả năng các harness có | Ún hiện tại | Bằng chứng |
|---|---|---|
| Đọc tài liệu dài theo trang / "đọc tiếp" qua một handle | Agent chỉ thấy 400 ký tự đầu của tối đa 5 đoạn mỗi lần tra; không có công cụ đọc tiếp | `agent_service.py` `_clip(content, 400)`; `models.yaml:24-25` |
| Input dài của người dùng (chia nhỏ, map-reduce, lưu thành tài liệu rồi đọc) | Tin nhắn > 10 000 ký tự bị từ chối | `chat_schema.py:5` |
| Đọc tin Discord quanh một tin (`read_messages_around`) | Không có | `agent_service.py` |
| Kiểm câu trả lời theo luật (đoạn trích phải có trong cái đã tra) | Có cho RAG và Nghiên cứu, **không** cho agent | `answer_grounding.grade_rag_answer` dùng ở `routers/rag.py:6`, `research.py:24` |
| Báo tiến độ khi agent chạy (stream các bước) | Chế độ agent không stream | `routers/chat.py:26` (`stream and not use_tools`) |
| Nén / tóm tắt hội thoại dài | Web chat bỏ tin cũ ngoài 40 tin; Discord có rút gọn tầng 3 | `settings.py:202` |
| Lập kế hoạch, agent con, tìm công cụ, chạy code, skills | Không có | — |

Nguyên liệu đã có sẵn: lớp chữ theo trang PDF (`routers/documents.py:144`), danh sách đoạn của tài liệu
(`:178`), kho tài liệu + upload (một đoạn dán dài có thể thành tài liệu tạm).

## Xếp hạng giá trị cho Ún (theo khảo sát; suy luận của agent phụ, điều phối đồng ý)

Ún bị giới hạn bởi cửa sổ 16k và ngân sách 90 s hơn là bởi cỡ 9B. "Code thường" = không tốn thêm lượt model.

| # | Khả năng | Loại | Đổi lời model đọc? | Rủi ro |
|---|---|---|---|---|
| 1 | `read_document(doc_id, from_chunk, n)` trả handle + xem trước; `read_messages_around` | code thường; model chỉ đưa số | có (thêm công cụ) | tốn một trong 3 vòng |
| 2 | Kiểm câu trả lời agent bằng `answer_grounding` sẵn có, thử lại 1 lần khi trượt | code thường | không (trừ khi thử lại) | thêm một lượt khi trượt |
| 3 | Input dài: đoạn dán > ngưỡng thành tài liệu tạm, agent đọc qua công cụ #1 | code thường | có | phải xoá tài liệu tạm |
| 4 | Stream tiến độ các bước agent tới web/Discord | code thường | không | không |
| 5 | Đặt tài liệu trước câu hỏi, trích trước khi trả lời | lời dặn | có | ticket 10 cho thấy đổi lời dặn xáo 38/40 câu |
| — | Agent con, tìm công cụ, lập kế hoạch, chạy code, skills | — | — | giá trị thấp với 3 công cụ, 1 GPU, model 9B (khảo sát §4, §6) |

## Đo

Agent Eval v0.2 không có bài nào đòi đọc quá 400 ký tự hay input dài → **v0.3 phải thêm bài đọc dài**
trước khi đo #1 và #3, cùng các sửa đã gom (doc-27, hist-07, NOT_FOUND, hist-08, "không hỏi lại server").
Luật đo: gỡ model trước mỗi lần, đăng ký trước, so từng bài chỉ tới chỗ khác đầu tiên.

## Comments
