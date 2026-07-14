from __future__ import annotations

from difflib import SequenceMatcher


def _distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, expected in enumerate(reference, start=1):
        current = [i]
        for j, actual in enumerate(hypothesis, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (expected != actual)))
        previous = current
    return previous[-1]


def evaluate_ocr(reference: str, actual: str) -> dict[str, object]:
    reference_chars, actual_chars = list(reference), list(actual)
    reference_words, actual_words = reference.split(), actual.split()
    char_distance = _distance(reference_chars, actual_chars)
    word_distance = _distance(reference_words, actual_words)
    matcher = SequenceMatcher(a=reference, b=actual)
    changes = [{"kind": kind, "reference": reference[i1:i2], "actual": actual[j1:j2]} for kind, i1, i2, j1, j2 in matcher.get_opcodes() if kind != "equal"]
    return {
        "cer": char_distance / max(1, len(reference_chars)),
        "wer": word_distance / max(1, len(reference_words)),
        "character_accuracy": max(0.0, 1 - char_distance / max(1, len(reference_chars))),
        "word_accuracy": max(0.0, 1 - word_distance / max(1, len(reference_words))),
        "changes": changes,
    }
