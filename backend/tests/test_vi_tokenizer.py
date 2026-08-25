"""T16: the segmenter is a versioned dependency of derived data, so it is pinned and the pin is enforced."""
from __future__ import annotations

import re
from importlib.metadata import version as installed_version
from pathlib import Path

from app.utils.vi_tokenizer import TOKENIZER_VERSION, tokenize_vietnamese

REQUIREMENTS = Path(__file__).resolve().parents[2] / "requirements.txt"


def test_vietnamese_tokenizer_preserves_compound_words():
    tokens = tokenize_vietnamese("Học sinh đang đến trường.")

    assert "học_sinh" in tokens
    assert "học" not in tokens
    assert "sinh" not in tokens


def test_tokenizer_version_reports_the_package_actually_installed():
    """Read back, never hard-coded — a constant that can lie is worse than none."""
    assert TOKENIZER_VERSION == f"pyvi-{installed_version('pyvi')}"
    assert TOKENIZER_VERSION != "pyvi-unknown"


def test_pyvi_is_pinned_exactly_and_the_pin_matches_the_installed_version():
    """The pin is only a promise until something checks it.

    Two failures this catches, both silent otherwise: a range creeping back into
    requirements.txt (so two machines segment differently and neither knows),
    and a pin edited without reinstalling (so the file claims one contract while
    the process runs another). Either one makes the recorded eval baseline
    describe a retrieval stack that is not the one running.
    """
    lines = REQUIREMENTS.read_text(encoding="ascii").splitlines()
    pins = [line.strip() for line in lines if re.match(r"^pyvi\s*[=<>!~]", line.strip())]

    assert pins == [f"pyvi=={installed_version('pyvi')}"], pins


def test_the_recorded_eval_baseline_states_which_tokenizer_produced_it():
    """The gate in evaluate_rag.py can only refuse a mismatch it can see."""
    import json

    baseline = json.loads((REQUIREMENTS.parent / "data/evaluation/rag_multidoc_baseline.json").read_text(encoding="utf-8"))

    assert baseline["tokenizer_version"] == TOKENIZER_VERSION


def test_the_segmenter_still_segments_the_way_the_pin_promises():
    """The version string authenticates a package, not a contract — pin BOTH.

    Found by an adversarial pass on T16 itself: a pyvi placed earlier on
    sys.path that segments differently but ships no dist-info of its own still
    resolves to "0.1.1" through importlib.metadata, so TOKENIZER_VERSION reads
    pyvi-0.1.1, requirements.txt is a pristine exact pin, and every other guard
    here goes green while "quản_lý_tài_liệu" has quietly become two tokens.

    A canary closes that: this is what the pinned segmenter actually DOES, and
    a compound splitting apart is precisely the change that would resegment the
    corpus. If this line goes red, do not edit the expectation — find out what
    is on sys.path.
    """
    assert tokenize_vietnamese("Quản lý tài liệu học sinh trong hệ thống") == [
        "quản_lý_tài_liệu", "học_sinh", "trong", "hệ_thống",
    ]


def test_models_endpoint_publishes_the_tokenizer_for_the_eval_harness(client):
    """The harness reads embedding_model from here; the tokenizer belongs beside it."""
    response = client.get("/models")

    assert response.status_code == 200
    assert response.json()["tokenizer_version"] == TOKENIZER_VERSION
