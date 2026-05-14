"""Test A: Decision layer on case_04.

Loads case_04's cached Stage 3 outputs from evals/results/results_full.json
(to avoid re-running 3 synthesis calls) and reconstructs a minimal
ResidentProfile from the cached snippet IDs and source-disagreement count.
The decision layer then runs against those four artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.extraction import (
    EvidenceSnippet,
    ResidentProfile,
    SourceDisagreement,
)
from pipeline.synthesis import generate_intake_decision


def main() -> None:
    results = json.loads(
        Path("evals/results/results_full.json").read_text()
    )
    entry = next(e for e in results if e["case"]["case_id"] == "case_04")
    output = entry["output"]
    meta = output["_meta"]

    # Reconstruct minimal profile from cached metadata. We don't have the
    # original verbatim_text or claim back, but we have the snippet IDs
    # the decision layer needs to validate against.
    snippet_ids = meta.get("valid_snippet_ids", [])
    profile = ResidentProfile(
        evidence_snippets=[
            EvidenceSnippet(
                snippet_id=sid,
                source="discharge",
                claim="(reconstructed for decision-layer test)",
                verbatim_text="(reconstructed for decision-layer test)",
            )
            for sid in snippet_ids
        ],
        source_disagreements=[
            SourceDisagreement(
                field=f"reconstructed_disagreement_{i}",
                discharge_claim=None,
                family_claim=None,
                evidence_snippet_ids=[],
            )
            for i in range(meta.get("source_disagreement_count", 0))
        ],
    )

    print(f"=== Decision-layer test: case_04 ===")
    print(
        f"Inputs: care_plan sections, "
        f"{len(output['acuity_factor_recommendations']['recommendations'])} acuity recs, "
        f"{len(output['risk_register']['gaps'])} risk-register gaps, "
        f"{len(profile.evidence_snippets)} snippet IDs, "
        f"{len(profile.source_disagreements)} disagreements\n"
    )

    decision = generate_intake_decision(
        care_plan=output["care_plan"],
        acuity_factor_recommendations=output["acuity_factor_recommendations"],
        risk_register=output["risk_register"],
        profile=profile,
    )

    print(json.dumps(decision, indent=2))

    # ===== Assertions =====

    assert decision["recommendation"] in {
        "accept",
        "accept_with_conditions",
        "hold_for_review",
    }, f"invalid recommendation: {decision['recommendation']}"

    assert 1 <= len(decision["conditions_before_admission"]) <= 5
    assert 1 <= len(decision["family_call_talking_points"]) <= 5
    assert len(decision["evidence_references"]) >= 1

    valid_snippet_ids = {s.snippet_id for s in profile.evidence_snippets}
    valid_factor_ids = {
        r["acuity_factor_id"]
        for r in output["acuity_factor_recommendations"]["recommendations"]
    }
    n_gaps = len(output["risk_register"]["gaps"])
    valid_gap_ids = {f"gap_{i:02d}" for i in range(n_gaps)}

    for ref in decision["evidence_references"]:
        rt, rid = ref["ref_type"], ref["ref_id"]
        if rt == "snippet":
            assert (
                rid in valid_snippet_ids
            ), f"unknown snippet ref: {rid}"
        elif rt == "acuity_factor":
            assert (
                rid in valid_factor_ids
            ), f"unknown acuity_factor ref: {rid}"
        elif rt == "risk_register_entry":
            assert (
                rid in valid_gap_ids
            ), f"unknown risk_register_entry ref: {rid}"

    # case_04 cached output had at least one high-severity gap (insulin
    # admin) — the deterministic logic should yield hold_for_review or at
    # minimum not accept.
    has_high = any(
        g.get("severity") == "high"
        for g in output["risk_register"]["gaps"]
    )
    if has_high:
        assert decision["recommendation"] != "accept", (
            "high-severity gap present; should not be a clean accept"
        )

    print("\nAll assertions passed.")


if __name__ == "__main__":
    main()
