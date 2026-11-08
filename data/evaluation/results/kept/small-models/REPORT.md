# Model nhỏ, chạy trần và trong harness: kết quả 08/11/2026

Đăng ký trước: `PREREGISTRATION.md`, gồm hai phần bổ sung. Mục sổ đo: `docs/SO_DO.md`, ngày 08/11. Số liệu: `analysis.json`, tạo bằng `analyze.py`. Fable đã kiểm và tính lại toàn bộ số; các chỗ sửa sau khi kiểm có ghi ở cuối tệp.

## Bản chất

Đêm qua đã thử hai model nhỏ. Mỗi model chạy theo hai cách: tự làm một mình, và làm trong khung của Ún (harness). Câu hỏi là có model nào đủ tốt để thử ở một vai trò của Ún không.

**Chưa có model nào đủ tốt.** Ở việc đơn giản nhất, tức gọi đúng một công cụ khi được nhờ, cả hai model nhỏ làm gần bằng model lớn. Nhưng chúng yếu ở hai chỗ quan trọng với Ún: nhận ra lúc *không* nên gọi công cụ, và làm bài tiếng Việt của dự án.

Phát hiện lớn nhất nằm ở harness, không nằm ở model. Với việc phải làm nhiều bước qua nhiều lượt hỏi, model nhỏ mạnh hơn tự làm một mình đạt khoảng một nửa số bài. Đặt vào harness, nó còn chưa tới một phần năm. Dấu hiệu nổi nhất: những bài cần nhiều bước trong một lượt gần như mất hết, vì harness dừng mỗi lượt sớm. Đây mới là phép đếm, chưa phải phép thử chứng minh nguyên nhân.

## Kết quả

Bảng ghi số bài đạt. Điều kiện chung: nhiệt độ 0, seed 42, Ollama 0.40.13, chạy ngày 08/11 từ 01:26 đến 07:32.

| | 9B trần | 9B harness | LFM3 trần | LFM3 harness | 2B trần | 2B harness |
|---|---:|---:|---:|---:|---:|---:|
| simple_python /400 | 367 ¹ | 352 ¹ | 359 | 363 | 287 | 341 ³ |
| irrelevance /240 | 197 | 201 | 135 | 166 | 179 | 82 |
| multi_turn_base /200 | không chạy ² | 31/159 ² | 103 | 38 | 43 | 29 ³ |
| Agent Eval /66 | — | 57 | — | 33 | — | 47 |

¹ Số ngày 07/11. Đêm nay chạy lại 81 bài ở mỗi nhánh, kết quả giống hệt cả 81/81.

² Chủ dự án bỏ các job 9B nhiều lượt lúc 05:21. Số 31/159 lấy từ 159 bài chạy ngày 07/11, chưa chạy lại để kiểm.

³ Có 3 bài lỗi "Cannot connect to Ollama", nên chưa thật sự được đo. Theo đăng ký trước, cả 3 tính là trượt. Cả 3 đều là bài mà 2B chạy trần làm đạt. Luật "đáng thử tiếp" không đổi vì lỗi này, nhưng cặp 2B nhiều lượt thì đổi (xem chú thích ⁴).

### Luật "đáng thử tiếp" (đặt trước, nhánh harness)

| Điều kiện | LFM3 | 2B |
|---|---|---|
| simple_python ≥ 9B − 5 điểm (≥ 83,0) | 90,75 ✓ | 85,25 ✓ |
| irrelevance ≥ 9B − 5 điểm (≥ 78,75) | 69,17 ✗ | 34,17 ✗ |
| Agent Eval ≥ 9B − 6 bài (≥ 51) | 33 ✗ | 47 ✗ |
| Không bài no_tool nào gọi công cụ | ✓ | ✗ (nt-01 gọi `current_time`, nt-02 gọi `search_documents`) |
| **Đạt luật** | **không** | **không** |

### So từng bài (McNemar chính xác)

| Cặp so | Bài | Chỉ A đạt | Chỉ B đạt | p |
|---|---|---:|---:|---:|
| LFM3 harness / LFM3 trần | multi_turn_base | 5 | 70 | <0,001 |
| LFM3 harness / LFM3 trần | irrelevance | 63 | 32 | 0,002 |
| LFM3 harness / LFM3 trần | simple_python | 13 | 9 | 0,52 |
| 2B harness / 2B trần | simple_python | 66 | 12 | <0,001 |
| 2B harness / 2B trần | irrelevance | 8 | 105 | <0,001 |
| 2B harness / 2B trần | multi_turn_base | 15 | 29 | 0,049 ⁴ |
| 9B harness / 9B trần | simple_python | 13 | 28 | 0,03 |
| 9B harness / 9B trần | irrelevance | 14 | 10 | 0,54 |
| LFM3 harness / 9B harness | simple_python | 33 | 22 | 0,18 |
| LFM3 harness / 9B harness | irrelevance | 15 | 50 | <0,001 |
| LFM3 harness / 9B harness | multi_turn_base (159 bài chung) | 18 | 18 | 1,0 |
| 2B harness / 9B harness | simple_python | 26 | 37 | 0,21 |
| 2B harness / 9B harness | irrelevance | 4 | 123 | <0,001 |
| 2B harness / 9B harness | multi_turn_base (159 bài chung) | 16 | 21 | 0,51 |
| LFM3 / 9B | Agent Eval | 2 | 26 | <0,001 |
| 2B / 9B | Agent Eval | 5 | 15 | 0,04 |
| LFM3 / 2B | Agent Eval | 8 | 22 | 0,016 |

⁴ Nếu bỏ hai bài chưa đo ra khỏi phép so, kết quả thành 15 / 28, p 0,07. Nếu tính hai bài đó là đạt, kết quả thành 16 / 28, p 0,10. Vậy cặp này không đứng vững.

Các cặp còn lại mà đăng ký trước yêu cầu (model nhỏ chạy trần so với 9B chạy trần, và LFM3 so với 2B trên BFCL) nằm trong `analysis.json`, khoá `pairs`. Danh sách từng bài Agent Eval khác 9B nằm ở khoá `agent_eval.<model>.only_this` và `only_9b`.

Agent Eval theo nhóm bài:

| Nhóm | 9B | LFM3 | 2B |
|---|---:|---:|---:|
| documents /45 | 39 | 22 | 36 |
| history /11 | 8 | 3 | 4 |
| no_tool /5 | 5 | 5 | 3 |
| status /5 | 5 | 3 | 4 |

### Thời gian, giây mỗi bài

Mỗi bài đều phải nạp lại model, nên các số này không phải tốc độ khi Ún chạy thật. Chúng chỉ dùng để so các model với nhau.

| | 9B | LFM3 | 2B |
|---|---:|---:|---:|
| harness, simple_python | 7,6 ⁵ | 3,1 | 6,2 |
| harness, irrelevance | 8,0 | 3,5 | 5,2 |
| harness, Agent Eval | 8,0 | 4,1 | 5,5 |
| trần, simple_python | 4,0 ⁵ | 0,4 | 3,4 |
| trần, irrelevance | 5,3 | 2,2 | 4,4 |
| trần, multi_turn_base | — | 7,8 | 9,7 |
| harness, multi_turn_base | — | 8,4 | 11,6 |

⁵ Đo ngày 07/11. Lần kiểm 81 bài đêm nay chỉ kiểm điểm, không kiểm thời gian.

## Dự đoán đúng hay sai

Có 7 trên 15 khoảng dự đoán đúng.

| | Dự đoán | Đo được | |
|---|---|---|---|
| LFM3 trần, multi_turn_base | 15–35 % | 51,5 % | sai, cao hơn nhiều |
| 2B trần, multi_turn_base | 3–15 % | 21,5 % | sai, cao hơn |
| 2B harness, irrelevance | 40–70 % | 34,2 % | sai, thấp hơn |
| LFM3 trần, irrelevance | 60–85 % | 56,3 % | sai, thấp hơn |
| LFM3, Agent Eval | 35–50 | 33 | sai, thấp hơn |
| 2B, Agent Eval | 25–45 | 47 | sai, cao hơn |
| 2B trần, simple_python | 40–70 % | 71,8 % | sai, sát mép trên |
| 2B trần, irrelevance | 75–95 % | 74,6 % | sai, sát mép dưới |
| 7 khoảng còn lại | | | đúng |

Hai dự đoán về hướng đều đúng: harness kéo 2B sang gọi công cụ, nhờ vậy simple_python lên mà irrelevance xuống.

## Phép thử tìm nguyên nhân: harness làm mất bài nhiều lượt

Phần này không có trong đăng ký trước, và được đếm sau khi đã thấy số. Ở đây "bài nhiều bước" là bài mà khi chạy trần, model cần hơn 3 vòng gọi công cụ trong ít nhất một lượt. Harness dừng mỗi lượt sau 3 vòng.

| Trong số bài chạy trần đạt | LFM3 | 2B |
|---|---:|---:|
| Bài nhiều bước: harness làm mất | 40/44 (91 %) | 12/12 |
| Bài còn lại: harness làm mất | 30/59 (51 %) | 17/31 |
| Bài bị mất mà harness chưa lần nào chạm trần 3 vòng | 24/70 | 10/29 |
| … trong đó có cả một lượt không gọi công cụ nào (lỗi "empty turn" của BFCL) | 13 | 5 |

Tỉ lệ trượt ở nhánh harness, tách theo việc bài có chạm trần 3 vòng hay không:

| | Có chạm trần | Không chạm trần |
|---|---:|---:|
| 9B (159 bài, 07/11) | 67/76 (88 %) | 61/83 (73 %) |
| LFM3 | 119/127 (94 %) | 43/73 (59 %) |
| 2B | 121/134 (90 %) | 50/66 (76 %) |

Cách đọc hai bảng:

- Trần 3 vòng đi kèm phần lớn số bài bị mất ở LFM3. Ở 9B, dấu hiệu này yếu hơn nhiều.
- Có khoảng một phần ba số bài bị mất không dính tới trần, nên trần không phải lời giải thích duy nhất.
- Có ba nguyên nhân khả dĩ chưa được tách riêng:
  - trần 3 vòng;
  - harness chỉ mang chữ sang lượt sau, không mang lệnh gọi và kết quả công cụ;
  - lượt bỏ trống, tức model trả lời bằng chữ mà không gọi gì. Lượt bỏ trống có thể sinh ra từ việc chỉ mang chữ sang lượt sau, cũng có thể từ câu trong lời dặn mà đăng ký trước đã nêu là làm 9B tụt điểm.
- Runner đã có sẵn hai công tắc `--max-steps` và `--carry-tool-traffic`. Đêm nay cả hai đều để mặc định: 3 vòng, và chỉ mang chữ. Vì vậy tách được nguyên nhân chỉ bằng hai lần chạy lại, không cần sửa code.

## Giới hạn

- Không có 9B chạy trần trên multi_turn_base, nên không biết harness làm 9B mất bao nhiêu bài nhiều lượt.
- Ở bài nhiều lượt, 9B và model nhỏ chỉ so được trên 159 bài chung, và 159 bài này chưa được kiểm lại.
- Lời dặn của harness được viết cho 9B. Với model nhỏ, điểm có thể thấp vì lời dặn chứ không vì model.
- Ún ship ở nhiệt độ 0,4, còn lần đo này dùng nhiệt độ 0.
- BFCL là bài tiếng Anh. Phần tiếng Việt chỉ có Agent Eval, bộ bài dự án tự viết.

## Các hướng tiếp

| Hướng | Ưu | Nhược | Chi phí |
|---|---|---|---|
| A. Giữ 9B, dừng hướng model nhỏ | Không tốn gì; số liệu cho thấy chưa model nhỏ nào đạt luật | Bỏ qua tốc độ: LFM3 nhanh hơn 9B khoảng 2–2,5 lần; câu hỏi về harness vẫn treo | 0 |
| B. Tìm nguyên nhân harness mất bài nhiều lượt: chạy lại multi_turn_base bằng hai công tắc có sẵn (nới trần vòng; mang cả lệnh gọi và kết quả công cụ sang lượt sau), kèm 9B chạy trần làm mốc | Đánh vào phát hiện lớn nhất; không cần sửa code để đo; kết quả có thể giúp mọi model, kể cả 9B (chưa đo); đúng trọng tâm "harness là mũi nhọn" | Cần đăng ký trước và đối chứng cùng ngày; muốn ship thì sau đó vẫn phải sửa vòng lặp agent | Mỗi lần chạy 200 bài, gồm mốc chạy trần, đối chứng mặc định và hai công tắc. Với 9B khoảng 4–5 giờ, với LFM3 khoảng 2 giờ. Ước từ tỉ lệ thời gian đêm nay, chưa đo |
| C. Viết lời dặn riêng cho model nhỏ, rồi đo lại irrelevance và Agent Eval | Kiểm được giới hạn "lời dặn viết cho 9B" | LFM3 thua 9B tới 24 bài Agent Eval, quá xa để lời dặn bù hết; dễ thành dò tham số trên chính tập test | 1–2 giờ đo mỗi lần thử |
| D. Dùng LFM3 ở một vai trò hẹp, không cần tiếng Việt và không phải tự quyết có gọi công cụ hay không | Nhanh; simple_python ngang 9B | Đi ngược luật đặt trước; Ún chưa có vai trò cụ thể nào như vậy | Chưa ước tính được |

Ý kiến của người viết: nghiêng về B. Đây là chỗ harness đang mất điểm nhiều nhất, việc đo không cần sửa code, và kết quả không phụ thuộc chọn model nào. B cũng chạm tới kế hoạch sửa lời dặn BFCL đang chờ (`.scratch/bfcl-guide-fix/PLAN.md`), nên cần xếp thứ tự giữa hai việc.

## Sửa sau khi Fable kiểm (08/11)

Fable tính lại mọi số và mọi cặp so. Các số khớp, không có số nào sai. Những chỗ đã sửa:

- Chú thích ³ và ⁴ trước đây không nói rằng cặp 2B nhiều lượt mất ý nghĩa khi tính lại hai bài chưa đo.
- Trước đây báo cáo gọi trần 3 vòng là "lý do chính". Giờ đổi thành "dấu hiệu nổi nhất", thêm bảng tỉ lệ nền, và thêm loại lỗi "lượt bỏ trống".
- Thời gian của 9B ở simple_python được đánh dấu là đo ngày 07/11, và thêm các dòng thời gian của irrelevance và của nhánh trần.
- Thêm hai cặp so 2B/9B ở bài nhiều lượt, cùng chỗ tra các cặp còn lại trong `analysis.json`.
- Phát hiện hai công tắc có sẵn, nên hướng B rẻ hơn ước tính cũ.
- Đoạn bản chất được viết lại: không còn tên model và con số, và câu hỏi được nêu đúng như đăng ký trước.
