# Trí nhớ bot Discord — khảo sát Meta AI và thiết kế bốn tầng

**Ngày:** 27/08/2026 · **Trạng thái:** 🟡 **THIẾT KẾ — CHƯA THI CÔNG** · **có 1 chốt chặn phải giải trước tầng 3 (§9.3)**

**Phương pháp:** 7 agent khảo sát Meta AI (5 tra cứu + 1 tổng hợp + 1 phản biện), sau đó 5 agent nữa **kiểm ngược chính tài liệu này** trên mã nguồn thật. Vòng kiểm ngược tìm ra **8 lỗi nghiêm trọng trong bản nháp đầu**, gồm cả việc cách sửa tôi đề xuất là **ngược**. §11 ghi đủ.

Mọi con số đều ghi rõ **ai kiểm**: ✅ tôi tự mở nguồn / tự chạy · ⚠️ từ agent, chưa tự kiểm.

**Xuất phát:** yêu cầu *"tôi muốn bot Discord nhớ mọi thứ mà server nói, và đến một thời điểm nó sẽ được rút gọn và lưu lại làm kiến thức của server đó"*, cộng câu hỏi *"tham khảo memory của Meta AI"*.

> ## ⚖️ PHÁN QUYẾT 27/08/2026 — sau phiên công/thủ
>
> Một agent phản bác, một agent bảo vệ, cả hai chạy thí nghiệm thật trên production. **Bên phản bác thắng ở điểm quyết định**, bằng một bằng chứng không bên nào lường trước: xem §1.1.
>
> **LÀM NGAY (≈4 dòng, không migration):** ① đặt **cả hai** `LOCAL_AI_API_KEY` và `LOCAL_AI_PROTECT_READS=true` · ② nâng `conversation_history_limit` 12 → 40 · ③ sửa đường đọc + xoá `search_memory`.
>
> **CẬP NHẬT 27/08 (vòng 3, §13):** chủ dự án đặt mục tiêu **3 server × 100 tin/ngày, khởi đầu 1 server × 30 tin/ngày** — chính là phép đo mà phán quyết chờ. **Tầng 1 được mở khoá có trình tự** (mở nghe 1 kênh đếm vài ngày trước, migration sau — bất biến #8). **Tầng 3 (Gemini) vẫn hoãn** — chốt chặn là đúng-sai, không phải dung lượng.
>
> **BÁC BỎ:** hàng chờ duyệt **không thể** chứa mệnh đề tầng 3 (§9.7). Lối thoát an toàn của quyết định Gemini không tồn tại.

---

## 0. Kết luận trước, lý lẽ sau

> **① Đường đọc trí nhớ đang hỏng, và nó hỏng nặng hơn tôi tưởng.** Ràng buộc "một dòng hiệu lực" nằm trong `discord_memories`. Bot **không đọc bảng đó** — nó đọc bản sao trong Qdrant bằng truy vấn **không bộ lọc nào**. Có **ba** nơi gọi đường hỏng này, một trong đó là **endpoint HTTP công khai mặc định**.
>
> **② Meta AI không có gì để tham khảo.** Tính năng memory **đã bị gỡ bỏ**. Khi còn sống chỉ chạy chat 1-1, loại trừ chat nhóm, chỉ ở Mỹ/Canada. Chưa bao giờ công bố kiến trúc, chưa ai đo.
>
> **③ Kiến trúc đúng là "lưu-rồi-tra", không phải "trích-rồi-nén".** Bằng chứng đo được đứng về phía giữ nguyên bản gốc.
>
> **④ CHỐT CHẶN: bộ gác không làm việc mà tôi tưởng nó làm.** Lập luận an toàn cho việc gửi dữ liệu lên Gemini dựa vào `evidence_grounded`. **Đo thật: nó nhận một fact NGƯỢC HẲN với nguồn, và loại đúng loại mệnh đề mà tầng 3 sinh ra.** Sai cả hai chiều. §9.3.

Điều quan trọng nhất, nói thẳng: **bản nháp đầu của tài liệu này sai ở đúng chỗ nó cảnh báo người khác đừng sai.** Nó viết một mục về việc "kết luận từ lược đồ thay vì từ đường thực thi", rồi làm đúng thế thêm ba lần nữa. §11.

---

## 1. Hiện trạng đo được (27/08/2026, dữ liệu production thật) ✅

```
luot Discord da luu        : 19
agent_traces (moi loai)    : 23
trong do goi search_memory : 4
ung vien tri nho           : 6
tri nho Discord (song)     : 0
tri nho chung (memories)   : 0
```

| Tin nhắn | Bộ lọc quyết định |
|---|---|
| "bạn tắt bị tắt rồi, chào mọi người đi" | `no_durable_fact` |
| "nay là ngày bao nhiêu" | `question_only` |
| "vậy bạn biết gì về 3dgs hay nerf không" | `question_only` |
| "dạy tôi về 2dgs đi" / "dạy tôi về 3dgs" | `no_durable_fact` |
| "bạn nhớ tôi thích uống gì không" | `durable_preference` → độ tự tin **0,000** → hoãn |

**Đường ống không hỏng. Nó chạy đúng.** Kho rỗng vì trong 19 lượt chưa ai nói điều gì đáng nhớ. Bộ lọc loại 5/6 là **đúng chức năng**.

Cái duy nhất lọt bộ lọc thì bị **bộ trích xuất 9b bỏ cuộc ở độ tự tin 0,000** — tín hiệu về §7.2, không phải về bộ lọc.

### 1.1. Bằng chứng quyết định — 19 lượt đó **chính là** lời phàn nàn của người dùng ✅

Toàn bộ 19 lượt nằm trong **một phiên duy nhất**, và phiên Discord **không bao giờ hết hạn** (chỉ `orphaned` được ghi trong code; `'expired'`/`'closed'` chỉ có trong ràng buộc CHECK).

Đọc nguyên văn câu hỏi của người dùng:

| Lượt | Nội dung |
|---|---|
| **4** | **"tôi thích trà sữa"** ← sự việc được nói ra |
| 5, 6, 7 | "đố bạn biết tôi thích gì" · "tôi thích gì ??" |
| **10** | **"thế tức là bạn không biết tôi thích gì ?"** |
| 19 | "bạn nhớ tôi thích uống gì không" |

Trần lịch sử thật là **6** (`discord_turn_service.py:72-74`: `history_limit // 2` = 12 // 2). Ở lượt 19, cửa sổ chỉ với tới lượt 13–18 — **lượt 4 đã trôi mất từ lâu**.

**Thí nghiệm chạy trên qwen3.5:9b thật, prompt dựng đúng như `build_discord_speaker_context`:**

| Cửa sổ | Token prompt | Trả lời |
|---|---|---|
| **6** (đang chạy) | 2.164 | *"Ún là một AI, nên không có vị giác để biết bạn thích uống gì cả"* → đoán mò |
| **18** | 3.781 | ***"Theo trí nhớ của Ún thì bạn rất thích trà sữa"*** |

**Chi phí:** +390 ms nạp prompt lúc nguội, **+6 ms lúc ấm**, **0 lần gọi sinh chữ thêm**. So với 2,6 s chờ trung vị của Discord.

> **Một số nguyên ở `settings.py:118` sửa được đúng lỗi duy nhất từng xảy ra thật.** Toàn bộ phần còn lại của tài liệu này nhắm vào những lỗi **chưa từng xảy ra**.
>
> Toàn bộ kho chữ đời của bot: **8.263 ký tự ≈ 2.754 token** — **17% cửa sổ 16.384**. §5.5 và §7.6 định cỡ cho 500 tin/ngày; quan sát thật là **~10 tin/ngày**.

---

## 2. Meta AI — kết quả tra cứu

### 2.1. Tính năng đã bị gỡ bỏ ✅

Trang trợ giúp WhatsApp (`faq.whatsapp.com/452845737176270`, tiêu đề vẫn là *About Meta AI Memory*) nay chỉ còn hai đoạn trong khối `json_cms_content`, đoạn đầu là:

> "Meta AI Memory and any details Meta AI may have remembered are no longer available."

(Đoạn thứ hai là một câu link "Learn more".) **Tự kiểm 27/08/2026** — đọc trực tiếp mã nguồn trang. Các cụm của bài cũ ("Memory updated", "choose to share") **không còn tồn tại**.

Thời điểm gỡ: **giữa 15/11/2025 và 11/04/2026**, không thông báo. ⚠️ *(agent tra Wayback; Wayback bị chặn ở môi trường này)*

### 2.2. Khi còn hoạt động, phạm vi rất hẹp ⚠️

| Tiêu chí | Meta AI memory |
|---|---|
| Loại chat | **Chỉ 1-1. Chat nhóm bị loại trừ**, Meta không nêu lý do |
| Quốc gia | Chỉ Mỹ và Canada. Ra mắt 41 nước châu Âu 3/2025 **không kèm memory** |
| Trong nhóm | Chỉ đọc tin @-mention nó — *"Meta AI does not access other messages in the chat"* |

> **Điểm quan trọng:** "lỗ hổng" của bot dự án này — chỉ nghe khi bị gọi tên — **chính là thiết kế Meta đã chọn và công bố như một cam kết riêng tư.**

### 2.3. Không có kiến trúc để học ⚠️

Không bài báo, không model card, không mã nguồn, không lược đồ. Mọi mô tả kỹ thuật đang lưu hành đều là báo chí diễn giải lại **cùng một bài newsroom**. Và chưa ai từng đo memory của Meta AI độc lập.

### 2.4. Cái Meta CÓ công bố (MSC / BlenderBot, 2021–2023) ⚠️

| Meta đã làm | So với dự án này |
|---|---|
| Nhãn "không có gì để nhớ" (`no_summary`) | ✅ đã có (`no_op` + mã lý do) |
| Kho trí nhớ: vector phẳng, chỉ thêm, tích vô hướng | Giống hệt **đường đọc đang chạy** của dự án (§3) |
| Xử lý fact cũ bị thay thế | ❌ không có |
| Gộp nhiều tin thành một fact | ❌ không có — MSC và BB3 đều 1 lượt → 0 hoặc 1 dòng |

Kết quả họ tự công bố: **BlenderBot 3 (175 tỉ tham số, ba module trí nhớ) vẫn thua BlenderBot 1 — không có trí nhớ dài hạn — ở hạng mục nhất quán.**

---

## 3. Lỗi trong đường đọc — việc số 0

### 3.1. Hai nơi lưu, bot đọc nhầm nơi ✅

| Nơi | Nội dung | Bộ lọc |
|---|---|---|
| `discord_memories` (Postgres) | Sổ cái, ràng buộc 1 dòng hiệu lực do DB cưỡng chế | **Đầy đủ** |
| Collection `memories` (Qdrant) | Bản sao chép | **Không có gì** |

```
qdrant_store.py:146   client.query_points(collection_name=self.memories_collection_name,
                                          query=vector, limit=top_k)
```

**Không lọc `status`, `guild_id`, `subject_id`, `scope`.** Payload chỉ có `{memory_id, content, memory_type, importance}` (`qdrant_store.py:139`) — kể cả muốn lọc cũng không có dữ liệu để lọc.

*(Tên collection là biến `self.memories_collection_name`, cấu hình được qua `settings.qdrant_memories_collection` — không phải chuỗi cứng.)*

### 3.2. **BỐN** nơi gọi đường hỏng này ✅

Bản nháp đầu nói một; bản thứ hai nói ba; đúng là **bốn**:

| # | Nơi gọi | Chạy khi nào |
|---|---|---|
| 1 | `agent_service.py:187` — công cụ `search_memory` | Model tự quyết · **4/19 lượt = 21%** |
| 2 | `chat_service.py:118` — nhánh `if use_memory` | Khi cờ bật |
| 2b | **`chat_service.py:170` — cùng khối, trong `stream_response`** | **Đường streaming, `payload.use_memory`** |
| 3 | **`routers/memory.py` — `POST /memory/search`** | **Endpoint HTTP, `read_guard` mặc định công khai** |

Cả bốn đều gọi cùng `memory_service.search` → cùng truy vấn không lọc.

### 3.3. Hai hậu quả ✅

**a) Bài toán "10 tin chốt 10 thứ" chưa được giải.** Ràng buộc nằm ở Postgres; bot đọc Qdrant, nơi **không tồn tại khái niệm "hiệu lực"**. Thứ đang chạy là tra ngữ nghĩa top-5 toàn cục trần — **đúng thiết kế BlenderBot 2 mà §2.4 vừa chê**. Phép đo áp thẳng vào đây: phân biệt "phủ định cái cũ" với "lặp lại cái cũ" chỉ đạt **AUROC 0,59**.

**b) Trí nhớ rò rỉ giữa các server**, qua cả ba lối, trong đó có một endpoint công khai.

### 3.4. Cách sửa — **KHÔNG phải bỏ `use_memory=False`**

> ⚠️ **Bản nháp đầu đề xuất "bỏ `use_memory=False` cứng". Đó là làm hỏng thêm, không phải sửa.**
>
> `chat_service.py:117-118` là toàn bộ thân nhánh đó:
> ```python
> if use_memory and self.memory_service is not None:
>     memories = self.memory_service.search(message, top_k=5)
> ```
> Bật cờ lên **chính là gọi đường không lọc** — nâng nó từ 21% số lượt lên **100% số lượt**, cộng thêm **một lần nhúng mỗi lượt**. Rò rỉ xuyên server nặng lên, không nhẹ đi.
>
> (Và không có chuỗi `use_memory=False` nào cả — `chat_service.py:78` là một `False` **vị trí trần**, gán vào tham số thứ ba của `_respond` khai báo ở `:91`.)

**Việc thật phải làm:** cho đường Discord đọc **`discord_memories` có lọc**, không đọc bản sao Qdrant.

Truy vấn đúng đã tồn tại (`discord_memory_repositories.py:534-546`, hàm `list_active_extractor_targets`) — lọc đủ `guild_id`, `scope`, `subject_type`, `subject_id`, `status == "active"`, `memory_type`.

**Chi phí thật — bốn tệp, không phải một:**

| Tệp | Vì sao |
|---|---|
| `main.py:95` | `ChatService(store, router, logging_service, history_limit, memory_service)` — **không nhận session factory, không nhận repository Discord**. Hiện tại nó **không thể** với tới truy vấn đó. Phải sửa chỗ lắp ráp |
| `chat_service.py` | Thay thân `:117-121`; mở rộng chữ ký `respond_with_context` (`:58-68`) — hiện **không nhận `guild_id`, không nhận id chủ thể** |
| `discord_turn_service.py:483-491` | Nơi gọi duy nhất, **không truyền cả hai**. Truy vấn đích bắt buộc có (`discord_memory_repositories.py:518-519` ném `ValueError` nếu thiếu) |
| `agent_service.py` | Xoá `search_memory`: `:33` (guide), `:40` (AGENT_TOOLS), `:59` (schema), `:183-192` (dispatch) |

**Và phải bịt lối thứ ba:** `POST /memory/search` nằm dưới `read_guard = require_api_key_for_read`, **công khai mặc định** (`security/api_key.py`: *"Reads are public by default"*). Xoá công cụ mà để endpoint mở thì rò rỉ vẫn còn nguyên, chỉ khó thấy hơn. **Bịt tạm bằng `LOCAL_AI_PROTECT_READS=true` — NHƯNG PHẢI ĐẶT CẢ `LOCAL_AI_API_KEY`.**

> ⚠️ **Lỗi #12, và nó nằm đúng trên mục ưu tiên số một.** Bản trước ghi *"một dòng"*. **Chạy thử: một dòng đó là vô hiệu.** `security/api_key.py:33-38` thoát sớm và **cho qua** khi chưa cấu hình khoá — và `.env` của máy này **không có** `LOCAL_AI_API_KEY` (`grep -c` trả 0, `settings.py:23` mặc định chuỗi rỗng). Bật mỗi cờ bảo vệ thì **không có tác dụng gì**. Phải **hai dòng**.

Phạm vi truy vấn hiện chỉ phủ `scope = member_in_guild`; muốn phủ `guild`/`channel`/`thread` cần union hoặc nới điều kiện.

---

## 4. Kiến trúc bốn tầng

| Tầng | Tên | Chứa gì | Vào đường trả lời bằng cách nào | Trạng thái |
|---|---|---|---|---|
| **1** | **Sổ gốc** | Mọi tin, nguyên văn, ai nói, lúc nào | Công cụ `search_history`, model phải tự gọi | ⬜ phải xây |
| **2** | **Ngữ cảnh phiên** | N **lượt bot đã trả lời** của phiên | Luôn luôn | ⚠️ có, nhưng xem dưới |
| **3** | **Bản rút gọn** | Mệnh đề rút từ từng khoảng | **CHƯA THIẾT KẾ — §9.4** | ⬜ phải xây |
| **4** | **Sổ cái sự việc** | 10 khoá, 1 dòng hiệu lực | Luôn luôn (sau việc 0) | ✅ đã có |

### 4.1. Đính chính về tầng 2 ✅

Bản nháp đầu ghi tầng 2 là *"N tin gần nhất"* và đánh dấu ✅. **Sai.**

Nó là **N lượt bot đã trả lời của phiên** (`discord_turn_service.py:447-450` gọi `context_turns(turn.session_id, ...)`), và `discord_bot/main.py:527` thoát sớm nếu bot không bị @-mention.

**Hệ quả:** tin nhắn ghi thụ động vào sổ gốc **không bao giờ vào đường luôn-luôn**. Sau khi làm xong việc 0, 1, 2 thì câu *"tôi vừa nói gì ở trên"* vẫn **không ai trả lời được** — trừ khi model tự gọi `search_history` **và** người hỏi nhớ đúng chữ mình đã dùng.

Đây là khoảng trống thật của thiết kế, không phải chi tiết nhỏ.

### 4.2. Nguyên tắc xuyên suốt

> **Tầng dưới không bao giờ mất. Tầng trên chỉ là lối đi tắt.**

Tầng 3 tóm sai → tầng 1 vẫn đúng. Tầng 4 chọn nhầm → tầng 1 vẫn có câu gốc.

**Meta không có sổ gốc — bản tóm tắt *chính là* trí nhớ, nên tóm sai là mất vĩnh viễn.** Đây là điểm thiết kế này hơn BlenderBot. (Điều kiện để nguyên tắc này đứng vững: §9.1 và §9.2.)

### 4.3. Vì sao "lưu-rồi-tra" thắng "trích-rồi-nén"

| Bằng chứng | Con số | Ai kiểm |
|---|---|---|
| GroupMemBench: BM25 vs các hệ trí nhớ chuyên dụng | **ngang hoặc thắng** | ✅ |
| GroupMemBench: hệ tốt nhất, trung bình | **46,0%** | ✅ |
| — riêng hạng mục cập nhật kiến thức | **27,1%** | ✅ |
| Zep vs nhét thẳng hội thoại, model đọc nhỏ, knowledge-update | 74,4% vs **76,9%** | ✅ |
| — hạng mục single-session-assistant | 75,0% vs **81,8%** | ✅ |
| SeCom (Microsoft): trí nhớ tóm tắt vs tra thẳng lượt gốc | tóm tắt **thua** | ⚠️ |

Nguồn: [GroupMemBench arXiv 2605.14498](https://arxiv.org/abs/2605.14498) · [Zep arXiv 2501.13956](https://arxiv.org/html/2501.13956v1) Bảng 3 · [arXiv 2606.26511](https://arxiv.org/abs/2606.26511) (Yadav, 25/06/2026 — **bài một tác giả**; AUROC 0,59 là cho *contradicted vs duplicated*).

### 4.4. Điều này gỡ mâu thuẫn 10 khoá — **một phần**

Sổ gốc lo phần "nhớ mọi thứ", sổ cái lo phần "trả lời nhanh và chắc". Sổ cái giữ nguyên 10 khoá và giữ độ chính xác cao.

> ⚠️ **Nhưng lưu được không phải nhớ được.** Sổ gốc chỉ với tới qua hai bộ lọc mà chính tài liệu này gọi là yếu: **model phải tự chọn gọi công cụ** (số đo của chính dự án: 4/19 = 21%) **và BM25 cần gần đúng chữ** (§6).
>
> Một sự việc bền ngoài 10 khoá — *"chị tôi tên Lan"* — được **lưu** nhưng **không bao giờ tự nổi lên**, vì đường luôn-luôn chỉ có tầng 4 + tầng 2.
>
> Giới hạn 10 khoá không biến mất; nó chuyển từ **một enum 10 dòng đếm được** sang **một suy đoán kích hoạt công cụ không đo được**. Đó là đánh đổi, không phải lời giải.

---

## 5. Tầng 1 — Sổ gốc

### 5.1. Vì sao phải là bảng mới ✅

`discord_session_turns` là **hàng đợi công việc**: `status`, `lease_expires_at`, `attempt_count`, `max_attempts`, `worker_id`, `heartbeat_at`, chỉ mục `uq_discord_session_turn_one_running`. Mỗi dòng là một lượt bot **phải trả lời**. Tin thụ động không phải việc phải làm; nhét vào phá cơ chế FIFO.

→ **Bảng mới.**

### 5.2. Cần lưu gì

| Cột | Ghi chú |
|---|---|
| `guild_id`, `channel_id`, `thread_id` | Ranh giới server |
| `discord_message_id` | Duy nhất, snowflake |
| `author_id`, `author_display_name` | Ai nói |
| `is_bot` | **Phải quyết — §9.2** |
| `content` | Nguyên văn |
| `sent_at` | **Suy ra từ snowflake lúc ghi**: `sent_at := snowflake_to_datetime(discord_message_id)` |
| `reply_to_message_id` | Ai trả lời ai |
| `edited_at`, `content_original` | **Xem §5.3** |
| `deleted_at` | Discord cho xoá tin |

**Về `sent_at`:** bản nháp đầu vừa nói "snowflake tự nó đã mang giờ tạo" vừa nói "`sent_at` là cột quan trọng nhất" và cảnh báo đừng lấy nhầm giờ ghi. Hai câu đó chỏi nhau. **Suy ra từ snowflake ngay lúc ghi** thì cái sai đó *không thể xảy ra* — tốt hơn là cảnh báo về nó. (Cùng hạng lỗi với `valid_from=now` ở `discord_memory_repositories.py:881, 967, 1047`.)

### 5.3. "Chỉ thêm" và `edited_at` không thể cùng đúng ✅

`discord_message_id` là duy nhất. Tôn trọng bản sửa nghĩa là **UPDATE** — không còn "chỉ thêm". Thêm dòng mới cho mỗi lần sửa thì phạm ràng buộc duy nhất.

Và bản gốc bị ghi đè **chính là văn bản mà tầng 3 đã rút gọn và bộ gác đã trích dẫn**.

> **Quyết định phải chọn:** giữ `content` (bản mới nhất) **và** `content_original` (bản đầu tiên, không bao giờ ghi đè). Bảng vẫn chỉ-thêm-dòng; ô `content` được cập nhật. Nói rõ trong migration rằng bất biến #3 áp cho **cấu trúc**, còn `content` là ô có thể đổi giá trị.

### 5.4. Bảng chính sách theo kênh

`discord_conversation_sessions` không dùng được — nó là bảng vòng đời phiên (`status`, `closed_at`), phiên đóng thì chính sách mất theo.

| Cột | Ý nghĩa |
|---|---|
| `guild_id`, `channel_id` | khoá |
| `listening_enabled` | bot có ghi tin kênh này không |
| `enabled_by`, `enabled_at`, `disabled_at` | kiểm toán (bất biến #6) |

Lý do bật theo kênh là **nhiễu** — `#bot-log`, `#meme` mà ghi hết thì rác sổ gốc và tốn lần rút gọn vào chuyện vô nghĩa.

> ⚠️ **Cái này KHÔNG phải cơ chế "thu hồi" mà bất biến #6 đòi.** Nó theo kênh và chỉ có tác dụng về sau; bất biến #6 đòi thu hồi được **một hành động đã xảy ra**. Xem §9.5.

Hai luật kèm theo: **thread theo kênh cha** · **DM mặc định không ghi**.

### 5.5. Chi phí ✅

| | |
|---|---|
| Dung lượng | 500 tin/ngày × 200 byte = **36 MB/năm** |
| Nhúng vector | **Không cần** (§6) |
| Lần gọi model sinh chữ | **0** |

---

## 6. Tra cứu sổ gốc — BM25, và nó không phải "chỉ đấu dây"

Câu hỏi *"tôi nói câu ... khi nào"* là **tra cứu gần-nguyên-văn** — người hỏi nhớ đúng chữ, chỉ quên thời điểm. Đó là địa hạt BM25. Kết luận này đứng.

> ⚠️ **Đính chính bản nháp đầu:** nó dựng một bảng BM25-vs-embedding trong đó dòng "phân biệt phủ định vs lặp lại" ghi **AUROC 0,59** cho embedding và **gạch ngang** cho BM25. Gạch ngang đó **không có nguồn** — [arXiv 2606.26511](https://arxiv.org/abs/2606.26511) chỉ đo cosine, không so BM25. Và lý lẽ của chính bài đó (phủ định là một *sửa đổi tối thiểu*) áp cho từ vựng cũng đúng. **Bỏ dòng đó, giữ kết luận** — BM25 được chọn vì tra gần-nguyên-văn, không phải vì nó xử lý được phủ định.

### 6.1. Ba chỗ "đấu dây" không đúng ✅

`postgres_bm25_service.py` **giả định một kho duy nhất, và kho đó là tài liệu**:

| Thực tế | Hệ quả |
|---|---|
| `_snapshot()` gọi `PostgresDocumentRepository.active_chunk_snapshot()`; `_IndexedChunk` là dataclass của tài liệu; `search()` chỉ lọc theo `document_id` | Không dùng lại nguyên trạng cho tin nhắn được |
| `_index` / `_chunks` / `_fingerprint` là **trường đơn** | Một service **không giữ được hai chỉ mục** |
| Không có thêm tăng dần — dựng **lại toàn bộ** trong `self._lock`, mỗi tin mới đổi fingerprint | Chi phí **0 lúc ghi, O(N) ở lần đọc kế tiếp**. Ở 100k tin đây là con số phải đo, không phải bỏ qua |
| SQL chỉ chạy một lần lúc dựng chỉ mục, trên toàn kho | **Lọc `guild_id` phải là hậu-lọc trong bộ nhớ** như `document_id` — trái luật "lọc ở SQL" của §5.2 |

→ Là **một service thứ hai cùng khuôn mẫu**, không phải "đấu dây". Và bộ lọc guild phải nằm ở truy vấn SQL dựng snapshot (thu hẹp kho theo guild trước khi dựng), không phải ở lúc xếp hạng.

### 6.2. Vì sao vẫn không trộn vào kho `documents` ✅

> ⚠️ **Đính chính:** bản nháp đầu nói *"đường chuẩn RAG (recall@5 = 0,9878) đo trên kho đó"*. **Sai** — nó đo trên **corpus lab** (`DEVELOPMENT_PLAN.md:481` "trên corpus lab (đúng luật §3d)"; `nightly_eval.py:37-38` ghi cứng `LAB_DB` và `documents_lab`). Gate **không bao giờ đọc** `documents`, nên trộn vào **không phá được đường chuẩn**.

Lý do thật để không trộn là **§6.1**: service giả định một kho, và trộn tin nhắn vào chỉ mục tài liệu làm hỏng chính việc tìm tài liệu.

### 6.3. Về tokenizer tiếng Việt ✅

`postgres_bm25_service.py:14,112,144` dùng `tokenize_vietnamese` — đúng, và tin nhắn nên dùng cùng tokenizer.

> ⚠️ **Đính chính:** bản nháp đầu viết *"bản pyvi được ghim và canh bằng băm SHA-256 (việc T16)"* như một sự bảo đảm. **Dự án đã tự bác điều đó**: `DEVELOPMENT_PLAN.md:195` — *"**nhưng cái ghim đo ra là vô hiệu** (pyvi 0.1.1 là bản duy nhất từ 2021)"*, và `:237` — *"Vì sao cái ghim không ghim được gì"*. Băm SHA-256 chỉ tồn tại **trong test** (`backend/tests/test_vi_tokenizer.py`); lúc chạy thật chỉ có `TOKENIZER_VERSION` — một chuỗi để ghi log, **không so với gì cả**.
>
> Tôi đã nhận lại một niềm tin mà chính dự án đã rút lại. Đây là lỗi §11.

---

## 7. Tầng 3 — Rút gọn bằng Gemini 2.5 Flash

### 7.1. Quyết định 27/08

**Toàn bộ khâu rút gọn chạy trên Gemini 2.5 Flash.** Không phân biệt kênh. Căn cứ của người quyết: *"không có gì nhạy cảm cả"*.

Ghim lại để sáu tháng nữa còn biết:

> Tuyên ngôn dự án (`docs/DEVELOPMENT_PLAN.md:30`): **"mọi dữ liệu ở trên máy của bạn"**.
>
> Quyết định 25/08 (`:505`): chấp nhận **mất sạch dữ liệu khi chết SSD** thay vì đẩy backup lên cloud — lý do ghi đủ là **"(giữ riêng tư + không tốn phần cứng)"**, hai vế ngang nhau.
>
> `:608` có ghi *"(+ Gemini/DeepSeek tùy chọn)"* — **nhưng câu đó nằm trong danh sách "Cố tình KHÔNG theo"**, và kết bằng *"dữ liệu ta là file cục bộ, đúng định vị riêng tư"*. Đọc nguyên câu thì nó **không phải** một lời cho phép mạnh như bản nháp đầu trình bày.
>
> Và phải nói đúng quy mô: rút gọn **đọc mọi tin nhắn**, chỉ là theo lô. Nên "chỉ tầng 3 dùng cloud" trên thực tế là **mọi câu mọi người nói trong server, sớm muộn đều đi qua Google**.

### 7.2. Vì sao Gemini tốt hơn ở đúng việc này ⚠️

Rút gọn là **đọc nhiều tin lộn xộn rồi xuất ra mệnh đề rời có cấu trúc** — đúng chỗ model nhỏ sụp:

| Bằng chứng | Con số |
|---|---|
| Model 7–13b tóm tắt hội thoại | **15–29% câu sai sự thật**, ~3× GPT-3.5 |
| Model nhỏ ở phần xuất có cấu trúc của bảo trì trí nhớ | sụp **0,781 → 0,447** |

**Hướng chắc chắn, độ lớn chưa biết.** §7.6 nói cách đo — và cảnh báo phép đo hiển nhiên là phép đo sai.

### 7.3. Cần đổi gì trong code ✅

**a) `models.yaml` — thêm ô, THỤT VÀO trong `models:`:**

```yaml
models:
  general:
    ...
  condenser:                 # <- thụt 2 dấu cách, nằm trong `models:`
    provider: gemini
    name: gemini-2.5-flash
    temperature: 0.2
    max_tokens: 4096
```

> ⚠️ Bản nháp đầu in khối này ở **mức ngoài cùng**, tức thành anh em với `models:`, `rag:`, `agent:`. `Settings.load_models()` (`settings.py:227-232`) chỉ trả `payload.get("models")`, nên khoá ngoài cùng **không bao giờ tới router**, và `self.models[mode]` (`model_router.py:80`) ném `KeyError` ngay cả sau khi đã nới danh sách mode. Khối cũ **dán vào là chạy sai một cách im lặng**.

**b) `model_router.py` — nới `chat()`:** đổi `if mode != "general"` thành danh sách cho phép `{"general", "condenser"}`. **Chỉ trong `chat()`** — giữ `general`-only cho `chat_tools()` và bản streaming.

**c) `.env` — `GEMINI_API_KEY`.** Máy móc đã có: `.gitignore` chặn, sao lưu mỗi đêm, `backup-env-once.bat` mã hoá AES-256.

Client Gemini (`app/llm_clients/gemini_client.py`, REST v1beta), `_cloud_kwargs`, dịch `num_predict` → `max_tokens` — **đã viết sẵn**.

> ⚠️ **d) Khoá API rò rỉ vào log — phải xử lý trước khi đặt khoá.** `gemini_client.py:100` và `:144` nhét khoá vào **URL**: `?key={self.api_key}`. `logging_service.py:52-56` ghi log dạng `serialize=True`, kèm `exception=record.exc_info`, giữ **30 ngày**. Một lỗi 5xx từ Google sẽ đưa nguyên URL — **kèm khoá** — vào `data/logs/`. Ba lớp bảo vệ nêu ở (c) đều chỉ giữ `.env`, **không giữ được log**. Và `data/backups/` sao lưu hằng đêm.

### 7.4. Luật kích hoạt, và cái chốt không đủ ✅

Dùng cloud thì không còn tranh chấp với Ollama, nên điều kiện "chờ kênh im 10 phút" có thể bỏ **về mặt tài nguyên**.

> ⚠️ **Nhưng bỏ nó cũng vứt luôn thứ duy nhất đánh dấu ranh giới câu chuyện.** Cắt cứng ở tin thứ 100 sẽ chẻ đôi một quyết định được nói rải từ tin 98 đến 102 — đúng loại đầu vào sinh ra ca loại-nhầm ở §9.3. SeCom (trích ở §4.3) là bài về **phân đoạn theo chủ đề**; lấy kết luận của nó mà bỏ cơ chế của nó là không nhất quán. **Giữ cửa sổ im lặng như một ranh giới ưu tiên, không phải như một điều kiện tài nguyên.**

**Đề xuất:** 100 tin, hoặc 24 giờ — cái nào đến trước; ưu tiên cắt ở khoảng im ≥ 10 phút gần nhất trong vùng.

Ngữ cảnh không phải ràng buộc: 500 tin × ~40 token = 20.000 token = 2% cửa sổ 1 triệu.

**Cái chốt `last_condensed_message_id` — một con số là KHÔNG đủ.** Bốn ca chính thiết kế này tạo ra:

| Ca | Vì sao chốt đơn hỏng |
|---|---|
| **Sửa tin** | §5.2 có `edited_at`, nhưng sửa **không đổi snowflake** → tin đã rút gọn không bao giờ được xét lại |
| **Tin về muộn** | Chốt tăng đơn điệu theo id → tin tới sau khi chốt đã vượt qua (gateway resume, ingest chết, backfill REST) bị **bỏ vĩnh viễn**. §7.7 chỉ che lúc *bộ rút gọn* chết, không che lúc *bộ ghi* chết — nên "tầng dưới không bao giờ mất" **chưa được bảo đảm** |
| **Thread** | §5.4 nói "thread theo kênh cha", §5.2 lại lưu `thread_id`. Một chốt cho kênh cha thì trộn thread vào cùng lô; một chốt cho mỗi thread thì không còn là "một con số" |
| **Đồng thời** | Hai lần kích hoạt không có trạng thái phụ → hai bộ rút gọn tính tiền cùng một khoảng. Đúng bài toán mà `lease_expires_at` / `uq_discord_session_turn_one_running` (§5.1 vừa trích) sinh ra để giải |

→ Cần **một bảng lô rút gọn có trạng thái và lease**, cùng khuôn mẫu `discord_session_turns`, không phải một cột số nguyên.

### 7.5. Đưa gì vào, lấy gì ra ✅

**Vào — bản ghi có giờ và tên:**

```
[27/08 14:03] Dũng: chốt dùng Postgres nhé
[27/08 14:05] An: ok vậy bỏ MySQL
```

**Ra — mệnh đề rời, và LƯU đủ những gì đã gọi là bắt buộc:**

| Trường | Bắt buộc vì |
|---|---|
| `content` | Nội dung mệnh đề |
| `source_message_ids` | Bộ gác cần biết đối chiếu với tin nào trong 100 tin |
| `speaker_id` | Truy ngược khi sai, **và xoá theo người** |
| `said_at` | Giờ nói thật |

> ⚠️ **Bản nháp đầu gọi bốn trường này là bắt buộc rồi lưu mỗi `content` + một *khoảng* id.** Không có `source_message_ids` thì bộ gác không biết đối chiếu với tin nào — tức chính cơ chế §9.3 dựa vào. Không có `speaker_id` thì không xoá được dữ liệu của một người. Cảnh báo của chính mục đó — *"không có nó thì tầng 3 thành hộp đen"* — áp đúng vào lược đồ của nó.

**Bảng lô rút gọn lưu:** `guild_id`, `channel_id`, `thread_id`, `from_message_id`, `to_message_id`, `from_sent_at`, `to_sent_at`, `model_used`, `message_count`, `status`, `lease_expires_at`.
**Bảng mệnh đề lưu:** `batch_id`, `content`, `source_message_ids`, `speaker_id`, `said_at`.

### 7.6. Chi phí, và vì sao phép đo hiển nhiên là phép đo sai ✅

Giá tự kiểm trên `ai.google.dev/gemini-api/docs/pricing` (27/08/2026): **$0,30 / 1 triệu token vào · $2,50 / 1 triệu token ra**, có bậc miễn phí.

| | |
|---|---|
| Token vào / tháng | ~690.000 → $0,207 |
| Token ra / tháng | ~90.000 → $0,225 |
| **Tổng** | **$0,43/tháng ≈ 11.000 đ** |

*(690.000 gồm ~15% phụ trội prompt cố định: 500×40×30 = 600.000 token nội dung, cộng ~600 token prompt mỗi lần gọi. "~5 lần/ngày" là **mỗi kênh** — nhánh 24 giờ tạo tối thiểu một lần gọi mỗi kênh đang nghe mỗi ngày.)*

**Tiền không phải yếu tố.**

> ⚠️ **Phép đo mà bản nháp đầu đề xuất — "so tỉ lệ mệnh đề qua được cửa `evidence_grounded`" — là vòng tròn.** Nó đo tỉ lệ lọt **qua chính cái cửa** đó; nới cửa ra thì con số đẹp lên. Và mệnh đề trôi chảy, trích dẫn chuẩn, tự tin chính là thứ **dễ qua** một phép so trùng từ. Một bộ rút gọn mạnh hơn sẽ **ăn điểm cao hơn kể cả khi nó sai nhiều hơn**.
>
> Phép đo đúng cần **nhãn người**: lấy ~50 mệnh đề của mỗi model, tự đọc và chấm đúng/sai so với tin gốc. 19 lượt đã lưu là đủ để bắt đầu.

### 7.7. Kiểu hỏng mới: mạng

Mất mạng thì rút gọn dừng; bảng lô có trạng thái làm điều đó vô hại. Cần **cảnh báo khi tồn đọng vượt ngưỡng** (ví dụ > 500 tin chưa rút gọn), ghép vào `check_operational_alerts.py`.

*(Chú ý: cái này che lúc bộ rút gọn chết. Lúc **bộ ghi** chết thì cần cơ chế khác — §7.4, ca "tin về muộn".)*

---

## 8. Đường "tôi nói câu đó khi nào"

| | Chạy khi nào | Chi phí | Lấy từ đâu |
|---|---|---|---|
| **Luôn luôn** | Mọi câu trả lời | **0 lần gọi sinh chữ** | Tầng 4 (có lọc) + tầng 2 |
| **Khi cần** | Model tự gọi công cụ | 1 vòng | Tầng 1 (sổ gốc, BM25) |

Dùng công cụ cho việc *phải làm mọi lần* thì hỏng; cho việc *hiếm và rõ ràng* thì đúng. "Tôi nói câu đó khi nào" đúng là loại hiếm và rõ ràng.

**Ngân sách công cụ:** xoá `search_memory`, thêm `search_history(query, author?, khoảng thời gian?)`. Vào một, ra một.

**Trả về:** tin nguyên văn + ai nói + giờ chính xác + link tới tin gốc. **Không tóm tắt, không diễn giải** — người hỏi cần bằng chứng, không cần ý kiến.

> ⚠️ **Tầng 3 không có đường đọc trong thiết kế này.** Bảng trên chỉ có hai làn: tầng 4+2, và tầng 1. Tầng 3 hiện được đặc tả **chỉ để ghi**. Xem §9.4.

---

## 9. Năm chỗ phải giải

### 9.1. Bộ gác không kiểm thứ mà §7 tưởng — **CHỐT CHẶN** ✅

`discord_memory_guard.py:61-70`:

```python
def evidence_grounded(evidence, source):
    return bool(evidence) and evidence in (source or "")     # kiểm CÂU TRÍCH

def auto_apply_allowed(*, canonical_fact, evidence_text, source_text):
    return evidence_grounded(evidence_text or "", source) and \
           fact_overlap(canonical_fact or "", source)        # 34% từ nội dung, gấp chữ
```

`evidence_grounded` kiểm **câu trích dẫn** có thật trong nguồn — **không bao giờ kiểm mệnh đề**. Mệnh đề chỉ đi qua `fact_overlap`: tỉ lệ túi-từ 34%, gấp dấu, **không xử lý phủ định**. Và **cùng một model viết cả hai trường**, nên nó tự chọn câu trích cho mình.

**Tôi tự chạy hàm thật:**

```
fact     'User uses Postgres'
evidence 'không dùng Postgres nữa'
nguồn    'Dũng: thôi chốt bỏ Postgres nhé, không dùng Postgres nữa'
→ auto_apply_allowed = True                    ← NHẬN fact ngược hẳn với nguồn
```

Đây đúng là kiểu mù-với-phủ-định mà §3.3 dùng AUROC 0,59 để chê.

**Và chiều ngược lại cũng hỏng:**

```
mệnh đề  'Nhóm quyết định chuyển từ MySQL sang Postgres'
vs 'Dũng: chốt dùng Postgres nhé'  →  evidence=False, overlap=False
vs 'An: ok vậy bỏ MySQL'           →  evidence=False, overlap=False
→ LOẠI đúng loại mệnh đề mà tầng 3 sinh ra để tạo
```

> **Kết luận:** câu *"Cloud đề xuất, máy này phán quyết"* là kiến trúc đúng, **nhưng bộ gác hiện tại không phán quyết được gì**. Nó xác nhận *một câu trích có thật*, không xác nhận *mệnh đề có suy ra từ đó không*.
>
> **Trước khi tầng 3 tự động ghi vào sổ cái: hoặc bộ gác phải kiểm được suy luận, hoặc tầng 3 phải nằm sau một người duyệt.**
>
> **✅ Cập nhật 27/08 (việc 4):** hai lỗ đo được ở trên đã đóng bằng hai luật tất định (vế-phủ-định + tối-thiểu-2-từ) — 0-chi-phí trên benchmark 75 ca, cả hai ca này giờ **FIXED** trong bộ eval và được hợp đồng test giữ không thoái lui. Verifier model 1-vs-1 đã ghép vào worker nhưng **ship tối**; tự-áp-dụng vẫn tắt cho tới khi benchmark `--with-extractor` qua ngưỡng §13.4.

### 9.2. Luật "một trong N" làm nó tệ hơn ✅

Bản nháp đầu đề xuất nới `evidence_grounded` thành "nguyên văn trong MỘT trong các tin nguồn", gọi đó là "sửa hẹp".

**Đo thật:** `fact_overlap('User prefers Postgres', ·)` **qua được 1 trong 5 tin không liên quan**. Ở N=100 thì trùng ngẫu nhiên gần như chắc chắn — trong khi mệnh đề liên-tin thật vẫn bị loại (§9.1).

Chính sách 96,7% / 36,2%→21,6% mà bộ gác dựa vào là **đo ở N=1**, không suy rộng ra N=100 được.

Và bản nháp đầu chỉ nói sửa `evidence_grounded` — `auto_apply_allowed` có **hai** phép kiểm nguồn-số-ít; `fact_overlap` không hề được nhắc.

### 9.3. Tin của chính bot có ghi vào sổ gốc không? — chưa quyết ✅

| Chọn | Hệ quả |
|---|---|
| **Không ghi** (hành vi hiện tại) | Tầng 3 rút gọn hội thoại **thiếu mọi câu trả lời của bot**. Một quyết định do bot đề xuất, người dùng chốt bằng "ok làm thế đi", sẽ rút gọn thành một lời đồng ý không gắn vào đâu |
| **Có ghi** | Chữ của bot thành `source_text` nguyên văn mà một `evidence_grounded` về sau sẽ trích — **ảo giác hôm qua thành bằng chứng hợp lệ hôm nay**. Không tầng nào chặn được, vì bộ gác lấy `source_text` làm chân lý theo thiết kế |

Phải chọn, và ghi vào cột `is_bot` để về sau đổi được.

### 9.4. Tầng 3 chưa có đường đọc

Tầng 3 là tầng **duy nhất** tốn một nhà cung cấp cloud, một khoá API, một thay đổi router và vị thế riêng tư của dự án — mà hiện **chỉ được đặc tả để ghi**.

Phải chọn một: **đặc tả cách truy vấn và nhét bản rút gọn vào prompt**, hoặc **xếp tầng 3 sau tầng 1+2** cho tới khi có nhu cầu thật.

### 9.5. Xoá dữ liệu chưa có thiết kế ✅

Lệnh "quên tôi đi" phải chạm: tầng 1 · tầng 2 (`discord_session_turns` — chưa từng được liệt kê là nơi chứa chữ của người dùng) · tầng 3 · tầng 4 · **và bản sao Qdrant mà §3.1 nói là có thể hỏng**.

Nặng nhất: theo §7.5 bản rút gọn là một khối `content` cho cả khoảng. **Không bóc riêng một người ra được — phải xoá cả khoảng, và không dựng lại được** nếu bản gốc đã bị bản sửa ghi đè (§5.3).

Nghĩa là **tầng duy nhất không hoàn tác được lại chính là tầng đi qua bên thứ ba.**

Và §5.4 lập luận bật-theo-kênh *"không phải riêng tư"*, trong khi §7.1 thừa nhận *"mọi câu mọi người nói đều đi qua Google"* — lý do §5.4 dùng để loại DM (*"người nhắn riêng không biết có bảng chính sách nào"*) áp **y nguyên** cho thành viên trong kênh.

### 9.6. Guard xuyên ngữ

`docs/DEVELOPMENT_PLAN.md:282` đã ghi nợ: *"fact tiếng Anh vs tin Việt bị từ chối oan"*. Cách khắc phục đã ghi ở đó — *"prompt extractor v6 viết fact bằng ngôn ngữ tin gốc"* — chính là điều cần áp cho prompt Gemini. Model mạnh **dễ tự chuẩn hoá sang tiếng Anh** hơn, nên rủi ro này tăng chứ không giảm.

### 9.7. Hàng chờ duyệt **không thể** chứa mệnh đề tầng 3 — lối thoát không tồn tại ✅

§9.1 chặn tầng 3 tự áp dụng, và §10 gỡ chặn bằng cách "ghi vào hàng chờ duyệt". **Hàng chờ đó về mặt lược đồ không chứa được.**

| Ràng buộc | Vì sao chặn |
|---|---|
| `models.py:518-522` — `source_turn_id` **NOT NULL**, FK tới `discord_session_turns` | Mệnh đề tầng 3 rút từ **tin thụ động**, mà §5.1 để ở bảng khác **chính vì chúng không phải turn**. Không có `source_turn_id` để điền |
| `models.py:484-493` — `UniqueConstraint(source_turn_id, extractor_schema_version)` | Một lô sinh **nhiều** mệnh đề. Ràng buộc duy nhất cấm |

**Và kể cả chứa được thì người duyệt cũng không duyệt nổi:**

| Thực tế | Hệ quả |
|---|---|
| `discord_memory_review_service.py:70` — `list_pending(limit=50)`; `routers/memory_review.py:29` gọi **không tham số phân trang** | **50 là trần cứng của cả API**. Mục cũ hơn rơi khỏi đáy, không với tới được |
| `frontend/dashboard.js:234-244` chỉ hiện `canonical_fact`, `evidence_text`, tác giả, độ tự tin | **Không có ô nào hiện tin nguồn.** §7.5 cho mệnh đề `source_message_ids` trỏ tới tối đa 100 tin mà giao diện không vẽ được |

Ở đúng cỡ §7.6 tự đặt (~5 lô/ngày/kênh), hàng chờ **tràn trần 50 trong vài ngày và âm thầm rụng mục**. "Người duyệt" như đang viết là **một cái nhãn, không phải một cơ chế kiểm soát** — và bất biến #6 đang được tuyên bố dựa trên một mặt phẳng không hiện nổi bằng chứng để mà kiểm.

> **Hệ quả cho quyết định Gemini:** §10 định giá tầng 3 là "~5 lần gọi Gemini/ngày · 0 cục bộ", coi hàng chờ duyệt là lối thoát miễn phí. **Nó cần thêm bảng thứ tư và một giao diện duyệt thứ hai** — cả hai đều không có trong bảng phạm vi của chính kế hoạch.

---

## 10. Thứ tự thi công

> ⚠️ **Bảng dưới đây đã được thay bằng bảng §13.5** sau vòng thẩm định thứ ba (đánh giá ngoài + 2 agent kiểm chéo). Giữ lại để đối chiếu.

| # | Việc | Chi phí | Ghi chú |
|---|---|---|---|
| **0a** | **Đặt `LOCAL_AI_API_KEY` + `LOCAL_AI_PROTECT_READS=true`** | 2 dòng `.env` | Rò rỉ **đang sống**. Một mình cờ bảo vệ là **vô hiệu** (§3.4) |
| **0b** | **Nâng `conversation_history_limit` 12 → 40** | **1 số nguyên** | Sửa **lỗi duy nhất từng xảy ra thật** (§1.1). +390 ms nguội, +6 ms ấm, 0 lần gọi thêm |
| **0c** | Sửa đường đọc (§3.4) | **4 tệp** + bịt endpoint | **Giảm** lần gọi sinh chữ (xoá công cụ = bớt một vòng trên 4/19 lượt) |
| — | **ĐO trước khi đi tiếp** | — | Mở nghe **một kênh**, đếm tin thụ động thật/ngày. Thiết kế cỡ 500/ngày; quan sát ~10/ngày |
| **1** | Sổ gốc + bảng chính sách kênh | Bảng mới · 0 lần gọi model | **Chỉ khi phép đo cho thấy cần.** Quyết `is_bot` (§9.3), `content_original` (§5.3), **và thiết kế xoá (§9.5)** trước khi viết migration |
| **2** | Service BM25 thứ hai + `search_history` | Đo lại: dựng chỉ mục 50k tin ≈ **2,1 s**, truy vấn 7,7 ms | Rẻ hơn §6.1 lo. Nhưng dựng lại nằm trên đường đọc |
| **3** | **Bộ gác: kiểm suy luận** | **Việc mới, không phải chỉnh ngưỡng** | `content_words('User uses Postgres')` = `{'postgres'}` (còn lại là stopword) → tỉ lệ 1,0. Phải **thay** `fact_overlap` |
| **4** | Bảng ứng viên tầng 3 + giao diện duyệt thứ hai | **Chưa được tính vào phạm vi** (§9.7) | Điều kiện cần của mọi thứ liên quan Gemini |
| **5** | Tầng 3 tự áp dụng | — | **Chỉ sau việc 3 và 4** |

> ⚠️ **Bản trước ghi "Việc 0, 1, 2 giải xong yêu cầu gốc". Câu đó mâu thuẫn với §4.4 của chính nó** — §4.4 đã nói sổ gốc chỉ với tới qua hai bộ lọc yếu và gọi đó là *"đánh đổi, không phải lời giải"*. Không thể vừa là đánh đổi vừa là lời giải.
>
> **Nói đúng:** việc **0a–0c** sửa những gì đang hỏng thật. Việc 1–2 mở khả năng lưu và tra lại — **chưa có bằng chứng là cần**. Việc 3–5 phụ thuộc vào việc 4 vốn chưa từng được tính chi phí.

---

## 11. Kỷ luật — những chỗ tôi nói sai

Theo tinh thần `docs/DEVELOPMENT_PLAN.md` §7c.

| Tôi đã nói | Thực tế | Bắt được nhờ |
|---|---|---|
| *"Chỉ tồn tại một dòng hiệu lực, không có gì để chọn nhầm"* | Đúng ở sổ cái, **sai ở đường đọc** | Agent phản biện |
| *"Ràng buộc của bạn mạnh hơn mọi thứ Meta từng ship"* | Chỉ đúng với **sổ ghi**; thứ model đọc **giống hệt BlenderBot 2** | như trên |
| *"Nhiều tin → một fact không biểu diễn được trong lược đồ"* | Quá rộng — `discord_memory_sources` đã cho nhiều nguồn | Tự kiểm `models.py:736-774` |
| *"Chỉ thêm một ô vào `models.yaml`, router tự lo"* | `router.chat()` chặn cứng mọi mode trừ `general` | Tự kiểm `model_router.py:78-79` |
| ***"Bỏ `use_memory=False` là cách sửa"*** | **Ngược.** Bật cờ đó **chính là gọi đường không lọc** — 21% → 100% số lượt | Vòng kiểm ngược tài liệu |
| **"Chi phí: một tệp"** | **Bốn tệp.** `ChatService` không nhận session factory nên **không thể** với tới truy vấn có lọc | như trên |
| **"Xoá `search_memory` là đóng được rò rỉ"** | Còn **`POST /memory/search`**, công khai mặc định | như trên |
| **"`evidence_grounded` khiến Gemini không bịa được"** | **Nó không kiểm mệnh đề.** Đo thật: nhận fact **ngược hẳn** với nguồn | Tự chạy hàm |
| **"pyvi được ghim và canh bằng băm SHA-256"** | Dự án **đã đo ra cái ghim là vô hiệu** (`:195`); băm chỉ có trong test | Vòng kiểm ngược |
| **"recall@5 = 0,9878 đo trên kho `documents`"** | Đo trên **corpus lab**; gate không đọc `documents` | như trên |
| **Tầng 2 là "N tin gần nhất"** | Là N **lượt bot đã trả lời**; tin thụ động không vào đường luôn-luôn | như trên |
| **"Bịt tạm bằng `LOCAL_AI_PROTECT_READS=true` — một dòng"** | **Vô hiệu.** `api_key.py:33-38` cho qua khi chưa cấu hình khoá; `.env` máy này không có `LOCAL_AI_API_KEY`. Phải **hai** dòng | Phiên công/thủ |
| **"BA nơi gọi đường hỏng"** | **Bốn** — sót `chat_service.py:170` trong `stream_response` | như trên |
| **"Việc 0, 1, 2 giải xong yêu cầu gốc"** | Mâu thuẫn với §4.4 của chính tài liệu | như trên |
| **Coi hàng chờ duyệt là lối thoát miễn phí cho tầng 3** | Lược đồ **không chứa nổi** mệnh đề tầng 3 (§9.7) | như trên |
| **Không hề chạy thí nghiệm cửa sổ lịch sử** | Một số nguyên sửa đúng lỗi duy nhất từng xảy ra thật (§1.1) | như trên |

**Bài học chung, và nó lặp lại năm lần trong ba ngày:**

> Tôi kết luận về hành vi hệ thống từ **tên biến, lược đồ dữ liệu, và tên hàm** thay vì từ **thân hàm và đường thực thi**.
>
> `use_memory` nghe như "dùng trí nhớ", nên tôi cho rằng bật nó lên là dùng trí nhớ *đúng*. `evidence_grounded` nghe như "có căn cứ", nên tôi cho rằng nó kiểm căn cứ. Cả hai tên đều đúng nghĩa đen và sai nghĩa tôi cần.
>
> **Cách chặn: mở thân hàm ra đọc, hoặc chạy nó.** Mọi lỗi nặng trong tài liệu này đều bị bắt bằng cách **chạy hàm thật với dữ liệu thật** — mất chưa tới một phút.

**Bài học thứ hai, từ phiên công/thủ:**

> **Tôi thiết kế cho lưu lượng tưởng tượng thay vì đọc lưu lượng đang có.** Tài liệu định cỡ cho 500 tin/ngày, rồi dựng bốn bảng, một service BM25 thứ hai và một nhà cung cấp cloud để phục vụ con số đó. Lưu lượng thật: **~10 tin/ngày, một phiên, một guild, 2.754 token đời**.
>
> Và trong 19 lượt đó **có sẵn nguyên văn lời phàn nàn của người dùng** — lượt 4 nói ra sự việc, lượt 10 hỏi *"thế tức là bạn không biết tôi thích gì?"*. Tôi đã truy vấn bảng đó **ba lần** để lấy số thống kê mà **chưa một lần đọc nội dung nó**.

---

## 12. Quyết định — đã chốt, còn mở, và bị chặn

**Đã chốt (27/08/2026, sau phiên công/thủ):**
- Kiến trúc bốn tầng, nguyên tắc "tầng dưới không bao giờ mất"
- Tầng 3 chạy Gemini 2.5 Flash **khi được xây** — nhưng **HOÃN**: §9.7 cho thấy lối thoát an toàn của nó không tồn tại, và lưu lượng chưa biện minh được
- Sổ gốc tra bằng BM25, không nhúng vector
- Bật chế độ nghe theo từng kênh (lý do: nhiễu)
- Giữ nguyên 10 khoá của sổ cái sự việc

**Bị chặn:**
- ~~**Tầng 3 tự áp dụng vào sổ cái** — chờ §9.1~~ **§9.1 đã đóng 27/08 (việc 4)**; còn chặn bởi §9.7 + đường đọc §9.4 + benchmark verifier
- **Bật `DISCORD_MEMORY_VERIFIER_ENABLED` + mở lại tự-áp-dụng** — chờ pha `--with-extractor` của bộ eval đo qua ngưỡng §13.4
- **Tầng 3 ghi vào hàng chờ duyệt** — chờ §9.7 (**bảng thứ tư + giao diện duyệt thứ hai**, chưa tính phạm vi)
- ~~**Tầng 1 và mọi migration** — chờ phép đo lưu lượng thụ động thật~~ **Mở khoá 27/08 (§13):** chủ dự án cam kết 3×100 tin/ngày; trình tự = mở nghe 1 kênh đếm trước, migration sau

**Làm ngay, không chờ gì:** ✅ **XONG 27/08** — 0a+0e, 0b, 0c, 0d. Suite 664 pass / 1 skip. **Cần khởi động lại API + container bot** để ăn `.env` và code mới.

**Còn mở:**
- **Tin của chính bot có vào sổ gốc không** (§9.3) — phải quyết trước khi viết migration tầng 1
- **Tầng 3 có đường đọc không, hay xếp sau tầng 1+2** (§9.4)
- **Thiết kế xoá dữ liệu** (§9.5)
- **Bộ trích xuất tầng 4 có chuyển sang Gemini luôn không** — lý lẽ giống §7.2, và ứng viên duy nhất lọt bộ lọc bị hoãn ở độ tự tin 0,000. Nhưng **§9.1 áp cho cả tầng 4**, nên model mạnh hơn ở đây cũng có nghĩa là mệnh đề sai **thuyết phục hơn** đi qua cùng cái cửa hỏng
- **N của luật rút gọn** — đề xuất 100 tin / 24 giờ / ưu tiên ranh giới im lặng, chưa có dữ liệu thật


---

## 13. Vòng thẩm định thứ ba — đánh giá ngoài + hai agent kiểm chéo (27/08)

Một bản đánh giá từ agent ngoài (18 mục) được đối chiếu bởi hai agent độc lập: một agent **soi từng mục vào code thật**, một agent **làm kế hoạch tối giản + thiết kế bộ eval**. Cộng phần tự kiểm của tôi. Ba nguồn hội tụ.

### 13.1. Quyết định cỡ — thay thế khoảng trống của phán quyết

> **Mục tiêu: 3 server × 100 tin/ngày (300/ngày). Khởi đầu: 1 server × 30 tin/ngày.**

Số học nền (từ phễu đo thật 6/19 lọc → 1/19 tới extractor):

| Đại lượng | Giá trị | Hệ quả |
|---|---|---|
| 300 tin/ngày quy token | **12k = 3/4 MỘT cửa sổ 16k** | Thành phần nào cần tưởng tượng 5.000/ngày mới đáng: **bỏ** |
| Lần gọi extractor | ~16/ngày | |
| Extract + verify (2 × 60s trên 9b) | **32 phút GPU/đêm = 2,2%** | Verifier chạy đêm thoải mái |
| Bão hoà verifier 1-vs-1 | ~3.400 tin/ngày (11× mục tiêu) | Đủ headroom |
| Bão hoà verifier so-cặp top-5 | ~1.100 tin/ngày | **Chết trước — khỏi xây** |
| Mục duyệt tay (đường mention) | 2–9/ngày ≈ 1–5 phút | Một người kham vô hạn |
| Mục duyệt nếu tầng 3 bật | 15–45/ngày, mỗi mục đọc tới 100 tin nguồn | **Gãy trong vài tuần** → E1 + E9 là điều kiện cần của tầng 3 |
| Lưu trữ | 60–120 MB/năm kể cả chỉ mục | Không đáng bàn |

### 13.2. Bốn mục NHẬN từ bản đánh giá ngoài (sau kiểm chéo)

| # | Mục | Vì sao, và điều chỉnh gì |
|---|---|---|
| **E8** | **Khoá Gemini → header `x-goog-api-key` + che secret ở tầng log** | ✅ Kiểm trên docs Google: header là chuẩn hiện hành, `?key=` là tương thích ngược. ~10 dòng. **Mục duy nhất mới-đúng-rẻ-vô-điều-kiện.** Làm TRƯỚC khi `GEMINI_API_KEY` vào `.env` → thành việc **0d** |
| **E1** | **Verifier 3 trạng thái** — hợp đồng cho việc "kiểm suy luận" mà §9.1 đòi nhưng chưa định hình | ENTAILMENT → ứng viên · CONTRADICTION → **hàng duyệt kèm lật-đổ điền sẵn** (điều chỉnh của agent kiểm code: **không bao giờ tự lật theo phán NLI**) · UNKNOWN → duyệt. Dạng **1-vs-1** với đúng dòng active của khoá đó — DB đã làm dedup hộ, so-cặp là thừa |
| **E14** (thu hẹp) | **Bộ eval trí nhớ** — phần cập nhật / thời gian / truy xuất | Tuyên bố "dự án không có eval" **sai một nửa**: benchmark trích xuất ĐÃ chạy trong test (75 ca + fixture 150 ca + harness). Thiếu thật: latest-fact, supersession, Recall@K. **Đã thiết kế xong 20 ca** (§13.4) |
| **E7** (thu hẹp) | **Chỉ quét secret bằng regex** trước mọi lời gọi cloud (API key, token, SĐT) | Vài dòng Python. Còn **giả-danh-hoá đầy đủ (tên→USER_001): BỎ** — mâu thuẫn thẳng với yêu cầu gán-người-nói của chính thiết kế (§7.5 cần `speaker_id` để xoá-theo-người), và NER tên tiếng Việt bằng regex thì nhiễu |

Cộng một mục **đôn sớm**: **E9 — UI duyệt hiện tin nguồn + phân trang.** Doc đã tự chỉ ra (§9.7), nhưng agent kiểm code thêm một mũi dao: docstring của chính `discord_memory_guard.py:13-14` nói *"con người LÀ bộ gác"* — mà con người chỉ thấy câu trích do model tự chọn. Ứng viên tầng-4 mang đúng một `source_turn_id` → join nội dung vào payload là việc nhỏ (~20 dòng + tham số phân trang). Trần 50 vỡ sau ~3 ngày ở 300/ngày.

### 13.3. Danh sách GIẾT và danh sách ĐÃ-CÓ-SẴN

**Giết:**

| Mục | Lý do |
|---|---|
| Bộ định tuyến truy vấn (BM25 vs dense) | Chạy cả hai < 30ms trên nền 2.600ms; classifier tiết kiệm ~20ms và mang tỉ lệ sai riêng |
| Importance scoring | Không quyết định nào tiêu thụ điểm: không prune, duyệt 16 mục/ngày quét một lượt. Và dự án **đã đo** confidence extractor = 1.0 bất kể đúng sai — thêm một điểm số nữa không phải giá trị miễn phí |
| Episode segmentation học máy | (kênh, ngày) ≈ 100 tin = 4k token; luật cắt-ở-khoảng-im đã có, 0 gọi model. Người tiêu thụ duy nhất (tầng 3) đang bị chặn |
| Dense embedding ngay | Hoãn theo tripwire: ca `para-01` ("đồ uống" → "trà sữa") đo Recall@5 — **< 0,60 thì xây, ≥ 0,80 thì chết hẳn**. Nếu xây: collection mới bắt buộc mang payload `{guild_id, channel_id, author_id, sent_at}` từ ngày đầu — không lặp lại lỗi mirror |
| Giả-danh-hoá PII đầy đủ | Xem E7. Việc riêng tư thật là **thiết kế xoá §9.5**, vẫn chưa làm |
| Bảng ứng viên + UI duyệt thứ hai cho tầng 3 | Chỉ cần khi tầng 3 mở — đừng xây trước |

**Đã-có-sẵn** (bản ngoài đề xuất lại; agent đã mở code từng dòng): tách Capture/Store/Retrieve/Remember (= §5/§6/§8 dưới tên khác) · hierarchy Message/Turn/... (= bảng đã có; "episode" = lô rút gọn có ranh giới im lặng) · scope + CHECK từng-scope + chỉ mục một-dòng-active (`constants:17-22`, `models.py:585-689`) · lifecycle 5/6 trạng thái (active/superseded/disputed/expired/deleted; thiếu đúng hard-delete = §9.5) · 3 loại trí nhớ (semantic = sổ cái, procedural = `workflow_rule`, episodic = tầng 1) · pipeline 9 bước (**7/9 đang chạy**; thiếu đúng E1 và importance-đã-giết) · lược đồ record 13 trường (**11/13 tồn tại**; 2 trường mới đáng lấy: `observed_at` = fix giờ-nói đã nằm kế hoạch, `verification{method,result}` thêm khi E1 ra đời).

Một điều chỉnh ưu tiên của bản ngoài bị **bác**: hạ cửa sổ 12→40 xuống P1. Nó sửa lỗi duy nhất từng xảy ra thật bằng một số nguyên — vẫn là LÀM NGAY.

### 13.4. Bộ eval trí nhớ — 20 ca, thiết kế xong

File đề xuất: `backend/tests/fixtures/discord_memory_e2e_v1.jsonl`. Tái dùng harness sẵn có (kể cả bộ đếm giả-mạo-chủ-thể); thêm hai chiều mới: **kịch bản nạp** (tin ingest vào DB lab theo thứ tự ngày — khuôn `nightly_eval.py`) và **mũi dò** (câu hỏi + kỳ vọng truy xuất/trạng thái).

Phân bố: **6 ca gieo từ 19 lượt production thật** · temporal ×3 (chuỗi 2–3 mắt, active phải là fact mới nhất) · contradiction ×3 (gồm phủ-định-không-thay-thế và lặp-lại-không-nhân-đôi — đúng cặp AUROC 0,59 nói embedding không phân biệt nổi) · attribution ×4 (tự-khai thắng lời-kể-hộ; cách ly xuyên người, xuyên guild) · verbatim ×2 · paraphrase ×2 (tripwire dense) · no-op ×3.

**Bốn ca cố tình TRƯỢT hôm nay = bài nghiệm thu:** `contra-01` (bộ ba Postgres §9.1) · `attrib-03` / `attrib-04` (rò rỉ §3.1 viết thành ca eval) · `real-01` (vụ trà sữa).

Ngưỡng gate (bất biến #4): extraction P ≥ 0,80 / R ≥ 0,70 chặn đổi prompt · `latest_fact ≥ 0,95` + `supersede_not_duplicate ≥ 0,90` + `forged_subject = 0` chặn tự-áp-dụng · `stale_leak@5 = 0` chặn đổi đường đọc · verbatim Recall@5 ≥ 0,90 chặn ship `search_history` · cặp 0,60/0,80 quyết dense. Nền đo hiện có (v5, trên 2b): fact_content 0,65 · no_op **0,42** (lỗ đo lớn nhất) · operation 0,73.

### 13.5. Phát hiện MỚI của vòng này — vách đá không nguồn nào trước đó nhắc

**BM25 dựng-lại-trên-đường-đọc là điểm gãy thật ở 300/ngày.** Khuôn hiện tại (`postgres_bm25_service.py:98-114`) dựng lại toàn bộ chỉ mục dưới `RLock` **ngay trên đường đọc**; TTL fingerprint chỉ trải mỏng phép *kiểm*, không trải phép *dựng*. Tuyến tính ~42µs/tin: 1 tháng +0,36s · 80 ngày ~1,0s · 6 tháng 2,3s · 1 năm **4,6s — vượt toàn bộ 2,6s chờ trung vị**, và một guild dựng thì hai guild kia bị khoá. Mỗi-guild-một-chỉ-mục chia 3 độ dốc nhưng **không làm phẳng**.

→ Đặc tả việc 2 đổi theo: (a) snapshot **theo guild ngay trong SQL** (đằng nào cũng cần cho cách ly — §6.1), (b) **dựng lại RỜI đường đọc** — trả bản cũ + debounce nền (cũ vài giây là vô hại với "tôi nói câu đó khi nào"), (c) phương án đo kèm: **Postgres FTS** (`tsvector` + GIN trên văn bản đã qua `tokenize_vietnamese`, config `simple`) — tăng dần, không dựng lại, mili-giây ở 100k dòng, DB có sẵn trong stack. Quyết bằng đo khi xây.

**Sàn 24-giờ-mỗi-kênh của tầng 3 chết ở 3 guild**: ~9 lô gần-rỗng/ngày, phụ trội prompt (~600 token) nuốt nội dung. Khi tầng 3 mở lại: thay bằng ngưỡng **≥ 20 tin chưa xử lý**.

### 13.6. Thứ tự thi công v3 — bảng hiệu lực

| # | Việc | Chi phí | Điều kiện |
|---|---|---|---|
| **0a** | `LOCAL_AI_API_KEY` + `LOCAL_AI_PROTECT_READS=true` | 2 dòng `.env` | ✅ **27/08** — kèm 0e: `AUTO_APPLY_THRESHOLD=off` (công tắc có sẵn trong validator, thay cho 1.1 bị chặn) |
| **0b** | Cửa sổ 12 → 40 | 1 số nguyên | ✅ **27/08** — `settings.py`, kèm chú thích thí nghiệm |
| **0c** | Sửa đường đọc + xoá `search_memory` + bịt endpoint | 4 tệp | ✅ **27/08** — SELECT sổ cái luôn-chạy trong `discord_turn_service` (repo mới `list_active_context_memories`, lọc guild+subject+active, cùng transaction dựng ngữ cảnh — bất biến #2 giữ); công cụ + nhánh dispatch + tham số ctor đã gỡ; endpoint khoá bởi 0a. **2 test mới**: fact vào prompt cho đúng người, không rò sang người khác, superseded không hiện |
| **0d** | Khoá Gemini → header + che secret ở log sink | ~10 dòng | ✅ **27/08** — `x-goog-api-key` cả 2 endpoint; filter `_redact_secrets` (5 biến env) trên sink file |
| **1** | Mở nghe 1 kênh, **đếm vài ngày** (bất biến #8) → migration sổ gốc + bảng chính sách kênh | bảng mới · 0 gọi model | 🟡 **Nửa đầu ✅ 27/08**: bộ đếm thụ động vũ trang trên kênh `1442208821333463194` — `discord_bot/passive_listener.py`, đếm **trước mọi cổng** (cả tin bot, gắn `author_is_bot` để §9.3 quyết bằng số), thread theo kênh cha, **không lưu nội dung**, ghi hỏng không gãy trả lời. File: `data/discord_listen/passive_counts.jsonl` (neo `__file__` — CWD container là `/app/backend`, đường tương đối rơi ngoài mount). Đọc: `python -m scripts.passive_listen_report`. **Nửa sau ✅ 28/08**: ba quyết định §12 chốt (xem §13.7) → migration `20260828_30` — `discord_channel_messages` (sent_at suy từ snowflake lúc ghi, `is_bot`, `content_original` một-lần, xoá mềm + xoá chữ) + `discord_channel_policies` (audit bất biến #6, upsert `env` lần đầu kênh xuất hiện). Bot gửi tin nghe được **fire-and-forget cạnh bộ đếm** — ghi hỏng không bao giờ chạm đường trả lời; sự kiện sửa/xoá raw được tôn trọng |
| **2** | Service BM25 theo-guild, dựng lại **rời đường đọc** (§13.5) + công cụ `search_history` | service thứ hai | ✅ **28/08 — phương án (c) §13.5 thắng**: Postgres FTS (`tsvector` config `simple` trên `tokenize_vietnamese`, GIN) — tăng dần theo dòng, **không tồn tại vách dựng-lại** để phải "rời đường đọc" nữa. Truy vấn OR-của-lexeme + `ts_rank` (plainto AND không bao giờ khớp câu hỏi dài vào tin ngắn). `search_history` vào `AGENT_TOOLS`, **guild do server bơm qua `tool_context`** (turn→chat→agent), model không tự chọn guild được; đường web không có ngữ cảnh → công cụ từ chối. Cổng §13.4: recall-verbatim 2/2 thắng 6 tin nhiễu trong top-5. `test_discord_history_service.py` 9 ca |
| **3** | Bộ eval **21 ca** (§13.4) | fixture + runner | ✅ **27/08 — pha trạng thái/truy xuất/gác** (`tests/fixtures/discord_memory_e2e_v1.jsonl` + `scripts/memory_e2e_eval.py`, 0 gọi model, mirror Qdrant stub). Kết quả chạy thật: **16 PASS · 2 KNOWN-FAIL đúng chỗ · 3 PENDING (job 2)**. `attrib-03`/`attrib-04` PASS = **0c nghiệm thu bằng máy**; `contra-01`/`guard-02` KNOWN-FAIL được **ghim trong suite** (`test_memory_e2e_eval.py`) — ngày chúng thành FIXED là ngày việc 4 hạ cánh. Pha `--with-extractor` (chấm P/R trích xuất) thuộc việc 4. **Phát hiện khi chạy**: lặp nguyên văn từ tin MỚI vẫn tạo version churn ở tầng áp dụng — idempotence chỉ phủ cùng-một-ứng-viên; chống-lặp thật nằm ở extractor (ca `contra-03` ghi lại) |
| **4** | Verifier 3 trạng thái, 1-vs-1 + cột `verification{method,result}` | 2×60s/ứng viên, nền | ✅ **27/08 — máy móc xong, ship TỐI**. (a) **Hai luật tất định vào guard** — vế-phủ-định (đánh trên chữ THÔ, không gấp dấu: đừng/dùng và nữa/nửa gấp dấu là trùng nhau) + tối-thiểu-2-từ-nội-dung — **đo 0-chi-phí trên benchmark 75 ca** (coverage 96,7% / poison 21,6% không đổi một li) và lật `contra-01`+`guard-02` thành **FIXED** (e2e: FIXED=2 · PASS=16 · PENDING=3 · 0 KNOWN-FAIL). (b) `DiscordMemoryVerifierAdapter` (nli-1v1, prompt verify-v1, fail-safe → unknown) + migration `20260827_28` + bước `verify_proposal` trong worker (model NGOÀI transaction — bất biến #2) + cổng autonomy đòi `entailment`. **Cờ `DISCORD_MEMORY_VERIFIER_ENABLED` mặc định TẮT** — bật + mở lại tự-áp-dụng chỉ sau khi pha `--with-extractor` đo qua ngưỡng §13.4. Suite: 680 pass |
| **5** | Vá UI duyệt: hiện tin nguồn + phân trang | ~20 dòng | ✅ **27/08** — `list_pending` join tin gốc từ `discord_session_turns` (người duyệt thấy NGUỒN, không chỉ câu trích model tự chọn — E9), tham số `limit`/`offset` phá trần-50, dashboard hiện dòng «tin gốc» + nút Tải thêm. Test hợp đồng: `test_memory_review_pagination.py` |
| **6** | Tầng 3 / Gemini | — | **giữ HOÃN** — 3 chốt cũ (§9.1 → việc 4, §9.7, đường đọc §9.4) + thay sàn 24h bằng ngưỡng ≥ 20 tin |

### 13.7. Ngày 28/08 — hội thoại guild 2 phơi 4 lỗi, 5 bước vá trong một ngày

Bằng chứng: 20 lượt thật (2 người) 26-27/08 — bot xác nhận đúng ngày sinh ở lượt
12 rồi **trả 5 câu từ chối trùng từng byte** (sha `8672a8e3…`, tokens_in tăng
1186→3763 chứng minh model được gọi thật mỗi lượt và lịch sử có đủ dữ kiện);
hai lượt bị mắng thì nhớ lại hoàn hảo. Chẩn đoán: **echo-lock** — model 9b chép
nguyên văn câu trả lời cũ của chính nó khi câu hỏi cùng hình dạng lặp lại.

1. **Bước 1 — lời dặn chống tự-vọng.** Persona viết lại (bỏ câu riêng tư dễ vặn
   thành cớ từ chối) + khối "Quy tắc dùng lịch sử" gắn CUỐI
   `DISCORD_SPEAKER_SYSTEM_INSTRUCTION`. **Vị trí là biến số đo được**: replay 5
   câu hỏng trên lịch sử đã nhiễm — baseline 1/5, luật giữa file 10/15, luật
   cuối khối system **13/15**. Ca lì nhất (lượt 17) chờ sổ cái trị tận gốc.
2. **Bước 2 — công cụ tài liệu chỉ chạy guild nhà.** Lượt 5 guild 2 đã
   `search_documents("Phương Anh thông tin cá nhân…")` trên kho tài liệu riêng
   của chủ (một corpus toàn backend). `DISCORD_AGENT_TOOLS_GUILD_ALLOWLIST`
   trong `.env`; guild lạ rơi về chat thường.
3. **Bước 3 — từ vựng v2.** Lượt 12 bị filter phán `no_durable_fact` — ca #2/#3
   của lỗ từ vựng (sau trà sữa). Thêm `user.birthday` (+`favorite_drink/food`),
   luật `personal_fact` (bắt buộc chữ số → câu hỏi vẫn `question_only`; lookbehind
   thân tộc chặn hearsay "bạn tôi sinh ngày…"), schema pipeline v1→v2 (wire giữ
   v1) mở tái-trích lượt cũ. Extractor no_op giờ **chốt sổ** (`not_required`/
   `no_op`) — hết dòng rác 0.000 trong hàng duyệt; 2 dòng rác cũ đã chuyển.
4. **Bước 4 — sổ cái nạp THEO GUILD, từng dòng ghi chủ nhân** (`về author_id=…`
   khớp nhãn lịch sử). Hai ca dùng thật đều hỏi chéo người — lọc theo người-hỏi
   chặn đúng thứ cần trả lời. **attrib-03 đổi ngữ nghĩa có chủ ý**; ranh giới
   tuyệt đối còn lại là GUILD (attrib-04 + test xuyên-guild mới ghim).
5. **Bước 5 — job 1+2 hạ cánh** (xem bảng trên). Ba quyết định §12 chốt bằng số
   đếm 2 ngày: §9.3 ghi cả tin bot (gắn `is_bot`, trích xuất không bao giờ ăn);
   §5.3 `content_original` giữ bản đầu một lần; §9.5 xoá mềm + xoá chữ ngay khi
   Discord xoá, xoá-cứng theo người = DELETE thường vì FTS theo-dòng.

**Rạng sáng 28/08 (~04h) — pha `--with-extractor` XÂY XONG và CHẠY, gate §13.4 ĐẠT.**
Runner nối filter thật + extractor 9b thật + verifier thật trên 22 ca (chuỗi
target theo-guild để update-vs-create chấm như production). Vòng 1: P=0.89 ·
**R=0.40** — 11/12 ca trượt đều là `filter=no_durable_fact`: nút thắt nằm ở
**tầng lọc regex**, không phải model. Vòng 1 cũng tóm được lỗi verifier ship
tối: thiếu `think:false` → suy nghĩ nuốt trọn `num_predict=8`, content RỖNG,
mọi verdict thành unknown — tự-áp-dụng sẽ không bao giờ nổ nếu bật mù. Sau khi
mở 6 nhóm mẫu lọc (card/vga sở hữu, stack cá nhân không cần "dự án", "gọi tôi
là X" trần, chuyển/rút quyết định stack có cổng tên-công-nghệ, chặn câu-hỏi-về-
sở-thích cùng-vế) + 12 dòng fixture ghim: **Vòng 2: P=0.94 (16/17) · R=0.80
(16/20) · forged=0 · verifier entailment 16/16 trên ca đúng, và phán
`contradiction` cho đúng ca sai duy nhất** (delete-thay-vì-update → về hàng
duyệt người, đúng tầng). Tripwire real-01 lật sống: "tôi thích trà sữa" →
`create user.favorite_drink` conf 1.00. Hệ quả: `DISCORD_MEMORY_VERIFIER_ENABLED=true`
từ lần khởi động sau; tự-áp-dụng mở bằng một dòng
`DISCORD_MEMORY_AUTO_APPLY_THRESHOLD=0.8` khi chủ dự án quyết (rollout bậc
thang: xem verdict trên lưu lượng thật vài hôm trước). Công cụ `search_history`
thêm chế độ không-query = N tin mới nhất theo thời gian (phục vụ "tóm tắt 20
tin gần đây"). Còn treo: tripwire dense `recall-para-02` chờ cặp ngưỡng §13.3.
