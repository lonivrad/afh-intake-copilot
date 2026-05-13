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
