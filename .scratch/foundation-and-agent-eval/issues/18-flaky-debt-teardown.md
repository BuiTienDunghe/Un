# 18 — `test_debt_t1_t2_t3` tự kẹt (deadlock) lúc dọn dẹp

Status: chờ duyệt — Nhân viên của Ún 1, nhánh `wip/18-flaky-debt-teardown`
Type: task
Blocked by: —

## Vì sao

`tests/test_debt_t1_t2_t3.py::test_t3_successful_replace_commits_hash_and_run_together` báo ERROR lúc
teardown: `psycopg.errors.DeadlockDetected ... while deleting tuple ... in relation "documents"`, hai
tiến trình Postgres chờ nhau. 27/10 nó đỏ hai lần trong bộ đầy đủ (sau gộp 12, sau gộp 16). Lần đầu điều
phối đổ cho việc chạy chen của một phiên khác — **sai**: chạy riêng file đó 3 lần liền lúc 22:45, không ai
khác dùng DB test, vẫn đỏ 1/3. Lỗi có từ trước ticket 16 (lần đầu lúc 17:59).

## Việc

Tìm hai kết nối nào cùng xoá `documents` trong teardown (fixture hay code test để lại một transaction/
session mở), sửa để không còn deadlock. Chạy file đó ít nhất 10 lần liền: 0 lỗi. Không đổi code sản phẩm
trừ khi chứng minh được lỗi nằm ở đó (khi đó dừng, báo điều phối trước).

## Comments

### 27/10 — Nhân viên của Ún 1

Bản chất: bài test cho thay một tài liệu, và việc thay đó khởi động một công việc chạy ngầm (đọc lại
và lập chỉ mục tài liệu). Bài test xong việc của nó là đi dọn ngay, trong khi công việc ngầm vẫn đang
ghi vào đúng những dòng đang bị xoá. Hai bên giữ khoá theo thứ tự ngược nhau, nên thỉnh thoảng chờ
nhau mãi, và Postgres phải giết một bên. Cách sửa: dọn dẹp chờ công việc ngầm của chính bài test đó
xong rồi mới xoá. Code sản phẩm không có lỗi; lỗi nằm ở test.

Hai kết nối đó là:
1. Teardown của fixture `debt_cleanup`: một transaction xoá `jobs` → `document_chunks` →
   `ingestion_runs` → bỏ `active_version_id` → `document_versions` → `documents`.
2. Luồng daemon `_run_index` của API (`postgres_document_service.py:373`). Backend thực thi mặc định là
   `"thread"` (`settings.py:51`), và `replace_source` bật luồng này để index lại. Bước kích hoạt của nó
   cập nhật `documents`, `document_versions`, `ingestion_runs` trong một transaction riêng.

`debt_cleanup` được dựng sau `client`, nên bị dọn TRƯỚC. Lúc nó xoá, app vẫn chạy, và luồng nền vẫn
đang ghi.

| Đo | Kết quả |
|---|---|
| Tái hiện trước khi sửa: chạy riêng bài t3 15 lần | 1/15 đỏ, `DeadlockDetected` |
| Chẩn đoán tạm: luồng index còn sống lúc teardown bắt đầu xoá (dòng in đã gỡ) | bài t3: 5/5 lần còn sống; bài t1 upload: không sinh luồng |
| Sau khi sửa: cả file 20 lần liền | 0/20 đỏ |
| Sau khi sửa: riêng bài t3 45 lần liền | 0/45 đỏ. Tổng 65 lần sạch liền; với tỉ lệ cũ 1/15, xác suất đó chỉ do may là (14/15)^65 ≈ 1,1% |

Sửa (chỉ trong test): `debt_cleanup` thay biến `threading` của riêng module `postgres_document_service`
bằng một lớp proxy, ghi lại mọi luồng nhắm `_run_index`. Teardown `join` các luồng đó (tối đa 60 s)
trước khi xoá. Còn luồng nào chạy quá hạn thì assert hỏng với lời nói rõ, thay vì xoá chen vào. Không
vá `threading.Thread` của cả tiến trình, vì TestClient và anyio cũng tạo luồng.

Rà thêm: trong `backend/tests/`, chỉ file này vừa sinh luồng index nền vừa tự xoá thẳng dòng `documents`.
Các file khác dọn qua endpoint xoá của API.
