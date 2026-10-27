GỘP ĐƯỢC
**Chủ dự án chốt (28/10, trong phiên fable), nguyên văn: "Ship #1-B theo luật đã đặt; mở tiêu chí 'trả lời có
số liệu mà không tra' ở v0.4."**

# Duyệt wip/20-agent-reading 8cc0f73 (#1-B: công cụ đọc, lời dặn như main) — fable 5.1, 28/10/2026

Soát bốn commit kể từ cd99811: 1f9a4d4 (chỉ bỏ câu nhắc trong `AGENT_GUIDE`; sha của chuỗi guide trên nhánh
= main, tôi băm lại cả hai: `cb00fdf7…`), cc354e1 + aff4a64 (đăng ký trước, 00:32:24/00:32:35, trước lần
chạy đầu 00:32:47), 8cc0f73 (hai lần lạnh + REPORT + analyze.py). Cây sạch.

## Số tính lại từ kept/ — khớp hết

| Đo | NV1 | Tôi tính lại |
|---|---|---|
| Tổng A / #1 / #1-B r1 / r2 | 35 / 34 / 38 / 38 | 35 / 34 / 38 / 38 |
| 40 bài cũ A / #1 / #1-B | 34 / 29 / 33 | 34 / 29 / 33 |
| 5 bài đọc dài A / #1 / #1-B | 0 / 4 / 4 | 0 / 4 / 4 |
| r1 = r2 (#1-B) | 48/48 | 48/48 |
| Câu cũ đổi chữ so với A | 39/40 | 39/40 |
| Bài lật so với A | tụt doc-10, 19, 25, 26, hist-05; lên doc-29, 31, hist-07, stat-02 | đúng danh sách |
| `read_document` | 4 bài, 0 BAD_ARGUMENTS, doc-36 không gọi | đúng; doc-33 vẫn `from_chunk=0, n=5` |
| tokens_in lớn nhất / cả lần | 3 811 (23,3%) / 149 244 | đúng |
| by_check A → #1-B | citation 16→15, must_mention 32→35, not_found 4→4, no_ask_back 3→3, tools_required 32→32 | khớp |
| **Hash** | guide #1-B = A (`6194cf0f`), tools #1-B = #1 (`15320965`) | đúng — đây là bằng chứng sạch nhất rằng #1-B chỉ khác A ở mô tả công cụ, và chỉ khác #1 ở một câu lời dặn |

Luật đặt trước (≥ 4/5 đọc dài VÀ ≥ 33/40 bài cũ) được áp đúng chữ, đạt, và **40 bài cũ đúng bằng ngưỡng**:
một bài lật theo chiều kia là trượt luật. REPORT nói thẳng điều này, tốt.

## Soát cách đọc của NV1

1. "Câu nhắc trong lời dặn là phần lớn lý do bài cũ tụt ở #1": ba điểm A 34 / #1 29 / #1-B 33 với đúng một
   biến đổi mỗi bước (hash chứng minh) ủng hộ cách đọc này. Giới hạn vẫn như cũ: mỗi phía một lần t0, và riêng
   mô tả công cụ đã xáo 39/40 câu, nên 33 so với 34 nằm trong vùng chưa đo được độ rộng.
2. doc-10 ở #1-B: **không tra, bịa mức phụ cấp "theo quy định hiện hành của Việt Nam"** với con số tự nghĩ;
   bộ chấm chỉ bắt được qua `tools_required` + `citation`, không có tiêu chí "cấm con số bịa". A cũng có
   32/36 `tools_required`, tức lớp lỗi "trả lời không tra" không mới, chỉ đổi bài. Nhưng đây là ví dụ rõ nhất
   tới nay của lớp lỗi đó, nên ghi vào ticket 23 (cột "bịa") và v0.4.
3. doc-25: hỏi xin phép thay vì tra — lớp lỗi 1a của ticket 10 quay lại ở một bài khác; cùng kết luận: không
   sửa bằng lời dặn nữa (ticket 10 đã đóng hướng đó).
4. doc-36 không gọi `read_document` lần này (ở #1 có gọi nhưng sai `from_chunk`): hai lần, hai cách trượt —
   bài này nhạy với prompt; đừng dùng nó làm bằng chứng cho công cụ.
5. r2 chạy khi dự án khác đang chờ GPU: câu trả lời r2 = r1 từng chữ nên thứ hạng/đạt-trượt không bị ảnh
   hưởng, và REPORT không dùng độ trễ r2 — xử lý đúng. Ghi chú quy trình: vòng lặp chạy nhiều lần nên kiểm
   tín hiệu nhường GPU **giữa** các lần, không chỉ trước lần đầu.

## Đề xuất cho v0.4 (không sửa bây giờ)

- Tiêu chí "bịa" rẻ và không cần liệt kê số: bài có `tools_required` mà agent không gọi công cụ **và** câu
  trả lời chứa con số/đơn vị tiền → đánh dấu "trả lời có số liệu mà không tra". Bắt được doc-10 hôm nay, và
  cho ticket 23 một cột "bịa" có nghĩa hơn `not_found` (xem review wip-23).
- Hai lỗi regex đã ghi ở review cd99811 (doc-12 "không thể tìm thấy"; regex riêng doc-19).

## Việc cho opus / chủ dự án

- Gộp được về mặt đo. **Ship #1-B hay không là quyết định của chủ dự án**, với ba cách: (a) ship theo luật đã
  đặt — ưu: đọc dài 0→4/5, bài cũ 33/34, luật đặt trước và đạt; nhược: đạt đúng ngưỡng, và một bài cũ bịa số
  liệu (lớp lỗi cũ). (b) làm (C) nhiều seed trước khi ship — ưu: biết dải dao động; nhược: ~8 phút GPU mỗi vòng,
  và ticket 10 cho thấy 40 bài vẫn khó tách chênh 1–2 bài. (c) ship + mở ngay tiêu chí "bịa" ở v0.4 để lần đo
  sau bắt được doc-10. Ý tôi: (c).
- Sau khi 23 gộp: `--append-history` cho 6 lần v0.3 (baseline r1/r2, read r1/r2, read-B r1/r2).

## Giới hạn của lượt duyệt

Không chạy lại model. Không đọc tay toàn bộ 48 câu; đọc doc-10, doc-25, doc-36 và tin cột "đọc tay" của NV1
cho phần còn lại.
