# AFH Acuity Intake Copilot

A staged GenAI pipeline for the Adult Family Home (AFH) intake conversation
in Washington State. Built against committed state `caa3bea`.

## 1. Context, user, problem

**User.** Washington State Adult Family Home (AFH) operators. AFHs are
small, residentially-zoned licensed homes that take 2-6 elderly or
disabled residents — typically Medicaid-funded. The operator is the
person on the phone with the discharging hospital and the family,
deciding whether they can safely accept the resident and how the
placement will be paid.

**Workflow being improved.** The pre-admission intake: read the
discharge summary, listen to the family, cross-check against the home's
DSHS Disclosure of Services, and decide whether to accept. Today this
is paper-driven, intuition-heavy, and inconsistent across operators.

**Why it matters.**

- **Revenue leak from under-billing.** WA AFH Medicaid payment is set
  by the DSHS CARE assessment (Groups A-Low through E-High per WAC
  388-106-0125). Acuity factors the operator forgets to mention to the
  case manager during the CARE interview translate directly to lower
  classifications and lower daily rates. Operators routinely under-
  document insulin scope, behavioral resistance, and fall risk — all
  scored acuity factors in WAC 388-106-0095, -0100, and -0105.
- **Safety risk from mismatched placement.** AFHs that accept a
  resident they cannot safely manage (exit-seeking dementia without
  secured egress, sliding-scale insulin without delegating RN, two-
  person transfer with single overnight staff) face WAC 388-76
  enforcement, involuntary discharge, and resident harm. Today the
  capability-vs-need check happens in the operator's head, not against
  the home's written disclosure.

## 2. Solution and design

**Flow.** Intake source documents → Stage 1 extraction → Stage 2
stateful interview → Stage 3 synthesis (three artifacts) → Stage 4
operator-facing decision view.

1. **Stage 1 — Initial Extraction** (`pipeline/extraction.py`). The
   discharge summary, family-reported notes, and the AFH disclosure
   text are fed to Claude with a forced tool call against a Pydantic
   `ResidentProfile` schema. Every populated field carries at least
   one `EvidenceSnippet` with the verbatim quote that supports it.
   Material conflicts between discharge and family are recorded as
   `SourceDisagreement` entries — the field is populated with the
   safer interpretation and the disagreement is preserved.
2. **Stage 2 — Stateful Interview** (`pipeline/interview.py`). For
   each triggered condition (diabetes / dementia / fall risk), an
   `InterviewSession` walks a JSON questioning tree in canonical order.
   The operator answers in plain language; a deterministic local
   parser handles boolean/numeric/enum patterns first, with Claude as
   a tightly-scoped fallback. Each answer mutates the shared profile
   at the exact `updates_profile_field` path and records an operator-
   sourced evidence snippet. Branching is governed by the tree, never
   by the LLM.
3. **Stage 3 — Synthesis** (`pipeline/synthesis.py`). Three forced-
   tool-call functions over the assembled profile produce:
   - a care plan organized by condition / ADLs / medications, with
     `evidence_snippet_ids` on every item;
   - a list of CARE acuity-factor recommendations (drawn from
     `data/dshs_rules.json`, twelve acuity factors per
     WAC 388-106-0090/-0095/-0100/-0105/-0110/-0125) with disclosure
     match-or-gap per factor;
   - a capability-gap risk register against the AFH disclosure, with
     severity, suggested next action, and verbatim disclosure quote
     where available.
4. **Stage 4 — Intake Decision** (`pipeline/synthesis.py:
   generate_intake_decision`). A re-organizer that consumes the three
   artifacts plus profile source-disagreements and emits a single
   `IntakeDecision` (accept / accept_with_conditions /
   hold_for_review) with rationale, pre-admission conditions, family-
   call talking points, and existing-ID evidence references. It does
   not re-read source documents.

A baseline single-call workflow (`pipeline/baseline.py`) does the
entire pipeline in one prompt for comparison.

![Architecture](docs/architecture.png)

**Why a staged pipeline beats a one-shot LLM.**

- **Stateful interview captures operator-tacit information.** The
  operator's knowledge of overnight staffing, prior placements, and
  family communication preferences is not in the discharge summary
  and is not in the family notes. A one-shot LLM never asks for it.
  The tree-driven Stage 2 forces these into the record.
- **Three-way evidence grounding.** Every claim in the artifacts cites
  an `evidence_snippet_id` that traces to verbatim text from either
  the discharge (Stage 1), the family notes (Stage 1), or the operator
  interview (Stage 2). Min-length=1 on the Pydantic evidence lists
  rejects unsupported claims at validation time.
- **Reconciliation of source disagreements.** Stage 1 detects
  material conflicts between discharge and family on the same field
  (orientation, fall pattern, medication scope). The disagreement is
  carried forward; Stage 2 can append an operator clarification to
  the same record; Stage 3 surfaces it in the care plan; Stage 4
  factors it into the recommendation.

**Where GenAI adds value vs. where the system is deterministic.**

| Component | Approach |
|---|---|
| Parsing unstructured discharge / family text into structured fields | GenAI (Claude tool use against Pydantic schema) |
| Parsing operator natural-language answers into a typed value | Deterministic local parser first (boolean / numeric / enum synonyms), Claude fallback only when local parser is not confident |
| Narrative synthesis of care plan / recommendations / risk register with evidence binding | GenAI (Claude tool use, evidence-ID-required schema) |
| Questioning tree branching (`next_node_logic`) | Deterministic — controlled by the tree JSON, not the model |
| DSHS acuity-factor reference lookups | Deterministic — `data/dshs_rules.json` is the authoritative catalog |
| Risk-register severity sorting | Deterministic — `{high: 0, medium: 1, low: 2}` at render time |
| Intake recommendation logic (accept / conditions / hold) | Deterministic rules expressed in the Stage 4 system prompt; the LLM applies them top-to-bottom |

## 3. Evaluation and results

<!-- VERIFY THESE NUMBERS BEFORE COMMIT -->

All numbers in this section are read directly from
`evals/results/results_full.json` and
`evals/results/results_baseline.json`, produced by
`evals/run_evals.py` against the eight synthetic test cases in
`data/test_cases/`. The full pipeline ran Stage 1 + an auto-answered
Stage 2 + Stage 3; the baseline ran `run_baseline(...)` once.

**Per-case scores:**

| case | full P | full R | base P | base R | halluc f | halluc b | disagr f | disagr b | gap P f | gap P b | gap R f | gap R b |
|------|-------:|-------:|-------:|-------:|---------:|---------:|:--------:|:--------:|--------:|--------:|--------:|--------:|
| case_01 | 0.00 | 1.00 | 0.00 | 1.00 | 0 | n/a | no | yes | 0.00 | 0.00 | 1.00 | 1.00 |
| case_02 | 0.60 | 1.00 | 0.50 | 1.00 | 0 | n/a | yes | yes | 0.83 | 0.60 | 1.00 | 0.50 |
| case_03 | 0.25 | 1.00 | 0.20 | 1.00 | 0 | n/a | yes | yes | 0.75 | 0.60 | 1.00 | 1.00 |
| case_04 | 0.80 | 1.00 | 0.67 | 1.00 | 0 | n/a | yes | yes | 0.86 | 1.00 | 1.00 | 1.00 |
| case_05 | 0.50 | 1.00 | 0.50 | 1.00 | 0 | n/a | no  | yes | 1.00 | 1.00 | 1.00 | 1.00 |
| case_06 | 0.90 | 1.00 | 0.75 | 1.00 | 0 | n/a | yes | yes | 0.90 | 0.89 | 1.00 | 1.00 |
| case_07 | 0.25 | 1.00 | 0.20 | 1.00 | 0 | n/a | yes | yes | 0.60 | 0.80 | 0.67 | 0.67 |
| case_08 | 0.40 | 1.00 | 0.33 | 1.00 | 0 | n/a | yes | yes | 1.00 | 1.00 | 1.00 | 0.67 |

**Macro averages (8 cases):**

| Metric | Full pipeline | Baseline |
|---|---:|---:|
| Acuity factor precision | **0.46** | 0.39 |
| Acuity factor recall | 1.00 | 1.00 |
| Hallucination count (cited snippet IDs not in profile) | **0.00** | n/a (baseline has no traceable evidence layer) |
| Capability-gap precision | 0.74 | 0.74 |
| Capability-gap recall | **0.96** | 0.85 |
| Source-disagreement detection correct (binary, 8 cases) | **4 / 8** | 2 / 8 |

The full pipeline wins on precision (+0.07), capability-gap recall
(+0.11), hallucination discipline (0 vs unmeasurable), and
disagreement-detection correctness (4 vs 2). Recall is tied — both
pipelines reliably surface every required factor; the staged pipeline
just over-recommends less.

### Three qualitative examples

**Clear win — case_06 (all three conditions, complex multi-system acuity).**

- Ground truth expects 9 factors; should-NOT-recommend = `CARE-TRANSFER-2PERSON`, `CARE-WOUND-CARE`.
- Full pipeline recommended 10 factors — caught all 9 expected plus one false positive (`CARE-WOUND-CARE`). Precision **0.90**.
- Baseline recommended 12 factors — caught the 9 expected plus three false positives (`CARE-MOOD-DEPRESS`, `CARE-TRANSFER-2PERSON`, `CARE-WOUND-CARE`). Precision **0.75**.
- Full first high-severity gap: *"Basal-bolus sliding-scale insulin administration (Humalog four times daily based on fingerstick BG plus glargine 25 units at bedtime) requir…"* — specific to the resident's regimen.
- Baseline first high-severity gap: *"Sliding-scale Humalog (four times daily) and glargine (bedtime) insulin administration by AFH caregivers."* — same topic, less specificity, and the baseline still over-fired `CARE-TRANSFER-2PERSON` despite no documented two-person transfer need.

**Tie — case_05 (dementia + fall risk, cognitive-mobility mismatch).**

- Ground truth expects `CARE-BEHAV-DEMENTIA`, `CARE-COG-IMPAIR`, `CARE-FALL-RISK`, `CARE-MED-ADMIN-MULTI`.
- Both pipelines recommended the same 8 factors: the 4 expected plus 4 false positives (`CARE-INCONT-BB`, `CARE-MOOD-DEPRESS`, `CARE-TOILET-ASSIST`, `CARE-WANDER-EXIT`). Precision **0.50 vs 0.50**, recall **1.00 vs 1.00**, gap precision **1.00 vs 1.00**.
- Full first high-severity gap: *"Nighttime fall prevention for a resident who frequently attempts unassisted ambulation at night, is unsteady without a walker, inconsistentl…"*
- Baseline first high-severity gap: *"Overnight fall prevention for a resident who frequently attempts to stand and ambulate unassisted at night, resulting in a documented fall w…"*
- Both pipelines converged on the same operationally-useful framing. The only edge for the full pipeline on this case is hallucination discipline (0 vs unmeasurable).

**Honest failure — case_01 (well-controlled type 2 diabetes, simple case).**

- Ground truth expects **zero** acuity factors (`should_recommend_factors: []`). The resident is on metformin only, A1C 6.8%, no insulin, no hypoglycemic history, fully independent.
- Full pipeline recommended `CARE-INSULIN-BGM` and `CARE-MED-ADMIN-MULTI`. Neither is correct — there is no insulin in the regimen and metformin alone does not meet the multi-medication clinical-complexity threshold. Precision **0.00**.
- Baseline recommended `CARE-FALL-RISK`, `CARE-INSULIN-BGM`, `CARE-MED-ADMIN-MULTI`, `CARE-MOOD-DEPRESS` — four false positives. Precision **0.00**.
- Full care-plan summary: *"Resident A is a 74-year-old female with well-controlled type 2 diabetes (HbA1c 6.8%) managed on metformin only, no insulin, no hypoglycemic history, and fully independent in all AD…"* — the summary correctly described the resident as low-acuity, but the acuity-recommendation tool still fired on the presence of diabetes-as-a-diagnosis. The staged pipeline saw "diabetes" and reached for the diabetes-shaped factor even though the resident's clinical profile didn't trigger the WAC criteria.
- This is the dominant failure mode and the right place to push next (see below).

### Where the system breaks down

- **Most common failure mode of the full system across the 8 cases.** Over-recommendation of acuity factors when a diagnosis is present but the clinical-complexity thresholds in WAC 388-106-0095/-0100/-0105 are not actually met. Precision averages 0.46; recall is 1.00. The system reliably catches what should fire, but it also fires on related-but-not-triggering conditions (e.g., metformin-only diabetes triggering `CARE-INSULIN-BGM`, generic dementia diagnosis triggering `CARE-MOOD-DEPRESS`). The synthesis prompt currently weights "evidence of the broad condition" too generously; a future revision should tie each recommendation to a specific WAC criterion match, not just to the presence of the condition.
- **One case where the baseline matched or beat the full pipeline.** On **case_04** (diabetes + dementia, insulin-resistance behavior), the baseline scored **gap precision 1.00 vs the full pipeline's 0.86**. The baseline's risk register had fewer, tighter gaps that all mapped cleanly to expected categories; the full pipeline added an extra borderline gap on injection-time staffing scheduling that didn't match a ground-truth expected gap. The full pipeline still beat the baseline on acuity-factor precision (0.80 vs 0.67) and disagreement detection on this case.
- **Input the system explicitly does not handle.** Scanned or OCR'd PDF disclosures (`pypdf` extracts text from native PDFs only — image-based scans return empty); non-Washington-State Medicaid intake (the DSHS rule reference, WAC citations, and specialty-contract names are all WA-specific); real PII in inputs (the pipeline is designed for synthetic test data, and Stage 1's PII hygiene rule is enforced by prompt rather than by a structural redaction step).

## 4. Why this is not "just ChatGPT"

- **Structured branching interview.** Stage 2 walks
  `data/trees/{diabetes,dementia,fall_risk}.json` deterministically.
  Each node specifies `expected_answer_shape`, `answer_options`,
  `updates_profile_field`, and `next_node_logic` with conditional
  `goto` edges. The tree controls flow; the LLM parses each answer
  into the typed value the node demands, but does not pick the next
  question. A plain ChatGPT session has no analogue of this — every
  branch is an unforced choice for the model.
- **Evidence-grounded snippet IDs.** Every populated field in
  `ResidentProfile` is paired with at least one `EvidenceSnippet`
  (schema in `pipeline/extraction.py`: `snippet_id`, `claim`,
  `source ∈ {discharge | family | operator}`, `verbatim_text`).
  Every claim in the care plan, acuity-factor recommendations, and
  risk register cites those IDs via `evidence_snippet_ids` /
  `resident_need_evidence` with Pydantic `min_length=1`. A claim
  without supporting evidence fails validation and is rejected.
- **Disclosure-vs-resident cross-checking.** The AFH disclosure of
  services is loaded as a first-class input alongside the resident
  artifacts. Each acuity-factor recommendation carries either a
  `disclosure_support_snippet` (verbatim quote) or
  `disclosure_gap_flagged = true`. The risk register
  (`CapabilityGap`) explicitly compares each documented resident
  need to disclosure language and assigns severity + a verbatim
  disclosure quote when available.
- **Operator-facing decision layer.** `generate_intake_decision`
  (Stage 4 in `pipeline/synthesis.py`) emits an `IntakeDecision` with
  three enumerated recommendations
  (`accept` / `accept_with_conditions` / `hold_for_review`), pre-
  admission conditions, family-call talking points, and
  `EvidenceRef` entries pointing only to existing snippet /
  acuity-factor / risk-register-entry IDs. The deterministic
  recommendation rule (any high-severity gap → hold) is encoded in
  the system prompt and the model executes it as a re-organizer, not
  as a reasoner over fresh inputs.

**Concrete numbers from the actual system.**

- A single intake walk on **case_04** (diabetes + dementia) produced
  in the committed eval: **22 structured operator interview
  responses** across **2 clinical conditions**, **49 evidence
  snippets** extracted from discharge + family + operator answers,
  **1 AFH Disclosure of Services document** cross-checked against
  resident needs, **5 acuity factors** evaluated against the WAC
  388-106 criteria catalog, **7 disclosure gaps** identified and
  severity-ranked, and **1 unresolved source disagreement**
  preserved for clinical review. The provenance box in the Summary
  tab surfaces these counts live to the operator.
- Across all 8 cases, the staged pipeline holds **+0.07 macro
  acuity-factor precision** over the baseline (0.46 vs 0.39),
  **+0.11 capability-gap recall** (0.96 vs 0.85), **+2 correct
  disagreement determinations** (4 of 8 vs 2 of 8), and **0
  hallucinated evidence references** across every case while the
  baseline has no structural way to be measured on that axis.

## 5. Artifact snapshots

The three views below illustrate the operator-facing surface. Open
Streamlit (see Setup) and walk a case through to reproduce.

- `docs/screenshot_decision.png` — top-of-page decision view: colored
  recommendation banner (red for hold_for_review, yellow for
  accept_with_conditions, green for accept), rationale truncated to
  the first 2 sentences, and the pre-admission conditions list.
- `docs/screenshot_interview.png` — stateful interview with the
  progress bar, the section breadcrumb (`Dementia → Diagnosis`), the
  `Question X of up to Y · ~N minutes remaining` counter, and the
  current question with its context hint expander.
- `docs/screenshot_evidence.png` — an expanded evidence snippet
  showing the `snippet_id`, the source label (discharge / family /
  operator), the claim, and the verbatim source text — the
  traceability that makes every artifact claim auditable.

## 6. Setup

```bash
# 1. Clone
git clone <repo-url> afh-intake-copilot
cd afh-intake-copilot

# 2. Create a virtual environment and install dependencies
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 3. Configure the Anthropic API key
cp .env.example .env
# then edit .env and replace 'your_key_here' with your actual key

# 4. Run the Streamlit app
./venv/bin/streamlit run app.py
```

**End-to-end example with the case_04 fixture:**

```bash
# Paste the contents of these two fields into the UI's input form:
cat data/test_cases/case_04.json | jq -r '.inputs.discharge_summary'
cat data/test_cases/case_04.json | jq -r '.inputs.family_notes'

# Then click "Start Intake", walk through the 22-question interview
# (the local parser will short-circuit ~12 of the 22 nodes; the rest
# go to Claude), then click "Generate Artifacts" and review the five
# tabs.
```

To re-run the evaluation harness across all eight cases:

```bash
./venv/bin/python evals/run_evals.py
# Results: evals/results/results_full.json,
#          evals/results/results_baseline.json,
#          evals/results/comparison_table.txt
```

Smoke tests for each pipeline stage (each runs against case_04):

```bash
./venv/bin/python test_extraction.py
./venv/bin/python test_interview.py
./venv/bin/python test_synthesis.py
./venv/bin/python test_baseline.py
./venv/bin/python test_intake_decision.py
./venv/bin/python test_intake_decision_distribution.py
```

## 7. Scope and limitations

- **Geography.** Washington State only. All WAC citations, specialty-
  contract names (SBS / RSW / ECS / EARC-SDC / Meaningful Day / CSS),
  the CARE classification matrix, and the disclosure form (DSHS
  10-409) are WA-specific. The pipeline will run on out-of-state
  inputs but will mis-cite regulatory authority.
- **Clinical conditions.** Three only: diabetes, dementia, fall risk.
  These are the conditions for which `data/trees/*.json` defines a
  structured interview. Other common AFH resident conditions
  (COPD with oxygen, dialysis, mental-health behavioral support,
  developmental disabilities) are not modeled.
- **Acuity factors.** Twelve only — the curated set in
  `data/dshs_rules.json`, derived from the five CARE acuity domains
  in WAC 388-106-0090 / -0095 / -0100 / -0105 / -0110. The
  `monthly_add_on_estimate_usd` field is null on every entry by
  design: Washington AFH Medicaid payment is set by the DSHS CARE
  assessment plus rate authorization, not by per-factor add-ons.
- **Test data.** Eight synthetic cases (`Resident A` through
  `Resident H`). No real PII. No real residents. The system is not
  validated on real intake documents.
- **Decision-support framing.** The artifacts are decision support,
  not clinical, legal, or billing determinations. The
  `review_required = true` field on every acuity recommendation is
  structural, not advisory: the AFH operator, family, and
  prescriber (where applicable) must review before any care or
  admission decision.
- **Difference from HW2.** HW2 was a prompt-only, single-call LLM
  that read source documents and emitted recommendations directly.
  It had no structured interview, no evidence grounding, no
  disclosure cross-check, and no operator-facing decision layer.
  This system replaces the single call with a four-stage pipeline,
  schematizes the artifacts so claims cannot be made without
  evidence, adds the disclosure-gap analysis the operator actually
  needs at intake, and ships a deterministic decision rule on top.
