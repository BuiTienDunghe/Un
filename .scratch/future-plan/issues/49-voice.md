# 49 — Giọng nói

Status: mở
Type: task
Blocked by: 41

Bản chất: bước đầu nhỏ nhất là nghe tin nhắn thoại Discord rồi đổi thành chữ, không phải vào kênh thoại hay đọc to.

Việc: khảo sát nguồn chính thống các model nghe tiếng Việt chạy trên máy, kèm dung lượng, VRAM và điểm công bố; code qua giao diện
có bản giả để test; mặc định tắt; model thoát khỏi card khi rảnh như decided. Dừng trước khi tải, trình chủ dự án các lựa chọn.

## Phải làm trước khi gắn model thật

Giới hạn 180 giây hiện chỉ kiểm ở bot, bằng `voice.duration` do máy của người gửi tự khai khi tải lên. Backend và cửa chỉ kiểm byte,
nên một tệp 8 MB dài hàng chục phút khai là 10 giây vẫn lọt tới card. Khi viết `_transcribe` thật (`tools/voice_server.py`) phải đo
thời lượng thật từ chính tệp ở model con hoặc ở cửa, và từ chối quá 180 giây bằng một câu trả lời lịch sự. Rà soát 82fceae, điểm 1.
