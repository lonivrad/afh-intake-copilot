# AFH Acuity Intake Copilot

A GenAI decision-support application for Washington State Adult Family
Home (AFH) operators performing pre-admission resident intake.

It helps one specific user complete one specific workflow:

> Decide whether a prospective resident can be safely admitted to an
> Adult Family Home, surface the unresolved clinical and operational
> concerns, and produce an actionable, evidence-grounded move-in plan.

Built as a Streamlit app on Claude, using structured schemas,
deterministic interview logic, evidence-linked artifact generation, and
a measured comparison against a simpler one-shot LLM workflow.

---

## 1. Context, user, and problem

### Who the user is

**Washington State Adult Family Home operators.**

AFHs are small, residentially-zoned licensed homes serving elderly or
disabled residents, often Medicaid-funded. The operator is the person on
the phone with the discharging hospital or the family, deciding whether
the home can safely accept a resident and how the placement will be
supported. They are not a hospital intake department — they are usually
a single operator with limited time and no clinical analytics team.

### The workflow being improved

Pre-admission intake. For each prospective resident the operator must:

1. Read the patient's clinical record (a hospital discharge summary, an
   H&P, or current provider notes — residents do not always arrive
   straight from a hospital).
2. Review family or proxy notes.
3. Cross-check resident needs against the home's written **AFH
   Disclosure of Services**.
4. Identify unresolved clinical, staffing, or capability concerns.
5. Decide whether admission can proceed.
6. Produce the follow-up actions required before move-in.

Today this is paper-driven, intuition-heavy, and inconsistent between
operators.

### Why it matters

**Revenue leak from under-documentation.** Washington AFH Medicaid
payment is set through the DSHS CARE assessment. Acuity that the operator
fails to surface — insulin scope, behavioral resistance, fall risk,
medication-administration burden — can translate to a lower
classification and a lower daily rate.

**Safety risk from mismatched placement.** A home that accepts a
resident it cannot safely manage faces licensing risk, involuntary
discharge, or resident harm — for example exit-seeking dementia without
secured egress, insulin support without a delegating RN, two-person
transfers with single overnight staffing, or wound-care needs absent
from the disclosure document. Today this capability-vs-need check often
happens in the operator's head rather than against the home's written
disclosure.

---

## 2. Solution and design

### What I built

**AFH Acuity Intake Copilot** — a Streamlit app that guides an operator
from raw intake documents to an admission review package.

It produces:

- an admission verdict (`accept` / `accept_with_conditions` /
  `hold_for_review`),
- an owner-grouped move-in action plan,
- a resident care plan,
- Washington CARE-factor recommendations with WAC references,
- capability gaps measured against the AFH disclosure,
- an evidence trail behind every major claim,
- a downloadable Admission Action Plan (PDF / markdown).

The result is organized around the operator's mental model, not the
backend pipeline. The Results page leads with a verdict status block
(severity-colored, with the concern count, readiness progress, and which
owners to contact first), then tabbed detail:

- **Action Plan** — interactive worklist grouped by owner, priority, and
  task type, with an inline owner filter and a downloadable worksheet.
- **Family Communication** — a clean numbered call script.
- **Care Plan** — a printable clinical reference with an executive
  "Clinical summary" and grouped, evidence-linked care items.
- **Capability Gaps** — why admission may be on hold: the concern, the
  recommended next step, and the evidence.
- **CARE Factors** — Washington CARE-informed acuity recommendations with
  WAC citations, confidence, and disclosure-gap status.
- **Evidence Map** — the full provenance/audit view: every snippet,
  filterable by source and by where it is cited.
- **Sources & Debug** — structured profile and developer telemetry.

### How it works

```text
Clinical record + family notes + AFH disclosure
        ↓
Stage 1: structured extraction (Claude, forced tool call → Pydantic)
        ↓
Stage 2: deterministic guided interview (JSON trees; local parser → Claude)
        ↓
Stage 3: artifact synthesis (care plan, CARE factors, capability gaps)
        ↓
Stage 4: rule-based intake decision + operator-facing Results
```

**Stage 1 — Extraction (`pipeline/extraction.py`).** Claude is called
with a forced tool call against a Pydantic `ResidentProfile` schema.
Every populated field carries at least one `EvidenceSnippet` with
verbatim supporting text; material conflicts across sources are recorded
as `SourceDisagreement` entries.

**Stage 2 — Guided interview (`pipeline/interview.py`).** For each
triggered condition (diabetes, dementia, fall risk) the app walks a JSON
questioning tree. **The tree controls the path, not the LLM.** Each node
declares its expected answer shape, options, the profile field it
updates, and branching logic. A deterministic local parser resolves
simple boolean / numeric / enum answers; Claude is only used when an
answer needs natural-language interpretation. The operator answers with
buttons, booleans, numeric inputs, checkbox multi-selects for
multi-applicable questions, or a free-text override, and can step
**Back** to revise a prior answer or defer one with **Ask later**.

**Stage 3 — Synthesis (`pipeline/synthesis.py`).** The assembled profile
produces the care plan, CARE-factor recommendations (referenced against
the curated `data/dshs_rules.json` catalog of 12 Washington CARE-related
factors), and the disclosure-vs-need capability gaps. Each item cites
supporting evidence IDs; unsupported claims fail validation at tool-call
time rather than reaching the operator.

**Stage 4 — Decision.** A rule-based layer consumes the generated
artifacts and source disagreements (it does not re-read the source
documents) and emits one recommendation plus rationale, conditions
before admission, family-call points, and owner-grouped actions.

### Key GenAI design choices

- **GenAI where the work is genuinely unstructured** — parsing messy
  discharge narratives, reconciling conflicting sources, and turning
  findings into operator-facing prose. Checklists or keyword rules can
  spot "insulin" or "walker" but cannot reconcile context and
  contradiction.
- **Determinism where it must hold** — interview branching is JSON-tree
  controlled, CARE references come from a curated rules file, severity
  ordering is deterministic, and the final recommendation follows
  rule-based logic.
- **Evidence-grounded by construction** — every profile field and every
  synthesized item is tied to a verbatim snippet ID; the audit trail is
  a first-class output, surfaced in the Evidence Map and kept out of the
  operator's reading flow so prose stays plain English.
- **Disclosure as a first-class input** — resident needs are explicitly
  cross-checked against the home's written disclosure, which is the
  check operators most often do informally.
- **Simplest design that supports evaluation** — no RAG, no agents, no
  multi-model routing; a single provider with structured tool calls.

---

## 3. Evaluation and results

All numbers below are read from `evals/results/results_full.json` and
`evals/results/results_baseline.json`, run against eight synthetic
resident cases in `data/test_cases/`.

### Baseline compared against

A **single-call, prompt-only workflow** (`pipeline/baseline.py`): it
receives the same discharge, family, and disclosure text and produces
all outputs in one Claude call. It has no structured interview, no local
parser, no evidence graph, no persistent source-disagreement object, no
deterministic branching, and no multi-step validation. This represents
the realistic "just ask the model once" alternative.

### What counted as good output

- acuity-factor precision and recall
- capability-gap precision and recall
- source-disagreement detection
- hallucinated evidence references (citing a snippet ID that does not
  exist in the resident profile)

The full pipeline ran extraction → auto-answered interview → synthesis;
the baseline ran one prompt. Ground truth is encoded per case in
`data/test_cases/*.json`.

### Per-case scores

| case | full P | full R | base P | base R | halluc f | halluc b | disagr f | disagr b | gap P f | gap P b | gap R f | gap R b |
|------|-------:|-------:|-------:|-------:|---------:|---------:|:--------:|:--------:|--------:|--------:|--------:|--------:|
| case_01 | 0.00 | 1.00 | 0.00 | 1.00 | 0 | n/a | no | yes | 0.00 | 0.00 | 1.00 | 1.00 |
| case_02 | 0.60 | 1.00 | 0.50 | 1.00 | 0 | n/a | yes | yes | 0.83 | 0.60 | 1.00 | 0.50 |
| case_03 | 0.25 | 1.00 | 0.20 | 1.00 | 0 | n/a | yes | yes | 0.75 | 0.60 | 1.00 | 1.00 |
| case_04 | 0.80 | 1.00 | 0.67 | 1.00 | 0 | n/a | yes | yes | 0.86 | 1.00 | 1.00 | 1.00 |
| case_05 | 0.50 | 1.00 | 0.50 | 1.00 | 0 | n/a | no | yes | 1.00 | 1.00 | 1.00 | 1.00 |
| case_06 | 0.90 | 1.00 | 0.75 | 1.00 | 0 | n/a | yes | yes | 0.90 | 0.89 | 1.00 | 1.00 |
| case_07 | 0.25 | 1.00 | 0.20 | 1.00 | 0 | n/a | yes | yes | 0.60 | 0.80 | 0.67 | 0.67 |
| case_08 | 0.40 | 1.00 | 0.33 | 1.00 | 0 | n/a | yes | yes | 1.00 | 1.00 | 1.00 | 0.67 |

### Macro averages

| Metric | Full pipeline | Baseline |
|---|---:|---:|
| Acuity-factor precision | **0.46** | 0.39 |
| Acuity-factor recall | 1.00 | 1.00 |
| Hallucination count | **0.00** | n/a |
| Capability-gap precision | 0.74 | 0.74 |
| Capability-gap recall | **0.96** | 0.85 |
| Source-disagreement detection correct | **4 / 8** | 2 / 8 |

The staged pipeline improved acuity-factor precision (+0.07),
capability-gap recall (+0.11), and source-disagreement detection
(2/8 → 4/8), with **zero hallucinated evidence references**. Recall on
acuity factors tied — both systems surfaced every required factor, but
the staged pipeline over-recommended less.

### Qualitative examples

**Clear win — case_06.** All three modeled conditions, complex
multi-system acuity. Ground truth: 9 factors. Full pipeline recommended
10 (all 9 + 1 false positive, precision 0.90); baseline recommended 12
(all 9 + 3 false positives, precision 0.75). The staged system was more
disciplined and preserved better evidence linkage.

**Tie — case_05.** Dementia + fall risk with a cognitive-mobility
mismatch. Both systems recommended the same factors and the same false
positives (precision 0.50 each). The full pipeline still carried
traceable evidence IDs; the baseline had no structural evidence layer.

**Honest failure — case_01.** Low-acuity diabetes (metformin only, no
insulin, no hypoglycemic history, full ADL independence). Ground truth:
zero acuity factors. The full pipeline still recommended
`CARE-INSULIN-BGM` and `CARE-MED-ADMIN-MULTI`; the baseline also
over-recommended. Root cause: seeing "diabetes" pulls diabetes-shaped
acuity factors even when the clinical-complexity threshold is not met.
This is the dominant failure mode.

### Where it breaks down

- **Over-recommendation** when a diagnosis is present but the clinical
  threshold is not met (e.g. metformin-only diabetes triggering
  insulin/BGM complexity). A future fix is to require each recommendation
  to map more tightly to a specific WAC criterion.
- **The baseline sometimes matches or beats it** — on case_04 the
  baseline scored higher capability-gap precision (1.00 vs 0.86) because
  the full pipeline added a borderline gap outside the expected category.
- **Input limits** — no OCR for image-only scanned PDFs, Washington-only
  CARE/WAC assumptions, only diabetes/dementia/fall-risk modeled, and no
  PII-handling controls.

### Where a human stays involved

The system is decision *support*, not a decision maker. It does not make
final clinical, billing, legal, or admission decisions. The operator,
family, physician, delegating RN, and care team must review the outputs.
Capability gaps and concerns are explicitly framed for human follow-up,
and the rationale/evidence is always inspectable.

---

## 4. Artifact snapshot

The app is a runnable Streamlit application. A full walkthrough on one
example (no live system required at review time):

1. **Inputs** — paste a clinical record + family notes (disclosure
   recommended). Required-field gating; weak-PDF-extraction warning.
2. **Confirm what we extracted** — Stage-1 structured profile snapshot
   (diabetes / insulin / falls / dementia / ADL fields).
3. **Interview** — condition-specific questions as buttons / booleans /
   numeric / checkbox multi-selects, with **← Back**, **Ask later**, a
   numbered-step workflow indicator, and a live "Captured so far"
   sidebar.
4. **Ready to generate** — counts of operator answers, conditions,
   disagreements, and open unknowns.
5. **Results** — verdict status block (concern count, readiness bar, who
   to contact first), then the tabbed detail described in §2.
6. **Download** — Admission Action Plan PDF; per-tab evidence is
   inspectable and clickable into the Evidence Map.

Sample inputs/outputs live in `data/test_cases/` (inputs) and
`evals/results/` (machine-readable outputs and the comparison table).
Optional screenshots can be dropped in `docs/screenshots/`
(e.g. `results.png`, `action-plan.png`, `care-plan.png`,
`care-factors.png`, `capability-gaps.png`, `evidence-map.png`,
`interview.png`); the README, eval results, and walkthrough stand on
their own without them.

---

## Setup and usage

### Install

```bash
git clone <repo-url> afh-intake-copilot
cd afh-intake-copilot
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### Provide the API key

This project requires an Anthropic API key. It is read from a `.env`
file (git-ignored — no key is committed):

```bash
cp .env.example .env
# then edit .env and set:
# ANTHROPIC_API_KEY=sk-ant-...
```

### Run the app

```bash
./venv/bin/streamlit run app.py
```

### Run it on one example

Pull the inputs from a bundled synthetic case and paste them into the UI
(uses Python — already installed, no extra tooling required):

```bash
./venv/bin/python -c "import json;d=json.load(open('data/test_cases/case_04.json'))['inputs'];print('--- CLINICAL RECORD ---\n'+d['discharge_summary']+'\n\n--- FAMILY NOTES ---\n'+d['family_notes'])"
```

Then: Start intake → confirm the extracted profile → complete the guided
interview → generate Results → review Action Plan, Family Communication,
Care Plan, Capability Gaps, CARE Factors, and the Evidence Map.

### Re-run the evaluation

```bash
./venv/bin/python evals/run_evals.py
# writes:
#   evals/results/results_full.json
#   evals/results/results_baseline.json
#   evals/results/comparison_table.txt
```

### Smoke tests

```bash
./venv/bin/python test_extraction.py
./venv/bin/python test_interview.py
./venv/bin/python test_synthesis.py
./venv/bin/python test_baseline.py
./venv/bin/python test_intake_decision.py
./venv/bin/python test_intake_decision_distribution.py
```

---

## Repository structure

```text
app.py                 Streamlit app (UI + flow)
DESIGN.md              Design system documentation

pipeline/
    extraction.py      Stage 1 — structured extraction + Pydantic schemas
    interview.py       Stage 2 — deterministic guided interview
    synthesis.py       Stage 3 — care plan / CARE factors / gaps / decision
    baseline.py        Single-call prompt-only baseline
    documents.py       Admission Action Plan markdown + PDF

data/
    trees/             diabetes.json, dementia.json, fall_risk.json
    dshs_rules.json    12 curated Washington CARE-related factors
    test_cases/        8 synthetic resident cases (inputs + ground truth)

evals/
    run_evals.py       Full-pipeline vs baseline harness
    results/           Machine-readable scores + comparison table
```

---

## Scope and limitations

- **Geography:** Washington State only — WAC citations, specialty
  contracts, CARE classification, and disclosure assumptions are
  Washington-specific.
- **Conditions modeled:** diabetes, dementia, fall risk. Not yet modeled:
  COPD/oxygen, dialysis, mental-health behavioral support, developmental
  disabilities.
- **CARE catalog:** 12 curated factors; not every CARE pathway.
- **Data:** 8 synthetic cases; no real residents, no PII committed
  (`.env` and data exclusions are git-ignored).
- **Decision support only:** all final clinical, billing, legal, and
  admission decisions remain with the human care team.

## Future work

OCR for scanned PDFs; persistent resident workspaces; more modeled
conditions; multi-resident intake queue; export to official AFH
templates; tighter WAC-criterion mapping to reduce over-recommendation.
