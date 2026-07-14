from time import perf_counter


def elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)
