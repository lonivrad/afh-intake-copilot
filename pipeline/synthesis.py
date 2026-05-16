"""Stage 3: Synthesis.

Three decision-support synthesis functions that consume the
ResidentProfile assembled by Stages 1-2 and produce:

  - a care plan organized by condition / ADLs / medications,
  - a list of CARE acuity-factor recommendations (not billing codes),
  - a capability-gap risk register against the AFH disclosure of services.

Every claim across all three outputs must trace back to an evidence_snippet
that already exists in the profile; unsupported claims are suppressed.
None of the outputs asserts billing-code semantics — WA AFH Medicaid
payment is set by the DSHS CARE assessment and rate authorization, not by
per-factor add-ons.
"""

from __future__ import annotations

import json
import os
from typing import Literal, Optional

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from pipeline.extraction import ResidentProfile

load_dotenv()

MODEL_ID = "claude-sonnet-4-6"


# ===== Output schemas =====


class CarePlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommendation: str
    rationale: str
    evidence_snippet_ids: list[str] = Field(
        min_length=1,
        description=(
            "List of bare snippet_id strings (e.g., ['S1', 'OP3']) drawn from "
            "profile.evidence_snippets. Do NOT include verbatim text or claim "
            "descriptions in these strings — IDs only."
        ),
    )


class CarePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    diabetes_care: list[CarePlanItem] = Field(default_factory=list)
    dementia_care: list[CarePlanItem] = Field(default_factory=list)
    fall_risk_care: list[CarePlanItem] = Field(default_factory=list)
    adl_support: list[CarePlanItem] = Field(default_factory=list)
    medication_management: list[CarePlanItem] = Field(default_factory=list)
    unresolved_disagreements: list[str] = Field(default_factory=list)
    open_questions_for_followup: list[str] = Field(default_factory=list)


Confidence = Literal["low", "medium", "high"]


class AcuityFactorRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acuity_factor_id: str
    acuity_factor_name: str
    resident_need_evidence: list[str] = Field(
        min_length=1,
        description=(
            "List of bare snippet_id strings (e.g., ['S1', 'OP3']) drawn from "
            "profile.evidence_snippets. Do NOT include verbatim text, claim "
            "descriptions, or 'S1: <quote>' compound strings — IDs only."
        ),
    )
    wac_citation: str
    disclosure_support_snippet: Optional[str] = None
    disclosure_gap_flagged: bool
    confidence: Confidence
    review_required: bool


class AcuityFactorRecommendations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommendations: list[AcuityFactorRecommendation] = Field(default_factory=list)
    method_note: str


Severity = Literal["low", "medium", "high"]


class CapabilityGap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resident_need: str
    missing_or_weak_support: str
    disclosure_quote: Optional[str] = None
    suggested_next_action: str
    severity: Severity
    evidence_snippet_ids: list[str] = Field(
        min_length=1,
        description=(
            "List of bare snippet_id strings (e.g., ['S1', 'OP3']) drawn from "
            "profile.evidence_snippets. IDs only — no verbatim text."
        ),
    )


class RiskRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gaps: list[CapabilityGap] = Field(default_factory=list)
    method_note: str


# ===== Helpers =====


def _client() -> anthropic.Anthropic:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return anthropic.Anthropic()


def _profile_json(profile: ResidentProfile) -> str:
    return profile.model_dump_json(exclude_none=True, indent=2)


# ===== generate_care_plan =====


CARE_PLAN_SYSTEM = """You are the Stage 3 synthesis engine for an Adult Family Home (AFH) intake pipeline. Produce a care plan based on the resident profile.

INPUTS YOU RECEIVE:
- The full ResidentProfile JSON, which includes evidence_snippets with verbatim source text and any source_disagreements detected in Stage 1.
- The original discharge summary and family notes for context.

OUTPUT: a structured care plan with sections (diabetes_care, dementia_care, fall_risk_care, adl_support, medication_management). Each item must cite at least one evidence_snippet_id that already exists in the profile.

DISCIPLINE RULES:
1. EVIDENCE REQUIREMENT. Every care-plan item must reference at least one existing evidence_snippet_id from the profile. If no evidence supports a claim, do not include the claim.
2. SUPPRESS UNSUPPORTED. Do not include generic best-practice recommendations that lack this resident's specific evidence. A fall-prevention recommendation requires evidence the resident has fall risk. A dementia recommendation requires dementia evidence.
3. SECTION-CONDITION ALIGNMENT. Only populate diabetes_care if profile.conditions_present.diabetes is true. Same for dementia_care and fall_risk_care.
4. SOURCE DISAGREEMENTS. When source_disagreements affect care decisions, surface them in unresolved_disagreements and explain how the plan defaults (usually toward the safer interpretation pending verification).
5. NO BILLING-CODE LANGUAGE. Refer to acuity factors, supervision needs, and care interventions — never "billing codes." This is decision support, not a billing determination.
6. DECISION SUPPORT, NOT CLINICAL ORDER. The plan is intended to support intake conversation between the operator, family, and (where appropriate) prescriber. It is not a clinical order, legal determination, or DSHS rate authorization.

Then call the record_care_plan tool with the structured plan."""


def generate_care_plan(
    profile: ResidentProfile, source_docs: dict[str, str]
) -> dict:
    """Generate an evidence-grounded care plan from the resident profile."""
    user_content = (
        f"RESIDENT PROFILE (JSON):\n{_profile_json(profile)}\n\n"
        f"=== DISCHARGE SUMMARY ===\n"
        f"{source_docs.get('discharge_summary', '(not provided)')}\n\n"
        f"=== FAMILY NOTES ===\n"
        f"{source_docs.get('family_notes', '(not provided)')}\n\n"
        "Call the record_care_plan tool."
    )

    response = _client().messages.create(
        model=MODEL_ID,
        max_tokens=4096,
        system=CARE_PLAN_SYSTEM,
        tools=[
            {
                "name": "record_care_plan",
                "description": "Record the evidence-grounded care plan.",
                "input_schema": CarePlan.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": "record_care_plan"},
        messages=[{"role": "user", "content": user_content}],
    )

    tool_block = next(b for b in response.content if b.type == "tool_use")
    plan = CarePlan.model_validate(tool_block.input)
    return plan.model_dump()


# ===== generate_acuity_factor_recommendation =====


ACUITY_FACTOR_SYSTEM = """You are the Stage 3 synthesis engine producing CARE acuity-factor recommendations for an Adult Family Home (AFH) intake. These are decision-support outputs, not billing or rate determinations.

INPUTS:
- ResidentProfile JSON (evidence-grounded intake with evidence_snippets and source_disagreements)
- Original source documents (discharge, family)
- AFH disclosure-of-services text (what this AFH publicly says it can or cannot provide)
- CARE acuity factors catalog from data/dshs_rules.json — these are acuity / rate factors per WAC 388-106-0090/-0095/-0100/-0105/-0110/-0125, NOT standalone DSHS billing codes.

OUTPUT: a list of CARE acuity factors that this resident's documented needs trigger, plus an assessment of whether the AFH's disclosure supports the corresponding capability.

CRITICAL RULES:
1. ACUITY FACTORS, NOT BILLING CODES. Washington AFH Medicaid payment is set by DSHS CARE assessment + rate authorization by the Office of Rates Management, not by per-factor billable add-ons. Never describe a factor as "billable" or assign it a dollar amount. Use the phrase "acuity factor."
2. CATALOG FIDELITY. Each recommendation's acuity_factor_id must be one of the IDs in the supplied catalog. Do not invent IDs. Do not rename factors.
3. EVIDENCE REQUIREMENT. Each recommendation must list at least one evidence_snippet_id from the profile (in resident_need_evidence) that grounds the resident need. The resident_need_evidence field is a list of BARE snippet_id strings — for example, ["S1", "OP3"], NOT ["S1: 'verbatim text here'"]. Do not embed quotes or claim descriptions inside these strings; use IDs only. Suppress any factor recommendation that lacks specific evidence in this resident's profile.
4. DISCLOSURE MATCHING. For each recommended factor, examine the AFH disclosure text:
   - If the AFH explicitly indicates it can support the capability, populate disclosure_support_snippet with a verbatim quote and set disclosure_gap_flagged=false.
   - If the AFH disclosure does not support the capability, or is silent on it, set disclosure_gap_flagged=true and leave disclosure_support_snippet null.
5. CONFIDENCE. "high" = strong multi-source evidence; "medium" = single source or borderline criteria; "low" = weak or disputed evidence. When source_disagreements bear on a factor, default to medium or low and note the disagreement in the surrounding analysis.
6. REVIEW_REQUIRED. Always true. These recommendations are decision support; the AFH operator, family, and (where appropriate) prescriber must review.
7. WAC_CITATION. Use the wac_citation string from the matching factor in the catalog. Do not invent or modify WAC citations.
8. METHOD_NOTE. Include a brief method_note clarifying that this output is decision support, that payment depends on DSHS CARE assessment and rate authorization, and that specialty contracts (SBS, RSW, ECS, EARC-SDC) require separate DSHS application — they are not auto-triggered.
9. CLINICAL THRESHOLD. A diagnosis alone does not satisfy the evidence requirement. Evidence must support that the specific clinical complexity threshold for that factor is met. Examples:
   - CARE-INSULIN-BGM requires evidence of actual insulin administration or BGM dependency — not merely a diabetes diagnosis.
   - CARE-MED-ADMIN-MULTI requires evidence of complex multi-drug management, not merely the presence of any medication.
   - CARE-DEMENTIA-SUPERVISION requires evidence of active behavioral or safety supervision needs, not merely a dementia diagnosis.
   If evidence shows a condition but not the corresponding complexity, set confidence="low" or suppress the factor entirely.

Then call the record_acuity_recommendations tool."""


def generate_acuity_factor_recommendation(
    profile: ResidentProfile,
    source_docs: dict[str, str],
    disclosure_text: str,
    dshs_rules: dict,
) -> dict:
    """Generate CARE acuity-factor recommendations grounded in the profile and disclosure.

    Uses dshs_rules["factors"] as the authoritative factor catalog.
    """
    factors = dshs_rules["factors"]

    user_content = (
        f"RESIDENT PROFILE (JSON):\n{_profile_json(profile)}\n\n"
        f"=== DISCHARGE ===\n"
        f"{source_docs.get('discharge_summary', '(not provided)')}\n\n"
        f"=== FAMILY NOTES ===\n"
        f"{source_docs.get('family_notes', '(not provided)')}\n\n"
        f"=== AFH DISCLOSURE OF SERVICES ===\n{disclosure_text}\n\n"
        f"=== CARE ACUITY FACTORS CATALOG ===\n"
        f"{json.dumps(factors, indent=2)}\n\n"
        "Call the record_acuity_recommendations tool."
    )

    response = _client().messages.create(
        model=MODEL_ID,
        max_tokens=4096,
        system=ACUITY_FACTOR_SYSTEM,
        tools=[
            {
                "name": "record_acuity_recommendations",
                "description": "Record evidence-grounded CARE acuity-factor recommendations and disclosure matching.",
                "input_schema": AcuityFactorRecommendations.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": "record_acuity_recommendations"},
        messages=[{"role": "user", "content": user_content}],
    )

    tool_block = next(b for b in response.content if b.type == "tool_use")
    recs = AcuityFactorRecommendations.model_validate(tool_block.input)
    return recs.model_dump()


# ===== generate_risk_register =====


RISK_REGISTER_SYSTEM = """You are the Stage 3 capability-gap analyzer for an Adult Family Home (AFH) intake. Identify where the resident's documented needs are NOT clearly supported by the AFH's disclosure-of-services language.

INPUTS:
- ResidentProfile JSON (evidence-grounded intake with evidence_snippets and source_disagreements)
- AFH disclosure-of-services text

OUTPUT: a register of capability gaps.

A capability gap exists when a documented resident need lacks clear matching disclosure language. Examples:
- Resident requires sliding-scale insulin administration; disclosure is silent on insulin or nurse delegation.
- Resident exhibits exit-seeking; disclosure does not address secured egress.
- Resident requires two-person transfer; disclosure mentions only single-staff assist.

RULES:
1. EVIDENCE REQUIREMENT. Each gap must cite at least one evidence_snippet_id from the profile that establishes the resident need.
2. VERBATIM DISCLOSURE QUOTES. When the disclosure speaks to the need (even weakly or with a precondition), quote it verbatim in disclosure_quote. If the disclosure is silent on the topic, set disclosure_quote=null.
3. SEVERITY. "high" = potential immediate safety risk (e.g., insulin admin scope mismatch, exit-seeking without secured egress, severe hypoglycemia history without on-call clinical support, two-person transfer without disclosed staffing). "medium" = elevated risk that needs mitigation but is not acute. "low" = preference / quality-of-life.
4. SUGGESTED ACTION. Concrete and actionable: "Verify delegating RN availability before admission," "Re-issue disclosure with secured-egress language," "Decline admission and refer to AFH holding applicable specialty contract."
5. SUPPRESS UNSUPPORTED. Do not flag generic concerns. Only flag gaps that have specific resident-need evidence in the profile.
6. SURFACE DISAGREEMENTS. Where source_disagreements affect a capability gap (e.g., disputed cognitive status changes whether secured-egress is needed), note that explicitly in missing_or_weak_support.
7. NO BILLING-CODE LANGUAGE. Decision support, not a billing determination.
8. METHOD_NOTE. Include a brief method_note clarifying the decision-support framing and the requirement that the AFH operator and clinical/legal stakeholders review before any admission decision.

Then call the record_risk_register tool."""


def generate_risk_register(
    profile: ResidentProfile, disclosure_text: str
) -> dict:
    """Generate the capability-gap risk register against the AFH disclosure."""
    user_content = (
        f"RESIDENT PROFILE (JSON):\n{_profile_json(profile)}\n\n"
        f"=== AFH DISCLOSURE OF SERVICES ===\n{disclosure_text}\n\n"
        "Call the record_risk_register tool."
    )

    response = _client().messages.create(
        model=MODEL_ID,
        max_tokens=4096,
        system=RISK_REGISTER_SYSTEM,
        tools=[
            {
                "name": "record_risk_register",
                "description": "Record evidence-grounded capability gaps between resident needs and AFH disclosure.",
                "input_schema": RiskRegister.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": "record_risk_register"},
        messages=[{"role": "user", "content": user_content}],
    )

    tool_block = next(b for b in response.content if b.type == "tool_use")
    reg = RiskRegister.model_validate(tool_block.input)
    return reg.model_dump()


# ===== generate_intake_decision (Stage 4 — operator-facing decision layer) =====


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref_type: Literal["snippet", "acuity_factor", "risk_register_entry"]
    ref_id: str


class IntakeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommendation: Literal[
        "accept",
        "accept_with_conditions",
        "hold_for_review",
    ]
    rationale: str
    conditions_before_admission: list[str] = Field(min_length=1, max_length=5)
    family_call_talking_points: list[str] = Field(min_length=1, max_length=5)
    evidence_references: list[EvidenceRef] = Field(min_length=1)


DECISION_LAYER_SYSTEM = """You are the Stage 4 INTAKE DECISION layer for an Adult Family Home (AFH) intake pipeline. You consume four already-produced artifacts and emit a single structured intake recommendation.

YOU ARE A RE-ORGANIZER, NOT A CLINICAL REASONER. Every condition and talking point you produce must already appear (or be straightforwardly derivable) from the care plan, acuity-factor recommendations, or risk register inputs. The only new content you produce is sentence structure and prioritization. Do not invent new clinical findings or new evidence.

YOU CANNOT access discharge summaries, family notes, the AFH disclosure text, or tree files. You can ONLY reason over:
- the care_plan
- the acuity_factor_recommendations
- the risk_register (each gap is annotated with a gap_id)
- the profile_summary (evidence snippet IDs and any source disagreements)

DETERMINISTIC RECOMMENDATION LOGIC (apply top-to-bottom — stop at the first that matches):

1. hold_for_review — choose this if ANY of:
   a. any risk_register gap has severity == "high"
   b. there is an unresolved source disagreement that materially affects admission safety (e.g., disagreement about cognition, fall pattern, or insulin/medication scope)
   c. an acuity factor has disclosure_gap_flagged == true on a critical capability (insulin administration, secured-egress dementia care, two-person transfer, complex wound care, behavioral support)

2. accept_with_conditions — choose this only if hold_for_review does NOT apply AND any of:
   a. one or more medium- or low-severity risk_register gaps
   b. one or more acuity factors with disclosure_gap_flagged == true (non-critical capability)

3. accept — choose this only if:
   a. no high-severity gaps
   b. no disclosure gaps
   c. no unresolved source disagreements that affect admission

OUTPUT FIELDS:

- rationale: 2-4 sentences in plain language for an AFH operator. Reference the artifacts that drove the choice; do not introduce new clinical content.

- conditions_before_admission: 1-5 concrete pre-admission action items. Each item should be drawn from a risk_register gap's suggested_next_action (or missing_or_weak_support), or from a disclosure-gap acuity factor. Each must be: concise (under 25 words), operator-facing (something the AFH must do), action-oriented (verb-led sentence). If the recommendation is "accept", still provide at least one item — typical pre-admission steps already implied in the care plan (e.g., final paperwork sign-off, medication-list reconciliation) are acceptable as long as they trace to existing artifact content.

- family_call_talking_points: 1-5 plain-language bullets an AFH operator could say during the placement call. No legal disclaimers. No clinical jargon unless unavoidable. Each must reference something already in the care plan, acuity recommendations, or risk register — do not invent.

- evidence_references: at least one EvidenceRef. Cite ONLY existing IDs:
  - ref_type="snippet" + ref_id matching a snippet_id from profile_summary.evidence_snippet_ids
  - ref_type="acuity_factor" + ref_id matching an acuity_factor_id from acuity_factor_recommendations.recommendations
  - ref_type="risk_register_entry" + ref_id matching a gap_id from risk_register.gaps

Then call the record_intake_decision tool."""


def generate_intake_decision(
    care_plan: dict,
    acuity_factor_recommendations: dict,
    risk_register: dict,
    profile: ResidentProfile,
) -> dict:
    """Produce a single operator-facing intake recommendation.

    Reasons ONLY over the four supplied artifacts; cannot access source
    documents. Each risk-register entry is annotated with a synthetic
    gap_NN id at call time so the model can reference gaps by ID.
    """
    # Inject synthetic gap_id on each risk-register entry (additive only —
    # the underlying risk_register dict is not mutated).
    gaps_with_ids = [
        {**gap, "gap_id": f"gap_{i:02d}"}
        for i, gap in enumerate(risk_register.get("gaps", []))
    ]
    risk_register_view = {**risk_register, "gaps": gaps_with_ids}

    profile_summary = {
        "evidence_snippet_ids": [s.snippet_id for s in profile.evidence_snippets],
        "source_disagreements": [
            {
                "field": d.field,
                "discharge_claim": d.discharge_claim,
                "family_claim": d.family_claim,
            }
            for d in profile.source_disagreements
        ],
    }

    user_content = (
        f"=== CARE PLAN ===\n{json.dumps(care_plan, indent=2)}\n\n"
        f"=== ACUITY FACTOR RECOMMENDATIONS ===\n"
        f"{json.dumps(acuity_factor_recommendations, indent=2)}\n\n"
        f"=== RISK REGISTER (each gap annotated with gap_id) ===\n"
        f"{json.dumps(risk_register_view, indent=2)}\n\n"
        f"=== PROFILE SUMMARY ===\n{json.dumps(profile_summary, indent=2)}\n\n"
        "Call the record_intake_decision tool with the structured decision."
    )

    response = _client().messages.create(
        model=MODEL_ID,
        max_tokens=2048,
        system=DECISION_LAYER_SYSTEM,
        tools=[
            {
                "name": "record_intake_decision",
                "description": (
                    "Record the structured intake recommendation derived "
                    "solely from the supplied artifacts. No new clinical "
                    "findings; evidence references must use existing IDs."
                ),
                "input_schema": IntakeDecision.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": "record_intake_decision"},
        messages=[{"role": "user", "content": user_content}],
    )

    tool_block = next(b for b in response.content if b.type == "tool_use")
    decision = IntakeDecision.model_validate(tool_block.input)
    return decision.model_dump()
