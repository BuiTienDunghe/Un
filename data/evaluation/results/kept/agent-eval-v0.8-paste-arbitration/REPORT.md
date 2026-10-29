# Ticket 20 — đợt đo phân xử N1 / C7 (Agent Eval v0.8): báo cáo

Đo đúng bản đăng ký `e6666c0` (fable duyệt `bcb76b7`), 29/10 09:58–10:13. Bốn lần chạy cô lập, GPU riêng, nóng nhất 79 °C.
Số tính bằng `analyze.py` cùng thư mục (`analysis.json`).

## Bản chất

Đưa cả văn bản cho model đọc một lần thì nó trả lời đúng mọi bài vừa sức chứa, kể cả khi đáp án nằm giữa một văn bản gần
30 000 ký tự. Nỗi lo "model bỏ sót khúc giữa" không xảy ra ở bài nào. Cho model lật trang bảy lần thay vì ba thì chỉ cứu được
những bài mà model chịu lật. Năm bài nó không chịu lật hoặc dừng ở trang mồi vẫn trượt như cũ. Cách đưa cả văn bản còn nhanh
gấp đôi. Văn bản quá sức chứa (bài 45 000 ký tự) thì chỉ cách lật bảy lần tới được đáp án.

## Theo luật đã đăng ký

| Mục | Kết quả |
|---|---|
| Điều kiện trước P | đủ cả 15 điều: băm, bộ bài v0.8 một sha, 15 bài cũ trùng v0.7, cô lập, khoá manifest, tập bài giữa, N1 nạp nguyên 18/18 và không nạp doc-57 |
| Bài bị loại vì gần cửa sổ (> 14 500 token) | không có. Vòng lớn nhất: N1 10 561 (doc-55), C7 11 504 (doc-55) |
| R1 (N1 thua C7 ở ≥ 2 trong 3 bài giữa mù) | **không**: N1 thua 0 bài |
| R2 (18 bài: không bài C7 đạt mà N1 trượt; 19 bài: không bài nền đạt mà N1 trượt) | **có**: 0 và 0 |
| R0 | không |
| R3 (vòng đầu doc-50 lệch > 15 % so với 10 900) | không: 9 763, lệch −10,4 % |

**Kết luận theo luật: R2, chọn N1, bỏ C.** Đây là phép thử cơ chế trên nhánh có phiếu #3-C, không phải cổng gộp main.

| Nhánh | 19 bài | 15 cũ | 3 giữa mù | 6 giữa cũ | doc-57 | Trung vị độ trễ | Tổng `tokens_in` |
|---|---|---|---|---|---|---|---|
| nền `613f0b2` | 10 | 10 | 0 | 3 | trượt | 12,1 s | 199 532 |
| N1 `d40d4e0` | **18** | **15** | **3** | **6** | trượt | **5,5 s** | **130 318** |
| C7 `bc93975` | 14 | 12 | 1 | 4 | **đạt** | 11,8 s | 286 090 |

N1 lần 2 trên 9 bài giữa: 9/9, câu trả lời giống lần 1 từng byte.

## Từng bài

Đ = đạt, T = trượt; số lần đọc đoạn dán; độ trễ.

| Bài | Nền | N1 | C7 | Ghi chú |
|---|---|---|---|---|
| doc-39 | Đ 1 · 8 s | Đ 0 · 3 s | Đ 1 · 8 s | |
| doc-40 | T 0 · 6 s | **Đ** 0 · 3 s | T 0 · 6 s | nền/C7 gọi `search_history` (cấm), không đọc |
| doc-41 | Đ 3 · 15 s | Đ 0 · 5 s | Đ 3 · 12 s | |
| doc-42 | Đ 0 · 2 s | Đ 0 · 3 s | Đ 0 · 2 s | |
| doc-43 | Đ 2 · 11 s | Đ 0 · 4 s | Đ 2 · 11 s | |
| doc-44 | T 0 · 10 s | **Đ** 0 · 5 s | T 0 · 10 s | nền/C7 không đọc, nói văn bản không ghi |
| doc-45 | Đ 0 · 3 s | Đ 0 · 3 s | Đ 0 · 3 s | |
| doc-46 | Đ 3 · 14 s | Đ 0 · 6 s | Đ 3 · 12 s | |
| doc-47 | T 1 · 12 s | **Đ** 0 · 14 s | T 1 · 12 s | nền/C7 đọc một lần, nói hợp đồng không nêu; N1: #2 bắn một lần |
| doc-48 | Đ 2 · 10 s | Đ 0 · 6 s | Đ 2 · 10 s | |
| doc-49 | T 3 · 18 s | **Đ** 0 · 9 s | **Đ** 4 · 18 s | nền hết lượt ở đoạn 8 |
| doc-50 | T 3 · 19 s | **Đ** 0 · 5 s | **Đ** 5 · 19 s | C7 nói với người dùng "chunk_index=14" |
| doc-51 | Đ 3 · 15 s | Đ 0 · 5 s | Đ 3 · 12 s | |
| doc-52 | Đ 0 · 3 s | Đ 0 · 3 s | Đ 0 · 3 s | |
| doc-53 | Đ 3 · 16 s | Đ 0 · 7 s | Đ 3 · 12 s | |
| doc-54 | T 0 · 6 s | **Đ** 0 · 7 s | T 0 · 6 s | mù; nền/C7 không đọc, nói không có thông tin |
| doc-55 | T 3 · 18 s | **Đ** 0 · 9 s | **Đ** 5 · 23 s | mù |
| doc-56 | T 2 · 21 s | **Đ** 0 · 10 s | T 2 · 21 s | mù; nền/C7 đọc tới đoạn 5, trả lời theo Điều 9 (mồi) |
| doc-57 | T 3 · 19 s | T 3 · 19 s | **Đ** 5 · 27 s | quá ngưỡng N1; chỉ C7 tới đoạn 13 |

**Kiểm nguồn gốc**: tôi đã đọc mọi câu trả lời đổi đạt/trượt giữa các nhánh: 8 bài của N1, 4 bài của C7 và 5 bài C7 trượt.
Mọi lần đạt đều nêu đúng số của văn bản, kèm điều khoản; không lần nào đạt nhờ đoán khoảng. doc-56: cả bốn câu trả lời đều
chứa số mồi. N1 nêu Điều 9 (30 ngày, 150.000) rồi khuyên dùng Điều 24 (75 ngày, 90.000) "vì đây là lý do y khoa", nên số mồi
chỉ là đối chiếu. Nền và C7 trả lời theo Điều 9, và hai câu trả lời đó giống hệt nhau.

## Dự đoán

| Mã | Dự đoán | Kết quả |
|---|---|---|
| p1 | Nền: 15 bài cũ giống hệt `v0.7-3d-iso-base-r1` | đúng |
| p2 | Nền trượt mọi bài mới | đúng |
| p3 | N1 đạt ≥ 2 bài giữa mù | đúng (3/3) |
| p4 | C7 đạt doc-49 và doc-50 | đúng |
| p5 | N1: #2 không bắn ở bài nạp nguyên | **sai**: bắn một lần ở doc-47 |
| p6 | N1, doc-57 giống hệt nền | đúng |
| p7 | Không bài nào dừng vì hết 90 giây | đúng |
| p8 | Trung vị độ trễ N1 < C7 | đúng (5,5 s so với 11,8 s) |
| p9 | N1 lần 1 = lần 2 trên bài giữa | đúng (9/9 giống từng byte) |
| p10 | C7: bài nền dừng trước trần thì giống hệt nền | đúng |

p5 sai: #2 bắn một lần ở doc-47 dưới N1. Vết chỉ ghi số lượng con số bị bắt, không ghi là số nào, và không giữ câu trả lời
đầu. Ba con số trong câu trả lời cuối (18.000.000, 36.000.000, 54.000.000) đều có nguyên văn trong văn bản. Câu thử lại tự
nói con số bị bắt là tiền cọc 54.000.000, mà số này có trong văn bản. Suy luận, chưa kiểm được: câu đầu viết khác dạng, ví dụ
"54 triệu"; bộ kiểm đọc "54" thành một số riêng, không khớp với 54.000.000. Đây là điểm mù sẵn có của #2, có ở mọi nhánh: nền
và C7 cũng bắn ở doc-47.

Câu trả lời sau lần thử lại mở đầu bằng "Xin lỗi, tôi đã nhầm lẫn…". Đây là lỗi lộ lời thử lại của #2, đã biết từ 28/10; nó
cũng có ở C7 doc-57 ("Xin lỗi, tôi cần làm rõ lại").

## Ghi riêng

| Mục | Kết quả |
|---|---|
| Tỉ lệ ký tự/token thật ở vòng đầu N1 | 3,07 (doc-55) – 3,80 (doc-39); doc-50 3,72. Con số 2,79 từ lần đọc cũ không lặp lại (khi đó văn bản bọc trong JSON) |
| Bộ ước của N1 | ước dư: doc-50 ước 10 882, thật 9 763. Trần 12 288 lệch về phía an toàn |
| Vòng > 16 384 token | không có |
| Dừng vì `turn_budget` | không có |
| Lệnh công cụ hỏng (ticket 27) | không có |
| #2 bắn | nền 3 (doc-44, 47, 56), N1 1 (doc-47), C7 4 (doc-44, 47, 56, 57) |
| Nạp lại model mỗi bài | trung vị 2,56 s |

## Ngoài luật

- **Nhiều lượt hơn không cứu được bài mà model không chịu đọc.** Năm bài C7 trượt có ba bài không đọc lần nào (doc-40, 44,
  54), một bài đọc một lần (doc-47), một bài dừng ở mồi (doc-56). Ở cả năm bài, model tự dừng trước trần, nên câu trả lời của C7
  giống hệt nền từng byte (p10). N1 bỏ hẳn bước model phải quyết định đọc.
- Bốn bài nền đạt nhờ câu trả lời ép ở vòng 4 (doc-41, 46, 51, 53) vẫn đạt ở C7. Ở C7, model tự dừng sau ba lần đọc.
- C7 doc-50 nói với người dùng "chunk_index=14", tức lộ chi tiết nội bộ.

## Giới hạn

- Nền và C7 chạy một lần; N1 chạy hai lần trên bài giữa.
- 15 bài cũ đã lộ với người viết code; chỉ doc-54..57 là mù.
- 19 bài chỉ bắt được chênh lệch lớn. Ở đây chênh lệch lớn: 18 so với 14 và 10.
- 47 bài không dán không chạy lại. Code của N1 chỉ chạm tin cuối là đoạn dán, có test ghim.
- Eval không có lịch sử hội thoại. Phần lịch sử trong ước token của N1 chỉ được test đơn vị kiểm, chưa đo bằng model. Trong
  chat thật, tối đa 40 tin lịch sử nằm cùng phép ước, nên trần thực tế thấp hơn ~36 000 ký tự. Discord giới hạn tin ở 10 000
  ký tự, nên N1 không bao giờ bật ở đó.
- Agent Eval là test hồi quy nội bộ, không phải khẳng định chất lượng.
- Các nhánh đo đứng trên phiếu #3-C (`int/20-arb`), không phải main. Main đang dùng phiếu #3.

## Cách cho chủ dự án (chưa làm gì)

| Cách | Làm gì | Ưu | Nhược |
|---|---|---|---|
| A | Gộp N1 vào main, trên phiếu #3 hiện có | ~20 dòng; mọi đoạn dán ≤ ~36 000 ký tự được nạp nguyên | Văn bản dài hơn vẫn đi phiếu #3, yếu hơn #3-C (45 so với 50/62 cô lập, so sánh ngoài luật). Nên chạy đủ 62 bài cô lập trên main + N1 trước khi gộp (~12 phút GPU) |
| B | Gộp cả #3-C lẫn N1 vào main (đúng thứ đã đo ở đây) | Main nhận đúng thứ đã đo; văn bản quá ngưỡng dùng phiếu tốt hơn | #3-C chưa từng qua luật đăng ký riêng; cũng cần lần chạy đủ 62 bài |
| C | B, thêm C7 cho văn bản quá ngưỡng | Khi N1 nạp nguyên thì C7 tự tắt, nên C7 chỉ chạy với văn bản quá ngưỡng; doc-57 cho thấy chỉ C7 tới được | Bằng chứng mới có một bài; cần một đợt đăng ký riêng với nhiều bài > 36 000 ký tự |
| D | Chưa gộp; trước hết đếm có bao nhiêu tin dán > 10 000 ký tự trên server thật | Biết phần quá ngưỡng có đáng làm không | Chậm giao giá trị đã đo được |

Ý kiến opus: B, kèm lần chạy đủ 62 bài làm điều kiện, rồi D trước khi tính tới C. B đưa lên main đúng thứ vừa đo. Lần chạy
62 bài là thứ duy nhất đợt này chưa kiểm.
