"""Unit tests for the read-only PC matching audit."""

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_pevm_matching.py"
SPEC = importlib.util.spec_from_file_location("audit_pevm_matching", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_classify_candidate_scores_matches_worker_confidence_rules():
    assert audit.classify_candidate_scores("", 0.99, 0.1) == "not_found"
    assert audit.classify_candidate_scores("1", 0.95, 0.94) == "confident"
    assert audit.classify_candidate_scores("1", 0.92, 0.86) == "confident"
    assert audit.classify_candidate_scores("1", 0.92, 0.90) == "manual_review"
