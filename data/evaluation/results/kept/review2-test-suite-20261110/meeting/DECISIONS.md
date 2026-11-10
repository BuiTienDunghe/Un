# Chốt sau vòng 2 (phiên điều phối, 10/11/2026)

Hai bên đồng ý phần lớn. Dưới đây là những điểm đã chốt, để bản kế hoạch chung theo đúng. Các điểm thuộc thẩm quyền chủ dự án được ghi riêng ở cuối và để ngoài bộ test.

## Nguyên tắc

1. **Chấp nhận `raises=KnownBug`.** Phiên điều phối đã duyệt, vì brief do phiên này viết. Chủ dự án sẽ được báo và có thể đổi lại.
   - Viết `@pytest.mark.xfail(strict=True, raises=KnownBug, reason="review2 <mã>: …")`.
   - `KnownBug` chỉ được ném ở dòng kiểm triệu chứng của lỗi đã biết.
   - Riêng R1: chỉ bắt đúng `AttributeError` tại lời gọi execute rồi đổi thành `KnownBug`. Không dùng `raise_server_exceptions=False` cho ca đó.
   - Tham số nào đang sai thì mới mang dấu, qua `pytest.param(..., marks=...)`.
2. **Kiểm kết quả, không kiểm cơ chế.** Một ca xfail phải lật sang đạt với MỌI cách sửa hợp lệ. Ca không viết được như vậy thì đưa vào danh sách "để ngoài", kèm lý do.
3. **Vá tạm để thấy XPASS.** Với mỗi ca xfail, người viết thử vá bằng `monkeypatch` trong một lần chạy tạm, không sửa tệp ứng dụng, và ghi lại rằng ca đó lật. Ca nào không vá được thì ghi rõ trong nhật ký.
4. **Mức tích hợp cho A.** Nối bot thật (`DiscordConversationGateway` + `LocalAgentClient`) với app thật qua `httpx.ASGITransport`, Discord giả. Ca A kiểm kết quả: "tin thường gửi sau một lượt mồ côi được trả lời trong hạn chờ".
   - Người viết phải chứng minh cách nối này chạy được trước khi viết ca A.
   - Nếu không nối được: ca A ở mức bot để ngoài; ca backend "lượt sau chạy" vẫn giữ, nhưng ghi rõ nó chỉ lật khi sửa ở backend.
5. **Cách giả lập:**
   - Đồng hồ: lệch ±30 giây, chỉ phía ứng dụng. Có cả chiều "ứng dụng nhanh", vì chiều này làm chữ đã quên lọt lại.
   - Bot chết: để `recover_stale` chạy trước, rồi lùi mọi cột giờ.
   - R5: dùng `Barrier(2)`, bọc `_public`.
   - Path traversal: gọi HTTP với `%2e%2e` và `..%5C..%5Cx`, đồng thời gọi thẳng `service.delete(...)`.
   - Mọi ca E chạy trên `client` thật với `auth_on`, không chạy trên app nhỏ.

## Kỳ vọng đã chốt

| Tình huống | Kỳ vọng |
|---|---|
| Lỗi bất ngờ khi chuẩn bị lượt (mã **A**, không phải R1) | Không trả 5xx. Sau tối đa `max_attempts` lần gọi lại, lượt kết thúc và lượt sau chạy được |
| Admin bị hạ quyền dùng token cũ | Nhận 401, 403 hoặc 404, và không thấy nội dung của người khác. R2 tách ba tham số: danh sách hội thoại, mở một hội thoại, dự án |
| Xoá job OCR đang chạy | Hợp lệ khi (a) job và tệp hết sạch sau khi worker dừng, hoặc (b) trả 409 và job còn nguyên. Bất biến: không bao giờ trả 204 rồi job lại hiện ra |
| Windows giữ tệp khi xoá | Kiểm trạng thái cuối: sau khi đóng tệp, xoá lại một lần (hoặc khởi động lại rồi xoá) thì không còn tệp nào |
| Người sửa nội dung tin (B, phía người) | Chỉ kiểm chữ cũ không vào prompt. Không kiểm phần lịch sử còn lại của kênh còn hay mất |
| Đồng hồ ứng dụng nhanh; snowflake lệch (F) | xfail F. Ghi trong `reason` đánh đổi: nếu so theo giờ nhận, tin gửi trước nhưng tới muộn sẽ lọt |
| N4-1 | Có biên nhận "đã quên", nguồn bị quên đúng một lần, và không có câu "tin đã bị xoá/sửa". Thêm N4-2: lượt "quên" đã lưu đáp án, giao hỏng, thử lại |
| C-1 | `1-1000000`, dưới 8 MiB |
| A-5 `cancel-open` | Giữ, ca đang đạt |

## Bỏ (trùng hoặc va test đang có)

- A-1, A-7: trùng test đang có.
- Biến thể timeout của A-8: `tests/test_discord_progress_message.py:294` đang ghim "timeout thì báo lỗi, không thử lại".
- B-3 ở mức backend: backend không biết lệnh xoá đến trước khi tin vào sổ là của ai.

## Để ngoài bộ test, chờ chủ dự án (ghi trong kế hoạch, kèm lý do)

- **R4-1:** điểm chèn lệnh "quên" phụ thuộc chọn 4a hay 4b.
- **D-1:** trần cỡ tệp OCR chưa được chọn.
- **D-2:** thứ tự render là cơ chế; kiểm tay.
- **R2-3:** dự án do admin tạo không có chủ, nên bị hạ quyền là mất dự án.
- **E-3:** job không chủ thì ai được xem.
- **B-4, B-5:** người khác sửa tin trong lúc một lượt đang chờ. Hiện lượt đó nhận câu "tin này đã bị xoá/sửa", nói sai với người hỏi.
- **"Người sửa tin làm Ún quên cả kênh":** là thiết kế hiện tại; có ghim bằng test hay không là việc chủ dự án quyết.
