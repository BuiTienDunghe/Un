# Đợt subagent 29/10: hướng tốt nhất cho văn bản dán dài — tổng hợp (fable 5.1)

Bốn agent độc lập (nới trần đọc, tìm trong đoạn dán, harness tìm hộ, phản biện), hai vòng: tìm hiểu + thử nghiệm offline,
rồi đọc chéo và phản bác. Không chạy model (GPU do dự án VI dùng tới ~06:00). Hạn dùng sau đợt: tuần 14 %, Fable 16 %
(ngưỡng dừng 35 %). Báo cáo từng agent nằm cùng thư mục; mục "Vòng 2" ở cuối mỗi tệp là phản bác.

## Bản chất

Suốt ba đợt sửa, ta dạy model tự lật sách: cho phiếu, cho lời nhắc, cho công cụ tìm. Model lật được một phần và không
bao giờ tới trang xa. Bốn agent đi bốn hướng khác nhau, tranh luận xong đều về một kết luận: với văn bản vừa cửa sổ của
model, đừng bắt nó lật nữa, đưa thẳng cả văn bản vào. Ngưỡng 10 000 ký tự đang chặn việc đó là giới hạn cũ của API chat,
không phải do cửa sổ 16k. Mọi bài thử hiện có đều vừa cửa sổ. Chỉ văn bản quá cỡ mới cần harness tìm hộ, và công cụ tìm đã
sửa lỗi làm dự phòng. Nới số lượt đọc thì tới cùng một trần (khoảng 27 000 ký tự) mà tốn gấp đôi thời gian, nên lùi xuống
vai phụ.

## Xếp hạng cuối của bốn agent (sau phản bác)

| Agent | Hạng 1 | Hạng 2 | Hạng 3 |
|---|---|---|---|
| Nới trần đọc (C) | N1 + P3 trên ngưỡng + sửa BM25 | N1 | sửa BM25 |
| Tìm trong đoạn dán | N1 khi vừa ngân sách, không thì P3, công cụ sửa làm dự phòng | N1 | P3 |
| Harness tìm hộ (P3) | N1 + P3 | N1 | P3 |
| Phản biện | đếm nhu cầu → N1 | P3 cho quá ngưỡng | sửa công cụ như sửa lỗi |

N1 = nạp nguyên văn bản dán khi ước token còn vừa cửa sổ (cả lịch sử); P3 = mục lục + 3 đoạn tìm bằng chữ trùng đưa vào
phiếu; C = nới trần lượt công cụ.

## Số đo offline đáng tin nhất (đã kiểm bằng code, không model)

| Số | Giá trị | Nguồn |
|---|---|---|
| Mỗi lần đọc 3 đoạn tốn thêm | 1 673 token, ~2,5 s | c-noi-tran-doc, n = 118 vòng |
| Cửa sổ 16k chứa tối đa | ~7 lần đọc, tức đoạn 0–20, ≈ 27 000 ký tự | c-noi-tran-doc |
| Nạp nguyên doc-50 (31 681 ký tự) | ≈ 10,9k token, vừa cửa sổ khi không có lịch sử | c-noi-tran-doc, 3,3 ký tự/token đo từ 186 câu |
| N1 so với C về thời gian | nhanh ~2 lần (10–13 s so với ~23 s), không phải 3 lần | c-noi-tran-doc (Ollama dùng lại phần đầu prompt) |
| Harness tách câu hỏi tự động | đúng phía 15/15; dính liền văn bản 15/15 với quy tắc R2 | harness-tim-ho (quy tắc viết sau khi đọc bài) |
| Tìm bằng chữ trùng, đáp án vào top-3 | 8–9/12 bài; bài trượt đứng hạng 7–10 | harness-tim-ho, tim-trong-doan-dan khớp nhau |
| Công cụ tìm hiện tại | chặn IDF làm doc-47 rỗng; mép không cắt ở 4 bài vì bộ chia bỏ tiêu đề; hit@3 30/58 → 38–43/58 khi sửa | tim-trong-doan-dan |
| doc-53 (đoạn mồi) | không biến thể đếm chữ nào thoát; nhưng ở nền model có cả đoạn mồi lẫn đáp án trong ngữ cảnh vẫn đạt | tim-trong-doan-dan, phan-bien |

## Điều chưa ai đo, phải đo trước khi tin N1

1. Chất lượng model 9B khi một tin dài 8–11k token và đáp án nằm giữa ("lost in the middle"): vòng lớn nhất từng chạy chỉ
   6 483 token. Đây là rủi ro số một.
2. Bước kiểm số #2 coi mọi tin trong lượt là "đã thấy": nạp nguyên văn bản thì #2 gần như tắt với đoạn dán (kể cả số mồi).
3. Ngưỡng phải tính bằng token ước cả lịch sử, không bằng ký tự; cần test đơn vị để 47 bài không dán không đổi.
4. Nhu cầu thật: chưa ai đếm có bao nhiêu tin dán > 10 000 ký tự trên server; một câu đếm chỉ đọc là đủ.

## Đề xuất một đợt đo phân xử (sau khi GPU rảnh, cô lập từng bài)

- Code: N1 ≈ 20 dòng trong `pastes.take_pastes` (hằng mới, không đụng `PASTE_THRESHOLD`), chỉ áp cho tin cuối; tuỳ chọn
  C7 (`max_steps` 3 → 7 khi có đoạn dán) làm nhánh đối chứng cơ chế.
- Bài: 15 bài dán cũ (đã lộ, chỉ để lặp) + ≥ 3 bài mù 25–30 000 ký tự đáp án ở 40–60 % chiều dài + ≥ 1 bài mù > 40 000 ký tự
  (N1 không áp dụng, để thấy nhánh dự phòng).
- Nhánh: nền (dùng lại `v0.7-3d-iso-base-r1`), N1, C7. Một lần mỗi nhánh, r1 = r2 đã chứng minh dưới cô lập.
- Luật đăng ký trước: N1 thua C7 ≥ 2 bài ở bài giữa → "lost in the middle" có thật, giữ C cho khúc giữa; N1 ≥ C7 mọi bài
  và không bài đạt nào lùi → chọn N1, bỏ C; `tokens_in` doc-50 lệch > 15 % so với 10,9k → tính lại ngưỡng. Đây là phép
  thử cơ chế, không phải cổng gộp.
- GPU ≈ 10–13 phút; dừng nếu GPU ≥ 85 °C hoặc hạn tuần ≥ 35 %.

## Ý kiến fable (không phải quyết định)

Hướng tốt nhất: **N1 làm chính, P3 + công cụ tìm đã sửa cho văn bản quá ngưỡng, C bỏ**. Trước khi xây P3, chạy đợt đo
phân xử trên để biết N1 có gãy ở khúc giữa không; nếu gãy, C7 là chốt chặn rẻ cho khúc 10–27k ký tự. Song song, chạy câu
đếm nhu cầu để biết có đáng xây phần quá ngưỡng hay không.
