"""Content-free model input measurements, opt-in per request."""
from contextlib import contextmanager
from contextvars import ContextVar
import json

_records = ContextVar("model_input_measurements", default=None)

@contextmanager
def model_input_measurements(enabled=True):
    if not enabled:
        yield None
        return
    rows = []
    token = _records.set(rows)
    try:
        yield rows
    finally:
        _records.reset(token)

def measure_input(kind, messages, schemas=None):
    rows = _records.get()
    if rows is None:
        return
    text = json.dumps(messages, ensure_ascii=False, separators=(",", ":"), default=str)
    schema = json.dumps(schemas or [], ensure_ascii=False, separators=(",", ":"), default=str)
    rows.append({"kind": kind, "message_chars": len(text), "schema_chars": len(schema)})
