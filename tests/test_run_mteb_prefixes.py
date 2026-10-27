"""run_mteb's two-sided prefix option, and that the default run did not move (ticket 13).

e5 needs "query: " / "passage: " on each side; Qwen3-Embedding an instruction on the
query side only. The first test pins what build_model hands mteb's wrapper, with a fake
`mteb` in sys.modules, so it runs anywhere. The second runs only where mteb is installed
(.venv-eval): it encodes through the REAL wrapper with the HTTP layer faked, because the
trap here is inside mteb — prompt_dict alone sent both sides bare (27/10), the same
"two configurations, identical numbers" failure as 05/09.
"""
from __future__ import annotations

import sys
import types

import pytest

from training.common import run_mteb

DEFAULT_KWARGS = {
    "endpoint_url": "http://127.0.0.1:11434", "model_name": "m", "api_key": "ollama",
    "modalities": ["text"], "use_chat_template": False,
}
QWEN_KWARGS = {
    **DEFAULT_KWARGS, "use_instructions": True, "apply_instruction_to_documents": False,
    "instruction_template": "Instruct: {instruction}\nQuery: ", "prompt_dict": {},
}
UNSET = object()


@pytest.fixture
def wrapper(monkeypatch):
    """A stand-in for mteb.models.OpenAIAPIEncodeWrapper that keeps its kwargs."""
    class FakeWrapper:
        model_prompts = UNSET

        def __init__(self, **kwargs):
            self.kwargs = kwargs

    models = types.ModuleType("mteb.models")
    models.OpenAIAPIEncodeWrapper = FakeWrapper
    package = types.ModuleType("mteb")
    package.models = models
    monkeypatch.setitem(sys.modules, "mteb", package)
    monkeypatch.setitem(sys.modules, "mteb.models", models)
    return FakeWrapper


def test_the_default_and_the_qwen_instruction_hand_mteb_what_they_did_before(wrapper):
    plain = run_mteb.build_model("m", "http://127.0.0.1:11434", False)
    qwen = run_mteb.build_model("m", "http://127.0.0.1:11434", True)

    assert plain.kwargs == DEFAULT_KWARGS and plain.model_prompts is UNSET
    assert qwen.kwargs == QWEN_KWARGS and qwen.model_prompts is UNSET


def test_two_sided_prefixes_set_prompt_dict_and_model_prompts_alike(wrapper):
    e5 = run_mteb.build_model("m", "http://127.0.0.1:11434", False, "query: ", "passage: ")

    assert e5.kwargs == {**DEFAULT_KWARGS, "prompt_dict": {"query": "query: ", "document": "passage: "}}
    assert e5.model_prompts == {"query": "query: ", "document": "passage: "}


def test_the_two_conventions_cannot_be_combined(wrapper):
    with pytest.raises(ValueError, match="pick one"):
        run_mteb.build_model("m", "http://127.0.0.1:11434", True, "query: ", None)


def test_the_real_wrapper_sends_each_side_its_prefix(monkeypatch):
    pytest.importorskip("mteb")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("HF_DATASETS_OFFLINE", "1")
    import mteb
    from mteb.models import openai_wrappers
    from mteb.types import PromptType

    sent: list[str] = []

    class Response:
        status_code, text = 200, ""

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

        def raise_for_status(self):
            pass

    class FakeRequests:
        def __getattr__(self, name):
            import requests
            return getattr(requests, name)

        @staticmethod
        def get(url, **kwargs):
            return Response({"data": [{"id": "m"}]})

        @staticmethod
        def post(url, json=None, **kwargs):
            sent.extend(json["input"])
            return Response({"data": [{"embedding": [1.0, 0.0], "index": i} for i, _ in enumerate(json["input"])]})

    monkeypatch.setattr(openai_wrappers, "requests", FakeRequests())
    meta = mteb.get_task("VieQuADRetrieval").metadata

    def texts(model) -> dict[str, str]:
        out = {}
        for side in (PromptType.query, PromptType.document):
            sent.clear()
            model.encode([{"text": ["xin chao"]}], task_metadata=meta, hf_split="test", hf_subset="default",
                         prompt_type=side, show_progress_bar=False)
            out[side.value] = sent[0]
        return out

    endpoint = "http://127.0.0.1:1"   # never reached: get and post are the fakes above
    assert texts(run_mteb.build_model("m", endpoint, False, "query: ", "passage: ")) == {
        "query": "query: xin chao", "document": "passage: xin chao"}
    assert texts(run_mteb.build_model("m", endpoint, True)) == {
        "query": "Instruct: Retrieve text based on user query.\nQuery: xin chao", "document": "xin chao"}
    assert texts(run_mteb.build_model("m", endpoint, False)) == {"query": "xin chao", "document": "xin chao"}
