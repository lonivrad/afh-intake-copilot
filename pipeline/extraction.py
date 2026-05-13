"""Stage 1: Initial Extraction.

Takes a discharge summary, family-reported notes, and (optionally) the AFH
disclosure-of-services text, and returns a structured ResidentProfile plus a
list of triggered conditions. Field paths align with the updates_profile_field
strings in data/trees/*.json so the Stage 2 interview can mutate the same
object without schema translation.
"""

from __future__ import annotations

import os
from typing import Literal, Optional

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()

MODEL_ID = "claude-sonnet-4-6"


# ===== ADL scoring (CARE self-performance levels per WAC 388-106-0105) =====

ADLLevel = Literal[
    "independent",
    "supervision",
    "limited_assistance",
    "extensive_assistance",
    "total_dependence",
]


class ADLStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bed_mobility: Optional[ADLLevel] = None
    transfers: Optional[ADLLevel] = None
    eating: Optional[ADLLevel] = None
    toilet_use: Optional[ADLLevel] = None
    locomotion: Optional[ADLLevel] = None
    dressing: Optional[ADLLevel] = None
    personal_hygiene: Optional[ADLLevel] = None
    bathing: Optional[ADLLevel] = None
    notes: Optional[str] = None


# ===== Diabetes =====


class DiabetesInsulin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uses: Optional[bool] = None
    regimen: Optional[
        Literal["fixed_dose", "sliding_scale", "basal_bolus", "unknown"]
    ] = None
    administered_by: Optional[
        Literal[
            "self",
            "family",
            "delegating_RN_via_AFH_staff",
            "contracted_LPN_or_RN",
            "unknown",
        ]
    ] = None


class DiabetesHypoglycemia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    history_6mo: Optional[bool] = None
    most_recent_severity: Optional[
        Literal[
            "mild_self_treated",
            "moderate_third_party_assist",
            "severe_ER_or_hospitalization",
            "unknown",
        ]
    ] = None


class DiabetesProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Optional[Literal["type_1", "type_2", "unknown"]] = None
    insulin: DiabetesInsulin = Field(default_factory=DiabetesInsulin)
    oral_medications: Optional[str] = None
    bgm_frequency_per_day: Optional[
        Literal[
            "none",
            "once_daily",
            "two_to_three_daily",
            "four_or_more_daily",
            "PRN_only",
        ]
    ] = None
    last_a1c_percent: Optional[float] = None
    hypoglycemia: DiabetesHypoglycemia = Field(default_factory=DiabetesHypoglycemia)
    diet_restrictions: Optional[
        Literal[
            "none",
            "carbohydrate_controlled",
            "renal_diabetic",
            "low_sodium",
            "modified_texture",
            "tube_feeding",
            "other",
        ]
    ] = None
    diet_notes: Optional[str] = None


# ===== Dementia =====


class DementiaBehaviors(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agitation: Optional[bool] = None
    exit_seeking: Optional[bool] = None
    sundowning: Optional[bool] = None
    resistance_to_care: Optional[
        Literal[
            "no_resistance",
            "verbal_only",
            "physical_occasional",
            "physical_frequent",
            "combative_during_care",
        ]
    ] = None


class DementiaPriorPlacement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Optional[
        Literal[
            "home_with_family",
            "home_alone",
            "adult_family_home",
            "assisted_living",
            "memory_care",
            "skilled_nursing",
            "hospital",
            "other",
        ]
    ] = None
    move_reason: Optional[
        Literal[
            "behaviors_unmanaged_prior",
            "family_caregiver_burnout",
            "medical_acuity_increase",
            "involuntary_discharge_prior",
            "financial_change",
            "family_preference_geography",
            "other",
        ]
    ] = None


class DementiaFamily(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary_contact: Optional[str] = None
    communication_preference: Optional[
        Literal[
            "daily_phone",
            "weekly_phone",
            "weekly_email_or_text",
            "as_needed_only",
            "in_person_only",
            "other",
        ]
    ] = None


class DementiaProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diagnosis_status: Optional[
        Literal["confirmed", "suspected_unconfirmed", "no_concern"]
    ] = None
    diagnosis_type: Optional[
        Literal[
            "alzheimers",
            "vascular",
            "lewy_body",
            "frontotemporal",
            "mixed",
            "unspecified",
            "unknown",
        ]
    ] = None
    stage: Optional[
        Literal["early", "moderate", "advanced", "end_stage", "unknown"]
    ] = None
    orientation_level: Optional[
        Literal[
            "oriented_x3",
            "oriented_x2_person_place",
            "oriented_x1_person",
            "fully_disoriented",
        ]
    ] = None
    behaviors: DementiaBehaviors = Field(default_factory=DementiaBehaviors)
    prior_placement: DementiaPriorPlacement = Field(
        default_factory=DementiaPriorPlacement
    )
    family: DementiaFamily = Field(default_factory=DementiaFamily)


# ===== Fall risk =====


class FallHistory6mo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    any_falls: Optional[bool] = None
    count: Optional[int] = None
    most_recent_circumstance: Optional[
        Literal[
            "toileting_or_bathroom",
            "bedside_or_transfer",
            "ambulating_indoors",
            "ambulating_outdoors",
            "during_personal_care",
            "unwitnessed_unknown",
            "other",
        ]
    ] = None
    worst_outcome: Optional[
        Literal[
            "no_injury",
            "minor_injury_treated_in_place",
            "ER_visit_no_admission",
            "hospitalization",
            "fracture_or_head_injury",
        ]
    ] = None


class FallMedications(BaseModel):
    model_config = ConfigDict(extra="forbid")
    has_FRIDs: Optional[bool] = None
    FRID_categories: Optional[str] = None


class FallEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accommodations_required: Optional[
        Literal[
            "standard_only",
            "grab_bars_bathroom",
            "low_bed_and_or_bed_alarm",
            "wheelchair_accessibility",
            "perimeter_monitoring_alarm",
            "multiple_modifications",
            "unknown",
        ]
    ] = None


class FallPtHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Optional[
        Literal[
            "currently_active",
            "discharged_within_3mo",
            "discharged_over_3mo_ago",
            "none",
            "unknown",
        ]
    ] = None
    provider_and_plan: Optional[str] = None


class FallRiskProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    history_6mo: FallHistory6mo = Field(default_factory=FallHistory6mo)
    assistive_device: Optional[
        Literal[
            "none",
            "cane",
            "walker",
            "rollator",
            "wheelchair_self_propel",
            "wheelchair_staff_propel",
            "transfer_lift_only_non_ambulatory",
        ]
    ] = None
    gait_stability: Optional[
        Literal[
            "stable_independent",
            "stable_with_device",
            "unsteady_with_device",
            "unsteady_without_device",
            "non_ambulatory",
        ]
    ] = None
    medications: FallMedications = Field(default_factory=FallMedications)
    environment: FallEnvironment = Field(default_factory=FallEnvironment)
    pt_history: FallPtHistory = Field(default_factory=FallPtHistory)


# ===== Top-level =====


class Demographics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    age_range: Optional[str] = None
    resident_name_placeholder: Optional[str] = None


class ConditionsPresent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diabetes: bool = False
    dementia: bool = False
    fall_risk: bool = False


class EvidenceSnippet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snippet_id: str
    claim: str
    source: Literal["discharge", "family", "operator"]
    verbatim_text: str


class SourceDisagreement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    discharge_claim: Optional[str] = None
    family_claim: Optional[str] = None
    evidence_snippet_ids: list[str] = Field(default_factory=list)


class ResidentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    demographics: Demographics = Field(default_factory=Demographics)
    conditions_present: ConditionsPresent = Field(default_factory=ConditionsPresent)
    medications: list[str] = Field(default_factory=list)
    adl_status: ADLStatus = Field(default_factory=ADLStatus)
    diabetes: Optional[DiabetesProfile] = None
    dementia: Optional[DementiaProfile] = None
    fall_risk: Optional[FallRiskProfile] = None
    source_disagreements: list[SourceDisagreement] = Field(default_factory=list)
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list)


# ===== Extraction =====


SYSTEM_PROMPT = """You are the Stage 1 extraction engine for an Adult Family Home (AFH) clinical intake pipeline in Washington State. You receive a hospital discharge summary, family-reported notes, and (optionally) the AFH disclosure-of-services statement. Produce a structured ResidentProfile containing ONLY information supported by the source text.

DISCIPLINE RULES (these override fluency):

1. SUPPRESS UNSUPPORTED CLAIMS. If a field is not explicitly supported by the sources, leave it null or omit it. Do not infer plausible defaults. Do not fill in age, diet, or assistive-device fields from "typical" elderly assumptions.

2. EVERY POPULATED FIELD MUST HAVE AT LEAST ONE EVIDENCE SNIPPET. For each field you populate (including condition booleans in conditions_present), add an entry to evidence_snippets with:
   - snippet_id: short string like "S1", "S2", ...
   - claim: brief description of what the snippet supports (e.g., "diabetes: insulin-dependent type 2")
   - source: "discharge", "family", or "operator"
   - verbatim_text: a substring copied directly from the source. It must appear in the source as-written.

3. SOURCE DISAGREEMENT DETECTION. When the discharge summary and family notes materially conflict on the same field — different fall counts, opposed cognitive descriptions, contradictory medication lists — record a SourceDisagreement entry with:
   - field: the dotted path (e.g., "fall_risk.history_6mo.any_falls", "dementia.orientation_level")
   - discharge_claim: short summary of what the discharge says (or null if discharge is silent)
   - family_claim: short summary of what the family says (or null if family is silent)
   - evidence_snippet_ids: IDs of the supporting snippets

   When a disagreement exists, populate the field with the SAFER interpretation (the one that triggers more supervision/intervention) and explicitly flag the disagreement. Do not silently pick one source.

4. CONDITIONS_PRESENT FLAGS. Set conditions_present.diabetes / .dementia / .fall_risk to true only when the sources explicitly establish the condition (formal diagnosis, documented insulin use, documented fall history, etc.). For borderline cases — "memory getting worse" without diagnosis, "occasional balance issues" without a fall — leave the flag false and rely on the operator interview to confirm.

5. CONDITION-SUBPROFILE POPULATION. If conditions_present.diabetes is true, populate the diabetes subprofile with whatever is supported. Same for dementia and fall_risk. Do not populate condition subprofiles when the condition flag is false.

6. FIELD-PATH FIDELITY. The nested field paths in this schema match exactly the updates_profile_field strings in the Stage 2 interview trees. Do not flatten or rename fields.

7. PII HYGIENE. Use placeholder names only ("Resident A", "Resident B"). Do not extract or invent phone numbers, emails, or street addresses, even when the source contains them.

Then call the record_resident_profile tool with the structured profile."""


def run_initial_extraction(
    discharge_summary: str,
    family_notes: str,
    disclosure_text: str,
) -> tuple[ResidentProfile, list[str]]:
    """Extract a structured ResidentProfile from source documents via Claude tool use.

    Returns (profile, triggered_conditions) where triggered_conditions is the
    subset of {"diabetes", "dementia", "fall_risk"} flagged in
    profile.conditions_present.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )

    client = anthropic.Anthropic()
    tool_schema = ResidentProfile.model_json_schema()

    user_content = (
        f"DISCHARGE SUMMARY:\n{discharge_summary}\n\n"
        f"FAMILY NOTES:\n{family_notes}\n\n"
        f"AFH DISCLOSURE OF SERVICES:\n"
        f"{disclosure_text if disclosure_text.strip() else '(not provided)'}\n\n"
        "Call the record_resident_profile tool with the extracted profile."
    )

    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        tools=[
            {
                "name": "record_resident_profile",
                "description": (
                    "Record the structured resident profile based ONLY on "
                    "evidence in the source documents. Every populated field "
                    "must have a corresponding evidence_snippet with verbatim "
                    "source text."
                ),
                "input_schema": tool_schema,
            }
        ],
        tool_choice={"type": "tool", "name": "record_resident_profile"},
        messages=[{"role": "user", "content": user_content}],
    )

    tool_use_block = next(b for b in response.content if b.type == "tool_use")
    profile = ResidentProfile.model_validate(tool_use_block.input)

    triggered = [
        name
        for name, flag in (
            ("diabetes", profile.conditions_present.diabetes),
            ("dementia", profile.conditions_present.dementia),
            ("fall_risk", profile.conditions_present.fall_risk),
        )
        if flag
    ]

    return profile, triggered
