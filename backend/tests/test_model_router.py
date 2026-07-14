from app.services.model_router import ModelRouter


class FakeClient:
    def __init__(self):
        self.model = None
        self.options = None
        self.think = None

    def chat(self, model, messages, options, keep_alive, think=None):
        self.model = model
        self.options = options
        self.think = think
        return "answer"


def test_model_router_uses_general_model():
    client = FakeClient()
    router = ModelRouter(client, {"general": {"name": "qwen3.5:9b", "context": 123, "temperature": 0.4}, "code": {"name": "qwen2.5-coder:7b"}})

    answer, model_used = router.chat("general", [{"role": "user", "content": "Hello"}])

    assert answer == "answer"
    assert model_used == "qwen3.5:9b"
    assert client.model == "qwen3.5:9b"
    assert client.options["num_ctx"] == 123


def test_model_router_disables_thinking_when_configured():
    client = FakeClient()
    router = ModelRouter(client, {"general": {"name": "qwen3.5:9b", "think": False}, "code": {"name": "qwen2.5-coder:7b"}})

    router.chat("general", [{"role": "user", "content": "Hello"}])

    assert client.think is False


def test_model_router_uses_code_model():
    client = FakeClient()
    router = ModelRouter(client, {"general": {"name": "qwen3.5:9b"}, "code": {"name": "qwen2.5-coder:7b"}})

    _, model_used = router.chat("code", [{"role": "user", "content": "Hello"}])

    assert model_used == "qwen2.5-coder:7b"
