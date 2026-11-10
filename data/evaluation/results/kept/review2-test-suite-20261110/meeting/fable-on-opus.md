claude-fable-5-2

# Fable phản biện kế hoạch của Opus — vòng 2

**Bản chất:** hai bản trùng nhau ở phần lớn ca và ở cách cô lập lỗi. Chỗ cần chốt là vài kỳ vọng mô tả *cách sửa* thay vì *kết quả*, và việc lỗi A chỉ nhìn thấy trọn vẹn khi bot và backend chạy cùng nhau.

## 1. Nguyên tắc

| Điểm | Ý kiến | Lý do |
|---|---|---|
| `raises=KnownBug` | **Đồng ý, nên duyệt** | `raises=AssertionError` của tôi yếu hơn: một `assert` hỏng ở bước chuẩn bị cũng được tính là xfail. `KnownBug` chỉ ném ở dòng kiểm triệu chứng. Nó chỉ thêm tham số, không đổi dạng dấu của brief |
| Bắt crash R1 rồi đổi thành `KnownBug` | Đồng ý, kèm điều kiện | Chỉ bắt đúng `AttributeError` tại lời gọi execute; bắt `Exception` thì lỗi khác cũng thành "lỗi đã biết" |
| Vá tạm để thấy XPASS | Đồng ý, cần nói rõ | Vá bằng `monkeypatch` trong một test tạm, không sửa tệp ứng dụng (brief cấm). Ca không vá được thì chạy không dấu và chép dòng lỗi |
| Đồng hồ ±30 giây, không ghi tay mốc | Đồng ý, lấy 30 giây thay 10 phút của tôi | Cùng cách; Opus thêm chiều **ứng dụng nhanh**, là chiều làm lộ chữ đã quên, tôi mới để "?" |
| R4 chờ 50 ms trước khi quên | Đồng ý | Tôi thiếu: không chờ thì lệch vài mili giây làm mốc nhỏ hơn giờ gửi, test đỏ xanh theo may |
| R5 bọc `_public` bằng `Barrier(2)` | Đồng ý, lấy thay hook SQL của tôi | Đơn giản hơn và không dò chuỗi SQL. Nếu bản sửa đổi tên hàm thì test đỏ rõ ràng, chấp nhận được |
| Bot chết bằng lùi lease | Đồng ý | Giống nhau |
| `%2e%2e` | Đồng ý, **thêm** lời gọi thẳng `service.delete("..")` | Việc gộp `/..` là hành vi của client thử; client thật và proxy có thể khác. Lớp service không phụ thuộc điều đó |
| E trên app nhỏ, tiêm danh tính | **Không đồng ý** | Nếu R2 sửa bằng "đọc lại vai trò từ database", app không có database có thể trả 401 cho cả thành viên. Đưa mọi ca E lên `client` + `auth_on` |

## 2. Ca của Opus nên đưa vào bản chung

- **R3-3**: gửi lại khi mốc đã dời trả câu cố định (đang đúng, phải giữ).
- **A-3**: lease hết, bot gọi lại chính lượt đó thì gửi lại đáp án đã lưu, không gọi model lần hai.
- **F-1, F-4**: ứng dụng nhanh 30 giây làm chữ đã quên quay lại (Discord và Web).
- **R6-2, R7-2**: xoá job đã xong; khởi động lại, mở job rồi xoá.
- **R7-4**: `root` lưu trong database trỏ ra ngoài thư mục OCR.
- **E-1** phần huỷ và promote job của người khác.
- **R9-1** cả hai thứ tự; **R9-2** dạng `(84-28)…`.
- **D-2** bản 4 trang thay bản 30 trang của tôi (rẻ hơn, cùng ý).
- Ghi chú của Opus về `test_discord_progress_message.py:294` (timeout đang được ghim là "báo lỗi, không thử lại"): ca A-8 của tôi phải bỏ biến thể timeout.

## 3. Ca nên bỏ hoặc sửa

| ID (Opus) | Vấn đề | Đề xuất |
|---|---|---|
| R2-1 | Gộp ba chỗ vào một test: sửa hai trong ba chỗ vẫn xfail, không ai biết | Tách ba tham số (danh sách hội thoại, mở hội thoại, dự án) |
| N4-1 | Chỉ kiểm phủ định; một bản sửa trả câu rỗng cũng đạt | Thêm: prompt có biên nhận "đã quên", và nguồn bị quên đúng một lần |
| (thiếu) | Lượt "quên" đã lưu đáp án, giao hỏng, thử lại: nhánh này trả câu "Nguồn trí nhớ đã được sửa…" (`turn_service.py:649`), khác nhánh N4-1 | Thêm N4-2 của tôi |
| B-3 | Backend không thể biết lệnh xoá đến trước là của bot hay của người; kỳ vọng "mốc không dời" sai với tin người chưa vào sổ | Bỏ ở mức backend. Nếu giữ thì viết ở mức bot: bot không chuyển lệnh xoá tin của chính nó |
| B-4, B-5 | Cột "Thì" là "?": chưa phải test | Để ngoài bộ, ghi vào danh sách chờ chủ dự án. Tôi rút B-5 của mình (tôi đã ghim hành vi hiện tại) |
| R7-5 | "Không trả 204" là một cách sửa; dọn sau cũng hợp lệ | Xem mục 4 |
| D-1 | Chỉ kiểm cỡ **khai báo**; bản sửa tin vào cỡ khai báo vẫn đạt | Thêm biến thể khai nhỏ nhưng luồng thật lớn |
| A-1 | "hoặc lượt mồ côi `failed`" là cơ chế | Chỉ giữ "lượt sau chạy" |
| R1-4 | "lần 3 thành `failed`" là cơ chế | Xem mục 4 |
| E-3 | "Chỉ admin thấy job không chủ" là một lựa chọn thiết kế | Đánh dấu chờ quyết, không viết vội |

Ca của tôi nên bỏ vì trùng test đã có: A-7 (execute trùng).

## 4. Mâu thuẫn kỳ vọng

| Tình huống | Opus | Fable | Đề xuất chốt |
|---|---|---|---|
| Lỗi bất ngờ khi chuẩn bị lượt | không 500, lần 3 `failed` | không 5xx, lượt không nằm `running` | "Không 5xx; sau tối đa `max_attempts` lần gọi lại, lượt kết thúc và lượt sau chạy" |
| Xoá job OCR đang chạy | sạch, **hoặc** 409 và job nguyên | phải sạch | Theo Opus (hai cách sửa đều hợp lệ), thêm bất biến: không bao giờ 204 rồi job hiện lại |
| Windows giữ tệp khi xoá | không trả 204 | xoá lại thì sạch | Kiểm trạng thái cuối: sau khi đóng tệp, một lần xoá nữa hoặc khởi động lại rồi xoá thì không còn tệp nào |
| Snowflake lệch (F-3) | xfail F | "?" | Theo Opus, nhưng ghi rõ: so theo giờ nhận thì tin gửi trước, tới muộn sẽ lọt. Đây là đánh đổi cần chủ dự án biết |
| Người sửa tin khi lượt người khác đang chờ | "?" | đạt (ghim) | Để ngoài bộ |
| Trần bộ nhớ C-1 | `1-1000000`, < 8 MiB | `1-300000`, < 1 MiB | Theo Opus |

## 5. Ca phụ thuộc thiết kế

**Đồng ý với hướng "kiểm kết quả, không kiểm cơ chế"**, kèm ba ý.

1. **A cần một mức test mới thì mới kiểm được kết quả.** Sửa ở bot thì test backend không thấy; sửa ở backend thì test bot với `FakeBackend` không thấy. Chỉ có test nối `DiscordConversationGateway` + `LocalAgentClient` thật vào app thật (qua `httpx.ASGITransport`), Discord giả, mới đúng với mọi cách sửa: "tin thường gửi sau một lượt mồ côi được trả lời trong hạn chờ". Tôi **chưa kiểm** cách nối này có chạy được không (hai gốc import, app đồng bộ). Nếu không nối được, để A-4, A-5 của Opus ngoài bộ; ca backend "lượt sau chạy" vẫn giữ nhưng ghi rõ nó chỉ lật khi sửa ở backend.
2. **R4 không viết được theo hướng này.** Điểm chèn "trước `snapshot`" chỉ là "sau giờ gửi" với cách 4a. Với 4b, giờ gửi lấy trong chính giao dịch đó, nên lệnh quên chèn vào là lệnh quên đến trước và việc lưu là đúng: test không bao giờ xanh. Đua thật bằng hai luồng thì theo may. Đề xuất để R4-1 ngoài bộ tới khi chọn cách sửa. Kỳ vọng "biên nhận Chưa lưu" của Opus cũng là chữ của một cách sửa.
3. **B-người-sửa:** chỉ kiểm điều đúng với mọi thiết kế: chữ cũ của tin đã sửa không vào prompt. Không kiểm phần còn lại của lịch sử kênh còn hay mất. Nghĩa là B-2 của Opus và B-3 của tôi phải nới lại.

Áp vào các mã còn lại:
- **R2:** viết được, ba cách sửa đều làm test lật. R2-3 (dự án chủ rỗng) để ngoài.
- **D:** D-1 viết được nếu tệp giả đủ lớn để vượt mọi trần hợp lý. D-2 là cơ chế (bản sửa giới hạn số trang sẽ không làm nó lật): để ngoài, kiểm tay.

Ca "đang đúng, chặn bản sửa ẩu" (R7-3, R9-4) không phụ thuộc thiết kế, giữ nguyên.
