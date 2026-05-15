"""AFH Acuity Intake Copilot — Streamlit UI.

Stateful one-page workflow: paste source documents -> Stage 1 extraction ->
Stage 2 stateful interview -> Stage 3 synthesis -> view the three
decision-support artifacts (care plan, CARE acuity-factor recommendations,
capability-gap risk register) with expandable evidence snippets, and
optionally compare against the single-call baseline.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta
from html import escape as html_escape
from pathlib import Path

import streamlit as st
from pypdf import PdfReader

from pipeline.baseline import run_baseline
from pipeline.documents import (
    generate_admission_action_plan,
    generate_admission_action_plan_pdf,
)
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
        background: var(--surface-1);
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
        font-size: 18px;
        font-style: italic;
        font-weight: 500;
        color: var(--text-secondary);
        margin-top: 4px;
        letter-spacing: 0.03em;
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
        margin: 20px 0 10px 0;
    }
    .ws-subgroup:first-child {
        margin-top: 6px;
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
    /* Generated-document preview: pull the leading title up tight
       under the expander and shrink the Expand-all control so there
       isn't a big empty band between the two. */
    div[data-testid="stExpanderDetails"]
      [data-testid="stMarkdownContainer"] h1 {
        font-size: 22px !important;
        margin: 4px 0 8px 0 !important;
        line-height: 1.25 !important;
    }
    div[class*="st-key-expand_all_doc_toggle"] {
        margin: -4px 0 2px 0 !important;
    }
    div[class*="st-key-expand_all_doc_toggle"] button {
        padding: 2px 12px !important;
        min-height: 26px !important;
        font-size: 12px !important;
    }
    /* More breathing room between bullet points in dense document
       sections so a long list isn't overwhelming to scan. */
    div[data-testid="stExpanderDetails"]
      [data-testid="stMarkdownContainer"] li {
        margin-bottom: 9px !important;
        line-height: 1.65 !important;
    }
    div[data-testid="stExpanderDetails"]
      [data-testid="stMarkdownContainer"] ul,
    div[data-testid="stExpanderDetails"]
      [data-testid="stMarkdownContainer"] ol {
        margin-bottom: 12px !important;
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
    """,
    unsafe_allow_html=True,
)
st.markdown(
    "<div class='brand-bar'>"
    "<div class='brand-issue'>&nbsp;</div>"
    "<div class='brand-text'>"
    "<span class='brand-name'>AFH Acuity Intake Copilot</span>"
    "<span class='brand-disclaimer'>"
    "Decision support · not clinical, legal, or billing. "
    "All outputs require review."
    "</span>"
    "</div>"
    "</div>",
    unsafe_allow_html=True,
)


# ===== Workflow stepper =====

_STEPPER_STAGES: list[tuple[str, str]] = [
    ("input", "Inputs"),
    ("profile_review", "Profile"),
    ("interview", "Interview"),
    ("synthesis_ready", "Generate"),
    ("synthesis_done", "Results"),
]


def _render_workflow_stepper(current_stage: str) -> None:
    """Material/Fluent-style numbered-circle stepper with connecting
    progress lines. Done steps fill green; the current step uses brand
    blue with a focus ring; future steps are faint outlines."""
    if current_stage not in {s[0] for s in _STEPPER_STAGES}:
        return
    seen_current = False
    parts: list[str] = []
    for i, (key, label) in enumerate(_STEPPER_STAGES):
        if key == current_stage:
            state = "current"
            seen_current = True
            mark = str(i + 1)
        elif seen_current:
            state = "next"
            mark = str(i + 1)
        else:
            state = "done"
            mark = "✓"
        parts.append(
            f"<div class='step {state}'>"
            f"<span class='step-circle'>{mark}</span>"
            f"<span class='step-label'>{label}</span>"
            f"</div>"
        )
        if i < len(_STEPPER_STAGES) - 1:
            line_cls = "step-line done" if state == "done" else "step-line"
            parts.append(f"<div class='{line_cls}'></div>")
    st.markdown(
        f"<div class='stepper-wrap'>"
        f"<div class='stepper'>{''.join(parts)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


_render_workflow_stepper(st.session_state.get("stage", "input"))


# ===== Session-state init =====

DEFAULT_STATE = {
    "stage": "input",  # input | profile_review | interview | synthesis_ready | synthesis_done
    "profile": None,
    "triggered_conditions": [],
    "source_docs": None,
    "disclosure_text": "",
    "session": None,
    "interview_history": [],
    "interview_total_nodes": 0,
    "artifacts": None,
    "intake_decision": None,
    "baseline_output": None,
    "draft_action_plan": None,
    "custom_tasks": [],
    "target_move_in_date": None,
}


_TASK_STATUS_OPTIONS = {
    "question": ["Unanswered", "Answered", "Waiting"],
    "condition": [
        "Pending",
        "Waiting on external party",
        "Confirmed",
    ],
    "action": ["Not started", "Waiting", "Done"],
}

_TASK_DONE_STATES = {
    "question": "Answered",
    "condition": "Confirmed",
    "action": "Done",
}

_OWNER_DUE_OFFSETS_DAYS = {
    "Physician": 5,
    "Delegating RN": 5,
    "Home Health / Hospital": 3,
    "Family": 3,
    "AFH Operator": 1,
    "Needs Assignment": 3,
}


_WORKSPACE_OWNER_ORDER = [
    "Physician",
    "Delegating RN",
    "AFH Operator",
    "Family",
    "Home Health / Hospital",
    "Needs Assignment",
]


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


_HUMAN_OPTION_LABELS: dict[str, str] = {
    "type_1": "Type 1",
    "type_2": "Type 2",
    "unknown": "Unknown",
    "fixed_dose": "Fixed dose",
    "sliding_scale": "Sliding scale",
    "basal_bolus": "Basal-bolus",
    "self": "Self",
    "family": "Family",
    "delegating_RN_via_AFH_staff": "Delegating RN via AFH staff",
    "contracted_LPN_or_RN": "Contracted LPN or RN",
    "once_daily": "Once daily",
    "two_to_three_daily": "2–3 times daily",
    "four_or_more_daily": "4+ times daily",
    "PRN_only": "PRN only",
    "mild_self_treated": "Mild (self-treated)",
    "moderate_third_party_assist": "Moderate (third-party assist)",
    "severe_ER_or_hospitalization": "Severe (ER or hospitalization)",
    "none": "None",
    "carbohydrate_controlled": "Carbohydrate-controlled",
    "renal_diabetic": "Renal / diabetic",
    "low_sodium": "Low sodium",
    "modified_texture": "Modified texture",
    "tube_feeding": "Tube feeding",
    "other": "Other",
    "confirmed": "Confirmed",
    "suspected_unconfirmed": "Suspected (unconfirmed)",
    "no_concern": "No concern",
    "alzheimers": "Alzheimer's",
    "vascular": "Vascular",
    "lewy_body": "Lewy body",
    "frontotemporal": "Frontotemporal",
    "mixed": "Mixed",
    "unspecified": "Unspecified",
    "early": "Early",
    "moderate": "Moderate",
    "advanced": "Advanced",
    "end_stage": "End-stage",
    "oriented_x3": "Oriented to person, place, and time",
    "oriented_x2_person_place": "Oriented to person and place",
    "oriented_x1_person": "Oriented to person only",
    "fully_disoriented": "Fully disoriented",
    "toileting_or_bathroom": "Toileting or bathroom",
    "bedside_or_transfer": "Bedside or transfer",
    "ambulating_indoors": "Ambulating indoors",
    "ambulating_outdoors": "Ambulating outdoors",
    "during_personal_care": "During personal care",
    "unwitnessed_unknown": "Unwitnessed / unknown",
    "no_injury": "No injury",
    "minor_injury_treated_in_place": "Minor injury (treated in place)",
    "ER_visit_no_admission": "ER visit (no admission)",
    "hospitalization": "Hospitalization",
    "fracture_or_head_injury": "Fracture or head injury",
    "cane": "Cane",
    "walker": "Walker",
    "rollator": "Rollator",
    "wheelchair_self_propel": "Wheelchair (self-propel)",
    "wheelchair_staff_propel": "Wheelchair (staff-propel)",
    "transfer_lift_only_non_ambulatory": "Transfer / lift only (non-ambulatory)",
    "perimeter_monitoring_alarm": "Wandering / exit monitoring alarm",
    "lift_transfer": "Mechanical lift / transfer equipment",
    "shower_seating": "Shower seating (shower chair or bench)",
    "stair_lift": "Stair lift",
    "door_widening": "Doorway widening for wheelchair / walker access",
    "True": "Yes",
    "False": "No",
}


def _humanize_option_value(opt: str) -> str:
    """Render an enum value (or boolean repr) in human-friendly form.
    Falls back to underscore-replaced title case when not in the
    explicit map."""
    if opt is None:
        return ""
    if opt in _HUMAN_OPTION_LABELS:
        return _HUMAN_OPTION_LABELS[opt]
    s = str(opt).strip()
    if not s:
        return ""
    return s.replace("_", " ").strip().title()


_NODE_LABEL_HUMAN: dict[str, str] = {
    "DIABETES_TYPE": "Diabetes type",
    "INSULIN_USE": "Insulin use",
    "INSULIN_REGIMEN": "Insulin regimen",
    "INSULIN_ADMIN": "Insulin administration",
    "ORAL_MEDS": "Oral diabetes meds",
    "BGM_FREQUENCY": "Blood glucose monitoring",
    "LAST_A1C": "Last A1C",
    "HYPO_HISTORY": "Hypoglycemia (6mo)",
    "HYPO_SEVERITY": "Hypoglycemia severity",
    "DIET_RESTRICTIONS": "Diet restrictions",
    "DIET_NOTES": "Diet notes",
    "DX_STATUS": "Diagnosis status",
    "DX_TYPE": "Dementia type",
    "STAGE": "Stage",
    "ORIENTATION_LEVEL": "Orientation",
    "BEHAV_AGITATION": "Agitation",
    "BEHAV_EXIT_SEEKING": "Exit-seeking / wandering",
    "BEHAV_SUNDOWNING": "Sundowning",
    "BEHAV_RESIST_CARE": "Resists care",
    "PRIOR_PLACEMENT_TYPE": "Prior placement",
    "MOVE_REASON": "Reason for move",
    "FAMILY_PRIMARY_CONTACT": "Family contact",
    "FAMILY_COMM_PREF": "Family comm preference",
    "FALL_HISTORY_6MO": "Falls in last 6mo",
    "FALL_COUNT": "Fall count",
    "FALL_CIRCUMSTANCES": "Fall circumstance",
    "FALL_OUTCOMES": "Worst fall outcome",
    "ASSISTIVE_DEVICE": "Mobility aid",
    "GAIT_STABILITY": "Gait stability",
    "MEDS_FALL_RISK": "Fall-risk medications",
    "MEDS_FALL_RISK_CATEGORIES": "Fall-risk categories",
    "HOME_ACCOMMODATIONS": "Home accommodations",
    "PT_HISTORY": "Physical therapy",
    "PT_NOTES": "Physical therapy notes",
}


_QUESTION_TEXT_OVERRIDES: dict[str, str] = {
    "BEHAV_EXIT_SEEKING": (
        "Has the resident shown wandering, exit-seeking, or attempts "
        "to leave the home?"
    ),
    "MEDS_FALL_RISK_CATEGORIES": (
        "Which fall-risk-increasing medication categories does the "
        "resident take?"
    ),
}


# Enum nodes where several options can legitimately co-apply — render
# as a multi-select instead of single-choice buttons. The backend field
# is still a single value; when >1 is chosen the combined answer flows
# through the normal parser (which normalizes to the schema, e.g.
# "multiple_modifications") and the literal selections are preserved in
# the operator evidence snippet.
_MULTISELECT_ENUM_NODES = {"HOME_ACCOMMODATIONS"}

# UI-only tweaks to the checkbox option list for a multi-select node:
# drop options that aren't useful to surface, and add operator-relevant
# choices not in the tree. Submitted values still flow through the
# normal parser (and stay verbatim in the evidence snippet); no schema
# or tree-file change.
_MULTISELECT_OPTION_OVERRIDES: dict[str, dict[str, object]] = {
    "HOME_ACCOMMODATIONS": {
        "remove": {"multiple_modifications"},
        "add": [
            "lift_transfer",
            "shower_seating",
            "stair_lift",
            "door_widening",
        ],
    },
}


_FRID_CATEGORY_OPTIONS = [
    "Benzodiazepines",
    "Opioids",
    "Antipsychotics",
    "Sedative-hypnotics",
    "Anticholinergics",
    "Antidepressants",
    "Antihypertensives / orthostatic BP medications",
    "Diuretics",
    "Other",
    "None",
]


def _has_active_interview_question(session) -> bool:
    """True only when the session has a live, in-bounds current question.
    Guards every UI read of session.trees[session.current_tree_idx] so a
    completed / reset / advanced-past-end interview cannot crash the
    sidebar or the interview stage."""
    return (
        session is not None
        and getattr(session, "trees", None)
        and 0 <= session.current_tree_idx < len(session.trees)
        and session.current_node_id is not None
    )


def _snapshot_session(session):
    """Deep-copy an InterviewSession so the operator can step Back to a
    prior question. The Anthropic client isn't deep-copyable, so it is
    detached during the copy and the live reference is reattached to
    both the original and the snapshot afterwards."""
    client = getattr(session, "_client", None)
    try:
        session._client = None
        snap = copy.deepcopy(session)
    finally:
        session._client = client
    snap._client = client
    return snap


def _restore_session(snap) -> None:
    """Make a snapshot the live session. session.profile is the
    deep-copied profile, so keep st.session_state.profile in sync."""
    st.session_state.session = snap
    st.session_state.profile = snap.profile


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


# ===== Care Plan tab — clinical artifact view =====


_CARE_PLAN_CATEGORIES = [
    ("Diabetes", "diabetes_care"),
    ("Dementia", "dementia_care"),
    ("Fall risk", "fall_risk_care"),
    ("ADLs", "adl_support"),
    ("Medications", "medication_management"),
]


def _adl_field_label(field: str) -> str:
    return field.replace("_", " ")


def _summarize_adl(adl_status) -> str:
    """Compact ADL summary from existing fields (no inference)."""
    if adl_status is None:
        return "Not documented"
    fields = [
        "bed_mobility", "transfers", "eating", "toilet_use",
        "locomotion", "dressing", "personal_hygiene", "bathing",
    ]
    independent: list[str] = []
    assisted: list[str] = []
    for f in fields:
        val = getattr(adl_status, f, None)
        if val == "independent":
            independent.append(_adl_field_label(f))
        elif val in (
            "supervision",
            "limited_assistance",
            "extensive_assistance",
            "total_dependence",
        ):
            assisted.append(_adl_field_label(f))
    parts: list[str] = []
    if independent:
        head = ", ".join(independent[:3])
        if len(independent) > 3:
            head += f" (+{len(independent) - 3} more)"
        parts.append(f"Independent in {head}")
    if assisted:
        head = ", ".join(assisted[:3])
        if len(assisted) > 3:
            head += f" (+{len(assisted) - 3} more)"
        parts.append(f"Assistance for {head}")
    if not parts:
        return "Not documented"
    return "; ".join(parts)


def _diagnosis_summary(profile: ResidentProfile) -> str:
    parts: list[str] = []
    cp = profile.conditions_present
    if cp.diabetes and profile.diabetes:
        t = (profile.diabetes.type or "").replace("_", " ")
        label = f"Diabetes {t}".strip()
        if profile.diabetes.insulin and profile.diabetes.insulin.uses:
            label += " (insulin-dependent)"
        parts.append(label or "Diabetes")
    elif cp.diabetes:
        parts.append("Diabetes")
    if cp.dementia and profile.dementia:
        dx = (profile.dementia.diagnosis_type or "").replace("_", " ")
        stage = profile.dementia.stage or ""
        label = (dx.capitalize() + " dementia").strip() if dx else "Dementia"
        if stage:
            label += f" ({stage} stage)"
        parts.append(label)
    elif cp.dementia:
        parts.append("Dementia")
    if cp.fall_risk:
        parts.append("Fall risk")
    return "; ".join(parts) if parts else "Not documented"


def _key_risks_summary(profile: ResidentProfile) -> list[str]:
    risks: list[str] = []
    cp = profile.conditions_present
    if cp.fall_risk and profile.fall_risk:
        h = profile.fall_risk.history_6mo
        if h and h.any_falls:
            risks.append("recent fall history")
        else:
            risks.append("fall risk")
    elif cp.fall_risk:
        risks.append("fall risk")
    if cp.diabetes and profile.diabetes:
        hypo = profile.diabetes.hypoglycemia
        if hypo and hypo.history_6mo:
            risks.append("hypoglycemia history")
        ins = profile.diabetes.insulin
        if ins and ins.uses:
            risks.append("insulin-dependent")
    if cp.dementia and profile.dementia and profile.dementia.behaviors:
        b = profile.dementia.behaviors
        if b.exit_seeking:
            risks.append("exit-seeking")
        if b.agitation:
            risks.append("agitation")
        if b.sundowning:
            risks.append("sundowning")
    return risks


def _medications_summary(profile: ResidentProfile) -> str:
    meds = profile.medications or []
    if not meds:
        return "Not documented"
    if len(meds) <= 3:
        return "; ".join(meds)
    return "; ".join(meds[:3]) + f" (+{len(meds) - 3} more)"


def _family_contact_summary(profile: ResidentProfile) -> str:
    if profile.dementia and profile.dementia.family:
        contact = profile.dementia.family.primary_contact
        if contact:
            return contact
    return "Not documented"


def _patient_snapshot_dict(profile: ResidentProfile) -> dict[str, str]:
    """Build the snapshot fields once so the on-screen card and the
    markdown export can share the same data."""
    demo = profile.demographics
    name = demo.resident_name_placeholder or "Resident (name not documented)"
    age = demo.age_range or ""
    resident = f"{name}" + (f" · {age}" if age else "")
    risks = _key_risks_summary(profile)
    return {
        "Resident": resident,
        "Diagnosis": _diagnosis_summary(profile),
        "Medication / regimen": _medications_summary(profile),
        "Key risks": ", ".join(risks) if risks else "Not documented",
        "ADL status": _summarize_adl(profile.adl_status),
        "Family / proxy": _family_contact_summary(profile),
    }


def _render_patient_snapshot(profile: ResidentProfile) -> None:
    snap = _patient_snapshot_dict(profile)
    with st.container(border=True):
        st.markdown("**Patient Snapshot**")
        for k, v in snap.items():
            st.markdown(f"- **{k}:** {v}")


def _high_gap_snippet_ids(risk_register: dict) -> set[str]:
    """Collect evidence_snippet_ids cited by any high-severity gap.
    A care item that cites the same snippet IDs has a real linkage to
    a high-severity gap through the evidence layer."""
    ids: set[str] = set()
    for g in risk_register.get("gaps", []) or []:
        if g.get("severity") != "high":
            continue
        for sid in g.get("evidence_snippet_ids", []) or []:
            ids.add(sid)
    return ids


def _is_blocker_linked(item: dict, high_snippet_ids: set[str]) -> bool:
    """A care item is blocker-linked when it cites at least one
    evidence snippet that is also cited by a high-severity risk gap.
    Linkage is via shared evidence IDs, not text overlap."""
    if not high_snippet_ids:
        return False
    item_ids = set(item.get("evidence_snippet_ids", []) or [])
    return bool(item_ids & high_snippet_ids)


def _render_care_plan_metadata(
    profile: ResidentProfile,
    care_plan: dict,
    risk_register: dict,
) -> None:
    n_snippets = len(profile.evidence_snippets)
    total_items = sum(
        len(care_plan.get(k, []) or []) for _, k in _CARE_PLAN_CATEGORIES
    )
    high_ids = _high_gap_snippet_ids(risk_register)
    flagged_linked = sum(
        1
        for _, k in _CARE_PLAN_CATEGORIES
        for it in (care_plan.get(k, []) or [])
        if _is_blocker_linked(it, high_ids)
    )
    today = datetime.now().strftime("%B %d, %Y")
    st.caption(
        f"Generated {today} · Based on {n_snippets} evidence "
        f"snippets · {total_items} care items · "
        f"{flagged_linked} flagged items"
    )


def _render_humanized_evidence(
    profile: ResidentProfile, snippet_ids: list[str], context_key: str | None = None,
) -> None:
    """Back-compat shim; delegates to the unified evidence renderer."""
    _render_evidence_unified(
        profile, snippet_ids, context_key=context_key
    )


def _clip_label(text: str, limit: int = 220) -> str:
    """Trim only genuinely over-long labels, and only at a word
    boundary — never a mid-sentence ellipsis. Streamlit expander
    labels wrap, so the full phrase is preferred."""
    t = " ".join((text or "").split())
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{cut}…"


def _care_item_title(recommendation: str) -> str:
    """The first sentence of the recommendation — a complete BLUF
    directive, used as the care-item expander header (no mid-sentence
    truncation)."""
    rec = " ".join((recommendation or "").split())
    if not rec:
        return "Care item"
    first = re.split(r"(?<=[.!?])\s+", rec)[0].strip()
    return _clip_label(first)


_EVID_CODE_RE = re.compile(
    r"\b(?:gap_\d+|(?:S|F|OP)\d+(?:/(?:S|F|OP)?\d+)*)\b"
)


def _strip_codes(text: str) -> str:
    """Remove inline evidence / gap codes from human-readable prose
    and tidy the leftover punctuation. The codes remain available in
    the labeled Evidence sections and the Evidence Map tab for audit;
    they just don't interrupt the sentence. Display-only — source
    text is not modified."""
    t = _EVID_CODE_RE.sub("", text)
    # Drop parens/brackets left empty after a code was removed.
    t = re.sub(r"[\(\[]\s*[/,;]?\s*[\)\]]", "", t)
    # Tidy stray separators and whitespace.
    t = re.sub(r"\s+([.,;:)\]])", r"\1", t)
    t = re.sub(r"([(\[])\s+", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\s+([—–-])\s+\1", r" \1", t)
    return t.strip()


def _render_prose(text: str, label: str | None = None) -> None:
    """Render a dense paragraph as readable prose: one sentence per
    block, generous spacing, a comfortable reading measure, and with
    audit codes stripped out of the sentence flow. Display-only;
    source text is not modified."""
    body = _strip_codes((text or "").strip())
    if not body:
        return
    sentences = re.split(r"(?<=[.;])\s+(?=[A-Z(])", body)
    paras = "".join(
        "<p style='margin:0 0 12px 0;'>"
        + html_escape(s.strip())
        + "</p>"
        for s in sentences
        if s.strip()
    )
    label_html = ""
    if label:
        label_html = (
            "<div style='font-size:12px;font-weight:700;"
            "text-transform:uppercase;letter-spacing:0.06em;"
            "color:var(--text-muted);margin:0 0 8px 0;'>"
            f"{html_escape(label)}</div>"
        )
    st.markdown(
        "<div style='max-width:66ch;font-size:15px;"
        "line-height:1.75;color:var(--text-secondary);'>"
        f"{label_html}{paras}</div>",
        unsafe_allow_html=True,
    )


def _render_care_plan_item(
    item: dict, profile: ResidentProfile, high_snippet_ids: set[str]
) -> None:
    rec = (item.get("recommendation") or "").strip()
    title = _care_item_title(rec)
    with st.expander(title, expanded=False):
        if _is_blocker_linked(item, high_snippet_ids):
            st.warning(
                "Flagged: shares evidence with a high-severity "
                "capability gap"
            )
        # Only show the full recommendation when it adds content beyond
        # what the collapsed title already showed.
        if rec and rec != title and len(rec) > len(title):
            _render_prose(rec, label="Recommendation")
        if item.get("rationale"):
            _render_prose(item["rationale"], label="Rationale")
        _render_humanized_evidence(
            profile, item.get("evidence_snippet_ids", []) or []
        )


def _build_care_plan_export_md(
    profile: ResidentProfile, care_plan: dict
) -> str:
    today = datetime.now().strftime("%B %d, %Y")
    lines = ["# Care Plan", "", f"_Generated {today}_", ""]
    snap = _patient_snapshot_dict(profile)
    lines.append("## Patient Snapshot")
    lines.append("")
    for k, v in snap.items():
        lines.append(f"- **{k}:** {v}")
    lines.append("")
    if care_plan.get("summary"):
        lines.append("## Summary")
        lines.append("")
        lines.append(care_plan["summary"])
        lines.append("")
    for category_label, key in _CARE_PLAN_CATEGORIES:
        items = care_plan.get(key, []) or []
        if not items:
            continue
        lines.append(f"## {category_label}")
        lines.append("")
        for it in items:
            rec = (it.get("recommendation") or "").strip()
            if not rec:
                continue
            lines.append(f"- **{rec}**")
            if it.get("rationale"):
                lines.append(f"  - Rationale: {it['rationale']}")
            ev = it.get("evidence_snippet_ids", []) or []
            if ev:
                lines.append(f"  - Evidence: {', '.join(ev)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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


def _render_disagreement_card_structured(idx: int, d) -> None:
    """Render a structured disagreement card using profile.source_disagreements
    fields. Severity is UI-inferred from the field path."""
    severity_label, severity_color = _infer_severity(d.field)
    chips_html = "".join(
        evidence_chip(s) for s in (d.evidence_snippet_ids or [])
    )
    rows: list[str] = [
        f'<div style="margin-bottom:8px;"><strong>Topic:</strong> '
        f'{html_escape(_strip_codes(d.field))}</div>'
    ]
    if d.discharge_claim:
        rows.append(
            '<div style="margin-bottom:6px;"><strong>Clinical record says:</strong> '
            f'{html_escape(_strip_codes(d.discharge_claim))}</div>'
        )
    if d.family_claim:
        rows.append(
            '<div style="margin-bottom:6px;"><strong>Family says:</strong> '
            f'{html_escape(_strip_codes(d.family_claim))}</div>'
        )
    if chips_html:
        rows.append(
            f'<div style="margin-top:10px;"><strong>Evidence:</strong> '
            f'{chips_html}</div>'
        )
    body_html = "".join(rows)
    st.markdown(
        f"""
        <div class="summary-card" style="border-left: 4px solid {severity_color}; padding-left: 22px;">
          <div style="margin-bottom:8px;">
            <span style="background:{severity_color}; color:white; padding:3px 9px; border-radius:6px; font-size:11px; font-weight:700; letter-spacing:.04em;">{severity_label}</span>
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
        <div class="summary-card" style="border-left: 4px solid {severity_color}; padding-left: 22px;">
          <div style="margin-bottom:8px;">
            <span style="background:{severity_color}; color:white; padding:3px 9px; border-radius:6px; font-size:11px; font-weight:700; letter-spacing:.04em;">{severity_label}</span>
          </div>
          <div style="font-size:13px; font-weight:800; color:#374151; letter-spacing:.04em; text-transform:uppercase; margin-bottom:8px;">
            CLINICAL CONFLICT
          </div>
          <div style="font-size:15px; line-height:1.55; color:#1f2937;">
            <div style="margin-bottom:8px;"><strong>{html_escape(_strip_codes(topic))}</strong></div>
            <div>{html_escape(_strip_codes(body))}</div>
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


# ===== Action Plan worklist helpers =====


def _infer_worklist_owner(text: str) -> str:
    """UI-only worklist-owner inference. Keyword fan-out matches the
    Step 10.34 spec; labeled 'UI-inferred' wherever it appears in the
    UI."""
    lower = (text or "").lower()
    if any(
        k in lower
        for k in (
            "physician", "endocrinologist", "dr.", "dr ",
            "prescriber", "doctor", "primary care",
        )
    ):
        return "Physician"
    if any(
        k in lower
        for k in (
            "delegating rn", "rn ", "registered nurse",
            "nurse delegation", "delegation",
            "delegating nurse", "nurse",
        )
    ):
        return "Delegating RN"
    if any(
        k in lower
        for k in (
            "daughter", "son", "spouse", "family",
            "representative", "responsible party",
            "primary contact",
        )
    ):
        return "Family"
    if any(
        k in lower
        for k in (
            "home health", "pt ", "physical therapy",
            "hospital", "discharging", "discharge team",
            "discharge plan", "skilled nursing", "snf",
        )
    ):
        return "Home Health / Hospital"
    if any(
        k in lower
        for k in (
            "disclosure", "afh", "operator", "staff",
            "caregiver", "intake",
        )
    ):
        return "AFH Operator"
    return "Needs Assignment"


# ===== Admission Command Center helpers =====


_PRIORITY_COLORS = {
    # Severity-pill scheme used everywhere in the app:
    # HIGH → red, MEDIUM → amber, FOLLOW-UP → gray.
    "High": "#dc2626",          # red
    "Medium": "#d97706",        # amber
    "Follow-up": "#6b7280",     # gray
}


def _priority_badge(priority: str) -> str:
    bg = _PRIORITY_COLORS.get(priority, "#6b7280")
    return (
        f'<span style="background:{bg}; color:white; padding:3px 9px; '
        f'border-radius:6px; font-size:12px; font-weight:700; '
        f'text-transform:uppercase; letter-spacing:.04em; '
        f'margin-right:6px;">{html_escape(priority)}</span>'
    )


def _owner_chip(owner: str) -> str:
    return (
        f'<span style="background:#f3f4f6; color:#374151; '
        f'padding:3px 9px; border-radius:6px; font-size:12px; '
        f'font-weight:600; margin-right:6px;">'
        f"{html_escape(owner)}</span>"
    )


_ORIGIN_LABELS = {
    "Condition": "Condition",
    "Risk gap": "Risk Gap",
    "Open question": "Question",
    "Custom": "Custom",
}


def _origin_chip(source: str) -> str:
    label = _ORIGIN_LABELS.get(source, source)
    return (
        '<span style="background:#eef2ff; color:#3730a3; '
        'padding:3px 9px; border-radius:6px; font-size:12px; '
        f'font-weight:600;">{html_escape(label)}</span>'
    )


def _build_workstreams(
    decision: dict,
    care_plan: dict,
    risk_register: dict,
    custom_tasks: list[dict],
) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """Return (open_questions_by_owner, action_tasks_by_owner).
    Tasks carry a UI-only `type` field used to dispatch the per-type
    renderer: open questions → 'question', conditions → 'condition',
    risk gaps → 'action'. Custom tasks default to 'action' but the
    user can override via the Add Custom Task form."""
    open_qs: dict[str, list[dict]] = {}
    actions: dict[str, list[dict]] = {}

    for i, cond in enumerate(
        decision.get("conditions_before_admission", []) or []
    ):
        cond = (cond or "").strip()
        if not cond:
            continue
        owner = _infer_worklist_owner(cond)
        actions.setdefault(owner, []).append(
            {
                "id": f"cond_{i}",
                "action": cond,
                "priority": "High",
                "owner": owner,
                "source": "Condition",
                "type": "condition",
            }
        )

    for i, gap in enumerate(risk_register.get("gaps", []) or []):
        sev = gap.get("severity")
        if sev not in ("high", "medium"):
            continue
        text = (
            gap.get("suggested_next_action")
            or gap.get("resident_need")
            or ""
        ).strip()
        if not text:
            continue
        owner = _infer_worklist_owner(text)
        actions.setdefault(owner, []).append(
            {
                "id": f"riskgap_{i}",
                "action": text,
                "priority": "High" if sev == "high" else "Medium",
                "owner": owner,
                "source": "Risk gap",
                "type": "action",
            }
        )

    for i, q in enumerate(
        care_plan.get("open_questions_for_followup", []) or []
    ):
        cleaned = re.sub(r"^\d+\.\s*", "", q).strip()
        if not cleaned:
            continue
        owner = _infer_worklist_owner(cleaned)
        open_qs.setdefault(owner, []).append(
            {
                "id": f"oq_{i}",
                "action": cleaned,
                "priority": "Follow-up",
                "owner": owner,
                "source": "Open question",
                "type": "question",
            }
        )

    for ct in custom_tasks or []:
        owner = ct.get("owner") or "Needs Assignment"
        t_type = ct.get("type") or "action"
        bucket = open_qs if t_type == "question" else actions
        bucket.setdefault(owner, []).append({**ct, "type": t_type})

    return open_qs, actions


def _suggest_due_date(owner: str, target_date):
    if not target_date:
        return None
    days = _OWNER_DUE_OFFSETS_DAYS.get(owner, 3)
    try:
        return target_date - timedelta(days=days)
    except Exception:
        return None


def _is_task_done(task: dict) -> bool:
    tid = task["id"]
    t = task.get("type", "action")
    status_key = f"task_status_{tid}"
    default = _TASK_STATUS_OPTIONS[t][0]
    current = st.session_state.get(status_key, default)
    return current == _TASK_DONE_STATES[t]


def _compute_workspace_kpis(
    open_qs: dict[str, list[dict]],
    actions: dict[str, list[dict]],
) -> tuple[int, int, int, int, int]:
    """Return (high_remaining, medium_remaining, followup_remaining,
    completed, total). Completion is derived from per-type status
    fields (Answered / Confirmed / Done) rather than a generic
    checkbox."""
    all_tasks: list[dict] = []
    for tasks in open_qs.values():
        all_tasks.extend(tasks)
    for tasks in actions.values():
        all_tasks.extend(tasks)
    total = len(all_tasks)

    high_rem = sum(
        1
        for t in all_tasks
        if t["priority"] == "High" and not _is_task_done(t)
    )
    med_rem = sum(
        1
        for t in all_tasks
        if t["priority"] == "Medium" and not _is_task_done(t)
    )
    fu_rem = sum(
        1
        for t in all_tasks
        if t["priority"] == "Follow-up" and not _is_task_done(t)
    )
    completed = sum(1 for t in all_tasks if _is_task_done(t))
    return high_rem, med_rem, fu_rem, completed, total


def _init_status_key(task: dict) -> str:
    tid = task["id"]
    status_key = f"task_status_{tid}"
    if status_key not in st.session_state:
        st.session_state[status_key] = _TASK_STATUS_OPTIONS[task["type"]][0]
    return status_key


def _task_header_badges(task: dict, include_priority: bool = True) -> str:
    """Compact badge row used inside an opened task card. Owner chip is
    omitted (owner is already in the group header). Priority pill may
    be suppressed when the surrounding subgroup label (Blocking /
    Pre-admission) already conveys priority. Risk-gap-derived tasks
    also surface their gap_NN reference as a muted mono chip so the
    audit ID never appears inline in the action sentence."""
    parts: list[str] = []
    if include_priority:
        parts.append(_priority_badge(task["priority"]))
    parts.append(_origin_chip(task["source"]))
    tid = task.get("id", "")
    if tid.startswith("riskgap_"):
        try:
            gap_num = int(tid.split("_", 1)[1])
            parts.append(_mono_id_chip(f"gap_{gap_num:02d}"))
        except (ValueError, IndexError):
            pass
    return "".join(parts)


def _task_label(task: dict, include_priority: bool = True) -> str:
    # Severity is shown as a styled chip in the expanded body via
    # _task_header_badges; the collapsed header keeps a clean action
    # sentence so no raw [HIGH]/[MED]/[FOLLOW-UP] tags appear in the
    # user-facing UI.
    return task["action"]


def _render_question_task(task: dict, include_priority: bool = True) -> None:
    tid = task["id"]
    status_key = _init_status_key(task)
    answer_key = f"task_answer_{tid}"
    with st.expander(_task_label(task, include_priority), expanded=False):
        st.markdown(
            _task_header_badges(task, include_priority=include_priority),
            unsafe_allow_html=True,
        )
        st.selectbox(
            "Status",
            _TASK_STATUS_OPTIONS["question"],
            key=status_key,
        )
        st.text_area(
            "Answer / resolution",
            value=st.session_state.get(answer_key, ""),
            key=answer_key,
            height=80,
        )


def _render_condition_task(
    task: dict, include_priority: bool = True
) -> None:
    tid = task["id"]
    status_key = _init_status_key(task)
    confirmed_by_key = f"task_confirmed_by_{tid}"
    confirmed_date_key = f"task_confirmed_date_{tid}"
    note_toggle_key = f"task_show_note_{tid}"
    notes_key = f"task_notes_{tid}"
    with st.expander(_task_label(task, include_priority), expanded=False):
        st.markdown(
            _task_header_badges(task, include_priority=include_priority),
            unsafe_allow_html=True,
        )
        st.selectbox(
            "Status",
            _TASK_STATUS_OPTIONS["condition"],
            key=status_key,
        )
        col1, col2 = st.columns([2, 1])
        with col1:
            st.text_input(
                "Confirmed by",
                value=st.session_state.get(confirmed_by_key, ""),
                key=confirmed_by_key,
            )
        with col2:
            st.date_input(
                "Confirmed date",
                value=st.session_state.get(confirmed_date_key),
                key=confirmed_date_key,
            )
        show_note = st.checkbox("Add note", key=note_toggle_key)
        if show_note:
            st.text_area(
                "Note",
                value=st.session_state.get(notes_key, ""),
                key=notes_key,
                height=70,
            )


def _render_action_task(task: dict, include_priority: bool = True) -> None:
    tid = task["id"]
    status_key = _init_status_key(task)
    due_key = f"task_due_{tid}"
    note_toggle_key = f"task_show_note_{tid}"
    notes_key = f"task_notes_{tid}"
    if due_key not in st.session_state:
        target = st.session_state.get("target_move_in_date")
        st.session_state[due_key] = _suggest_due_date(task["owner"], target)
    with st.expander(_task_label(task, include_priority), expanded=False):
        st.markdown(
            _task_header_badges(task, include_priority=include_priority),
            unsafe_allow_html=True,
        )
        col_s, col_d = st.columns([2, 1])
        with col_s:
            st.selectbox(
                "Status",
                _TASK_STATUS_OPTIONS["action"],
                key=status_key,
            )
        with col_d:
            st.date_input(
                "Suggested due date",
                value=st.session_state.get(due_key),
                key=due_key,
            )
        show_note = st.checkbox("Add note", key=note_toggle_key)
        if show_note:
            st.text_area(
                "Note",
                value=st.session_state.get(notes_key, ""),
                key=notes_key,
                height=70,
            )


def _render_task_dispatch(
    task: dict, include_priority: bool = True
) -> None:
    t = task.get("type", "action")
    if t == "question":
        _render_question_task(task, include_priority=include_priority)
    elif t == "condition":
        _render_condition_task(task, include_priority=include_priority)
    else:
        _render_action_task(task, include_priority=include_priority)


def _owner_display(owner: str) -> str:
    """Operator-facing label for an owner bucket."""
    if owner == "Needs Assignment":
        return "Unassigned — needs an owner"
    return owner


def _owner_header(
    owner: str, tasks: list[dict], has_blocking: bool = False
) -> str:
    return f"{_owner_display(owner)} ({len(tasks)})"


def _render_open_questions_workstream(
    tasks_by_owner: dict[str, list[dict]],
) -> None:
    """Per-owner expanders for the Open Questions workstream. All
    tasks here are follow-up; per spec, default collapsed."""
    if not any(tasks_by_owner.values()):
        st.caption("No open questions for this resident.")
        return
    for owner in _WORKSPACE_OWNER_ORDER:
        tasks = tasks_by_owner.get(owner)
        if not tasks:
            continue
        header = _owner_header(owner, tasks)
        with st.expander(header, expanded=False):
            for task in tasks:
                _render_task_dispatch(task, include_priority=False)


def _render_action_tasks_workstream(
    tasks_by_owner: dict[str, list[dict]],
) -> None:
    """Per-owner expanders for the Action Tasks workstream, with
    Blocking (High) and Pre-admission (Medium) subgroups inside each
    owner. Groups containing Blocking items default expanded; others
    default collapsed. Priority pill is suppressed inside subgroups
    because the subgroup label already conveys priority."""
    if not any(tasks_by_owner.values()):
        st.caption("No action tasks for this resident.")
        return
    for owner in _WORKSPACE_OWNER_ORDER:
        tasks = tasks_by_owner.get(owner)
        if not tasks:
            continue
        blocking = [t for t in tasks if t["priority"] == "High"]
        pre_adm = [t for t in tasks if t["priority"] == "Medium"]
        other = [
            t
            for t in tasks
            if t["priority"] not in ("High", "Medium")
        ]
        header = _owner_header(owner, tasks, has_blocking=bool(blocking))
        with st.expander(header, expanded=bool(blocking)):
            if blocking:
                st.markdown(
                    "<div class='ws-subgroup'>Required before "
                    "move-in</div>",
                    unsafe_allow_html=True,
                )
                for task in blocking:
                    _render_task_dispatch(task, include_priority=False)
            if pre_adm:
                st.markdown(
                    "<div class='ws-subgroup'>Before the target "
                    "date</div>",
                    unsafe_allow_html=True,
                )
                for task in pre_adm:
                    _render_task_dispatch(task, include_priority=False)
            if other:
                st.markdown(
                    "<div class='ws-subgroup'>Other</div>",
                    unsafe_allow_html=True,
                )
                for task in other:
                    _render_task_dispatch(task, include_priority=True)


def _render_add_custom_task() -> None:
    with st.expander("Add custom task", expanded=False):
        text = st.text_input(
            "Task text", key="custom_task_text_input"
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            owner = st.selectbox(
                "Owner",
                _WORKSPACE_OWNER_ORDER,
                key="custom_task_owner_select",
            )
        with col2:
            severity = st.selectbox(
                "Priority",
                ["High", "Medium", "Follow-up"],
                key="custom_task_priority_select",
            )
        with col3:
            t_type = st.selectbox(
                "Type",
                ["action", "question", "condition"],
                key="custom_task_type_select",
            )
        if st.button("Add task", key="custom_task_add_button"):
            cleaned = (text or "").strip()
            if not cleaned:
                st.warning("Task text is required.")
            else:
                n = len(st.session_state.custom_tasks)
                st.session_state.custom_tasks.append(
                    {
                        "id": f"custom_{n}",
                        "action": cleaned,
                        "priority": severity,
                        "owner": owner,
                        "source": "Custom",
                        "type": t_type,
                    }
                )
                # Clear the input by removing its key; Streamlit will
                # re-init the widget to its default empty value on the
                # next rerun. Direct assignment to a widget-bound key
                # after the widget is rendered raises in Streamlit.
                if "custom_task_text_input" in st.session_state:
                    del st.session_state["custom_task_text_input"]
                st.rerun()


def _wipe_workspace_state() -> None:
    """Clear all per-task session state (status, due, notes, answer,
    confirmed_by, confirmed_date, show_note) plus custom tasks. The
    target_move_in_date is preserved across regenerate."""
    for k in list(st.session_state.keys()):
        if k.startswith("task_"):
            del st.session_state[k]
    st.session_state.custom_tasks = []


# ===== Action Plan markdown sectionizer =====


_SEVERITY_DOT_COLORS = {
    "CRITICAL": "#a32c3a",
    "HIGH": "#a32c3a",
    "MEDIUM": "#a86610",
    "MED": "#a86610",
    "LOW": "#6c6c66",
    "FOLLOW-UP": "#6c6c66",
    "FOLLOWUP": "#6c6c66",
}


def _decorate_severity_tokens(md: str) -> str:
    """Display-only: replace bracketed severity tokens like [HIGH] in
    the generated-document preview with a small colored dot. The stored
    draft_action_plan (PDF / markdown export) is untouched."""
    def _repl(m: "re.Match") -> str:
        word = m.group(1).upper().replace(" ", "")
        color = _SEVERITY_DOT_COLORS.get(word, "#6c6c66")
        pretty = m.group(1).strip().title()
        return (
            f"<span title='{pretty}' style='display:inline-block;"
            f"width:9px;height:9px;border-radius:50%;background:"
            f"{color};vertical-align:middle;margin-right:7px;'></span>"
        )

    return re.sub(
        r"\[(CRITICAL|HIGH|MEDIUM|MED|LOW|FOLLOW[- ]?UP)\]",
        _repl,
        md,
        flags=re.IGNORECASE,
    )


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


def _conf_chip(conf: str) -> str:
    """Blue clinical-reference chip for a CARE confidence level."""
    label = (conf or "").strip().lower()
    pretty = f"{label.title()} confidence" if label else "Confidence —"
    return (
        f'<span style="background:#dbeafe; color:#1e40af; padding:3px 9px; '
        f'border-radius:6px; font-size:12px; font-weight:700; '
        f'margin-right:6px; display:inline-block;">'
        f'{html_escape(pretty)}</span>'
    )


def _gap_flag_chip() -> str:
    return (
        '<span style="background:#fef3c7; color:#92400e; padding:3px 9px; '
        'border-radius:6px; font-size:12px; font-weight:700; '
        'margin-right:6px; display:inline-block;">Gap flagged</span>'
    )


def _composite_chip() -> str:
    return (
        '<span style="background:#fef3c7; color:#92400e; padding:3px 9px; '
        'border-radius:6px; font-size:12px; font-weight:700; '
        'margin-right:6px; display:inline-block;">'
        'Composite recommendation</span>'
    )


def _mono_id_chip(text: str) -> str:
    """Neutral mono chip for a CARE-factor identifier."""
    return (
        f'<span style="background:#f3f4f6; color:#374151; padding:3px 9px; '
        f'border-radius:6px; font-family:monospace; font-size:11px; '
        f'font-weight:600; margin-right:6px; display:inline-block;">'
        f'{html_escape(text)}</span>'
    )


def _is_composite_factor(rec: dict) -> bool:
    wac = (rec.get("wac_citation") or "").strip().lower()
    if not wac:
        return True
    return any(
        marker in wac
        for marker in ("no direct", "composite", "not enumerated",
                       "not separately enumerated")
    )


def _split_wac_citation(text: str) -> tuple[str, str]:
    """Split 'WAC 388-106-0095: prose' into (code, plain_english).
    Returns ('', '') when nothing useful can be extracted."""
    s = (text or "").strip()
    if not s:
        return "", ""
    m = re.match(
        r"^(WAC\s+[\d\-\.]+)\s*[:\-—]\s*(.+)$", s, re.IGNORECASE
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    if s.lower().startswith("wac"):
        return s, ""
    return "", s


def _render_acuity_factor_nested(
    rec: dict,
    profile: ResidentProfile,
    *,
    suppress_disclosure_warning: bool = False,
) -> None:
    name = rec.get("acuity_factor_name", rec.get("acuity_factor_id", "?"))
    conf = rec.get("confidence", "low")
    gap_flag = bool(rec.get("disclosure_gap_flagged"))
    factor_id = (rec.get("acuity_factor_id") or "").strip()
    composite = _is_composite_factor(rec)
    wac_code, wac_plain = _split_wac_citation(rec.get("wac_citation") or "")

    with st.expander(name, expanded=False):
        chips = _conf_chip(conf)
        if gap_flag:
            chips += _gap_flag_chip()
        if composite:
            chips += _composite_chip()
        if factor_id:
            chips += _mono_id_chip(factor_id)
        st.markdown(chips, unsafe_allow_html=True)
        if composite:
            st.caption(
                "This factor is clinically relevant but not separately "
                "enumerated in CARE."
            )
        if wac_code:
            st.markdown(f"**{wac_code}**")
        if wac_plain:
            st.caption(wac_plain)
        if rec.get("disclosure_support_snippet"):
            st.markdown(
                "_Disclosure quote:_ > "
                f"{rec['disclosure_support_snippet']}"
            )
        elif gap_flag and not suppress_disclosure_warning:
            st.warning(
                "AFH disclosure does not clearly support this capability."
            )
        _render_evidence_unified(
            profile,
            rec.get("resident_need_evidence", []) or [],
            context_key=f"acuity_{factor_id or name}",
            inline=True,
        )


_OPERATOR_VALUE_MAP = {
    ("DIABETES_TYPE", "type_1"): "Type 1 diabetes",
    ("DIABETES_TYPE", "type_2"): "Type 2 diabetes",
    ("INSULIN_USE", "True"): "Insulin in use",
    ("INSULIN_USE", "False"): "No insulin in use",
    ("INSULIN_REGIMEN", "sliding_scale"): "Sliding-scale regimen",
    ("INSULIN_REGIMEN", "basal_bolus"): "Basal-bolus regimen",
    ("INSULIN_ADMIN", "staff"): "Staff administer insulin",
    ("INSULIN_ADMIN", "self"): "Resident self-administers insulin",
    ("INSULIN_ADMIN", "staff/self"): "Staff and resident both involved",
}
_OPERATOR_PREFIX_MAP = {
    "BGM_FREQUENCY": "Blood glucose monitoring frequency reported",
    "MOBILITY_AID": "Mobility aid reported",
}


def _operator_claim_parts(claim: str) -> tuple[str, str] | None:
    """Return (node_id, raw_value) parsed from 'operator answer at NODE -> val',
    or None when the claim is not in that internal format."""
    m = re.match(r"operator answer at (\w+)\s*->\s*(.+)$", (claim or "").strip())
    if not m:
        return None
    node_id = m.group(1)
    raw = m.group(2).strip()
    if len(raw) >= 2 and raw[0] in ("'", '"') and raw[-1] == raw[0]:
        raw = raw[1:-1]
    return node_id, raw


def _humanize_operator_claim(claim: str) -> str:
    """Turn 'operator answer at NODE_ID -> value' into a readable phrase."""
    parts = _operator_claim_parts(claim)
    if parts is None:
        return claim or ""
    node_id, val = parts
    mapped = _OPERATOR_VALUE_MAP.get((node_id, val))
    if mapped:
        return mapped
    if node_id in _OPERATOR_PREFIX_MAP:
        return _OPERATOR_PREFIX_MAP[node_id]
    return val or claim


def _parse_mismatch(verbatim: str, raw_value: str, humanized: str) -> bool:
    """Heuristic: True when the verbatim operator answer shares no
    substantive token with the system's normalized recording — i.e. a
    parse may have collapsed or reshaped the answer."""
    v = (verbatim or "").lower()
    if not v:
        return False
    candidates = [
        (raw_value or "").replace("_", " ").lower(),
        (humanized or "").lower(),
    ]
    tokens: list[str] = []
    for c in candidates:
        tokens.extend(t for t in re.findall(r"[a-z0-9]+", c) if len(t) >= 4)
    if not tokens:
        return False
    return not any(t in v for t in tokens)


def _next_ev_ctx_key() -> str:
    """Per-render counter used to give evidence-chip buttons unique keys
    when the unified evidence renderer is called multiple times in one
    Streamlit run. Reset at the top of synthesis_done."""
    n = int(st.session_state.get("_ev_ctx_seq", 0)) + 1
    st.session_state["_ev_ctx_seq"] = n
    return f"ctx{n}"


_SEMANTIC_CHIP_CSS = (
    "background:#eef2ff; color:#3730a3; padding:3px 9px; "
    "border-radius:999px; font-size:11px; font-weight:700; "
    "margin-right:6px; display:inline-block;"
)


def _render_evidence_unified(
    profile: ResidentProfile,
    snippet_ids: list[str],
    *,
    context_key: str | None = None,
    label: str | None = None,
    inline: bool = False,
) -> None:
    """Single shared evidence renderer for Care Plan, CARE Factors,
    Capability Gaps, and the Sources & Debug audit views.

    Behavior:
      • Each operator snippet is humanized via _humanize_operator_claim
        so backend strings like "operator answer at NODE -> 'val'" never
        reach the user-facing UI.
      • When the operator's raw answer differs materially from what the
        pipeline normalized, an inline "Needs confirmation" warning is
        shown with both sides.
      • Each snippet ID renders as a clickable chip that sets a
        session-state filter Sources & Debug honors.

    When the caller is itself inside an expander (e.g. a CARE-factor
    card), pass inline=True to avoid nesting accordions.
    """
    if not snippet_ids:
        return
    ctx = context_key or _next_ev_ctx_key()
    by_id = {s.snippet_id: s for s in profile.evidence_snippets}
    exp_label = label or f"Evidence ({len(snippet_ids)})"
    if inline:
        st.markdown(f"**{exp_label}**")
        body = st.container()
    else:
        body = st.expander(exp_label, expanded=False)
    with body:
        st.markdown(
            "<div style='font-size:11px; color:var(--text-muted); "
            "margin-bottom:6px;'>Evidence IDs trace each statement to "
            "its source — <b>S</b> clinical record · <b>F</b> family "
            "notes · <b>OP</b> operator interview answer. Click an ID "
            "to inspect it.</div>",
            unsafe_allow_html=True,
        )
        # De-duplicate while preserving order — a gap/care item can
        # cite the same snippet more than once.
        seen_ids: set[str] = set()
        unique_ids = [
            s for s in snippet_ids
            if not (s in seen_ids or seen_ids.add(s))
        ]
        for _i, sid in enumerate(unique_ids):
            snip = by_id.get(sid)
            if snip is None:
                st.markdown(f"- `{sid}` — _(not in current profile)_")
                continue
            chip_col, body_col = st.columns(
                [1, 6],
                gap="small",
                vertical_alignment="center",
            )
            with chip_col:
                if st.button(
                    sid,
                    key=f"ev_chip_{ctx}_{_i}_{sid}",
                    help="Pin this snippet at the top of the "
                    "Evidence Map tab",
                    use_container_width=True,
                ):
                    st.session_state["evidence_filter_snippet_id"] = sid
                    st.rerun()
            with body_col:
                if snip.source == "operator":
                    parts = _operator_claim_parts(snip.claim)
                    if parts is None:
                        st.markdown(
                            f"**Operator:** {snip.verbatim_text}"
                        )
                    else:
                        node_id, raw_value = parts
                        display = _humanize_operator_claim(snip.claim)
                        st.markdown(f"**Operator:** {display}")
                        if _parse_mismatch(
                            snip.verbatim_text, raw_value, display
                        ):
                            st.warning(
                                f"Needs confirmation — Operator said: "
                                f"{snip.verbatim_text}  ·  System "
                                f"recorded: "
                                f"{raw_value.replace('_', ' ')}"
                            )
                elif snip.source == "discharge":
                    st.markdown(
                        f"**Clinical record:** {snip.verbatim_text}"
                    )
                elif snip.source == "family":
                    st.markdown(f"**Family:** {snip.verbatim_text}")
                else:
                    st.markdown(
                        f"**{snip.source.title()}:** {snip.verbatim_text}"
                    )


def _format_suggested_action(text: str) -> None:
    """Render suggested_next_action; split (1)(2)(3)-style clauses into a
    numbered list. Otherwise render as a paragraph."""
    s = (text or "").strip()
    if not s:
        return
    parts = re.split(r"\s*\(\d+\)\s*", s)
    if len(parts) > 1:
        intro = parts[0].strip()
        items = [p.strip() for p in parts[1:] if p.strip()]
        if items:
            if intro:
                st.write(intro)
            for i, item in enumerate(items, 1):
                st.markdown(f"{i}. {item}")
            return
    st.write(s)


def _render_risk_evidence_snippets(
    profile: ResidentProfile, snippet_ids: list[str], context_key: str | None = None,
) -> None:
    """Thin wrapper kept for back-compat; routes through the unified
    evidence renderer."""
    _render_evidence_unified(
        profile, snippet_ids, context_key=context_key
    )


def _render_risk_gap_nested(
    gap: dict, profile: ResidentProfile, index: int
) -> None:
    sev = gap.get("severity", "low")
    need = (gap.get("resident_need") or "").strip()
    with st.expander(_clip_label(need) or "Capability gap",
                     expanded=False):
        st.markdown(severity_badge(sev), unsafe_allow_html=True)
        missing = (gap.get("missing_or_weak_support") or "").strip()
        if missing:
            _render_prose(missing, label="The concern")
        action = (gap.get("suggested_next_action") or "").strip()
        if action:
            st.markdown(
                "<div style='font-size:12px;font-weight:700;"
                "text-transform:uppercase;letter-spacing:0.06em;"
                "color:var(--text-muted);margin:4px 0 6px 0;'>"
                "Recommended next step</div>",
                unsafe_allow_html=True,
            )
            _format_suggested_action(action)
        _render_risk_evidence_snippets(
            profile, gap.get("evidence_snippet_ids", []) or []
        )
        st.caption(
            "Related tasks are tracked in the Action Plan tab. "
            f"Audit reference: gap_{index:02d} "
            "(this gap's ID in the capability-gap register)."
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
    """Legacy shim — every caller now routes through the unified
    renderer, which humanizes operator claims and renders clickable
    snippet-id chips."""
    _render_evidence_unified(profile, snippet_ids)


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
            _render_prose(item["rationale"], label="Rationale")
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


def severity_badge(level: str) -> str:
    # Severity-pill scheme: HIGH → red, MEDIUM → amber, LOW → gray.
    colors = {
        "high": ("#dc2626", "white"),
        "medium": ("#d97706", "white"),
        "low": ("#6b7280", "white"),
    }
    bg, fg = colors.get(str(level).lower(), ("#6b7280", "white"))
    return (
        f'<span style="background:{bg}; color:{fg}; padding:4px 0; '
        f'border-radius:6px; font-size:12px; font-weight:700; '
        f'text-transform:uppercase; margin-right:8px; '
        f'display:inline-block; min-width:78px; text-align:center; '
        f'letter-spacing:0.04em;">{level}</span>'
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
    "discharge": "Clinical record",
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
        label += " · linked to a high-severity gap"
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
    Reference-finding logic unchanged. The caller is expected to wrap
    this in a single expander so we don't double-nest accordions.
    """
    with st.container():
        st.caption(
            "Every claim in the artifacts traces back to a verbatim "
            "source quote. Use the filters below to narrow the view; "
            "expand any snippet for full text and the artifacts that "
            "cite it."
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
            "S = clinical record · F = family note · "
            "OP = operator interview answer · gap_XX = capability-gap "
            "register item"
        )

        st.divider()

        # Filter controls.
        col_src, col_ref, col_hi = st.columns([1, 1, 1])
        with col_src:
            source_filter = st.selectbox(
                "Source",
                ["All", "Clinical record", "Family", "Operator"],
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
            f"Coverage: Clinical record {discharge_count} · Family "
            f"{family_count} · Operator {operator_count} · Total {total}"
        )

        # Filter application.
        def _matches(s, refs: list[str]) -> bool:
            _src_key = {
                "Clinical record": "discharge",
                "Family": "family",
                "Operator": "operator",
            }.get(source_filter, source_filter.lower())
            if source_filter != "All" and s.source != _src_key:
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
            ("discharge", "Clinical record evidence"),
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
    st.markdown(
        "<div style='font-size:18px; font-weight:700; "
        "color:#111827; margin-bottom:6px;'>Workspace</div>",
        unsafe_allow_html=True,
    )
    _stage_help = {
        "input": (
            "Paste the patient's clinical record, family notes, and "
            "(recommended) the AFH disclosure. Stage 1 extracts the "
            "structured profile."
        ),
        "profile_review": (
            "Review what Stage 1 pulled. Continue to start the "
            "condition-specific interview."
        ),
        "interview": (
            "Answer each question to confirm or fill gaps in the "
            "extracted profile. You can use Ask later for unknowns."
        ),
        "synthesis_ready": (
            "Generate the care plan, acuity factors, risk register and "
            "intake decision in a single batch."
        ),
        "synthesis_done": (
            "Review the verdict and work through the concerns to "
            "address. Acknowledge to start working the Action Plan."
        ),
    }
    st.caption(
        _stage_help.get(
            st.session_state.get("stage", "input"),
            "",
        )
    )
    with st.expander("Developer tools", expanded=False):
        compare_baseline = st.toggle(
            "Compare against baseline",
            value=False,
            help=(
                "Run the single-call baseline on the same inputs and "
                "show side-by-side with the staged pipeline once "
                "artifacts are ready."
            ),
        )

    if (
        st.session_state.stage == "interview"
        and _has_active_interview_question(
            st.session_state.get("session")
        )
    ):
        st.divider()
        st.subheader("Captured so far")
        _session = st.session_state.session
        _profile = st.session_state.profile
        _op_snips = [
            s for s in _profile.evidence_snippets if s.source == "operator"
        ]
        st.caption(f"Operator evidence snippets: {len(_op_snips)}")
        _current_tree_id = _session.trees[_session.current_tree_idx]["tree_id"]
        _section = _NODE_SECTION.get(
            (_session.get_next_question() or {}).get("node_id"), ""
        )
        _section_label = (
            f"{_TREE_PRETTY.get(_current_tree_id, _current_tree_id)}"
            + (f" → {_section}" if _section else "")
        )
        st.caption(f"Current section: {_section_label}")
        st.caption(
            "Triggered conditions: "
            + (
                ", ".join(
                    _TREE_PRETTY.get(c, c)
                    for c in st.session_state.triggered_conditions
                )
                or "(none)"
            )
        )
        if _op_snips:
            st.markdown("**Last 5 operator answers**")
            for _s in _op_snips[-5:][::-1]:
                parts = _operator_claim_parts(_s.claim)
                if parts is None:
                    fallback = (
                        _s.verbatim_text
                        or _humanize_operator_claim(_s.claim)
                    )
                    st.markdown(f"- Operator answer: {fallback}")
                    continue
                _nid, _raw = parts
                _label = _NODE_LABEL_HUMAN.get(_nid)
                _value = _humanize_option_value(_raw)
                if _label:
                    st.markdown(f"- **{_label}:** {_value}")
                else:
                    st.markdown(f"- Operator answer: {_value}")
        with st.expander("Full profile JSON", expanded=False):
            st.json(_profile.model_dump(exclude_none=True))

    st.divider()
    if st.button("Reset session"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()


# ===== Main area =====

stage = st.session_state.stage


# --- Stage: input ---

if stage == "input":
    _hour = datetime.now().hour
    if _hour < 12:
        _greet = "Good morning"
    elif _hour < 18:
        _greet = "Good afternoon"
    else:
        _greet = "Good evening"
    st.markdown(
        f"<div class='t-headline'>{_greet} — let's start a "
        "new intake</div>"
        "<div class='t-body' style='margin: 8px 0 24px 0; "
        "max-width: 620px;'>"
        "Provide the patient's clinical record and family notes to "
        "begin. The AFH disclosure is recommended so the "
        "capability-gap analysis can anchor to disclosure language."
        "</div>",
        unsafe_allow_html=True,
    )

    def _load_upload_text(upload):
        """Return (text, size_bytes, error_str). On failure, text is ''."""
        if upload is None:
            return "", 0, None
        try:
            size_bytes = int(getattr(upload, "size", 0) or 0)
            if upload.name.lower().endswith(".pdf"):
                text = _read_pdf(upload)
            else:
                text = upload.read().decode("utf-8", errors="replace")
            return text, size_bytes, None
        except Exception as exc:
            return "", 0, str(exc)

    def _resolve_input_field(text_value, upload):
        """Return the final text the pipeline should consume. If an upload
        is present, its extracted text wins and we render either a weak-
        extraction warning or a confirmation. Falls back to the textarea."""
        if upload is None:
            return text_value
        loaded, size_bytes, err = _load_upload_text(upload)
        if err is not None:
            st.error(f"Could not read uploaded file: {err}")
            return text_value
        if len(loaded) < 100 and size_bytes > 100 * 1024:
            st.warning(
                f"Only {len(loaded)} characters were extracted from this "
                "file. It may be scanned or image-based. Paste text "
                "manually or run OCR before continuing."
            )
        else:
            st.info("Uploaded file text loaded into this field.")
        return loaded

    st.markdown(
        "**Clinical record** "
        "<span style='background:#a3262e;color:white;padding:2px 8px;"
        "border-radius:4px;font-size:11px;font-weight:600;letter-spacing:"
        ".06em;margin-left:6px;'>REQUIRED</span>"
        "<br><span style='font-size:12px;color:var(--text-muted);'>"
        "Discharge summary, H&amp;P, or current provider notes — "
        "whatever clinical documentation you have.</span>",
        unsafe_allow_html=True,
    )
    discharge_text = st.text_area(
        "Clinical record text",
        height=220,
        key="input_discharge_text",
        label_visibility="collapsed",
    )
    discharge_upload = st.file_uploader(
        "Upload .txt / .pdf",
        type=["txt", "pdf"],
        key="input_discharge_upload",
    )
    discharge = _resolve_input_field(discharge_text, discharge_upload)

    st.markdown(
        "**Family notes** "
        "<span style='background:#a3262e;color:white;padding:2px 8px;"
        "border-radius:4px;font-size:11px;font-weight:600;letter-spacing:"
        ".06em;margin-left:6px;'>REQUIRED</span>",
        unsafe_allow_html=True,
    )
    family_text = st.text_area(
        "Family notes text",
        height=200,
        key="input_family_text",
        label_visibility="collapsed",
    )
    family_upload = st.file_uploader(
        "Upload .txt / .pdf",
        type=["txt", "pdf"],
        key="input_family_upload",
    )
    family = _resolve_input_field(family_text, family_upload)

    st.markdown(
        "**AFH Disclosure of Services** "
        "<span style='background:#a86610;color:white;padding:2px 8px;"
        "border-radius:4px;font-size:11px;font-weight:600;letter-spacing:"
        ".06em;margin-left:6px;'>RECOMMENDED</span>",
        unsafe_allow_html=True,
    )
    disclosure_text = st.text_area(
        "Disclosure text",
        height=180,
        key="input_disclosure_text",
        label_visibility="collapsed",
    )
    disclosure_upload = st.file_uploader(
        "Upload disclosure (.txt / .pdf)",
        type=["txt", "pdf"],
        key="input_disclosure_upload",
    )
    disclosure = _resolve_input_field(disclosure_text, disclosure_upload)

    can_start = bool((discharge or "").strip() and (family or "").strip())
    if st.button(
        "Start Intake",
        type="primary",
        disabled=not can_start,
        key="start_intake_btn",
    ):
        try:
            with st.spinner(
                "Reading the documents and pulling structured fields…"
            ):
                profile, triggered = run_initial_extraction(
                    discharge_summary=discharge,
                    family_notes=family,
                    disclosure_text=disclosure,
                )
        except Exception as exc:
            st.error(
                "Stage 1 extraction failed. The model call returned an "
                "error. You can retry by clicking Start Intake again."
            )
            st.caption(f"Details: {exc}")
            st.stop()
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
            # Fresh per-session Back-history (never the shared
            # DEFAULT_STATE list, so a reset starts truly empty).
            st.session_state.interview_history = []
            # Y for interview progress: sum of all nodes across triggered
            # trees, computed ONCE at interview start so the progress bar
            # never moves backward as branching skips nodes.
            st.session_state.interview_total_nodes = sum(
                len(t["nodes"]) for t in session.trees
            )
            st.session_state.stage = "profile_review"
        else:
            st.info(
                "Stage 1 flagged no conditions for interview; jumping to synthesis."
            )
            st.session_state.stage = "synthesis_ready"
        st.rerun()


# --- Stage: profile_review ---

elif stage == "profile_review":
    st.markdown(
        "<div class='t-headline'>Confirm what we extracted</div>"
        "<div class='t-body' style='margin: 8px 0 24px 0; "
        "max-width: 620px;'>"
        "Stage 1 pulled the structured profile below from your "
        "documents. Review it, then continue to the condition-specific "
        "interview."
        "</div>",
        unsafe_allow_html=True,
    )
    profile = st.session_state.profile
    triggered = st.session_state.triggered_conditions

    op_count = sum(
        1 for s in profile.evidence_snippets if s.source == "operator"
    )
    nonop_count = len(profile.evidence_snippets) - op_count

    c1, c2, c3 = st.columns(3)
    c1.metric("Triggered conditions", len(triggered))
    c2.metric("Evidence snippets", nonop_count)
    c3.metric("Source disagreements", len(profile.source_disagreements))

    st.markdown("**Triggered conditions**")
    if triggered:
        st.write(
            ", ".join(_TREE_PRETTY.get(c, c) for c in triggered)
        )
    else:
        st.write("(none)")

    st.markdown("**Key extracted fields**")
    rows: list[tuple[str, str]] = []
    if profile.diabetes is not None:
        dtype = getattr(profile.diabetes, "type", None)
        if dtype:
            rows.append(
                ("Diabetes type", _humanize_option_value(str(dtype)))
            )
        insulin = getattr(
            getattr(profile.diabetes, "insulin", None), "uses", None
        )
        if insulin is not None:
            rows.append(("Insulin use", "Yes" if insulin else "No"))
    if profile.fall_risk is not None:
        falls = getattr(
            getattr(profile.fall_risk, "history_6mo", None),
            "any_falls",
            None,
        )
        if falls is not None:
            rows.append(
                ("Fall history (6mo)", "Yes" if falls else "No")
            )
        aid = getattr(profile.fall_risk, "assistive_device", None)
        if aid:
            rows.append(
                ("Mobility aid", _humanize_option_value(str(aid)))
            )
    if profile.dementia is not None:
        dx = getattr(profile.dementia, "diagnosis_status", None)
        if dx:
            rows.append(
                (
                    "Dementia diagnosis",
                    _humanize_option_value(str(dx)),
                )
            )
        stage_v = getattr(profile.dementia, "stage", None)
        if stage_v:
            rows.append(
                ("Dementia stage", _humanize_option_value(str(stage_v)))
            )
    adl = profile.adl_status
    adl_dep: list[str] = []
    if adl is not None:
        for f in (
            "bathing",
            "dressing",
            "toilet_use",
            "transfers",
            "eating",
        ):
            v = getattr(adl, f, None)
            if v and str(v).lower() not in ("independent", "unknown"):
                adl_dep.append(f.replace("_", " "))
        if adl_dep:
            rows.append(("ADL support needed", ", ".join(adl_dep)))
        else:
            rows.append(
                ("ADL status", "Independent or unknown across ADLs")
            )

    if rows:
        for label, value in rows:
            st.markdown(f"- **{label}:** {value}")
    else:
        st.caption("No structured fields extracted yet.")

    st.info(
        "Interview will ask only the condition-specific follow-up "
        "questions needed to confirm or fill gaps."
    )

    col_a, col_b = st.columns([1, 4])
    with col_a:
        if st.button("Continue to Interview", type="primary"):
            st.session_state.stage = "interview"
            st.rerun()
    with col_b:
        if st.button("← Edit source documents"):
            st.session_state.stage = "input"
            st.rerun()


# --- Stage: interview ---

elif stage == "interview":
    session = st.session_state.session
    if not _has_active_interview_question(session):
        # Either the operator just answered the last question (current
        # tree index has advanced past the end) or the session was reset
        # / never created. The first case is a normal completion; the
        # second needs an explicit operator decision.
        if session is not None and getattr(session, "trees", None):
            st.session_state.stage = "synthesis_ready"
            st.rerun()
        st.warning(
            "Interview session ended or became invalid. Continue to "
            "artifact generation or reset session."
        )
        cols = st.columns(2)
        with cols[0]:
            if st.button("Continue", key="interview_fallback_continue"):
                st.session_state.stage = "synthesis_ready"
                st.rerun()
        with cols[1]:
            if st.button(
                "Reset session", key="interview_fallback_reset"
            ):
                for _k in list(st.session_state.keys()):
                    del st.session_state[_k]
                st.rerun()
        st.stop()

    node = session.get_next_question()

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
    minutes_remaining = max(round((y_total - x_current) * 30 / 60), 0)

    with st.container(border=True):
        st.markdown(
            f"**Question {x_current} of up to {y_total}**"
        )
        st.markdown(f"Section: {breadcrumb}")
        st.caption(
            f"Estimated time remaining: ~{minutes_remaining} minute"
            f"{'' if minutes_remaining == 1 else 's'}"
        )
        st.progress(min(x_current / y_total, 1.0) if y_total else 0.0)
        if not st.session_state.get("_interview_up_to_explained"):
            st.caption(
                "Question count may shorten depending on answers."
            )
            st.session_state._interview_up_to_explained = True

    # Back navigation — restore the snapshot taken before the last
    # answer so the operator can change a prior response.
    _history = st.session_state.get("interview_history") or []
    if _history:
        back_col, _ = st.columns([1, 4])
        with back_col:
            if st.button(
                "← Back",
                key="interview_back_btn",
                use_container_width=True,
            ):
                _restore_session(st.session_state.interview_history.pop())
                st.rerun()

    # Friendly milestone callouts so the operator feels momentum.
    if y_total:
        _ratio = x_current / y_total
        if x_current == y_total:
            st.markdown(
                "<div class='milestone'>🎯 Last question — you're "
                "almost there.</div>",
                unsafe_allow_html=True,
            )
        elif x_current > 1 and 0.45 <= _ratio <= 0.55:
            st.markdown(
                "<div class='milestone'>🚀 Halfway through the "
                "interview.</div>",
                unsafe_allow_html=True,
            )

    question_label = _QUESTION_TEXT_OVERRIDES.get(
        node["node_id"], node["question_text"]
    )
    st.markdown(
        f"<div class='interview-q'>{html_escape(question_label)}</div>",
        unsafe_allow_html=True,
    )
    if node.get("context_hint"):
        with st.expander("Context", expanded=False):
            st.write(node["context_hint"])

    shape = node["expected_answer_shape"]
    options = node.get("answer_options") or []
    node_id = node["node_id"]

    def _submit(value: str) -> None:
        # Snapshot the pre-answer state so the operator can step Back.
        snap = _snapshot_session(session)
        try:
            with st.spinner("Parsing answer..."):
                session.submit_answer(value)
        except Exception as exc:
            st.error(
                "Could not parse that answer. The model call failed; "
                "please try a different phrasing or use Ask later."
            )
            st.caption(f"Details: {exc}")
            return
        st.session_state.interview_history.append(snap)
        st.rerun()

    btn_key_base = f"{tree_id}_{node_id}"

    if node_id == "MEDS_FALL_RISK_CATEGORIES":
        st.caption("Select all that apply, or choose None.")
        selected = st.multiselect(
            "Categories",
            options=_FRID_CATEGORY_OPTIONS,
            key=f"frid_select_{btn_key_base}",
            label_visibility="collapsed",
        )
        other_detail = ""
        if "Other" in selected:
            other_detail = st.text_input(
                "Describe 'Other' category",
                key=f"frid_other_{btn_key_base}",
            )
        none_with_others = (
            "None" in selected and len(selected) > 1
        )
        if none_with_others:
            st.warning(
                "'None' cannot be combined with medication categories. "
                "Submit only 'None' or remove it before continuing."
            )
        if st.button(
            "Submit categories",
            type="primary",
            key=f"frid_submit_{btn_key_base}",
            use_container_width=True,
        ):
            if not selected:
                st.warning("Pick at least one category, or choose None.")
            elif none_with_others:
                st.warning(
                    "Remove 'None' or remove the other categories."
                )
            else:
                parts = []
                for p in selected:
                    if p == "Other" and other_detail.strip():
                        parts.append(f"Other: {other_detail.strip()}")
                    else:
                        parts.append(p)
                _submit(", ".join(parts))
    elif node_id in _MULTISELECT_ENUM_NODES and shape == "enum" and options:
        st.caption("Check all that apply.")
        _ovr = _MULTISELECT_OPTION_OVERRIDES.get(node_id, {})
        _remove = _ovr.get("remove", set())
        _opts = [o for o in options if o not in _remove]
        for _extra in _ovr.get("add", []):
            if _extra not in _opts:
                _opts.append(_extra)
        # Keep "unknown" as the last choice.
        if "unknown" in _opts:
            _opts = [o for o in _opts if o != "unknown"] + ["unknown"]
        picked: list[str] = []
        for opt in _opts:
            if st.checkbox(
                _humanize_option_value(opt),
                key=f"chk_{btn_key_base}_{opt}",
            ):
                picked.append(opt)
        if st.button(
            "Submit selection",
            type="primary",
            key=f"multi_submit_{btn_key_base}",
            use_container_width=True,
        ):
            if not picked:
                st.warning("Check at least one option.")
            else:
                _submit(
                    picked[0]
                    if len(picked) == 1
                    else ", ".join(picked)
                )
    elif shape == "enum" and options:
        cols = st.columns(min(len(options), 4))
        for i, opt in enumerate(options):
            col = cols[i % len(cols)]
            if col.button(
                _humanize_option_value(opt),
                key=f"enum_{btn_key_base}_{opt}",
                use_container_width=True,
                type="primary",
            ):
                _submit(opt)
    elif shape == "boolean":
        b1, b2, b3 = st.columns(3)
        if b1.button(
            "Yes",
            key=f"bool_yes_{btn_key_base}",
            use_container_width=True,
            type="primary",
        ):
            _submit("yes")
        if b2.button(
            "No",
            key=f"bool_no_{btn_key_base}",
            use_container_width=True,
            type="primary",
        ):
            _submit("no")
        if b3.button(
            "Unknown / Not sure",
            key=f"bool_unk_{btn_key_base}",
            use_container_width=True,
        ):
            _submit("unknown")
    elif shape in ("numeric", "numeric_or_null"):
        num_col, btn_col = st.columns([3, 1])
        with num_col:
            num_val = st.number_input(
                "Numeric answer",
                value=None,
                step=1.0,
                key=f"num_{btn_key_base}",
                label_visibility="collapsed",
                placeholder="Enter a number",
            )
        with btn_col:
            if st.button(
                "Submit",
                key=f"num_submit_{btn_key_base}",
                type="primary",
                use_container_width=True,
            ):
                if num_val is None:
                    st.warning("Enter a number, or use Unknown below.")
                else:
                    val_str = (
                        str(int(num_val))
                        if float(num_val).is_integer()
                        else str(num_val)
                    )
                    _submit(val_str)
        if shape == "numeric_or_null":
            if st.button(
                "Unknown",
                key=f"num_unk_{btn_key_base}",
            ):
                _submit("unknown")

    # Free-text fallback: collapsed by default for structured shapes so
    # the buttons stay the visual focus. Always expanded for freetext.
    free_default_open = shape == "freetext"
    detail_label = (
        "Operator answer"
        if free_default_open
        else "Add detail"
    )
    with st.expander(detail_label, expanded=free_default_open):
        with st.form(key=f"answer_form_{btn_key_base}"):
            answer = st.text_area(
                "Operator answer",
                height=110 if free_default_open else 80,
                key=f"ans_{btn_key_base}",
                label_visibility="collapsed",
            )
            sub_cols = st.columns([1, 1, 4])
            with sub_cols[0]:
                submitted = st.form_submit_button(
                    "Submit Answer", type="primary"
                )
            with sub_cols[1]:
                ask_later = st.form_submit_button("Ask later")
        if submitted:
            if not answer.strip():
                st.warning(
                    "Please enter an answer, or use Ask later."
                )
            else:
                _submit(answer)
        elif ask_later:
            _submit("unknown - needs follow-up")


# --- Stage: synthesis_ready ---

elif stage == "synthesis_ready":
    st.markdown(
        "<div class='t-headline'>Ready to generate</div>"
        "<div class='t-body' style='margin: 8px 0 24px 0; "
        "max-width: 620px;'>"
        "All interview answers are captured. Generate the care plan, "
        "acuity factors, risk register, and intake decision in one "
        "batch."
        "</div>",
        unsafe_allow_html=True,
    )
    _profile = st.session_state.profile
    _op_snips = [
        s for s in _profile.evidence_snippets if s.source == "operator"
    ]
    _open_unknowns = [
        s
        for s in _op_snips
        if any(
            tok in (s.verbatim_text or "").lower()
            for tok in ("unknown", "not sure", "needs follow-up")
        )
    ]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Operator answers", len(_op_snips))
    c2.metric(
        "Triggered conditions",
        len(st.session_state.triggered_conditions),
    )
    c3.metric(
        "Source disagreements", len(_profile.source_disagreements)
    )
    c4.metric("Open unknowns", len(_open_unknowns))
    if st.session_state.triggered_conditions:
        st.caption(
            "Covered: "
            + ", ".join(
                _TREE_PRETTY.get(c, c)
                for c in st.session_state.triggered_conditions
            )
        )
    if _open_unknowns:
        with st.expander(
            f"Open unknowns ({len(_open_unknowns)})", expanded=False
        ):
            for _s in _open_unknowns:
                _human = _humanize_operator_claim(_s.claim)
                st.markdown(f"- {_human}")
    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    if st.button("Generate Artifacts", type="primary"):
        try:
            dshs_rules = _load_dshs_rules()
            with st.spinner(
                "Drafting the care plan from interview answers…"
            ):
                care = generate_care_plan(
                    st.session_state.profile,
                    st.session_state.source_docs,
                )
            with st.spinner(
                "Mapping CARE acuity factors to WAC 388-106…"
            ):
                recs = generate_acuity_factor_recommendation(
                    st.session_state.profile,
                    st.session_state.source_docs,
                    st.session_state.disclosure_text,
                    dshs_rules,
                )
            with st.spinner(
                "Cross-checking capability gaps against the disclosure…"
            ):
                reg = generate_risk_register(
                    st.session_state.profile,
                    st.session_state.disclosure_text,
                )
            with st.spinner(
                "Reaching an intake recommendation…"
            ):
                decision = generate_intake_decision(
                    care_plan=care,
                    acuity_factor_recommendations=recs,
                    risk_register=reg,
                    profile=st.session_state.profile,
                )
        except Exception as exc:
            st.error(
                "Synthesis failed. One of the model calls returned an "
                "error. Click Generate Artifacts again to retry."
            )
            st.caption(f"Details: {exc}")
            st.stop()
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
    # Reset the per-render evidence-context counter so every snippet
    # chip button gets a stable, collision-free key for this rerun.
    st.session_state["_ev_ctx_seq"] = 0

    # The workflow stepper above already conveys "Results" position;
    # this row keeps the title + the New intake escape hatch.
    title_col, btn_col = st.columns([5, 1])
    with title_col:
        st.markdown(
            "<div class='t-headline' style='margin:0 0 12px 0;'>"
            "Results</div>",
            unsafe_allow_html=True,
        )
    with btn_col:
        if st.button(
            "New intake",
            key="new_intake_button",
            use_container_width=True,
        ):
            for _k in list(st.session_state.keys()):
                del st.session_state[_k]
            st.rerun()

    artifacts = st.session_state.artifacts
    profile = st.session_state.profile
    baseline = st.session_state.baseline_output
    decision = st.session_state.intake_decision

    # Auto-generate the Action Plan markdown so the worklist + PDF are
    # ready the moment the operator opens the tab. Pure template work
    # (no LLM call) — safe to run synchronously each time it's missing.
    if (
        st.session_state.get("draft_action_plan") is None
        and decision is not None
        and artifacts is not None
        and profile is not None
    ):
        try:
            _resident_name = (
                profile.demographics.resident_name_placeholder
                or "Resident (name not documented)"
            )
            st.session_state.draft_action_plan = (
                generate_admission_action_plan(
                    resident_name=_resident_name,
                    afh_name="AFH Operator",
                    artifacts={
                        **artifacts,
                        "intake_decision": decision,
                    },
                    profile=profile,
                )
            )
        except Exception:
            st.session_state.draft_action_plan = ""

    if decision is not None:
        # Workstreams + KPIs computed once at global scope so verdict
        # subtitle, progress denominator, next-steps, and Action Plan
        # tab all read the same numbers.
        global_open_qs, global_action_tasks = _build_workstreams(
            decision,
            artifacts["care_plan"],
            artifacts["risk_register"],
            st.session_state.custom_tasks,
        )
        (
            global_high_rem,
            global_med_rem,
            global_fu_rem,
            global_completed,
            global_total_tasks,
        ) = _compute_workspace_kpis(
            global_open_qs, global_action_tasks
        )

        rec = decision.get("recommendation", "")
        rationale_full = (decision.get("rationale") or "").strip()
        if rec == "accept":
            v_label = "ACCEPT"
        elif rec == "accept_with_conditions":
            v_label = "ACCEPT WITH CONDITIONS"
        else:
            v_label = "HOLD FOR REVIEW"
        # Tasteful celebratory moment: confetti the first time the
        # operator lands on an unconditional ACCEPT verdict for this
        # session — never on subsequent reruns.
        if (
            rec == "accept"
            and not st.session_state.get("_celebrated_accept")
        ):
            st.balloons()
            st.session_state["_celebrated_accept"] = True
        # Banner state is dynamic: color reflects current blocker count
        # so the operator sees the verdict get greener as work clears.
        if global_high_rem >= 8:
            accent_color, accent_icon = "#991b1b", "⚠"
        elif global_high_rem >= 1:
            accent_color, accent_icon = "#b45309", "⚠"
        else:
            accent_color, accent_icon = "#15803d", "✓"

        # Provenance inputs — needed by the Evidence Map tab and
        # by the status block now rendered in the Action Plan tab.
        combined_for_map = {
            **artifacts,
            "intake_decision": decision,
        }
        all_snips = profile.evidence_snippets
        unref_count = sum(
            1
            for s in all_snips
            if not find_snippet_references(
                s.snippet_id, combined_for_map
            )
        )
    else:
        global_open_qs, global_action_tasks = ({}, {})
        global_high_rem = 0
        combined_for_map = {**(artifacts or {})}

    (
        tab_action,
        tab_summary,
        tab_care,
        tab_risk,
        tab_acuity,
        tab_evidence,
        tab_profile,
    ) = st.tabs(
        [
            "Action Plan",
            "Family Communication",
            "Care Plan",
            "Capability Gaps",
            "CARE Factors",
            "Evidence Map",
            "Sources & Debug",
        ]
    )

    # Family Communication — operator-first order: the call script
    # (talking points) first, provenance second, edge cases last.
    with tab_summary:
        plan = artifacts["care_plan"]
        unresolved_disagreements = plan["unresolved_disagreements"]
        open_questions = plan.get("open_questions_for_followup", [])

        # Talking points — clean numbered list, no "What to say" prefix
        # or boxed cards. Reads as a phone-call script.
        if decision is not None:
            tps = decision.get("family_call_talking_points", [])
            if tps:
                st.subheader("Talking points for the family call")
                for i, tp in enumerate(tps, 1):
                    st.markdown(f"**{i}.** {tp}")

        # Provenance is already represented in the Hero (totals) and the
        # Sources & Debug tab (full audit). Skip the bullet-list card
        # here so Family Communication stays a clean call script.

        # Unresolved disagreements — prefer the structured
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
        # Status block — verdict, concern count, readiness, who
        # to contact, and the audit/methodology — lives at the
        # top of the Action Plan tab instead of as a banner over
        # every tab.
        if decision is not None:
            # ----- Hero Status Block -----
            with st.container(border=True):
                # Verdict label — color reflects severity.
                st.markdown(
                    f"<div class='hero-verdict' "
                    f"style='color:{accent_color};'>"
                    f"{accent_icon} {v_label}</div>",
                    unsafe_allow_html=True,
                )

                # Count + label on one baseline-aligned row.
                if global_high_rem > 0:
                    st.markdown(
                        "<div style='display:flex; align-items:baseline;"
                        " gap:10px; margin:6px 0 0 0;'>"
                        f"<span class='hero-blocker-num' "
                        f"style='margin:0;'>{global_high_rem}</span>"
                        "<span class='hero-blocker-label' "
                        "style='margin:0;'>concern"
                        f"{'' if global_high_rem == 1 else 's'} "
                        "to address</span></div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        "<div style='display:flex; align-items:baseline;"
                        " gap:10px; margin:6px 0 0 0;'>"
                        "<span class='hero-blocker-num' "
                        "style='margin:0; font-size:36px; "
                        "color:#15803d;'>All clear</span>"
                        "<span class='hero-blocker-label' "
                        "style='margin:0;'>no concerns to address"
                        "</span></div>",
                        unsafe_allow_html=True,
                    )

                # Admission readiness section.
                if global_total_tasks > 0:
                    st.markdown(
                        "<div class='hero-section-label'>"
                        "Admission readiness</div>",
                        unsafe_allow_html=True,
                    )
                    st.progress(global_completed / global_total_tasks)
                    st.markdown(
                        f"<div class='hero-progress-text'>"
                        f"{global_completed} of {global_total_tasks} "
                        f"tasks complete</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    cond_total = len(
                        decision.get("conditions_before_admission") or []
                    )
                    if cond_total > 0:
                        st.markdown(
                            "<div class='hero-section-label'>"
                            "Admission readiness</div>",
                            unsafe_allow_html=True,
                        )
                        st.progress(0.0)
                        st.markdown(
                            f"<div class='hero-progress-text'>0 of "
                            f"{cond_total} conditions complete</div>",
                            unsafe_allow_html=True,
                        )

                # Why this verdict — collapsed by default.
                if rationale_full:
                    with st.expander("Why this verdict?", expanded=False):
                        _render_prose(rationale_full)


            with st.expander("Audit & Methodology", expanded=False):
                st.markdown(
                    f"<div style='font-size:14px; font-weight:600; "
                    f"color:var(--text-primary);'>Evidence base: "
                    f"{len(all_snips)} snippets · {unref_count} "
                    f"unreferenced</div>"
                    "<div style='font-size:12px; color:var(--text-muted); "
                    "margin-top:2px;'>Full provenance map and per-snippet "
                    "audit trail live in the Sources &amp; Debug tab.</div>"
                    "<div style='border-top:1px solid var(--border-default); "
                    "margin:12px 0;'></div>"
                    "<div style='font-size:14px; font-weight:600; "
                    "color:var(--text-primary);'>Methodology comparison</div>"
                    "<div style='font-size:12px; color:var(--text-muted); "
                    "margin-top:2px;'>For evaluation only: compares the "
                    "staged pipeline against a one-shot baseline.</div>",
                    unsafe_allow_html=True,
                )
                if not compare_baseline:
                    st.caption(
                        "Enable 'Compare against baseline' in the sidebar "
                        "to activate side-by-side rendering."
                    )
                if (
                    compare_baseline
                    and st.session_state.baseline_output is None
                ):
                    if st.button(
                        "Run baseline single-call for comparison",
                        key="run_baseline_button",
                    ):
                        try:
                            with st.spinner("Running baseline single-call..."):
                                dshs_rules = _load_dshs_rules()
                                st.session_state.baseline_output = run_baseline(
                                    discharge_summary=st.session_state.source_docs[
                                        "discharge_summary"
                                    ],
                                    family_notes=st.session_state.source_docs[
                                        "family_notes"
                                    ],
                                    disclosure_text=st.session_state.disclosure_text,
                                    dshs_rules=dshs_rules,
                                )
                        except Exception as exc:
                            st.error(
                                "Baseline run failed. Try again or proceed "
                                "without comparison."
                            )
                            st.caption(f"Details: {exc}")
                        else:
                            st.rerun()
                elif compare_baseline and st.session_state.baseline_output is not None:
                    st.caption(
                        "Baseline already loaded. See per-tab comparisons."
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

        # The draft markdown is auto-generated at synthesis_done; the
        # else-branch below is the only state. Keep an explicit guard
        # to fall back to a regenerate-only view if generation failed.
        if not st.session_state.draft_action_plan:
            st.warning(
                "Action Plan markdown could not be generated. "
                "Click Regenerate below to retry."
            )
            if st.button(
                "Regenerate Action Plan",
                type="primary",
                key="regen_action_plan_fallback",
            ):
                try:
                    st.session_state.draft_action_plan = (
                        _generate_action_plan()
                    )
                except Exception as exc:
                    st.error(f"Generation failed: {exc}")
                st.rerun()
        else:
            # Decision card, readiness dashboard, blocker banner and
            # evidence map are rendered globally above the tabs —
            # rendering them again inside this tab would just duplicate
            # the same content. Reuse the workstreams computed above so
            # the per-owner subgroups stay in sync with the dashboard
            # numbers shown in the global header.
            open_qs = global_open_qs
            action_tasks = global_action_tasks

            st.markdown(
                "<div class='t-headline' style='margin:0 0 2px 0;'>"
                "Action Plan</div>"
                "<div style='font-size:13px; color:var(--text-muted); "
                "margin-bottom:10px;'>Interactive move-in worklist."
                "</div>",
                unsafe_allow_html=True,
            )

            # Owner filter is integrated into the Action Tasks heading
            # below; no separate filter banner row.
            owner_filter = st.session_state.get(
                "action_plan_owner_filter"
            )
            if owner_filter:
                open_qs = {
                    k: v
                    for k, v in open_qs.items()
                    if k == owner_filter
                }
                action_tasks = {
                    k: v
                    for k, v in action_tasks.items()
                    if k == owner_filter
                }

            # Open Questions — compact empty state when none.
            has_open_qs = any(open_qs.values())
            if has_open_qs:
                st.markdown(
                    "<div style='font-size:18px; font-weight:700; "
                    "color:#111827; margin:22px 0 10px 0;'>"
                    "Open Questions to Resolve</div>",
                    unsafe_allow_html=True,
                )
                _render_open_questions_workstream(open_qs)
            else:
                st.markdown(
                    "<div class='empty-ok'>Open questions resolved"
                    "</div>",
                    unsafe_allow_html=True,
                )

            # Action Tasks heading — embeds the active filter chip when
            # set, with an inline ✕ that clears the filter.
            if owner_filter:
                hdr_cols = st.columns([5, 1])
                with hdr_cols[0]:
                    st.markdown(
                        "<div style='font-size:18px; font-weight:700; "
                        "color:#111827; margin:22px 0 10px 0;'>"
                        "Action Tasks "
                        "<span style='font-size:12px; color:#6b7280; "
                        "font-weight:500;'>· Filtered to</span> "
                        f"<span class='filter-chip'>"
                        f"{html_escape(owner_filter)}</span></div>",
                        unsafe_allow_html=True,
                    )
                with hdr_cols[1]:
                    if st.button(
                        "✕ Clear",
                        key="clear_action_owner_filter",
                        use_container_width=True,
                    ):
                        del st.session_state[
                            "action_plan_owner_filter"
                        ]
                        st.rerun()
            else:
                st.markdown(
                    "<div style='font-size:18px; font-weight:700; "
                    "color:#111827; margin:22px 0 10px 0;'>"
                    "Action Tasks</div>",
                    unsafe_allow_html=True,
                )
            _render_action_tasks_workstream(action_tasks)
            _render_add_custom_task()

            try:
                pdf_bytes = generate_admission_action_plan_pdf(
                    st.session_state.draft_action_plan
                )
                st.download_button(
                    label="Download PDF",
                    data=pdf_bytes,
                    file_name=(
                        "admission_action_plan_"
                        f"{datetime.now().strftime('%Y%m%d')}.pdf"
                    ),
                    mime="application/pdf",
                    type="primary",
                    key="ap_pdf_dl",
                )
            except Exception:
                st.error("PDF unavailable.")

            with st.expander(
                "Preview Admission Action Plan", expanded=False
            ):
                intro_md, sections = _parse_action_plan_sections(
                    st.session_state.draft_action_plan
                )
                # Expand all / Collapse all toggle for the section
                # sub-expanders below.
                _expand_doc = bool(
                    st.session_state.get("expand_all_doc_sections", False)
                )
                if st.button(
                    "Collapse all" if _expand_doc else "Expand all",
                    key="expand_all_doc_toggle",
                ):
                    st.session_state["expand_all_doc_sections"] = (
                        not _expand_doc
                    )
                    st.rerun()
                if intro_md:
                    st.markdown(
                        _decorate_severity_tokens(intro_md),
                        unsafe_allow_html=True,
                    )
                for section_title, section_body in sections:
                    with st.expander(
                        section_title, expanded=_expand_doc
                    ):
                        if section_body:
                            st.markdown(
                                _decorate_severity_tokens(section_body),
                                unsafe_allow_html=True,
                            )

            st.divider()
            st.caption(
                "Regenerating will reset task statuses, answers, "
                "dates, notes, and sign-off fields for this session."
            )
            ok_to_regen = st.checkbox(
                "I understand this will reset the current Action Plan "
                "workspace.",
                key="confirm_regen_checkbox",
            )
            if ok_to_regen and st.button(
                "Regenerate Draft Action Plan",
                type="primary",
                key="regenerate_action_plan_button",
            ):
                _wipe_workspace_state()
                try:
                    st.session_state.draft_action_plan = (
                        _generate_action_plan()
                    )
                except Exception as exc:
                    st.error(f"Generation failed: {exc}")
                # Clear the confirm checkbox by removing its key;
                # direct assignment to a widget-bound key after render
                # raises in Streamlit.
                if "confirm_regen_checkbox" in st.session_state:
                    del st.session_state["confirm_regen_checkbox"]
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
        care_plan_view = artifacts["care_plan"]
        risk_register_view = artifacts["risk_register"]

        # Patient Snapshot — replaces the long paragraph summary.
        _render_patient_snapshot(profile)

        # Metadata strip with live counts and potential blocker-linked
        # item count.
        _render_care_plan_metadata(
            profile, care_plan_view, risk_register_view
        )

        # Executive summary — surfaced as a readable block (not buried
        # in a collapsed expander) so it frames the care plan.
        plan_summary = care_plan_view.get("summary")
        if plan_summary:
            _render_prose(plan_summary, label="Clinical summary")

        st.divider()

        # Category sections with per-item expanders. Blocker linkage
        # is computed from shared evidence_snippet_ids with high-
        # severity gaps (not keyword overlap).
        high_ids = _high_gap_snippet_ids(risk_register_view)
        rendered_any = False
        for category_label, key in _CARE_PLAN_CATEGORIES:
            items = care_plan_view.get(key, []) or []
            if not items:
                continue
            rendered_any = True
            st.subheader(f"{category_label} ({len(items)})")
            for item in items:
                _render_care_plan_item(item, profile, high_ids)
        if not rendered_any:
            st.caption("No care-plan items produced for this resident.")

        st.divider()

        # Care Plan markdown export (secondary).
        export_md = _build_care_plan_export_md(profile, care_plan_view)
        st.download_button(
            "Download Care Plan Markdown",
            data=export_md,
            file_name=(
                f"care_plan_{datetime.now().strftime('%Y%m%d')}.md"
            ),
            mime="text/markdown",
        )

        if compare_baseline and baseline is not None:
            with st.expander(
                "Compare against baseline (single call)", expanded=False
            ):
                _render_care_plan(baseline["care_plan"], profile)

    with tab_acuity:
        acuity = artifacts["acuity_factor_recommendations"]
        acuity_recs_list = acuity.get("recommendations", []) or []

        if acuity_recs_list:
            for r in acuity_recs_list:
                conf = (r.get("confidence") or "low").lower()
                sev = (
                    "high"
                    if conf == "high"
                    else ("medium" if conf == "medium" else "low")
                )
                fac_name = (
                    r.get("acuity_factor_name")
                    or r.get("acuity_factor_id")
                    or "?"
                )
                st.markdown(
                    severity_badge(sev) + f" {html_escape(fac_name)}",
                    unsafe_allow_html=True,
                )

        with st.expander("Regulatory context", expanded=False):
            st.markdown(
                "<div style='font-size:14px; font-weight:600; "
                "color:var(--text-primary); margin-bottom:2px;'>"
                "What these factors mean</div>"
                "<div style='font-size:13px; color:var(--text-muted);'>"
                "CARE factors inform the Washington CARE assessment and "
                "rate-setting — they do not, on their own, determine "
                "payment.</div>",
                unsafe_allow_html=True,
            )
            if acuity.get("method_note"):
                st.markdown(
                    "<div style='border-top:1px solid "
                    "var(--border-default); margin:12px 0;'></div>"
                    "<div style='font-size:14px; font-weight:600; "
                    "color:var(--text-primary); margin-bottom:6px;'>"
                    "How these were derived</div>",
                    unsafe_allow_html=True,
                )
                _render_prose(acuity["method_note"])

        all_gap_flagged = False
        if acuity_recs_list:
            gap_count = sum(
                1 for r in acuity_recs_list
                if r.get("disclosure_gap_flagged")
            )
            all_gap_flagged = gap_count == len(acuity_recs_list)
            if all_gap_flagged:
                st.warning(
                    "AFH disclosure-of-services document does not "
                    "currently support any of the "
                    f"{len(acuity_recs_list)} recommended CARE factors."
                )

        for rec in acuity_recs_list:
            _render_acuity_factor_nested(
                rec,
                profile,
                suppress_disclosure_warning=all_gap_flagged,
            )

        if compare_baseline and baseline is not None:
            with st.expander(
                "Compare against baseline (single call)", expanded=False
            ):
                _render_acuity_recs(
                    baseline["acuity_factor_recommendations"], profile
                )

    with tab_risk:
        risk = artifacts["risk_register"]
        gaps_all = risk.get("gaps", []) or []
        sev_count = {"high": 0, "medium": 0, "low": 0}
        for _g in gaps_all:
            _s = _g.get("severity")
            if _s in sev_count:
                sev_count[_s] += 1
        total_gaps = len(gaps_all)
        st.markdown(
            f"<div class='t-caption'>{total_gaps} gap"
            f"{'' if total_gaps == 1 else 's'} · "
            f"{sev_count['high']} high · "
            f"{sev_count['medium']} medium · "
            f"{sev_count['low']} low</div>",
            unsafe_allow_html=True,
        )
        if risk.get("method_note"):
            with st.expander("About this analysis", expanded=False):
                st.markdown(risk["method_note"])
        if gaps_all:
            with_quote = sum(
                1
                for _g in gaps_all
                if (_g.get("disclosure_quote") or "").strip()
            )
            without_quote = total_gaps - with_quote
            if with_quote == 0:
                st.info(
                    "Disclosure document status: The AFH disclosure does "
                    "not provide supporting language for the gaps below. "
                    "Treat each gap as requiring operator review before "
                    "admission."
                )
            elif without_quote > 0:
                st.info(
                    "Some gaps have supporting disclosure language; gaps "
                    "without quotes require operator review."
                )
        # Preserve original enumeration so gap_NN references match the
        # synthesis-order convention used by find_snippet_references.
        indexed_gaps = list(enumerate(gaps_all))
        sev_labels = (
            ("high", "High Severity Gaps"),
            ("medium", "Medium Severity Gaps"),
            ("low", "Low Severity Gaps"),
        )
        for sev_key, sev_title in sev_labels:
            bucket = [
                (i, g)
                for i, g in indexed_gaps
                if g.get("severity") == sev_key
            ]
            if not bucket:
                continue
            st.markdown(f"#### {sev_title} ({len(bucket)})")
            for i, gap in bucket:
                _render_risk_gap_nested(gap, profile, i)
        if compare_baseline and baseline is not None:
            with st.expander(
                "Compare against baseline (single call)", expanded=False
            ):
                _render_risk_register(baseline["risk_register"], profile)

    # Evidence Map — full provenance/audit view, promoted to its own
    # top-level tab.
    with tab_evidence:
        _pinned = st.session_state.get("evidence_filter_snippet_id")
        if _pinned:
            _by_id = {
                s.snippet_id: s for s in profile.evidence_snippets
            }
            _ps = _by_id.get(_pinned)
            with st.container(border=True):
                pin_l, pin_r = st.columns([5, 1])
                with pin_l:
                    if _ps is None:
                        st.markdown(
                            f"**Pinned snippet `{_pinned}`** — not "
                            "found in the current profile."
                        )
                    else:
                        if _ps.source == "operator":
                            _txt = _humanize_operator_claim(_ps.claim)
                        else:
                            _txt = _ps.verbatim_text
                        st.markdown(
                            f"**Pinned `{_ps.snippet_id}` · "
                            f"{_SOURCE_LABELS.get(_ps.source, _ps.source)}"
                            f"**  \n{html_escape(_txt)}"
                        )
                with pin_r:
                    if st.button(
                        "Clear pin",
                        key="clear_evidence_pin",
                        use_container_width=True,
                    ):
                        del st.session_state[
                            "evidence_filter_snippet_id"
                        ]
                        st.rerun()
        _render_evidence_provenance_map(combined_for_map, profile)

    # Sources & Debug — structured profile + developer telemetry.
    with tab_profile:
        triggered_pretty = (
            ", ".join(
                _TREE_PRETTY.get(c, c)
                for c in st.session_state.triggered_conditions
            )
            or "(none)"
        )
        st.markdown(f"**Triggered conditions:** {triggered_pretty}")
        st.markdown(
            f"**Evidence snippets:** {len(profile.evidence_snippets)}"
        )
        with st.expander("Recent snippets"):
            for s in profile.evidence_snippets[-10:]:
                if s.source == "operator":
                    human = _humanize_operator_claim(s.claim)
                    st.text(f"[OP] {s.snippet_id}: {human}")
                else:
                    src_tag = "DC" if s.source == "discharge" else (
                        "FAM" if s.source == "family" else s.source[:3].upper()
                    )
                    preview = (s.verbatim_text or "")[:60]
                    st.text(f"[{src_tag}] {s.snippet_id}: {preview}")
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
