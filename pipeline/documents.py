"""Downstream document generation from existing intake artifacts.

The Draft Admission Action Plan is a markdown worksheet the AFH operator
can use while preparing the official negotiated care plan / service
agreement. It is NOT legally binding, NOT WAC-compliant, and NOT a
substitute for the official DSHS-required documentation.

This module performs no LLM calls and no clinical reasoning — it
formats fields that already exist in the four committed artifacts
(care_plan, acuity_factor_recommendations, risk_register,
intake_decision). When a section has no source content, the placeholder
"[Not documented during intake — operator to complete.]" is inserted
rather than inventing.
"""

from __future__ import annotations

import re
from datetime import datetime

from pipeline.extraction import ResidentProfile


_RECOMMENDATION_LABELS = {
    "accept": "ACCEPT",
    "accept_with_conditions": "ACCEPT WITH CONDITIONS",
    "hold_for_review": "HOLD FOR REVIEW",
}

_CARE_PLAN_SECTIONS = [
    ("Diabetes", "diabetes_care"),
    ("Dementia", "dementia_care"),
    ("Fall Risk", "fall_risk_care"),
    ("ADL Support", "adl_support"),
    ("Medication Management", "medication_management"),
]

_NOT_DOCUMENTED = "[Not documented during intake — operator to complete.]"


def _strip_leading_number(text: str) -> str:
    """Strip a leading 'N. ' prefix some artifact strings carry."""
    return re.sub(r"^\d+\.\s*", "", text)


def generate_admission_action_plan(
    resident_name: str,
    afh_name: str,
    artifacts: dict,
    profile: ResidentProfile,
) -> str:
    """Generate a draft admission action plan from existing artifacts.

    This is an operator worksheet, not a legally binding agreement.
    Returns formatted markdown.
    """
    today = datetime.now().strftime("%B %d, %Y")
    decision = artifacts.get("intake_decision", {}) or {}
    care_plan = artifacts.get("care_plan", {}) or {}
    risk_register = artifacts.get("risk_register", {}) or {}

    conditions = decision.get("conditions_before_admission", []) or []
    talking_points = decision.get("family_call_talking_points", []) or []
    open_questions = care_plan.get("open_questions_for_followup", []) or []
    gaps = risk_register.get("gaps", []) or []
    serious_gaps = sorted(
        [g for g in gaps if g.get("severity") in ("high", "medium")],
        key=lambda g: 0 if g.get("severity") == "high" else 1,
    )

    parts: list[str] = []

    # ---- Header ----
    parts.append("# Draft Admission Action Plan")
    parts.append("")
    parts.append(f"**Resident Name:** {resident_name}  ")
    parts.append(f"**AFH Name:** {afh_name}  ")
    parts.append(f"**Date Prepared:** {today}  ")
    parts.append(
        "**Generated From:** AFH Acuity Intake Copilot artifacts  "
    )
    parts.append(
        "**Status:** Draft worksheet — requires operator, clinician, and "
        "family review"
    )
    parts.append("")
    parts.append(
        "> This document is decision support only. It is not a legal "
        "agreement, clinical order, billing determination, or substitute "
        "for the official negotiated care plan / service agreement."
    )
    parts.append("")
    parts.append("---")

    # ---- 1. Admission Recommendation ----
    parts.append("")
    parts.append("## 1. Admission Recommendation")
    parts.append("")
    rec = decision.get("recommendation")
    rationale = decision.get("rationale", "")
    if rec:
        label = _RECOMMENDATION_LABELS.get(rec, str(rec).upper())
        parts.append(f"**Recommendation:** {label}")
        parts.append("")
        if rationale:
            parts.append(f"**Rationale:** {rationale}")
        else:
            parts.append(f"**Rationale:** {_NOT_DOCUMENTED}")
    else:
        parts.append(_NOT_DOCUMENTED)
    parts.append("")
    parts.append("---")

    # ---- 2. Conditions Before Admission ----
    parts.append("")
    parts.append("## 2. Conditions Before Admission")
    parts.append("")
    if conditions:
        for c in conditions:
            parts.append(f"- {c}")
    else:
        parts.append(_NOT_DOCUMENTED)
    parts.append("")
    parts.append("---")

    # ---- 3. Services / Supports Identified in the Care Plan ----
    parts.append("")
    parts.append("## 3. Services / Supports Identified in the Care Plan")
    parts.append("")
    rendered_any = False
    for section_label, key in _CARE_PLAN_SECTIONS:
        items = care_plan.get(key, []) or []
        if not items:
            continue
        rendered_any = True
        parts.append(f"### {section_label}")
        parts.append("")
        for item in items:
            rec_text = (item.get("recommendation") or "").strip()
            if rec_text:
                parts.append(f"- {rec_text}")
        parts.append("")
    if not rendered_any:
        parts.append(_NOT_DOCUMENTED)
        parts.append("")
    parts.append("---")

    # ---- 4. Disclosure / Capability Gaps to Resolve ----
    parts.append("")
    parts.append("## 4. Disclosure / Capability Gaps to Resolve")
    parts.append("")
    if serious_gaps:
        for g in serious_gaps:
            sev = (g.get("severity") or "").upper()
            need = (g.get("resident_need") or "").strip()
            missing = (g.get("missing_or_weak_support") or "").strip()
            action = (g.get("suggested_next_action") or "").strip()
            parts.append(f"**[{sev}]** {need}")
            if missing:
                parts.append(f"- Missing or weak support: {missing}")
            if action:
                parts.append(f"- Suggested next action: {action}")
            parts.append("")
    else:
        parts.append(_NOT_DOCUMENTED)
        parts.append("")
    parts.append("---")

    # ---- 5. Family Communication Notes ----
    parts.append("")
    parts.append("## 5. Family Communication Notes")
    parts.append("")
    if talking_points:
        for t in talking_points:
            parts.append(f"- {t}")
    else:
        parts.append(_NOT_DOCUMENTED)
    parts.append("")
    parts.append("---")

    # ---- 6. Open Questions Before Move-In ----
    parts.append("")
    parts.append("## 6. Open Questions Before Move-In")
    parts.append("")
    if open_questions:
        for q in open_questions:
            parts.append(f"- {_strip_leading_number(q)}")
    else:
        parts.append("No open questions documented during intake.")
    parts.append("")
    parts.append("---")

    # ---- 7. Operator Completion Checklist ----
    parts.append("")
    parts.append("## 7. Operator Completion Checklist")
    parts.append("")
    checklist: list[str] = []
    for c in conditions:
        checklist.append(c)
    for g in serious_gaps:
        action = (g.get("suggested_next_action") or "").strip()
        if action:
            checklist.append(action)
    for q in open_questions:
        checklist.append(_strip_leading_number(q))
    if checklist:
        for item in checklist:
            parts.append(f"- [ ] {item}")
    else:
        parts.append(_NOT_DOCUMENTED)
    parts.append("")
    parts.append("---")

    # ---- 8. Final Review Sign-Off ----
    parts.append("")
    parts.append("## 8. Final Review Sign-Off")
    parts.append("")
    parts.append(
        "AFH operator review: __________________   Date: ________  "
    )
    parts.append(
        "RN / clinician review, if applicable: __________________   "
        "Date: ________  "
    )
    parts.append(
        "Resident or representative review: __________________   "
        "Date: ________"
    )
    parts.append("")
    parts.append("---")

    # ---- Footer ----
    parts.append("")
    parts.append(
        "*Draft only. Final admission documents must be completed by the "
        "AFH operator using applicable DSHS-required forms and "
        "professional judgment.*"
    )

    return "\n".join(parts)
