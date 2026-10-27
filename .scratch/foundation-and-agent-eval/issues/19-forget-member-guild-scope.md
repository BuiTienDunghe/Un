# 19 — Bước 6 của `forget_member` xoá turn của thành viên ở MỌI guild

Status: đã chốt (chủ dự án 27/10 23:30): chỉ server nơi yêu cầu; quên mọi nơi bằng cờ --all-guilds tường minh. Làm sau 17 (Nhân viên của Ún 1)
Type: task
Blocked by: 17 (cùng file `backend/scripts/forget_member.py`)

## Vì sao

Nhân viên 1 nêu, fable xác nhận (27/10): mọi bước khác của `forget_member` lọc theo guild, riêng bước 6
xoá turn theo `author_id` không lọc guild. Người dùng yêu cầu "quên tôi" ở server X thì lượt hỏi của họ ở
server Y cũng mất. Xoá thừa an toàn hơn xoá sót, nhưng trái phạm vi của lệnh và không ai được báo.

## Việc

Lọc bước 6 theo guild như các bước khác; dry-run in số turn sẽ xoá theo guild; test Postgres: A có turn ở
hai guild, quên A ở guild X, turn ở guild Y còn nguyên. Nếu chủ dự án muốn giữ hành vi "quên ở mọi nơi",
thì đổi thành một cờ tường minh (`--all-guilds`) thay vì mặc định ngầm — hỏi trước khi code.

## Comments
- 27/10 23:30 (chủ dự án): "quên tôi" chỉ xoá trong server nơi người đó yêu cầu. Muốn quên mọi nơi thì
  dùng cờ `--all-guilds` tường minh. Cờ phải áp cho **mọi** bước, không riêng bước 6; dry-run in rõ phạm vi.
