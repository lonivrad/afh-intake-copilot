"""Test B: Distribution sanity check across all 8 cases.

Runs the decision layer once per cached case and prints the count of
each recommendation type. Sanity assertion: not all 8 cases get the
same recommendation. If they do, the prompt needs revision before UI
integration.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pipeline.extraction import (
    EvidenceSnippet,
    ResidentProfile,
    SourceDisagreement,
)
from pipeline.synthesis import generate_intake_decision


def _reconstruct_profile(meta: dict) -> ResidentProfile:
    return ResidentProfile(
        evidence_snippets=[
            EvidenceSnippet(
                snippet_id=sid,
                source="discharge",
                claim="(reconstructed for decision-layer test)",
                verbatim_text="(reconstructed for decision-layer test)",
            )
            for sid in meta.get("valid_snippet_ids", [])
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


def main() -> None:
    results = json.loads(
        Path("evals/results/results_full.json").read_text()
    )

    print("=== Decision-layer distribution test ===\n")
    print(
        f"{'case':<10} {'recommendation':<22} "
        f"{'#conds':>7} {'#tps':>5} {'#refs':>6} {'gaps_h':>7} {'gaps_m':>7} {'gaps_l':>7}"
    )
    print("-" * 80)

    recommendations: list[str] = []
    for entry in results:
        if "score" not in entry:
            continue
        cid = entry["case"]["case_id"]
        output = entry["output"]

        profile = _reconstruct_profile(output["_meta"])
        decision = generate_intake_decision(
            care_plan=output["care_plan"],
            acuity_factor_recommendations=output[
                "acuity_factor_recommendations"
            ],
            risk_register=output["risk_register"],
            profile=profile,
        )
        rec = decision["recommendation"]
        recommendations.append(rec)

        sev_counts = Counter(
            g.get("severity") for g in output["risk_register"]["gaps"]
        )
        print(
            f"{cid:<10} {rec:<22} "
            f"{len(decision['conditions_before_admission']):>7} "
            f"{len(decision['family_call_talking_points']):>5} "
            f"{len(decision['evidence_references']):>6} "
            f"{sev_counts.get('high', 0):>7} "
            f"{sev_counts.get('medium', 0):>7} "
            f"{sev_counts.get('low', 0):>7}"
        )

    print("-" * 80)
    dist = Counter(recommendations)
    print(
        f"Distribution: accept={dist['accept']}, "
        f"accept_with_conditions={dist['accept_with_conditions']}, "
        f"hold_for_review={dist['hold_for_review']}"
    )

    # Sanity check: not all cases get the same recommendation
    unique_recs = set(recommendations)
    if len(unique_recs) == 1:
        print(
            f"\nSANITY-CHECK FAILED: all {len(recommendations)} cases got "
            f"the same recommendation ({recommendations[0]}). The prompt "
            "needs revision before UI integration."
        )
        raise SystemExit(1)

    print(
        f"\nSanity check passed: {len(unique_recs)} distinct recommendation "
        f"types across {len(recommendations)} cases."
    )


if __name__ == "__main__":
    main()
