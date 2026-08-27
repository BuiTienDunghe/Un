"""The memory e2e eval's contract, pinned in the suite (memory_design.md §13.4).

Three things this asserts, and why each is load-bearing:
- attrib-03 / attrib-04 PASS: the acceptance tests of 0c — member- and
  guild-isolation on the answer path. If these regress, the read-path leak
  is back.
- contra-01 / guard-02 KNOWN-FAIL: the guard measurably accepts a fact that
  contradicts its source. These rows MUST keep failing until job 4 replaces
  fact_overlap; the day they flip to FIXED is the day auto-apply may return.
- guard-03 PASS: the guard's positive duty — a true, well-evidenced fact is
  accepted. Any future verifier must not regress this while fixing the two
  above.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.postgres.database import create_postgres_engine, create_session_factory
from scripts.memory_e2e_eval import FIXTURE, run_case

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")

EXPECTED_STATUS = {
    "attrib-03": "PASS",
    "attrib-04": "PASS",
    "contra-01": "KNOWN-FAIL",
    "guard-02": "KNOWN-FAIL",
    "guard-03": "PASS",
}


def test_e2e_fixture_has_no_unexpected_failures():
    factory = create_session_factory(create_postgres_engine(str(URL)))
    prefix = f"e2e-test-{uuid4().hex[:8]}"
    cases = [
        json.loads(line)
        for line in Path(FIXTURE).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(cases) == 21

    statuses: dict[str, str] = {}
    for case in cases:
        status, problems = run_case(factory, prefix, case, keep=False)
        statuses[case["id"]] = status
        assert status != "FAIL", f"{case['id']}: {problems}"

    for case_id, expected in EXPECTED_STATUS.items():
        assert statuses[case_id] == expected, (
            f"{case_id} = {statuses[case_id]}, hợp đồng đòi {expected} — nếu một "
            "hàng KNOWN-FAIL vừa thành FIXED thì việc 4 đã hạ cánh: cập nhật "
            "EXPECTED_STATUS và mở lại tự-áp-dụng theo ngưỡng §13.4."
        )
