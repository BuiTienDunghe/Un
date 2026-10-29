GỘP ĐƯỢC (vào int/20-arb trước khi đo; bốn chỗ NV3 tự quyết đều đứng được, hai chỗ cần ghi vào bản đăng ký)

# Duyệt wip/20-paste-tasks-e 0adc697 (Agent Eval v0.8: bốn bài dán mù doc-54..57 cho đợt đo phân xử) — fable 5.1, 29/10/2026

Đã kiểm: diff b100d56..0adc697 (4 tệp: `tasks.jsonl` +4 dòng, `dataset.json` đổi version, README +44, `test_agent_eval.py`
+82). Đọc trọn câu hỏi, đoạn đáp án và đoạn mồi của cả bốn bài; chạy lại vị trí bằng script riêng. Không chạy model.
Đối chiếu với brief trong tong-hop.md (≥ 3 bài 25–30 000 ký tự, đáp án ở 40–60 %; ≥ 1 bài > 40 000 ký tự).

## Kiểm độc lập

| Kiểm | Kết quả |
|---|---|
| 62 bài cũ không đổi, bộ chấm không đổi | diff `tasks.jsonl` chỉ thêm 4 dòng cuối; không tệp nào của grader bị đụng; 66 bài |
| Độ dài và vị trí (tính lại bằng `_chunks` + regex trên nguyên văn) | doc-54 27 076 ký tự / 19 đoạn, đáp án đoạn 10 ở 56 %; doc-55 28 596 / 21, đoạn 10 (47 %) và 12 (58 %); doc-56 28 058 / 20, đoạn 10 ở 55 %, mồi đoạn 4; doc-57 45 166 / 33, đoạn 13 ở 38 % — khớp README và `PASTE_ANSWER_CHUNKS` |
| Ba bài giữa dưới trần ước của brief (1 300 + ký tự/3,3 ≤ 12 288 ⇔ ≤ ~36 200 ký tự); bài dài vượt | đúng: 28 596 < 36 200 < 45 166 |
| Mỗi mẫu `must_mention` khớp đúng một chỗ trong nguyên văn, đúng đoạn đã khai | đúng cả 8 mẫu; "90.000" của doc-56 có mặt ở đoạn 1 nhưng đứng sau chữ số nên lookbehind loại, test `[match] = finditer` ghim |
| Đáp án không lộ qua phiếu (600 ký tự đầu/cuối) | cả 4 bài: đầu là tiêu đề hoặc câu hỏi, cuối là câu hỏi hoặc phần đóng; không mẫu nào khớp hai mép |
| Đọc lần lượt từ đoạn 0, mỗi lần 3 đoạn, qua chính `AgentService._read_document` | test v0.8 kiểm mọi cửa sổ 3 đoạn liền nhau trả đủ 3 đoạn; đáp án tới ở lần đọc 4 (54, 56, mảnh 1 của 55) và 5 (mảnh 2 của 55, 57), trong 7 lượt |
| Câu đúng / câu lấy số mồi / câu đoán khoảng | 16 câu mẫu mới chấm đúng chiều; mẫu số chặn chữ số đứng sau "-", "–", "~" kể cả cách dấu cách |
| Test | 253 xanh, 13 bỏ qua (`tests/test_agent*.py`) ở worktree NV3, HEAD 0adc697 sạch |

## Nội dung từng bài (đã đọc)

- **doc-54** (giải chạy, điểm cắt 21 km): câu hỏi ở đầu, rõ; đáp án một câu ở đoạn 10 ("trạm Suối Mơ… đóng lúc 8 giờ 40"),
  ngay sau là hai điểm cắt của cự ly 42 km làm nhiễu đúng chỗ. Không mơ hồ.
- **doc-55** (sổ tay sinh viên): hai mảnh, nơi nộp (Bộ phận Một cửa, nhà Hoa Sữa) và phí duy trì hồ sơ 320.000/học kỳ;
  cạnh mảnh hai có 95.000 và 50.000 làm nhiễu. Hai mảnh cách 2 đoạn nên một lần đọc từ đoạn 10 lấy cả hai: bài này đo
  "đọc tới giữa" chứ không đo "gom hai mảnh xa nhau"; NV3 đã ghi trong giới hạn.
- **doc-56** (điều khoản gym): câu hỏi nói kiểu đời thường; đoạn mồi (Điều 9: tạm dừng 30 ngày, 150.000, kèm một câu
  hỏi-đáp dùng gần hệt chữ của câu hỏi) nằm ở đoạn 4, tức model đọc lần lượt sẽ gặp mồi trước. Đáp án Điều 24 (75 ngày,
  90.000) đúng với ca gãy chân có kết luận y tế. Một điểm mở: Điều 24 nói "không ảnh hưởng tới quyền lợi theo Điều 9", nên
  câu trả lời nêu cả hai điều vẫn hợp lý và vẫn đạt (không có `must_not_mention`); câu chỉ nêu Điều 9 thì trượt, đúng chủ ý.
- **doc-57** (quy chế chi tiêu): bảng năm vùng trong một đoạn, Tây Nguyên 265.000 / 870.000; nhiễu là bốn vùng còn lại và
  khoán 330.000 cùng đoạn. Đáp án ở 38 % chiều dài, cố ý ngoài dải 40–60 %, lý do NV3 nêu đúng: bài này nằm ngoài tầm nạp
  nguyên văn, nếu tính là bài giữa thì nhánh N1 và nền giống nhau theo cách dựng.

## Bốn chỗ NV3 tự quyết

| Chỗ | Ý kiến fable |
|---|---|
| doc-57 ở 38 % | đúng; brief chỉ đòi bài > 40 000 ký tự, không đòi vị trí; bản đăng ký phải nói rõ doc-57 **không** nằm trong tập "ba bài giữa" của luật 1 và 2 |
| doc-55 hai mảnh cách 2 đoạn | chấp nhận; dải 40–60 % của 29 000 ký tự thật sự không chứa hai đoạn cách ≥ 3; hệ quả: không có bài mù nào đo việc gom hai mảnh xa |
| Không `must_not_mention` | chấp nhận; thêm vào sẽ đánh trượt câu trả lời đầy đủ ở doc-56; báo cáo nên liệt kê tay câu trả lời doc-56 có nêu số mồi hay không |
| Mồi doc-56 ở đoạn 4 | đúng ý "model gặp mồi trước đáp án"; là bài phân biệt rõ nhất giữa "đọc tiếp" và "dừng ở mồi" |

## Cho bản đăng ký (opus)

- Băm bộ bài đổi (v0.8), nên luật 1–2 phải nêu tập bài giữa = {doc-54, 55, 56}, bài dài = {doc-57}; 15 bài dán cũ chỉ để lặp.
- Nền phải chạy 4 bài mới trên int/20-arb; 15 bài cũ của nền có dùng lại lần chạy cô lập trước hay chạy lại là việc của bản
  đăng ký, phải nói rõ và nói vì sao.
- Mù: README ghi người viết không xem hai nhánh của NV1; tôi không có cách kiểm, ghi nhận lời khai.

## Nhỏ, không chặn

- README mục v0.8 có một câu "Độ dài chọn theo cách ước của đề bài N1 (1 300 + ký tự/3,3)": hằng thật của nhánh có thể
  khác; NV3 đã rào "chỉ là ước để chọn độ dài", đủ.
