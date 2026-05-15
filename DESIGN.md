# AFH Acuity Intake Copilot — Design System

The shipped system is **editorial**: a confident serif display face paired
with a clean grotesque body, a near-monochrome warm-paper palette, and a
single restrained accent. No gradients, no glassmorphism, no decorative
color. Hairline rules and generous spacing carry the structure.

All design lives as CSS variables in the `<style>` block at the top of
`app.py`. Change the token, not the call site.

---

## Typography

| Role | Family | Notes |
|------|--------|-------|
| Display (brand, headlines, questions, section titles, hero number, milestones) | **Instrument Serif** (`--font-display`) | Editorial serif. Used at size + light weight (400–500), never faux-bold. |
| Body (everything else — buttons, captions, chips, tabs, forms, prose) | **Libre Franklin** (`--font-body`) | Franklin-Gothic revival; loads from Google Fonts for all users. |
| Mono (evidence-ID chips, rare metadata) | system mono / JetBrains Mono (`--font-mono`) | |

Type scale tokens: `--type-display 56` · `--type-headline 40` ·
`--type-title-lg 28` · `--type-title 20` · `--type-body-lg 16` ·
`--type-body 15` · `--type-caption 13` · `--type-overline 11`.

Use the `.t-display / .t-headline / .t-title-lg / .t-title / .t-body /
.t-caption / .t-overline` utility classes instead of inline font sizes.
Display classes apply the serif; everything else is Libre Franklin.

---

## Palette

Near-monochrome warm paper. One accent (oxblood) used sparingly.

| Token | Hex | Role |
|-------|-----|------|
| `--surface-0` | `#fafaf7` | Page paper (warm off-white) |
| `--surface-1` | `#ffffff` | Cards |
| `--surface-2` | `#ffffff` | Elevated cards (with shadow) |
| `--surface-soft` | `#f5f4ee` | Subtle group / zebra background |
| `--surface-muted` | `#ececea` | Chip / pill background |
| `--border-subtle` / `--border-default` / `--border-strong` | `#efedea` / `#e3e1dc` / `#c9c6c0` | Hairline rules |
| `--text-primary` | `#0e0e0c` | Primary text + app-shell ink |
| `--text-secondary` | `#3d3d3a` | Body prose |
| `--text-muted` | `#6c6c66` | Captions, overlines |
| `--text-faint` | `#a4a49d` | De-emphasized (e.g. stripped-out codes) |
| `--accent-700/600/500` | `#6b1424` / `#8b1d2c` / `#a32c3a` | **Oxblood** — the only accent |
| Amber | `#a86610` / bg `#f6ecd6` / text `#5d3a07` | MEDIUM severity, warnings |
| Red | `#8b1d2c` / bg `#fbe7ea` / text `#6b1424` | HIGH / CRITICAL severity |
| Green | `#1f5f3f` / bg `#e3ece3` / text `#143b27` | Cleared / confirmed / "all clear" |

Spacing: 4-pt grid (`--space-1`…`--space-16`).
Radius: flat/architectural — `--radius-xs 2` … `--radius-xl 12`, `--radius-pill 999`.
Shadows: neutral and very subtle (`--shadow-1/2`); focus ring is oxblood (`--shadow-focus`).
Motion: `--ease-standard` cubic-bezier(0.2,0,0,1), `--duration-quick 120ms` / `--duration-base 220ms`.

---

## Color Rules

- **Near-black owns the chrome and primary actions.** Brand title, stepper
  current step, primary buttons (black fill, white text), active tab.
- **Oxblood is the single accent.** Hero left rule, tab/section emphasis,
  focus rings, primary-button hover. Use at small scale only — never a
  large fill.
- **Status colors communicate state, never decorate.** Red = HIGH/CRITICAL,
  amber = MEDIUM/warning, green = cleared/confirmed. They appear only when
  the pipeline has produced that state.
- **Paper is the canvas.** Content areas, cards, inputs. No color for
  decoration here.

---

## Components

### Brand bar
Masthead pattern: serif product name, italic muted disclaimer, hard 1px
near-black hairline rule beneath. No logo plate, no gradient.

### Workflow stepper
Numbered circles connected by 2px progress lines. Done = filled green ✓;
current = filled near-black with oxblood focus ring; future = faint
outline. Step labels below the circles.

### Tabs
A row of bordered buttons, equal 8px gap, sticky to the top of the
scroll. Active tab = near-black fill + white text. No underline
indicator.

### Hero status block (Results)
Bordered card with a 2px oxblood left rule. Verdict overline → large
serif count (e.g. blockers/concerns) → italic serif label → section
overlines (Admission readiness, Who to contact first) → clickable owner
cards → Acknowledge → collapsed "Why this verdict?".

### Cards (`.summary-card`)
White, 1px hairline border, flat radius, minimal shadow. Disagreement
cards add a colored left rule with `22px` left padding (text never
crowds the rule).

### Buttons
- **Primary:** near-black fill, white text, weight 600. (Start Intake is
  forced solid `#000000` even when disabled — full opacity, no grey fade.)
- **Secondary:** white fill, strong border, brand-color hover.
- **Focus:** oxblood focus ring (`:focus-visible`).

### Inputs
Visible 1px border (`--border-strong`), hover deepens, focus = oxblood
ring. Applies to every text/select/date/number widget so fields read as
discrete even nested in expanders.

### Severity
HIGH/CRITICAL = red, MEDIUM = amber, LOW/FOLLOW-UP = gray. Rendered as
styled pills via the existing chip helpers in the tabs, and as small
colored **dots** (with hover tooltips) in the generated-document
preview. Never raw `[HIGH]` text in user-facing UI.

### Prose (`_render_prose`)
Dense rationale / summary / support paragraphs are split one sentence
per block, capped to a ~66-character reading measure with 1.75
line-height, and **audit codes are stripped from the sentence flow**.

### Evidence codes
`S` = clinical record · `F` = family notes · `OP` = operator interview
answer · `gap_NN` = capability-gap register index. These are an audit
trail, **quarantined to the labeled Evidence sections and the Evidence
Map tab** (with an inline legend) — never left bare inside prose.

### Empty states
A single muted line or a green `.empty-ok` pill (e.g. "Open questions
resolved") — never a large empty card with heading + paragraph.

---

## Voice & Terminology

- No internal/jargon terms in user-facing copy: "concerns / flagged"
  not "blocking"; "clinical record" not "discharge summary"; no
  "UI priority (inferred…)" meta notes.
- Interview questions read as considered editorial prompts (serif,
  light weight), not bulky bold headings.
- Microcopy is operator-facing and warm (time-of-day greeting,
  milestone callouts, friendly model-error messages).

---

## Scope Rules

When applying this design system:

- **Touch only:** CSS/styling, color values, fonts, spacing, borders,
  copy/wording, and presentation logic — all within `app.py`.
- **Do not touch:** Pydantic schemas, pipeline/synthesis logic,
  extraction, interview-tree JSON, prompts, eval harness, generated
  artifact content, PDF generation.
- UI-layer overrides (e.g. `_QUESTION_TEXT_OVERRIDES`,
  `_MULTISELECT_ENUM_NODES`, `_MULTISELECT_OPTION_OVERRIDES`,
  `_HUMAN_OPTION_LABELS`) are the sanctioned way to adjust wording or
  option lists without modifying the tree or schema; submitted values
  still flow through the normal parser and stay verbatim in evidence.
- After any change: `python -m py_compile app.py` and a Streamlit
  health check before considering it done.
