GỘP ĐƯỢC

Duyệt commit `09e2658` nhánh `wip/30-docs-guild-gate` (worktree `local-ai-core-wt/30-docs-guild-gate`) theo spec
`issues/30-docs-guild-gate.md`. Chỉ đọc code và chạy test, không sửa gì.

## Bản chất

Trước commit này, bất kỳ server nào có bot đều gõ `/docs` được và thấy tên mọi tệp trong ô gợi ý. Commit này bắt bot hỏi
"người gõ đang ở server nào" trước khi đụng tới kho tài liệu, và dùng đúng danh sách server mà backend đã dùng cho công
cụ @Ún. Server không có trong danh sách, hoặc tin nhắn riêng, nhận một câu từ chối chỉ mình họ thấy và ô gợi ý trống.
Danh sách trống thì `/docs` tắt ở mọi server — đóng mặc định.

## Phải sửa trước khi gộp

Không có.

## Đáng ghi nhận (không chặn gộp)

1. **Một công tắc không đi cùng.** `backend/app/discord/turn_service.py:127-129` tắt mọi công cụ @Ún khi
   `DISCORD_AGENT_TOOLS_ENABLED=false`, bất kể danh sách. `docs_allowed` (`discord_bot/main.py:114-119`) chỉ nhìn danh
   sách. Hệ quả: đặt `DISCORD_AGENT_TOOLS_ENABLED=false` mà danh sách có server thì @Ún mất công cụ nhưng `/docs` vẫn
   chạy ở server đó. Spec chỉ yêu cầu danh sách nên đây không phải lỗi; tài liệu viết "cùng danh sách" là đúng chữ, nhưng
   dòng chú thích `.env.example:85-86` đọc như thể một chỗ điều khiển cả hai.
2. **Fake trong test rộng tay hơn thư viện.** `tests/test_discord_docs_guild_gate.py:44-48`: `FakeResponse.send_message`
   không ném `InteractionResponded` khi bị gọi lần hai (thư viện ném, `interactions.py:1056-1057`), và test gọi thẳng
   `.callback` / `_params["document"].autocomplete` (dòng 77, 84-85) nên bỏ qua `CommandTree._call` và bộ chuyển kiểu
   tham số. Logic cổng vẫn được chạy bằng hàm thật với closure thật; vòng đời "một lượt chỉ trả lời một lần" của Discord
   thì không. Không có test nào kiểm `document_lists == 0` khi server bị từ chối mà có truyền `document`; đọc code thì
   cổng đứng trước (`main.py:609`) nên `indexed_documents()` không với tới được.
3. **Dòng log lặp khi bot kết nối lại.** `on_ready` (`main.py:484-498`) chạy mỗi lần Discord gửi READY, không chỉ lần
   đầu, nên dòng `/docs is on in N server(s)` sẽ xuất hiện lại sau mỗi lần re-identify. Vô hại.
4. **CHANGELOG nói "ghi số server được bật"** (`CHANGELOG.md:18`); với `*` log ghi `/docs is on in every server`, không
   có con số. Sai lệch nhỏ về chữ.
5. **Bot chạy từ bảng điều khiển đọc `.env` bằng parser riêng.** `discord_bot/control.py:59-75` không cắt chú thích
   cùng dòng (`=111 # nhà`). python-dotenv mà pydantic-settings dùng thì cắt (đã chạy thử: `X=111 # nha` → `'111'`;
   `Y=*` → `'*'`); compose theo tài liệu cũng cắt, chưa chạy thử vì không bật Docker. Một dòng như vậy làm bot host nhận
   `{"111 # nhà"}` → `/docs` tắt, trong khi backend (và có lẽ bot compose) nhận `{"111"}`. Lỗi có sẵn của parser, áp
   dụng cho mọi biến, không do commit này.

## Đã kiểm bằng cách chạy

| Lệnh | Kết quả |
|---|---|
| `pytest tests/test_discord_docs_guild_gate.py` | 29 passed |
| `pytest tests` (toàn bộ thư mục gốc) | 124 passed, 1 skipped |
| `pytest backend/tests/test_compose_defaults.py` | 8 passed (khoá compose mới để trống nên không bị coi là default thứ hai) |

Điều kiện: env như brief (không Postgres/Redis test, Ollama trỏ cổng chết, CUDA ẩn). Không có GPU hay Ollama nào bị đụng.

Nghiệm thu "bài đỏ khi gỡ phần sửa" — lập luận, không chạy (đọc-chỉ):

| Gỡ gì | Test nào đỏ |
|---|---|
| cổng trong `docs` (`main.py:609-612`) | `test_docs_refuses_another_guild…`: `rag_questions` không rỗng, `deferred` thành True |
| cổng trong autocomplete (`main.py:572-573`) | `test_autocomplete_shows_no_filename…`: choices có tên tệp, `document_lists == 1` |
| dòng đọc biến trong `from_env` (`main.py:100-102`) | `test_settings_read_the_same_variable…` (mặc định dataclass vẫn là rỗng nên `…fail_closed…` không đỏ) |
| mặc định `frozenset()` đổi thành `None` ở `create_bot` / `DiscordSettings` | `test_create_bot_fails_closed…`, `test_settings_fail_closed…` |
| khoá trong `docker-compose.yml:149` | `test_the_compose_bot_receives_the_list` |
| ba dòng log `main.py:493-498` | `test_startup_log_says_how_many…` |

## Đã kiểm bằng cách đọc

**Đường tới tài liệu.** Đọc hết `discord_bot/main.py`. Chỉ `/docs` gọi `/rag/chat` (`api_client.py:197`) và `/documents`
(`api_client.py:250`). `/ask` và @mention đi `gateway.prepare`: đường cũ gọi `/chat` không có `use_tools`
(`api_client.py:566-574`), backend lúc đó không tìm tài liệu (`chat_service.py:124-151`, chỉ tìm trí nhớ; nhánh còn lại
của `/chat` khi không có công cụ, `routers/chat.py:88-94`, chỉ trả 422 cho tin quá dài); đường phiên bền
qua `enqueue_discord_turn`, backend tự kiểm danh sách (`turn_service.py:516`). Bộ đệm `documents_cache` chỉ được nạp bởi
`indexed_documents()`, mà cả hai chỗ gọi nó (autocomplete dòng 575, `/docs` dòng 619) đều đứng sau cổng. Chân trang nguồn
chỉ in sau khi `/rag/chat` trả về. Không còn đường nào cho server ngoài danh sách hay DM thấy nội dung hoặc tên tệp.

**Phân tích danh sách.** `main.py:106-111` giống từng ký tự với `backend/app/discord/__init__.py:76-84`: `strip()` rồi
so `*`; còn lại tách dấu phẩy, bỏ phần trống. Trống, toàn khoảng trắng, `,,`, chuỗi rác → tập rỗng → không server nào.
`*` lẫn trong danh sách (`*,111`) ở cả hai bên đều là phần tử thường, không phải "mọi server". Backend đọc cùng file
`.env` gốc (`settings.py:29`).

**Biến tới bot ở mọi cách khởi động.** `run-discord-bot.bat:44` chạy `docker compose --profile discord up` → compose
đọc `.env` cùng thư mục, khoá để trống ở `docker-compose.yml:149` nên biến không đặt thì vắng trong container và bot dùng
mặc định rỗng. `control.py:276-279` gộp `.env` vào môi trường tiến trình. Backend trong compose không có (chạy host).

**Thư viện discord.py 2.7.1** (`.venv/Lib/site-packages/discord/`):

| Giả định trong code | Nguồn thư viện | Kết luận |
|---|---|---|
| `Interaction.guild_id` là None trong DM, có giá trị trong server | `interactions.py:221` đọc thẳng `guild_id` từ payload; `:245-247` tạo guild tạm nếu chưa cache | đúng; cả tương tác autocomplete lẫn lệnh dùng cùng lớp |
| autocomplete được gọi `(interaction, value)` | `app_commands/commands.py:923`; hàm tự do không nhận binding (`:230-231`) | đúng; test gọi đúng chữ ký |
| trả `[]` là ô gợi ý trống | `commands.py:928` gửi `autocomplete([])` về Discord | đúng, là phản hồi rỗng thật, không phải im lặng |
| `send_message(ephemeral=True)` trước defer là riêng tư | `interactions.py:1059-1061` đặt `flags.ephemeral` trên phản hồi kiểu 4 | thư viện gửi đúng cờ |
| "Discord chốt ẩn/hiện lúc defer" | chỉ có docstring `interactions.py:847-848`: "whether the deferred message will eventually be ephemeral" | khớp với bình luận trong code, nhưng là hành vi máy chủ Discord, thư viện không chứng minh được |

## Không kiểm được

Không ai ở đây thử được trên Discord thật: câu từ chối có thực sự chỉ người gõ thấy, ô gợi ý có trống trên client, và
quy tắc "ẩn/hiện chốt lúc defer" (cũng là lý do các `followup.send(..., ephemeral=True)` sẵn có sau `defer` công khai ở
`main.py:622, 634` có thể đang hiện công khai — chuyện cũ, không thuộc commit này). CHANGELOG đã ghi đúng giới hạn này.
