"""
Pure UI helper functions for the AFH Intake Copilot.
No session_state access, no pipeline imports — safe to import anywhere.
"""
from __future__ import annotations

import re
from html import escape as html_escape

_EVID_CODE_RE = re.compile(
    r"\b(?:gap_\d+|(?:S|F|OP)\d+(?:/(?:S|F|OP)?\d+)*)\b"
)


_PRIORITY_COLORS = {
    # Severity-pill scheme used everywhere in the app:
    # HIGH → red, MEDIUM → amber, FOLLOW-UP → gray.
    "High": "#dc2626",          # red
    "Medium": "#d97706",        # amber
    "Follow-up": "#6b7280",     # gray
}


_ORIGIN_LABELS = {
    "Condition": "Condition",
    "Risk gap": "Risk Gap",
    "Open question": "Question",
    "Custom": "Custom",
}


_SEVERITY_DOT_COLORS = {
    "CRITICAL": "#a32c3a",
    "HIGH": "#a32c3a",
    "MEDIUM": "#a86610",
    "MED": "#a86610",
    "LOW": "#6c6c66",
    "FOLLOW-UP": "#6c6c66",
    "FOLLOWUP": "#6c6c66",
}


def _first_two_sentences(text: str) -> str:
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:2]).strip()

def _clip_label(text: str, limit: int = 220) -> str:
    """Trim only genuinely over-long labels, and only at a word
    boundary — never a mid-sentence ellipsis. Streamlit expander
    labels wrap, so the full phrase is preferred."""
    t = " ".join((text or "").split())
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{cut}…"

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

def evidence_chip(text: str) -> str:
    """Return inline HTML for a small pill-style evidence ID chip."""
    return (
        f'<span style="background:#eef2ff; color:#3730a3; padding:4px 10px; '
        f'border-radius:999px; font-size:12px; font-weight:600; '
        f'margin-right:6px; display:inline-block;">{html_escape(text)}</span>'
    )

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

def _origin_chip(source: str) -> str:
    label = _ORIGIN_LABELS.get(source, source)
    return (
        '<span style="background:#eef2ff; color:#3730a3; '
        'padding:3px 9px; border-radius:6px; font-size:12px; '
        f'font-weight:600;">{html_escape(label)}</span>'
    )

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
            f"width:13px;height:13px;border-radius:50%;background:"
            f"{color};vertical-align:middle;margin-right:9px;'></span>"
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

def _preview_text(text: str, n: int = 90) -> str:
    """Collapse whitespace and truncate at a word boundary (never
    mid-word) with a single ellipsis. Used for Evidence Map row
    labels."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= n:
        return cleaned
    return cleaned[:n].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
