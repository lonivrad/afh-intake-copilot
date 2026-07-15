"""Decision layer on case_04.

Split into two tests:

- test_decision_plumbing_case_04_offline / test_decision_rejects_invalid_output_offline
  run OFFLINE with a mocked Anthropic client. They assert only on what the
  decision layer's own Python computes from the inputs — the gap_id sequence it
  injects, the profile summary it reconstructs from the cached _meta, and the
  fact that the Pydantic parse of the tool output actually runs. They do NOT
  re-assert the canned values fed to the mock; every assertion here would fail
  if the corresponding plumbing were removed.

- test_decision_behavior_case_04 is the model-judgment test (valid evidence
  references, high-severity gap => not a clean accept). It makes a live API
  call and is marked `api`, so it only runs with ANTHROPIC_API_KEY set.

Inputs come from case_04's cached Stage 3 outputs in
evals/results/results_full.json to avoid re-running synthesis.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import pipeline.synthesis as synthesis
from pipeline.extraction import (
    EvidenceSnippet,
    ResidentProfile,
    SourceDisagreement,
)
from pipeline.synthesis import generate_intake_decision


def _load_case(case_id: str) -> dict:
    results = json.loads(Path("evals/results/results_full.json").read_text())
    return next(e for e in results if e["case"]["case_id"] == case_id)


def reconstruct_profile(meta: dict) -> ResidentProfile:
    """Rebuild a minimal ResidentProfile from cached metadata. We don't have
    the original verbatim_text/claim, but we have the snippet IDs and the
    source-disagreement count the decision layer reasons over."""
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


# ---------------------------------------------------------------------------
# Offline mock: a stand-in Anthropic client that captures the request the
# decision layer builds and returns a caller-supplied tool payload.
# ---------------------------------------------------------------------------


class _ToolUseBlock:
    type = "tool_use"

    def __init__(self, tool_input: dict) -> None:
        self.input = tool_input


class _Response:
    def __init__(self, content: list) -> None:
        self.content = content


class _CapturingClient:
    """Records the kwargs passed to messages.create and returns a fixed tool
    payload, so tests can inspect what the decision layer actually sent."""

    def __init__(self, tool_input: dict) -> None:
        self._tool_input = tool_input
        self.last_create_kwargs: dict | None = None

    @property
    def messages(self) -> "_CapturingClient":
        return self

    def create(self, **kwargs) -> _Response:
        self.last_create_kwargs = kwargs
        return _Response([_ToolUseBlock(self._tool_input)])


def _valid_decision_payload() -> dict:
    """A schema-valid IntakeDecision payload. Its *values* are arbitrary and
    are never asserted on — only that the layer parses and returns them."""
    return {
        "recommendation": "accept_with_conditions",
        "rationale": "canned rationale for offline plumbing test",
        "conditions_before_admission": ["canned condition"],
        "family_call_talking_points": ["canned talking point"],
        "evidence_references": [{"ref_type": "snippet", "ref_id": "CANNED"}],
    }


def _sent_user_content(client: _CapturingClient) -> str:
    assert client.last_create_kwargs is not None, "messages.create was never called"
    return client.last_create_kwargs["messages"][0]["content"]


def test_decision_plumbing_case_04_offline(monkeypatch) -> None:
    entry = _load_case("case_04")
    output = entry["output"]
    meta = output["_meta"]
    profile = reconstruct_profile(meta)

    client = _CapturingClient(_valid_decision_payload())
    monkeypatch.setattr(synthesis, "_client", lambda: client)

    result = generate_intake_decision(
        care_plan=output["care_plan"],
        acuity_factor_recommendations=output["acuity_factor_recommendations"],
        risk_register=output["risk_register"],
        profile=profile,
    )

    sent = _sent_user_content(client)

    # (A) gap_id injection: the layer annotates each risk-register gap with a
    # gap_NN id. Assert the exact sequence for this case's gap count appears in
    # the request, and that the layer does not fabricate an extra one. This
    # fails if the gap_id annotation loop is removed.
    n_gaps = len(output["risk_register"]["gaps"])
    assert n_gaps > 0, "fixture precondition: case_04 has risk-register gaps"
    for i in range(n_gaps):
        assert f"gap_{i:02d}" in sent, f"missing injected gap id gap_{i:02d}"
    assert f"gap_{n_gaps:02d}" not in sent, "layer injected more gap ids than gaps"

    # (B) profile-summary reconstruction: the layer forwards the profile's
    # evidence snippet ids. Assert every id derived from the cached _meta made
    # it into the request. Fails if profile_summary construction is gutted.
    snippet_ids = meta["valid_snippet_ids"]
    assert snippet_ids, "fixture precondition: case_04 has snippet ids"
    for sid in snippet_ids:
        assert sid in sent, f"snippet id {sid} not forwarded to the model"

    # (C) the Pydantic parse actually ran and shaped the return value: the
    # result is a plain dict carrying exactly the IntakeDecision fields.
    assert isinstance(result, dict)
    assert set(result.keys()) == {
        "recommendation",
        "rationale",
        "conditions_before_admission",
        "family_call_talking_points",
        "evidence_references",
    }


def test_decision_rejects_invalid_output_offline(monkeypatch) -> None:
    """Proves the IntakeDecision.model_validate step is real plumbing, not
    decoration: an empty conditions_before_admission violates min_length=1, so
    the layer must reject it rather than pass the raw tool output through."""
    entry = _load_case("case_04")
    output = entry["output"]
    profile = reconstruct_profile(output["_meta"])

    bad_payload = _valid_decision_payload()
    bad_payload["conditions_before_admission"] = []  # violates min_length=1
    monkeypatch.setattr(
        synthesis, "_client", lambda: _CapturingClient(bad_payload)
    )

    with pytest.raises(ValidationError):
        generate_intake_decision(
            care_plan=output["care_plan"],
            acuity_factor_recommendations=output[
                "acuity_factor_recommendations"
            ],
            risk_register=output["risk_register"],
            profile=profile,
        )


@pytest.mark.api
def test_decision_behavior_case_04() -> None:
    entry = _load_case("case_04")
    output = entry["output"]
    profile = reconstruct_profile(output["_meta"])

    decision = generate_intake_decision(
        care_plan=output["care_plan"],
        acuity_factor_recommendations=output["acuity_factor_recommendations"],
        risk_register=output["risk_register"],
        profile=profile,
    )

    print(json.dumps(decision, indent=2))

    assert decision["recommendation"] in {
        "accept",
        "accept_with_conditions",
        "hold_for_review",
    }, f"invalid recommendation: {decision['recommendation']}"

    assert 1 <= len(decision["conditions_before_admission"]) <= 5
    assert 1 <= len(decision["family_call_talking_points"]) <= 5
    assert len(decision["evidence_references"]) >= 1

    # Every evidence reference must cite an id that actually exists in the
    # inputs — a real check on the live model's grounding.
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
            assert rid in valid_snippet_ids, f"unknown snippet ref: {rid}"
        elif rt == "acuity_factor":
            assert rid in valid_factor_ids, f"unknown acuity_factor ref: {rid}"
        elif rt == "risk_register_entry":
            assert rid in valid_gap_ids, f"unknown risk_register_entry ref: {rid}"

    # case_04's cached output had at least one high-severity gap (insulin
    # admin) — the decision logic should not return a clean accept.
    has_high = any(
        g.get("severity") == "high" for g in output["risk_register"]["gaps"]
    )
    if has_high:
        assert decision["recommendation"] != "accept", (
            "high-severity gap present; should not be a clean accept"
        )


if __name__ == "__main__":
    test_decision_behavior_case_04()
