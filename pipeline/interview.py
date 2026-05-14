"""Stage 2: Stateful Interview.

InterviewSession walks the diabetes / dementia / fall_risk question trees in
the canonical order (diabetes -> dementia -> fall_risk) for whichever
conditions Stage 1 flagged. Each operator answer is parsed by Claude into the
structured shape required by the current node, the shared ResidentProfile is
mutated at the exact updates_profile_field path, an operator evidence_snippet
is recorded, and the next node is chosen strictly from the tree's
next_node_logic.

The per-node LLM call is tightly scoped: it sees only the current question,
the expected answer shape, the allowed values (for enum), and the operator's
answer. It does not see the source documents and does not decide flow.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

from pipeline.extraction import (
    DementiaProfile,
    DiabetesProfile,
    EvidenceSnippet,
    FallRiskProfile,
    ResidentProfile,
)

load_dotenv()

MODEL_ID = "claude-sonnet-4-6"

CANONICAL_TREE_ORDER = ("diabetes", "dementia", "fall_risk")


# ===== Local answer parsing =====
#
# To cut Claude calls during Stage 2, we try a deterministic local parse
# first for the simple answer shapes (boolean, numeric, numeric_or_null,
# enum). Claude remains the fallback for anything ambiguous or for
# freetext. Local parsers must be conservative — returning the sentinel
# below signals "I'm not confident; ask Claude."


_SENTINEL_FALLBACK = object()


_WORD_NUMBERS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12,
}


_NULL_INDICATORS: tuple[str, ...] = (
    "unknown", "not sure", "don't know", "do not know",
    "no idea", "not available", "n/a", "not provided",
    "not given", "not reported", "not stated",
    "not in the chart", "didn't say", "did not say",
    "no value", "blank", "not recorded",
)


# Curated synonym map for the enum values our trees use. Keys are
# lowercased phrases; values are the canonical option string. Longer
# keys are preferred when multiple match.
_ENUM_SYNONYMS: dict[str, str] = {
    # Diabetes type
    "type 2": "type_2", "type ii": "type_2", "type two": "type_2",
    "type-2": "type_2",
    "type 1": "type_1", "type i": "type_1", "type one": "type_1",
    "type-1": "type_1",
    # Insulin regimen
    "basal bolus": "basal_bolus", "basal-bolus": "basal_bolus",
    "long acting plus mealtime": "basal_bolus",
    "sliding scale": "sliding_scale", "sliding-scale": "sliding_scale",
    "fixed dose": "fixed_dose", "fixed-dose": "fixed_dose",
    # Orientation
    "person and place but not time": "oriented_x2_person_place",
    "person and place": "oriented_x2_person_place",
    "person only": "oriented_x1_person",
    "fully disoriented": "fully_disoriented",
    "oriented x3": "oriented_x3",
    # Resistance to care
    "no resistance": "no_resistance",
    "verbal only": "verbal_only",
    "physical occasional": "physical_occasional",
    "physical frequent": "physical_frequent",
    "pulls away": "physical_occasional",
    "combative during care": "combative_during_care",
    "combative": "combative_during_care",
    # Diet restrictions
    "carb controlled": "carbohydrate_controlled",
    "carb-controlled": "carbohydrate_controlled",
    "carbohydrate controlled": "carbohydrate_controlled",
    "carbohydrate-controlled": "carbohydrate_controlled",
    "diabetic diet": "carbohydrate_controlled",
    # BGM frequency
    "four times a day": "four_or_more_daily",
    "4 times a day": "four_or_more_daily",
    "four times daily": "four_or_more_daily",
    "4x daily": "four_or_more_daily",
    "before meals and bedtime": "four_or_more_daily",
}


def _enum_normalize(s: str) -> str:
    """Strip apostrophes and common punctuation; lowercase.

    So "Alzheimer's." normalizes to "alzheimers", matching the option name.
    """
    return re.sub(r"['\".,;:!?]", "", s).lower()


_BOOLEAN_AFFIRMATIVE_TOKENS = {
    "yes", "yeah", "yep", "yup", "correct", "true",
    "affirmative", "absolutely", "definitely", "certainly",
    "indeed", "right",
    # Weaker but useful when they LEAD the answer:
    "currently", "does", "takes", "has", "had", "is", "was",
}

_BOOLEAN_NEGATIVE_TOKENS = {
    "no", "nope", "never", "false", "negative", "none", "not",
}

_BOOLEAN_NEGATION_SUBSTRINGS: tuple[str, ...] = (
    "doesn't", "does not", "do not", "didn't", "did not",
    "hasn't", "has not", "haven't", "have not",
    "isn't", "is not", "aren't", "are not",
    "wasn't", "was not", "weren't", "were not",
    "won't", "will not",
    "no history", "no episodes", "no concerns", "no resistance",
    "no falls", "no exit", "no wandering", "no diabetes",
    "no dementia", "no incidents", "no events",
    "not applicable", "not present", "not really",
    "not particularly", "not so much", "not very",
    "denies", "denied",
)


def _first_token(text: str) -> str:
    parts = re.split(r"[\s,.!?;:—\-]", text, maxsplit=1)
    return parts[0] if parts else ""


def _local_parse_boolean(text_lower: str) -> Any:
    if not text_lower:
        return _SENTINEL_FALLBACK
    if any(pat in text_lower for pat in _BOOLEAN_NEGATION_SUBSTRINGS):
        return False
    first = _first_token(text_lower)
    if first in _BOOLEAN_AFFIRMATIVE_TOKENS:
        return True
    if first in _BOOLEAN_NEGATIVE_TOKENS:
        return False
    return _SENTINEL_FALLBACK


def _local_parse_numeric(text_lower: str) -> Any:
    # 1. "X point Y" (decimal phrase)
    m = re.search(r"\b(\w+)\s+point\s+(\w+)\b", text_lower)
    if m:
        i_word, d_word = m.group(1), m.group(2)
        try:
            i_val: Any = _WORD_NUMBERS.get(i_word, None)
            if i_val is None and i_word.isdigit():
                i_val = int(i_word)
            d_val: Any = _WORD_NUMBERS.get(d_word, None)
            if d_val is None and d_word.isdigit():
                d_val = int(d_word)
            if i_val is not None and d_val is not None:
                return float(f"{i_val}.{d_val}")
        except (ValueError, TypeError):
            pass

    # 2. Direct decimal/integer
    m = re.search(r"\b(\d+(?:\.\d+)?)\b", text_lower)
    if m:
        try:
            v = float(m.group(1))
            return int(v) if v.is_integer() else v
        except ValueError:
            pass

    # 3. Word number anywhere
    for w in re.findall(r"\b[a-z]+\b", text_lower):
        if w in _WORD_NUMBERS:
            return _WORD_NUMBERS[w]

    return _SENTINEL_FALLBACK


def _local_parse_numeric_or_null(text_lower: str) -> Any:
    if not text_lower:
        return None
    if any(ind in text_lower for ind in _NULL_INDICATORS):
        return None
    return _local_parse_numeric(text_lower)


def _local_parse_enum(text_lower: str, options: list[str]) -> Any:
    # Apostrophe- and punctuation-tolerant comparison: normalize both the
    # operator text and the option/option-phrase forms before matching.
    text_norm = _enum_normalize(text_lower)
    options_lc = {opt.lower(): opt for opt in options}

    # 1. Exact case-insensitive match (apostrophe-tolerant)
    stripped = text_norm.strip()
    if stripped in options_lc:
        return options_lc[stripped]

    # 2. Curated synonym map (longest synonym wins; but ambiguous => fallback)
    syn_matches = [
        (syn, canon)
        for syn, canon in _ENUM_SYNONYMS.items()
        if syn in text_norm and canon in options
    ]
    if syn_matches:
        unique_canon = {c for _, c in syn_matches}
        if len(unique_canon) == 1:
            return next(iter(unique_canon))
        # Multiple distinct mappings — ambiguous, fall back to Claude.
        return _SENTINEL_FALLBACK

    # 3. Normalized option-name phrase match: replace underscores with
    # spaces, strip apostrophes/punctuation, and look for that phrase.
    # Single unique match wins.
    phrase_matches: list[tuple[str, str]] = []
    for opt in options:
        opt_phrase = _enum_normalize(opt.replace("_", " "))
        if len(opt_phrase) >= 4 and opt_phrase in text_norm:
            phrase_matches.append((opt_phrase, opt))
    if phrase_matches:
        unique = {c for _, c in phrase_matches}
        if len(unique) == 1:
            return next(iter(unique))
        return _SENTINEL_FALLBACK

    return _SENTINEL_FALLBACK


def _local_parse(node: dict, answer: str) -> Any:
    """Try a deterministic local parse.

    Returns the parsed value on success, or _SENTINEL_FALLBACK to indicate
    Claude should be used. Freetext and unknown shapes always return the
    sentinel.
    """
    shape = node["expected_answer_shape"]
    text_lower = answer.strip().lower()

    if shape == "boolean":
        return _local_parse_boolean(text_lower)
    if shape == "numeric":
        return _local_parse_numeric(text_lower)
    if shape == "numeric_or_null":
        return _local_parse_numeric_or_null(text_lower)
    if shape == "enum":
        return _local_parse_enum(text_lower, list(node.get("answer_options", [])))

    return _SENTINEL_FALLBACK


class InterviewSession:
    """Stateful walk over one or more clinical questioning trees."""

    def __init__(
        self,
        profile: ResidentProfile,
        triggered_conditions: list[str],
        trees_dir: Path | str | None = None,
    ) -> None:
        self.profile = profile
        if trees_dir is None:
            trees_dir = Path(__file__).resolve().parent.parent / "data" / "trees"
        self.trees_dir = Path(trees_dir)

        self.trees: list[dict] = []
        self.tree_nodes: list[dict[str, dict]] = []
        for cond in CANONICAL_TREE_ORDER:
            if cond in triggered_conditions:
                tree = json.loads((self.trees_dir / f"{cond}.json").read_text())
                self.trees.append(tree)
                self.tree_nodes.append({n["node_id"]: n for n in tree["nodes"]})
                self._ensure_subprofile(cond)

        self.current_tree_idx = 0
        self.current_node_id: str | None = (
            self.trees[0]["entry_node_id"] if self.trees else None
        )
        self._operator_snippet_counter = 0
        self._last_parsed_value: Any = None
        self._last_parse_method: str | None = None  # "local" | "fallback"
        self._local_parse_count = 0
        self._fallback_parse_count = 0
        self._client = anthropic.Anthropic()

    def _ensure_subprofile(self, cond: str) -> None:
        if cond == "diabetes" and self.profile.diabetes is None:
            self.profile.diabetes = DiabetesProfile()
        elif cond == "dementia" and self.profile.dementia is None:
            self.profile.dementia = DementiaProfile()
        elif cond == "fall_risk" and self.profile.fall_risk is None:
            self.profile.fall_risk = FallRiskProfile()

    def get_next_question(self) -> dict | None:
        if self.current_node_id is None:
            return None
        return self.tree_nodes[self.current_tree_idx][self.current_node_id]

    def submit_answer(self, answer: str) -> None:
        node = self.get_next_question()
        if node is None:
            raise RuntimeError("interview is complete; no current question")

        parsed_value = self._parse_answer(node, answer)
        self._last_parsed_value = parsed_value
        self._set_field_path(node["updates_profile_field"], parsed_value)
        snippet_id = self._record_operator_snippet(node, answer, parsed_value)
        self._maybe_clarify_disagreement(node["updates_profile_field"], snippet_id)
        self._advance(node, parsed_value)

    # -------- internal helpers --------

    def _parse_answer(self, node: dict, answer: str) -> Any:
        # Try a deterministic local parse first; fall back to Claude only
        # when the local parser is not confident.
        local_value = _local_parse(node, answer)
        if local_value is not _SENTINEL_FALLBACK:
            self._local_parse_count += 1
            self._last_parse_method = "local"
            return local_value

        self._fallback_parse_count += 1
        self._last_parse_method = "fallback"
        return self._claude_parse_answer(node, answer)

    def _claude_parse_answer(self, node: dict, answer: str) -> Any:
        shape = node["expected_answer_shape"]

        if shape == "enum":
            value_schema: dict[str, Any] = {
                "type": "string",
                "enum": list(node["answer_options"]),
            }
        elif shape == "freetext":
            value_schema = {"type": "string"}
        elif shape == "numeric":
            value_schema = {"type": "number"}
        elif shape == "numeric_or_null":
            value_schema = {"anyOf": [{"type": "number"}, {"type": "null"}]}
        elif shape == "boolean":
            value_schema = {"type": "boolean"}
        else:
            raise ValueError(f"unknown expected_answer_shape: {shape!r}")

        tool_schema = {
            "type": "object",
            "properties": {"parsed_value": value_schema},
            "required": ["parsed_value"],
            "additionalProperties": False,
        }

        system_lines = [
            "You parse a single operator answer for an Adult Family Home intake interview.",
            "Tightly bounded scope — only the current question matters.",
            "",
            f"Current question: {node['question_text']}",
            f"Expected answer shape: {shape}",
        ]
        if shape == "enum":
            system_lines.append(f"Allowed values: {node['answer_options']}")
        system_lines.extend(
            [
                "",
                "RULES:",
                "- Map the operator's answer to the shape. For enum, pick the single best-matching allowed value.",
                "- For numeric_or_null, return null if the operator indicates unknown / don't know / N/A / blank.",
                "- For boolean, yes/yeah/has/did/correct -> true; no/none/never/hasn't/incorrect -> false.",
                "- Do NOT infer details the operator did not state.",
                "- Do NOT add commentary or unrelated clinical conclusions.",
                "- Do NOT decide the next question — the tree controls flow.",
                "- Call the record_parsed_answer tool with parsed_value.",
            ]
        )

        response = self._client.messages.create(
            model=MODEL_ID,
            max_tokens=256,
            system="\n".join(system_lines),
            tools=[
                {
                    "name": "record_parsed_answer",
                    "description": "Record the parsed structured value for the current interview question.",
                    "input_schema": tool_schema,
                }
            ],
            tool_choice={"type": "tool", "name": "record_parsed_answer"},
            messages=[{"role": "user", "content": f"Operator's answer: {answer}"}],
        )

        tool_block = next(b for b in response.content if b.type == "tool_use")
        return tool_block.input["parsed_value"]

    def _set_field_path(self, dotted_path: str, value: Any) -> None:
        parts = dotted_path.split(".")
        obj: Any = self.profile
        for p in parts[:-1]:
            obj = getattr(obj, p)
        setattr(obj, parts[-1], value)

    def _record_operator_snippet(
        self, node: dict, answer: str, parsed_value: Any
    ) -> str:
        self._operator_snippet_counter += 1
        snippet_id = f"OP{self._operator_snippet_counter}"
        self.profile.evidence_snippets.append(
            EvidenceSnippet(
                snippet_id=snippet_id,
                claim=f"operator answer at {node['node_id']} -> {parsed_value!r}",
                source="operator",
                verbatim_text=answer,
            )
        )
        return snippet_id

    def _maybe_clarify_disagreement(self, field: str, snippet_id: str) -> None:
        # Preserve all existing disagreements. If the operator just answered
        # a node whose field exactly matches a disagreement, append the
        # operator's snippet ID so downstream synthesis can see the
        # clarification trail.
        for d in self.profile.source_disagreements:
            if d.field == field:
                d.evidence_snippet_ids.append(snippet_id)

    def _advance(self, node: dict, parsed_value: Any) -> None:
        nnl = node["next_node_logic"]
        next_id = nnl["default"]
        for cond in nnl["conditional"]:
            if cond["if_answer"] == parsed_value:
                next_id = cond["goto"]
                break

        if next_id == "END":
            self.current_tree_idx += 1
            if self.current_tree_idx >= len(self.trees):
                self.current_node_id = None
            else:
                self.current_node_id = self.trees[self.current_tree_idx]["entry_node_id"]
        else:
            self.current_node_id = next_id
