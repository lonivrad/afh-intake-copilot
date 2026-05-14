"""Smoke test for the single-call baseline against case_04.

Uses the same mock disclosure as test_synthesis.py (imported from there) so
that Step 10's baseline-vs-pipeline comparison sees identical inputs.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.baseline import run_baseline
from test_synthesis import MOCK_DISCLOSURE


def main() -> None:
    case = json.loads(Path("data/test_cases/case_04.json").read_text())
    dshs_rules = json.loads(Path("data/dshs_rules.json").read_text())
    valid_factor_ids = {f["acuity_factor_id"] for f in dshs_rules["factors"]}

    print(f"=== Baseline single-call test: {case['case_id']} ===")
    print(f"Description: {case['description']}\n")

    out = run_baseline(
        discharge_summary=case["inputs"]["discharge_summary"],
        family_notes=case["inputs"]["family_notes"],
        disclosure_text=MOCK_DISCLOSURE,
        dshs_rules=dshs_rules,
    )

    print(json.dumps(out, indent=2))
    print()

    # ===== Assertions =====

    # Top-level structure mirrors the staged pipeline's three artifacts
    assert isinstance(out, dict)
    assert set(out.keys()) >= {
        "care_plan",
        "acuity_factor_recommendations",
        "risk_register",
    }, f"missing required top-level keys; got {set(out.keys())}"

    # No billing-code or billable language anywhere
    all_str = json.dumps(out).lower()
    assert (
        "billing code" not in all_str
    ), "output contains forbidden phrase 'billing code'"
    assert (
        "billable" not in all_str
    ), "output contains forbidden phrase 'billable'"

    # Acuity factor IDs must come from the catalog
    rec_factor_ids = [
        r["acuity_factor_id"]
        for r in out["acuity_factor_recommendations"]["recommendations"]
    ]
    for fid in rec_factor_ids:
        assert fid in valid_factor_ids, f"invalid factor id: {fid}"

    # Diagnostic (not enforced): case_04 has no documented fall history, so
    # CARE-FALL-RISK appearing here is a baseline-mode false positive —
    # exactly the kind of behavior Step 10 should compare against the staged
    # pipeline. Surface as a warning so the trace is visible without failing
    # the "confirm it runs" smoke test.
    if "CARE-FALL-RISK" in rec_factor_ids:
        print(
            "DIAGNOSTIC: baseline recommended CARE-FALL-RISK without documented "
            "fall-risk evidence in case_04 — likely a single-call false positive."
        )

    # Care-plan items have non-empty evidence_snippet_ids
    plan = out["care_plan"]
    plan_section_names = (
        "diabetes_care",
        "dementia_care",
        "fall_risk_care",
        "adl_support",
        "medication_management",
    )
    plan_item_total = 0
    for section in plan_section_names:
        for item in plan.get(section, []):
            plan_item_total += 1
            assert (
                len(item["evidence_snippet_ids"]) >= 1
            ), f"plan item in {section} has no evidence"
            # Bare IDs only — no compound strings like "DS1: '...'"
            for eid in item["evidence_snippet_ids"]:
                assert ":" not in eid and "'" not in eid and '"' not in eid, (
                    f"plan item in {section} has compound snippet id (expected bare ID): "
                    f"{eid!r}"
                )

    # Diagnostic (not enforced): fall_risk_care should be empty for case_04.
    # If the baseline filled it, log it as a single-call false positive.
    if len(plan.get("fall_risk_care", [])) > 0:
        print(
            f"DIAGNOSTIC: baseline populated fall_risk_care with "
            f"{len(plan['fall_risk_care'])} item(s) despite no fall-risk evidence "
            "in case_04 — single-call false positive."
        )

    # Risk register: gaps have evidence and valid severity
    for gap in out["risk_register"]["gaps"]:
        assert (
            len(gap["evidence_snippet_ids"]) >= 1
        ), f"gap has no evidence: {gap['resident_need'][:80]}"
        assert gap["severity"] in {"low", "medium", "high"}

    # Should recommend at least one obviously-applicable factor for case_04
    obvious = {"CARE-INSULIN-BGM", "CARE-BEHAV-DEMENTIA", "CARE-COG-IMPAIR"}
    assert obvious & set(rec_factor_ids), (
        f"missing obvious factors for diabetes+dementia case; "
        f"expected at least one of {obvious}, got {rec_factor_ids}"
    )

    print(
        f"\nSummary: care_plan_items={plan_item_total}, "
        f"acuity_recs={len(out['acuity_factor_recommendations']['recommendations'])}, "
        f"capability_gaps={len(out['risk_register']['gaps'])}"
    )
    print("All assertions passed.")


if __name__ == "__main__":
    main()
