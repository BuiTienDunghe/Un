"""Input measurements count characters without retaining prompt content."""
import json
from concurrent.futures import ThreadPoolExecutor

from app.services.input_metrics import measure_input, model_input_measurements


def test_disabled_measurements_do_not_serialize_inputs():
    class NoSerialize:
        def __str__(self):
            raise AssertionError("disabled measurement must not inspect content")
    measure_input("chat", NoSerialize())
    with model_input_measurements(False) as rows:
        measure_input("chat", NoSerialize())
    assert rows is None


def test_enabled_measurements_count_unicode_characters_and_reset_nested_scope():
    messages = [{"role": "user", "content": "bí mật: tiếng Việt"}]
    schema = [{"function": {"name": "look_up"}}]
    with model_input_measurements() as outer:
        measure_input("tools", messages, schema)
        with model_input_measurements() as inner:
            measure_input("chat", messages)
        measure_input("chat", messages)
    assert len(outer) == 2 and len(inner) == 1
    assert outer[0] == {"kind": "tools",
        "message_chars": len(json.dumps(messages, ensure_ascii=False, separators=(",", ":"))),
        "schema_chars": len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")))}
    assert "bí mật" not in repr(outer)
    measure_input("chat", messages)
    assert len(outer) == 2


def test_threads_do_not_share_measurement_rows():
    def run(size):
        with model_input_measurements() as rows:
            measure_input("chat", ["x" * size])
            return rows
    with ThreadPoolExecutor(2) as workers:
        small, large = list(workers.map(run, [1, 100]))
    assert len(small) == len(large) == 1
    assert large[0]["message_chars"] - small[0]["message_chars"] == 99
