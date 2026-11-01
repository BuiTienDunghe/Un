# Khảo sát giọng nói — nghe tin thoại tiếng Việt trên máy (ticket 49)

Tra ngày 02/11/2026, chỉ từ trang chính thức của model (Hugging Face, GitHub, bài báo). Chưa tải gì, chưa chạy gì, không dùng GPU.

## Bản chất

Một tin nhắn thoại trên Discord là một tệp ghi âm ngắn. Muốn Ún trả lời nó, phải có một "người nghe" chép tệp đó thành chữ, rồi chữ đó đi vào Ún như thể bạn gõ. Người nghe là một model riêng, nằm trên card đồ hoạ chung với model trả lời. Nó chỉ cần có mặt lúc đang nghe: nghe xong một lúc thì thoát khỏi card, như model phân loại trí nhớ (decided) đang làm. Việc cần chọn là người nghe nào: nghe tiếng Việt đủ tốt, vừa chỗ còn dư trên card, và giấy phép cho dùng.

## Chỗ trống trên card

| Mục | Số | Ghi chú |
|---|---|---|
| Card | 16 GB | |
| Qwen 9B đang dùng | ~6,6 GB | số chủ dự án đưa |
| Dư danh nghĩa | ~9,4 GB | **chưa đo** những thứ khác đang ở trên card (màn hình Windows, game, decided khi đang chạy) |

## Các lựa chọn nghe được tiếng Việt, chạy trên máy

Cách đọc bảng. "Tải" là dung lượng tệp trên trang chính thức, kèm độ chính xác số. "VRAM" chỉ ghi khi nguồn chính thức nêu; số **suy ra** nói rõ. "Điểm" là WER (tỷ lệ chữ sai, thấp là tốt). **Điểm của các dòng khác nhau không so với nhau được**: bộ thử khác (Common Voice bản 9/14/16.1/17, FLEURS, VIVOS, VLSP) và cách chuẩn hoá chữ khác.

| # | Model | Tham số | Tải | VRAM | Điểm tiếng Việt công bố | Giấy phép |
|---|---|---|---|---|---|---|
| 1 | Whisper large-v3 ([openai](https://huggingface.co/openai/whisper-large-v3); bản [faster-whisper](https://huggingface.co/Systran/faster-whisper-large-v3/tree/main)) | 1,55 B | bản faster-whisper 3,09 GB (fp16) | README Whisper ghi "~10 GB" cho cỡ large; faster-whisper đo large-**v2** trên RTX 3070 Ti: 4,5 GB fp16, 2,9 GB int8. Cho v3 là suy ra | Chính thức: **chưa đọc được** (README chỉ có biểu đồ ảnh). Bài báo Whisper cho large-**v2**: FLEURS 10,3; Common Voice 9 18,2. Bên thứ ba: Common Voice 17 14,8 và FLEURS 8,9 ([Dolphin](https://arxiv.org/html/2503.20212)); Common Voice 16.1 16,2, FLEURS 8,3, VIVOS 12,3 (tự báo, `verified: false`, [thẻ doof-ferb](https://huggingface.co/doof-ferb/whisper-large-peft-lora-vi/blob/main/README.md)) | MIT (GitHub), Apache-2.0 (thẻ HF) |
| 2 | Whisper large-v3-turbo ([openai](https://huggingface.co/openai/whisper-large-v3-turbo)) | 809 M (decoder 4 lớp thay vì 32) | 1,62 GB (fp16); whisper.cpp: 1,62 GB, q8_0 874 MB, q5_0 574 MB | README Whisper: "~6 GB" (PyTorch) | **Không có số tiếng Việt chính thức nào.** Thẻ nói chỉ giảm chất lượng "nhẹ" so với large-v3, không nêu số | MIT |
| 3 | Whisper medium / small ([whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp/tree/main)) | 769 M / 244 M | medium 1,53 GB (q5_0 539 MB); small 488 MB (q5_1 190 MB) | RAM theo whisper.cpp: medium ~2,1 GB, small ~852 MB | Bài báo Whisper, FLEURS: medium 12,7; small 21,2. Common Voice 9: 24,4; 33,3 | MIT |
| 4 | PhoWhisper tiny/base/small/medium/large ([VinAI](https://github.com/VinAIResearch/PhoWhisper)) — Whisper tinh chỉnh trên 844 giờ tiếng Việt (large dựa trên large-v2) | 39 M / 74 M / 244 M / 769 M / 1,55 B | small 967 MB, medium 3,06 GB, large 6,17 GB (đều fp32, `pytorch_model.bin`). Chưa có bản CTranslate2 chính thức; có bản cộng đồng ([qbsmlabs](https://huggingface.co/qbsmlabs/PhoWhisper-large), [nunu-willump](https://huggingface.co/nunu-willump/PhoWhisper-medium-ct2)) **chưa kiểm** | **Không công bố.** Suy từ cỡ Whisper tương ứng, chưa đo | BSD-3-Clause |
| 5 | EraX-WoW-Turbo-V1.1 ([bản CT2](https://huggingface.co/erax-ai/EraX-WoW-Turbo-V1.1-CT2/blob/main/README.md)) — turbo tinh chỉnh ~1000 giờ | cỡ turbo | thẻ không nêu | không nêu | **Chưa có bảng.** Thẻ ghi "khoảng 12%" sơ bộ, không nói bộ nào, cách đo nào | MIT |
| 6 | Qwen3-ASR [1,7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) / [0,6B](https://huggingface.co/Qwen/Qwen3-ASR-0.6B) — có tiếng Việt trong danh sách ngôn ngữ | ~2 B / ~0,9 B | 4,7 GB / 1,88 GB (bf16) | không nêu (chỉ nói FlashAttention 2 giảm bộ nhớ) | **Chỉ có điểm gộp nhiều ngôn ngữ, không tách tiếng Việt.** Bộ có tiếng Việt là "Fleurs†" (8 ngôn ngữ thêm vào 12 ngôn ngữ lõi, trong đó có Vietnamese): **1,7B 6,62; 0,6B 10,37**. Các số 7,57 (0,6B) và 4,90 (1,7B) là bộ 12 ngôn ngữ lõi, **không** có tiếng Việt, đừng so với dòng trên | Apache-2.0 |
| 7 | wav2vec2-large-vi-vlsp2020 ([nguyenvulebinh](https://huggingface.co/nguyenvulebinh/wav2vec2-large-vi-vlsp2020)) | 317 M (số từ bài báo PhoWhisper) | thẻ không nêu | thẻ không nêu | VLSP T1: 6,90 (5,32 khi thêm mô hình ngôn ngữ 5-gram). Bài báo PhoWhisper đo cùng họ model trên Common Voice: trên 100% (đầu ra không dấu câu, không viết hoa), VIVOS 8,61 | **CC BY-NC 4.0** (cấm thương mại) |
| 8 | Zipformer-30M-RNNT-6000h ([hynt](https://huggingface.co/hynt/Zipformer-30M-RNNT-6000h)) | 30 M | thẻ không nêu | chạy tốt trên CPU: 0,3 s cho clip 12 s | VLSP2020-T1 12,29; VLSP2023 10,40/11,10; VLSP2025 7,97/8,10; GigaSpeech2 7,56 (dòng này thẻ chỉ có 4 giá trị, tôi giả định giá trị đầu) | **CC BY-NC-ND 4.0** |
| 9 | SeamlessM4T v2 large ([Meta](https://huggingface.co/facebook/seamless-m4t-v2-large)) — nghe được tiếng Việt | 2,3 B | thẻ không nêu | không nêu | thẻ không có số tiếng Việt | **CC BY-NC 4.0** |
| 10 | Dolphin ([bài báo](https://arxiv.org/html/2503.20212)) — có tiếng Việt | base 140 M, small 372 M (chỉ hai cỡ này được phát hành; số tiếng Việt trong bài là của cỡ **large**, không phát hành) | chưa tra | chưa tra | không có số cho cỡ phát hành | bài báo không nêu; chưa tra repo |

Không dùng được, ghi để khỏi tra lại: [Parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) (25 ngôn ngữ châu Âu, không có tiếng Việt), [Voxtral Mini 3B](https://huggingface.co/mistralai/Voxtral-Mini-3B-2507) (8 ngôn ngữ, không có tiếng Việt; ~9,5 GB VRAM).

**Chưa tra**: Meta MMS, NVIDIA Canary, Gemma 3n (nghe âm thanh), SenseVoice, Granite Speech. Danh sách này không đầy đủ.

## Phần chạy model (chọn riêng với model)

| Cách chạy | Giấy phép | Điều đã kiểm | Điều chưa kiểm |
|---|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | Đọc thẳng tệp ogg/opus (PyAV mang sẵn FFmpeg, không cần cài ffmpeg riêng). GPU cần cuBLAS và cuDNN 9 cho CUDA 12; trên Windows phải lấy thư viện từ kho Purfview hoặc chạy trong Linux/WSL | Chạy được trên máy này không; dung lượng cuDNN phải tải |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | MIT | Có CPU, Vulkan, CUDA trên Windows; `whisper-cli` chỉ nhận WAV 16 bit, tức phải có ffmpeg đổi ogg sang wav | Có ffmpeg trên máy không; bản dựng sẵn cho Windows |
| transformers (cho PhoWhisper, Qwen3-ASR) | Apache-2.0 | Môi trường `Fine-tune` (chạy decided) đã có torch 2.11+cu128 và transformers 5.19. **Không thấy** `av`, `soundfile`, `librosa` trong đó, nên đọc ogg/opus cần ffmpeg hoặc cài thêm một gói nhỏ | Qwen3-ASR có chạy bằng transformers thường hay cần gói riêng của Qwen: **chưa kiểm** |

Lưu ý về môi trường `Fine-tune`: đó là venv Linux (`python3.12`), decided chỉ vào được qua `run-decided.bat` và WSL. Chọn B hoặc C dựa vào nó nghĩa là hoặc chạy cả cửa `voice_server.py` trong WSL như decided (khi đó đường tệp tạm phải đổi bằng `wslpath` trước khi model con mở được; chưa làm), hoặc dựng venv Windows mới có torch (hàng GB). Dòng `voice` trong `tools/supervisor.py` hiện chạy bằng Python của dự án trên Windows, và `VOICE_MODEL_PYTHON` chỉ đổi được trình thông dịch của model con; chưa đủ cho trường hợp WSL.

Rủi ro chung của họ Whisper: khi im lặng hoặc nhiễu, nó có thể "bịa" ra câu không ai nói, và dễ lặp ([thẻ large-v3](https://huggingface.co/openai/whisper-large-v3) tự nhận, nặng hơn với ngôn ngữ ít dữ liệu). Cần bộ lọc im lặng ở phía model và kiểm đầu ra rỗng; phần code đã có đường cho "không nghe ra lời nào".

## Các cách đi

Điều kiện chung: mọi cách đều phải tải model quá 200 MB (nhỏ nhất ở bảng trên là 190 MB, nhưng chất lượng tiếng Việt của cỡ đó kém), nên bước tải cần chủ dự án duyệt riêng.

| Cách | Ưu | Nhược | Chi phí / rủi ro |
|---|---|---|---|
| **A. Whisper large-v3-turbo qua faster-whisper** | Một model đa ngữ, MIT, runtime phổ biến, nhẹ hơn large-v3 | **Không có điểm tiếng Việt công bố**; GPU trên Windows cần thư viện CUDA phụ | ~1,6 GB tải + cuDNN; hỏi: rơi chất lượng bao nhiêu so với large-v3 |
| **B. PhoWhisper medium (hoặc small) qua transformers** | Cách duy nhất có bảng điểm tiếng Việt do chính tác giả công bố; BSD; môi trường `Fine-tune` đã có torch/transformers | Tải 3,06 GB (medium, fp32) hoặc 967 MB (small); điểm công bố đo trên bộ đọc/ghi âm sạch (VIVOS, Common Voice), không phải giọng Discord; phải thêm bộ giải mã ogg | Chạy qua transformers chậm hơn CT2; bản CT2 cộng đồng chưa kiểm |
| **C. Qwen3-ASR 0,6B** | Apache, 1,88 GB, mới, có tiếng Việt | Chỉ có điểm gộp (Fleurs† có tiếng Việt: 0,6B 10,37, kém hẳn 1,7B 6,62, cỡ 1,7B nặng 4,7 GB); chưa biết runtime; thẻ không nêu VRAM | Chưa kiểm cách chạy |
| **D. whisper.cpp, medium hoặc turbo lượng tử q5_0 (539–574 MB)** | Nhỏ nhất đáng dùng; chạy được cả CPU nên có thể không đụng card | Cần ffmpeg để đổi ogg; lượng tử làm điểm tụt, chưa có số | Phải dựng hoặc tải bản whisper.cpp |
| **E. Không tải, đo trước** | Không có điểm nào ở trên đo trên giọng Discord thật; 20–30 clip chủ dự án tự ghi, đo A, B, C bằng cùng một cách chuẩn hoá, trả lời được câu "cái nào nghe đúng hơn" | Tốn một buổi và vẫn phải tải ba model | Đây là bước đo trước khi chọn, không loại trừ A–D |
| Loại: wav2vec2-vlsp2020, Zipformer-30M, SeamlessM4T | Nhỏ hoặc nhanh | Giấy phép cấm thương mại (và Zipformer cấm cả sửa) | |

Ý kiến của tôi, không phải kết luận: nghiêng về **E rồi B-medium hoặc A**, vì các số công bố không so với nhau được và không số nào đo trên giọng của bạn. Nếu phải chọn khi chưa đo, B-small là bước rẻ nhất có điểm tiếng Việt đi kèm; A đơn giản hơn để chạy nhưng thiếu số.

## Cách Ún dùng (đã code ở nhánh `wip/49-voice`, tắt mặc định)

| Câu hỏi | Trả lời |
|---|---|
| Tin thoại nào được nghe | Chỉ tin thoại **trả lời một tin của Ún** (Discord không cho tin thoại có chữ, nên không thể gắn @Ún trong đó; trả lời tin của Ún là đường duy nhất qua cổng "được gắn tên" hiện có), trong server nằm trong danh sách cho phép |
| Ghi âm có được lưu không | Không. Nằm trong bộ nhớ ở bot và backend; ở cửa model chép tạm vào một tệp tạm và xoá ngay sau khi nghe, kể cả khi lỗi |
| Chữ nghe được | Vào lượt như tin gõ thường; không ghi vào sổ lịch sử vì tin thoại không có chữ gốc |
| Lỗi, quá dài, quá lớn, chưa bật | Ún trả lời một câu lịch sự, không tạo lượt, không văng lỗi |

**Chưa kiểm**: Discord có cho gửi tin thoại như một lời *trả lời* hay không (tôi không tìm thấy tài liệu nói rõ; cần thử một lần trên Discord thật, và bật "@ON" khi trả lời). Nếu không cho, hoặc khi chủ dự án thấy bất tiện, có hai cách khác:

| Cách kích hoạt | Ưu | Nhược |
|---|---|---|
| Trả lời tin của Ún (đã làm) | Chỉ nghe khi người ta chủ ý nói với Ún; không nghe lén cuộc trò chuyện | Phải bấm trả lời và giữ "@ON"; chưa kiểm trên Discord thật |
| Mọi tin thoại trong server được phép | Tự nhiên nhất | Chép giọng của mọi người không ai hỏi ý, chiếm card theo lưu lượng của server; chưa làm |
| Tin nhắn riêng (DM) | Không lo người khác | Cổng danh sách server hiện từ chối DM; phải thêm danh sách người dùng; chưa làm |
