import pytest

from app.services.reranker_service import RerankerService, RerankerUnavailableError


class FakeCrossEncoder:
    def predict(self, pairs):
        return [0.1, 0.9, 0.4]


def test_reranker_is_disabled_without_loading_model():
    service = RerankerService(False, "unused", 15, model_loader=lambda _: (_ for _ in ()).throw(AssertionError()))
    candidates = [{"content": "a"}, {"content": "b"}]

    assert service.rerank("question", candidates, 1) == [{"content": "a"}]


def test_reranker_reorders_candidates_by_cross_encoder_score():
    service = RerankerService(True, "fake", 15, model_loader=lambda _: FakeCrossEncoder())
    candidates = [{"content": "first"}, {"content": "second"}, {"content": "third"}]

    results = service.rerank("question", candidates, 2)

    assert [result["content"] for result in results] == ["second", "third"]
    assert results[0]["reranker_score"] == 0.9


def test_candidate_limit_caps_what_the_cross_encoder_scores():
    """The limit is a cost control: scoring is linear in candidates, and every
    one of them costs query-time milliseconds (P4-3)."""
    seen: list[int] = []

    class CountingEncoder:
        def predict(self, pairs):
            seen.append(len(pairs))
            return list(range(len(pairs)))

    service = RerankerService(True, "fake", 2, model_loader=lambda _: CountingEncoder())
    candidates = [{"content": f"c{index}"} for index in range(10)]

    service.rerank("question", candidates, 5)

    assert seen == [2], "more candidates were scored than candidate_limit allows"


def test_model_is_loaded_once_across_questions():
    loads: list[str] = []

    def loader(name):
        loads.append(name)
        return FakeCrossEncoder()

    service = RerankerService(True, "fake", 15, model_loader=loader)
    for _ in range(3):
        service.rerank("question", [{"content": "a"}, {"content": "b"}, {"content": "c"}], 2)

    assert loads == ["fake"], "the cross-encoder must be loaded once, not per question"


def test_run_failure_surfaces_as_reranker_unavailable():
    def loader(_):
        raise RuntimeError("no weights on this machine")

    service = RerankerService(True, "fake", 15, model_loader=loader)

    with pytest.raises(RerankerUnavailableError):
        service.rerank("question", [{"content": "a"}, {"content": "b"}], 1)


# ── Warmup: a misconfigured machine must fail at startup, not at question time ──


def test_warmup_loads_the_model_so_the_first_question_does_not_pay_for_it():
    loads: list[str] = []
    service = RerankerService(True, "fake", 15, model_loader=lambda name: loads.append(name) or FakeCrossEncoder())

    service.warmup()
    assert loads == ["fake"]

    service.rerank("question", [{"content": "a"}, {"content": "b"}, {"content": "c"}], 2)
    assert loads == ["fake"], "warmup did not prime the cache; the question reloaded the model"


def test_warmup_raises_when_the_optional_extra_is_missing():
    def loader(_):
        raise RerankerUnavailableError("Reranker cần gói tùy chọn: pip install -e .[rerank]")

    with pytest.raises(RerankerUnavailableError, match=r"\[rerank\]"):
        RerankerService(True, "fake", 15, model_loader=loader).warmup()


def test_warmup_is_a_noop_when_disabled():
    """A machine with the flag off must start even without the extra installed."""
    service = RerankerService(False, "fake", 15, model_loader=lambda _: (_ for _ in ()).throw(AssertionError()))

    service.warmup()  # must not raise, must not load


# ── Per-environment override (DEVELOPMENT_PLAN.md 3e) ────────────────


def test_from_config_follows_models_yaml_when_no_override():
    service = RerankerService.from_config({"reranker": {"enabled": True, "model": "m", "candidate_limit": 30}})
    assert service.enabled is True
    assert service.model_name == "m" and service.candidate_limit == 30


def test_from_config_env_override_wins_in_both_directions():
    # Light machine without the [rerank] extra: yaml ON, .env pins OFF.
    assert RerankerService.from_config({"reranker": {"enabled": True}}, enabled_override=False).enabled is False
    # Heavy machine trying it ahead of the shared default: yaml OFF, .env ON.
    assert RerankerService.from_config({"reranker": {"enabled": False}}, enabled_override=True).enabled is True


def test_from_config_tolerates_missing_block():
    service = RerankerService.from_config({})
    assert service.enabled is False
    assert service.candidate_limit == 15
    assert service.model_name == "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


def test_disabled_reranker_never_truncates_to_its_candidate_limit():
    # Regression (pre-existing since 07/2026, found in the P4-3 review): the
    # candidate_limit slice ran BEFORE the enabled check, so the disabled
    # default RerankerService(False, "", 1) capped any caller at one result.
    service = RerankerService(False, "", 1)
    candidates = [{"content": f"chunk {i}", "chunk_id": str(i)} for i in range(5)]
    assert service.rerank("q", candidates, top_k=3) == candidates[:3]
