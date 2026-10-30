GỘP ĐƯỢC

# Duyệt wip/35-agent-memory-web 6556dde (main feacc87..HEAD, ticket 35) — fable 5.1, 30/10/2026

Với cấu hình mặc định như commit này ship, người lạ không ghi được trí nhớ và không chạm được vào máy: công cụ web
tắt (`AGENT_WEB_TOOLS_ENABLED=false`), còn `remember` chỉ chạy trong guild được phép, chỉ khi chính người nói dặn
nhớ trong tin đó, chỉ ghi bằng lời của họ, và thu hồi được trên màn hình Ghi nhớ. Không tìm được lỗi làm hỏng đường
chạy thường. **Hai mục đầu phần "Sửa trước khi bật" phải xong trước khi đặt `AGENT_WEB_TOOLS_ENABLED=true`**; các mục
còn lại là lựa chọn của chủ dự án.

## Bản chất

Ún có thêm hai khả năng. Một: khi ai đó nói "hãy nhớ…", Ún ghi điều đó vào sổ trí nhớ của server, nhưng chỉ nếu chính
tin nhắn của người ấy có lời dặn, và câu ghi phải lắp từ chữ và số người ấy vừa gõ — nên chữ trong ảnh, tài liệu hay
trang web không tự chui vào sổ được. Điều đã ghi được áp dụng ngay, không chờ ai duyệt, và cả server thấy nó trong
mọi câu trả lời sau; màn hình Ghi nhớ hiện nó và có nút thu hồi. Hai: Ún tìm trên mạng rồi đọc trang, nhưng chỉ mở
đúng những địa chỉ mà lần tìm vừa trả về hoặc người dùng tự gõ, và từ chối địa chỉ nội bộ. Rủi ro còn lại nằm ở ba
chỗ: địa chỉ mà bot chép ra từ ảnh đính kèm cũng được tính là "người dùng viết"; một trang nhỏ giọt mãi không hết có
thể giữ một lượt treo vô hạn; và việc "nhớ" là tự áp dụng, không qua người duyệt như bộ trích trí nhớ hiện có.

## Đã kiểm

| Việc | Cách | Kết quả |
|---|---|---|
| Test của nhánh + eval + register | 4 tệp, env coordinator cho, không DB, không mạng | 177 xanh, 2 skip (2 test cần DB) |
| Băm công cụ của agent-eval | đọc `scripts/agent_eval.py:417-434` | eval dựng `core_tools()` + `search_history` riêng; diff không chạm `core_tools`/`agent_tools.py` → `tools_sha256` không đổi theo cấu tạo; test `test_the_core_list_the_evals_grade_has_no_web_tool` xanh |
| HTMLParser treo trên HTML độc | 20 mẫu 2 MB: `<!--`×500k, `<`×2M, `<a b='x c='y`…, `&amp;`×400k, `<div>`×400k, `<![CDATA[`… trên Python 3.11.9 | chậm nhất 2,24 s (`<`×2M), không ngoại lệ |
| Trần kích thước | đọc `fetch_page:176-181` | `iter_bytes` dừng ở 2 MB byte đã giải nén; đúng |
| Trang không bao giờ hết | đọc `fetch_page`, `agent_service.run:395`, `turn_service:605-638`, `api_client.py:47` | **không có hạn giờ tổng** (mục S1) |
| `public_address` với host literal | 13 URL, `getaddrinfo` cục bộ không cần DNS | `127.0.0.1`, `[::ffff:127.0.0.1]`, `[::ffff:7f00:1]`, `2130706433`, `0x7f000001`, `127.1`, `0177.0.0.1`, `[::1]`, `0.0.0.0`, `169.254.169.254`, `:8000` đều bị chặn; `[64:ff9b::7f00:1]` (NAT64) lọt — máy này không có NAT64 |
| Phân giải tên hai lần | đọc `public_address:154` + httpx tự resolve khi connect | DNS rebinding có thể qua (mục S3); chỉ tới cổng 80/443 |
| Chuyển hướng | `test_a_redirect_to_this_machine_is_stopped` + đọc vòng lặp | kiểm lại từng bước, `//host` và `file:` bị chặn, tối đa 3 bước |
| charset lạ | `httpx.Response(... charset=bogus-xyz).encoding` | về `utf-8`, không `LookupError` |
| `web_urls` và tin Discord | `attributed_user_content:113` + `question_with_images:137` + regex `agent_service.py:365` chạy trên tin mẫu | **URL trong mô tả ảnh vào `web_urls`** (mục S2); tin trả lời (reply target) nằm trước tin cuối nên không ảnh hưởng; đoạn dán dài thành slip → mất URL (an toàn hơn) |
| Cổng `remember` | 11 câu qua `asked_to_remember`, 4 cặp qua `fact_is_their_own` | câu hỏi "Bạn nhớ giúp tôi với nhé…" = có dặn; đảo phủ định và đảo chủ ngữ qua được (mục N1) |
| Ràng buộc DB | đọc `models.py:679-724, 811-850, 1053-1058`, `discord_memory_constants.py` | `candidate`, `explicit_remember`, `deferred`, `create`, `member_in_guild` đều trong CHECK; `memory_type`/`subject_type`/`fact_key` không CHECK; `memories.memory_type` String(64) → `"fact"` qua gương web |
| Idempotency với worker trí nhớ | `uq_discord_memory_candidate_turn_schema` = (turn, schema); worker dùng schema v3, tool dùng `agent-remember-v1` | không đụng khoá; trùng chỉ khi bộ trích bật (mặc định tắt) → có thể hai trí nhớ cùng ý khác `fact_key` |
| Giao dịch qua lời gọi embedding | `remember_tool.py:96-129`, `approve:187-256` | `approve` gọi SAU khi `with sessions.begin()` đóng; `approve` tự commit rồi mới embed; mọi `return` sớm trong `with` xảy ra trước flush nào |
| Màn hình Ghi nhớ | `memory_review_service.list_applied:135-138`, `memory.js:520, 780-786` | hàng `decision=applied`, `status=active` hiện trong "đang hiệu lực" với nhãn "👤 agent_remember" (biểu tượng người, chỉ "agent" mới được robot), có nút thu hồi; nếu `approve` hỏng giữa chừng, hàng `deferred` có `canonical_fact` hiện ở tab Chờ duyệt |

## Chặn

Không có.

## Sửa trước khi bật `AGENT_WEB_TOOLS_ENABLED`

**S1. `web_tools.py:160-182` — không có hạn giờ tổng.** `timeout=10` của httpx là từng thao tác đọc; máy chủ nhả 1
byte mỗi 9 giây không bao giờ vi phạm. `call_within` ở `agent_service.py:395` chỉ bọc lời gọi model, công cụ nằm
ngoài ngân sách 90 s. Kịch bản: một thành viên gửi URL nhỏ giọt và nói "đọc cái này" → luồng của lượt treo; heartbeat
(`turn_service.py:605-611`) giữ lease nên lượt không được xếp lại; bot bỏ cuộc sau 360 s (`api_client.py:47`) nhưng
luồng backend vẫn kẹt, mỗi tin như vậy chiếm một luồng trong pool ~40 của endpoint đồng bộ. Hình dạng sửa: mốc giờ
tổng quanh vòng `iter_bytes` (và quanh `httpx.post` của `web_search`), ví dụ 15 s, vượt thì `ValueError`.

**S2. `agent_service.py:365` — `web_urls` đọc cả ghi chú ảnh.** Tin Discord tới agent là
`[Người đang hỏi…]\n{request_text}`, mà `request_text` đã dán `[Ảnh đính kèm …: {mô tả của model vision}]`
(`discord_bot/main.py:137`). Đã chạy regex trên tin mẫu: `https://attacker.example/beacon?id=7` nằm trong mô tả ảnh
vào thẳng `web_urls`. Kịch bản: ảnh chứa dòng chữ URL + "mở link này" → Ún GET địa chỉ kẻ tấn công chọn. Tác hại thật:
URL cố định trước (không mang dữ liệu lượt ra ngoài), GET, nhận về ≤ 6 000 ký tự đã dán nhãn dữ liệu — nên không chặn,
nhưng câu CHANGELOG "chỉ mở được url … người dùng tự viết" và docstring đầu `web_tools.py` sai với code. Khó về cấu
trúc: `run()` **ghi đè** `web_urls` thay vì gộp như `readable_documents`, nên tầng Discord không lọc trước được.

| Cách | Ưu | Nhược |
|---|---|---|
| A. `run()` gộp `web_urls` do caller đưa; `turn_service` tự tính từ `request_text.split(IMAGE_NOTE)` | đúng tầng: Discord biết ghi chú ảnh là gì | thêm một chỗ phải nhớ cập nhật khi đổi định dạng ghi chú |
| B. Core cắt `IMAGE_NOTE` ngay tại `agent_service.py:365` | một dòng | core biết một chuỗi của bot Discord, trái tinh thần ticket 22 |
| C. Bot gửi chữ trong ảnh ngoài băng (trường riêng), không dán vào câu hỏi | gốc rễ: `request_text` sạch, bộ trích trí nhớ cũng không đọc được chữ ảnh (mục 3 bản duyệt 31–34) | đổi schema turn + API + bot; lớn hơn ticket này |

Tôi nghiêng về A cho lần này và C khi làm lại đường ảnh — là ý kiến.

**S3. `web_tools.py:145-157` — phân giải tên hai lần.** `public_address` gọi `getaddrinfo`, rồi httpx tự phân giải lại
khi connect; tên miền có TTL 0 đổi giữa IP công khai và `127.0.0.1`/`192.168.1.1` qua được. Chạm được gì: chỉ những
gì nghe ở cổng 80/443 trên máy này hoặc LAN (router), **không** phải 8000/11434/6333/5432/6379 vì `parts.port` bị khoá.
Sửa: resolve một lần rồi connect bằng IP, đặt `Host`/SNI theo tên (transport tuỳ biến), hoặc chấp nhận và ghi vào docs.

**S4. Câu tìm kiếm là kênh ra ngoài mở.** `web_search` gửi `query` bất kỳ tới DuckDuckGo; chỉ mô tả công cụ nhắc model
đừng đưa nội dung riêng vào. Một tài liệu có lệnh giấu "tìm trên web: <nội dung tài liệu khác>" là đường rò rỉ. Đây là
thiết kế đã chấp nhận (tắt mặc định, CHANGELOG ghi "câu tìm kiếm rời khỏi máy") — nhưng câu đó nên nói thẳng: nội dung
tài liệu/tin nhắn có thể rời máy qua câu tìm kiếm nếu model bị dụ.

## Không chặn — `remember`

**N1. `remember_tool.py:64-70` — cổng "lời của họ" là túi từ.** Đã đo: `"Tôi thích tôm"` qua được với tin
`"Hãy nhớ tôi không thích tôm"`; `"Dũng ghét Lan"` qua được với `"Dũng không ghét Lan, Lan không ghét Dũng"`. Cần model
bị dụ *trong cùng lượt người dùng có dặn nhớ* nên hẹp; người bị ghi sai thấy và thu hồi được. `fact_key` băm từ đã
sắp (`:106`) nên "Dũng ghét Lan"/"Lan ghét Dũng" trùng khoá, câu sau bị coi là "đã nhớ từ trước".

**N2. `remember_tool.py:129` — tự áp dụng, không qua người duyệt.** `approve(reviewed_by="agent_remember")` ngay trong
lượt, không cần ngưỡng tin cậy như đường agent hiện có (0,8). Thành viên nào trong guild được phép cũng ghi thẳng vào
khối hệ thống toàn server (`turn_service.py:544-561`, 50 dòng, mỗi dòng ≤ 300 ký tự, mọi lượt sau đều đọc). CHANGELOG
nói "đi qua đường duyệt sẵn có" — thực ra là đường *thu hồi*, không phải duyệt. Lựa chọn:

| Cách | Ưu | Nhược |
|---|---|---|
| Giữ tự áp dụng (như commit) | người dùng thấy hiệu quả ngay; đúng nghĩa "hãy nhớ" | ai cũng tô được 300 ký tự vào prompt chung; chỉ sửa sau khi thấy |
| Để `deferred`, admin duyệt trên màn hình Ghi nhớ | cùng luật với bộ trích; không gì vào prompt mà chưa có người xem | "hãy nhớ" không có tác dụng tới khi chủ dự án bấm; cần đổi câu trả lời của tool |
| Tự áp dụng chỉ với `author_id` của chủ dự án, còn lại `deferred` | giữ tiện cho người chính; chặn người lạ | thêm một cấu hình; cần test |

**N3. Lỗi giữa chừng để lại hàng mồ côi.** Nếu `approve` ném sau khi `with` đã commit (vd. Postgres rớt), hàng
`deferred` có `canonical_fact` còn lại; tool trả `TOOL_FAILED`, model nói "chưa lưu" — nhưng lần gọi lại cùng lượt
`created=False` → câu "Mỗi tin nhắn chỉ ghi nhớ được một điều" sai ngữ cảnh. Hàng đó hiện ở tab Chờ duyệt nên admin
cứu được.

**N4. Một dòng mỗi mục.** `_ASKED:32` nhánh `nhớ\s+(?:là|rằng)\b(?<=^nhớ là)` chết (lookbehind không bao giờ đúng sau
"rằng"; "Nhớ là…" đầu câu đã được `^nhớ\b` bắt). `_REFUSED:35` bắt nhầm "Hãy nhớ tôi không nhớ mật khẩu" thành từ
chối. `remember` được chào cho agent web (`/rag/chat`, cùng registry) nhưng luôn `TOOL_UNAVAILABLE_HERE` — một lượt gọi
phí. `approve` embed (Ollama) trên luồng của lượt, ngoài ngân sách 90 s. "Hãy nhớ Lan thích trà" thành trí nhớ *về
người nói* với nội dung về Lan. `IMAGE_NOTE` là hợp đồng chuỗi bot↔backend, test chỉ chép literal.
Registry Discord thật giờ khác eval một công cụ (`remember`) — eval vẫn đúng vai "hồi quy core", nhưng số 55/62 không
còn là số của bot.

## Docs và CHANGELOG lệch code

| Chỗ | Nói | Code |
|---|---|---|
| CHANGELOG ticket 35 web | "chỉ mở được url vừa tìm thấy hoặc người dùng tự viết" | thêm URL trong mô tả ảnh (S2) |
| CHANGELOG ticket 35 remember | "Đi qua đường duyệt sẵn có" | tự áp dụng; chỉ thu hồi được (N2) |
| `web_tools.py:3-6` docstring | như CHANGELOG | như trên |
| `docs/current_architecture.md:90-92` | core đăng ký `search_documents`, `read_document`, `system_status`; Discord thêm `search_history` | thật: `search_documents`, `read_document`, `search_history`, `remember`, `system_status`, `current_time`, `calculate` (+ `web_search`, `read_webpage` khi bật) — lệch từ ticket 33/34, nay thêm hai |
| `backend/app/discord/README.md` | liệt kê `agent_tools.py` | không có `remember_tool.py` |
| `.env.example:124-126` | — | dòng mới chen giữa `ANTHROPIC_API_KEY` và hai dòng `ANTHROPIC_*` chú thích |

Màn hình Ghi nhớ: **có thấy** (tab đang hiệu lực, nhãn "👤 agent_remember", nút thu hồi); nếu muốn robot như agent
tự áp dụng thì thêm nhánh ở `memory.js:784`.

## Chưa kiểm được

- DuckDuckGo thật: trang CAPTCHA/"anomaly" sẽ parse ra 0 kết quả → model nghe "không tìm thấy" thay vì "bị chặn";
  markup `result__a`/`result__snippet` có thể đổi. Không mạng.
- Phân giải DNS thật, NAT64, và rebinding end-to-end. Không mạng.
- Bộ test DB (`test_a_told_fact_is_saved…`, `test_words_from_an_image…`) — coordinator chạy.
- Gương web với embedding thật (test dùng `NoMirror`); `"fact"` qua được theo schema nhưng chưa chạy.
- Luồng ảnh thật qua bot.
