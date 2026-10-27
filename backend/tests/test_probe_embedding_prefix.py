"""probe_embedding_prefix, everything short of Ollama (ticket 09, step 1).

The probe has to run against the real model: that is the point of step 1, after the
05/09 trap of two "different" runs that were byte-identical. What can be checked
before the GPU is free is the wiring up to the HTTP call: a pin on embedding-v0-qi
reaches the router, only the query side carries the instruction, the empty pin the
script uses for its baseline really is the active version, and the pass condition
reads the right way round. OllamaClient.embed is the one thing replaced.
"""
from __future__ import annotations

import hashlib

import pytest

from app.llm_clients.ollama_client import OllamaClient
from scripts import probe_embedding_prefix as probe

INSTRUCTION = "Instruct: Retrieve text based on user query.\nQuery: "


def fake_vector(text: str) -> list[float]:
    return [byte - 127.5 for byte in hashlib.sha256(text.encode("utf-8")).digest()]


@pytest.fixture
def sent(monkeypatch) -> list[tuple[str, str]]:
    """(model, text) for every embed call; Settings without probes, so nothing else is reached."""
    calls: list[tuple[str, str]] = []

    def embed(self, model: str, text: str) -> list[float]:
        calls.append((model, text))
        return fake_vector(text)

    monkeypatch.setattr(OllamaClient, "embed", embed)
    monkeypatch.setenv("MODEL_STARTUP_PROBES", "false")
    # Required by Settings; never connected to, because no probe runs.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://probe:probe@127.0.0.1:1/none")
    return calls


def test_only_the_query_side_carries_the_instruction(sent, monkeypatch):
    monkeypatch.setenv("MODEL_VERSION_EMBEDDING", "embedding-v0-qi")
    probe.vectors()
    assert sent == [("qwen3-embedding:0.6b", INSTRUCTION + probe.TEXT), ("qwen3-embedding:0.6b", probe.TEXT)]


def test_the_scripts_empty_pin_is_the_active_version_without_a_prefix(sent, monkeypatch):
    monkeypatch.setenv("MODEL_VERSION_EMBEDDING", "")
    probe.vectors()
    assert sent == [("qwen3-embedding:0.6b", probe.TEXT), ("qwen3-embedding:0.6b", probe.TEXT)]


def test_the_pass_condition_holds_when_only_the_query_side_moved(sent, monkeypatch):
    monkeypatch.setenv("MODEL_VERSION_EMBEDDING", "")
    base = probe.vectors()
    monkeypatch.setenv("MODEL_VERSION_EMBEDDING", "embedding-v0-qi")
    pinned = probe.vectors()

    assert probe.cosine(base["query"], pinned["query"]) < 0.999
    assert probe.cosine(base["passage"], pinned["passage"]) >= 0.999999
