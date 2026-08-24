"""The eval's latency summary: report-only numbers the operating machine reads.

The percentile convention is nearest-rank, matching how the P4-3 measurements
were taken by hand (82 cases -> p95 is the 78th sorted value).
"""
from scripts.evaluate_rag import latency_summary


def _results(values: list[int | None]) -> list[dict[str, object]]:
    return [{"latency_ms": value} for value in values]


def test_latency_summary_nearest_rank_over_82_cases():
    # 82 distinct values 1..82: p50 = ceil(41.0) = 41st value, p95 = ceil(77.9) = 78th.
    summary = latency_summary(_results(list(range(1, 83))))

    assert summary == {"measured": 82, "p50_latency_ms": 41, "p95_latency_ms": 78, "max_latency_ms": 82}


def test_latency_summary_max_sees_the_one_slow_case_p95_misses():
    """The rebuild hang is a single slow case; p95 over 82 must not hide it from max."""
    values = [600] * 81 + [27000]
    summary = latency_summary(_results(values))

    assert summary["p95_latency_ms"] == 600
    assert summary["max_latency_ms"] == 27000


def test_latency_summary_reports_partial_coverage_and_skips_failed_cases():
    summary = latency_summary(_results([100, None, 300]))

    assert summary["measured"] == 2  # a partial run must be visible as partial
    assert summary["p50_latency_ms"] == 100 and summary["max_latency_ms"] == 300


def test_latency_summary_is_none_when_nothing_was_measured():
    assert latency_summary(_results([None, None])) is None
    assert latency_summary([]) is None
