"""scripts.passage_drift: which pair it compares, and the numbers the three-tier drift rule reads."""
from __future__ import annotations

import pytest

from scripts import passage_drift


def test_no_arguments_is_the_27_10_pair_so_that_run_stays_reproducible():
    assert passage_drift.arguments([]) == ("documents_drill_heldout", "documents_drill_heldout_qi", "http://127.0.0.1:6333")


def test_the_new_bases_are_named_on_the_command_line():
    assert passage_drift.arguments(["documents_lab_r2", "documents_lab_r2_qi"]) == ("documents_lab_r2", "documents_lab_r2_qi", "http://127.0.0.1:6333")
    assert passage_drift.arguments(["documents_drill_heldout_r2", "documents_drill_heldout_r2_qi", "http://qdrant:6333/"]) == (
        "documents_drill_heldout_r2", "documents_drill_heldout_r2_qi", "http://qdrant:6333")


@pytest.mark.parametrize("argv", [["http://127.0.0.1:6333"], ["a", "b", "c", "d"]])
def test_one_argument_is_refused_rather_than_read_as_a_collection(argv):
    with pytest.raises(SystemExit, match="usage"):
        passage_drift.arguments(argv)


def test_report_pairs_by_id_and_counts_only_the_intersection():
    v0 = {"a": [1.0, 0.0], "b": [0.0, 1.0], "only-v0": [1.0, 1.0]}
    qi = {"a": [2.0, 0.0], "b": [1.0, 1.0], "only-qi": [1.0, 0.0]}
    lines = passage_drift.report(v0, qi)
    assert lines[0] == "qi points 3 · paired with v0 2 · unpaired 1"
    assert lines[1].startswith(f"cosine min {1 / 2 ** 0.5:.8f}")       # b: 45 degrees apart
    assert lines[2] == "below 0.999999: 1"                               # a is identical up to scale
