"""The memory e2e eval's contract, pinned in the suite (memory_design.md §13.4).

Three things this asserts, and why each is load-bearing:
- attrib-04 PASS: the privacy boundary — GUILD isolation on the answer path
  (§3.2). If it regresses, the cross-guild leak is back.
- attrib-03 PASS: guild-wide injection (28/08, step 4) — A's member fact MUST
  appear in B's context within the same guild. A regression means the read
  was re-narrowed to the asker and both observed production uses (asking
  about another member; recalling what someone said about you) broke again.
  Member-level isolation inside a guild is intentionally GONE.
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
    # Job 2 (28/08): FTS history search over sổ gốc — verbatim recall beats
    # six distractors in top-5 (the §13.4 ship gate for search_history).
    "recall-verbatim-01": "PASS",
    "recall-verbatim-02": "PASS",
    # The dense tripwire fails deterministically by design — it flips FIXED
    # only when a dense retriever lands (§13.3 threshold pair).
    "recall-para-02": "KNOWN-FAIL",
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
