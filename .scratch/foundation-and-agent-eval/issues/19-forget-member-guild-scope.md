# 19 — Bước 6 của `forget_member` xoá turn của thành viên ở MỌI guild

Status: đã gộp vào main (28/10 00:05), fable 5.1 duyệt; còn một test bổ sung (lọc quá hẹp ở bước 2) theo gợi ý fable
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
- Output có `scope`: `all_guilds`, `guilds` (các guild được xoá), `left_alone` (số dòng ghi tên A còn lại
  ở từng guild khác; không đếm bản chép). `remaining` chỉ đếm trong phạm vi, nên phần để lại không làm exit 1.
- Tham số `all_guilds` của `forget()` mặc định False, chỉ dùng theo tên, nên các lời gọi cũ không đổi.

| Kiểm | Kết quả |
|---|---|
| `tests/test_forget_member_guild_scope.py` (DB, A có turn + tin nhắn ở X và Y): dry-run ở X nêu `left_alone` của Y; quên ở X thì Y còn nguyên; chạy lại với `--all-guilds` thì Y mất; `--all-guilds` ngay từ đầu thì cả hai mất; CLI chỉ mở rộng khi có cờ; ký ức về A ở Y (nguồn trích turn của A ở Y) còn nguyên khi quên ở X | 5 xanh |
| Cùng chạy test của 17, condensation và `test_discord_memory_foundation` | 68 xanh |
| Kiểm ngược: bỏ lọc bước 6 / bỏ lọc bước 7 / cho `--all-guilds` không có tác dụng / bỏ lọc nguồn ký ức | 1 đỏ / 1 đỏ / 3 đỏ / 1 đỏ (trên 4–5 test) |

Giới hạn: test chỉ dựng ký ức ở guild KHÔNG bị xoá. Xoá ký ức thật sẽ gọi Qdrant, mà test không có
Qdrant. Nếu có nguồn nào trích chéo guild, lệnh xoá turn sẽ hỏng ồn ào và rollback cả transaction; code
ghi nguồn (`attach_source`) đã từ chối ghép chéo guild.

Một lựa chọn để chủ dự án quyết: `--guild-id` vẫn bắt buộc cả khi có `--all-guilds`, để output ghi nơi
người đó yêu cầu. Cách khác là cho hai cờ loại trừ nhau. Đổi thì chỉ sửa phần đọc tham số.
- 28/10 00:05 (opus 5.5): gộp. Cờ: giữ (i) — `--guild-id` bắt buộc kể cả khi có `--all-guilds`, để output
  luôn ghi nơi người đó yêu cầu (fable đồng ý). Test bổ sung theo fable: nguồn do A viết trích turn của A
  ở X nhưng ký ức VỀ B; quên A ở X → nguồn mất ở bước 2, turn của A xoá được ở bước 6, ký ức về B còn —
  bắt lọc QUÁ HẸP mà các kiểm ngược hiện có không bắt.

### 27/10 — Nhân viên của Ún 1: test bổ sung theo fable (sau khi gộp)

Các kiểm ngược trước chỉ bắt bộ lọc nguồn QUÁ RỘNG. Test mới bắt bộ lọc QUÁ HẸP. Dữ liệu: ký ức về B ở X,
gốc từ turn của chính B, và có thêm một nguồn phụ do A viết, trích turn của A ở X. Quên A ở X thì nguồn
của A mất ở bước 2, candidate và turn của A xoá được ở bước 5–6, còn ký ức về B và nguồn của B ở lại.

| Kiểm | Kết quả |
|---|---|
| `test_forget_member_guild_scope.py` (6) + 17 + condensation + `test_discord_memory_foundation` | 69 xanh |
| Kiểm ngược: lệnh xoá ở bước 2 không khớp nguồn nào (phần đếm giữ nguyên) | chỉ test mới đỏ, `IntegrityError` ở bước 5 (`fk_discord_memory_sources_candidate`); 5 test cũ xanh |

Thử ngoài lề, không commit: nếu ký ức về B có GỐC là candidate của A, thì quên A sẽ hỏng ở bước 5
(`fk_discord_memories_origin_candidate`). Phần Postgres rollback, nhưng bước 1 và 3 đã chạy ngoài
transaction. Đường trích ký ức hiện không sinh ra được trường hợp này, vì chủ thể duy nhất được tin là
chính người viết (`discord_memory_extractor.py:319-326`); chỉ cơ sở dữ liệu là không chặn.
- 28/10 00:15 (opus 5.5): gộp test bổ sung 66aba69 (lọc quá hẹp ở bước 2). Rủi ro Nhân viên 1 tìm thêm:
  ký ức về B có GỐC là candidate của A thì "quên A" hỏng ở bước 5 (`fk_discord_memories_origin_candidate`);
  Postgres rollback nhưng bước 1 (Qdrant) và bước 3 (condensation) đã chạy ngoài transaction → trạng thái
  làm dở. Hiện không xảy ra qua đường thường (extractor chỉ tin chủ thể là chính người viết,
  `discord_memory_extractor.py:319-326`). Chọn (a): để nguyên, ghi thành rủi ro; mở lại nếu có đường ghi
  ký ức mới (vd admin).
