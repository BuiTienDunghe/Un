# Plan đột phá: bộ óc nhỏ trong khung tốt ngang bộ óc lớn

Status: đề xuất, chờ chủ dự án chọn hướng
Type: plan
Viết 23/11/2026 bởi claude-fable-5-2. Chưa chạy phép đo nào cho plan này: mọi con số là số dự án đã đo (có ngày) hoặc số
của nguồn ngoài (có nhãn). Bằng chứng ngoài nằm ở `harness-survey-2026-11-23.md` cùng thư mục, gọi tắt là KS.

## Bản chất

Ún đang chuyển sang một bộ óc nhỏ để chạy nhanh và vừa máy yếu. Bộ óc nhỏ làm tốt việc được giao rõ, nhưng kém ở việc tự
quyết: lúc nào nên đi tra, lúc nào trả lời luôn, lúc nào đã xong. Hiện giờ cái khung quanh nó giao các quyết định đó cho
chính nó bằng lời dặn, và lời dặn kiểu nào cũng lệch một bên: dặn "đừng tra bừa" thì nó bỏ cả lúc cần tra, bỏ câu dặn thì
nó đi tra cả khi chỉ được chào. Đột phá không nằm ở việc viết lời dặn khéo hơn. Nó nằm ở hai việc: chuyển những quyết định
lặp đi lặp lại từ bộ óc sang phần code quanh nó, và dựng một phòng thử để mỗi thay đổi chỉ được giữ khi nó thắng trên những
bài chưa ai nhìn thấy lúc sửa. Đích đo được: bộ óc nhỏ trong khung mới làm việc ngang bộ óc lớn trong khung cũ.

## Vì sao tin hướng này

Số của chính dự án (08/11 và 10/11, Ollama 0.40.13, nhiệt độ 0, gỡ model trước mỗi bài; `docs/SO_DO.md`):

| Phép đo | 9B trong harness | 2B chạy trần | 2B trong harness |
|---|---:|---:|---:|
| Agent Eval v0 /66 | 57 | — | 47 |
| BFCL simple_python /400 | 352 | 287 | 341 |
| BFCL irrelevance /240 | 201 | 179 | **82** |
| BFCL multi_turn_base /200 | 31/159 | 43 | 29 |
| Trung vị mỗi bài Agent Eval | 4,4 s | — | 2,0–2,1 s |
| VRAM đỉnh | 6.950 MiB | — | 3.376 MiB |

Các phép thử tìm nguyên nhân của dự án, đều trên mẫu chọn sau khi thấy kết quả nên chỉ là chẩn đoán:

| Phép thử | Kết quả | Ngày |
|---|---|---|
| 9B, bỏ câu "kiến thức chung thì trả lời thẳng" | 53 → 74 trên 81 bài simple_python | 07/11 |
| 2B, lời dặn trung tính theo công cụ thật | irrelevance 5/8 → 0/8; simple_python 5/8 → 6/8 | 08/11 |
| LFM3, giữ kết quả công cụ qua lượt + 10 vòng + lời dặn trung tính | 4/12 → 9/12 bài nhiều lượt | 08/11 |

Đọc hai bảng: harness kéo 2B sang gọi công cụ, nên được ở bài cần gọi và mất nhiều hơn ở bài không được gọi. Lời dặn là đòn
bẩy hai chiều: cách viết giúp phía này thì hại phía kia. Mất kết quả công cụ giữa các lượt và trần 3 vòng cùng gây hại ở
bài nhiều lượt.

Bằng chứng ngoài, bốn dòng quyết định (đủ ở KS):

| Điều | Số đo | KS |
|---|---|---|
| Cùng model 2B, đổi harness | 0,017 → 0,821 (tự báo) | §1 |
| Lời dặn "đừng gọi" chặn cả lệnh gọi cần thiết; nhu cầu gọi đọc được trước khi model viết | AUROC 0,89–0,96 | §2 |
| Thêm chữ vào system prompt | −2,3 điểm, trong khi sửa công cụ +3,3 | §3 |
| Máy tự tìm harness trên Qwen3.5-2B | ngang tinh chỉnh model ở bài tra cứu, với 5,79 % số lượt chạy; nhưng bản chạy lại độc lập trên bộ khác cho +0,0 ở bài chưa thấy | §4 |

## Đích đề xuất

Ngưỡng là đề xuất; ba dòng BFCL lấy nguyên luật trong `PREREGISTRATION-2b-baseline.md`.

| Chỉ số (2B trong harness) | Hôm nay | Đích | Lý do ngưỡng |
|---|---:|---:|---|
| Agent Eval v0 /66 | 47 | ≥ 55 | 9B đạt 57; nhiễu nền khoảng 3 bài |
| irrelevance, chênh ròng trần hơn harness | 97 | < 15 | luật "khe hở đã khép" |
| simple_python, chênh ròng harness hơn trần | 54 | ≥ 30 | luật "đánh đổi vẫn đúng" |
| multi_turn_base, harness so với trần | thua 14 | không thua | p ≥ 0,05 hoặc harness hơn |
| Chat không được gọi công cụ, 18 bài | chưa đo | ≤ 1 bài tự gọi | luật bảng Discord-chat |
| Lượt gọi model và độ trễ trung vị mỗi bài | 2,0–2,1 s | không tăng | bất biến 7 |
| VRAM đỉnh | 3.376 MiB | dưới 4 GB | vừa card 4 GB |

Mọi dòng đo cùng ngày với đối chứng, và chỉ tính khi đạt trên tập xác nhận khoá (Đợt 0).

## Các hướng có thể chọn

| Hướng | Làm gì | Ưu | Nhược, chi phí, rủi ro |
|---|---|---|---|
| **A. Code quyết định thay model** | Từng quyết định lặp lại (đưa công cụ nào, gọi hay không, tham số hợp lệ chưa, xong chưa) chuyển sang code; mỗi thứ một cờ | Không thêm lượt gọi model. Hợp bất biến 7. Bằng chứng model nhỏ nhiều nhất (KS §1, §2) | Nhiều mảnh nhỏ, mỗi mảnh một phép đo. Hiệu ứng phụ thuộc model: có nghiên cứu thấy 2B không đổi dưới ba kiểu khung. Chưa ai đo trên hỏi đáp tài liệu 3 vòng |
| **B. Phòng thử harness** | Tập xác nhận khoá, luật so sánh cố định, rồi vòng "đề xuất, thử, giữ hoặc bỏ" chạy tự động với model mạnh làm người đề xuất ngoài đường trả lời | Biến cách làm 02–08/11 thành máy. Trace đầy đủ là đầu vào quý nhất và dự án đã có. Với 2B, mỗi nhánh của một vòng thử nhanh (66 + 25 bài) mất khoảng 9 phút GPU theo số đo 08/11 | Bản chạy lại độc lập cho +0,0 trên bài chưa thấy: không có tập khoá thì hướng này tự lừa mình. Khoảng 10 triệu token đề xuất mỗi vòng ở bản gốc. Phải viết bài mới |
| **C. Dạy lại model nhỏ** | Chưng cất 9B sang 2B bằng trace của chính harness (mục D2 cũ) | Sửa tận gốc. WHALE: xen kẽ tìm harness và chỉnh model cho kết quả cao nhất | LoRA gọi công cụ công khai làm irrelevance 80 % → 42 %. Chỉnh model riêng lẻ cần hơn 500 nghìn lượt chạy. `.venv-train` đã xoá. Không nguồn nào đo cách này trên bộ bài như của ta |
| **D. Hai tầng: 2B trước, 9B khi luật rẻ báo khó** | Bỏ chốt chặn 9B trong `small_model_policy.py` | Có thể lấy lại một phần trong 10 bài mà không chờ nghiên cứu, ở máy 16 GB | Không chạy được trên card 4 GB. Đổi model tốn thời gian nạp. Không tìm thấy nghiên cứu nào về kiểu leo thang này ở model cục bộ. Trái hồ sơ model nhỏ hiện hành ("không chạy 9B" trong README) |
| **E. Giữ nguyên, làm tiếp ticket 42–54** | Không đổi hướng | Không rủi ro mới | Khe hở 97 bài và 10 bài vẫn nguyên; mỗi tính năng mới tiếp tục đo trên thước cũ |

Ý kiến của người viết: làm phần thước đo của B trước, rồi A, rồi phần tự động của B, và chỉ mở C khi A và B đã phẳng. Lý
do: A có nhiều bằng chứng nhất cho model nhỏ và không tốn lượt gọi; nhưng thiếu tập khoá của B thì 66 bài không phân biệt
được lợi thật với nhiễu (cần thắng:thua 6:0 hoặc 10:2 mới đủ, KS §6). D mâu thuẫn với đích chạy trên máy yếu. Đây là ý
kiến; các hướng khác vẫn khả thi nếu chủ dự án đặt ưu tiên khác, ví dụ chọn D nếu chỉ cần máy 16 GB.

## Trình tự nếu chọn B-thước-đo → A → B-tự-động

Mọi mục mặc định tắt, đo riêng từng mục so với đối chứng cùng ngày, đúng luật ở `.scratch/future-plan/map.md`.

**Đợt 0. Thước đo. Không đổi hành vi sản phẩm.**

| # | Việc | Ghi chú |
|---|---|---|
| 0.1 | Chạy mốc 2B cùng ngày đã đăng ký 11/11 và chưa chạy | Khoảng 3,7 giờ GPU theo ước tính trong bản đăng ký |
| 0.2 | Lập tập xác nhận khoá: chỉ script điều phối đọc, người và AI sửa lời dặn hay code không xem trace của nó | 105 bài tự viết hiện có đã bị nhìn nên chỉ làm tập làm việc. Ứng viên: 300 bài BFCL đã tách bằng băm ở tool-state v2, When2Tool, Multilingual-BFCL tiếng Việt, và bài tiếng Việt mới |
| 0.3 | Ghi một lần luật so sánh: xen kẽ cùng ngày, McNemar chính xác, bảng thắng:thua tối thiểu, khoảng Wilson | Thêm cột "ổn định": cùng bài chạy ấm K lần, vì sản phẩm chạy ấm còn bài thi chạy nguội |
| 0.4 | Nối lại bảng điểm lịch sử | Dòng cuối là 01/11, chưa có dòng 2B nào |
| 0.5 | Một phép đo: Ollama có dùng lại phần đầu prompt của qwen3.5:2b giữa các vòng và các lượt không | Đọc số token đã dùng lại mà Ollama báo. Quyết định mục 1.5 có đáng làm |

**Đợt 1. Năm thay đổi không thêm lượt gọi model.**

| # | Giả thuyết | Hiện trạng trong code | KS |
|---|---|---|---|
| 1.1 | Chỉ đưa công cụ dùng được ở lượt này, và sinh lời dặn từ đúng danh sách đó | Lượt web thấy 7 công cụ, trong đó `search_history` và `remember` chỉ trả `TOOL_UNAVAILABLE_HERE`; `AGENT_GUIDE` là chuỗi cố định | §2 #5 |
| 1.2 | Kiểm tham số theo schema ở một chỗ, trả lỗi kèm ví dụ đúng; thử cho công cụ không tham số một tham số bắt buộc | Tham số không phải dict bị đổi thành `{}`; `system_status` và `current_time` không có tham số | §2 #2, #9 |
| 1.3 | Cắt kết quả dài giữ cả đầu và đuôi | `_dump` bỏ từ cuối danh sách | §2 #3 |
| 1.4 | Một ví dụ lệnh gọi mẫu trong prompt; sau đó lấy ví dụ từ lượt chạy đạt của chính Ún, mỗi lượt một mẩu | Không có ví dụ nào | §2 #4, §4 |
| 1.5 | Giữ phần đầu prompt không đổi giữa các lượt | Khối trí nhớ phụ thuộc câu hỏi đứng trước lịch sử; dòng thành viên server nằm ở tin đầu | §2 bảng máy chủ |

Rủi ro đã thấy trước: 1.1 gần với "lời dặn trung tính theo công cụ thật" của 08/11, thứ từng làm 2B sụp ở irrelevance. Vì
vậy 1.1 chỉ được giữ khi cả simple_python và irrelevance cùng không tụt.

**Đợt 2. Tách quyết định "gọi hay không" khỏi lời dặn.** Ba cơ chế, rẻ trước:

| Cơ chế | Tốn | Ưu | Nhược |
|---|---|---|---|
| 2a. Luật code: tin chào hỏi hoặc không có dấu hiệu cần dữ liệu thì không đưa công cụ | 0 lượt gọi | Rẻ nhất, dễ kiểm | Dễ chặn nhầm câu hỏi giọng trò chuyện (ba bài `hist-d03..05`) |
| 2b. Bộ phân loại bằng model nhúng đang có, so với ví dụ đã gán nhãn | 0 lượt gọi sinh; có độ trễ nhúng | Model chấm điểm nhỏ nằm ngoài ngân sách của bất biến 7 | Bằng chứng "đọc được nhu cầu gọi" là từ bên trong model sinh, không phải từ model nhúng ngoài; chuyển sang là giả định |
| 2c. Một lượt hỏi một chữ, lấy xác suất, như `tools/label_server.py` | +1 lượt gọi ngắn | Gần bằng chứng nhất | Cần ngoại lệ mới của luật 5 |

Khi một cơ chế đạt thì gỡ câu "kiến thức chung thì trả lời thẳng" khỏi lời dặn và đo lại cả hai phía. Cổng: ba dòng BFCL
và dòng chat trong bảng đích, cộng bảy bài "cần gọi" của bộ Discord-chat không kém đi.

**Đợt 3. Việc nhiều lượt.** Chạy phép đo đã đăng ký của `tool-state-continuity` (giữ kết quả công cụ qua lượt). Thử trần
theo thời gian thay cho 3 vòng: 2B mất khoảng 2 giây mỗi bài nên 90 giây chứa được nhiều vòng hơn. Gộp các bước kiểm hiện
có (`lookup_check`, `answer_check`, `read_rest`, `promise_check`) thành một cổng hoàn tất với một lượt thử lại duy nhất
(KS §2 #1), thay vì mỗi bước kiểm một ngoại lệ.

**Đợt 4. Vòng thử tự chạy.** Model mạnh, chỉ là công cụ phát triển, đọc trace các bài trượt của tập làm việc cùng mã
nguồn, đề xuất sửa đổi không gắn với bài cụ thể, mỗi sửa kèm một dự đoán. Script chạy đối chứng và ứng viên cùng ngày. Chỉ
ứng viên thắng trên tập làm việc mới được một lần chạm tập xác nhận. Chặn khớp quá mức bằng: trần độ dài lời dặn, số lần
chạm tập xác nhận có hạn, và phát lại trace để kiểm sửa đổi chỉ-code mà không cần GPU.

**Song song, không đụng vòng agent:**

| # | Việc | Vì sao | KS |
|---|---|---|---|
| S1 | Trí nhớ nguồn: thêm tìm theo nghĩa trên tin nguyên văn bằng model nhúng đang có; hiện chỉ tìm theo từ | Hướng lưu nguyên văn của dự án được nghiên cứu độc lập ủng hộ; model nhúng là đòn bẩy lớn nhất | §5 |
| S2 | Lúc lập chỉ mục, thay lượt gọi model cho từng chunk bằng tiền tố đường dẫn mục; đo trên cổng 82 câu | Nếu ngang nhau thì việc index không còn tốn lượt gọi model nào; chỉ có tóm tắt bài báo | §5 |
| S3 | Ghi chú nền cạnh nguyên văn lúc máy rảnh (mục D3b cũ) | +8 điểm với model đọc 9B ở nguồn ngoài; phải có luật nhường GPU | §5 |

## Không làm, và vì sao

Sub-agent, bộ lập kế hoạch chung, tóm tắt ngữ cảnh bằng model, lấy nhiều mẫu rồi bỏ phiếu, định tuyến nhiều agent, LoRA
gọi công cụ bằng dữ liệu công khai, model đệ quy đọc văn bản dài, ép schema cứng lên cả lệnh gọi, để model viết lại trí
nhớ thành "sự kiện". Mỗi thứ có số đo trung tính hoặc âm ở model dưới 10B (KS §2, §3, §5).

## Điểm lệch thấy khi rà code (chưa sửa gì)

| Chỗ | Điều thấy | Mức kiểm |
|---|---|---|
| `backend/app/discord/source_memory.py:117` | Đọc lịch sử Discord bản mới gọi `_dump` với mặc định bỏ cuối danh sách. Khi không có từ khoá, danh sách xếp cũ → mới nên phần bị bỏ là tin mới nhất. Bản cũ dùng `drop="first"` (`agent_tools.py:114`) | Đã đọc code; chưa chạy tái hiện |
| `backend/app/services/agent_service.py:59-69` | Lời dặn nêu `search_history` ở cả lượt web. Câu đã đo là nguyên nhân chính ngày 07/11 vẫn còn | Đã đọc code |
| `backend/app/services/chat_service.py:300` | `prompt_hash` chỉ băm tin đầu, không gồm lời dặn và công cụ, nên không phát hiện được lời dặn đổi | Đã đọc code |
| `data/evaluation/results/kept/agent-eval-scorecard-history.jsonl` | 51 dòng, dòng cuối 01/11, toàn 9B | Đã đọc tệp |
| `.scratch/future-plan/issues/42..49`, `README.en.md:116` | Ticket còn ghi "mở" dù code 43–48 đã gộp; README tiếng Anh còn ghi `qwen3.5:9b` | Ticket và README đã đọc; "đã gộp" là theo trợ lý rà code |
| `backend/app/services/model_router.py:87-93` | Vòng agent không đặt seed (chỉ đặt khi cấu hình có), và không đặt `num_predict` | Seed: đã đọc code. `num_predict`: theo trợ lý rà code |

## Việc chủ dự án cần quyết

1. Đích: 2B ngang 9B (đề xuất), hay tối ưu cho 9B, hay giữ hai hồ sơ.
2. Hướng và thứ tự trong năm hướng A–E.
3. Tập xác nhận khoá lấy từ đâu, ai viết bài tiếng Việt mới, ai được đọc trace của nó.
4. Cơ chế 2c có được thêm một lượt gọi ngắn không (ngoại lệ luật 5), hay chỉ cho 2a và 2b.
5. Hạn mức token cho người đề xuất tự động ở Đợt 4.
6. Card 4 GB có là máy đích phải đo không, khi kế hoạch chính thức đang ghi một môi trường vận hành duy nhất.

## Giới hạn của plan này

- Chưa đo gì. Mọi mục ở Đợt 1–4 là giả thuyết.
- Số ngoài phần lớn là tự báo, trên bài code và tệp tiếng Anh nhiều bước; chưa ai đo trên hỏi đáp tài liệu tiếng Việt có
  trích nguồn trong 3 vòng.
- Đích "2B ngang 9B" có thể không đạt được chỉ bằng harness: ở nguồn ngoài, bài cần suy luận gần như không nhúc nhích cho
  tới khi chỉnh model (KS §4, WHALE), và 2B từng chọn sai dữ kiện khi đọc dài (doc-57, 08/11).
- Khi đã chốt hướng mới tách ticket theo `docs/agents/issue-tracker.md`.
