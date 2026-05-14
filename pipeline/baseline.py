"""Baseline single-call workflow.

Produces care_plan + acuity_factor_recommendations + risk_register in ONE
Claude API call. No staged extraction, no stateful interview, no separate
Stage 1 / 2 / 3 — this is the generic one-shot LLM version used as a
control to compare against the staged pipeline in Step 10.

Output structure mirrors the staged-pipeline outputs so the two can be
compared directly.
"""

from __future__ import annotations

import json
import os

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

from pipeline.synthesis import (
    AcuityFactorRecommendations,
    CarePlan,
    RiskRegister,
)

load_dotenv()

MODEL_ID = "claude-sonnet-4-6"


class BaselineOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    care_plan: CarePlan
    acuity_factor_recommendations: AcuityFactorRecommendations
    risk_register: RiskRegister


BASELINE_SYSTEM = """You are an Adult Family Home (AFH) clinical intake co-pilot operating in single-call baseline mode. In ONE structured tool call, produce three decision-support artifacts from the discharge summary, family-reported notes, AFH disclosure of services, and the supplied CARE acuity-factors catalog (from data/dshs_rules.json).

ARTIFACTS:
1. care_plan — sectioned into diabetes_care, dementia_care, fall_risk_care, adl_support, medication_management. Each item lists evidence_snippet_ids: brief BARE identifiers you assign as you read the sources — use "DS1", "DS2", ... for discharge-summary quotes and "FN1", "FN2", ... for family-note quotes. Reuse the same ID across items when the same source quote supports multiple recommendations. Use IDs only — no compound "DS1: <quote>" strings.

2. acuity_factor_recommendations — list of CARE acuity factors this resident's documented needs trigger. Each acuity_factor_id MUST come from the supplied catalog. These are CARE acuity / rate factors per WAC 388-106-0090/-0095/-0100/-0105/-0110/-0125, NOT standalone DSHS billing codes. Each recommendation must include:
   - acuity_factor_id (from catalog)
   - acuity_factor_name (from catalog)
   - resident_need_evidence (list of bare snippet IDs using the DS#/FN# scheme above — IDs only)
   - wac_citation (copy verbatim from the catalog)
   - disclosure_support_snippet (verbatim quote from disclosure if supported) OR disclosure_gap_flagged=true with disclosure_support_snippet=null
   - confidence (low / medium / high)
   - review_required = true

3. risk_register — capability gaps where the resident's documented needs are not clearly supported by AFH disclosure language. Each gap: resident_need, missing_or_weak_support, optional verbatim disclosure_quote, suggested_next_action, severity (low / medium / high), evidence_snippet_ids.

DISCIPLINE RULES:
- LANGUAGE DISCIPLINE: never use the phrases "billing code," "billable," or "bill," not even in negation. Refer to "CARE acuity factors" or "CARE rate-classification factors." Washington AFH Medicaid payment is set by DSHS CARE assessment and rate authorization by the DSHS Office of Rates Management — describe this directly, without mentioning what payment is NOT. Example acceptable phrasing for the method_note: "Payment depends on DSHS CARE assessment and rate authorization by the Office of Rates Management; no acuity factor listed here generates an automatic payment add-on."
- Suppress claims you cannot ground in the supplied sources. If a recommendation has no supporting quote in discharge or family notes, omit it.
- Only populate condition sections (diabetes_care, dementia_care, fall_risk_care) when the sources establish the condition. Do not infer a condition from typical-elderly defaults.
- When discharge and family materially disagree on a fact, surface that in care_plan.unresolved_disagreements and default the care plan toward the safer interpretation.
- Specialty contracts (SBS, RSW, ECS, EARC-SDC, Meaningful Day, CSS) are discrete DSHS-contracted programs requiring AFH application and approval — they are NOT auto-triggered. Mention this in the method_note fields.
- Decision support, not a clinical, legal, or billing determination. Every output requires review.

Then call the record_baseline_output tool with the full structured output."""


def run_baseline(
    discharge_summary: str,
    family_notes: str,
    disclosure_text: str,
    dshs_rules: dict,
) -> dict:
    """Run the entire AFH intake workflow in a single Claude API call.

    Returns a dict with keys care_plan, acuity_factor_recommendations,
    and risk_register that mirror the shapes of the staged pipeline's
    Stage 3 outputs.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )

    client = anthropic.Anthropic()
    factors = dshs_rules["factors"]

    user_content = (
        f"=== DISCHARGE SUMMARY ===\n{discharge_summary}\n\n"
        f"=== FAMILY NOTES ===\n{family_notes}\n\n"
        f"=== AFH DISCLOSURE OF SERVICES ===\n{disclosure_text}\n\n"
        f"=== CARE ACUITY FACTORS CATALOG ===\n{json.dumps(factors, indent=2)}\n\n"
        "Call the record_baseline_output tool with the full structured output."
    )

    response = client.messages.create(
        model=MODEL_ID,
        # 16k headroom — case_06-equivalent complex outputs (all three
        # conditions + nine acuity factors) can otherwise truncate.
        max_tokens=16000,
        system=BASELINE_SYSTEM,
        tools=[
            {
                "name": "record_baseline_output",
                "description": (
                    "Record the baseline single-call output containing the care "
                    "plan, CARE acuity-factor recommendations, and capability-gap "
                    "risk register."
                ),
                "input_schema": BaselineOutput.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": "record_baseline_output"},
        messages=[{"role": "user", "content": user_content}],
    )

    tool_block = next(b for b in response.content if b.type == "tool_use")
    out = BaselineOutput.model_validate(tool_block.input)
    return out.model_dump()
