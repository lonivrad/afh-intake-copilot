"""
Design-token CSS for the AFH Intake Copilot.
Call inject_styles() once at app startup.
"""
import streamlit as st

_CSS = """
    <style>
    /* Editorial typography pairing: Instrument Serif for displays +
       Libre Franklin for body. Libre Franklin is a Google Fonts
       revival of Franklin Gothic — a classic American editorial /
       newspaper grotesque — so it loads for every viewer and stays
       cohesive with the serif display rather than reading like the
       generic Inter/Geist default. JetBrains Mono for mono accents. */
    @import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Libre+Franklin:wght@400;500;600;700&family=JetBrains+Mono:wght@500&display=swap');

    /* ============================================================
       Design tokens — editorial / warm-paper palette.
       ============================================================ */
    :root {
        /* Type families — editorial serif display + Franklin-Gothic
           grotesque body. */
        --font-display: "Instrument Serif", "Fraunces", Georgia, serif;
        --font-body: "Libre Franklin", -apple-system, "Segoe UI",
                     system-ui, sans-serif;
        --font-mono: ui-monospace, "JetBrains Mono",
                     "Menlo", "SF Mono", monospace;

        /* Monochrome surfaces — almost white, very lightly warm. */
        --surface-0: #fafaf7;       /* page paper */
        --surface-1: #ffffff;       /* card */
        --surface-2: #ffffff;       /* elevated */
        --surface-soft: #f5f4ee;    /* subtle group bg */
        --surface-muted: #ececea;   /* chip / pill bg */

        /* Hairline borders. */
        --border-subtle: #efedea;
        --border-default: #e3e1dc;
        --border-strong: #c9c6c0;

        /* Ink scale — true near-black to faint. */
        --text-primary: #0e0e0c;
        --text-secondary: #3d3d3a;
        --text-muted: #6c6c66;
        --text-faint: #a4a49d;
        --text-on-brand: #ffffff;

        /* App shell ink (sidebar, brand mark) — same as text-primary
           so nothing competes with the single accent. */
        --brand-700: #0e0e0c;
        --brand-600: #1a1a18;
        --brand-500: #2a2a26;
        --brand-50:  #f5f4ee;

        /* Single editorial accent — deep oxblood used sparingly for
           tab indicator, primary action, hero side rule. */
        --accent-700: #6b1424;
        --accent-600: #8b1d2c;
        --accent-500: #a32c3a;
        --accent-50:  #fbe7ea;

        /* Status colors. Restrained — print-publication palette. */
        --accent-amber: #a86610;
        --accent-amber-bg: #f6ecd6;
        --accent-amber-text: #5d3a07;
        --accent-red: #8b1d2c;
        --accent-red-bg: #fbe7ea;
        --accent-red-text: #6b1424;
        --accent-green: #1f5f3f;
        --accent-green-bg: #e3ece3;
        --accent-green-text: #143b27;

        /* Spacing — generous editorial defaults. */
        --space-1: 4px;  --space-2: 8px;  --space-3: 12px;
        --space-4: 16px; --space-5: 20px; --space-6: 24px;
        --space-8: 32px; --space-10: 40px; --space-12: 48px;
        --space-16: 64px;

        /* Radius — flatter, more architectural. */
        --radius-xs: 2px;
        --radius-sm: 4px;
        --radius-md: 6px;
        --radius-lg: 8px;
        --radius-xl: 12px;
        --radius-pill: 999px;

        /* Shadows — neutral, very subtle. No warm tint, no glow. */
        --shadow-1: 0 1px 2px rgba(14,14,12,0.04);
        --shadow-2: 0 2px 8px rgba(14,14,12,0.06);
        --shadow-focus: 0 0 0 2px rgba(163,44,58,0.30);

        /* Type scale — editorial display tier sized for confidence. */
        --type-display: 56px;
        --type-headline: 40px;
        --type-title-lg: 28px;
        --type-title: 20px;
        --type-body-lg: 16px;
        --type-body: 15px;
        --type-caption: 13px;
        --type-overline: 11px;

        /* Motion. */
        --ease-standard: cubic-bezier(0.2, 0.0, 0, 1.0);
        --duration-quick: 120ms;
        --duration-base: 220ms;
    }

    * {
        box-sizing: border-box;
        overflow-wrap: anywhere !important;
        word-break: normal !important;
    }
    div[data-testid="stMarkdownContainer"] {
        overflow-wrap: anywhere !important;
        white-space: normal !important;
    }
    section.main * {
        line-height: 1.6 !important;
    }
    /* Page surface — warm cream so cards feel like paper on a desk. */
    div[data-testid="stMain"] {
        background: var(--surface-0);
    }
    /* Body type defaults to Libre Franklin; serif applied below. */
    html, body, [class*="css"], div[data-testid="stMarkdownContainer"] {
        font-family: var(--font-body);
        color: var(--text-primary);
    }

    /* ============================================================
       Type utility classes — use these instead of inline font-size.
       ============================================================ */
    .t-display {
        font-family: var(--font-display);
        font-size: var(--type-display);
        font-weight: 600;
        color: var(--text-primary);
        letter-spacing: -0.02em;
        line-height: 1.1;
        font-variation-settings: "opsz" 144;
    }
    .t-headline {
        font-family: var(--font-display);
        font-size: var(--type-headline);
        font-weight: 500;
        color: var(--text-primary);
        letter-spacing: 0.005em;
        line-height: 1.25;
    }
    .t-title-lg {
        font-family: var(--font-display);
        font-size: var(--type-title-lg);
        font-weight: 600;
        color: var(--text-primary);
        line-height: 1.25;
        letter-spacing: -0.01em;
    }
    .t-title {
        font-size: var(--type-title);
        font-weight: 700;
        color: var(--text-primary);
        line-height: 1.35;
    }
    .t-body-lg {
        font-size: var(--type-body-lg);
        color: var(--text-primary);
    }
    .t-body {
        font-size: var(--type-body);
        color: var(--text-secondary);
    }
    .t-caption {
        font-size: var(--type-caption);
        color: var(--text-muted);
    }
    .t-overline {
        font-size: var(--type-overline);
        font-weight: 700;
        color: var(--text-muted);
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    /* ============================================================
       Brand bar — minimal app shell.
       ============================================================ */
    /* Brand bar — masthead pattern. Issue tag stacks above the
       title on narrow viewports so the name never clips. */
    .brand-bar {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: var(--space-2);
        padding: var(--space-3) 0 var(--space-5) 0;
        margin-bottom: var(--space-6);
        border-bottom: 1px solid var(--text-primary);
    }
    .brand-issue {
        font-family: var(--font-mono);
        font-size: 10px;
        font-weight: 500;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.1em;
        white-space: normal;
        overflow-wrap: anywhere;
        max-width: 100%;
    }
    .brand-text {
        display: flex;
        flex-direction: column;
        line-height: 1.1;
        width: 100%;
    }
    .brand-name {
        font-family: var(--font-display);
        font-size: 44px;
        font-weight: 500;
        color: var(--text-primary);
        letter-spacing: -0.005em;
        line-height: 1.05;
        white-space: normal;
        overflow-wrap: break-word;
    }
    .brand-disclaimer {
        font-family: var(--font-body);
        font-size: 13px;
        color: var(--text-muted);
        margin-top: 8px;
        letter-spacing: 0;
        font-style: italic;
    }

    /* Decorative ornament — three centered dots used between
       editorial sections. */
    .ornament {
        text-align: center;
        color: var(--border-strong);
        margin: var(--space-6) 0;
        font-size: 14px;
        letter-spacing: 0.6em;
    }
    .ornament::before { content: "·  ·  ·"; }

    /* ============================================================
       Workflow stepper — numbered circles connected by progress lines
       (Material/Fluent stepper convention).
       ============================================================ */
    .stepper-wrap {
        margin: var(--space-2) 0 var(--space-5) 0;
    }
    .stepper {
        display: flex;
        align-items: center;
        gap: 0;
        max-width: 760px;
    }
    .step {
        display: flex;
        flex-direction: column;
        align-items: center;
        flex: 0 0 auto;
        min-width: 72px;
    }
    .step-circle {
        width: 28px;
        height: 28px;
        border-radius: 999px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        font-weight: 700;
        border: 2px solid var(--border-strong);
        background: var(--surface-1);
        color: var(--text-muted);
        transition: all var(--duration-base) var(--ease-standard);
    }
    .step.done .step-circle {
        background: var(--accent-green);
        border-color: var(--accent-green);
        color: var(--text-on-brand);
    }
    .step.current .step-circle {
        background: var(--text-primary);
        border-color: var(--text-primary);
        color: var(--text-on-brand);
        box-shadow: var(--shadow-focus);
    }
    .step.next .step-circle {
        background: var(--surface-1);
        border-color: var(--border-strong);
        color: var(--text-faint);
    }
    .step-label {
        font-size: 12px;
        font-weight: 600;
        color: var(--text-muted);
        margin-top: 6px;
    }
    .step.done .step-label {
        color: var(--accent-green);
    }
    .step.current .step-label {
        color: var(--text-primary);
        font-weight: 700;
    }
    .step.next .step-label {
        color: var(--text-faint);
        font-weight: 400;
    }
    .step-line {
        flex: 1 1 auto;
        height: 2px;
        background: var(--border-default);
        margin: 0 4px;
        margin-bottom: 22px; /* align with circle vertical center */
    }
    .step-line.done {
        background: var(--accent-green);
    }

    /* ============================================================
       Sticky tab bar + brand-color indicator.
       ============================================================ */
    /* Tab bar — render each tab as a bordered button, equally
       spaced and sticky at the top of the scroll. */
    div[data-baseweb="tab-list"] {
        position: sticky;
        top: 0;
        z-index: 50;
        background: var(--surface-0);
        border-bottom: 1px solid var(--border-default);
        padding: 10px 0 !important;
        gap: 8px !important;
        display: flex !important;
        flex-wrap: wrap !important;
    }
    div[data-baseweb="tab-list"] button[role="tab"] {
        font-weight: 600 !important;
        font-size: 13px !important;
        color: var(--text-secondary) !important;
        background: var(--surface-1) !important;
        border: 1px solid var(--border-strong) !important;
        border-radius: var(--radius-sm) !important;
        padding: 8px 14px !important;
        margin: 0 !important;
        transition: all var(--duration-quick) var(--ease-standard);
    }
    div[data-baseweb="tab-list"] button[role="tab"]:hover {
        color: var(--text-primary) !important;
        border-color: var(--text-primary) !important;
        background: var(--surface-soft) !important;
    }
    div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"] {
        color: var(--text-on-brand) !important;
        background: var(--text-primary) !important;
        border-color: var(--text-primary) !important;
    }
    div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"] * {
        color: var(--text-on-brand) !important;
    }
    /* Hide the default Streamlit underline indicator — bordered
       button + dark fill already conveys selection. */
    div[data-baseweb="tab-highlight"] {
        display: none !important;
    }

    /* ============================================================
       Hero status block — editorial pull-quote treatment.
       ============================================================ */
    .hero-card {
        background: var(--surface-2);
        border: 1px solid var(--border-default);
        border-radius: var(--radius-lg);
        padding: var(--space-4) var(--space-5);
        margin: 0 0 var(--space-4) 0;
        box-shadow: var(--shadow-1);
        position: relative;
    }
    /* Hairline marginal rule — single-color editorial signature. */
    .hero-card::before {
        content: "";
        position: absolute;
        left: 0; top: 16px; bottom: 16px;
        width: 2px;
        background: var(--accent-600);
    }
    .hero-verdict {
        font-size: var(--type-overline);
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .hero-blocker-num {
        font-family: var(--font-display);
        font-size: 52px;
        font-weight: 500;
        line-height: 1.0;
        color: var(--text-primary);
        margin: 6px 0 0 0;
        letter-spacing: -0.03em;
        font-feature-settings: "tnum", "lnum";
        font-variation-settings: "opsz" 144;
    }
    .hero-blocker-label {
        font-family: var(--font-display);
        font-size: 24px;
        font-style: italic;
        font-weight: 700;
        color: var(--text-primary);
        margin-top: 4px;
        letter-spacing: 0.02em;
        word-spacing: 0.04em;
    }
    .hero-section-label {
        font-size: var(--type-overline);
        font-weight: 700;
        color: var(--text-muted);
        letter-spacing: 0.12em;
        text-transform: uppercase;
        margin: 14px 0 6px 0;
    }
    .hero-progress-text {
        font-size: 13px;
        color: var(--text-secondary);
        margin-top: 4px;
        margin-bottom: 14px;
        font-feature-settings: "tnum";
    }

    /* ============================================================
       Chips + filter pills.
       ============================================================ */
    .filter-chip {
        display: inline-block;
        background: var(--accent-amber-bg);
        color: var(--accent-amber-text);
        padding: 3px 10px;
        border-radius: var(--radius-pill);
        font-size: 12px;
        font-weight: 700;
        margin-left: 8px;
    }

    /* ============================================================
       Slim section header used inside tabs — editorial title set in
       Fraunces with a tighter sans subtitle.
       ============================================================ */
    .ap-strip-title {
        font-family: var(--font-display);
        font-size: var(--type-title-lg);
        font-weight: 600;
        color: var(--text-primary);
        margin-bottom: 4px;
        letter-spacing: -0.01em;
    }
    .ap-strip-sub {
        font-size: 13px;
        color: var(--text-muted);
        font-style: italic;
    }
    .section-heading {
        font-family: var(--font-display);
        font-size: var(--type-title);
        font-weight: 600;
        color: var(--text-primary);
        margin: 18px 0 8px 0;
        letter-spacing: -0.005em;
    }
    /* Tight workstream subgroup label — small caps overline, minimal
       vertical margin so task rows sit directly beneath it without a
       big divider gap. */
    .ws-subgroup {
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-muted);
        margin: 24px 0 16px 0;
    }
    .ws-subgroup:first-child {
        margin-top: 8px;
    }

    /* ============================================================
       Buttons — refine focus, hover, primary / secondary.
       ============================================================ */
    button[data-testid="stBaseButton-secondary"]:hover {
        border-color: var(--brand-500);
        color: var(--brand-500);
    }
    button[data-testid="stBaseButton-primary"],
    button[data-testid="stBaseButton-primaryFormSubmit"] {
        background: var(--text-primary) !important;
        border-color: var(--text-primary) !important;
        color: #ffffff !important;
        font-weight: 600;
        letter-spacing: 0.01em;
    }
    /* Force white on every nested element Streamlit puts inside the
       button (label wrapper, <p>, span) — disabled state included. */
    button[data-testid="stBaseButton-primary"] *,
    button[data-testid="stBaseButton-primaryFormSubmit"] * {
        color: #ffffff !important;
        fill: #ffffff !important;
    }
    button[data-testid="stBaseButton-primary"]:hover,
    button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
        background: var(--accent-700) !important;
        border-color: var(--accent-700) !important;
        color: #ffffff !important;
    }
    button[data-testid="stBaseButton-primary"]:disabled,
    button[data-testid="stBaseButton-primaryFormSubmit"]:disabled {
        background: var(--text-primary) !important;
        border-color: var(--text-primary) !important;
        color: #ffffff !important;
        opacity: 0.6 !important;
        cursor: not-allowed;
    }
    button[data-testid="stBaseButton-primary"]:disabled *,
    button[data-testid="stBaseButton-primaryFormSubmit"]:disabled * {
        color: #ffffff !important;
        fill: #ffffff !important;
    }
    button[data-testid="stBaseButton-secondary"] {
        background: var(--surface-1);
        border-color: var(--border-strong);
        color: var(--text-primary);
        font-weight: 500;
    }
    button:focus-visible {
        outline: none;
        box-shadow: var(--shadow-focus);
    }
    /* Start Intake — always a solid black fill, even while disabled
       (no grey fade), so the on-ramp action reads clearly. Selector
       is intentionally specific (class + data-testid + :disabled) so
       it outranks the global disabled-primary rule. */
    div[class*="st-key-start_intake_btn"]
      button[data-testid="stBaseButton-primary"],
    div[class*="st-key-start_intake_btn"]
      button[data-testid="stBaseButton-primary"]:disabled,
    div[class*="st-key-start_intake_btn"]
      button[data-testid="stBaseButton-primary"]:hover,
    div[class*="st-key-start_intake_btn"]
      button[data-testid="stBaseButton-primaryFormSubmit"],
    div[class*="st-key-start_intake_btn"]
      button[data-testid="stBaseButton-primaryFormSubmit"]:disabled {
        background: #000000 !important;
        border-color: #000000 !important;
        color: #ffffff !important;
        opacity: 1 !important;
        cursor: pointer;
    }
    div[class*="st-key-start_intake_btn"] button *,
    div[class*="st-key-start_intake_btn"] button:disabled * {
        color: #ffffff !important;
    }

    /* Evidence ID chips — uniform mono pills regardless of label
       length (S3 vs OP18). Same height, centered, monospace. */
    div[class*="st-key-ev_chip_"] button {
        font-family: var(--font-mono) !important;
        font-size: 12px !important;
        font-weight: 600 !important;
        letter-spacing: 0.02em !important;
        padding: 4px 6px !important;
        min-height: 30px !important;
        background: var(--surface-soft) !important;
        border: 1px solid var(--border-strong) !important;
        color: var(--text-secondary) !important;
        border-radius: var(--radius-sm) !important;
    }
    div[class*="st-key-ev_chip_"] button:hover {
        border-color: var(--accent-600) !important;
        color: var(--accent-700) !important;
        background: var(--surface-1) !important;
    }
    div[class*="st-key-ev_chip_"] button * {
        color: inherit !important;
    }

    /* ============================================================
       Form polish — visible borders + focus rings for every input.
       Expander chrome quiet so content reads first.
       ============================================================ */
    input:focus, textarea:focus, select:focus {
        outline: none;
    }
    /* Always-visible borders so inputs nested inside expanders
       (Action Plan task cards, Add custom task, etc.) read as
       discrete fields instead of running together. */
    div[data-baseweb="select"] > div:first-child,
    div[data-baseweb="input"],
    div[data-baseweb="textarea"],
    div[data-testid="stDateInputField"],
    div[data-testid="stTextInputRootElement"] {
        border: 1px solid var(--border-strong) !important;
        border-radius: var(--radius-sm) !important;
        background: var(--surface-1) !important;
    }
    div[data-baseweb="select"] > div:first-child:hover,
    div[data-baseweb="input"]:hover,
    div[data-baseweb="textarea"]:hover {
        border-color: var(--text-secondary) !important;
    }
    div[data-baseweb="input"]:focus-within,
    div[data-baseweb="textarea"]:focus-within,
    div[data-baseweb="select"]:focus-within {
        box-shadow: var(--shadow-focus);
        border-radius: var(--radius-sm);
    }
    /* Expander chrome — quieter so the content reads first. */
    div[data-testid="stExpander"] {
        border: 1px solid var(--border-default) !important;
        border-radius: var(--radius-md) !important;
        background: var(--surface-1);
        margin-bottom: 10px !important;
    }
    /* Breathing room around the statement in each collapsed card so
       a long worklist doesn't read as a squished block. */
    div[data-testid="stExpander"] summary {
        font-weight: 600;
        color: var(--text-primary);
        padding-top: 12px !important;
        padding-bottom: 12px !important;
        line-height: 1.5 !important;
    }
    /* Generated-document preview only: keep the leading "Draft
       Admission Action Plan" h1 tight under the expander and shrink
       the Expand-all control. Scoped to the h1 (only the preview
       renders a markdown h1) and to the keyed Expand-all button, so
       this does NOT touch Action Plan task cards or other expanders. */
    div[data-testid="stExpanderDetails"]
      [data-testid="stMarkdownContainer"] h1 {
        font-size: 22px !important;
        margin: 0 0 6px 0 !important;
        line-height: 1.2 !important;
    }
    div[class*="st-key-expand_all_doc_toggle"] {
        margin: -6px 0 -8px 0 !important;
    }
    div[class*="st-key-expand_all_doc_toggle"] button {
        padding: 2px 12px !important;
        min-height: 26px !important;
        font-size: 12px !important;
    }

    /* ============================================================
       Page padding — breathing room without consuming first viewport.
       ============================================================ */
    div.block-container {
        padding-top: 24px !important;
        padding-left: 32px !important;
        padding-right: 32px !important;
        max-width: 1200px;
    }

    /* ============================================================
       Sidebar typography.
       ============================================================ */
    section[data-testid="stSidebar"] {
        background: var(--surface-soft);
        border-right: 1px solid var(--border-default);
    }

    /* ============================================================
       Motion — restrained, professional micro-interactions.
       ============================================================ */
    @keyframes fade-up {
        from { opacity: 0; transform: translateY(6px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes pulse-ring {
        0%   { box-shadow: 0 0 0 0 rgba(37,99,235,0.55); }
        70%  { box-shadow: 0 0 0 10px rgba(37,99,235,0); }
        100% { box-shadow: 0 0 0 0 rgba(37,99,235,0); }
    }
    @keyframes shimmer {
        0%   { background-position: -200px 0; }
        100% { background-position: 200px 0; }
    }
    .hero-card {
        animation: fade-up 360ms var(--ease-standard) both;
    }
    .step.current .step-circle {
        animation: pulse-ring 1800ms var(--ease-standard) infinite;
    }
    /* Card-style buttons (used by hero owner cards + next steps)
       pick up a soft lift on hover. */
    div[data-testid="stHorizontalBlock"]
      button[data-testid="stBaseButton-secondary"] {
        transition: transform var(--duration-quick) var(--ease-standard),
                    box-shadow var(--duration-quick) var(--ease-standard),
                    border-color var(--duration-quick) var(--ease-standard);
    }
    div[data-testid="stHorizontalBlock"]
      button[data-testid="stBaseButton-secondary"]:hover {
        transform: translateY(-1px);
        box-shadow: var(--shadow-2);
        border-color: var(--brand-500);
        color: var(--brand-500);
    }
    /* Subtle cap on hero card depth. */
    .hero-card:hover {
        box-shadow: var(--shadow-2);
    }

    /* ============================================================
       Friendly empty-state badges.
       ============================================================ */
    .empty-ok {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 8px 14px;
        border-radius: var(--radius-pill);
        background: var(--accent-green-bg);
        color: var(--accent-green-text);
        font-size: 13px;
        font-weight: 600;
        margin: 6px 0;
    }
    .empty-ok::before {
        content: "✓";
        font-weight: 800;
    }

    /* ============================================================
       Milestone toast (interview progress).
       ============================================================ */
    .milestone {
        background: var(--surface-1);
        border-left: 2px solid var(--accent-600);
        color: var(--text-primary);
        border-radius: 0;
        padding: 10px 18px;
        font-family: var(--font-body);
        font-size: 16px;
        font-style: italic;
        font-weight: 700;
        color: var(--text-primary);
        letter-spacing: 0.07em;
        word-spacing: 0.12em;
        line-height: 1.7;
        margin: 8px 0 12px 0;
        animation: fade-up 320ms var(--ease-standard) both;
    }

    /* Interview question — editorial serif, light weight, so the
       prompt feels considered rather than a bulky bold heading. */
    .interview-q {
        font-family: var(--font-display);
        font-size: 27px;
        font-weight: 400;
        line-height: 1.38;
        letter-spacing: 0.015em;
        color: var(--text-primary);
        margin: 8px 0 12px 0;
    }
    </style>
"""


def inject_styles() -> None:
    """Inject the app's design-token CSS into the Streamlit page."""
    st.markdown(_CSS, unsafe_allow_html=True)
