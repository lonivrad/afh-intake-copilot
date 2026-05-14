"""Step 10: Evaluation harness.

Loops through all 8 synthetic test cases and runs each through both:
- the full staged pipeline (Stage 1 extraction -> auto-answered Stage 2
  interview -> Stage 3 synthesis)
- the single-call baseline

Scores each output against the case ground_truth and writes:
- evals/results/results_full.json
- evals/results/results_baseline.json

Prints a comparison table to stdout.

The auto-answerer is a Claude call that simulates an AFH operator. It sees
the current interview question and the case source documents (and ground
truth only as background — never the EVALUATION fields like
should_recommend_factors, which would bias the run).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

# Allow running this script from anywhere — put the repo root on sys.path
# so the `pipeline` package resolves.
_REPO_ROOT_FOR_IMPORTS = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORTS))

import anthropic
from dotenv import load_dotenv

from pipeline.baseline import run_baseline
from pipeline.extraction import run_initial_extraction
from pipeline.interview import InterviewSession
from pipeline.synthesis import (
    generate_acuity_factor_recommendation,
    generate_care_plan,
    generate_risk_register,
)

load_dotenv()

MODEL_ID = "claude-sonnet-4-6"
REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "evals" / "results"

INTERVIEW_QUESTION_CAP = 60  # safety stop in case of branching loop bug


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


# ===== Auto-answerer =====


AUTO_ANSWER_SYSTEM = """You are simulating an Adult Family Home (AFH) operator answering an intake interview question for a placement candidate. The operator has read the resident's discharge summary and family-reported notes and has no other information.

YOUR JOB: produce a SHORT, NATURAL operator answer (under 60 words) to the current question based on the source documents.

DISCIPLINE:
- Answer ONLY the current question. Do not preview future questions.
- Do not invent facts beyond the source documents. If the sources do not support a clear answer, say "unknown" or "I'm not sure from what I've been given."
- Sound like a real operator paraphrasing — not a clinical recitation. Avoid copy-pasting source text verbatim.
- For boolean/yes-no questions, answer "yes" or "no" with a brief reason.
- For enum questions, pick the option that best fits the sources.
- For numeric questions, give the number from the sources or "unknown."
- Do NOT cite or reference the ground-truth evaluation targets (factor lists, expected gaps) even if you happen to see them. Answer only from the source documents.

Output ONLY the operator's answer text. No preamble, no labels."""


def auto_answer(
    client: anthropic.Anthropic,
    node: dict,
    source_docs: dict,
    case_disagreement_hint: str | None = None,
) -> str:
    """Generate a single operator answer for the given interview node."""
    user_lines = [
        f"CURRENT QUESTION: {node['question_text']}",
        f"Expected answer shape: {node['expected_answer_shape']}",
    ]
    if node.get("answer_options"):
        user_lines.append(f"Suggested values: {', '.join(node['answer_options'])}")
    if node.get("context_hint"):
        user_lines.append(f"Background context: {node['context_hint']}")
    user_lines.extend(
        [
            "",
            "=== DISCHARGE SUMMARY ===",
            source_docs["discharge_summary"],
            "",
            "=== FAMILY-REPORTED NOTES ===",
            source_docs["family_notes"],
        ]
    )
    if case_disagreement_hint:
        user_lines.extend(
            [
                "",
                "(Background only — do not echo verbatim) Known source disagreement: "
                + case_disagreement_hint,
            ]
        )

    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=256,
        system=AUTO_ANSWER_SYSTEM,
        messages=[{"role": "user", "content": "\n".join(user_lines)}],
    )
    text_blocks = [b.text for b in response.content if b.type == "text"]
    return " ".join(text_blocks).strip()


# ===== Pipeline runners =====


def run_full_pipeline(
    case: dict, dshs_rules: dict, client: anthropic.Anthropic
) -> dict:
    source_docs = {
        "discharge_summary": case["inputs"]["discharge_summary"],
        "family_notes": case["inputs"]["family_notes"],
    }
    disagreement_hint = case["ground_truth"].get("known_source_disagreement")

    # Stage 1
    profile, triggered = run_initial_extraction(
        discharge_summary=source_docs["discharge_summary"],
        family_notes=source_docs["family_notes"],
        disclosure_text=MOCK_DISCLOSURE,
    )

    # Stage 2 (auto-answered)
    n_questions = 0
    if triggered:
        session = InterviewSession(profile=profile, triggered_conditions=triggered)
        while n_questions < INTERVIEW_QUESTION_CAP:
            node = session.get_next_question()
            if node is None:
                break
            answer = auto_answer(client, node, source_docs, disagreement_hint)
            session.submit_answer(answer)
            n_questions += 1

    # Stage 3
    care = generate_care_plan(profile, source_docs)
    recs = generate_acuity_factor_recommendation(
        profile, source_docs, MOCK_DISCLOSURE, dshs_rules
    )
    reg = generate_risk_register(profile, MOCK_DISCLOSURE)

    return {
        "care_plan": care,
        "acuity_factor_recommendations": recs,
        "risk_register": reg,
        "_meta": {
            "triggered_conditions": triggered,
            "interview_questions_answered": n_questions,
            "evidence_snippet_count": len(profile.evidence_snippets),
            "source_disagreement_count": len(profile.source_disagreements),
            "valid_snippet_ids": [s.snippet_id for s in profile.evidence_snippets],
        },
    }


def run_baseline_pipeline(case: dict, dshs_rules: dict) -> dict:
    out = run_baseline(
        discharge_summary=case["inputs"]["discharge_summary"],
        family_notes=case["inputs"]["family_notes"],
        disclosure_text=MOCK_DISCLOSURE,
        dshs_rules=dshs_rules,
    )
    out["_meta"] = {"valid_snippet_ids": None}
    return out


# ===== Scoring =====


_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "at", "with",
    "that", "this", "these", "those", "must", "should", "may", "can",
    "could", "would", "if", "no", "not", "be", "is", "are", "was", "were",
    "as", "it", "its", "by", "on", "from", "have", "has", "had", "do",
    "does", "did", "will", "all", "any", "but", "what", "which", "who",
    "when", "where", "they", "them", "their", "her", "his", "she", "he",
    "than", "into", "out", "up", "down", "over", "under", "also", "more",
    "less", "such", "via",
}


def _extract_keywords(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z\-]+", text.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) >= 3}


def _score_capability_gaps(
    output_gaps: list[dict], expected_gaps: list[str]
) -> dict:
    """Approximate gap precision/recall via keyword overlap.

    Output is fuzzy — designed as a signal, not ground truth. >= 3 shared
    content keywords between an output gap (resident_need +
    missing_or_weak_support + suggested_next_action) and an expected gap
    counts as a match.
    """
    if not expected_gaps and not output_gaps:
        return {"precision": 1.0, "recall": 1.0, "matched_expected": 0}
    if not expected_gaps:
        return {"precision": 0.0, "recall": 1.0, "matched_expected": 0}
    if not output_gaps:
        return {"precision": 1.0, "recall": 0.0, "matched_expected": 0}

    expected_kw = [_extract_keywords(g) for g in expected_gaps]
    output_kw = [
        _extract_keywords(
            " ".join(
                [
                    g.get("resident_need", ""),
                    g.get("missing_or_weak_support", ""),
                    g.get("suggested_next_action", ""),
                ]
            )
        )
        for g in output_gaps
    ]

    out_matched = sum(
        1
        for ow in output_kw
        if max((len(ow & ew) for ew in expected_kw), default=0) >= 3
    )
    exp_matched = sum(
        1
        for ew in expected_kw
        if max((len(ow & ew) for ow in output_kw), default=0) >= 3
    )

    return {
        "precision": out_matched / len(output_gaps) if output_gaps else 0.0,
        "recall": exp_matched / len(expected_kw) if expected_kw else 0.0,
        "matched_expected": exp_matched,
    }


def score_output(case: dict, output: dict, label: str) -> dict:
    gt = case["ground_truth"]
    should_rec = set(gt["should_recommend_factors"])
    should_not_rec = set(gt["should_not_recommend_factors"])
    expected_gaps = gt.get("expected_capability_gaps", [])
    expected_disagreement = gt.get("known_source_disagreement") is not None

    recs = output["acuity_factor_recommendations"]
    recommended_ids = {
        r["acuity_factor_id"] for r in recs.get("recommendations", [])
    }

    tp = recommended_ids & should_rec
    fp_against_negative = recommended_ids & should_not_rec
    fp_total = recommended_ids - should_rec
    fn = should_rec - recommended_ids

    if recommended_ids:
        precision = len(tp) / len(recommended_ids)
    else:
        precision = 1.0 if not should_rec else 0.0
    recall = len(tp) / len(should_rec) if should_rec else 1.0

    # Hallucination = cited snippet id NOT in the staged-pipeline profile.
    # Only computable for full pipeline (baseline IDs are baseline-internal
    # and have no traceable layer); reported as None for baseline.
    hallucinations: int | None = None
    valid_ids = output.get("_meta", {}).get("valid_snippet_ids")
    if valid_ids is not None:
        valid_set = set(valid_ids)
        hallucinations = 0
        plan = output["care_plan"]
        for section in (
            "diabetes_care",
            "dementia_care",
            "fall_risk_care",
            "adl_support",
            "medication_management",
        ):
            for item in plan.get(section, []):
                for eid in item.get("evidence_snippet_ids", []):
                    if eid not in valid_set:
                        hallucinations += 1
        for rec in recs.get("recommendations", []):
            for eid in rec.get("resident_need_evidence", []):
                if eid not in valid_set:
                    hallucinations += 1
        for gap in output["risk_register"].get("gaps", []):
            for eid in gap.get("evidence_snippet_ids", []):
                if eid not in valid_set:
                    hallucinations += 1

    # Source-disagreement detection (binary): either Stage 1 produced
    # source_disagreements, or the care plan surfaced unresolved_disagreements.
    detected = False
    meta = output.get("_meta", {})
    if meta.get("source_disagreement_count", 0) > 0:
        detected = True
    if output["care_plan"].get("unresolved_disagreements"):
        detected = True

    gap_metrics = _score_capability_gaps(
        output["risk_register"].get("gaps", []), expected_gaps
    )

    return {
        "pipeline": label,
        "case_id": case["case_id"],
        "recommended_factor_ids": sorted(recommended_ids),
        "should_recommend": sorted(should_rec),
        "should_not_recommend": sorted(should_not_rec),
        "true_positives": sorted(tp),
        "false_positives_total": sorted(fp_total),
        "false_positives_against_negative_list": sorted(fp_against_negative),
        "false_negatives": sorted(fn),
        "precision": precision,
        "recall": recall,
        "hallucination_count": hallucinations,
        "disagreement_expected": expected_disagreement,
        "disagreement_detected": detected,
        "disagreement_correct": detected == expected_disagreement,
        "capability_gap_precision": gap_metrics["precision"],
        "capability_gap_recall": gap_metrics["recall"],
        "capability_gap_flagged_count": len(
            output["risk_register"].get("gaps", [])
        ),
        "capability_gap_expected_count": len(expected_gaps),
        "interview_questions_answered": meta.get(
            "interview_questions_answered"
        ),
    }


# ===== Comparison table =====


def print_comparison_table(full_scores: list[dict], baseline_scores: list[dict]) -> str:
    """Build and print a side-by-side comparison; returns the table string."""
    rows = []
    header = (
        f"{'case':<10} "
        f"{'full P':>7} {'full R':>7} "
        f"{'base P':>7} {'base R':>7} "
        f"{'halluc f':>9} {'halluc b':>9} "
        f"{'disagr f':>9} {'disagr b':>9} "
        f"{'gap P f':>8} {'gap P b':>8}"
    )
    rows.append(header)
    rows.append("-" * len(header))

    full_by_id = {s["case_id"]: s for s in full_scores}
    base_by_id = {s["case_id"]: s for s in baseline_scores}

    for cid in sorted(set(full_by_id) | set(base_by_id)):
        f = full_by_id.get(cid, {})
        b = base_by_id.get(cid, {})
        def fmt_num(v, w):
            if v is None:
                return f"{'n/a':>{w}}"
            if isinstance(v, float):
                return f"{v:>{w}.2f}"
            return f"{v:>{w}}"
        def fmt_bool(v, w):
            if v is None:
                return f"{'n/a':>{w}}"
            return f"{'yes' if v else 'no':>{w}}"
        row = (
            f"{cid:<10} "
            f"{fmt_num(f.get('precision'), 7)} {fmt_num(f.get('recall'), 7)} "
            f"{fmt_num(b.get('precision'), 7)} {fmt_num(b.get('recall'), 7)} "
            f"{fmt_num(f.get('hallucination_count'), 9)} {fmt_num(b.get('hallucination_count'), 9)} "
            f"{fmt_bool(f.get('disagreement_detected'), 9)} {fmt_bool(b.get('disagreement_detected'), 9)} "
            f"{fmt_num(f.get('capability_gap_precision'), 8)} {fmt_num(b.get('capability_gap_precision'), 8)}"
        )
        rows.append(row)

    # Summary line: macro-averaged
    def macro(scores, key):
        vals = [s.get(key) for s in scores if isinstance(s.get(key), (int, float))]
        return sum(vals) / len(vals) if vals else None

    def fmt_avg(v, w):
        if v is None:
            return f"{'n/a':>{w}}"
        if isinstance(v, float):
            return f"{v:>{w}.2f}"
        return f"{v:>{w}}"

    rows.append("-" * len(header))
    rows.append(
        f"{'avg':<10} "
        f"{fmt_avg(macro(full_scores, 'precision'), 7)} {fmt_avg(macro(full_scores, 'recall'), 7)} "
        f"{fmt_avg(macro(baseline_scores, 'precision'), 7)} {fmt_avg(macro(baseline_scores, 'recall'), 7)} "
        f"{fmt_avg(macro(full_scores, 'hallucination_count'), 9)} {fmt_avg(macro(baseline_scores, 'hallucination_count'), 9)} "
        f"{'':>9} {'':>9} "
        f"{fmt_avg(macro(full_scores, 'capability_gap_precision'), 8)} {fmt_avg(macro(baseline_scores, 'capability_gap_precision'), 8)}"
    )

    table = "\n".join(rows)
    print(table)
    return table


# ===== Main =====


def main() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; aborting.", file=sys.stderr)
        sys.exit(1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    case_paths = sorted(
        (REPO_ROOT / "data" / "test_cases").glob("case_*.json")
    )
    dshs_rules = json.loads(
        (REPO_ROOT / "data" / "dshs_rules.json").read_text()
    )

    client = anthropic.Anthropic()

    full_results: list[dict] = []
    baseline_results: list[dict] = []
    full_scores: list[dict] = []
    baseline_scores: list[dict] = []

    for case_path in case_paths:
        case = json.loads(case_path.read_text())
        cid = case["case_id"]
        print(f"\n=== {cid}: {case['description']} ===", flush=True)
        t0 = time.time()

        # Full staged pipeline
        try:
            full_out = run_full_pipeline(case, dshs_rules, client)
            full_score = score_output(case, full_out, "full")
            full_results.append({"case": case, "output": full_out, "score": full_score})
            full_scores.append(full_score)
            print(
                f"  full: P={full_score['precision']:.2f} R={full_score['recall']:.2f} "
                f"halluc={full_score['hallucination_count']} "
                f"interview_q={full_score['interview_questions_answered']} "
                f"({time.time() - t0:.1f}s)",
                flush=True,
            )
        except Exception as exc:
            print(f"  full FAILED: {exc}", file=sys.stderr, flush=True)
            traceback.print_exc()
            full_results.append({"case": case, "error": str(exc)})

        # Baseline
        t1 = time.time()
        try:
            base_out = run_baseline_pipeline(case, dshs_rules)
            base_score = score_output(case, base_out, "baseline")
            baseline_results.append(
                {"case": case, "output": base_out, "score": base_score}
            )
            baseline_scores.append(base_score)
            print(
                f"  baseline: P={base_score['precision']:.2f} R={base_score['recall']:.2f} "
                f"({time.time() - t1:.1f}s)",
                flush=True,
            )
        except Exception as exc:
            print(f"  baseline FAILED: {exc}", file=sys.stderr, flush=True)
            traceback.print_exc()
            baseline_results.append({"case": case, "error": str(exc)})

        # Progressive save after each case
        (RESULTS_DIR / "results_full.json").write_text(
            json.dumps(full_results, indent=2, default=str)
        )
        (RESULTS_DIR / "results_baseline.json").write_text(
            json.dumps(baseline_results, indent=2, default=str)
        )

    print("\n" + "=" * 80)
    print("COMPARISON TABLE")
    print("=" * 80)
    table = print_comparison_table(full_scores, baseline_scores)
    (RESULTS_DIR / "comparison_table.txt").write_text(table)
    print("\nResults saved to:")
    print(f"  {RESULTS_DIR / 'results_full.json'}")
    print(f"  {RESULTS_DIR / 'results_baseline.json'}")
    print(f"  {RESULTS_DIR / 'comparison_table.txt'}")


if __name__ == "__main__":
    main()
