"""The memory e2e eval's contract, pinned in the suite (memory_design.md §13.4).

Three things this asserts, and why each is load-bearing:
- attrib-03 / attrib-04 PASS: the acceptance tests of 0c — member- and
  guild-isolation on the answer path. If these regress, the read-path leak
  is back.
- contra-01 / guard-02 FIXED (27/08, job 4): the negation-clause and
  min-two-content-words rules close the two measured holes — zero-cost on
  the 75-case benchmark (coverage 96.7% / poison 21.6% unchanged). FIXED is
  now load-bearing: a regression here reopens §9.1. Auto-apply itself stays
  off until the --with-extractor benchmark clears the §13.4 thresholds.
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
    "contra-01": "FIXED",
    "guard-02": "FIXED",
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
