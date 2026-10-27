# 18 — `test_debt_t1_t2_t3` tự kẹt (deadlock) lúc dọn dẹp

Status: đã giao — Nhân viên của Ún 1
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
