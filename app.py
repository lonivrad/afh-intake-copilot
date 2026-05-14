"""AFH Acuity Intake Copilot — Streamlit UI.

Stateful one-page workflow: paste source documents -> Stage 1 extraction ->
Stage 2 stateful interview -> Stage 3 synthesis -> view the three
decision-support artifacts (care plan, CARE acuity-factor recommendations,
capability-gap risk register) with expandable evidence snippets, and
optionally compare against the single-call baseline.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
from pypdf import PdfReader

from pipeline.baseline import run_baseline
from pipeline.extraction import ResidentProfile, run_initial_extraction
from pipeline.interview import InterviewSession
from pipeline.synthesis import (
    generate_acuity_factor_recommendation,
    generate_care_plan,
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
    "artifacts": None,
    "baseline_output": None,
}
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


def _render_risk_register(reg: dict, profile: ResidentProfile):
    if reg.get("method_note"):
        st.caption(reg["method_note"])
    for gap in reg.get("gaps", []):
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

    if st.session_state.profile is not None:
        st.header("Profile state")
        st.write(
            f"**Triggered conditions:** "
            f"{', '.join(st.session_state.triggered_conditions) or '(none)'}"
        )

        profile = st.session_state.profile
        st.write(f"**Evidence snippets:** {len(profile.evidence_snippets)}")
        with st.expander("Recent snippets"):
            for s in profile.evidence_snippets[-10:]:
                st.text(f"[{s.source}] {s.snippet_id}: {s.claim[:60]}")

        st.write(
            f"**Source disagreements:** {len(profile.source_disagreements)}"
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
            st.session_state.session = InterviewSession(
                profile=profile, triggered_conditions=triggered
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
    tree_id = session.trees[session.current_tree_idx]["tree_id"]
    st.markdown(
        f"_Tree:_ **{tree_id}**  |  _Node:_ **{node['node_id']}**  |  "
        f"_Shape:_ **{node['expected_answer_shape']}**"
    )
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
        st.session_state.artifacts = {
            "care_plan": care,
            "acuity_factor_recommendations": recs,
            "risk_register": reg,
        }
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

    tab_names = [
        "Care Plan",
        "Acuity Factor Recommendations",
        "Risk Register",
    ]
    tabs = st.tabs(tab_names)
    artifact_keys = [
        "care_plan",
        "acuity_factor_recommendations",
        "risk_register",
    ]
    renderers = {
        "care_plan": _render_care_plan,
        "acuity_factor_recommendations": _render_acuity_recs,
        "risk_register": _render_risk_register,
    }

    for tab, key in zip(tabs, artifact_keys):
        with tab:
            if compare_baseline and baseline is not None:
                col_staged, col_baseline = st.columns(2)
                with col_staged:
                    st.markdown("##### Staged pipeline")
                    renderers[key](artifacts[key], profile)
                with col_baseline:
                    st.markdown("##### Baseline (single call)")
                    renderers[key](baseline[key], profile)
            else:
                renderers[key](artifacts[key], profile)
