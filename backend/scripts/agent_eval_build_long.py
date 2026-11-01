"""Writes the v0-long dataset of Agent Eval (tickets 44 and 45): `data/benchmarks/agent_eval/v0-long/`.

    python -m scripts.agent_eval_build_long            # from backend/; rewrites the five files
    python -m scripts.agent_eval_build_long --check    # exit 1 when the files on disk differ

Two kinds of task, 14 in all, none of them in the 66 of v0 (which this does not touch):

- end-01..07 (ticket 45): a paste of 40 000-95 000 characters, past what N1 reads whole
  (~36 400), with the answer in its last 15 %, beyond the 600 characters of the slip's tail.
- ctx-01..07 (ticket 44): a turn whose tool results do not fit the window with the history,
  so a context budget has something to clear. ctx-01..04: a long chat history, and one
  document whose three facts are three or more chunks apart (three reads). ctx-05..07: three
  suppliers' quotes, a price in one chunk and a delivery time in another, two reads each.

The answers are written by hand below; every other sentence is generated from the pools in
GENRES with a seeded random, so the files are the same on every run. Everything is made up:
people, companies, amounts, dates. The numbers the filler may use (DAYS, MONEY, HOURS,
PERCENT) leave out every figure an answer needs, and the tests check that each answer's
pattern matches once in the whole text.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "data" / "benchmarks" / "agent_eval" / "v0-long"
VERSION = "agent-eval-v0-long.1"

DAYS = (2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 15, 20, 21, 25)
MONEY = ("20.000", "50.000", "80.000", "100.000", "120.000", "150.000", "200.000", "250.000", "300.000", "500.000")
HOURS = ("7 giờ", "8 giờ", "9 giờ", "10 giờ", "14 giờ", "15 giờ", "17 giờ")
PERCENT = (5, 10, 15, 25, 40, 50)

# subjects / rules / tails per genre. A rule is a clause that follows a subject; {d} {m} {h} {p} are
# filled from the sets above. Tails are optional.
GENRES: dict[str, dict[str, list[str]]] = {
    "chung_cu": {
        "titles": ["QUY ĐỊNH CHUNG", "GỬI XE", "RÁC THẢI", "THANG MÁY", "KHÁCH THĂM", "SỬA CHỮA CĂN HỘ", "TIẾNG ỒN", "PHÒNG CHÁY", "SẢNH VÀ HÀNH LANG", "NUÔI THÚ CƯNG", "PHÍ DỊCH VỤ", "KHIẾU NẠI"],
        "subjects": ["Cư dân", "Ban quản lý", "Đơn vị vận hành", "Bảo vệ tòa nhà", "Chủ căn hộ", "Người thuê nhà"],
        "rules": [
            "phải thông báo cho quầy lễ tân trước {d} ngày khi cần sửa chữa trong căn hộ",
            "không để rác ngoài hành lang ngoài khung giờ {h} đến {h}",
            "được đón tối đa hai khách qua đêm mà không cần đăng ký thêm",
            "nộp phí dịch vụ theo từng quý, chậm quá {d} ngày thì chịu phụ phí {p}% số tiền chưa nộp",
            "không dùng thang chở hàng để chuyển đồ vào các giờ cao điểm",
            "đăng ký thẻ ra vào mới tại văn phòng với lệ phí {m} đồng một thẻ",
            "giữ yên lặng trong căn hộ từ 22 giờ đến 6 giờ sáng hôm sau",
            "không lắp thêm thiết bị ngoài mặt dựng của tòa nhà",
            "báo ngay cho bảo vệ khi thấy người lạ ở khu vực cầu thang bộ",
            "được mượn xe đẩy hàng ở sảnh, trả lại trong ngày và tự chịu trách nhiệm nếu làm hỏng",
        ],
        "tails": ["theo quy chế quản lý và sử dụng nhà chung cư", "trừ trường hợp có thỏa thuận khác bằng văn bản", "để bảo đảm an toàn cho các hộ liền kề", "như đã nêu ở phụ lục của hợp đồng"],
    },
    "thue_kho": {
        "titles": ["ĐỐI TƯỢNG HỢP ĐỒNG", "GIÁ THUÊ", "THANH TOÁN", "BÀN GIAO", "BẢO TRÌ", "BẢO HIỂM", "NHẬP XUẤT HÀNG", "AN NINH", "VI PHẠM", "CHẤM DỨT", "BẤT KHẢ KHÁNG", "GIẢI QUYẾT TRANH CHẤP"],
        "subjects": ["Bên thuê", "Bên cho thuê", "Hai bên", "Quản lý kho", "Đại diện bên thuê", "Đại diện bên cho thuê"],
        "rules": [
            "thanh toán tiền thuê mỗi tháng một lần, chậm nhất ngày {d} của tháng đó",
            "thông báo bằng văn bản trước {d} ngày khi muốn đổi người phụ trách giao nhận",
            "chịu chi phí điện nước phát sinh theo đồng hồ riêng của từng khu",
            "không lưu trữ hàng hóa dễ cháy nổ nếu chưa được bên kia đồng ý bằng văn bản",
            "được vào kiểm tra kho trong giờ làm việc, báo trước {d} ngày",
            "chịu phạt {p}% giá trị tháng thuê nếu vi phạm điều khoản về an ninh",
            "bảo đảm lối thoát hiểm luôn thông thoáng và không chất hàng cao quá ba mét",
            "mua bảo hiểm cháy nổ cho hàng hóa của mình với mức tối thiểu theo phụ lục",
            "lập biên bản ghi nhận tình trạng mặt bằng mỗi lần bàn giao hoặc nhận lại",
            "chịu phí vệ sinh khu bốc xếp {m} đồng một lần nếu để lại rác sau khi nhập hàng",
        ],
        "tails": ["theo điều khoản của hợp đồng này", "và được ghi vào biên bản có chữ ký hai bên", "trừ khi luật có quy định khác", "mà không phải bồi thường thêm khoản nào"],
    },
    "thi": {
        "titles": ["ĐĂNG KÝ HỌC PHẦN", "LỊCH THI", "COI THI", "CHẤM THI", "PHÚC KHẢO", "XÉT HỌC BỔNG", "NGHỈ HỌC TẠM THỜI", "KỶ LUẬT", "ĐIỂM RÈN LUYỆN", "TỐT NGHIỆP", "CHUYỂN NGÀNH", "HỖ TRỢ SINH VIÊN"],
        "subjects": ["Sinh viên", "Phòng Đào tạo", "Giảng viên phụ trách", "Cố vấn học tập", "Hội đồng thi", "Khoa chuyên môn"],
        "rules": [
            "đăng ký học phần chậm nhất {d} ngày trước khi học kỳ bắt đầu",
            "mang theo thẻ sinh viên và giấy tờ tùy thân khi vào phòng thi",
            "không được rời phòng thi trong {d} phút đầu tiên",
            "nộp đơn phúc khảo tại phòng Đào tạo, lệ phí {m} đồng cho mỗi môn",
            "được công bố điểm trên cổng thông tin sau khi giảng viên nộp bảng điểm",
            "xin nghỉ học tạm thời với lý do chính đáng và có xác nhận của cố vấn học tập",
            "bị lập biên bản nếu mang tài liệu không được phép vào phòng thi",
            "được xét học bổng khi điểm trung bình học kỳ không thấp hơn mức quy định của khoa",
            "đăng ký chuyển ngành vào đầu năm học, mỗi sinh viên chỉ chuyển một lần",
            "phải hoàn thành học phí trước khi nhận giấy báo dự thi",
        ],
        "tails": ["theo quy chế đào tạo hiện hành", "và chịu trách nhiệm về thông tin đã khai", "trừ sinh viên thuộc diện được miễn theo quy định", "để việc xếp lịch thi được thuận lợi"],
    },
    "bao_hanh": {
        "titles": ["PHẠM VI BẢO HÀNH", "THỜI HẠN", "ĐIỀU KIỆN", "TRƯỜNG HỢP TỪ CHỐI", "QUY TRÌNH GỬI MÁY", "LINH KIỆN", "BẢO HÀNH TẠI NHÀ", "ĐỔI MỚI", "GIA HẠN", "TRUNG TÂM ỦY QUYỀN", "VẬN CHUYỂN", "KHIẾU NẠI"],
        "subjects": ["Khách hàng", "Trung tâm bảo hành", "Kỹ thuật viên", "Nhà phân phối", "Bộ phận tiếp nhận", "Người mua"],
        "rules": [
            "xuất trình phiếu bảo hành và chứng từ mua hàng khi gửi máy",
            "được sửa chữa miễn phí các lỗi do nhà sản xuất trong thời hạn bảo hành",
            "chịu chi phí vận chuyển hai chiều nếu ở ngoài khu vực hỗ trợ tận nơi",
            "chờ tối đa {d} ngày làm việc để nhận lại máy sau khi tiếp nhận",
            "không được tự ý tháo niêm phong, nếu không thiết bị mất quyền bảo hành",
            "được đổi mới trong {d} ngày đầu nếu máy lỗi ngay từ lần sử dụng đầu tiên",
            "đóng phí kiểm tra {m} đồng khi thiết bị không thuộc diện bảo hành",
            "được gia hạn thêm bảo hành với mức phí bằng {p}% giá bán lẻ",
            "báo cho trung tâm nếu thay đổi địa chỉ nhận máy sau khi đã đăng ký",
            "nhận thông báo kết quả sửa chữa qua tin nhắn đến số điện thoại đã đăng ký",
        ],
        "tails": ["theo chính sách bảo hành đã công bố", "và thông tin được lưu trong hệ thống của hãng", "trừ các phụ kiện tiêu hao", "kể từ ngày ghi trên chứng từ mua hàng"],
    },
    "cau_lac_bo": {
        "titles": ["TÔN CHỈ", "HỘI VIÊN", "HỘI PHÍ", "BAN CHẤP HÀNH", "ĐẠI HỘI", "SINH HOẠT ĐỊNH KỲ", "GIẢI ĐẤU", "TÀI SẢN", "KHEN THƯỞNG", "KỶ LUẬT", "SỬA ĐỔI ĐIỀU LỆ", "GIẢI THỂ"],
        "subjects": ["Hội viên", "Ban chấp hành", "Thủ quỹ", "Chủ nhiệm câu lạc bộ", "Ban kiểm tra", "Thư ký"],
        "rules": [
            "đóng hội phí đúng hạn, chậm quá {d} ngày thì bị nhắc nhở bằng văn bản",
            "tham gia ít nhất một nửa số buổi sinh hoạt định kỳ trong năm",
            "được bỏ phiếu trong đại hội khi đã đóng đủ hội phí của năm trước",
            "giữ gìn dụng cụ của câu lạc bộ và bồi thường nếu làm mất hoặc hư hỏng",
            "báo cáo thu chi cho hội viên mỗi quý một lần",
            "đề cử người vào ban chấp hành bằng văn bản có chữ ký của {d} hội viên",
            "tổ chức giải nội bộ vào cuối năm với lệ phí tham dự {m} đồng một người",
            "được tặng giấy khen khi có thành tích trong các giải do câu lạc bộ cử đi",
            "bị mời ra khỏi buổi sinh hoạt nếu có hành vi làm mất trật tự",
            "lập biên bản mỗi cuộc họp và gửi cho hội viên trong vòng {d} ngày",
        ],
        "tails": ["theo điều lệ này", "và được ghi nhận trong sổ theo dõi", "nếu không có lý do chính đáng", "trừ hội viên danh dự"],
    },
    "an_toan": {
        "titles": ["TRANG BỊ BẢO HỘ", "VẬN HÀNH MÁY", "KHU VỰC NGUY HIỂM", "HÓA CHẤT", "PHÒNG CHÁY CHỮA CHÁY", "CẤP CỨU", "BÁO CÁO SỰ CỐ", "ĐÀO TẠO", "LÀM VIỆC TRÊN CAO", "KHÁM SỨC KHỎE", "NGƯNG VIỆC KHẨN CẤP", "KIỂM TRA ĐỊNH KỲ"],
        "subjects": ["Công nhân", "Tổ trưởng", "Cán bộ an toàn", "Quản đốc phân xưởng", "Người vận hành máy", "Nhân viên bảo trì"],
        "rules": [
            "đội mũ bảo hộ và đeo kính khi vào khu vực gia công",
            "kiểm tra thiết bị an toàn của máy trước mỗi ca làm việc",
            "không đứng trong vùng quay của trục khi máy chưa ngắt điện",
            "ghi sổ giao ca sau mỗi lần dừng máy dài hơn {d} phút",
            "được cấp găng tay mới sau mỗi {d} tuần sử dụng hoặc khi bị rách",
            "tham dự buổi huấn luyện an toàn định kỳ, vắng mặt phải học bù trong {d} ngày",
            "dán nhãn rõ ràng lên mọi bình chứa hóa chất, kể cả khi chỉ dùng trong ngày",
            "ngưng việc ngay khi phát hiện rò rỉ khí hoặc mùi lạ trong xưởng",
            "không làm việc trên giàn giáo cao quá hai mét nếu chưa đeo dây an toàn",
            "nộp giấy khám sức khỏe định kỳ cho phòng nhân sự, chi phí {m} đồng được công ty hoàn lại",
        ],
        "tails": ["theo quy trình an toàn của nhà máy", "và có xác nhận của tổ trưởng", "không có ngoại lệ", "trừ khi cán bộ an toàn cho phép khác"],
    },
    "du_lich": {
        "titles": ["ĐẶT TOUR", "GIÁ VÀ PHỤ THU", "THANH TOÁN", "HỦY VÀ ĐỔI TOUR", "HÀNH LÝ", "KHÁCH SẠN", "XE VẬN CHUYỂN", "BẢO HIỂM DU LỊCH", "TRẺ EM", "TRƯỞNG ĐOÀN", "BẤT KHẢ KHÁNG", "KHIẾU NẠI"],
        "subjects": ["Khách hàng", "Công ty lữ hành", "Hướng dẫn viên", "Trưởng đoàn", "Phòng Điều hành", "Đơn vị vận chuyển"],
        "rules": [
            "đặt cọc để giữ chỗ và hoàn tất thanh toán chậm nhất {d} ngày trước khi khởi hành",
            "mang theo giấy tờ tùy thân còn hiệu lực trong suốt chuyến đi",
            "được mang một hành lý ký gửi và một hành lý xách tay theo quy định của hãng vận chuyển",
            "chịu phụ thu phòng đơn {m} đồng cho mỗi đêm nếu đi một mình",
            "thông báo cho hướng dẫn viên nếu có yêu cầu về chế độ ăn từ khi đặt tour",
            "được giảm {p}% giá tour đối với trẻ em dưới mười hai tuổi ngủ chung giường với người lớn",
            "tập trung đúng giờ tại điểm hẹn, xe không chờ quá {d} phút",
            "chịu trách nhiệm về tài sản cá nhân trong suốt chuyến đi",
            "được đổi ngày khởi hành một lần nếu báo trước và còn chỗ trống",
            "nhận lịch trình chi tiết qua thư điện tử {d} ngày trước ngày khởi hành",
        ],
        "tails": ["theo chương trình đã công bố", "và được xác nhận bằng văn bản", "trừ các dịp cao điểm", "để đoàn khởi hành đúng kế hoạch"],
    },
    "bao_gia": {
        "titles": ["GIỚI THIỆU", "SẢN PHẨM", "ĐƠN GIÁ", "ĐIỀU KIỆN THANH TOÁN", "GIAO HÀNG", "LẮP ĐẶT", "BẢO HÀNH", "ĐỔI TRẢ", "HỖ TRỢ SAU BÁN", "HIỆU LỰC BÁO GIÁ"],
        "subjects": ["Công ty chúng tôi", "Bên bán", "Bộ phận kinh doanh", "Đội giao hàng", "Bên mua", "Phòng kỹ thuật"],
        "rules": [
            "xuất hóa đơn đỏ cho mọi đơn hàng khi bên mua cung cấp đủ thông tin thuế",
            "hỗ trợ đổi hàng lỗi trong {d} ngày đầu kể từ ngày nhận",
            "giao hàng đến chân công trình, bên mua tự lo bốc xếp lên tầng",
            "tư vấn cách bố trí tại chỗ miễn phí khi bên mua yêu cầu",
            "tính phụ phí {m} đồng cho mỗi lần giao hàng vào ngày nghỉ",
            "giảm {p}% cho các đơn hàng đặt lại trong vòng một năm",
            "thông báo ngày giao dự kiến qua điện thoại trước khi xuất kho",
            "lưu mẫu của lô hàng để đối chiếu khi cần",
            "nhận thanh toán bằng chuyển khoản, không nhận tiền mặt quá hạn mức quy định",
            "giữ nguyên báo giá cho các đơn hàng xác nhận trong thời gian hiệu lực",
        ],
        "tails": ["theo thỏa thuận trong báo giá này", "và được ghi vào hợp đồng nếu hai bên ký kết", "trừ các mặt hàng đặt riêng", "như các khách hàng doanh nghiệp khác"],
    },
}


def _sentence(rng: random.Random, genre: dict[str, list[str]]) -> str:
    rule = rng.choice(genre["rules"]).format(
        d=rng.choice(DAYS), m=rng.choice(MONEY), h=rng.choice(HOURS), p=rng.choice(PERCENT)
    )
    tail = f", {rng.choice(genre['tails'])}" if rng.random() < 0.6 else ""
    return f"{rng.choice(genre['subjects'])} {rule}{tail}."


def _paragraph(rng: random.Random, genre: dict[str, list[str]]) -> str:
    return " ".join(_sentence(rng, genre) for _ in range(rng.randint(3, 5)))


# ── the pastes (ticket 45) ───────────────────────────────────────────────

# Each spec: where the text is from, how long it is, where the question goes, the answer sentences
# (fraction of the length where each is planted), a near-miss or two, and the patterns that an
# answer must match. `must` patterns match once in the whole text and not in the question.
PASTES: list[dict[str, Any]] = [
    {
        "id": "end-01", "genre": "chung_cu", "length": 41_000, "question_at": "end",
        "intro": "Mình vừa nhận nhà ở chung cư Hoa Giấy, ban quản lý gửi bản nội quy rất dài, mình dán nguyên vào đây.",
        "question": "Nhà mình có một chiếc ô tô. Nếu gửi cố định ở hầm B2 thì mỗi tháng mất bao nhiêu, và đăng ký ở đâu?",
        "facts": [(0.91, "ĐIỀU 118. Phí gửi ô tô cố định tại hầm B2 là 1.840.000 đồng một tháng cho mỗi chỗ. Cư dân đăng ký tại quầy lễ tân tòa Ngọc Lan trong giờ hành chính, mang theo cà vẹt xe và hợp đồng mua bán căn hộ.")],
        "near": [(0.35, "ĐIỀU 41. Phí gửi xe máy tại hầm B1 là 135.000 đồng một tháng cho mỗi xe, đăng ký tại quầy lễ tân tòa Cẩm Tú."), (0.62, "ĐIỀU 77. Phí gửi ô tô vãng lai tại sảnh nhà C tính theo giờ, tối đa 90.000 đồng một ngày.")],
        "must": [r"(?<![\d.,])1\.840\.000|(?<![\d.,])1[.,]84\s*triệu", r"Ngọc Lan"],
        "good": "Gửi ô tô cố định ở hầm B2 là 1.840.000 đồng một tháng, đăng ký tại quầy lễ tân tòa Ngọc Lan.",
        "bad": "Gửi ô tô ở hầm B2 khoảng 90.000 đồng một ngày, đăng ký tại quầy lễ tân tòa Cẩm Tú.",
        "note": "Nội quy chung cư: phí gửi ô tô hầm B2 và nơi đăng ký ở điều gần cuối. Gây nhiễu: phí xe máy hầm B1 và phí ô tô vãng lai.",
    },
    {
        "id": "end-02", "genre": "thue_kho", "length": 48_500, "question_at": "start",
        "intro": "Đây là hợp đồng thuê kho giữa công ty mình và Công ty TNHH Kho vận Bình Minh, bản đầy đủ gồm cả các phụ lục.",
        "question": "Nếu công ty mình muốn chấm dứt hợp đồng thuê kho trước hạn thì bao lâu sau khi bàn giao mặt bằng sẽ được hoàn cọc, và nộp hồ sơ hoàn cọc cho ai?",
        "facts": [(0.93, "PHỤ LỤC 23. Khi hợp đồng chấm dứt trước hạn do bên thuê, tiền đặt cọc được hoàn lại sau 45 ngày kể từ ngày bàn giao mặt bằng, sau khi trừ các khoản chưa thanh toán. Người nhận hồ sơ hoàn cọc là bà Đặng Thục Quyên, phòng Kế toán của bên cho thuê.")],
        "near": [(0.4, "PHỤ LỤC 9. Khi hợp đồng hết hạn bình thường, tiền đặt cọc được hoàn lại sau 20 ngày kể từ ngày bàn giao mặt bằng. Người nhận hồ sơ hoàn cọc là ông Lương Vĩnh Tiến, phòng Hành chính.")],
        "must": [r"(?<!\d)45\s*ngày", r"Đặng Thục Quyên"],
        "good": "Hoàn cọc sau 45 ngày kể từ ngày bàn giao mặt bằng; nộp hồ sơ cho bà Đặng Thục Quyên.",
        "bad": "Hoàn cọc sau 20 ngày; nộp hồ sơ cho ông Lương Vĩnh Tiến.",
        "note": "Hợp đồng thuê kho: thời hạn hoàn cọc khi chấm dứt trước hạn và người nhận hồ sơ, ở phụ lục gần cuối; câu hỏi ở đầu. Gây nhiễu: phụ lục về hết hạn bình thường (20 ngày, người khác).",
    },
    {
        "id": "end-03", "genre": "thi", "length": 55_000, "question_at": "end",
        "intro": "Trường Cao đẳng Kỹ thuật Hải Đăng gửi quy chế đào tạo năm học mới, mình dán cả văn bản.",
        "question": "Mình trượt môn cuối kỳ này. Thi lại thì lệ phí mỗi lần bao nhiêu và hạn nộp là mấy giờ?",
        "facts": [(0.9, "ĐIỀU 142. Sinh viên có điểm thi cuối kỳ dưới 4,0 chỉ được đăng ký thi lại tối đa hai lần. Lệ phí mỗi lần thi lại là 280.000 đồng, nộp tại phòng Tài chính trước 16 giờ 30 của ngày làm việc cuối cùng trong tuần đăng ký.")],
        "near": [(0.3, "ĐIỀU 58. Lệ phí phúc khảo là 150.000 đồng cho mỗi môn, nộp tại phòng Đào tạo trước 11 giờ 45 của ngày làm việc thứ năm sau khi công bố điểm."), (0.66, "ĐIỀU 96. Lệ phí học lại là 400.000 đồng cho mỗi tín chỉ, nộp cùng học phí học kỳ.")],
        "must": [r"(?<![\d.,])280\.000", r"16\s*giờ\s*30|16[:h]30"],
        "good": "Thi lại là 280.000 đồng mỗi lần, nộp trước 16 giờ 30 của ngày làm việc cuối tuần đăng ký.",
        "bad": "Thi lại là 150.000 đồng mỗi lần, nộp trước 11 giờ 45.",
        "note": "Quy chế đào tạo: lệ phí thi lại và giờ chót, điều 142 gần cuối. Gây nhiễu: lệ phí phúc khảo (150.000, 11 giờ 45) và lệ phí học lại.",
    },
    {
        "id": "end-04", "genre": "bao_hanh", "length": 63_000, "question_at": "start",
        "intro": "Máy lọc nước Suối Nguồn nhà mình có kèm cuốn điều khoản bảo hành này, đây là toàn bộ nội dung:",
        "question": "Máy lọc nước nhà mình bị hỏng bo mạch vì sét đánh. Có được bảo hành không, mình phải trả bao nhiêu phần trăm, và gọi tổng đài số nào để báo?",
        "facts": [(0.92, "MỤC 263. Máy bị ngập nước do lỗi người dùng không được bảo hành. Riêng bo mạch điều khiển bị hỏng do sét đánh được hỗ trợ sửa một lần, khách hàng đồng chi trả 35% giá linh kiện; báo hỏng qua tổng đài 1900 6725.")],
        "near": [(0.45, "MỤC 120. Lỗi bo mạch do nguồn điện không ổn định không được bảo hành; khách hàng chịu toàn bộ chi phí, liên hệ tổng đài 1900 5518.")],
        "must": [r"35\s*(%|phần trăm)", r"1900\s?6725"],
        "good": "Có, được hỗ trợ sửa một lần; bạn chi trả 35% giá linh kiện. Gọi tổng đài 1900 6725.",
        "bad": "Không được bảo hành, gọi tổng đài 1900 5518.",
        "note": "Điều khoản bảo hành: trường hợp sét đánh gần cuối, kèm tỉ lệ đồng chi trả và số tổng đài; câu hỏi ở đầu. Gây nhiễu: điều về nguồn điện không ổn định, tổng đài khác số.",
    },
    {
        "id": "end-05", "genre": "cau_lac_bo", "length": 72_000, "question_at": "end",
        "intro": "Câu lạc bộ Cờ Tướng Phố Cổ vừa phát điều lệ sửa đổi, mình dán toàn bộ để hỏi.",
        "question": "Mình sắp đi công tác một năm. Muốn giữ tư cách hội viên thì đơn gửi cho ai, báo trước bao lâu và phí giữ chỗ là bao nhiêu?",
        "facts": [(0.89, "ĐIỀU 197. Hội viên muốn bảo lưu tư cách hội viên khi đi công tác dài hạn phải nộp đơn cho Thủ quỹ Vũ Thanh Hằng ít nhất 30 ngày trước, và đóng phí bảo lưu 600.000 đồng cho mỗi năm.")],
        "near": [(0.4, "ĐIỀU 83. Hội viên xin rút khỏi câu lạc bộ phải nộp đơn cho Thư ký Hồ Minh Triết ít nhất 20 ngày trước; hội phí đã đóng không được hoàn lại.")],
        "must": [r"Vũ Thanh Hằng", r"(?<!\d)30\s*ngày", r"(?<![\d.,])600\.000"],
        "good": "Gửi đơn cho Thủ quỹ Vũ Thanh Hằng, báo trước ít nhất 30 ngày, phí bảo lưu 600.000 đồng mỗi năm.",
        "bad": "Gửi đơn cho Thư ký Hồ Minh Triết, báo trước 20 ngày.",
        "note": "Điều lệ câu lạc bộ: bảo lưu tư cách hội viên (người nhận đơn, thời hạn, phí) ở điều 197. Gây nhiễu: điều về xin rút khỏi câu lạc bộ.",
    },
    {
        "id": "end-06", "genre": "an_toan", "length": 84_000, "question_at": "start",
        "intro": "Nhà máy Cơ khí Tân Phát phát sổ tay an toàn lao động dày cộp. Mình dán toàn bộ nội dung sau đây.",
        "question": "Trong ca đêm có người trượt ngã bị thương nhẹ. Biên bản ban đầu nộp cho ai, trong bao lâu, và quá hạn thì bị trừ mấy điểm thi đua?",
        "facts": [(0.9, "MỤC 411. Sau mỗi sự cố, biên bản ban đầu phải nộp cho trưởng ca Nguyễn Hữu Đoàn trong vòng 90 phút. Quá hạn thì ca làm việc đó bị trừ 2 điểm thi đua trong tháng.")],
        "near": [(0.5, "MỤC 205. Sau mỗi sự cố, báo cáo đầy đủ nộp cho cán bộ an toàn Triệu Khánh Vân trong vòng 24 giờ. Quá hạn thì ca làm việc đó bị nhắc nhở bằng văn bản.")],
        "must": [r"Nguyễn Hữu Đoàn", r"(?<!\d)90\s*phút", r"(?<!\d)2\s*điểm"],
        "good": "Nộp biên bản ban đầu cho trưởng ca Nguyễn Hữu Đoàn trong 90 phút; quá hạn bị trừ 2 điểm thi đua.",
        "bad": "Nộp cho cán bộ an toàn Triệu Khánh Vân trong 24 giờ.",
        "note": "Sổ tay an toàn: biên bản ban đầu sau sự cố (người nhận, hạn, điểm trừ) ở mục 411; câu hỏi ở đầu. Gây nhiễu: mục báo cáo đầy đủ với người nhận và hạn khác.",
    },
    {
        "id": "end-07", "genre": "du_lich", "length": 95_500, "question_at": "end",
        "intro": "Công ty du lịch Bồ Câu Trắng gửi bản điều khoản tour đoàn rất dài, mình dán cả vào để hỏi.",
        "question": "Đoàn công ty mình đi 32 người. Từ bao nhiêu khách thì được miễn suất của trưởng đoàn, và nếu hủy tour trước ngày khởi hành 9 ngày thì mất bao nhiêu phần trăm, liên hệ ai?",
        "facts": [
            (0.86, "ĐIỀU 305. Đoàn từ 26 khách trở lên được miễn phí một suất của trưởng đoàn, áp dụng sau khi đã thanh toán đủ giá tour của các khách còn lại."),
            (0.94, "ĐIỀU 318. Hủy tour trước ngày khởi hành 9 ngày thì mất 12% giá tour; người nhận yêu cầu hủy là chị Lê Diễm Hương, phòng Điều hành."),
        ],
        "near": [(0.3, "ĐIỀU 64. Đoàn từ 15 khách trở lên được tặng một bữa tối chung; hủy tour trước ngày khởi hành 3 ngày thì mất 50% giá tour."), (0.6, "ĐIỀU 190. Hủy tour trước ngày khởi hành 14 ngày thì mất 5% giá tour; liên hệ anh Mạc Quốc Thịnh, phòng Kinh doanh.")],
        "must": [r"(?<!\d)26\s*khách", r"(?<!\d)12\s*(%|phần trăm)", r"Lê Diễm Hương"],
        "good": "Từ 26 khách trở lên được miễn một suất trưởng đoàn; hủy trước 9 ngày mất 12%, liên hệ chị Lê Diễm Hương.",
        "bad": "Từ 15 khách; hủy trước 9 ngày mất 5%, liên hệ anh Mạc Quốc Thịnh.",
        "note": "Điều khoản tour đoàn: hai dữ kiện ở điều 305 (miễn suất) và 318 (hủy tour, người nhận), cả hai trong 15% cuối; văn bản dài nhất của bộ. Gây nhiễu: điều về hủy tour trước 3 và 14 ngày.",
    },
]


def paste_text(spec: dict[str, Any]) -> str:
    rng = random.Random(spec["id"])
    genre = GENRES[spec["genre"]]
    length = spec["length"]
    question, intro = spec["question"], spec["intro"]
    head = f"{question}\n\n{intro}\n\n" if spec["question_at"] == "start" else f"{intro}\n\n"
    budget = length - len(head) - (len(question) + 2 if spec["question_at"] == "end" else 0)
    planted = sorted([(fraction, text) for fraction, text in spec["facts"] + spec["near"]])
    parts: list[str] = []
    size, heading, titles = 0, 0, genre["titles"]
    while size < budget:
        if planted and size >= int(planted[0][0] * length) - len(head):
            block = planted.pop(0)[1]
        elif not parts or rng.random() < 0.14:
            block = f"MỤC {heading + 1}. {titles[heading % len(titles)]}" if heading < len(titles) else f"MỤC {heading + 1}. PHẦN BỔ SUNG {heading + 1 - len(titles)}"
            heading += 1
        else:
            block = _paragraph(rng, genre)
        parts.append(block)
        size += len(block) + 2
    body = head + "\n\n".join(parts)
    return body + f"\n\n{question}" if spec["question_at"] == "end" else body


# ── the long conversations and the documents (ticket 44) ──────────────────

ASKS = [
    "Cho mình hỏi quy định chung về {x} nói gì?",
    "Tóm tắt giúp mình phần {x} trong tài liệu hôm trước được không?",
    "Mình cần nhớ gì về {x} khi làm việc ở đây?",
    "Có điểm nào về {x} mà người mới hay bỏ sót không?",
    "Nhờ bạn liệt kê các việc cần làm liên quan đến {x}.",
    "Ngoài {x} thì còn mục nào mình nên đọc kỹ?",
    "Phần {x} có thay đổi so với năm trước không?",
    "Bạn giải thích thêm về {x} giúp mình nhé.",
    "Mình nên chuẩn bị gì trước khi bàn về {x}?",
]


def history(rng: random.Random, chars: int, genres: list[str]) -> list[dict[str, str]]:
    """A chat of earlier turns about other things: each user line is short, each answer a few paragraphs."""
    messages: list[dict[str, str]] = []
    size, turn = 0, 0
    while size < chars:
        genre = GENRES[genres[turn % len(genres)]]
        topic = genre["titles"][(turn * 5 + 1) % len(genre["titles"])].lower()
        ask = ASKS[turn % len(ASKS)].format(x=topic)
        answer = "\n\n".join(_paragraph(rng, genre) for _ in range(rng.randint(3, 4)))
        messages += [{"role": "user", "content": ask}, {"role": "assistant", "content": answer}]
        size += len(ask) + len(answer)
        turn += 1
    return messages


CHUNK_MIN, CHUNK_MAX = 1_750, 1_900


def chunk_text(rng: random.Random, genre: dict[str, list[str]], plant: str | None = None) -> str:
    """One chunk of 1 750-1 900 characters; `plant` goes in after the first 800, so the 400-character preview never shows it."""
    sentences: list[str] = []
    size = 0
    while size < 800:
        sentences.append(_sentence(rng, genre))
        size += len(sentences[-1]) + 1
    if plant:
        sentences.append(plant)
        size += len(plant) + 1
    while size < CHUNK_MIN:
        sentences.append(_sentence(rng, genre))
        size += len(sentences[-1]) + 1
    text = " ".join(sentences)
    while len(text) > CHUNK_MAX:  # Drop a trailing filler sentence (never the planted one).
        last = sentences[-1]
        if last == plant:
            break
        sentences.pop()
        text = " ".join(sentences)
    return text


def document(document_id: str, filename: str, genre: str, chunks: int, plants: dict[int, str], seed: str) -> dict[str, Any]:
    rng = random.Random(seed)
    return {
        "document_id": document_id,
        "filename": filename,
        "chunks": [
            {"chunk_index": index, "page_start": None, "page_end": None, "content": chunk_text(rng, GENRES[genre], plants.get(index))}
            for index in range(chunks)
        ],
    }


SINGLES: list[dict[str, Any]] = [
    {
        "id": "ctx-01", "genre": "cau_lac_bo", "filename": "dieu_le_hoi_cuu_sinh_vien_khoa_co_khi.txt", "chunks": 12, "history_chars": 24_000,
        "history_genres": ["thi", "chung_cu", "an_toan"],
        "plants": {1: "ĐIỀU 12. Hội phí thường niên của hội viên là 340.000 đồng, nộp một lần trong quý đầu năm.", 5: "ĐIỀU 31. Đại hội toàn thể họp vào ngày 18 tháng 3 hằng năm, tại hội trường tầng 4 nhà E.", 10: "ĐIỀU 58. Ban kiểm tra do bà Phan Ngọc Trâm làm trưởng ban."},
        "question": "Cho mình hỏi trong điều lệ của Hội Cựu sinh viên Khoa Cơ khí: hội phí hằng năm bao nhiêu, đại hội họp ngày nào, và ai làm trưởng ban kiểm tra?",
        "must": [r"(?<![\d.,])340\.000", r"18\s*(tháng\s*3|/\s*0?3)", r"Phan Ngọc Trâm"],
        "good": "Hội phí 340.000 đồng mỗi năm; đại hội họp ngày 18 tháng 3; bà Phan Ngọc Trâm là trưởng ban kiểm tra (dieu_le_hoi_cuu_sinh_vien_khoa_co_khi.txt).",
        "bad": "Hội phí 340.000 đồng mỗi năm; đại hội họp ngày 18 tháng 3.",
        "note": "Điều lệ hội, 12 đoạn: ba dữ kiện ở đoạn 1, 5, 10, cách nhau từ 4 đoạn, nên cần ba lần đọc.",
    },
    {
        "id": "ctx-02", "genre": "thi", "filename": "quy_che_thuc_tap_khoa_dien_tu.txt", "chunks": 12, "history_chars": 23_000,
        "history_genres": ["bao_hanh", "du_lich", "cau_lac_bo"],
        "plants": {2: "ĐIỀU 14. Thời gian thực tập tối thiểu của sinh viên là 11 tuần liên tục tại doanh nghiệp được khoa chấp thuận.", 6: "ĐIỀU 33. Sinh viên nộp báo cáo thực tập cho cô Trịnh Mỹ Dung, phòng Đào tạo, trước ngày 27/05.", 11: "ĐIỀU 61. Điểm thực tập tối thiểu để được công nhận học phần là 5,5 trên thang mười."},
        "question": "Về quy chế thực tập của Khoa Điện tử: tối thiểu thực tập bao lâu, nộp báo cáo cho ai và trước ngày nào, và điểm tối thiểu để được công nhận là bao nhiêu?",
        "must": [r"(?<!\d)11\s*tuần", r"Trịnh Mỹ Dung", r"27\s*/\s*0?5|27 tháng 5", r"5[,.]5"],
        "good": "Tối thiểu 11 tuần; nộp báo cáo cho cô Trịnh Mỹ Dung trước ngày 27/05; điểm tối thiểu 5,5.",
        "bad": "Tối thiểu 11 tuần; nộp báo cáo cho phòng Đào tạo.",
        "note": "Quy chế thực tập, 12 đoạn: ba dữ kiện ở đoạn 2, 6, 11 (bốn mẩu thông tin), ba lần đọc.",
    },
    {
        "id": "ctx-03", "genre": "an_toan", "filename": "so_tay_an_toan_xuong_son.txt", "chunks": 12, "history_chars": 22_000,
        "history_genres": ["chung_cu", "thue_kho", "thi"],
        "plants": {1: "MỤC 9. Bình chữa cháy trong xưởng sơn được kiểm tra định kỳ mỗi 9 tháng, do cán bộ an toàn ký xác nhận.", 5: "MỤC 24. Số điện thoại khẩn cấp nội bộ của xưởng sơn là 7788, trực suốt 24 giờ.", 9: "MỤC 40. Khi có báo động, mọi người tập hợp tại bãi xe phía sau nhà kho số 6."},
        "question": "Trong sổ tay an toàn xưởng sơn: bình chữa cháy kiểm tra bao lâu một lần, số điện thoại khẩn cấp nội bộ là gì và khi báo động thì tập hợp ở đâu?",
        "must": [r"(?<!\d)9\s*tháng", r"(?<!\d)7788(?!\d)", r"nhà kho số 6"],
        "good": "Kiểm tra mỗi 9 tháng; số khẩn cấp nội bộ 7788; tập hợp tại bãi xe phía sau nhà kho số 6.",
        "bad": "Kiểm tra mỗi 9 tháng; số khẩn cấp 7788.",
        "note": "Sổ tay an toàn xưởng sơn, 12 đoạn: ba dữ kiện ở đoạn 1, 5, 9.",
    },
    {
        "id": "ctx-04", "genre": "thue_kho", "filename": "hop_dong_thue_van_phong_tang_5.txt", "chunks": 12, "history_chars": 24_500,
        "history_genres": ["du_lich", "an_toan", "bao_hanh"],
        "plants": {1: "ĐIỀU 5. Tiền thuê văn phòng tầng 5 là 7.250.000 đồng mỗi tháng, đã gồm phí quản lý.", 6: "ĐIỀU 19. Bên thuê muốn gia hạn hợp đồng phải báo trước 50 ngày bằng văn bản.", 10: "ĐIỀU 27. Người nhận các thông báo của bên thuê là ông Cao Văn Thiện, trưởng phòng Hành chính của bên cho thuê."},
        "question": "Hợp đồng thuê văn phòng tầng 5: tiền thuê mỗi tháng bao nhiêu, muốn gia hạn thì báo trước bao lâu, và thông báo gửi cho ai?",
        "must": [r"(?<![\d.,])7\.250\.000|7,25\s*triệu", r"(?<!\d)50\s*ngày", r"Cao Văn Thiện"],
        "good": "Tiền thuê 7.250.000 đồng một tháng; gia hạn phải báo trước 50 ngày; thông báo gửi ông Cao Văn Thiện.",
        "bad": "Tiền thuê 7.250.000 đồng một tháng; báo trước 50 ngày.",
        "note": "Hợp đồng thuê văn phòng, 12 đoạn: ba dữ kiện ở đoạn 1, 6, 10.",
    },
]

QUOTE_CHUNKS = 8
QUOTES: list[dict[str, Any]] = [
    {
        "id": "ctx-05", "goods": "ghế văn phòng", "history_chars": 9_000,
        "history_genres": ["chung_cu", "thi", "du_lich"],
        "suppliers": [
            ("Công ty Cổ phần Nội thất Tân Lộc", "bao_gia_tan_loc.txt", "1.265.000", "18"),
            ("Công ty TNHH Nội thất Bạch Dương", "bao_gia_bach_duong.txt", "1.090.000", "26"),
            ("Cơ sở Mộc Hưng Thịnh", "bao_gia_hung_thinh.txt", "1.340.000", "11"),
        ],
        "question": "Công ty mình cần 40 ghế văn phòng. So ba báo giá giúp mình: bên nào có đơn giá thấp nhất và là bao nhiêu, bên nào giao nhanh nhất và mất bao nhiêu ngày làm việc?",
        "cheapest": 1, "fastest": 2,
        "note": "Ba báo giá ghế, 8 đoạn mỗi tài liệu: đơn giá ở đoạn 1, thời hạn giao ở đoạn 6; sáu lần đọc.",
    },
    {
        "id": "ctx-06", "goods": "máy chiếu", "history_chars": 10_000,
        "history_genres": ["thue_kho", "cau_lac_bo", "bao_hanh"],
        "suppliers": [
            ("Công ty TNHH Thiết bị Quang Minh", "bao_gia_quang_minh.txt", "9.820.000", "13"),
            ("Công ty Cổ phần Công nghệ Vĩnh Phát", "bao_gia_vinh_phat.txt", "10.450.000", "9"),
            ("Cửa hàng Điện máy Song Ngư", "bao_gia_song_ngu.txt", "8.930.000", "22"),
        ],
        "question": "Phòng họp cần một máy chiếu. Trong ba báo giá, đơn vị nào rẻ nhất, giá bao nhiêu, và đơn vị nào giao nhanh nhất, bao nhiêu ngày làm việc?",
        "cheapest": 2, "fastest": 1,
        "note": "Ba báo giá máy chiếu, 8 đoạn mỗi tài liệu: đơn giá ở đoạn 2, thời hạn giao ở đoạn 6.",
        "price_chunk": 2,
    },
    {
        "id": "ctx-07", "goods": "bảng tên in", "history_chars": 8_500,
        "history_genres": ["an_toan", "du_lich", "thi"],
        "suppliers": [
            ("Xưởng in Hoàng Yến", "bao_gia_hoang_yen.txt", "47.500", "16"),
            ("Công ty In ấn Sao Mai", "bao_gia_sao_mai.txt", "52.300", "9"),
            ("Công ty TNHH Quảng cáo Đại Phong", "bao_gia_dai_phong.txt", "41.800", "19"),
        ],
        "question": "Mình cần in 200 bảng tên cho hội nghị. Báo giá nào có đơn giá một bảng thấp nhất và là bao nhiêu, báo giá nào giao nhanh nhất và mất mấy ngày làm việc?",
        "cheapest": 2, "fastest": 1,
        "note": "Ba báo giá bảng tên, 8 đoạn mỗi tài liệu: đơn giá ở đoạn 1, thời hạn giao ở đoạn 5.",
        "delivery_chunk": 5,
    },
]


def _money_pattern(price: str) -> str:
    return r"(?<![\d.,])" + price.replace(".", r"\.")


def build_single(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    doc_id = f"long-{spec['id']}"
    doc = document(doc_id, spec["filename"], spec["genre"], spec["chunks"], spec["plants"], spec["id"])
    task = {
        "id": spec["id"], "category": "documents", "surface": "web",
        "history": history(random.Random(spec["id"] + "-history"), spec["history_chars"], spec["history_genres"]),
        "input": spec["question"],
        "expect": {
            "tools_required": ["search_documents", "read_document"],
            "tools_forbidden": ["search_history", "system_status"],
            "must_mention": spec["must"],
        },
        "context_ceiling": True,
        "note": spec["note"] + f" Lịch sử trò chuyện {spec['history_chars']:,} ký tự về chuyện khác, nên ba kết quả đọc không vừa cửa sổ cùng với lịch sử. Nội dung hư cấu.".replace(",", " "),
    }
    return task, doc, _retrieval(spec["id"], doc, [0, 3, 7], spec["question"])


def build_quote(spec: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    price_chunk, delivery_chunk = spec.get("price_chunk", 1), spec.get("delivery_chunk", 6)
    docs: list[dict[str, Any]] = []
    for number, (company, filename, price, days) in enumerate(spec["suppliers"], 1):
        plants = {
            price_chunk: f"ĐƠN GIÁ. {company} chào giá {spec['goods']} là {price} đồng một cái, đã gồm thuế giá trị gia tăng.",
            delivery_chunk: f"GIAO HÀNG. {company} giao toàn bộ đơn hàng trong {days} ngày làm việc kể từ ngày hai bên ký hợp đồng.",
        }
        docs.append(document(f"long-{spec['id']}-{number}", filename, "bao_gia", QUOTE_CHUNKS, plants, f"{spec['id']}-{number}"))
    cheapest, fastest = spec["suppliers"][spec["cheapest"]], spec["suppliers"][spec["fastest"]]
    task = {
        "id": spec["id"], "category": "documents", "surface": "web",
        "history": history(random.Random(spec["id"] + "-history"), spec["history_chars"], spec["history_genres"]),
        "input": spec["question"],
        "expect": {
            "tools_required": ["search_documents", "read_document"],
            "tools_forbidden": ["search_history", "system_status"],
            "must_mention": [re.escape(_short(cheapest[0])), _money_pattern(cheapest[2]), re.escape(_short(fastest[0])), r"(?<!\d)" + fastest[3] + r"\s*ngày"],
        },
        "context_ceiling": True,
        "note": spec["note"] + f" Lịch sử trò chuyện {spec['history_chars']:,} ký tự về chuyện khác. Nội dung hư cấu.".replace(",", " "),
    }
    hits = [doc for doc in docs]
    return task, docs, _retrieval(spec["id"], hits, [0], spec["question"])


def _short(company: str) -> str:
    """The name a person would say: the company's last two words ("Tân Lộc", "Hưng Thịnh")."""
    return " ".join(company.split()[-2:])


def _retrieval(task_id: str, docs: Any, indexes: list[int], query: str) -> dict[str, Any]:
    docs = docs if isinstance(docs, list) else [docs]
    chunks = []
    for doc in docs:
        for index in indexes:
            chunk = doc["chunks"][index]
            chunks.append({
                "filename": doc["filename"], "page": None, "content": chunk["content"], "score": round(0.92 - 0.03 * len(chunks), 2),
                "chunk_id": f"{doc['document_id']}#{index}", "document_id": doc["document_id"], "chunk_index": index,
            })
    return {"task_id": task_id, "source": "handwritten", "query": query, "chunks": chunks}


def paste_task(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": spec["id"], "category": "documents", "surface": "web",
        "input": paste_text(spec),
        "expect": {"tools_forbidden": ["search_history", "system_status"], "must_mention": spec["must"]},
        "long_input": True,
        "note": spec["note"] + " Nội dung hư cấu.",
    }


def build() -> dict[str, str]:
    """The text of each file."""
    tasks = [paste_task(spec) for spec in PASTES]
    documents: list[dict[str, Any]] = []
    retrieval: list[dict[str, Any]] = []
    for spec in SINGLES:
        task, doc, fixture = build_single(spec)
        tasks.append(task)
        documents.append(doc)
        retrieval.append(fixture)
    for spec in QUOTES:
        task, docs, fixture = build_quote(spec)
        tasks.append(task)
        documents.extend(docs)
        retrieval.append(fixture)
    meta = {
        "version": VERSION,
        "created": "2026-11-02",
        "note": "Bộ bài dài cho ticket 44 (chạm trần ngữ cảnh) và 45 (đáp án ở cuối văn bản rất dài); không có bài nào của v0. Dữ liệu hoàn toàn bịa, sinh bằng backend/scripts/agent_eval_build_long.py.",
        "guild": {
            "guild_id": "900000000000000001",
            "now": "2026-10-20T12:00:00+07:00",
            "messages": [
                {"id": "7001", "channel_id": "50", "author_id": "1001", "author_display_name": "Lan", "is_bot": False, "content": "Chào mọi người.", "sent_at": "2026-10-12T09:00:00+07:00"},
            ],
        },
        "status_snapshots": {"healthy": {"status": "ok", "service": "local-ai-core", "ollama": "ok", "qdrant": "ok", "postgres": "ok", "redis": "ok", "checked_at": "2026-10-20T05:00:00+00:00"}},
    }

    def lines(rows: list[dict[str, Any]]) -> str:
        return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)

    return {
        "dataset.json": json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        "tasks.jsonl": lines(tasks),
        "retrieval.jsonl": lines(retrieval),
        "documents.jsonl": lines(documents),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 when the files on disk differ")
    args = parser.parse_args()
    files = build()
    if args.check:
        stale = [name for name, text in files.items() if not (OUT_DIR / name).is_file() or (OUT_DIR / name).read_bytes().replace(b"\r\n", b"\n") != text.encode("utf-8")]
        print("khác: " + ", ".join(stale) if stale else "khớp")
        return 1 if stale else 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (OUT_DIR / name).write_bytes(text.encode("utf-8"))
    print(f"đã ghi {len(files)} tệp vào {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
