"""Review2 R9: the OCR reader's field filter decides which evidence blocks the model may
choose from. A question about a field must reach the blocks that hold it, and only them;
a question about a field the document lacks must be answered "missing" without a model call.

Pure Python: read_evidence with a fake model that records the blocks it was offered.
"""
from __future__ import annotations

import json

import pytest

from app.services.ocr_reader import read_evidence
from review2_support import KnownBug, known_bug


class Reader:
    def __init__(self) -> None:
        self.calls = 0
        self.offered: list[str] = []

    def chat_structured(self, mode, messages, schema, **kwargs):
        self.calls += 1
        self.offered = [block["id"] for block in json.loads(messages[1]["content"])["evidence"]]
        return json.dumps({"block_ids": []}), "fake-reader"


def ask(question: str, blocks: dict[str, str]):
    reader = Reader()
    result = read_evidence(reader, question, [
        {"id": key, "page": 1, "kind": "text", "text": value} for key, value in blocks.items()])
    return reader, result


NAME = "Người nhận: Phạm Ngọc Quỳnh"
PHONE = "Điện thoại: 0912 345 678"
EMAIL = "Email: quynh@example.vn"
ACCOUNT = "Số tài khoản: 0123 456 789"
R9 = "review2 R9: the field filter keeps only the first matching rule and a Vietnamese-only phone pattern"


@pytest.mark.parametrize("question", ["Số điện thoại và email của người nhận?", "Email và số điện thoại của người nhận?"],
                         ids=["phone_then_email", "email_then_phone"])
@pytest.mark.xfail(strict=True, raises=KnownBug, reason=R9)
def test_r9_1_asking_for_phone_and_email_offers_both(question):
    reader, _ = ask(question, {"phone": PHONE, "email": EMAIL, "name": NAME})
    known_bug({"phone", "email"} <= set(reader.offered), f"the model was offered only {reader.offered}")


@pytest.mark.parametrize("block", [
    "Phone: +1 415 555 2671",
    "ĐT: 028 3822 1234",
    "Di động: 0912 345 678",
    "Hotline: 1900 1234",
    "Điện thoại: (84-28) 3822 1234",
], ids=["intl_plus1", "label_DT", "label_di_dong", "hotline_1900", "paren_84_28"])
@pytest.mark.xfail(strict=True, raises=KnownBug, reason=R9)
def test_r9_2_a_phone_number_written_another_way_reaches_the_model(block):
    reader, result = ask("Số điện thoại của người gửi là gì?", {"phone": block, "name": NAME})
    known_bug("phone" in reader.offered, f"the phone block never reached the model: {result.get('reason')}")


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=R9)
def test_r9_3_a_question_about_a_phone_model_is_not_a_phone_number_question():
    reader, result = ask("What phone model is shown?", {"model": "Model: iPhone 15 Pro", "name": NAME})
    known_bug(reader.calls == 1, f"the model was never asked: {result.get('reason')}")


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=R9)
def test_r9_3_asking_for_an_e_mail_the_document_lacks_is_answered_missing():
    reader, result = ask("E-mail của người nhận là gì?", {"name": NAME})
    known_bug(reader.calls == 0 and result["status"] == "insufficient_evidence",
              f"the model was asked to find an e-mail among {reader.offered}")


@pytest.mark.parametrize("block", [NAME, "STK: 0123 456 789", "Ngày lập: 12/03/2024"], ids=["name", "account_stk", "date"])
def test_r9_4_a_phone_question_without_a_phone_number_is_answered_missing(block):
    reader, result = ask("Số điện thoại của người nhận là gì?", {"other": block})
    assert reader.calls == 0
    assert result["status"] == "insufficient_evidence"


@pytest.mark.parametrize(("question", "phone", "expected"), [
    ("Số điện thoại?", PHONE, "phone"),
    ("Số điện thoại?", "SĐT: +84 912 345 678", "phone"),
    ("Số điện thoại?", "Tel: (028) 3822-1234", "phone"),
    ("Email của người nhận?", PHONE, "email"),
    ("Số tài khoản là gì?", PHONE, "account"),
], ids=["vn_plain", "vn_plus84", "vn_landline", "email_only", "account_only"])
def test_r9_5_a_field_question_offers_its_field_and_nothing_else(question, phone, expected):
    reader, _ = ask(question, {"phone": phone, "email": EMAIL, "account": ACCOUNT, "name": NAME})
    assert reader.offered == [expected]
