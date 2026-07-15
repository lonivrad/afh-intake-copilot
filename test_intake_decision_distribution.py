"""Distribution check across all cached cases.

- test_decision_plumbing_all_cases_offline runs OFFLINE with a mocked client
  and asserts the per-case plumbing (gap_id injection reflecting each case's own
  gap count, schema-valid return) across every cached case. It never asserts the
  canned mock values.

- test_decision_distribution_behavior is the model-judgment test: run the live
  decision layer once per cached case and confirm not all cases collapse to the
  same recommendation. Marked `api`; runs only with ANTHROPIC_API_KEY set.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

import pipeline.synthesis as synthesis
from pipeline.synthesis import generate_intake_decision
from test_intake_decision import (
    _CapturingClient,
    _sent_user_content,
    _valid_decision_payload,
    reconstruct_profile,
)


def _scored_cases() -> list[dict]:
    results = json.loads(Path("evals/results/results_full.json").read_text())
    return [e for e in results if "score" in e]


def test_decision_plumbing_all_cases_offline(monkeypatch) -> None:
    cases = _scored_cases()
    assert len(cases) >= 2, "fixture precondition: multiple cached cases"

    for entry in cases:
        cid = entry["case"]["case_id"]
        output = entry["output"]
        profile = reconstruct_profile(output["_meta"])

        client = _CapturingClient(_valid_decision_payload())
        monkeypatch.setattr(synthesis, "_client", lambda c=client: c)

        result = generate_intake_decision(
            care_plan=output["care_plan"],
            acuity_factor_recommendations=output[
                "acuity_factor_recommendations"
            ],
            risk_register=output["risk_register"],
            profile=profile,
        )

        sent = _sent_user_content(client)

        # gap_id injection must reflect THIS case's own gap count — a per-case
        # property computed by the layer, not a canned value.
        n_gaps = len(output["risk_register"]["gaps"])
        for i in range(n_gaps):
            assert f"gap_{i:02d}" in sent, f"{cid}: missing gap_{i:02d}"
        assert f"gap_{n_gaps:02d}" not in sent, f"{cid}: extra gap id injected"

        # The layer parsed the tool output into the IntakeDecision shape.
        assert set(result.keys()) == {
            "recommendation",
            "rationale",
            "conditions_before_admission",
            "family_call_talking_points",
            "evidence_references",
        }


@pytest.mark.api
def test_decision_distribution_behavior() -> None:
    cases = _scored_cases()

    recommendations: list[str] = []
    for entry in cases:
        output = entry["output"]
        profile = reconstruct_profile(output["_meta"])
        decision = generate_intake_decision(
            care_plan=output["care_plan"],
            acuity_factor_recommendations=output[
                "acuity_factor_recommendations"
            ],
            risk_register=output["risk_register"],
            profile=profile,
        )
        recommendations.append(decision["recommendation"])

    dist = Counter(recommendations)
    print(
        f"Distribution: accept={dist['accept']}, "
        f"accept_with_conditions={dist['accept_with_conditions']}, "
        f"hold_for_review={dist['hold_for_review']}"
    )

    # Sanity check: not all cases get the same recommendation. If they do, the
    # prompt needs revision before UI integration.
    unique_recs = set(recommendations)
    assert len(unique_recs) > 1, (
        f"all {len(recommendations)} cases got the same recommendation "
        f"({recommendations[0]}); the prompt needs revision."
    )


if __name__ == "__main__":
    test_decision_distribution_behavior()
