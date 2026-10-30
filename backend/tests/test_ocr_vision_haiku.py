"""Ticket 33: Haiku reads images for the OCR and vision roles, and the bot hands a turn what it saw."""
from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

import pytest

from app.llm_clients.anthropic_client import AnthropicClient, image_block
from app.services.model_router import ModelRouter
from discord_bot.main import question_with_images

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 20).decode()
JPEG = base64.b64encode(b"\xff\xd8\xff" + b"0" * 20).decode()
HOME = 111


class FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="đã đọc")], stop_reason="end_turn", model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0),
        )


def claude() -> tuple[AnthropicClient, FakeMessages]:
    messages = FakeMessages()
    client = AnthropicClient(api_key="k", sdk_client=SimpleNamespace(messages=messages))
    return client, messages


def test_the_media_type_comes_from_the_bytes() -> None:
    assert image_block(PNG)["source"]["media_type"] == "image/png"
    assert image_block(JPEG)["source"]["media_type"] == "image/jpeg"
    with pytest.raises(ValueError):
        image_block(base64.b64encode(b"not an image").decode())


def test_ocr_goes_to_claude_when_a_claude_version_serves() -> None:
    client, messages = claude()
    router = ModelRouter({"anthropic": client}, {"ocr": {"provider": "anthropic", "name": "claude-haiku-5-5", "enabled": True, "max_tokens": 4096}})
    assert router.ocr(PNG, prompt="Chép lại") == ("đã đọc", "claude-haiku-5-5")
    content = messages.calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[1]["text"] == "Chép lại"


def test_vision_refuses_when_nothing_serves_and_answers_when_something_does() -> None:
    client, _ = claude()
    with pytest.raises(ValueError):
        ModelRouter({"anthropic": client}, {}).vision("Gì đây?", PNG)
    router = ModelRouter({"anthropic": client}, {"vision": {"provider": "anthropic", "name": "claude-haiku-5-5"}})
    assert router.vision("Gì đây?", PNG)[0] == "đã đọc"


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
