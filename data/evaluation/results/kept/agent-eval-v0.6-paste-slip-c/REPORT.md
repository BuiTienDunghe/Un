# Agent Eval v0.6 — ticket 20 #3-C, lời phiếu đoạn dán lần hai (28/10/2026, 18:56–19:02)

**Đây là test hồi quy nội bộ, không phải khẳng định chất lượng.** Bộ bài do dự án tự viết, không có điểm công bố.
Đăng ký trước: `PREREGISTRATION.md` (9f2a23a), fable duyệt (`reviews/prereg-20-3c-9f2a23a.md`).

## Thật ra chuyện này là gì

Khi người dùng dán một văn bản dài, model chỉ được xem phần đầu và phần cuối, kèm một tờ phiếu chỉ cách tự mở phần
giữa. Lần sửa trước làm model chịu mở, nhưng mỗi lần nó lại xin đọc nhiều hơn mức cho phép. Lần này lỗi đó hết hẳn:
lần đọc nào model cũng xin đúng mức. Ở những bài model đã từng gặp, phiếu mới cho nhiều bài đạt hơn, và không bài nào
đang đạt bị trượt. Nhưng phép thử thật sự là những bài mới chưa ai thấy, vì nó cho biết phiếu có dùng được ngoài mấy
bài quen hay không. Ở những bài đó, model vẫn thường không tự mở phần giữa. Có lần nó biết phần giữa còn thiếu mà vẫn
nhờ người dùng dán lại. Có lần nó đọc được một nửa rồi nói đã đọc hết. Theo luật viết trước khi chạy, phiếu mới
**không đạt**.

## Kết quả (mỗi phía r1 = r2 từng chữ)

| Luật đăng ký trước | Kết quả |
|---|---|
| 1. Băm công cụ, lời dặn, prompt, bộ bài đúng số đăng ký, bằng nhau ở hai phía | **đúng** (`153209…`, `6194cf…`, `385cb4…`, `cd38e4…`) |
| 2. Không bài nào trong 9 bài từ đạt thành trượt | **đúng** |
| 3. Ít nhất 2/3 bài **mới** cần phần giữa (doc-44, 46, 47) từ trượt thành đạt | **SAI**: 1/3 (doc-46) |
| 4. doc-45 đạt ở phía sau | **đúng**, không đọc lần nào |
| 5. Ít nhất 2/4 bài đã thấy cần phần giữa (doc-39, 40, 41, 43) từ trượt thành đạt | **đúng**: 3/4 (39, 41, 43) |

**Không đề xuất gộp.** Main vẫn giữ phiếu cũ (`01daa42`). `int/20-3c` (`ed210e4`) giữ nguyên làm nhánh.

Các dòng tách riêng như đã đăng ký:

| | Trước (phiếu cũ) | Sau (phiếu #3-C) |
|---|---:|---:|
| Điểm 9 bài | 2/9 (42, 45) | 6/9 (39, 41, 42, 43, 45, 46) |
| Mở đoạn dán, trên 7 bài cần phần giữa | 4/7 (40, 41, 46, 47) | 5/7 (39, 41, 43, 46, 47), nhưng doc-47 chỉ mở **sau** khi bị kiểm con số bác, nên phần của phiếu là **4/7** |
| Đọc tiếp đúng bằng `next_from_chunk` (40, 41, 43, 44, 46, 47) | 1/6 (46) | **3/6** (41, 43, 46) |
| `n` lần đọc đầu ≤ 3 | 1/4 | **5/5** |
| `n` các lần đọc sau ≤ 3 | 0/2 | **5/5** |
| Số lần đọc ở doc-42 / doc-45 (đáp án đã có trong phiếu) | 0 / 0 | 0 / 0 |

Phiếu đổi **bài nào** mở và mở **đúng cách** (luôn từ đoạn 0, `n` = 3, đọc tiếp đúng) nhiều hơn là đổi **bao nhiêu**
bài mở. Lỗi `n` mà #3-B để lại đã hết ở cả lần đọc đầu lẫn các lần sau. Ghi chú 2 của fable (lần sau vẫn xin quá 3) không
xảy ra, nên việc sửa kết quả công cụ để chữa `n` không còn cần.

## Từng bài

| Bài | Nhóm | Trước | Sau | Sau: lần đọc (`from_chunk`, `n`) | Sau: đạt |
|---|---|---|---|---|:-:|
| doc-39 | đã thấy | tìm kho, hỏi lại; thiếu ý | mở, đủ ý | (0, 3) | ✓ |
| doc-40 | đã thấy | đọc (4, 4), sai ngày, sai người | gọi `search_history` (bị cấm), nói "dữ liệu dán… không thể dùng `read_document`", nhờ người dùng dán phần giữa | không đọc | ✗ |
| doc-41 | đã thấy | tìm kho hai lần, đọc (0, 15); thiếu ý | đọc tiếp tới đoạn 6, trả lời ở lượt ép | (0, 3) (3, 3) (6, 3) | ✓ |
| doc-42 | đã thấy, đáp án trong phiếu | không đọc, đạt | không đọc, đạt | — | ✓ |
| doc-43 | đã thấy | không đọc, hỏi lại | đọc tới đoạn 5, đủ cả người lẫn ngày | (0, 3) (3, 3) | ✓ |
| doc-44 | **mới** | không đọc, lấy giá gây nhiễu 420.000 ở mép cuối | không đọc; nói phần giữa chưa hiện ra rồi nhờ người dùng dán lại | không đọc | ✗ |
| doc-45 | **mới**, đáp án trong phiếu | không đọc, đạt | không đọc, đạt | — | ✓ |
| doc-46 | **mới** | đọc (1, 12) (4, 8) (7, 5): đủ ý, trượt **chỉ vì `n`** | đọc tới đoạn 7, trả lời ở lượt ép | (0, 3) (3, 3) (6, 3) | ✓ |
| doc-47 | **mới** | đọc (7, 3), không thấy cả hai mảnh | bị kiểm con số bác trước; rồi đọc (0, 3), thấy 75 ngày ở đoạn 2, **không đọc tiếp**, nói "đã đọc được văn bản hợp đồng đầy đủ", rồi nêu tiền cọc 54.000.000 ở mép cuối và bảo hợp đồng không nói mức bị giữ (đáp án 36 triệu nằm ở đoạn 5) | (0, 3) | ✗ |

Ba bài trượt ở phía sau trượt theo ba cách khác nhau:
- doc-40 hiểu sai phiếu.
- doc-44 hiểu phiếu nhưng không làm theo.
- doc-47 đọc một nửa rồi tưởng đã đủ.

Hai bài kết bằng việc nhờ người dùng cung cấp thứ mà model tự đọc được (40, 44). Bài thứ ba hỏi có cần tìm thêm không (47).

Ở doc-40, câu "Văn bản dán nằm trong tin nhắn, không phải tệp đã tải lên: search_documents không tìm thấy nó" đã có y
nguyên ở phiếu #3-B, và ở #3-B doc-40 vẫn mở. Vậy không quy được cái lùi của doc-40 về một câu. Những gì #3-C đổi quanh
câu đó là: thêm câu "đã đủ thì trả lời luôn" ngay sau nó, thêm câu trần `n`, bỏ câu số đoạn. doc-40 không tính vào điều 2,
vì nó trượt ở cả hai phía; nhưng hành vi tệ đi: trước mở sai chỗ, sau không mở và gọi công cụ bị cấm.

Ghi chú 1 của fable (điều 5 đạt mà doc-39 lùi): **không xảy ra**. doc-39 và doc-43 đều mở và đạt.

doc-46 từ trượt thành đạt chỉ nhờ sửa `n`: ở phía trước nó đã đủ ý. Đó là bài duy nhất làm điều 3 không về 0.

## Dự đoán

| Dự đoán | Kết quả |
|---|---|
| Trước: doc-39..43 trùng từng chữ phía trước của #3-B | **đúng**: cả 5 bài, cả hai lần. Ủng hộ giải thích "thứ tự chạy" cho lệch doc-39 ở #3-B (cả hai lần doc-39 là bài đầu) |
| Trước: doc-44, 46, 47 trượt; doc-45 đạt, không đọc | **đúng** |
| Sau: mọi bài có đọc đều có `n` lần đầu ≤ 3 | **đúng** (5/5) |
| Sau: doc-39 mở và đạt | **đúng** |
| Sau: doc-43 mở | **đúng** (và đạt) |
| Sau: doc-42 và doc-45 không đọc, cả hai đạt | **đúng** |
| Sau: doc-44, 46, 47 mở cả ba | **sai**: doc-44 không mở; doc-47 chỉ mở sau khi bị kiểm con số bác |
| Mỗi phía r1 = r2 từng chữ | **đúng** |
| (không dự đoán) `n` các lần đọc sau | 5/5 ≤ 3 |

## Chi phí của phiếu mới (r1; r2 trùng)

| Bài | Token vào cả bài: trước → sau | Độ trễ (ms): trước → sau | Lý do dừng sau |
|---|---|---|---|
| doc-39 | 3 572 → 5 400 | 11 168 → 10 638 | final |
| doc-40 | 5 024 → 3 908 | 4 833 → 6 202 | final |
| doc-41 | 8 298 → 16 063 | 9 426 → 9 830 | max_steps |
| doc-42 | 1 728 → 1 838 | 1 706 → 2 298 | final |
| doc-43 | 1 693 → 10 959 | 2 618 → 11 890 | final |
| doc-44 | 1 750 → 1 859 | 4 365 → 5 504 | final |
| doc-45 | 1 741 → 1 851 | 1 395 → 2 984 | final |
| doc-46 | 14 501 → 15 403 | 14 647 → 16 580 | max_steps |
| doc-47 | 4 484 → 7 811 | 8 145 → 11 034 | final |

Lượt model lớn nhất ở phía sau nhận 5 792 token, dưới một nửa khung 16k. doc-42 không còn đọc thừa ba lần như ở #3-B
(15 850 token).

## Điều kiện đo

| | |
|---|---|
| Trước | worktree sạch tách tại `01daa42`, tức main = `8b91199` (gộp bài v0.6) + bản đăng ký `9f2a23a` + bài duyệt của fable; ngoài `8b91199` chỉ thêm tệp tài liệu |
| Sau | worktree sạch tách tại `ed210e4`, tức `int/20-3c` = `01daa42` + gộp `--no-ff` `wip/20-paste-slip-c` (`5d16c7b`); khác main chỉ ở `pastes.py` và test của nó; ticket giữ bản của main |
| Test trước khi đo | trên `ed210e4`, chạy kiểu giữ im: 213 đạt, 17 bỏ qua (`-k agent`) |
| Quy trình | `--tasks doc-39,…,doc-47`. Trước mỗi lần chạy: gỡ `qwen3.5:9b`, ghi `/api/ps` (`ollama_ps.jsonl`). t0, seed 42, `--probe`, `--gpu-shared no`. Giờ bắt đầu: trước r1 18:56:47, trước r2 18:58:11, sau r1 18:59:27, sau r2 19:01:02 |
| GPU | không dùng chung, 43–53 °C lúc bắt đầu mỗi lần. Trước r1 chưa nạp `qwen3-embedding:0.6b` (0 MiB), ba lần sau có (1 782 MiB); trước r1 = r2 nên không gây lệch |
| Bảng điểm | không `--append-history`: lần đo 9 bài là lần đo một phần |

## Tệp

`v0.6-3c-{before,after}-r{1,2}-cold/`: năm tệp mỗi lần chạy. `analyze.py`, commit cùng bản đăng ký, tính lại
`analysis.json`. "Lần tệ hơn" đọc theo hướng bất lợi cho đề xuất: đạt trước nếu một lần trước đạt; đạt sau chỉ khi
cả hai lần sau đạt.
