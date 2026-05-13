"""Smoke test for Stage 1 extraction against case_01."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.extraction import run_initial_extraction


def main() -> None:
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

    # Ground-truth sanity check
    gt = case["ground_truth"]
    expected_disagreement = gt["known_source_disagreement"]
    if expected_disagreement is None and not profile.source_disagreements:
        print("\nMatches ground truth: no source disagreement expected, none recorded.")
    elif expected_disagreement is not None and profile.source_disagreements:
        print("\nMatches ground truth: disagreement expected and recorded.")
    else:
        print(
            "\nWARNING: disagreement state diverges from ground truth — "
            f"expected={'yes' if expected_disagreement else 'no'}, "
            f"recorded={len(profile.source_disagreements)}"
        )


if __name__ == "__main__":
    main()
