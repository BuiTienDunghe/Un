# Brief: bộ test hồi quy chuẩn cho vùng lỗi của bản nhận xét thứ hai (10/11/2026)

Repo: `C:\Users\dungbt06\local-ai-core`, chạy trên Windows; Bash là Git Bash. Code là main `ed60401` cộng phần sửa lỗi B chưa commit trong cây làm việc (`backend/app/discord/history_service.py`, `backend/tests/test_source_memory_discord.py`). Code backend nằm ở `backend/app/`, test backend ở `backend/tests/`. Code bot nằm ở `discord_bot/`, test bot và các test gốc ở `tests/`.

## Mục tiêu

Chủ dự án muốn một **bộ test chuẩn**, bao gọn mọi tình huống có thể xảy ra ở các vùng dưới đây. Bộ test phải bắt được các lỗi đã biết, và chặn những lỗi cùng họ quay lại sau này. Quy trình gồm ba bước: Opus và Fable họp bàn để chốt kế hoạch test; Opus 5.5 viết bộ test; Fable 5.2 duyệt.

## Đọc trước

- `data/evaluation/results/kept/review2-second-opinion-20261110/brief-9-loi.md`: 9 lỗi, chỗ trong code, các hướng sửa.
- `.../review2-second-opinion-20261110/opus55-review.md` và `fable52-review.md`: hai bản duyệt độc lập, có thêm các lỗi mới.
- `docs/SO_DO.md`, các mục ngày 10/11 ở đầu tệp: những gì đã chạy để tái hiện và kết quả.
- `.../review2-second-opinion-20261110/test_tmp_*.py`: các test tạm đã dùng để tái hiện, dùng làm mẫu được.
- Test hiện có cần biết: `backend/tests/test_source_memory*.py` (fixture `v2client`, helper `send`/`queue`/`ledger`), `test_discord_history_service.py`, `tests/test_discord_api_client.py`, `tests/test_discord_progress_message.py`.

## Mã lỗi dùng trong kế hoạch và trong test

| Mã | Lỗi | Trạng thái |
|---|---|---|
| R1 | Reply Discord đọc `created_at` không tồn tại; lượt hỏng chặn kênh | chưa sửa |
| R2 | Vai trò admin lấy từ token (3 chỗ) | chưa sửa |
| R3 | Phát lại hoặc gửi lại đáp án của tin đã sửa/xoá | chưa sửa |
| R4 | "Nhớ" vẫn được lưu khi "quên" chen vào trước lúc chụp trạng thái (Web) | chưa sửa |
| R5 | Hai lần hạ quyền đồng thời làm hết admin | chưa sửa |
| R6 | Xoá job OCR đang chạy thì job hiện lại | chưa sửa |
| R7 | Xoá lịch sử OCR sau khi khởi động lại còn sót tệp; nguy cơ path traversal khi sửa | chưa sửa |
| R8 | DPI không giới hạn | chưa sửa |
| R9 | Bộ lọc trường OCR (luật đầu tiên; số quốc tế; nhãn; câu kích nhầm) | chưa sửa |
| A | Lượt mồ côi (5xx, timeout, giao tin hỏng, bot chết) chặn kênh | chưa sửa |
| B | Bot sửa/xoá tin của mình, hoặc sửa không đổi chữ, làm quên cả kênh | **đã sửa (cách a), chưa commit**; người sửa nội dung vẫn làm quên cả kênh, đây là thiết kế |
| C | `page_range` dựng hết tập trang trước khi kiểm biên | chưa sửa |
| D | Tải tệp OCR không giới hạn cỡ; render mọi trang vào RAM | chưa sửa |
| E | Job OCR không có chủ; thành viên đọc được job của người khác | chưa sửa |
| F | Trộn đồng hồ ứng dụng, Postgres, Discord khi so với mốc | chưa sửa |
| N2 | Reply không kiểm tombstone của tin gốc | chưa sửa |
| N4 | Thử lại lượt "quên" thì nhận câu "tin đã bị xoá/sửa" | chưa sửa |

## Quy ước bắt buộc

- **Lỗi chưa sửa:** viết test theo hành vi ĐÚNG, đánh dấu `@pytest.mark.xfail(strict=True, reason="review2 <mã>: <một câu>")`. Nhờ vậy bộ test vẫn xanh. Khi lỗi được sửa, test chuyển XPASS và `strict` làm bộ đỏ, nhắc người sửa bỏ dấu đi. Hành vi đang đúng thì test chạy bình thường. Không viết test khẳng định hành vi sai.
- **Chỉ tạo tệp mới**, không sửa tệp đang có:
  - `backend/tests/test_review2_<vùng>.py`;
  - `tests/test_review2_<vùng>.py` cho phía bot;
  - helper dùng chung, nếu cần, đặt ở `backend/tests/review2_support.py`.
- **Không** sửa code ứng dụng. Không commit, không push, không chạy git checkout/stash/reset.
- **Không** đọc `.env` và không in bí mật. Không khởi động API, bot hay Ollama thật. Không dùng GPU, không mở trình duyệt, không tải gì về.
- **Không** sửa `docs/SO_DO.md`. Ghi nhật ký chạy vào thư mục của brief này; phiên điều phối sẽ ghi sổ đo.
- **Môi trường test**, chỉ dành cho người viết và người duyệt, chạy lần lượt, không chạy song song:
  - Container dùng một lần, mỗi lần đặt tên mới với tiền tố `chk-r2t-`:
    - `docker run -d --rm --name chk-r2t-pg -p 55441:5432 -e POSTGRES_USER=local_ai -e POSTGRES_PASSWORD=$(cat "$TEMP/claude_check_pw") -e POSTGRES_DB=local_ai_core_test postgres:16-alpine`
    - `redis:7-alpine` trên `56381:6379`
    - `qdrant/qdrant:v1.18.2` trên `56334:6333`
  - Nạp biến môi trường: `source "C:/Users/dungbt06/AppData/Local/Temp/claude/ee2371d0a8cf6a43/e6e8417c-7768-4bfa-af3c-88aece6116c1/scratchpad/check-c57/env_fix.sh"`. Script này đặt `POSTGRES_TEST_URL`, `REDIS_URL`, đặt Ollama vào một cổng chết và ẩn CUDA.
  - Migrate từ gốc repo: `.venv/Scripts/python.exe -m alembic -c alembic.ini upgrade head`.
  - Chạy test backend: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/...`.
  - Chạy test gốc: `.venv/Scripts/python.exe -m pytest tests/...` từ gốc repo. Không chạy `pytest` trần ở gốc, vì nó sẽ gom cả bản sao repo trong `.scratch/`.
  - Chạy xong thì `docker stop` các container đã bật.
