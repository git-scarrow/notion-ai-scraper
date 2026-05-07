from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lab_query_contract import validate_count_answer
from tool_catalog import (
    SCOPE_LABELS,
    lab_query_catalog_payload,
    tools_safe_for_lab_query,
)


def test_compliant_answer_passes():
    text = "Work Items: 581 exact total; Dispatch Ready: 22 matched count."
    result = validate_count_answer(text)
    assert result["ok"], result
    assert "exact total" in result["scope_labels_found"]
    assert "matched count" in result["scope_labels_found"]


def test_unlabeled_total_warns():
    text = "Work Items: 581 total."
    result = validate_count_answer(text)
    assert not result["ok"]
    assert any("581 total" in w for w in result["warnings"])


def test_scanned_count_phrase_passes():
    text = "Status distribution over 200 scanned count of Work Items: Done 115 items."
    result = validate_count_answer(text)
    assert result["ok"], result
    assert "scanned count" in result["scope_labels_found"]


def test_limit_label_passes():
    text = "Returning the first limit 50 rows; not a database total."
    result = validate_count_answer(text)
    assert result["ok"], result


def test_mixed_compliance_warns_only_on_offender():
    text = (
        "Work Items: 581 exact total across the database. "
        "Separately, the dashboard widget showed approximately 12 matches "
        "without any provenance, which we are quoting unverified."
    )
    result = validate_count_answer(text)
    assert not result["ok"]
    assert any("12 matches" in w for w in result["warnings"])
    assert "exact total" in result["scope_labels_found"]


def test_empty_text_ok():
    assert validate_count_answer("")["ok"]
    assert validate_count_answer("   ")["ok"]


def test_non_count_prose_ok():
    text = "The Lab Query agent is read-only and prefers canonical tools."
    assert validate_count_answer(text)["ok"]


def test_catalog_payload_shape():
    payload = lab_query_catalog_payload()
    assert set(payload) == {
        "safe_for_lab_query",
        "canonical_reads",
        "requires_approval",
        "scope_labels",
    }
    assert payload["scope_labels"] == list(SCOPE_LABELS)
    assert "count_database" in payload["safe_for_lab_query"]
    assert "count_database" in payload["canonical_reads"]
    assert "update_agent" in payload["requires_approval"]
    assert "update_agent" not in payload["safe_for_lab_query"]


def test_tools_safe_for_lab_query_excludes_writes():
    safe = set(tools_safe_for_lab_query())
    for forbidden in ("update_agent", "set_agent_config_raw", "chat_with_agent"):
        assert forbidden not in safe


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
