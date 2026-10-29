# Harness tìm hộ đoạn dán: mục lục và tìm theo từ khoá, không dùng model (29/10/2026)

Người viết: nghiên cứu độc lập (opus 5.5). Không gọi model nào, không sửa repo. Mọi con số dưới đây chạy bằng code trên 15
bài đoạn dán của `agent_eval/v0/tasks.jsonl` (worktree `coord-main`, `ca099fa`), trừ những chỗ ghi "ước" hoặc "lập luận".
Script và kết quả thô: `C:\Users\dungbt06\AppData\Local\Temp\claude\C--Users-dungbt06-local-ai-core\5e9b23d6-dd28-46a2-b314-bd7791bd6b8f\scratchpad\research\outline\`
(`analyze.py`, `qrobust.py`; số cuối cùng ở `result2.json` / `run2.txt`. `result.json` là lần chạy trước khi thêm lệnh
loại dòng đánh số; số BM25 hai lần như nhau).

## Bản chất

Hiện nay trợ lý nhận một văn bản dài giống như một tập hồ sơ dày mà nó chỉ nhìn thấy trang đầu và trang cuối. Muốn xem
phần giữa, nó phải tự quyết định lật, mỗi lần vài trang, và chỉ được lật vài lần. Thường nó lật từ đầu, nên hết lượt
trước khi tới chỗ cần. Hướng này để người đưa hồ sơ làm hai việc trước, không cần tới trí tuệ nhân tạo. Việc thứ nhất là
chép các tiêu đề mục ra thành một mục lục. Việc thứ hai là lấy câu hỏi của người dùng, dò xem trang nào có nhiều chữ trùng
với câu hỏi nhất, rồi kẹp sẵn mấy trang đó ngay cạnh câu hỏi. Cách dò chữ trùng chạy được khi người hỏi dùng đúng chữ của
văn bản. Nó hỏng khi người hỏi nói khác chữ ("máy bay trễ" so với "phương tiện khởi hành muộn"), khi câu hỏi lẫn lời
nhờ việc ("soạn tin nhắn gửi bố mẹ"), hoặc khi người hỏi nhớ sai và chính chữ nhớ sai kéo trang sai lên đầu. Mục lục bù
được phần lớn những chỗ hỏng đó, nhưng dùng mục lục thì trợ lý vẫn phải tự quyết định mở mục nào. Đó đúng là kiểu quyết
định mà trước giờ nó làm kém.

## Số đo (15 bài, chạy bằng code; 12 bài cần phần giữa, 3 bài mép 42/45/52)

**Điều kiện chung.** Đoạn lấy đúng từ `pastes._chunks` (480/80 token). Tôi đã kiểm vị trí đáp án bằng regex `must_mention`
trên từng đoạn, và cả 15 bài khớp danh sách được giao. Từ khoá là token của `tokenize_vietnamese` (pyvi, cùng bộ tách
BM25 production đang dùng), đã bỏ hư từ. Khi chấm, tôi gỡ các dòng câu hỏi khỏi đoạn chứa chúng, để đoạn đó không tự
khớp với chính câu hỏi. **Đây là số trong mẫu.** Tôi viết quy tắc và danh sách hư từ sau khi đã đọc 15 câu hỏi, nên số
thật trên bài mới sẽ thấp hơn.

### Tách câu hỏi

Quy tắc: lấy đoạn văn đầu hoặc cuối tin (tách theo dòng trống), dài tối đa 600 ký tự, không có dòng viết hoa toàn bộ,
và có "?" hoặc một từ hỏi (ai, nào, đâu, bao nhiêu, bao lâu, mấy, gì, khi nào, thế nào, có … không). R2 thêm một bước:
nếu đoạn văn quá dài thì xét riêng dòng đầu và dòng cuối.

| Biến thể (sinh từ 15 bài) | Quy tắc gốc | R2 |
|---|---|---|
| Nguyên bản | 15/15 đúng phía (8 cuối, 7 đầu) | 15/15 |
| Gỡ câu hỏi đi (văn bản không có câu hỏi) | 15/15 không bắt nhầm | 15/15 |
| Câu hỏi dính liền văn bản, không có dòng trống | **4/15** | 15/15 |
| Câu hỏi viết dạng lệnh, không "?" và không từ hỏi | chưa thử bằng biến thể; trường hợp này rơi về dòng "truy vấn = hai mép" ở bảng sau | |

### Tìm theo từ khoá (BM25, không model): đoạn đáp án có nằm trong top-k không (bài hai mảnh thì phải đủ cả hai)

| Cách | top-3 / 12 bài giữa | top-5 / 12 | Bài trượt top-3 (hạng) | Ký tự 3 đoạn đưa vào phiếu, tb / max |
|---|---|---|---|---|
| B1: token pyvi (như production) | **8** | 8 | 44 (7), 46 (7), 47 (3 và 8), 53 (9) | 4 712 / 5 331 |
| B2: âm tiết + cặp âm tiết | **9** | 9 | 44 (8), 46 (10), 53 (9) | 4 696 / 5 322 |
| B3: tách câu hỏi hỏng, lấy hai mép làm truy vấn | 4 | 7 | 8 bài | 4 927 / 5 505 |
| Chỉ đưa cửa sổ 400 ký tự quanh chỗ trùng nhiều nhất thay vì cả đoạn (B1) | đáp án nằm trong cửa sổ: 4/12 | | | 1 200 |

Ở các bài trượt, tăng từ top-3 lên top-5 không cứu được bài nào: đoạn đáp án đứng hạng 7–10. Ba nguyên nhân đọc được từ
dữ liệu:

- doc-53 nói khác chữ văn bản.
- doc-44 có câu hỏi lẫn lời nhờ việc.
- doc-46 là câu kể hoàn cảnh, trong khi chữ "học bổng" có ở mọi đoạn.

Đưa cửa sổ ngắn thay cho cả đoạn thì hỏng: chỉ 4/12 bài có đáp án lọt vào cửa sổ. Muốn dùng kết quả tìm thì phải đưa cả
đoạn.

Ba bài mép đều có đoạn mép trong top-3. Riêng **doc-45**: đoạn đứng hạng 1 là đoạn 9, chứa "nhà văn hóa" 2 lần và
"thứ Sáu" 3 lần, đúng những chữ người hỏi nhớ sai; đáp án ở đoạn 0, hạng 2.

### Mục lục tự động

Cách chấm máy: xếp các dòng mục lục theo số từ khoá câu hỏi mà mỗi dòng chứa, rồi xem đoạn đáp án có nằm trong 3 dòng đầu
không. Chấm tay: tôi đóng vai người đọc chỉ thấy câu hỏi và mục lục, chọn tối đa 2 dòng, mỗi dòng đọc 3 đoạn kể từ đó.
Bài trúng nếu các lần đọc phủ đủ đáp án. Chấm tay có thiên lệch vì tôi biết đáp án nằm đâu.

Cột "≥1 từ câu hỏi" và "lộ đáp án" là tiêu chí được giao: dòng của đoạn đáp án chứa ít nhất một từ khoá câu hỏi, hoặc
khớp regex đáp án. Tiêu chí "≥1 từ" quá dễ đạt (A2c đạt 11/12 mà vẫn xếp sai thứ tự), nên tôi dựa vào cột top-3.

| Cách | ≥1 từ câu hỏi / 12 | Lộ đáp án / 12 | Trúng top-3 (máy) / 12 | Chấm tay / 12 | Ký tự mục lục tb / max | Ký tự / đoạn | Dòng rỗng |
|---|---|---|---|---|---|---|---|
| A1: `heading_path` sẵn có của bộ chia đoạn | 0 | 0 | 1 | — | 47 / 115 | 4 | **99%** |
| A2b: câu đầu, sau phần chồng lấn | 5 | 1 | 5 | — | 406 / 996 | 40 | 0 |
| A2c: khối đầu sau phần chồng lấn, 90 ký tự | 11 | 1 | 7 | — | 1 014 / 2 365 | 92 | 0 |
| A3: 5 từ nổi bật (tf-idf trong đoạn dán) | 6 | 0 | 4 | — | 423 / 1 031 | 38 | 0 |
| **A6: dòng tiêu đề trong đoạn, rỗng thì lấy A2c** | 9 | 1 (doc-44) | 6 | **11** (doc-43 chỉ ra một mảnh) | 715 / 1 861 | 66 | 0 |
| B1 ∪ A6 (máy) | | | 8 | | | | |

Nhận dòng tiêu đề, A6 dùng tiền tố Điều/PHẦN/MỤC/Chương/Ngày/Đêm/Email, số La Mã, dòng viết hoa toàn bộ, và dòng bắt đầu
bằng số. Dòng bắt đầu bằng số mà kết thúc bằng dấu câu thì bị loại, đúng như `_heading_match` của bộ chia đoạn. Không có
lệnh loại này, các dòng giờ giấc ("07 giờ 00: …") và các khoản đánh số ("3. Việc tạm ngừng…") lọt vào mục lục: mục lục
doc-49 phình lên 2 070 ký tự, và dòng đoạn 4 của doc-44 thành vô dụng.

A1 gần như rỗng: `_make_chunk` chỉ gán `heading_path` khi cả đoạn nằm trọn dưới một tiêu đề, và đoạn nào cũng vắt qua
nhiều mục. Mặt khác, bộ chia đoạn **bỏ dòng tiêu đề khỏi nội dung đoạn** (`_blocks_from_pages` gặp dòng tiêu đề thì
`continue`). A6 vì thế phải đọc lại văn bản gốc để lấy tiêu đề. Đây cũng là lý do BM25 phải chấm trên `heading_path +
content`.

Văn bản không có tiêu đề rõ:

- doc-44 (lịch tour): A6 có "NGÀY 3 — thứ Hai 14/12" ở đoạn 2. Dòng của đoạn 4 rơi về câu đầu "Đêm 3 nghỉ tại homestay
  Đá Vàng…", tức lộ luôn một nửa đáp án. Đoạn 3 thì chỉ còn "07 giờ 00: ăn sáng, trả phòng…", vô dụng.
- doc-48 (sách hướng dẫn) thật ra có tiêu đề "MỤC 8. MÃ LỖI VÀ CÁCH XỬ LÝ", nên trúng.
- Văn bản trơn hoàn toàn thì A6 rơi về câu đầu của khối (A2c). Ví dụ doc-53 có "Khi Phương tiện vận tải công cộng… khởi
  hành muộn": người đọc hiểu được đó là chỗ cần mở, còn dò chữ thì xếp nó hạng 5.

Lý do chấm tay cao hơn chấm máy: người đọc hiểu "Điều 9. Hạng và mức học bổng" hay "PHẦN 14. NGHỈ PHÉP" là đúng mục cần
mở, trong khi dò chữ thì không. Model 9B đọc được như người đến đâu thì chưa đo.

## Chi phí token của phiếu mới

Cách ước:

- 2,9 ký tự/token (`ticket20-design-1.md`, đã đo).
- Mỗi đoạn ứng với khoảng 1 294 ký tự văn bản (đo trên 15 bài, đã tính phần chồng lấn).
- Mục lục A6 tốn 66 ký tự/đoạn; nếu cắt mỗi dòng ở 80 ký tự và cả mục lục ở 2 400 ký tự thì 100k bị cắt bớt.
- 3 đoạn tìm được tốn khoảng 4 700 ký tự, không phụ thuộc độ dài văn bản.
- Độ trễ: hồi quy trên 121 lượt chạy của các lần chạy cô lập ở `kept/agent-eval-v0.7-paste-nudge-search` cho 0,29 ms mỗi
  token vào (cộng qua các vòng) và 14,5 ms mỗi token ra (R² 0,998, số trong mẫu).

| Văn bản | Số đoạn | Mục lục (ký tự → token) | + 3 đoạn tìm được | Phiếu tăng thêm | Vòng 1 (hôm nay ~1 840 token) | Thêm độ trễ mỗi vòng |
|---|---|---|---|---|---|---|
| 10k | ~8 | 530 → ~180 | ~1 620 | ~1,9k token | ~3,7k | ~0,55 s |
| 30k | ~23 | 1 520 → ~520 | ~1 620 | ~2,2k | ~4,1k | ~0,65 s |
| 100k | ~77 | 5 080 → ~1 750 (có trần: 2 400 → ~830) | ~1 620 | ~3,5k (có trần: ~2,6k) | ~5,3k (~4,4k) | ~1,0 s (~0,75 s) |

Phần mở rộng thêm khoảng 1,6k token, ngang một lần `read_document` (đọc 3 đoạn, trần 6 000 ký tự). Khi tìm trúng, nó thay
được một vòng gọi công cụ. Ở doc-39, vòng đó tốn khoảng 4,2 s và khoảng 3,5k token vào. Khi tìm trượt, hay ở bài mép,
mỗi vòng mất thêm khoảng 0,5–1 s. Dù vậy cửa sổ vẫn còn rộng: vòng 1 ≤ 5,4k trên 16 384.

Nhúng (C), ước từ tài liệu dự án, **không chạy**:

- `qwen3-embedding:0.6b` cần 2 870 MiB và nằm chung bộ nhớ với model chính, trong trần `budget.vram_mib`.
- Lần nhúng lại 3 896 đoạn hết 17 phút 41 giây (`09-model-experiment-run.md`), tức khoảng 0,27 s/đoạn. Con số này gồm cả
  ghi Qdrant và DB, nên là trần trên.
- Theo đó, mỗi đoạn dán tốn khoảng 2 s ở 10k, khoảng 6 s ở 30k và khoảng 21 s ở 100k. Có thể cache theo `paste_id` để chỉ
  nhúng một lần cho mỗi đoạn dán.
- Ollama phục vụ từng yêu cầu một, nên thời gian nhúng ăn thẳng vào ngân sách 90 s của lượt. Ở 100k là khoảng 23% ngân
  sách.
- Số chunk/s thuần của GPU chưa có trong dự án.

## Rủi ro (lập luận, trừ chỗ ghi đã đo)

1. **Bài "đã thấy đủ" (42, 45, 52).** Mỗi bài dài thêm khoảng 1,9k token. Lập luận: đoạn chèn vào là chữ có sẵn trong
   phiếu, không phải lệnh gọi công cụ, nên khó làm model đọc thêm. Nếu có đổi, khả năng cao là model đọc ít đi, vì đáp
   án hiện ra hai lần. Rủi ro thật nằm ở chỗ khác: chữ nhiễu được chèn sát câu hỏi. Đã đo trên doc-45: đoạn hạng 1 khớp
   đúng điều người hỏi nhớ sai. Ở doc-42, đoạn 4 trong top-3 có "tổng duyệt" và "dẫn chương trình" của một email cũ.
2. **Tách câu hỏi sai.**
   - Không tìm thấy câu hỏi: đã đo bằng truy vấn hai mép, chỉ 4/12 vào top-3, mà vẫn tốn khoảng 1,6k token chữ nhiễu.
     Vì vậy thiết kế dưới đây **không chèn đoạn nào khi không tách được câu hỏi**, chỉ đưa mục lục.
   - Bắt nhầm một dòng không phải câu hỏi: 0/15 trên biến thể đã gỡ câu hỏi, nhưng biến thể đó vẫn là văn bản của bộ bài
     này.
   - Câu hỏi nằm ở tin sau, khi người dùng dán trước rồi mới hỏi: quy tắc không thấy. Lúc đó có thể lấy tin mới nhất làm
     truy vấn. Cái giá là phiếu đổi theo từng lượt.
3. **Văn bản không tiêu đề.** Mục lục rơi về câu đầu của khối sau phần chồng lấn. Cách này có ích khi câu đầu nói chủ đề,
   như doc-53, và vô dụng khi câu đầu là chi tiết lặt vặt, như đoạn 4 của doc-44 ("07 giờ 00: ăn sáng…").
4. **Hai mảnh.** BM25 tìm đủ cả hai mảnh ở doc-43 và doc-51; B1 sót doc-47 còn B2 thì đủ. Lần đo #3-D ghi lại đúng kiểu
   hỏng này: tìm ra một mảnh rồi dừng (doc-43 ở +1+3').
5. **Thứ tự đặt trong phiếu.** Với bài có câu hỏi ở đầu (7/15), đặt các đoạn tìm được sau phần mép cuối nghĩa là để xa
   câu hỏi. Cách sửa rẻ là lặp lại câu hỏi đã tách ngay sau các đoạn, tốn khoảng 200 ký tự. Cách này theo "Lost in the
   Middle" và hướng dẫn long-context của Anthropic đã dẫn trong `paste-directions`, chưa đo trên Qwen.

## Các phương án (chủ dự án chọn)

| # | Phương án | Ưu | Nhược | Token thêm (10k / 100k) |
|---|---|---|---|---|
| P1 | Chỉ mục lục A6 | rẻ; bài mép gần như không đổi; không cần tách câu hỏi | model vẫn phải tự chọn mở, đúng kiểu quyết định đã hỏng ở #3-B/C/D | ~0,2k / ~0,8k (có trần) |
| P2 | Chỉ chèn 3 đoạn BM25 | không cần model quyết định; 8–9/12 trong mẫu | trượt khi khác chữ hoặc câu hỏi có tiền đề sai; bài mép dài thêm | ~1,7k / ~1,7k |
| P3 | Mục lục + 3 đoạn (+ lặp câu hỏi) | mục lục đỡ các bài P2 trượt (44, 46, 47, 53 đều có dòng mục lục chỉ đúng chỗ, chấm tay) | dài nhất; hai cơ chế cùng lúc nên khó quy công cho từng cái | ~1,9k / ~2,6k |
| P4 | Chỉ con trỏ: "đoạn hợp nhất: 6, 4, 0" + dòng mục lục của chúng | khoảng 150 ký tự; khớp với 3' | model vẫn phải gọi đọc; ở #3-D model gọi tìm có 3/12 lần | ~0,05k |
| P5 | P3 nhưng tìm bằng nhúng lai (BM25 + nhúng, như đường RAG) | có thể cứu bài khác chữ (doc-53) | GPU 2–21 s mỗi lần dán (trần trên); code bất đồng bộ + cache; tranh GPU; chưa có số | như P3 |

Ý kiến của tôi, không phải quyết định: nghiêng P3 không nhúng. Lý do:

- Đây là phương án duy nhất trong bảng không đặt cược vào việc model tự quyết đọc.
- Phần tìm đo được hoàn toàn không cần GPU.
- P5 chỉ đáng làm khi bài mới cho thấy kiểu trượt vì khác chữ chiếm phần lớn.

Nếu ưu tiên phiếu ngắn và ít rủi ro chữ nhiễu ở bài mép, P1 + P4 là lựa chọn công bằng; đổi lại là quay về phụ thuộc
model.

## Đề xuất thiết kế cụ thể (P3)

Thiết kế này mở rộng phiếu #3-C (`int/20-3c`, `ed210e4`; #3-D đo nó ở `94e321f`), đúng nền chủ dự án đã chọn. Nhánh
"nền" của lần đo dưới đây là commit đó. Chữ ký `slip(text)` giữ nguyên, vì truy vấn lấy từ chính đoạn dán. Nhờ vậy
`agent_service` không phải đổi gì.

`pastes.py`:

- Thêm `_question(text)`: quy tắc R2, khoảng 15 dòng.
- Thêm `_outline(text)`: dòng tiêu đề lấy từ văn bản gốc (luật nhận dòng như A6, kể cả lệnh loại dòng đánh số kết thúc
  bằng dấu câu), gán cho đoạn đầu tiên có vị trí cuối ≥ vị trí dòng. Đoạn nào không có thì lấy khối đầu sau phần chồng
  lấn. Bỏ dòng câu hỏi: đoạn 10 của doc-53 đang hiện chính câu hỏi trong mục lục. Mỗi dòng cắt 80 ký tự, cả mục lục cắt
  2 400 ký tự. Khoảng 25 dòng.
- Thêm `_top_chunks(text, query, k=3)`: `BM25Okapi` + `tokenize_vietnamese` trên `heading_path + content`, đã gỡ dòng câu
  hỏi. Không có câu hỏi thì trả rỗng. Khoảng 15 dòng.
- `slip()` thêm ba khối sau phần mép cuối:
  1. "MỤC LỤC (tự tạo, đoạn i: tiêu đề)".
  2. "CÁC ĐOẠN CÓ NHIỀU CHỮ TRÙNG CÂU HỎI NHẤT (chọn tự động theo chữ, có thể sai): đoạn i: …". Phần đoạn 0 hoặc đoạn cuối
     đã nằm trong mép thì bỏ.
  3. "Câu hỏi: …" (lặp lại).

  Lời dặn chỉ cần một câu: "Nếu các đoạn trên chưa đủ, đọc đoạn theo mục lục bằng read_document(from_chunk=i)".

Ước khối lượng: khoảng 70 dòng code và khoảng 100 dòng test. Không đổi `tools_sha256`, system prompt hay agent guide. Chỉ
bài có đoạn dán bị ảnh hưởng. Hàm thuần, cache theo `paste_id` như `_chunks`, nên phiếu giữ nguyên giữa các lượt.

Đo cô lập (theo giao thức #3-D):

1. **Cửa offline, không GPU, chạy trước.** NV3 viết mù khoảng 10 bài đoạn dán mới:
   - ≥ 3 bài có đáp án sau đoạn 8;
   - ≥ 2 bài khác chữ hoàn toàn với văn bản;
   - ≥ 2 bài có câu hỏi dạng lệnh, không "?";
   - ≥ 1 bài câu hỏi dính liền văn bản;
   - ≥ 2 bài văn bản không tiêu đề;
   - ≥ 2 bài mép có tiền đề sai.

   Chạy `_top_chunks` và `_question` lên các bài này, ghi tỉ lệ top-3 trước khi chạy model. Luật đăng ký trước, ví dụ: tách
   đúng ≥ 80% và top-3 ≥ 60% bài giữa; trượt thì dừng, không tốn GPU. Bước này tách độ đúng của harness khỏi hành vi của
   model.
2. **Chạy model.** Ba nhánh: nền / P1 / P3, trên 25 bài (15 cũ + 10 mới), mỗi nhánh r1 và r2, gỡ model trước mỗi bài.
   Thêm một lần đủ bộ (62 + 10) cho nhánh thắng để chứng minh 47 bài không dán trùng từng chữ. Theo dõi riêng: bài mép
   đổi điểm, `tokens_in` của vòng 1, số lần đọc thêm sau khi đoạn đáp án đã được chèn.
3. **GPU, ước từ đồng hồ các lần chạy đã có** (15 bài khoảng 3,5 phút, 62 bài 9,6 phút):
   - 25 bài khoảng 6 phút × 3 nhánh × 2 lần, khoảng 36 phút;
   - lần đủ 72 bài khoảng 11 phút;
   - **tổng khoảng 47 phút**. Bỏ nhánh P1 thì khoảng 35 phút. Thêm P5 thì cộng khoảng 12 phút, cùng thời gian nhúng.

## Điều tôi chưa kiểm

- Mọi tỉ lệ ở trên đều trong mẫu: quy tắc và danh sách hư từ viết sau khi đọc 15 câu hỏi. Chưa có bài mới nào.
- Chưa chạy model: model 9B có dùng mục lục, có trả lời từ đoạn được chèn hay vẫn gọi đọc, có bị đoạn nhiễu (doc-45)
  kéo lệch hay không, đều chưa biết.
- Chấm tay mục lục (11/12) là của một người biết trước đáp án.
- Luật nhận dòng tiêu đề của A6 do tôi viết trên chính 15 bài. Số ký tự mục lục có thể lệch ở văn bản có kiểu đánh mục
  khác, như "a)", "Khoản", hay gạch đầu dòng.
- Biến thể "câu hỏi dạng lệnh" chưa sinh ra để thử, chỉ có số của truy vấn hai mép làm cận dưới.
- Tốc độ nhúng thuần trên GPU chưa đo; 0,27 s/đoạn là của cả đường nhúng lại.
- Hồi quy độ trễ là số trong mẫu của một máy và một bản Ollama; chưa tách phần cache tiền tố prompt.
- Chưa đọc code `agent_service` ở chỗ gọi `take_pastes`, nên chưa xác nhận tin mới nhất có sẵn ở đó để làm truy vấn.


## Vòng 2 (sau khi đọc c-noi-tran-doc, tim-trong-doan-dan, phan-bien)

**Bản chất.** Nạp nguyên văn bản (N1) là đặt cả tập hồ sơ lên bàn; tìm hộ (P3) là chỉ đặt mục lục và ba trang có vẻ
đúng nhất. Khi hồ sơ vừa bàn, chưa có bằng chứng nào cho thấy chọn trang hơn đặt cả tập: lựa chọn có thể sai, cả tập thì
không sót gì. Tìm hộ chỉ thật sự cần khi hồ sơ không vừa bàn, và ở cỡ đó bộ bài hiện chưa có bài nào.

**1. P3 thắng N1 ở đâu.**
- **Chắc chắn: văn bản vượt cửa sổ.** Chỗ cho văn bản là 16 384 − 1 842 (vòng đầu, đo) − ~1 000 (câu trả lời dài nhất
  1 003 token, đo) − lịch sử, tức ≤ ~12k token hay 35–42k ký tự. `PASTE_MAX` 100k vượt xa con số này.
- **Có thể, nhưng chưa có số: chất lượng 9B khi ngữ cảnh dài.** Tôi quét 3 681 vòng model trong `kept/`. Prompt lớn nhất
  một vòng là 6 483 token (doc-49, trượt vì hết lượt), không có vòng nào ≥ 8k. Tỉ lệ đạt theo cỡ vòng (≥ 6k: 9/19; 4–6k:
  129/192) bị nhiễu, vì chỉ bài khó mới có vòng lớn. "Lost in the middle" bất lợi cho N1, nhưng P3 cũng trượt 3–4/12.
  Vậy lợi thế của P3 chỉ có thật nếu 9B giảm chất lượng nhiều ở khoảng 10k token.
- **Token:** P3 thêm ~1,9k, N1 thêm 3,5–11k, tức chênh 0,3–2 s mỗi lượt theo hồi quy. Không đủ để quyết định.

**2. Kết hợp: N1 khi vừa, P3 khi không vừa.**
- Ngưỡng là **ngân sách token tính lúc chạy**: nạp nguyên nếu `len/2,9` ≤ 16 384 − prompt hiện tại − 1 024 − 10%.
  Hội thoại một tin cho ra khoảng 35k ký tự, phủ cả 15 bài.
- Không dùng hằng số ký tự vì lịch sử dài thì chỗ trống co lại, mà khi tràn Ollama cắt đầu prompt, đúng chỗ đặt câu hỏi
  kèm văn bản dán.
- Chỉ nạp nguyên tin dán mới nhất; các lượt sau quay về phiếu.
- Code: N1 ~20 dòng (`take_pastes` cần biết prompt hiện tại), P3 ~70 dòng, test ~130 dòng; không đổi `tools_sha256`.
- Hệ quả: trên bộ hiện tại, P3 không chạy ở bài nào. Muốn đo P3 phải có tầng > 35k ký tự.

**3. Rủi ro của P3 với doc-45 và doc-53.**
- **doc-45 (đoạn nhiễu khớp điều người hỏi nhớ sai):** xếp 3 đoạn theo thứ tự trong văn bản thay vì theo điểm, và dán
  nhãn "chọn theo chữ trùng, có thể trái câu hỏi". Cả hai chưa đo. Trong bản kết hợp, doc-45 (10,6k ký tự) đi đường N1.
- **doc-53 (đoạn mồi):** không chặn được bằng đếm chữ. Top-3 của B1 là 8, 9, 1, đúng phần ví dụ mồi; đáp án đứng hạng 9.
  Báo cáo tìm-trong-đoạn-dán cũng thấy đoạn mồi đứng hạng 1 ở mọi truy vấn. Chỉ còn dòng mục lục (lại cần model tự chọn)
  hoặc nhúng (chưa đo). Tôi không có cách chặn đã kiểm.

**4. Trả lời câu hỏi của phản biện.**
- **Câu 7 (tách câu hỏi sai):** sai 0/15. Khi câu hỏi dính liền văn bản: quy tắc gốc sai 11/15, R2 sai 0/15. Câu hỏi nằm
  giữa văn bản thì không thấy, nên chỉ đưa mục lục; chưa có bài thử.
- **Câu 8 (hai mảnh, phiếu dài thêm):** ở k = 3, B1 lấy đủ doc-43 và doc-51, còn doc-47 cần k = 8. B2 lấy đủ cả ba ở
  k = 3. Ở bài mép, phiếu dài thêm khoảng 4,2–5,2k ký tự (≈ 1,5–1,8k token).
- **Câu 9 (dưới 30k, tìm hộ có hơn không):** không có số. Lợi thế đo được duy nhất là ít token, mà token không quyết
  định. Tôi rút P3 khỏi dải này.
- **Câu 10 (bài > 35k):** không có. Trên bộ hiện tại, hướng của tôi không đo được gì mà N1 không phủ.
- **Câu 11 (dự đoán cổng):** đoán **trượt** cổng "thắng − thua ≥ 3" nếu chạy P3 thay N1 trên 15 bài cũ: ước +2, chỉ
  doc-49 và doc-50. Vì vậy không chạy.

**Xếp hạng lại** (ý kiến; làm sau bước đếm nhu cầu của phản biện):
1. **Kết hợp N1 + P3:** phủ tới `PASTE_MAX`, không cần model quyết đọc. Phần P3 chỉ đáng code khi có văn bản thật > 35k.
2. **N1 một mình:** phủ trọn bộ hiện tại với ~20 dòng; rủi ro duy nhất là chất lượng 9B ở 8–12k token, và đo được.
3. **P3 một mình:** chỉ còn lý do ở văn bản không vừa cửa sổ; dưới mức đó thua N1 về độ đầy đủ.
4. **C:** tới đoạn 14; tốn token hơn N1 ở mọi độ dài N1 phủ; vẫn cần model tự giở.
5. **Tìm-sửa:** chỗ hỏng là model không gọi tìm (9/12), sửa công cụ tìm không chạm tới chỗ đó.

**Thí nghiệm có model phân xử N1 và P3 (khoảng 10 phút GPU): độn độ dài.**
- **Bài:** 12 bài giữa, mỗi bài thêm một bản độn lên khoảng 30k ký tự (≈ 10k token). Thân văn bản kẹp giữa hai khối lấy từ
  bài dán khác chủ đề; câu hỏi giữ ở mép cũ, nên đáp án rơi vào giữa.
- **Ba nhánh, chạy cô lập, mỗi nhánh một lần** (t = 0 cho r1 = r2): N1-gốc (15 bài, ~3,5 phút), N1-độn (12 bài, ~3
  phút), P3-độn (12 bài, ~3,5 phút).
- **Luật đăng ký trước:**
  - N1-độn ≥ N1-gốc − 1 và ≥ P3-độn → N1 tới hết ngân sách, P3 chỉ cho phần vượt.
  - N1-độn thua N1-gốc ≥ 3 mà P3-độn giữ được → hạ ngưỡng N1 xuống khoảng 15k ký tự.
  - Còn lại → chưa phân xử, không gộp.
- **Điều kiện:** N1 và P3 phải viết xong trước. Bản độn không mù với người viết, nên chỉ dùng để chọn ngưỡng, không dùng
  làm cổng gộp.
