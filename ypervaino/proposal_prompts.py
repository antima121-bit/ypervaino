"""Structured prompts and JSON schemas for Phase 4 LLM calls (Call A shallow, Call B deep)."""

from __future__ import annotations

EVIDENCE_SCHEMA = """
Evidence (required on every proposal — always an array of objects, never a string):
{
  "finding_type": "aspect" | "hypothesis" | "narrative" | "counter_example" | "recommendation",
  "finding_id": "string (aspect id or hypothesis id when applicable)",
  "severity": "high" | "medium" | "low",
  "summary": "one-line human explanation",
  "session_ids": ["optional", "max 5"],
  "metrics": { "label": "string", "value": "string|number", "baseline": "optional" }
}
"""

SHALLOW_OUTPUT_SCHEMA = """
Return exactly one JSON object: { "shallow_proposals": ShallowProposal[] }
Max 5 proposals. At most one proposal per target_key. Every proposal MUST be applyable.

ShallowProposal {
  "id": "string slug e.g. prop-reduce-transfers-main-auth",
  "title": "string",
  "description": "string — user-facing rationale",
  "confidence": "high" | "medium" | "low",
  "expected_impact": "string — what metric/behavior should improve",
  "evidence": Evidence[],
  "target": BlueprintTarget,
  "target_key": "string — canonical key, see formats below",
  "patch": BlueprintPatch,
  "status": "pending"
}

BlueprintTarget {
  "domain": "skill.instructions" | "skill.description" | "tool.description" | "global_guidelines" | "welcome_message" | "dialog_flow.node_instructions" | ...,
  "skill_name": "string (must match blueprint skill_list[].name when domain is skill.*)",
  "skill_id": "string (optional)",
  "tool_name": "string (when domain is tool.*)",
  "node_id": "string (when domain is dialog_flow.*)",
  "field_path": "string e.g. instructions",
  "display_label": "string breadcrumb e.g. Main_Auth › Instructions"
}

target_key formats (required, unique per proposal):
  skill:{SkillName}:instructions
  tool:{ToolName}:description
  global:guidelines
  node:{node_id}:instructions

BlueprintPatch {
  "ops": PatchOp[]   // REQUIRED — at least 1 op; proposals with empty ops are discarded
  "preview": { "before_excerpt": "string", "after_excerpt": "string" }  // recommended
}

PatchOp — use EXACT field names; copy find/anchor strings VERBATIM from blueprint text:
  { "op": "replace_text", "find": "exact substring from blueprint", "replace": "new text", "match": "exact"|"first"|"all" }
  { "op": "insert_after", "anchor": "exact substring from blueprint", "text": "text to insert" }
  { "op": "insert_before", "anchor": "exact substring from blueprint", "text": "text to insert" }
  { "op": "delete_text", "find": "exact substring", "match": "exact"|"first"|"all" }
  { "op": "replace_field", "field_path": "instructions", "value": "full new field value" }
  { "op": "append", "field_path": "instructions", "value": "text to append" }
  { "op": "prepend", "field_path": "instructions", "value": "text to prepend" }
  { "op": "replace_node_instructions", "node_id": "uuid", "value": "new instructions" }

INVALID (will be rejected):
  - patch as an array (must be { "ops": [...] })
  - replace_text without both "find" and "replace"
  - insert_after/before without both "anchor" and "text"
  - anchor/find strings not copied from actual blueprint text
  - proposals with no patch.ops
  - evidence as a string (must be Evidence[] objects)
"""

SHALLOW_EXAMPLE = """
Example valid response (structure only — use real skill names and verbatim text from the blueprint provided):

{
  "shallow_proposals": [
    {
      "id": "prop-clarify-transfer-main-auth",
      "title": "Clarify transfer escalation in Main_Auth instructions",
      "description": "Users escalate to transfer when payment steps are unclear. Add explicit guidance before offering transfer.",
      "confidence": "high",
      "expected_impact": "Lower interruption_count and transfer_rate on billing-related calls",
      "evidence": [
        {
          "finding_type": "aspect",
          "finding_id": "transfer_rate",
          "severity": "high",
          "summary": "Transfer rate elevated in after cohort",
          "metrics": { "label": "transfer_rate", "value": 0.18, "baseline": 0.11 }
        },
        {
          "finding_type": "hypothesis",
          "finding_id": "frustration_escalation",
          "severity": "high",
          "summary": "Frustration correlates with transfer requests"
        }
      ],
      "target": {
        "domain": "skill.instructions",
        "skill_name": "Main_Auth",
        "field_path": "instructions",
        "display_label": "Main_Auth › Instructions"
      },
      "target_key": "skill:Main_Auth:instructions",
      "patch": {
        "ops": [
          {
            "op": "insert_after",
            "anchor": "If the user asks about payment status,",
            "text": " first confirm you have their account context. Only offer call transfer after two failed resolution attempts. "
          }
        ],
        "preview": {
          "before_excerpt": "...If the user asks about payment status, check eligibility...",
          "after_excerpt": "...If the user asks about payment status, first confirm you have their account context..."
        }
      },
      "status": "pending"
    }
  ]
}
"""

SHALLOW_SYSTEM = f"""You produce VA Blueprint change proposals as strict JSON for an automated patch applier.

{SHALLOW_OUTPUT_SCHEMA}

{EVIDENCE_SCHEMA}

{SHALLOW_EXAMPLE}

Rules:
1. Every shallow_proposals[] item MUST include patch.ops with at least one valid PatchOp.
2. Prefer insert_after or replace_text for small edits; use replace_field only for full rewrites.
3. find/anchor strings MUST be copied verbatim from the Current VA Blueprint JSON — do not invent placeholders.
4. skill_name / tool_name MUST match names in assistant_info.skill_list from the blueprint.
5. Do not propose backend/pipeline fixes here — those belong in deep proposals.
6. Return ONLY valid JSON matching the schema above. No markdown fences, no commentary.
"""

DEEP_OUTPUT_SCHEMA = """
Return exactly one JSON object: { "deep_proposals": DeepProposal[] }
Max 5 proposals. These are NOT applyable via VA Blueprint — backend, bot code, data model, evaluation pipeline, infra.

DeepProposal {
  "id": "string slug e.g. deep-add-transfer-primitive",
  "title": "string",
  "description": "string — user-facing explanation",
  "confidence": "high" | "medium" | "low",
  "category": "backend_logic" | "new_feature" | "data_model" | "evaluation_pipeline" | "infra" | "other",
  "evidence": Evidence[],
  "recommendation": "string — concrete action for engineering",
  "suggested_approach": "string (optional) — implementation sketch",
  "out_of_scope_reason": "string — why this cannot be a blueprint edit",
  "repo_references": RepoReference[],
  "status": "pending"
}

RepoReference {
  "repo_path": "string",
  "line_range": [number, number],
  "snippet": "string (≤20 lines)",
  "relevance": "string"
}

INVALID (will be rejected or poorly ranked):
  - Duplicating a shallow proposal fix (same root cause)
  - Missing recommendation or out_of_scope_reason
  - evidence as a string (must be Evidence[] objects)
  - category not from the enum above
"""

DEEP_EXAMPLE = """
Example valid response:

{
  "deep_proposals": [
    {
      "id": "deep-transfer-tool-signal",
      "title": "Add transfer_tool_invoked session primitive",
      "description": "Hypothesis testing transfer behavior fails because transfer_count is unreliable; need explicit tool-call signal in FeatureComputer.",
      "confidence": "high",
      "category": "evaluation_pipeline",
      "evidence": [
        {
          "finding_type": "hypothesis",
          "finding_id": "transfer_after_payment_fail",
          "severity": "high",
          "summary": "Hypothesis could not be evaluated — missing transfer signal in traces"
        }
      ],
      "recommendation": "Add a boolean feature transfer_tool_invoked derived from CALL_TRANSFER BotProbe events in FeatureComputer.",
      "suggested_approach": "Extend features.py to grep trace for CALL_TRANSFER; expose in evaluation predicates.",
      "out_of_scope_reason": "Requires pipeline code change, not VA Blueprint instruction edits.",
      "repo_references": [
        {
          "repo_path": "ypervaino/features.py",
          "relevance": "FeatureComputer defines session-level primitives used by hypotheses"
        }
      ],
      "status": "pending"
    }
  ]
}
"""

DEEP_SYSTEM = f"""You produce backend/dev change proposals as strict JSON. These fixes are OUT OF SCOPE for VA Blueprint.

{DEEP_OUTPUT_SCHEMA}

{EVIDENCE_SCHEMA}

{DEEP_EXAMPLE}

Rules:
1. Only propose changes that CANNOT be done via blueprint instruction/tool edits.
2. Do not duplicate shallow proposal titles or fixes already listed under "Shallow proposals already generated".
3. Prioritize failed/rejected hypotheses and aspects with poor metrics where blueprint edits are insufficient.
4. Ground recommendations in repo snippets and event_schema when provided.
5. Every proposal MUST include recommendation, out_of_scope_reason, and evidence[] (array of objects).
6. Return ONLY valid JSON matching the schema above. No markdown fences, no commentary.
"""
