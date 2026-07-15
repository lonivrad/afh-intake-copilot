"""Tests for InterviewSession.

Two tests:

- test_interview_state_machine_offline runs FULLY OFFLINE. It walks the
  fall_risk tree with answers crafted to be handled entirely by the local
  parser (exact enum tokens, digit numerics, plain yes/no), so it exercises the
  deterministic state machine — a branch taken, a branch skipped, nested-path
  updates, and the numeric_or_null null case — without any API call. The client
  is swapped for a stand-in that raises on any fallback, and the test asserts
  _fallback_parse_count == 0 as proof it never went live.

- test_interview_full_walk_case_04 is the richer case_04 (diabetes + dementia)
  walk with deliberately conversational answers. 10 of its 22 answers require
  the LLM to map natural language to canonical enums (e.g. "...basal-bolus
  regimen." -> basal_bolus), so it is a behavioral test marked `api` and only
  runs with ANTHROPIC_API_KEY set.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.extraction import (
    ConditionsPresent,
    DementiaProfile,
    Demographics,
    DiabetesProfile,
    EvidenceSnippet,
    ResidentProfile,
    SourceDisagreement,
)
from pipeline.interview import InterviewSession


class _NoApiClient:
    """Stand-in for the Anthropic client that makes any fallback parse fail
    loudly instead of silently issuing a live (billable) API call. Used by the
    offline test: if a crafted answer ever trips the LLM fallback, this turns
    that drift into an immediate test failure rather than a surprise charge."""

    def __getattr__(self, _name: str):
        raise AssertionError(
            "InterviewSession attempted a live API fallback parse; the offline "
            "test's answers must all be handled by the local parser."
        )


def _diabetes_node(node_id: str) -> dict:
    tree = json.loads(Path("data/trees/diabetes.json").read_text())
    return next(n for n in tree["nodes"] if n["node_id"] == node_id)


def test_interview_state_machine_offline() -> None:
    """Deterministic state-machine coverage with zero API calls.

    Walks the fall_risk tree. FALL_HISTORY_6MO=yes TAKES the fork into
    FALL_COUNT; MEDS_FALL_RISK=no SKIPS the (freetext) MEDS_FALL_RISK_CATEGORIES
    node; PT_HISTORY=none routes to END (skipping freetext PT_NOTES). All
    answers are locally parseable, so nothing goes live.
    """
    profile = ResidentProfile()
    session = InterviewSession(
        profile=profile, triggered_conditions=["fall_risk"]
    )
    # Any fallback to the API raises — the proof this test stays offline.
    session._client = _NoApiClient()

    answers = {
        "FALL_HISTORY_6MO": "yes",              # boolean True -> fork TAKEN
        "FALL_COUNT": "2",                       # digit numeric
        "FALL_CIRCUMSTANCES": "bedside_or_transfer",
        "FALL_OUTCOMES": "no_injury",
        "ASSISTIVE_DEVICE": "walker",
        "GAIT_STABILITY": "stable_with_device",
        "MEDS_FALL_RISK": "no",                  # boolean False -> fork SKIPPED
        "HOME_ACCOMMODATIONS": "grab_bars_bathroom",
        "PT_HISTORY": "none",                    # -> END (skips PT_NOTES)
    }

    visited: list[str] = []
    while True:
        node = session.get_next_question()
        if node is None:
            break
        nid = node["node_id"]
        visited.append(nid)
        session.submit_answer(answers[nid])

    # Fork TAKEN: FALL_HISTORY_6MO=yes opened the FALL_COUNT follow-up.
    assert "FALL_COUNT" in visited, "true-branch child was not visited"
    # Fork SKIPPED: MEDS_FALL_RISK=no bypassed the MEDS_FALL_RISK_CATEGORIES
    # freetext node, and PT_HISTORY=none bypassed PT_NOTES.
    assert "MEDS_FALL_RISK_CATEGORIES" not in visited, "skip branch was entered"
    assert "PT_NOTES" not in visited, "skip branch was entered"

    # Nested-path updates land on the right sub-objects.
    assert profile.fall_risk.history_6mo.any_falls is True
    assert profile.fall_risk.history_6mo.count == 2
    assert profile.fall_risk.assistive_device == "walker"
    assert profile.fall_risk.gait_stability == "stable_with_device"
    assert profile.fall_risk.medications.has_FRIDs is False
    assert profile.fall_risk.pt_history.status == "none"

    # numeric_or_null: the only such node (diabetes LAST_A1C) sits behind a
    # freetext node and is unreachable in a pure offline walk, so exercise its
    # parse path directly — still deterministic, still no fallback.
    a1c_node = _diabetes_node("LAST_A1C")
    assert session._parse_answer(a1c_node, "unknown") is None  # null case
    assert session._parse_answer(a1c_node, "7.8") == 7.8       # value case

    # Proof the whole test stayed offline.
    assert session._fallback_parse_count == 0, (
        f"expected zero API fallbacks, got {session._fallback_parse_count}"
    )


def build_starting_profile() -> ResidentProfile:
    """Mock Stage 1 output for case_04 to avoid a live extraction call."""
    return ResidentProfile(
        demographics=Demographics(
            age_range="70-79", resident_name_placeholder="Resident D"
        ),
        conditions_present=ConditionsPresent(
            diabetes=True, dementia=True, fall_risk=False
        ),
        medications=[
            "insulin (sliding-scale Humalog + glargine 30u HS)",
            "metformin 1000 mg BID",
            "donepezil",
            "sertraline 50 mg daily",
        ],
        diabetes=DiabetesProfile(),
        dementia=DementiaProfile(),
        evidence_snippets=[
            EvidenceSnippet(
                snippet_id="S1",
                claim="Insulin-dependent type 2 diabetes",
                source="discharge",
                verbatim_text=(
                    "type 2 diabetes mellitus, insulin-dependent for the past six years"
                ),
            ),
            EvidenceSnippet(
                snippet_id="S2",
                claim="Alzheimer's-type dementia diagnosis",
                source="discharge",
                verbatim_text=(
                    "Alzheimer's-type dementia diagnosed approximately four years ago"
                ),
            ),
        ],
        source_disagreements=[
            SourceDisagreement(
                field="dementia.orientation_level",
                discharge_claim="oriented to person and place but not time",
                family_claim="knows me but doesn't always know what day it is",
                evidence_snippet_ids=["S2"],
            )
        ],
    )


SIMULATED_ANSWERS = [
    # diabetes tree (10 nodes visited: type, insulin_use, regimen, admin,
    # oral_meds, bgm, a1c, hypo_history, hypo_severity, diet)
    "Type 2 diabetes, insulin-dependent.",
    "Yes she takes insulin.",
    "Sliding-scale Humalog before meals plus glargine at bedtime — basal-bolus regimen.",
    "Will need delegating RN at the AFH — daughter has been doing it but is burned out.",
    "Metformin 1000 mg twice daily.",
    "Four times a day, before each meal and bedtime.",
    "Seven point eight.",
    "Yes, two mild events in the past year.",
    "Mild — she treated them herself with juice.",
    "Carb-controlled.",
    # dementia tree (12 nodes visited: dx_status, dx_type, stage,
    # orientation, 4 behaviors, prior_placement, move_reason, primary_contact,
    # comm_pref)
    "Confirmed Alzheimer's disease.",
    "Alzheimer's.",
    "Moderate stage.",
    "She knows me and the building but not the time or date.",
    "Only at injection times — she gets agitated when she sees the needle.",
    "No, she does not try to leave.",
    "Not particularly.",
    "Physical resistance during injections only, otherwise gentle and pleasant.",
    "Home with my care as her daughter.",
    "Caregiver burnout — I cannot do four insulin shots a day anymore.",
    "Daughter, primary caregiver and responsible party. (placeholder)",
    "Weekly phone updates would be good.",
]


@pytest.mark.api
def test_interview_full_walk_case_04() -> None:
    profile = build_starting_profile()
    initial_evidence_count = len(profile.evidence_snippets)
    initial_disagreement_evidence = list(
        profile.source_disagreements[0].evidence_snippet_ids
    )

    session = InterviewSession(
        profile=profile,
        triggered_conditions=["diabetes", "dementia"],
    )

    print("=== InterviewSession test: case_04 (diabetes + dementia) ===")
    print(f"Trees loaded (in order): {[t['tree_id'] for t in session.trees]}")
    print(f"Starting evidence snippets: {initial_evidence_count}")
    print(f"Starting source disagreements: {len(profile.source_disagreements)}")
    print()

    answers_given = 0
    while True:
        node = session.get_next_question()
        if node is None:
            break
        if answers_given >= len(SIMULATED_ANSWERS):
            raise RuntimeError(
                f"Script exhausted but interview not complete; next question = {node['node_id']!r}"
            )
        answer = SIMULATED_ANSWERS[answers_given]
        session.submit_answer(answer)
        answers_given += 1
        print(
            f"Q{answers_given:2d}  {node['node_id']:<28}  "
            f"shape={node['expected_answer_shape']:<16}  "
            f"parsed={session._last_parsed_value!r:<32}  "
            f"via {session._last_parse_method}"
        )

    print(f"\nTotal questions answered: {answers_given}")
    total_parses = session._local_parse_count + session._fallback_parse_count
    local_pct = (
        100.0 * session._local_parse_count / total_parses
        if total_parses
        else 0.0
    )
    print(
        f"Parse methods: local={session._local_parse_count} ({local_pct:.0f}%), "
        f"fallback (Claude)={session._fallback_parse_count} ({100 - local_pct:.0f}%)"
    )
    print(
        f"Stage-2 API calls avoided by local parser: "
        f"{session._local_parse_count} of {total_parses}"
    )
    operator_snippets = [
        s for s in profile.evidence_snippets if s.source == "operator"
    ]
    print(
        f"Final evidence snippets: {len(profile.evidence_snippets)}  "
        f"(operator = {len(operator_snippets)}, "
        f"non-operator = {len(profile.evidence_snippets) - len(operator_snippets)})"
    )
    print(f"Final source disagreements: {len(profile.source_disagreements)}")
    print(
        f"Disagreement evidence_snippet_ids now: "
        f"{profile.source_disagreements[0].evidence_snippet_ids}"
    )

    # ===== Assertions =====

    # (1) Correct trees loaded
    assert [t["tree_id"] for t in session.trees] == [
        "diabetes",
        "dementia",
    ], "wrong trees loaded"

    # (2) State updates at correct nested paths
    assert profile.diabetes.type == "type_2"
    assert profile.diabetes.insulin.uses is True
    assert profile.diabetes.insulin.regimen == "basal_bolus"
    assert profile.diabetes.insulin.administered_by == "delegating_RN_via_AFH_staff"
    assert profile.diabetes.oral_medications  # freetext, non-empty
    assert profile.diabetes.bgm_frequency_per_day == "four_or_more_daily"

    # (3) numeric_or_null path works for A1C
    assert profile.diabetes.last_a1c_percent == 7.8

    # (4) Branching: hypo=True opened HYPO_SEVERITY
    assert profile.diabetes.hypoglycemia.history_6mo is True
    assert profile.diabetes.hypoglycemia.most_recent_severity == "mild_self_treated"

    # (4b) Branching: diet=carbohydrate_controlled skipped DIET_NOTES
    assert profile.diabetes.diet_restrictions == "carbohydrate_controlled"
    assert profile.diabetes.diet_notes is None, "DIET_NOTES should have been skipped"

    # (4c) Branching: dx_status=confirmed opened DX_TYPE
    assert profile.dementia.diagnosis_status == "confirmed"
    assert profile.dementia.diagnosis_type == "alzheimers"

    # (5) Behaviors recorded correctly
    assert profile.dementia.behaviors.exit_seeking is False
    assert profile.dementia.behaviors.sundowning is False
    assert profile.dementia.prior_placement.move_reason == "family_caregiver_burnout"

    # (6) Stage 1 evidence preserved
    assert any(
        s.snippet_id == "S1" for s in profile.evidence_snippets
    ), "S1 lost"
    assert any(
        s.snippet_id == "S2" for s in profile.evidence_snippets
    ), "S2 lost"

    # (7) Operator snippets added — one per question
    assert (
        len(operator_snippets) == answers_given
    ), f"expected {answers_given} operator snippets, got {len(operator_snippets)}"

    # (8) Disagreement preserved with operator clarification appended
    assert (
        len(profile.source_disagreements) == 1
    ), "disagreement count changed"
    dis = profile.source_disagreements[0]
    assert dis.field == "dementia.orientation_level"
    for prior_id in initial_disagreement_evidence:
        assert prior_id in dis.evidence_snippet_ids, f"prior evidence id {prior_id} dropped from disagreement"
    operator_clarifies = [
        eid for eid in dis.evidence_snippet_ids if eid.startswith("OP")
    ]
    assert (
        len(operator_clarifies) >= 1
    ), "operator ORIENTATION_LEVEL answer did not append to disagreement evidence"

    print("\nAll assertions passed.")


if __name__ == "__main__":
    test_interview_state_machine_offline()
    test_interview_full_walk_case_04()
