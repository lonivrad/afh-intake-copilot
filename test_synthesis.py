"""Smoke test for Stage 3 synthesis against case_04 (diabetes + dementia)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.extraction import (
    ADLStatus,
    ConditionsPresent,
    DementiaBehaviors,
    DementiaFamily,
    DementiaPriorPlacement,
    DementiaProfile,
    Demographics,
    DiabetesHypoglycemia,
    DiabetesInsulin,
    DiabetesProfile,
    EvidenceSnippet,
    ResidentProfile,
    SourceDisagreement,
)
from pipeline.synthesis import (
    generate_acuity_factor_recommendation,
    generate_care_plan,
    generate_risk_register,
)


MOCK_DISCLOSURE = """ADULT FAMILY HOME DISCLOSURE OF SERVICES (mock document for testing)

This home provides 24-hour resident care including:
- Personal hygiene assistance (showering, bathing, pericare)
- Medication storage and administration of oral, topical, and eye/ear medications
- Blood glucose monitoring up to four times daily
- Assistance with toileting, dressing, and mobility
- Carb-controlled and renal-modified diets
- Coordination with outpatient mental health and primary care providers
- One-person transfer assistance and walker support

This home does NOT independently provide:
- Sliding-scale or basal-bolus insulin administration (arrangement via delegating RN required prior to admission)
- Secured-egress / locked-perimeter dementia care
- Two-person transfer or mechanical lift transfer
- Wound care beyond Stage 1-2 pressure injury

Staffing model: two awake caregivers daytime, one awake caregiver overnight."""


def build_populated_profile() -> ResidentProfile:
    """Mock a post-Stage-2 profile for case_04 to avoid running Stages 1-2 live."""
    return ResidentProfile(
        demographics=Demographics(
            age_range="70-79", resident_name_placeholder="Resident D"
        ),
        conditions_present=ConditionsPresent(
            diabetes=True, dementia=True, fall_risk=False
        ),
        medications=[
            "insulin sliding-scale Humalog before meals plus glargine 30 units at bedtime",
            "metformin 1000 mg twice daily",
            "donepezil 10 mg daily",
            "sertraline 50 mg daily",
            "lisinopril",
            "atorvastatin",
        ],
        adl_status=ADLStatus(
            bathing="extensive_assistance",
            dressing="supervision",
            eating="independent",
            toilet_use="independent",
            notes=(
                "Bathes with hands-on assistance; eats and toilets independently; "
                "requires verbal cues for dressing."
            ),
        ),
        diabetes=DiabetesProfile(
            type="type_2",
            insulin=DiabetesInsulin(
                uses=True,
                regimen="basal_bolus",
                administered_by="delegating_RN_via_AFH_staff",
            ),
            oral_medications="Metformin 1000 mg twice daily.",
            bgm_frequency_per_day="four_or_more_daily",
            last_a1c_percent=7.8,
            hypoglycemia=DiabetesHypoglycemia(
                history_6mo=True, most_recent_severity="mild_self_treated"
            ),
            diet_restrictions="carbohydrate_controlled",
        ),
        dementia=DementiaProfile(
            diagnosis_status="confirmed",
            diagnosis_type="alzheimers",
            stage="moderate",
            orientation_level="oriented_x2_person_place",
            behaviors=DementiaBehaviors(
                agitation=True,
                exit_seeking=False,
                sundowning=False,
                resistance_to_care="physical_occasional",
            ),
            prior_placement=DementiaPriorPlacement(
                type="home_with_family", move_reason="family_caregiver_burnout"
            ),
            family=DementiaFamily(
                primary_contact=(
                    "Daughter, primary caregiver and responsible party (placeholder)"
                ),
                communication_preference="weekly_phone",
            ),
        ),
        evidence_snippets=[
            EvidenceSnippet(
                snippet_id="S1",
                source="discharge",
                claim="Insulin-dependent type 2 diabetes",
                verbatim_text=(
                    "type 2 diabetes mellitus, insulin-dependent for the past six years"
                ),
            ),
            EvidenceSnippet(
                snippet_id="S2",
                source="discharge",
                claim="Alzheimer's-type dementia diagnosis",
                verbatim_text=(
                    "Alzheimer's-type dementia diagnosed approximately four years ago"
                ),
            ),
            EvidenceSnippet(
                snippet_id="S3",
                source="discharge",
                claim="Moderate dementia, MMSE 18",
                verbatim_text="MMSE 18 on admission",
            ),
            EvidenceSnippet(
                snippet_id="S4",
                source="discharge",
                claim="Resistance to insulin injections",
                verbatim_text=(
                    "the resident has developed pronounced resistance to insulin "
                    "injections — pulls away, becomes agitated"
                ),
            ),
            EvidenceSnippet(
                snippet_id="S5",
                source="discharge",
                claim="BGM four times daily",
                verbatim_text="BGM four times daily",
            ),
            EvidenceSnippet(
                snippet_id="S6",
                source="discharge",
                claim="Two mild hypoglycemic events in past year",
                verbatim_text=(
                    "Two episodes of mild hypoglycemia (BG 60-70 mg/dL) in the "
                    "past year, both self-resolved after juice."
                ),
            ),
            EvidenceSnippet(
                snippet_id="S7",
                source="discharge",
                claim="No exit-seeking, no wandering, no falls",
                verbatim_text="No exit-seeking, no wandering, no falls.",
            ),
            EvidenceSnippet(
                snippet_id="S8",
                source="discharge",
                claim="Bathes with hands-on assistance; otherwise independent",
                verbatim_text=(
                    "Bathes with hands-on assistance; otherwise independent in "
                    "eating and dressing with verbal prompting."
                ),
            ),
            EvidenceSnippet(
                snippet_id="S9",
                source="family",
                claim="Daughter caregiver burnout — cannot do four daily injections",
                verbatim_text=(
                    "I've been taking care of her at home but it's become too much "
                    "for me — I have to give her insulin four times a day"
                ),
            ),
            EvidenceSnippet(
                snippet_id="S10",
                source="family",
                claim="Resident resists injections specifically",
                verbatim_text="she sees the needle and gets very upset",
            ),
            EvidenceSnippet(
                snippet_id="OP3",
                source="operator",
                claim="Operator confirmed basal-bolus regimen with delegating RN",
                verbatim_text=(
                    "Sliding-scale Humalog before meals plus glargine at bedtime — "
                    "basal-bolus regimen."
                ),
            ),
            EvidenceSnippet(
                snippet_id="OP14",
                source="operator",
                claim="Operator reports orientation x2 (person, place)",
                verbatim_text=(
                    "She knows me and the building but not the time or date."
                ),
            ),
        ],
        source_disagreements=[
            SourceDisagreement(
                field="dementia.orientation_level",
                discharge_claim="oriented to person and place but not time",
                family_claim="knows me but doesn't always know what day it is",
                evidence_snippet_ids=["S2", "OP14"],
            )
        ],
    )


@pytest.mark.api
def test_stage3_synthesis_case_04() -> None:
    case_04 = json.loads(Path("data/test_cases/case_04.json").read_text())
    source_docs = {
        "discharge_summary": case_04["inputs"]["discharge_summary"],
        "family_notes": case_04["inputs"]["family_notes"],
    }
    profile = build_populated_profile()
    dshs_rules = json.loads(Path("data/dshs_rules.json").read_text())
    valid_factor_ids = {f["acuity_factor_id"] for f in dshs_rules["factors"]}
    profile_snippet_ids = {s.snippet_id for s in profile.evidence_snippets}

    print("=== Stage 3 synthesis test: case_04 (diabetes + dementia) ===")
    print(f"Profile evidence snippets: {sorted(profile_snippet_ids)}")
    print(f"Profile disagreements: {len(profile.source_disagreements)} "
          f"(field: {profile.source_disagreements[0].field})\n")

    print("--- generate_care_plan ---")
    plan = generate_care_plan(profile, source_docs)
    print(json.dumps(plan, indent=2))
    print()

    print("--- generate_acuity_factor_recommendation ---")
    recs = generate_acuity_factor_recommendation(
        profile, source_docs, MOCK_DISCLOSURE, dshs_rules
    )
    print(json.dumps(recs, indent=2))
    print()

    print("--- generate_risk_register ---")
    register = generate_risk_register(profile, MOCK_DISCLOSURE)
    print(json.dumps(register, indent=2))
    print()

    # ===== Assertions =====

    all_outputs_str = json.dumps([plan, recs, register]).lower()

    # No "billing code" language anywhere
    assert (
        "billing code" not in all_outputs_str
    ), "output contains forbidden phrase 'billing code'"
    assert (
        "billable" not in all_outputs_str
    ), "output contains forbidden phrase 'billable'"

    # Care plan: every item references existing snippet IDs from the profile
    plan_sections = [
        "diabetes_care",
        "dementia_care",
        "fall_risk_care",
        "adl_support",
        "medication_management",
    ]
    plan_item_total = 0
    for section in plan_sections:
        for item in plan.get(section, []):
            plan_item_total += 1
            eids = item.get("evidence_snippet_ids", [])
            assert (
                len(eids) >= 1
            ), f"plan item in {section} has no evidence: {item['recommendation'][:80]}"
            for eid in eids:
                assert eid in profile_snippet_ids, (
                    f"plan item in {section} cites nonexistent snippet {eid}: "
                    f"{item['recommendation'][:80]}"
                )

    # fall_risk_care must be empty (conditions_present.fall_risk=False for case_04)
    assert (
        len(plan.get("fall_risk_care", [])) == 0
    ), "fall_risk_care populated despite fall_risk=False"

    # Acuity factor recommendations
    rec_factor_ids = []
    for rec in recs["recommendations"]:
        assert (
            rec["acuity_factor_id"] in valid_factor_ids
        ), f"invalid factor id: {rec['acuity_factor_id']}"
        rec_factor_ids.append(rec["acuity_factor_id"])
        assert (
            len(rec["resident_need_evidence"]) >= 1
        ), f"rec {rec['acuity_factor_id']} has no evidence"
        for eid in rec["resident_need_evidence"]:
            assert (
                eid in profile_snippet_ids
            ), f"rec {rec['acuity_factor_id']} cites nonexistent snippet {eid}"
        assert (
            rec["review_required"] is True
        ), f"rec {rec['acuity_factor_id']}: review_required must be True"
        if rec["disclosure_gap_flagged"]:
            assert rec["disclosure_support_snippet"] is None, (
                f"rec {rec['acuity_factor_id']}: when gap is flagged, "
                "disclosure_support_snippet should be null"
            )

    # The case_04 profile should trigger at least one obviously-applicable factor
    obvious = {"CARE-INSULIN-BGM", "CARE-BEHAV-DEMENTIA", "CARE-COG-IMPAIR"}
    assert obvious & set(rec_factor_ids), (
        f"missing obvious factors: expected at least one of {obvious}, "
        f"got {rec_factor_ids}"
    )

    # case_04 has no fall_risk evidence; do not recommend fall-risk factor
    assert (
        "CARE-FALL-RISK" not in rec_factor_ids
    ), "CARE-FALL-RISK recommended despite no fall-risk evidence in profile"

    # Risk register: gaps have evidence
    for gap in register["gaps"]:
        assert (
            len(gap["evidence_snippet_ids"]) >= 1
        ), f"gap has no evidence: {gap['resident_need'][:80]}"
        for eid in gap["evidence_snippet_ids"]:
            assert (
                eid in profile_snippet_ids
            ), f"gap cites nonexistent snippet {eid}"
        assert gap["severity"] in {"low", "medium", "high"}

    # Disclosure has explicit gaps (insulin admin, secured-egress, two-person
    # transfer, complex wounds). Insulin admin should be flagged since it's a
    # documented resident need. The flag may appear either in recommendations
    # (disclosure_gap_flagged=true on CARE-INSULIN-BGM) or in the risk register.
    insulin_gap_in_recs = any(
        rec["acuity_factor_id"] == "CARE-INSULIN-BGM"
        and rec["disclosure_gap_flagged"]
        for rec in recs["recommendations"]
    )
    insulin_gap_in_register = any(
        "insulin" in gap["resident_need"].lower()
        or "insulin" in gap["missing_or_weak_support"].lower()
        for gap in register["gaps"]
    )
    assert insulin_gap_in_recs or insulin_gap_in_register, (
        "expected insulin-admin gap to be flagged in either recommendations or "
        "risk register"
    )

    # Source disagreement: should be preserved or surfaced
    disagreement_surfaced = (
        len(plan.get("unresolved_disagreements", [])) > 0
        or "orientation" in json.dumps(plan).lower()
        or "disagreement" in all_outputs_str
        or "disputed" in all_outputs_str
    )
    if not disagreement_surfaced:
        print(
            "WARNING: source disagreement (dementia.orientation_level) not "
            "explicitly surfaced in any output"
        )

    print(
        f"\nSummary: care_plan_items={plan_item_total}, "
        f"acuity_recs={len(recs['recommendations'])}, "
        f"capability_gaps={len(register['gaps'])}, "
        f"disagreement_surfaced={'yes' if disagreement_surfaced else 'no'}"
    )
    print("All assertions passed.")


if __name__ == "__main__":
    test_stage3_synthesis_case_04()
