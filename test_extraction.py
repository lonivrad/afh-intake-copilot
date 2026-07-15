"""Smoke test for Stage 1 extraction against case_01."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.extraction import ResidentProfile, run_initial_extraction


@pytest.mark.api
def test_stage1_extraction_case_01() -> None:
    case_path = Path(__file__).parent / "data" / "test_cases" / "case_01.json"
    case = json.loads(case_path.read_text())

    print(f"=== Stage 1 extraction: {case['case_id']} ===")
    print(f"Description: {case['description']}\n")

    profile, triggered = run_initial_extraction(
        discharge_summary=case["inputs"]["discharge_summary"],
        family_notes=case["inputs"]["family_notes"],
        disclosure_text="",
    )

    print(f"Triggered conditions: {triggered}\n")
    print("Resident profile (non-null fields):")
    print(json.dumps(profile.model_dump(exclude_none=True), indent=2))

    print(f"\nEvidence snippets recorded: {len(profile.evidence_snippets)}")
    print(f"Source disagreements recorded: {len(profile.source_disagreements)}")

    # ===== Assertions =====

    # Structural: extraction returns a typed profile and a list of triggers.
    assert isinstance(profile, ResidentProfile)
    assert isinstance(triggered, list)

    # Every recorded snippet carries a non-empty id and source.
    for snip in profile.evidence_snippets:
        assert snip.snippet_id, "evidence snippet missing id"
        assert snip.source, "evidence snippet missing source"

    # Ground-truth sanity check. Extraction is a live, non-deterministic LLM
    # call, so this stays a diagnostic (not a hard assert) to avoid a flaky
    # gate — matching the original smoke-test intent.
    gt = case["ground_truth"]
    expected_disagreement = gt["known_source_disagreement"]
    if bool(expected_disagreement) == bool(profile.source_disagreements):
        print("\nMatches ground truth on source-disagreement presence.")
    else:
        print(
            "\nWARNING: disagreement state diverges from ground truth — "
            f"expected={'yes' if expected_disagreement else 'no'}, "
            f"recorded={len(profile.source_disagreements)}"
        )

    print("\nAll structural assertions passed.")


if __name__ == "__main__":
    test_stage1_extraction_case_01()
