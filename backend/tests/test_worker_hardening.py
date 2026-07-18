from app.services.job_errors import classify_error, retry_delay


def test_retry_backoff_and_classification():
    assert [retry_delay(value) for value in (1, 2, 3, 4)] == [10, 30, 90, 90]
    assert classify_error(TimeoutError())[0] is True
    assert classify_error(FileNotFoundError())[0] is False
    assert classify_error(ValueError())[0] is False
