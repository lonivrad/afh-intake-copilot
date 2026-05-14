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


# ===== Per-item expanders per artifact tab (Step 10.20) =====


def _truncate(text: str, n: int = 90) -> str:
    text = text.strip()
    return text if len(text) <= n else text[:n].rstrip() + "…"


def _render_care_item_expanders(
    care_plan: dict, profile: ResidentProfile
) -> None:
    """One expander per care-plan item. Label = section · truncated
    recommendation. Body = full recommendation + rationale + evidence."""
    items_by_section = [
        ("Diabetes", "diabetes_care"),
        ("Dementia", "dementia_care"),
        ("Fall risk", "fall_risk_care"),
        ("ADLs", "adl_support"),
        ("Medications", "medication_management"),
    ]
    for section_label, key in items_by_section:
        for item in care_plan.get(key, []):
            recommendation = item.get("recommendation", "")
            label = (
                f"{section_label} · {_truncate(recommendation, 80)}"
            )
            with st.expander(label, expanded=False):
                st.markdown(recommendation)
                st.caption(f"Rationale: {item.get('rationale', '')}")
                _render_evidence_snippets(
                    profile, item.get("evidence_snippet_ids", [])
                )


def _render_acuity_factor_expanders(
    recs: dict, profile: ResidentProfile
) -> None:
    """One expander per recommended CARE acuity factor. Label = factor
    name + confidence + disclosure status. Body = WAC citation,
    disclosure quote (or gap warning), and resident-need evidence."""
    if recs.get("method_note"):
        st.caption(recs["method_note"])
    for rec in recs.get("recommendations", []):
        name = rec.get("acuity_factor_name", rec.get("acuity_factor_id", "?"))
        conf = rec.get("confidence", "—")
        disclosure = (
            "gap flagged" if rec.get("disclosure_gap_flagged") else "supported"
        )
        label = f"{name} — Confidence: {conf} | Disclosure: {disclosure}"
        with st.expander(label, expanded=False):
            st.markdown(f"`{rec.get('acuity_factor_id', '')}`")
            st.markdown(f"_WAC citation:_ {rec.get('wac_citation', '')}")
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


def _render_risk_gap_expanders(risk: dict, profile: ResidentProfile) -> None:
    """One expander per risk-register gap. Label = severity tag +
    resident_need. Body = colored severity badge, missing-support detail
    in a severity-tinted banner, disclosure quote, suggested action,
    evidence."""
    if risk.get("method_note"):
        st.caption(risk["method_note"])
    gaps_sorted = sorted(
        risk.get("gaps", []),
        key=lambda g: _SEVERITY_ORDER.get(g.get("severity"), 99),
    )
    sev_tag = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}
    for gap in gaps_sorted:
        sev = gap.get("severity", "low")
        need = gap.get("resident_need", "")
        label = _truncate(
            f"{sev_tag.get(sev, '[?]')} {need}", 100
        )
        with st.expander(label, expanded=False):
            st.markdown(
                severity_badge(sev) + f" **{need}**",
                unsafe_allow_html=True,
            )
            missing = gap.get("missing_or_weak_support", "")
            if sev == "high":
                st.error(missing)
            elif sev == "medium":
                st.warning(missing)
            else:
                st.info(missing)
            if gap.get("disclosure_quote"):
                st.markdown(f"_Disclosure quote:_ > {gap['disclosure_quote']}")
            else:
                st.markdown(
                    "_Disclosure quote:_ _(disclosure silent on this need)_"
                )
            st.markdown(
                f"_Suggested next action:_ "
                f"{gap.get('suggested_next_action', '')}"
            )
            _render_evidence_snippets(
                profile, gap.get("evidence_snippet_ids", [])
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


def _render_evidence_provenance_map(
    combined_artifacts: dict, profile: ResidentProfile
) -> None:
    """Live Evidence Provenance Viewer (Step 10.21 + compact refactor).

    Outer expander → coverage counts → referenced snippets grouped by
    source (each snippet its own collapsed expander) → compact
    unreferenced section (also one expander per snippet). No full
    verbatim text is rendered outside an individual snippet expander.
    """
    with st.expander("🔍 View Evidence Provenance Map", expanded=False):
        snippets = profile.evidence_snippets

        # Evidence statistics (counts by source) — always visible.
        discharge_count = sum(1 for s in snippets if s.source == "discharge")
        family_count = sum(1 for s in snippets if s.source == "family")
        operator_count = sum(1 for s in snippets if s.source == "operator")
        total = len(snippets)

        st.subheader("Evidence Coverage")
        st.markdown(
            f"- Discharge summary: {discharge_count} snippets\n"
            f"- Family notes: {family_count} snippets\n"
            f"- Operator interview: {operator_count} snippets\n"
            f"- **Total evidence base: {total} snippets**"
        )

        # Pre-compute references once per snippet so we can group cleanly.
        snippet_refs: dict[str, list[str]] = {}
        unreferenced_list = []
        for s in snippets:
            refs = find_snippet_references(s.snippet_id, combined_artifacts)
            snippet_refs[s.snippet_id] = refs
            if not refs:
                unreferenced_list.append(s)

        # Referenced snippets grouped by source. Each snippet renders as
        # its own collapsed expander — full text only on expand.
        source_meta = [
            ("discharge", "Discharge summary evidence"),
            ("family", "Family notes evidence"),
            ("operator", "Operator interview evidence"),
        ]
        for source_key, source_heading in source_meta:
            in_source = [
                s
                for s in snippets
                if s.source == source_key
                and snippet_refs[s.snippet_id]
            ]
            if not in_source:
                continue
            st.subheader(source_heading)
            for s in in_source:
                label = (
                    f"{s.snippet_id} · {s.source} · "
                    f"{_preview_text(s.verbatim_text)}"
                )
                with st.expander(label, expanded=False):
                    st.markdown(f"**Full text:** {s.verbatim_text}")
                    st.markdown("**Referenced in:**")
                    for ref in snippet_refs[s.snippet_id]:
                        st.markdown(f"- {ref}")

        # Unreferenced evidence — compact: id + source + preview only.
        if unreferenced_list:
            st.subheader(
                f"⚠ Unreferenced Evidence ({len(unreferenced_list)})"
            )
            st.markdown(
                "These snippets were extracted but not cited in final "
                "artifacts. Expand a row for full text."
            )
            for s in unreferenced_list:
                label = (
                    f"{s.snippet_id} · {s.source} · "
                    f"{_preview_text(s.verbatim_text)}"
                )
                with st.expander(label, expanded=False):
                    st.markdown(f"**Full text:** {s.verbatim_text}")
                    st.markdown(f"**Claim:** {s.claim}")
                    st.markdown(
                        "_(not referenced by any committed artifact)_"
                    )


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
        plan = artifacts["care_plan"]
        acuity_recs = artifacts["acuity_factor_recommendations"]
        risk_register = artifacts["risk_register"]
        # Single source of truth for the unresolved-disagreements list:
        # whatever the Unresolved Disagreements section renders is also
        # what the provenance box counts, so the two cannot diverge.
        unresolved_disagreements = plan["unresolved_disagreements"]
        open_questions = plan.get("open_questions_for_followup", [])

        # 1. Talking points — at the top.
        if decision is not None:
            tps = decision.get("family_call_talking_points", [])
            if tps:
                st.subheader("Talking points for the family call")
                for tp in tps:
                    st.markdown(f"- {tp}")

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

        # 4. Unresolved disagreements — only if any exist.
        if len(unresolved_disagreements) > 0:
            st.subheader("Unresolved disagreements")
            for d in unresolved_disagreements:
                st.markdown(f"- {d}")

        # 5. Open questions for follow-up — only if any exist.
        if len(open_questions) > 0:
            st.subheader("Open questions for follow-up")
            for q in open_questions:
                # Strip a leading "N. " numeric prefix so we don't render
                # double-formatted bullets like "- 1. FOO" when the model
                # already numbered its own list.
                cleaned = re.sub(r"^\d+\.\s*", "", q)
                st.markdown(f"- {cleaned}")

    # Action Plan tab — generates the Draft Admission Action Plan
    # markdown from existing artifacts on demand. Preview is collapsed
    # by default so the tab opens with just intro + button visible.
    with tab_action:
        st.markdown(
            "Generate a draft admission worksheet from the current "
            "intake artifacts. This is not a legal agreement and "
            "requires operator review."
        )
        if st.button("Generate Draft Admission Action Plan"):
            resident_name = (
                profile.demographics.resident_name_placeholder
                or "Resident (name not documented)"
            )
            st.session_state.admission_action_plan = (
                generate_admission_action_plan(
                    resident_name=resident_name,
                    afh_name="AFH Operator",
                    artifacts={
                        **artifacts,
                        "intake_decision": decision,
                    },
                    profile=profile,
                )
            )
        plan_text = st.session_state.get("admission_action_plan")
        if plan_text:
            st.download_button(
                label="Download Draft Action Plan",
                data=plan_text,
                file_name=(
                    "admission_action_plan_"
                    f"{datetime.now().strftime('%Y%m%d')}.md"
                ),
                mime="text/markdown",
            )
            with st.expander(
                "Preview Draft Action Plan", expanded=False
            ):
                st.markdown(plan_text)

    # Care Plan / Acuity Factors / Risk Register — existing renderers
    # unchanged.
    def _render_in_tab(key: str, renderer) -> None:
        if compare_baseline and baseline is not None:
            col_staged, col_baseline = st.columns(2)
            with col_staged:
                st.markdown("##### Staged pipeline")
                renderer(artifacts[key], profile)
            with col_baseline:
                st.markdown("##### Baseline (single call)")
                renderer(baseline[key], profile)
        else:
            renderer(artifacts[key], profile)

    with tab_care:
        st.info(_care_plan_summary(artifacts["care_plan"]))
        _render_care_item_expanders(artifacts["care_plan"], profile)
        if compare_baseline and baseline is not None:
            with st.expander(
                "Compare against baseline (single call)", expanded=False
            ):
                _render_care_plan(baseline["care_plan"], profile)
    with tab_acuity:
        st.info(
            _acuity_summary(artifacts["acuity_factor_recommendations"])
        )
        _render_acuity_factor_expanders(
            artifacts["acuity_factor_recommendations"], profile
        )
        if compare_baseline and baseline is not None:
            with st.expander(
                "Compare against baseline (single call)", expanded=False
            ):
                _render_acuity_recs(
                    baseline["acuity_factor_recommendations"], profile
                )
    with tab_risk:
        st.warning(_risk_summary(artifacts["risk_register"]))
        _render_risk_gap_expanders(artifacts["risk_register"], profile)
        if compare_baseline and baseline is not None:
            with st.expander(
                "Compare against baseline (single call)", expanded=False
            ):
                _render_risk_register(baseline["risk_register"], profile)

    # Profile — developer telemetry moved here from the sidebar.
    with tab_profile:
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
