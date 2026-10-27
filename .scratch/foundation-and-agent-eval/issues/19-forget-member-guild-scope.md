# 19 — Bước 6 của `forget_member` xoá turn của thành viên ở MỌI guild

Status: chờ duyệt — Nhân viên của Ún 1, nhánh `wip/19-forget-member-guild-scope`
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

### 27/10 — Nhân viên của Ún 1: đã làm (trên main f23d5e8, đã có 17)

Bản chất: lệnh "quên tôi" giờ chỉ xoá ở server nơi người đó yêu cầu, ở mọi bước. Muốn xoá ở mọi server
thì phải nói rõ bằng một cờ riêng. Khi chạy thử, lệnh in ra nó sẽ xoá ở đâu và để lại gì ở các server khác.

Khảo sát: không chỉ bước 6. Bước 2 (nguồn ký ức do A viết) cũng xoá theo `source_author_id` ở mọi guild.
Bảng nguồn không có cột guild, nên tôi lọc nó theo guild của turn mà nguồn trích. Như vậy mọi nguồn trích
một turn mà bước 6 sắp xoá đều đi trước, đúng thứ tự RESTRICT.

- `_scope(model, guild)` là bộ lọc guild chung của mọi bước. Turn lấy guild của session, nguồn lấy guild
  của turn nó trích. Với `--all-guilds` thì không lọc.
- `--guild-id` vẫn bắt buộc, vì đó là nơi yêu cầu và được ghi trong output. `--all-guilds` mở rộng ra mọi
  guild mà A có dữ liệu (`_member_guilds`: tin nhắn kênh, turn, candidate, ký ức, mệnh đề).
- Bước 3 (dịch vụ condensation) chỉ nhận một guild, nên gọi lần lượt từng guild. Bước 8 (bản chép, ticket
  17) dò từng guild bằng chính lời A viết ở guild đó. Mọi lệnh xoá Postgres vẫn nằm trong MỘT transaction.
- Output có `scope`: `all_guilds`, `guilds` (các guild được xoá), `left_alone` (số dòng của A còn lại ở
  từng guild khác). `remaining` chỉ đếm trong phạm vi, nên phần để lại không làm exit 1.
- Tham số `all_guilds` của `forget()` mặc định False, chỉ dùng theo tên, nên các lời gọi cũ không đổi.

| Kiểm | Kết quả |
|---|---|
| `tests/test_forget_member_guild_scope.py` (DB, A có turn + tin nhắn ở X và Y): dry-run ở X nêu `left_alone` của Y; quên ở X thì Y còn nguyên; chạy lại với `--all-guilds` thì Y mất; `--all-guilds` ngay từ đầu thì cả hai mất; CLI chỉ mở rộng khi có cờ | 4 xanh |
| Cùng chạy test của 17 và condensation | 30 xanh |
| Kiểm ngược: bỏ lọc ở bước 6 / bỏ lọc ở bước 7 / cho `--all-guilds` không có tác dụng | 1/4 đỏ / 1/4 đỏ / 3/4 đỏ |

Giới hạn: test không dựng ký ức và nguồn, vì cần Qdrant. Việc lọc bước 2 theo guild của turn chỉ được kiểm
bằng đọc code. Nếu có nguồn nào trích chéo guild, lệnh xoá turn sẽ hỏng ồn ào và rollback cả transaction;
code ghi nguồn (`attach_source`) đã từ chối ghép chéo guild.
