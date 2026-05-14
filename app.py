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
from pathlib import Path

import streamlit as st
from pypdf import PdfReader

from pipeline.baseline import run_baseline
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


_RECOMMENDATION_LABELS = {
    "accept": "ACCEPT",
    "accept_with_conditions": "ACCEPT WITH CONDITIONS",
    "hold_for_review": "HOLD FOR REVIEW",
}


def _render_intake_decision(decision: dict) -> None:
    rec = decision.get("recommendation", "")
    rationale_full = decision.get("rationale", "")
    rationale_short = _first_two_sentences(rationale_full)
    conditions = decision.get("conditions_before_admission", [])
    label = _RECOMMENDATION_LABELS.get(rec, rec.upper())

    banner_body = f"### Recommendation: {label}\n\n{rationale_short}"
    if rec == "accept":
        st.success(banner_body)
    elif rec == "accept_with_conditions":
        st.warning(banner_body)
    else:  # hold_for_review or unknown — treat as red banner
        st.error(banner_body)

    st.subheader("Conditions before admission")
    if rec == "accept":
        st.write(
            "No conditions — this resident appears to fit the home's "
            "disclosed capabilities."
        )
    else:
        for cond in conditions:
            st.markdown(f"- {cond}")


def _render_risk_register(reg: dict, profile: ResidentProfile):
    if reg.get("method_note"):
        st.caption(reg["method_note"])
    gaps_sorted = sorted(
        reg.get("gaps", []),
        key=lambda g: _SEVERITY_ORDER.get(g.get("severity"), 99),
    )
    for gap in gaps_sorted:
        sev = gap["severity"]
        st.markdown(f"**[{sev.upper()}] {gap['resident_need']}**")
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
    # sentences) + conditions. The four-metric row is intentionally
    # removed — the banner now carries operator priority directly.
    if decision is not None:
        _render_intake_decision(decision)

    st.divider()

    tab_summary, tab_care, tab_acuity, tab_risk, tab_profile = st.tabs(
        ["Summary", "Care Plan", "Acuity Factors", "Risk Register", "Profile"]
    )

    # Summary — readable in under 30 seconds: provenance box, talking
    # points, unresolved disagreements, open follow-up questions. No
    # expanders.
    with tab_summary:
        plan = artifacts["care_plan"]
        acuity_recs = artifacts["acuity_factor_recommendations"]
        risk_register = artifacts["risk_register"]
        # Single source of truth for the unresolved-disagreements list:
        # whatever the Unresolved Disagreements section renders is also
        # what the provenance box counts, so the two cannot diverge.
        unresolved_disagreements = plan["unresolved_disagreements"]

        # Provenance box — all numbers computed live from existing objects.
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

        if decision is not None:
            tps = decision.get("family_call_talking_points", [])
            if tps:
                st.subheader("Talking points for the family call")
                for tp in tps:
                    st.markdown(f"- {tp}")
        if unresolved_disagreements:
            st.subheader("Unresolved disagreements")
            for d in unresolved_disagreements:
                st.markdown(f"- {d}")
        open_qs = plan.get("open_questions_for_followup", [])
        if open_qs:
            st.subheader("Open questions for follow-up")
            for q in open_qs:
                # Strip a leading "N. " numeric prefix so we don't render
                # double-formatted bullets like "- 1. FOO" when the model
                # already numbered its own list.
                cleaned = re.sub(r"^\d+\.\s*", "", q)
                st.markdown(f"- {cleaned}")

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
        _render_in_tab("care_plan", _render_care_plan)
    with tab_acuity:
        st.info(
            _acuity_summary(artifacts["acuity_factor_recommendations"])
        )
        _render_in_tab(
            "acuity_factor_recommendations", _render_acuity_recs
        )
    with tab_risk:
        st.warning(_risk_summary(artifacts["risk_register"]))
        _render_in_tab("risk_register", _render_risk_register)

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
