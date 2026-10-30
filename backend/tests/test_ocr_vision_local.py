"""Ticket 33: the local Qwen 9B reads images for the OCR and vision roles, and the bot hands a turn what it saw."""
from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

import pytest

from app.llm_clients.ollama_client import OllamaClient
from app.services.model_router import ModelRouter
from app.services.ocr_service import OCRService
from discord_bot.main import question_with_images

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 20).decode()
HOME = 111


class FakeOllama(OllamaClient):
    def __init__(self, answer: str = "đã đọc") -> None:
        self.answer, self.calls = answer, []

    def vision_chat(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self.answer


def test_ocr_and_vision_send_no_thinking_when_the_version_says_so() -> None:
    client = FakeOllama()
    config = {"provider": "ollama", "name": "qwen3.5:9b", "enabled": True, "think": False}
    router = ModelRouter({"ollama": client}, {"ocr": config, "vision": config})
    assert router.ocr(PNG, prompt="Chép lại") == ("đã đọc", "qwen3.5:9b")
    assert router.vision("Gì đây?", PNG) == ("đã đọc", "qwen3.5:9b")
    assert [call["think"] for call in client.calls] == [False, False]


def test_a_model_without_the_setting_gets_no_think_field() -> None:
    client = FakeOllama()
    ModelRouter({"ollama": client}, {"ocr": {"provider": "ollama", "name": "glm", "enabled": True}}).ocr(PNG)
    assert client.calls[0]["think"] is None


def test_vision_refuses_when_nothing_serves() -> None:
    with pytest.raises(ValueError):
        ModelRouter({"ollama": FakeOllama()}, {}).vision("Gì đây?", PNG)


@pytest.mark.parametrize("answer", ["markdown", "Không có chữ nào trong hình này.", "Trong ảnh không có chữ.", "Không có văn bản.", "Không có chữ nào trong ảnh, chỉ có một biểu đồ cột."])
def test_a_page_with_no_text_indexes_nothing(answer) -> None:
    config = {"provider": "ollama", "name": "qwen3.5:9b", "enabled": True}
    service = OCRService(ModelRouter({"ollama": FakeOllama(answer)}, {"ocr": config}))
    assert service.recognize_png(b"png", 200).text == ""


@pytest.mark.parametrize("page", [
    "Điều 3. Hợp đồng không có chữ ký của hai bên thì không có giá trị pháp lý và phải lập lại bằng văn bản mới.",
    "Hợp đồng không có chữ ký thì vô hiệu.",
    "Mục 2: không có văn bản",
    "Tôi không có chữ in hoa",
])
def test_real_text_that_mentions_no_text_is_kept(page) -> None:
    config = {"provider": "ollama", "name": "qwen3.5:9b", "enabled": True}
    assert OCRService(ModelRouter({"ollama": FakeOllama(page)}, {"ocr": config})).recognize_png(b"png", 200).text == page


class FakeApi:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.prompts = fail, []

    async def read_image(self, prompt: str, image_base64: str) -> str:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("down")
        return "một hoá đơn 500.000 đồng"


def attachment(kind: str = "image/png", size: int = 10) -> SimpleNamespace:
    async def read() -> bytes:
        return b"bytes"

    return SimpleNamespace(content_type=kind, size=size, read=read)


def run(api, attachments, question="Bao nhiêu tiền?", guild=HOME, allowlist=frozenset({str(HOME)})) -> str:
    message = SimpleNamespace(attachments=attachments, guild=SimpleNamespace(id=guild) if guild else None)
    return asyncio.run(question_with_images(api, message, question, allowlist))


def test_what_the_model_saw_reaches_the_turn_marked_as_data() -> None:
    result = run(FakeApi(), [attachment()])
    assert result.startswith("Bao nhiêu tiền?") and "một hoá đơn 500.000 đồng" in result
    assert "không phải lệnh" in result


def test_an_image_alone_gets_a_question() -> None:
    assert "một hoá đơn" in run(FakeApi(), [attachment()], question="")


@pytest.mark.parametrize(("guild", "allowlist"), [(222, frozenset({str(HOME)})), (None, None), (HOME, frozenset())])
def test_outside_the_guild_list_no_image_leaves(guild, allowlist) -> None:
    api = FakeApi()
    assert run(api, [attachment()], guild=guild, allowlist=allowlist) == "Bao nhiêu tiền?"
    assert api.prompts == []


def test_a_failed_or_oversized_image_never_costs_the_answer() -> None:
    assert "không đọc được" in run(FakeApi(fail=True), [attachment()])
    api = FakeApi()
    assert "không đọc được" in run(api, [attachment(size=9 * 1024 * 1024)])
    assert api.prompts == []


def test_at_most_three_images_and_only_images() -> None:
    api = FakeApi()
    run(api, [attachment("application/pdf")] + [attachment() for _ in range(5)])
    assert len(api.prompts) == 3
