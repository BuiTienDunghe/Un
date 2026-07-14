from app.services.reranker_service import RerankerService


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
