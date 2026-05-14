"""AFH Acuity Intake Copilot — Streamlit UI.

Stateful one-page workflow: paste source documents -> Stage 1 extraction ->
Stage 2 stateful interview -> Stage 3 synthesis -> view the three
decision-support artifacts (care plan, CARE acuity-factor recommendations,
capability-gap risk register) with expandable evidence snippets, and
optionally compare against the single-call baseline.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from html import escape as html_escape
from pathlib import Path

import streamlit as st
from pypdf import PdfReader

from pipeline.baseline import run_baseline
from pipeline.documents import generate_admission_action_plan
from pipeline.extraction import ResidentProfile, run_initial_extraction
from pipeline.interview import InterviewSession
from pipeline.synthesis import (
    generate_acuity_factor_recommendation,
    generate_care_plan,
    generate_intake_decision,
    generate_risk_register,
)


# ===== Page setup =====

st.set_page_config(page_title="AFH Acuity Intake Copilot", layout="wide")
st.markdown(
    """
    <style>
    p, li, div {
        word-wrap: break-word !important;
        overflow-wrap: break-word !important;
    }
    section.main * {
        line-height: 1.55 !important;
    }
    .summary-card {
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 16px 18px;
        margin-bottom: 14px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("AFH Acuity Intake Copilot")
st.caption(
    "Decision support for Adult Family Home intake in Washington State. "
    "Not a clinical, legal, or billing determination. All outputs require review."
)


# ===== Session-state init =====

DEFAULT_STATE = {
    "stage": "input",  # input | interview | synthesis_ready | synthesis_done
    "profile": None,
    "triggered_conditions": [],
    "source_docs": None,
    "disclosure_text": "",
    "session": None,
    "interview_total_nodes": 0,
    "artifacts": None,
    "intake_decision": None,
    "baseline_output": None,
    "draft_action_plan": None,
}


# ===== Interview UX constants =====

_TREE_PRETTY = {
    "diabetes": "Diabetes",
    "dementia": "Dementia",
    "fall_risk": "Fall risk",
}

# Map node_id -> section breadcrumb tail. Display-layer only; no tree-file
# changes. Unknown node IDs fall back to the tree name alone.
_NODE_SECTION = {
    # Diabetes
    "DIABETES_TYPE": "Diagnosis",
    "INSULIN_USE": "Insulin administration",
    "INSULIN_REGIMEN": "Insulin administration",
    "INSULIN_ADMIN": "Insulin administration",
    "ORAL_MEDS": "Oral medications",
    "BGM_FREQUENCY": "Blood glucose monitoring",
    "LAST_A1C": "A1C",
    "HYPO_HISTORY": "Hypoglycemia",
    "HYPO_SEVERITY": "Hypoglycemia",
    "DIET_RESTRICTIONS": "Diet",
    "DIET_NOTES": "Diet",
    # Dementia
    "DX_STATUS": "Diagnosis",
    "DX_TYPE": "Diagnosis",
    "STAGE": "Stage",
    "ORIENTATION_LEVEL": "Orientation",
    "BEHAV_AGITATION": "Behavioral symptoms",
    "BEHAV_EXIT_SEEKING": "Behavioral symptoms",
    "BEHAV_SUNDOWNING": "Behavioral symptoms",
    "BEHAV_RESIST_CARE": "Behavioral symptoms",
    "PRIOR_PLACEMENT_TYPE": "Prior placement",
    "MOVE_REASON": "Prior placement",
    "FAMILY_PRIMARY_CONTACT": "Family contact",
    "FAMILY_COMM_PREF": "Family contact",
    # Fall risk
    "FALL_HISTORY_6MO": "Fall history",
    "FALL_COUNT": "Fall history",
    "FALL_CIRCUMSTANCES": "Fall history",
    "FALL_OUTCOMES": "Fall history",
    "ASSISTIVE_DEVICE": "Assistive device",
    "GAIT_STABILITY": "Gait",
    "MEDS_FALL_RISK": "Fall-risk medications",
    "MEDS_FALL_RISK_CATEGORIES": "Fall-risk medications",
    "HOME_ACCOMMODATIONS": "Environment",
    "PT_HISTORY": "Physical therapy",
    "PT_NOTES": "Physical therapy",
}


def _first_two_sentences(text: str) -> str:
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:2]).strip()


# ===== Per-tab executive-summary helpers (Step 10.10) =====


_CARE_SECTION_LABELS = [
    ("diabetes_care", "diabetes"),
    ("dementia_care", "dementia"),
    ("fall_risk_care", "fall risk"),
    ("adl_support", "ADLs"),
    ("medication_management", "medications"),
]


def _care_plan_summary(care_plan: dict) -> str:
    total = sum(
        len(care_plan.get(k, [])) for k, _ in _CARE_SECTION_LABELS
    )
    present = [
        label for k, label in _CARE_SECTION_LABELS if care_plan.get(k)
    ]
    if not present:
        return f"Care Plan Summary: {total} care items."
    return (
        f"Care Plan Summary: {total} care items across "
        f"{', '.join(present)} — all grounded in "
        "discharge/family/operator evidence."
    )


def _short_factor_label(name: str) -> str:
    cleaned = name.replace(" acuity factor", "")
    if "(" in cleaned:
        cleaned = cleaned.split("(")[0].strip()
    return cleaned.lower()


def _acuity_summary(acuity_recs: dict) -> str:
    recs = acuity_recs.get("recommendations", [])
    total = len(recs)
    if total == 0:
        return "Acuity Summary: 0 CARE factors recommended."
    top = recs[:5]
    items = ", ".join(
        f"{_short_factor_label(r['acuity_factor_name'])} ({r['confidence']})"
        for r in top
    )
    extra = f" (+{total - 5} more)" if total > 5 else ""
    plural = "s" if total != 1 else ""
    return (
        f"Acuity Summary: {total} CARE factor{plural} recommended: "
        f"{items}{extra}."
    )


def _risk_summary(risk_register: dict) -> str:
    gaps = risk_register.get("gaps", [])
    total = len(gaps)
    if total == 0:
        return "Risk Summary: 0 capability gaps."
    sev_count = {"high": 0, "medium": 0, "low": 0}
    for g in gaps:
        s = g.get("severity")
        if s in sev_count:
            sev_count[s] += 1
    parts = []
    if sev_count["high"]:
        parts.append(f"{sev_count['high']} high severity")
    if sev_count["medium"]:
        parts.append(f"{sev_count['medium']} medium")
    if sev_count["low"]:
        parts.append(f"{sev_count['low']} low")
    breakdown = ", ".join(parts) if parts else "severity unspecified"
    return f"Risk Summary: {total} capability gaps: {breakdown}."


# ===== Summary-tab operator dashboard helpers =====


def evidence_chip(text: str) -> str:
    """Return inline HTML for a small pill-style evidence ID chip."""
    return (
        f'<span style="background:#eef2ff; color:#3730a3; padding:4px 10px; '
        f'border-radius:999px; font-size:12px; font-weight:600; '
        f'margin-right:6px; display:inline-block;">{html_escape(text)}</span>'
    )


_CRITICAL_FIELD_KEYWORDS = (
    "insulin", "bgm", "hypoglyc", "fall", "wander", "exit",
    "cognition", "orientation", "seizure", "wound",
)


def _infer_severity(text_or_field: str) -> tuple[str, str]:
    """UI-only priority inference. Returns (label, color)."""
    lower = (text_or_field or "").lower()
    if any(k in lower for k in _CRITICAL_FIELD_KEYWORDS):
        return ("CRITICAL", "#991b1b")
    return ("CLARIFY", "#b45309")


def _infer_owner(question_text: str) -> str:
    """UI-only owner inference for open questions. Best-effort keyword
    match against common roles. The user is reminded this is UI-inferred,
    not artifact-authored."""
    lower = (question_text or "").lower()
    if any(
        k in lower
        for k in (
            "dr.", "dr ", "prescriber", "physician", "doctor",
            "primary care", "specialist", "psychiatrist",
        )
    ):
        return "Prescriber / clinician"
    if any(
        k in lower
        for k in (
            "delegating rn", "delegating nurse", "registered nurse",
            "nurse delegation", "rn ",
        )
    ):
        return "Delegating RN"
    if any(
        k in lower
        for k in (
            "daughter", "son", "spouse", "family", "next of kin",
            "responsible party", "primary contact",
        )
    ):
        return "Family"
    if any(
        k in lower
        for k in (
            "hospital", "discharging facility", "discharge team",
            "discharge planner", "discharge plan", "home health",
            "skilled nursing", "snf",
        )
    ):
        return "Hospital / Home Health"
    if any(
        k in lower
        for k in ("afh", "operator", "intake", "staff", "caregiver")
    ):
        return "AFH operator"
    return "Unassigned"


def _render_talking_point_card(idx: int, text: str) -> None:
    """Render a single 'What to say' talking-point card via render_info_card."""
    render_info_card(
        f"TALKING POINT {idx}",
        f"<strong>What to say:</strong> {html_escape(text)}",
        accent="#1e3a5f",
    )


def _render_disagreement_card_structured(idx: int, d) -> None:
    """Render a structured disagreement card using profile.source_disagreements
    fields. Severity is UI-inferred from the field path."""
    severity_label, severity_color = _infer_severity(d.field)
    chips_html = "".join(
        evidence_chip(s) for s in (d.evidence_snippet_ids or [])
    )
    rows: list[str] = [
        f'<div style="margin-bottom:8px;"><strong>Topic:</strong> '
        f'{html_escape(d.field)}</div>'
    ]
    if d.discharge_claim:
        rows.append(
            '<div style="margin-bottom:6px;"><strong>Discharge says:</strong> '
            f'{html_escape(d.discharge_claim)}</div>'
        )
    if d.family_claim:
        rows.append(
            '<div style="margin-bottom:6px;"><strong>Family says:</strong> '
            f'{html_escape(d.family_claim)}</div>'
        )
    if chips_html:
        rows.append(
            f'<div style="margin-top:10px;"><strong>Evidence:</strong> '
            f'{chips_html}</div>'
        )
    body_html = "".join(rows)
    st.markdown(
        f"""
        <div class="summary-card" style="border-left: 5px solid {severity_color};">
          <div style="margin-bottom:8px;">
            <span style="background:{severity_color}; color:white; padding:3px 9px; border-radius:6px; font-size:11px; font-weight:700; letter-spacing:.04em;">{severity_label}</span>
            <span style="font-size:11px; color:#6b7280; font-weight:600; margin-left:8px;">UI priority (inferred from field path)</span>
          </div>
          <div style="font-size:13px; font-weight:800; color:#374151; letter-spacing:.04em; text-transform:uppercase; margin-bottom:8px;">
            CLINICAL CONFLICT
          </div>
          <div style="font-size:15px; line-height:1.55; color:#1f2937;">
            {body_html}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_disagreement_card_narrative(idx: int, text: str) -> None:
    """Fallback narrative disagreement card when profile.source_disagreements
    is empty. The em-dash split gives a topic line; everything after is the
    narrative body. Severity inferred from the text keywords."""
    severity_label, severity_color = _infer_severity(text)
    parts = text.split("—", 1)
    if len(parts) == 2 and parts[0].strip():
        topic, body = parts[0].strip(), parts[1].strip()
    else:
        topic, body = f"Disagreement {idx}", text.strip()
    st.markdown(
        f"""
        <div class="summary-card" style="border-left: 5px solid {severity_color};">
          <div style="margin-bottom:8px;">
            <span style="background:{severity_color}; color:white; padding:3px 9px; border-radius:6px; font-size:11px; font-weight:700; letter-spacing:.04em;">{severity_label}</span>
            <span style="font-size:11px; color:#6b7280; font-weight:600; margin-left:8px;">UI priority (inferred from text keywords)</span>
          </div>
          <div style="font-size:13px; font-weight:800; color:#374151; letter-spacing:.04em; text-transform:uppercase; margin-bottom:8px;">
            CLINICAL CONFLICT
          </div>
          <div style="font-size:15px; line-height:1.55; color:#1f2937;">
            <div style="margin-bottom:8px;"><strong>{html_escape(topic)}</strong></div>
            <div>{html_escape(body)}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


_OWNER_ORDER = [
    "Prescriber / clinician",
    "Delegating RN",
    "Family",
    "Hospital / Home Health",
    "AFH operator",
    "Unassigned",
]


def _render_open_questions_grouped(open_questions: list[str]) -> None:
    """Group questions by inferred owner and render under small
    subheaders. Owner labels carry an explicit 'Suggested owner
    (UI-inferred)' qualifier so operators don't read it as authored
    metadata."""
    groups: dict[str, list[str]] = {}
    for q in open_questions:
        cleaned = re.sub(r"^\d+\.\s*", "", q).strip()
        owner = _infer_owner(cleaned)
        groups.setdefault(owner, []).append(cleaned)
    for owner in _OWNER_ORDER:
        items = groups.get(owner)
        if not items:
            continue
        st.markdown(
            f"""
            <div style="margin-top:14px; margin-bottom:4px;">
              <span style="font-size:14px; font-weight:700; color:#1e3a5f;">{html_escape(owner)}</span>
              <span style="font-size:11px; font-weight:500; color:#6b7280; margin-left:10px;">Suggested owner (UI-inferred)</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        for q in items:
            st.markdown(f"- {q}")


# ===== Action Plan markdown sectionizer =====


def _parse_action_plan_sections(md: str) -> tuple[str, list[tuple[str, str]]]:
    """Split the generated Draft Admission Action Plan markdown into an
    intro block (everything before the first '## ' header) and a list of
    (section_title, section_body) pairs. Trailing horizontal-rule
    separators are stripped from each section body."""
    parts = re.split(r"^## ", md, flags=re.MULTILINE)
    intro = parts[0].strip()
    sections: list[tuple[str, str]] = []
    for chunk in parts[1:]:
        chunk = chunk.rstrip()
        if "\n" in chunk:
            title, body = chunk.split("\n", 1)
        else:
            title, body = chunk, ""
        body = re.sub(r"\n+---\s*$", "", body).strip()
        sections.append((title.strip(), body.strip()))
    return intro, sections


# ===== Nested per-item renderers (inside the "View …" outer expander) =====


_CARE_SECTIONS = [
    ("Diabetes", "diabetes_care"),
    ("Dementia", "dementia_care"),
    ("Fall risk", "fall_risk_care"),
    ("ADLs", "adl_support"),
    ("Medications", "medication_management"),
]


def _render_care_item_nested(
    section_label: str, item: dict, profile: ResidentProfile
) -> None:
    rec = (item.get("recommendation") or "").strip()
    preview = rec if len(rec) <= 100 else rec[:100].rstrip() + "…"
    label = f"{section_label} · {preview}"
    with st.expander(label, expanded=False):
        st.markdown(rec)
        if item.get("rationale"):
            st.caption(f"Rationale: {item['rationale']}")
        _render_evidence_snippets(
            profile, item.get("evidence_snippet_ids", []) or []
        )


def _render_acuity_factor_nested(
    rec: dict, profile: ResidentProfile
) -> None:
    name = rec.get("acuity_factor_name", rec.get("acuity_factor_id", "?"))
    conf = rec.get("confidence", "—")
    disclosure = (
        "gap flagged" if rec.get("disclosure_gap_flagged") else "supported"
    )
    label = f"{name} · Confidence: {conf} · Disclosure: {disclosure}"
    with st.expander(label, expanded=False):
        if rec.get("acuity_factor_id"):
            st.markdown(f"`{rec['acuity_factor_id']}`")
        if rec.get("wac_citation"):
            st.markdown(f"_WAC citation:_ {rec['wac_citation']}")
        if rec.get("disclosure_support_snippet"):
            st.markdown(
                f"_Disclosure quote:_ > {rec['disclosure_support_snippet']}"
            )
        elif rec.get("disclosure_gap_flagged"):
            st.warning(
                "AFH disclosure does not clearly support this capability."
            )
        _render_evidence_snippets(
            profile, rec.get("resident_need_evidence", []) or []
        )


def _render_risk_gap_nested(gap: dict, profile: ResidentProfile) -> None:
    sev = gap.get("severity", "low")
    need = (gap.get("resident_need") or "").strip()
    preview = need if len(need) <= 120 else need[:120].rstrip() + "…"
    sev_tag = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}.get(
        sev, "[?]"
    )
    label = f"{sev_tag} {preview} · gap flagged"
    with st.expander(label, expanded=False):
        st.markdown(
            severity_badge(sev) + f" **{need}**",
            unsafe_allow_html=True,
        )
        missing = (gap.get("missing_or_weak_support") or "").strip()
        if missing:
            if sev == "high":
                st.error(missing)
            elif sev == "medium":
                st.warning(missing)
            else:
                st.info(missing)
        if gap.get("disclosure_quote"):
            st.markdown(
                f"_Disclosure quote:_ > {gap['disclosure_quote']}"
            )
        else:
            st.markdown(
                "_Disclosure quote:_ _(disclosure silent on this need)_"
            )
        if gap.get("suggested_next_action"):
            st.markdown(
                f"_Suggested next action:_ {gap['suggested_next_action']}"
            )
        _render_evidence_snippets(
            profile, gap.get("evidence_snippet_ids", []) or []
        )
for _k, _v in DEFAULT_STATE.items():
    st.session_state.setdefault(_k, _v)


# ===== Helpers =====


@st.cache_data
def _load_dshs_rules() -> dict:
    return json.loads(
        (Path(__file__).parent / "data" / "dshs_rules.json").read_text()
    )


def _read_pdf(uploaded_file) -> str:
    reader = PdfReader(uploaded_file)
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _render_evidence_snippets(profile: ResidentProfile, snippet_ids: list[str]):
    if not snippet_ids:
        return
    by_id = {s.snippet_id: s for s in profile.evidence_snippets}
    with st.expander(f"Evidence ({len(snippet_ids)})", expanded=False):
        for sid in snippet_ids:
            snip = by_id.get(sid)
            if snip is None:
                st.markdown(f"- `{sid}` — _(not in staged-pipeline profile)_")
                continue
            st.markdown(
                f"- **`{sid}`** _(source: {snip.source})_ — {snip.claim}"
            )
            st.markdown(f"  > {snip.verbatim_text}")


def _render_care_plan(plan: dict, profile: ResidentProfile):
    if plan.get("summary"):
        st.markdown("**Summary**")
        st.write(plan["summary"])
    sections = [
        ("diabetes_care", "Diabetes"),
        ("dementia_care", "Dementia"),
        ("fall_risk_care", "Fall risk"),
        ("adl_support", "ADL support"),
        ("medication_management", "Medication management"),
    ]
    for key, title in sections:
        items = plan.get(key, [])
        if not items:
            continue
        st.markdown(f"**{title}**")
        for i, item in enumerate(items, 1):
            st.markdown(f"{i}. {item['recommendation']}")
            st.caption(f"Rationale: {item['rationale']}")
            _render_evidence_snippets(profile, item.get("evidence_snippet_ids", []))
    if plan.get("unresolved_disagreements"):
        st.markdown("**Unresolved disagreements**")
        for d in plan["unresolved_disagreements"]:
            st.markdown(f"- {d}")
    if plan.get("open_questions_for_followup"):
        st.markdown("**Open questions for follow-up**")
        for q in plan["open_questions_for_followup"]:
            st.markdown(f"- {q}")


def _render_acuity_recs(recs: dict, profile: ResidentProfile):
    if recs.get("method_note"):
        st.caption(recs["method_note"])
    for rec in recs.get("recommendations", []):
        st.markdown(
            f"**{rec['acuity_factor_name']}** `({rec['acuity_factor_id']})`"
        )
        st.markdown(
            f"Confidence: **{rec['confidence']}**  |  "
            f"Disclosure: **{'gap flagged' if rec['disclosure_gap_flagged'] else 'supported'}**  |  "
            f"Review required: **{'yes' if rec['review_required'] else 'no'}**"
        )
        st.markdown(f"_WAC citation:_ {rec['wac_citation']}")
        if rec.get("disclosure_support_snippet"):
            st.markdown(
                f"_Disclosure quote:_ > {rec['disclosure_support_snippet']}"
            )
        elif rec.get("disclosure_gap_flagged"):
            st.warning(
                "AFH disclosure does not clearly support this capability."
            )
        _render_evidence_snippets(
            profile, rec.get("resident_need_evidence", [])
        )
        st.divider()


_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def render_decision_card(recommendation: str, rationale: str) -> None:
    """Professional styled recommendation card. Inline-styled HTML so the
    color signal carries even without the Streamlit theme (which already
    matches; see .streamlit/config.toml)."""
    if recommendation == "accept":
        color, symbol, label = "#2d5f3f", "✓", "ACCEPT"
    elif recommendation == "accept_with_conditions":
        color, symbol, label = "#b45309", "!", "ACCEPT WITH CONDITIONS"
    else:
        color, symbol, label = "#991b1b", "!", "HOLD FOR REVIEW"
    st.markdown(
        f"""
        <div style="background:{color}; color:white; padding:24px; border-radius:12px; margin-bottom:20px; box-shadow:0 2px 8px rgba(0,0,0,0.10);">
            <div style="font-size:13px; font-weight:700; letter-spacing:1px; opacity:0.9;">{symbol} RECOMMENDATION</div>
            <div style="font-size:28px; font-weight:800; margin:8px 0 14px 0;">{label}</div>
            <div style="font-size:16px; line-height:1.6; opacity:0.96;">{rationale}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_info_card(
    title: str, body: str, accent: str = "#1e3a5f"
) -> None:
    """Small accented card with a small-caps title and a body line.
    Inline-styled HTML so it carries even without theme overrides."""
    st.markdown(
        f"""
        <div style="border-left: 5px solid {accent}; background: #ffffff; padding: 16px 18px; border-radius: 10px; margin: 12px 0 18px 0; box-shadow: 0 1px 4px rgba(0,0,0,0.06);">
            <div style="font-size: 14px; font-weight: 800; color: {accent}; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 6px;">{title}</div>
            <div style="font-size: 15px; line-height: 1.55; color: #374151;">{body}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def severity_badge(level: str) -> str:
    colors = {
        "high": ("#991b1b", "white"),
        "medium": ("#b45309", "white"),
        "low": ("#6b7280", "white"),
    }
    bg, fg = colors.get(str(level).lower(), ("#6b7280", "white"))
    return (
        f'<span style="background:{bg}; color:{fg}; padding:4px 10px; '
        f'border-radius:6px; font-size:12px; font-weight:700; '
        f'text-transform:uppercase; margin-right:8px;">{level}</span>'
    )


def find_snippet_references(snippet_id: str, artifacts: dict) -> list[str]:
    """Return human-readable section labels where snippet_id is cited.

    Scans the four committed artifacts (care_plan, acuity_factor_
    recommendations, risk_register, intake_decision) via the explicit
    fields the schemas already use to carry snippet IDs:
      - care_plan[section][*].evidence_snippet_ids
      - acuity_factor_recommendations.recommendations[*].resident_need_evidence
      - risk_register.gaps[*].evidence_snippet_ids
      - intake_decision.evidence_references[*] (when ref_type == 'snippet')

    Risk-register entries are labeled gap_NN by enumeration index, matching
    the convention generate_intake_decision uses when assigning gap_ids.
    """
    refs: list[str] = []

    care_plan = artifacts.get("care_plan", {}) or {}
    for section_key in (
        "diabetes_care",
        "dementia_care",
        "fall_risk_care",
        "adl_support",
        "medication_management",
    ):
        for item in care_plan.get(section_key, []):
            if snippet_id in item.get("evidence_snippet_ids", []):
                refs.append(f"Care Plan → {section_key}")
                break  # one mention per section is enough

    acuity = artifacts.get("acuity_factor_recommendations", {}) or {}
    for rec in acuity.get("recommendations", []):
        if snippet_id in rec.get("resident_need_evidence", []):
            refs.append(
                f"Acuity Factors → {rec.get('acuity_factor_id', '?')}"
            )

    risk = artifacts.get("risk_register", {}) or {}
    for i, gap in enumerate(risk.get("gaps", [])):
        if snippet_id in gap.get("evidence_snippet_ids", []):
            refs.append(f"Risk Register → gap_{i:02d}")

    decision = artifacts.get("intake_decision", {}) or {}
    for ref in decision.get("evidence_references", []):
        if (
            ref.get("ref_type") == "snippet"
            and ref.get("ref_id") == snippet_id
        ):
            refs.append("Intake Decision → evidence_references")
            break

    return refs


def _preview_text(text: str, n: int = 70) -> str:
    """Collapse whitespace and truncate to n chars with an ellipsis suffix
    if longer. Used for the Evidence Provenance Map expander labels."""
    cleaned = " ".join(text.split())
    return cleaned if len(cleaned) <= n else cleaned[:n] + "..."


_SOURCE_LABELS = {
    "discharge": "Discharge evidence",
    "family": "Family note",
    "operator": "Operator answer",
}


def _evidence_label(
    snippet, n_refs: int, is_high_gap: bool
) -> str:
    """Build the compact-row label for one evidence snippet."""
    src_label = _SOURCE_LABELS.get(snippet.source, snippet.source)
    preview = _preview_text(snippet.verbatim_text)
    if snippet.source == "operator":
        middle = f"{src_label} → {preview}"
    else:
        middle = f"{src_label} · {preview}"
    ref_suffix = f"{n_refs} ref{'' if n_refs == 1 else 's'}"
    label = f"{snippet.snippet_id} · {middle} · {ref_suffix}"
    if is_high_gap:
        label += " · HIGH-GAP EVIDENCE"
    return label


def _render_snippet_row(snippet, refs: list[str], is_high_gap: bool) -> None:
    label = _evidence_label(snippet, len(refs), is_high_gap)
    with st.expander(label, expanded=False):
        if is_high_gap:
            st.warning(
                "This snippet supports a high-severity capability gap."
            )
        if snippet.claim:
            st.markdown(f"**Claim / context:** {snippet.claim}")
        st.markdown(f"**Full text:** {snippet.verbatim_text}")
        if refs:
            st.markdown("**Referenced in:**")
            for ref in refs:
                st.markdown(f"- {ref}")
        else:
            st.markdown(
                "_Not referenced by any committed artifact._"
            )


def _render_evidence_provenance_map(
    combined_artifacts: dict, profile: ResidentProfile
) -> None:
    """Audit-navigation view of the evidence base.

    Summary line + legend → filter row (source / reference type / high-
    gap toggle) → coverage line → filtered snippets grouped by source
    (compact collapsed rows) → unreferenced section with explanation.
    Reference-finding logic unchanged.
    """
    with st.expander("🔍 View Evidence Provenance Map", expanded=False):
        render_info_card(
            "Evidence Map",
            "Every claim in the artifacts traces back to a verbatim "
            "source quote. Use the filters below to narrow the view; "
            "expand any snippet for full text and the artifacts that "
            "cite it.",
            accent="#0f766e",
        )
        snippets = profile.evidence_snippets

        # Reference index per snippet (computed once).
        snippet_refs: dict[str, list[str]] = {
            s.snippet_id: find_snippet_references(
                s.snippet_id, combined_artifacts
            )
            for s in snippets
        }

        # Snippet IDs cited by any high-severity risk gap.
        high_gap_snippet_ids: set[str] = set()
        risk = combined_artifacts.get("risk_register", {}) or {}
        for gap in risk.get("gaps", []) or []:
            if gap.get("severity") == "high":
                for sid in gap.get("evidence_snippet_ids", []) or []:
                    high_gap_snippet_ids.add(sid)

        total = len(snippets)
        unreferenced_count = sum(
            1 for s in snippets if not snippet_refs[s.snippet_id]
        )

        # Summary line + legend.
        st.markdown(
            f"**{total} evidence snippets · {unreferenced_count} "
            "unreferenced · grouped by source and artifact references**"
        )
        st.caption(
            "S = discharge/source document · F = family note · "
            "OP = operator interview answer · gap_XX = risk register item"
        )

        st.divider()

        # Filter controls.
        col_src, col_ref, col_hi = st.columns([1, 1, 1])
        with col_src:
            source_filter = st.selectbox(
                "Source",
                ["All", "Discharge", "Family", "Operator"],
                key="ev_filter_source",
            )
        with col_ref:
            ref_filter = st.selectbox(
                "References",
                [
                    "All references",
                    "Risk gaps only",
                    "Care plan only",
                    "Acuity factors only",
                    "Intake decision only",
                    "Unreferenced only",
                ],
                key="ev_filter_ref",
            )
        with col_hi:
            high_gap_only = st.checkbox(
                "Show only evidence tied to high-severity gaps",
                key="ev_filter_highgap",
            )

        # Live coverage line (totals never change with filter).
        discharge_count = sum(
            1 for s in snippets if s.source == "discharge"
        )
        family_count = sum(1 for s in snippets if s.source == "family")
        operator_count = sum(
            1 for s in snippets if s.source == "operator"
        )
        st.caption(
            f"Coverage: Discharge {discharge_count} · Family "
            f"{family_count} · Operator {operator_count} · Total {total}"
        )

        # Filter application.
        def _matches(s, refs: list[str]) -> bool:
            if (
                source_filter != "All"
                and s.source != source_filter.lower()
            ):
                return False
            if ref_filter == "Risk gaps only" and not any(
                r.startswith("Risk Register") for r in refs
            ):
                return False
            if ref_filter == "Care plan only" and not any(
                r.startswith("Care Plan") for r in refs
            ):
                return False
            if ref_filter == "Acuity factors only" and not any(
                r.startswith("Acuity Factors") for r in refs
            ):
                return False
            if ref_filter == "Intake decision only" and not any(
                r.startswith("Intake Decision") for r in refs
            ):
                return False
            if ref_filter == "Unreferenced only" and refs:
                return False
            if (
                high_gap_only
                and s.snippet_id not in high_gap_snippet_ids
            ):
                return False
            return True

        passing = [s for s in snippets if _matches(s, snippet_refs[s.snippet_id])]

        # "Unreferenced only" → single flat list, no source grouping
        # and no separate unreferenced section.
        if ref_filter == "Unreferenced only":
            if not passing:
                st.info("No snippets match the current filter.")
            else:
                st.subheader(
                    f"⚠ Unreferenced Evidence ({len(passing)})"
                )
                st.markdown(
                    "These snippets were extracted but not cited in "
                    "final artifacts. This is often normal for "
                    "demographic or background details, but should be "
                    "reviewed if the snippet contains clinical or "
                    "operational risk."
                )
                for s in passing:
                    _render_snippet_row(
                        s, [], s.snippet_id in high_gap_snippet_ids
                    )
            return

        # Referenced snippets grouped by source.
        source_meta = [
            ("discharge", "Discharge summary evidence"),
            ("family", "Family notes evidence"),
            ("operator", "Operator interview evidence"),
        ]
        rendered_any = False
        for source_key, heading in source_meta:
            group = [
                s
                for s in passing
                if s.source == source_key and snippet_refs[s.snippet_id]
            ]
            if not group:
                continue
            rendered_any = True
            st.subheader(heading)
            for s in group:
                _render_snippet_row(
                    s,
                    snippet_refs[s.snippet_id],
                    s.snippet_id in high_gap_snippet_ids,
                )

        # Unreferenced section — only when "All references" is selected
        # (other reference filters by definition exclude unreferenced).
        unreferenced_passing = [
            s for s in passing if not snippet_refs[s.snippet_id]
        ]
        if unreferenced_passing and ref_filter == "All references":
            st.subheader(
                f"⚠ Unreferenced Evidence ({len(unreferenced_passing)})"
            )
            st.markdown(
                "These snippets were extracted but not cited in final "
                "artifacts. This is often normal for demographic or "
                "background details, but should be reviewed if the "
                "snippet contains clinical or operational risk."
            )
            for s in unreferenced_passing:
                _render_snippet_row(
                    s, [], s.snippet_id in high_gap_snippet_ids
                )

        if not rendered_any and not unreferenced_passing:
            st.info("No snippets match the current filter.")


def _render_intake_decision(
    decision: dict,
    artifacts: dict | None = None,
    profile: ResidentProfile | None = None,
) -> None:
    rec = decision.get("recommendation", "")
    rationale_full = decision.get("rationale", "")
    rationale_short = _first_two_sentences(rationale_full)
    conditions = decision.get("conditions_before_admission", [])

    render_decision_card(rec, rationale_short)

    # Evidence provenance map — between the decision card and the
    # conditions checklist. Reveals bidirectional traceability between
    # extracted evidence and artifact claims.
    if artifacts is not None and profile is not None:
        combined = {**artifacts, "intake_decision": decision}
        _render_evidence_provenance_map(combined, profile)

    st.subheader("✓ Conditions before admission")
    if rec == "accept":
        st.write(
            "No conditions — this resident appears to fit the home's "
            "disclosed capabilities."
        )
        return

    # Interactive admission checklist with a readiness meter rendered
    # above it via st.empty() so the count updates same-run when the
    # operator toggles a checkbox.
    if "conditions_checked" not in st.session_state:
        st.session_state.conditions_checked = {}

    total = len(conditions)
    meter_placeholder = st.empty()

    for idx, condition in enumerate(conditions):
        key = f"condition_{idx}"
        # Initialize from nested dict on first encounter; subsequent runs
        # let Streamlit's auto-key binding own the value to avoid the
        # "value parameter ignored" warning when both `value` and `key`
        # are passed and the key is already in session_state.
        if key not in st.session_state:
            st.session_state[key] = (
                st.session_state.conditions_checked.get(key, False)
            )
        checked = st.checkbox(condition, key=key)
        st.session_state.conditions_checked[key] = checked

    checked_count = sum(
        1
        for idx in range(total)
        if st.session_state.conditions_checked.get(
            f"condition_{idx}", False
        )
    )

    with meter_placeholder.container():
        st.markdown(
            f"**Admission readiness: {checked_count} of {total} "
            "conditions resolved**"
        )
        if total > 0:
            st.progress(checked_count / total)


def _render_risk_register(reg: dict, profile: ResidentProfile):
    if reg.get("method_note"):
        st.caption(reg["method_note"])
    gaps_sorted = sorted(
        reg.get("gaps", []),
        key=lambda g: _SEVERITY_ORDER.get(g.get("severity"), 99),
    )
    for gap in gaps_sorted:
        sev = gap["severity"]
        st.markdown(
            severity_badge(sev) + f" **{gap['resident_need']}**",
            unsafe_allow_html=True,
        )
        if sev == "high":
            st.error(gap["missing_or_weak_support"])
        elif sev == "medium":
            st.warning(gap["missing_or_weak_support"])
        else:
            st.info(gap["missing_or_weak_support"])
        if gap.get("disclosure_quote"):
            st.markdown(f"_Disclosure quote:_ > {gap['disclosure_quote']}")
        else:
            st.markdown("_Disclosure quote:_ _(disclosure silent on this need)_")
        st.markdown(f"_Suggested next action:_ {gap['suggested_next_action']}")
        _render_evidence_snippets(profile, gap.get("evidence_snippet_ids", []))
        st.divider()


# ===== Sidebar =====

with st.sidebar:
    st.header("Settings")
    compare_baseline = st.toggle(
        "Compare against baseline",
        value=False,
        help=(
            "Run the single-call baseline on the same inputs and show "
            "side-by-side with the staged pipeline once artifacts are ready."
        ),
    )

    st.divider()
    if st.button("Reset session"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()


# ===== Main area =====

stage = st.session_state.stage


# --- Stage: input ---

if stage == "input":
    st.header("1. Inputs")
    col1, col2 = st.columns(2)
    with col1:
        discharge = st.text_area(
            "Discharge summary",
            height=260,
            placeholder="Paste the hospital discharge summary here",
        )
    with col2:
        family = st.text_area(
            "Family-reported notes",
            height=260,
            placeholder="Paste family-reported observations here",
        )

    disclosure = st.text_area(
        "AFH disclosure of services",
        height=200,
        placeholder=(
            "Paste the AFH disclosure here, or upload a .txt or .pdf below"
        ),
    )
    upload = st.file_uploader(
        "Optional: upload disclosure as .txt or .pdf",
        type=["txt", "pdf"],
    )
    if upload is not None:
        try:
            if upload.name.lower().endswith(".pdf"):
                disclosure = _read_pdf(upload)
            else:
                disclosure = upload.read().decode("utf-8", errors="replace")
            st.success(
                f"Loaded {len(disclosure):,} characters from {upload.name}"
            )
        except Exception as exc:
            st.error(f"Could not read uploaded file: {exc}")

    can_start = bool(discharge and family)
    if st.button("Start Intake", type="primary", disabled=not can_start):
        with st.spinner("Running Stage 1 extraction..."):
            profile, triggered = run_initial_extraction(
                discharge_summary=discharge,
                family_notes=family,
                disclosure_text=disclosure,
            )
        st.session_state.profile = profile
        st.session_state.triggered_conditions = triggered
        st.session_state.source_docs = {
            "discharge_summary": discharge,
            "family_notes": family,
        }
        st.session_state.disclosure_text = disclosure
        if triggered:
            session = InterviewSession(
                profile=profile, triggered_conditions=triggered
            )
            st.session_state.session = session
            # Y for interview progress: sum of all nodes across triggered
            # trees, computed ONCE at interview start so the progress bar
            # never moves backward as branching skips nodes.
            st.session_state.interview_total_nodes = sum(
                len(t["nodes"]) for t in session.trees
            )
            st.session_state.stage = "interview"
        else:
            st.info(
                "Stage 1 flagged no conditions for interview; jumping to synthesis."
            )
            st.session_state.stage = "synthesis_ready"
        st.rerun()


# --- Stage: interview ---

elif stage == "interview":
    session = st.session_state.session
    node = session.get_next_question()
    if node is None:
        st.session_state.stage = "synthesis_ready"
        st.rerun()

    st.header("2. Interview")

    # Stable progress: Y fixed at session start; X = answered + 1.
    y_total = st.session_state.interview_total_nodes
    answered = session._local_parse_count + session._fallback_parse_count
    x_current = answered + 1
    tree_id = session.trees[session.current_tree_idx]["tree_id"]
    tree_pretty = _TREE_PRETTY.get(tree_id, tree_id)
    section = _NODE_SECTION.get(node["node_id"])
    breadcrumb = (
        f"{tree_pretty} → {section}" if section else tree_pretty
    )
    minutes_remaining = round((y_total - x_current) * 30 / 60)

    st.markdown(f"**{breadcrumb}**")
    st.caption(
        f"Question {x_current} of up to {y_total} · "
        f"~{minutes_remaining} minutes remaining"
    )
    st.progress(min(x_current / y_total, 1.0) if y_total else 0.0)

    st.subheader(node["question_text"])
    if node.get("context_hint"):
        with st.expander("Context"):
            st.write(node["context_hint"])
    if node["expected_answer_shape"] == "enum" and node.get("answer_options"):
        st.caption(
            "Suggested values: " + ", ".join(node["answer_options"])
        )

    with st.form(key=f"answer_form_{tree_id}_{node['node_id']}"):
        answer = st.text_area(
            "Operator answer",
            height=120,
            key=f"ans_{tree_id}_{node['node_id']}",
        )
        submitted = st.form_submit_button("Submit Answer", type="primary")
    if submitted:
        if not answer.strip():
            st.warning("Please enter an answer.")
        else:
            with st.spinner("Parsing answer..."):
                session.submit_answer(answer)
            st.rerun()


# --- Stage: synthesis_ready ---

elif stage == "synthesis_ready":
    st.header("3. Generate artifacts")
    st.write(
        "Interview complete. Generate the three decision-support artifacts."
    )
    if st.button("Generate Artifacts", type="primary"):
        dshs_rules = _load_dshs_rules()
        with st.spinner("Generating care plan..."):
            care = generate_care_plan(
                st.session_state.profile, st.session_state.source_docs
            )
        with st.spinner("Generating acuity factor recommendations..."):
            recs = generate_acuity_factor_recommendation(
                st.session_state.profile,
                st.session_state.source_docs,
                st.session_state.disclosure_text,
                dshs_rules,
            )
        with st.spinner("Generating risk register..."):
            reg = generate_risk_register(
                st.session_state.profile, st.session_state.disclosure_text
            )
        with st.spinner("Generating intake decision..."):
            decision = generate_intake_decision(
                care_plan=care,
                acuity_factor_recommendations=recs,
                risk_register=reg,
                profile=st.session_state.profile,
            )
        st.session_state.artifacts = {
            "care_plan": care,
            "acuity_factor_recommendations": recs,
            "risk_register": reg,
        }
        st.session_state.intake_decision = decision
        st.session_state.stage = "synthesis_done"
        st.rerun()


# --- Stage: synthesis_done ---

elif stage == "synthesis_done":
    st.header("4. Artifacts")

    if compare_baseline and st.session_state.baseline_output is None:
        if st.button("Run baseline single-call for comparison"):
            with st.spinner("Running baseline single-call..."):
                dshs_rules = _load_dshs_rules()
                st.session_state.baseline_output = run_baseline(
                    discharge_summary=st.session_state.source_docs[
                        "discharge_summary"
                    ],
                    family_notes=st.session_state.source_docs["family_notes"],
                    disclosure_text=st.session_state.disclosure_text,
                    dshs_rules=dshs_rules,
                )
            st.rerun()

    artifacts = st.session_state.artifacts
    profile = st.session_state.profile
    baseline = st.session_state.baseline_output
    decision = st.session_state.intake_decision

    # Top-of-page: decision banner (with rationale truncated to first 2
    # sentences) + evidence provenance map + conditions checklist.
    # Provenance map sits between the banner and the conditions per the
    # Step 10.21 spec; it reads the same artifacts dict used elsewhere on
    # this page.
    if decision is not None:
        _render_intake_decision(decision, artifacts, profile)

    st.divider()

    (
        tab_summary,
        tab_action,
        tab_care,
        tab_acuity,
        tab_risk,
        tab_profile,
    ) = st.tabs(
        [
            "Summary",
            "Action Plan",
            "Care Plan",
            "Acuity Factors",
            "Risk Register",
            "Profile",
        ]
    )

    # Summary — operator-first order: the actual answer (talking points)
    # first, process transparency (provenance) second, edge cases
    # (disagreements / open questions) last, and only when non-empty.
    with tab_summary:
        render_info_card(
            "Summary",
            "Operator script and decision context.",
            accent="#374151",
        )
        plan = artifacts["care_plan"]
        acuity_recs = artifacts["acuity_factor_recommendations"]
        risk_register = artifacts["risk_register"]
        # Single source of truth for the unresolved-disagreements list:
        # whatever the Unresolved Disagreements section renders is also
        # what the provenance box counts, so the two cannot diverge.
        unresolved_disagreements = plan["unresolved_disagreements"]
        open_questions = plan.get("open_questions_for_followup", [])

        # 1. Talking points — render every item as a TALKING POINT N
        # card with the operator-facing "What to say" line. No overflow
        # collapsers (3-7 items is short enough to scan).
        if decision is not None:
            tps = decision.get("family_call_talking_points", [])
            if tps:
                st.subheader("Talking points for the family call")
                for i, tp in enumerate(tps, 1):
                    _render_talking_point_card(i, tp)

        # 2. Divider.
        st.divider()

        # 3. Provenance box — all counts computed live from existing
        # objects.
        operator_answer_count = sum(
            1 for s in profile.evidence_snippets if s.source == "operator"
        )
        triggered_condition_count = len(
            st.session_state.triggered_conditions
        )
        evidence_snippet_count = len(profile.evidence_snippets)
        acuity_factor_count = len(acuity_recs["recommendations"])
        risk_gap_count = len(risk_register["gaps"])
        disagreement_count = len(unresolved_disagreements)

        with st.container(border=True):
            st.subheader("How this recommendation was generated")
            st.caption(
                "Every claim below traces to a verifiable evidence ID."
            )
            st.markdown(
                f"- ✓ {operator_answer_count} structured operator interview "
                f"responses captured across {triggered_condition_count} "
                "clinical conditions\n"
                f"- ✓ {evidence_snippet_count} evidence snippets extracted "
                "from discharge summary and family notes\n"
                "- ✓ 1 AFH Disclosure of Services document cross-checked "
                "against resident needs\n"
                f"- ✓ {acuity_factor_count} acuity factors evaluated against "
                "Washington CARE criteria (WAC 388-106)\n"
                f"- ✓ {risk_gap_count} disclosure gaps identified and "
                "severity-ranked\n"
                f"- ✓ {disagreement_count} unresolved source disagreements "
                "surfaced for clinical review"
            )

        # 4. Unresolved disagreements — prefer the structured
        # profile.source_disagreements (carries discharge_claim /
        # family_claim / evidence_snippet_ids); fall back to
        # care_plan.unresolved_disagreements as narrative cards when
        # the structured list is empty. Severity is a UI-inferred
        # "CRITICAL" / "CLARIFY" chip, labeled accordingly.
        structured_disagreements = list(profile.source_disagreements)
        if structured_disagreements:
            st.subheader("Unresolved disagreements")
            for i, d in enumerate(structured_disagreements, 1):
                _render_disagreement_card_structured(i, d)
        elif unresolved_disagreements:
            st.subheader("Unresolved disagreements")
            for i, d in enumerate(unresolved_disagreements, 1):
                _render_disagreement_card_narrative(i, d)

        # 5. Open questions for follow-up — grouped under
        # UI-inferred owner subheaders. Each group header carries an
        # explicit "Suggested owner (UI-inferred)" qualifier.
        if len(open_questions) > 0:
            st.subheader("Open questions for follow-up")
            _render_open_questions_grouped(open_questions)

    # Action Plan tab — generates the Draft Admission Action Plan
    # markdown from existing artifacts on demand. Two clean states:
    # pre-generation (intro + primary button only) and post-generation
    # (success + download + collapsed preview + secondary regenerate).
    # st.rerun() after state transitions so the rendered surface
    # matches the new state immediately.
    with tab_action:
        render_info_card(
            "Action Plan",
            "Downloadable worksheet for move-in preparation. Not a "
            "legal agreement — requires operator review.",
            accent="#1e3a5f",
        )

        def _generate_action_plan() -> str:
            resident_name = (
                profile.demographics.resident_name_placeholder
                or "Resident (name not documented)"
            )
            return generate_admission_action_plan(
                resident_name=resident_name,
                afh_name="AFH Operator",
                artifacts={
                    **artifacts,
                    "intake_decision": decision,
                },
                profile=profile,
            )

        if st.session_state.draft_action_plan is None:
            if st.button(
                "Generate Draft Admission Action Plan",
                type="primary",
            ):
                st.session_state.draft_action_plan = (
                    _generate_action_plan()
                )
                st.rerun()
        else:
            st.success("Draft Action Plan generated.")
            st.download_button(
                label="Download Draft Action Plan",
                data=st.session_state.draft_action_plan,
                file_name=(
                    "admission_action_plan_"
                    f"{datetime.now().strftime('%Y%m%d')}.md"
                ),
                mime="text/markdown",
            )
            with st.expander(
                "Preview Draft Action Plan", expanded=False
            ):
                # Split the markdown by major numbered section so each
                # one is its own collapsed expander instead of rendering
                # the whole document as a single wall of markdown.
                intro_md, sections = _parse_action_plan_sections(
                    st.session_state.draft_action_plan
                )
                if intro_md:
                    st.markdown(intro_md)
                for section_title, section_body in sections:
                    with st.expander(section_title, expanded=False):
                        if section_body:
                            st.markdown(section_body)
            if st.button("Regenerate Draft Action Plan"):
                st.session_state.draft_action_plan = (
                    _generate_action_plan()
                )
                st.rerun()

    # Care Plan / Acuity Factors / Risk Register tabs — each tab shows
    # the summary card up top and the existing original full renderer
    # behind a single collapsed expander. No compact previews, no
    # "remaining items" sections, no duplicate renderings.
    # Care Plan / Acuity Factors / Risk Register tabs — inside each
    # "View …" outer expander, every artifact item is its own nested
    # collapsed expander so opening the outer view stays scannable.
    # Long paragraphs only render after the operator opens the
    # individual item. Compare-baseline mode keeps the original full
    # renderer for the side-by-side view.
    with tab_care:
        render_info_card(
            "Care Plan",
            _care_plan_summary(artifacts["care_plan"]),
            accent="#2563eb",
        )
        with st.expander("View care plan", expanded=False):
            care_plan = artifacts["care_plan"]
            if care_plan.get("summary"):
                st.markdown(f"**Summary:** {care_plan['summary']}")
            for section_label, key in _CARE_SECTIONS:
                for item in care_plan.get(key, []) or []:
                    _render_care_item_nested(
                        section_label, item, profile
                    )
        if compare_baseline and baseline is not None:
            with st.expander(
                "Compare against baseline (single call)", expanded=False
            ):
                _render_care_plan(baseline["care_plan"], profile)

    with tab_acuity:
        render_info_card(
            "Acuity Factors",
            _acuity_summary(artifacts["acuity_factor_recommendations"]),
            accent="#7c3aed",
        )
        with st.expander(
            "View acuity factor details", expanded=False
        ):
            acuity = artifacts["acuity_factor_recommendations"]
            if acuity.get("method_note"):
                st.caption(acuity["method_note"])
            for rec in acuity.get("recommendations", []) or []:
                _render_acuity_factor_nested(rec, profile)
        if compare_baseline and baseline is not None:
            with st.expander(
                "Compare against baseline (single call)", expanded=False
            ):
                _render_acuity_recs(
                    baseline["acuity_factor_recommendations"], profile
                )

    with tab_risk:
        render_info_card(
            "Risk Register",
            _risk_summary(artifacts["risk_register"]),
            accent="#b45309",
        )
        with st.expander("View risk register", expanded=False):
            risk = artifacts["risk_register"]
            if risk.get("method_note"):
                st.caption(risk["method_note"])
            gaps_sorted = sorted(
                risk.get("gaps", []) or [],
                key=lambda g: _SEVERITY_ORDER.get(g.get("severity"), 99),
            )
            for gap in gaps_sorted:
                _render_risk_gap_nested(gap, profile)
        if compare_baseline and baseline is not None:
            with st.expander(
                "Compare against baseline (single call)", expanded=False
            ):
                _render_risk_register(baseline["risk_register"], profile)

    # Profile — developer telemetry moved here from the sidebar.
    with tab_profile:
        render_info_card(
            "Profile",
            "Structured profile and developer telemetry.",
            accent="#6b7280",
        )
        st.markdown(
            f"**Triggered conditions:** "
            f"{', '.join(st.session_state.triggered_conditions) or '(none)'}"
        )
        st.markdown(
            f"**Evidence snippets:** {len(profile.evidence_snippets)}"
        )
        with st.expander("Recent snippets"):
            for s in profile.evidence_snippets[-10:]:
                st.text(f"[{s.source}] {s.snippet_id}: {s.claim[:60]}")
        st.markdown(
            f"**Source disagreements:** "
            f"{len(profile.source_disagreements)}"
        )
        if profile.source_disagreements:
            with st.expander("Disagreements"):
                for d in profile.source_disagreements:
                    st.text(d.field)
                    if d.discharge_claim:
                        st.caption(f"  discharge: {d.discharge_claim}")
                    if d.family_claim:
                        st.caption(f"  family: {d.family_claim}")
        with st.expander("Full profile JSON"):
            st.json(profile.model_dump(exclude_none=True))
