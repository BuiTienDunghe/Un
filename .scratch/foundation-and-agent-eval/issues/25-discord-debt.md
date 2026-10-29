# 25 — Nợ còn lại sau khi tách mềm Discord: lõi vẫn biết tên Discord ở ba chỗ

Status: đang làm 1B — chủ dự án chọn 1B, 2A, 3A (30/10)
Type: task
Blocked by: 22 (đã gộp d1711e7); C4 của 22 nên gộp trước, để shim không còn

## Bản chất

Sau ticket 22, lõi không còn **import** code Discord: cả gói `app/discord/` có xoá đi thì agent, tài liệu
và trí nhớ web vẫn nạp được. Nhưng lõi vẫn còn **biết tên** Discord ở ba chỗ:

- bảng cấu hình chung còn chứa các núm vặn của bot;
- bộ phân việc nền còn ghi sẵn địa chỉ việc nạp trí nhớ Discord;
- ba dịch vụ lõi còn tự đọc bảng của Discord để hiện số lên dashboard và trang tình trạng.

Ba món này không gây lỗi gì. Cái giá của chúng chỉ lộ ra khi có thay đổi: muốn gỡ hẳn Discord, hay thêm
một kênh thứ hai (vd Telegram), thì phải sửa lõi ở đúng ba chỗ này. Ticket này liệt kê từng món, kèm các
cách xử lý. Có thể chọn "để nguyên" cho cả ba.

## Hiện trạng (đếm trên main ec4d843, 28/10)

| Món nợ | Ở đâu trong lõi | Dùng để làm gì |
|---|---|---|
| 1. Cấu hình | `config/settings.py`: **23** trường `discord_*` (thiết kế 22 ghi 25; đếm lại bằng `grep -E '^\s+discord_[a-z_]+\s*:'`), cùng các validator đọc chúng (dòng 210–265) | Phần lõi đọc 7 trường: `model_registry.py:1195-1204` (bật/tắt vai trò extractor, verifier, condenser và ghim tag thô), `main.py:119,144-145` (tên hàng đợi trí nhớ, cờ ingestion cho `/health`), `workers/tasks.py:95` (tên hàng đợi). 16 trường còn lại chỉ gói Discord đọc |
| 2. Tuyến việc nền | `jobs/routing.py:6,34-36`: hằng `DISCORD_MEMORY_INGEST_JOB_TYPE` và chuỗi `app.discord.memory_tasks.discord_memory_ingest` | `JobQueueService` đẩy việc theo tuyến này. `operational_service.py:28,336-362` dùng hằng đó để đếm việc trí nhớ đang chờ, đang thử lại hay đã hỏng cho `/health` |
| 3a. Dashboard | `services/dashboard_service.py:16-18,93-112` đọc `DiscordConversationSession`, `DiscordSessionTurn`, `DiscordTurnDelivery` | Ô "Discord agent" trên dashboard. `DashboardResponse.discord` (lõi) giữ hình dạng của ô này |
| 3b. Tình trạng và nhật ký hành động | `services/operational_service.py:19-20,254-261` đọc `DiscordMemoryCandidate`, `DiscordMemory` | Dòng thời gian "hành động tự động" (`agent_activity`): quyết định trí nhớ, kèm tay gỡ nếu còn gỡ được |
| 3c. Danh sách hội thoại web | `stores/postgres_auxiliary_store.py:18,195-197` join `DiscordConversationSession` | Loại các hội thoại có nguồn Discord khỏi danh sách hội thoại web |

Nhỏ hơn, không tính là nợ: `chat_service.py:163` ghi `source = "discord"` khi có `guild_id`, và
`model_registry.py` có tên biến môi trường `DISCORD_MEMORY_*`. Cả hai chỉ là nhãn.

## Các cách xử lý

### Nợ 1 — cấu hình

| Cách | Làm gì | Được | Mất |
|---|---|---|---|
| 1A. Để nguyên | — | Không rủi ro, không tốn gì | Gỡ Discord vẫn để lại 23 trường chết; lõi tiếp tục lớn thêm trường Discord nếu không ai canh |
| 1B. Chặn lan, giữ chỗ | Thêm một test: ngoài `app/discord/`, chỉ `model_registry.py`, `main.py`, `workers/tasks.py` được đọc `settings.discord_*` (danh sách cố định 7 trường). Nhóm 23 trường thành một khối có chú thích | Rẻ (một test); chặn được nợ mới; không đổi `.env` | Tên trường vẫn nằm trong lõi |
| 1C. Gói tự đọc cấu hình của nó | `app/discord/settings.py` là một `BaseSettings` riêng, đọc cùng biến `DISCORD_*` nên `.env` không đổi; lõi nhận 7 giá trị nó cần qua tham số. Bật/tắt vai trò extractor/verifier/condenser trong registry phải đổi thành gói khai báo | Lõi sạch tên Discord trong cấu hình | Hai đối tượng cấu hình; 3 validator chéo (vd `DISCORD_MEMORY_EXTRACTOR_MODEL` với `MODEL_VERSION_EXTRACTOR`) phải tách hoặc nhân đôi; registry cần một ổ cắm mới, đụng code đã chạy ổn từ 03fd6e4; rủi ro cao nhất trong ticket |

### Nợ 2 — tuyến việc nền

| Cách | Làm gì | Được | Mất |
|---|---|---|---|
| 2A. Để nguyên | — | Không rủi ro | Lõi biết tên một việc Discord |
| 2B. Gói đăng ký tuyến | `jobs/routing.register_route(job_type, route)`; gói Discord đăng ký lúc khởi động | Lõi không còn chuỗi Discord | Không chỉ API mà cả worker RQ và outbox dispatcher đều phải gọi đăng ký, vì chúng không chạy lifespan của FastAPI; quên ở một tiến trình thì việc nạp trí nhớ hỏng mà không báo. `/health` vẫn cần biết loại việc để đếm, nên phải kèm cách 3B |
| 2C. Tuyến khai trong cấu hình | Bảng `job_type → (queue, task_path)` chuyển vào `models.yaml` | Không code lõi nào biết tên Discord | Gõ sai thì chỉ lỗi lúc chạy; dời nợ từ code sang cấu hình chứ không xoá |

### Nợ 3 — dịch vụ lõi đọc bảng Discord

| Cách | Làm gì | Được | Mất |
|---|---|---|---|
| 3A. Để nguyên | — | Model ở lõi (lựa chọn 2 của ticket 22), nên việc đọc này không phạm luật của 22 | Gỡ Discord thì phải sửa ba dịch vụ này |
| 3B. "Người góp số" | Dashboard, `/health` và nhật ký hành động nhận danh sách hàm góp số do gói đăng ký; Discord góp ô của nó | Lõi không gọi tên model Discord | `DashboardResponse.discord` là hợp đồng với frontend: hoặc giữ trường và để người góp điền, hoặc đổi frontend. `/health` còn chạy trong tiến trình worker, nên lại vướng chuyện đăng ký như 2B |
| 3C. Riêng 3c: cột `origin` trên `conversations` | Đánh dấu nguồn ngay trên hội thoại, bỏ join | Danh sách hội thoại web không cần biết bảng Discord | Cần migration và backfill. Ticket 22 cấm migration; ở đây phải duyệt riêng |

## Ý kiến của tôi (Nhân viên 2), chủ dự án chọn khác được

**1B, 2A, 3A.** Lý do: tách mềm đã đạt điều đáng giá nhất, là lõi nạp được khi không có Discord. Các
cách sạch hơn (1C, 2B, 3B) đều phải thêm một ổ cắm mà mọi tiến trình đều phải nhớ cắm, trong khi hôm nay
chưa có kênh thứ hai nào và cũng chưa có kế hoạch gỡ Discord. 1B là cách rẻ duy nhất mà chặn được nợ mới.
Nếu sau này thật sự thêm Telegram, lúc đó làm 2B và 3B cùng một lượt, vì cả hai cần cùng một cơ chế đăng ký
ở tiến trình worker.

## Nghiệm thu (tuỳ cách được chọn)

| Cách | Kiểm |
|---|---|
| 1B | Test mới đỏ khi một module lõi ngoài danh sách đọc `settings.discord_*`; kiểm đột biến bằng cách thêm một chỗ đọc |
| 1C | Bộ test đầy đủ xanh; `.env` hiện có khởi động y như cũ; `/models.registry` của extractor/verifier/condenser trùng trước khi đổi |
| 2B | Worker RQ, outbox dispatcher và API đều thấy tuyến; có test chạy riêng từng điểm vào |
| 3B | `GET /api/dashboard/stats` và `/health` trùng từng trường trước/sau; frontend không đổi |
| 3C | Migration có test lên/xuống; danh sách hội thoại web trùng trước/sau trên DB thật đã sao lưu |

## Comments
- 30/10 00:30 (opus 5.5): chủ dự án chọn **1B, 2A, 3A** ("chặn lan, rẻ"). 1B làm trên `wip/25-config-guard`; 2A và 3A là để nguyên.
