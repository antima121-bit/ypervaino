# Ypervaíno — Proposal Tab Contract (v1)

**Audience:** Frontend implementation  
**Related:** [input_schema.md](./input_schema.md), [output_schema.md](./output_schema.md), [api.md](./api.md), [UI_design.md](./UI_design.md)

This document defines the **data shapes, storage layout, HTTP API, and UI states** for the **Proposals** tab (Tab 4). It does not describe server-side generation logic.

---

## 0. Tab placement in the product flow

| Step | Tab | Study `status` gate |
|------|-----|---------------------|
| 1 | New Study | — |
| 2 | Explore | `explored` |
| 3 | Results | `complete` |
| 4 | **Proposals** | `complete` |

**User journey on Proposals tab:**

1. User lands on Proposals after Results (`?study={slug}`).
2. If proposals have not been generated yet, user clicks **Generate proposals** (or equivalent CTA).
3. UI polls until generation finishes.
4. UI shows **shallow** proposals (editable / applyable) and **deep** proposals (read-only advisory).
5. User may **Apply** each shallow proposal individually; each successful apply creates a **new blueprint version**.
6. User may **Reject** or **Acknowledge** proposals; deep proposals expose a **Create Jira ticket** stub button (no integration in v1).

---

## 1. Prerequisites

The Proposals tab is available only when:

| Condition | File / field |
|-----------|----------------|
| Phase 3 finished | `meta.json` → `status == "complete"` |
| Evaluation exists | `output/evaluation_result.json` |
| Baseline blueprint exists | `intermediate/blueprint/versions/v0001.json` |

Optional upstream inputs (used during generation; may be absent):

| Artifact | Path |
|----------|------|
| Analysis plan | `intermediate/analysis_plan.json` |
| Change context | `intermediate/change_context.json` |
| Blueprint summary | `intermediate/blueprint_summary.json` |
| Phase 3 narrative recommendations | `output/evaluation_result.json` → `artifacts.recommendations[]` |
| Dialog flow graph | `intermediate/blueprint/dialog_flow.json` (when fetched separately from VA Blueprint API) |
| Full VA Blueprint (current version) | `intermediate/blueprint/versions/{current}.json` |

### 1.1 Phase 4 generation inputs

Phase 4 runs two LLM calls on demand ([proposal_implementation.md](./proposal_implementation.md)). Both calls receive **full** Phase 3 evaluation outputs for aspects and hypotheses — not a ranked subset.

| Input | Shallow call (Call A) | Deep call (Call B) |
|-------|----------------------|-------------------|
| **Aspect results** | `evaluation_result` → `quantitative.aspects[]` (full) | same (full) |
| **Hypothesis results** | `evaluation_result` → `qualitative.hypotheses[]` (full, incl. counter_examples) | same (full) |
| **Recommendations** | `artifacts.recommendations[]` | same |
| **VA Blueprint** | **Full** current-version JSON (`blueprint/versions/{current}.json`) — not trimmed | not passed |
| **Dialog flow** | full `dialog_flow.json` if present | not passed |
| **Analysis plan** | aspects + hypotheses (predicates, components) | not passed |
| **Change context** | not passed | full if present |
| **Event schema** | not passed | `config/event_schema.json` |
| **Repo snippets** | not passed | deterministic grep/read from bot repo |
| **Shallow proposal titles** | not passed | titles only (dedup guard) |

Evidence on generated proposals should reference `finding_type: "aspect"` or `"hypothesis"` with the corresponding `finding_id`.

---

## 2. Study directory layout (new paths)

All paths are relative to `studies/{slug}/`.

```
studies/{slug}/
  intermediate/
    blueprint/
      manifest.json                 # version index + current pointer
      dialog_flow.json              # optional; graph snapshot if separate endpoint
      versions/
        v0001.json                  # baseline from VA Blueprint API (Phase 0)
        v0002.json                  # after first apply
        v0003.json                  # after second apply / manual edit
    proposal_generation/
      status.json                   # generation job state (poll target)
  output/
    proposal_bundle.json            # generated proposals (read-only bundle)
```

**Versioning rules (contract):**

- `v0001` is always the **baseline** fetched at study creation (Phase 0).
- Every successful **Apply** (shallow proposal or manual blueprint edit) appends the next sequential version (`v0002`, `v0003`, …).
- `manifest.json` → `current_version` points at the latest version the UI should display by default.
- Version files are **immutable** once written; edits always produce a new version file.

---

## 3. HTTP API

Base prefix: `/api/v1/ypervaino` (see [api.md](./api.md) §1).

### 3.1 Static page

| Path | Tab |
|------|-----|
| `GET /proposals?study={slug}` | Proposals |

Top nav adds **Proposals** alongside New Study, Explore, Results.

---

### 3.2 Get proposal generation status + bundle

```
GET /api/v1/ypervaino/studies/{slug}/proposals
```

**Requires:** `status == "complete"`.

**Response 200:**

```json
{
  "meta": {
    "title": "qwen swap",
    "slug": "qwen-swap-6",
    "status": "complete"
  },
  "generation": {
    "status": "not_started",
    "started_at": null,
    "finished_at": null,
    "error": null,
    "logs_url": "/api/v1/ypervaino/studies/qwen-swap-6/logs?tail=100"
  },
  "bundle": null,
  "blueprint": {
    "current_version": "v0001",
    "manifest_url": "/api/v1/ypervaino/studies/qwen-swap-6/blueprint/manifest"
  }
}
```

When generation has completed, `bundle` is populated (see §4.1) and `generation.status == "ready"`.

| `generation.status` | UI behavior |
|---------------------|-------------|
| `not_started` | Show empty state + **Generate proposals** CTA |
| `generating` | Show spinner; poll every 2–3 s |
| `ready` | Render proposal lists from `bundle` |
| `failed` | Show error + retry CTA |

**Response 404:** unknown slug.  
**Response 409 (`INVALID_STATE`):** study not `complete`.

---

### 3.3 Start proposal generation (on demand)

```
POST /api/v1/ypervaino/studies/{slug}/proposals/generate
```

**Request body:** empty `{}`.

**Requires:** `status == "complete"`.  
**Idempotency:** If `generation.status == "generating"`, return `202` with current job (do not start a second job). If `generation.status == "ready"`, return `200` with existing bundle unless `?force=true` query param is set (optional v1 extension).

**Response 202:**

```json
{
  "slug": "qwen-swap-6",
  "generation": {
    "status": "generating",
    "started_at": "2026-09-01T17:30:00+05:30",
    "poll_url": "/api/v1/ypervaino/studies/qwen-swap-6/proposals"
  }
}
```

UI polls §3.2 until `generation.status` is `ready` or `failed`.

---

### 3.4 Blueprint version manifest

```
GET /api/v1/ypervaino/studies/{slug}/blueprint/manifest
```

**Response 200:** [BlueprintVersionManifest](#41-blueprintversionmanifest) (§5.1).

---

### 3.5 Get blueprint JSON by version

```
GET /api/v1/ypervaino/studies/{slug}/blueprint/versions/{version}
```

| Param | Example | Notes |
|-------|---------|-------|
| `version` | `v0001`, `v0003`, or `current` | `current` resolves via manifest |

**Response 200:**

```json
{
  "version": "v0003",
  "created_at": "2026-09-01T17:45:00+05:30",
  "source": "proposal_apply",
  "source_proposal_id": "prop-transfer-tool-main-auth",
  "parent_version": "v0002",
  "blueprint": { }
}
```

- `blueprint` — full VA Blueprint payload (same top-level shape as VA Blueprint API `extract_blueprint` response body, typically `{ "assistant_info": { ... }, ... }`).
- UI renders instructions, skills, tools, guardrails, knowledge sources, and dialog flow from this object.

**Response 404:** unknown version.

---

### 3.6 Apply one shallow proposal

```
POST /api/v1/ypervaino/studies/{slug}/proposals/{proposal_id}/apply
```

**Request body:** empty `{}`.

**Requires:**

- `generation.status == "ready"`
- Target proposal exists in `bundle.shallow_proposals[]`
- Proposal `status == "pending"`
- Proposal `target_key` is not already applied (see §5.3 uniqueness)

**Response 200:**

```json
{
  "proposal_id": "prop-transfer-tool-main-auth",
  "proposal_status": "applied",
  "applied_at": "2026-09-01T17:45:00+05:30",
  "blueprint": {
    "previous_version": "v0002",
    "new_version": "v0003",
    "manifest": { }
  },
  "apply_result": {
    "success": true,
    "ops_applied": 2,
    "warnings": []
  }
}
```

**Response 409 (`PROPOSAL_CONFLICT`):** another proposal with the same `target_key` is already `applied`.  
**Response 409 (`APPLY_FAILED`):** patch could not be applied (e.g. anchor not found); `apply_result.errors[]` populated.

```json
{
  "apply_result": {
    "success": false,
    "errors": [
      {
        "op_index": 0,
        "code": "ANCHOR_NOT_FOUND",
        "message": "Anchor string not found in Main_Auth instructions"
      }
    ]
  }
}
```

After success, UI refreshes blueprint viewer to `new_version` and updates proposal card status.

---

### 3.7 Reject shallow proposal

```
POST /api/v1/ypervaino/studies/{slug}/proposals/{proposal_id}/reject
```

**Request body (optional):**

```json
{
  "reason": "User dismissed — already fixed in prod"
}
```

**Response 200:** `{ "proposal_id": "...", "proposal_status": "rejected" }`

---

### 3.8 Manual blueprint edit (optional UI path)

If the UI allows direct edits outside a proposal card:

```
POST /api/v1/ypervaino/studies/{slug}/blueprint/patch
```

**Request body:**

```json
{
  "target": { },
  "patch": { },
  "note": "PM tweaked escalation wording"
}
```

Uses the same [BlueprintTarget](#53-blueprinttarget) and [BlueprintPatch](#54-blueprintpatch) shapes as shallow proposals.

**Response 200:** same shape as §3.6 apply success (`new_version`, `apply_result`), with `source: "manual_edit"`.

---

### 3.9 Deep proposal actions

**Acknowledge:**

```
POST /api/v1/ypervaino/studies/{slug}/proposals/{proposal_id}/acknowledge
```

**Response 200:** `{ "proposal_id": "...", "proposal_status": "acknowledged" }`

**Reject:** same as §3.7 (shared endpoint; works for deep proposals too).

**Create Jira ticket (stub v1):**

```
POST /api/v1/ypervaino/studies/{slug}/proposals/{proposal_id}/jira-stub
```

**Response 200 (stub — no real Jira call in v1):**

```json
{
  "proposal_id": "prop-backend-transfer-signal",
  "stub": true,
  "ticket_draft": {
    "summary": "Add rule-based transfer_tool_invoked primitive",
    "description": "…formatted markdown from proposal…",
    "labels": ["ypervaino", "voice-bot"],
    "study_slug": "qwen-swap-6",
    "evidence_session_ids": ["57e2f8b3-6a9f-4cca-ad1e-fcfc22e7f115"]
  },
  "message": "Jira integration not configured; copy draft to create ticket manually."
}
```

UI: show modal with copyable title + description; button label **Create Jira ticket** (disabled or informational until integration exists).

---

### 3.10 Blueprint diff (optional helper for UI)

```
GET /api/v1/ypervaino/studies/{slug}/blueprint/diff?from=v0001&to=v0003&target_key=skill:Main_Auth:instructions
```

**Response 200:**

```json
{
  "from_version": "v0001",
  "to_version": "v0003",
  "target_key": "skill:Main_Auth:instructions",
  "before_excerpt": "…",
  "after_excerpt": "…",
  "unified_diff": "…"
}
```

If not implemented in v1, UI may use `patch.preview` on the proposal card instead.

---

## 4. Core data types

### 4.1 ProposalBundle

**File:** `output/proposal_bundle.json`  
**Produced by:** Phase 4 (on demand)  
**Consumed by:** Proposals tab

```typescript
ProposalBundle {
  schema_version:     "1.0"
  study_slug:         string
  generated_at:       string              // ISO 8601

  summary:            string              // 2–4 sentence overview for banner

  inputs: {
    evaluation_result_path:   string      // "output/evaluation_result.json"
    analysis_plan_path:       string
    blueprint_baseline_version: string    // always "v0001"
    blueprint_current_version:  string    // at generation time; full JSON at blueprint/versions/{current}
    change_context_path?:     string
    dialog_flow_path?:        string
    recommendations?:         string[]     // snapshot from evaluation_result.artifacts.recommendations
    aspect_count?:            number       // len(aspects[]) at generation time
    hypothesis_count?:        number       // len(hypotheses[]) at generation time
  }

  shallow_proposals:  ShallowProposal[]
  deep_proposals:     DeepProposal[]

  stats: {
    shallow_count:      number
    deep_count:         number
    findings_addressed: string[]           // hypothesis_id / aspect_id list
  }
}
```

---

### 4.2 Evidence

Shared by shallow and deep proposals. Links a proposal to evaluation findings.

```typescript
Evidence {
  finding_type:   "hypothesis" | "aspect" | "narrative" | "counter_example" | "recommendation"
  finding_id?:    string                    // e.g. "frustration_escalation", "transfer_rate"
  severity:       "high" | "medium" | "low"
  summary:        string                    // one-line human text
  session_ids?:   string[]                  // up to 5; link out to BotProbe / session detail
  metrics?: {
    label:        string
    value:        string | number
    baseline?:    string | number
  }
}
```

UI: render evidence as a collapsible block with session links and metric chips.

---

### 4.3 ShallowProposal

VA Blueprint–level, **applyable one at a time**.

```typescript
ShallowProposal {
  id:               string                  // stable UUID or slug
  title:            string
  description:      string                  // user-facing rationale
  confidence:       "high" | "medium" | "low"
  expected_impact:  string

  evidence:         Evidence[]

  target:           BlueprintTarget
  target_key:       string                  // canonical uniqueness key (§5.3)
  patch:            BlueprintPatch

  status:           "pending" | "applied" | "rejected" | "superseded"
  applied_at?:      string                  // ISO 8601; set after successful apply
  applied_version?: string                 // blueprint version created by this apply, e.g. "v0003"
  rejected_at?:     string
  reject_reason?:   string
}
```

**UI actions per card (by status):**

| `status` | Actions |
|----------|---------|
| `pending` | **Preview**, **Apply**, **Reject** |
| `applied` | View diff (baseline → `applied_version`); badge **Applied** |
| `rejected` | badge **Rejected** |
| `superseded` | badge **Superseded** (another proposal replaced same target) |

---

### 4.4 DeepProposal

Out-of-scope (backend / infra / pipeline). **Not applyable.**

```typescript
DeepProposal {
  id:               string
  title:            string
  description:      string
  confidence:       "high" | "medium" | "low"
  category:
    | "backend_logic"
    | "new_feature"
    | "data_model"
    | "evaluation_pipeline"
    | "infra"
    | "other"

  evidence:         Evidence[]

  recommendation:       string
  suggested_approach?:    string
  out_of_scope_reason:    string            // why not a blueprint edit

  repo_references?:   RepoReference[]

  status:           "pending" | "acknowledged" | "rejected"
  acknowledged_at?: string
  rejected_at?:     string
  reject_reason?:   string
}

RepoReference {
  repo_path:    string                        // e.g. "bot/skills/transfer_handler.py"
  line_range?:  [number, number]
  snippet?:     string                        // ≤ 20 lines
  relevance:    string
}
```

**UI actions:**

| Action | Endpoint |
|--------|----------|
| **Create Jira ticket** (stub) | §3.9 |
| **Acknowledge** | §3.9 |
| **Reject** | §3.7 |

Visual treatment: distinct from shallow cards (e.g. “Out of scope · Backend” badge); no Apply button.

---

### 4.5 BlueprintTarget

Tells the UI **where** to scroll / highlight in the blueprint editor.

```typescript
BlueprintTarget {
  domain:
    | "skill.instructions"
    | "skill.description"
    | "skill.tools"
    | "tool.schema"
    | "tool.description"
    | "guardrail"
    | "guardrail.policy"
    | "dialog_flow.node"
    | "dialog_flow.edge"
    | "dialog_flow.node_instructions"
    | "knowledge_source"
    | "global_guidelines"
    | "transfer_rules"
    | "welcome_message"
    | "orchestration_config"

  // Stable locators from VA Blueprint / dialog flow API
  skill_id?:          string
  skill_name?:        string                 // e.g. "Main_Auth"
  tool_id?:           string
  tool_name?:         string                 // e.g. "call_transfer"
  node_id?:           string                 // dialog flow node UUID
  node_label?:        string
  edge_id?:           string
  knowledge_source_id?: string

  field_path?:        string                 // e.g. "instructions", "tools[0].description"
  display_label:      string                 // breadcrumb, e.g. "Main_Auth › Instructions"
}
```

---

### 4.6 BlueprintPatch

Machine-readable edit payload. The LLM may emit **partial text edits** or **full field replacement** depending on change size.

```typescript
BlueprintPatch {
  ops:      PatchOp[]
  preview?: {
    before_excerpt:  string                  // for diff panel on proposal card
    after_excerpt:   string
  }
}

PatchOp =
  // Partial text edits (instructions, long markdown fields)
  | { op: "replace_text";  find: string; replace: string; match?: "exact" | "first" | "all" }
  | { op: "insert_after";  anchor: string; text: string }
  | { op: "insert_before"; anchor: string; text: string }
  | { op: "delete_text";   find: string; match?: "exact" | "first" | "all" }

  // Full field replacement (large rewrites)
  | { op: "replace_field"; field_path: string; value: unknown }
  | { op: "append";        field_path: string; value: unknown }
  | { op: "prepend";       field_path: string; value: unknown }

  // Dialog flow graph
  | { op: "set_node_property";  node_id: string; property: string; value: unknown }
  | { op: "replace_node_instructions"; node_id: string; value: string }
  | { op: "add_edge";           from_node_id: string; to_node_id: string; condition?: string; edge_id?: string }
  | { op: "remove_edge";        edge_id: string }
  | { op: "update_edge";        edge_id: string; property: string; value: unknown }
```

UI **Preview** panel: prefer `patch.preview` if present; otherwise request §3.10 diff or show ops as a human-readable list.

---

### 4.7 BlueprintVersionManifest

**File:** `intermediate/blueprint/manifest.json`

```typescript
BlueprintVersionManifest {
  schema_version:   "1.0"
  study_slug:       string
  current_version:  string                    // e.g. "v0003"
  baseline_version: "v0001"
  versions:         BlueprintVersionEntry[]
}

BlueprintVersionEntry {
  version:          string                    // "v0001", "v0002", …
  created_at:       string
  source:
    | "initial_fetch"
    | "proposal_apply"
    | "manual_edit"
  source_proposal_id?: string
  parent_version?:  string
  label?:           string                    // optional short note for version picker
  path:             string                    // "intermediate/blueprint/versions/v0002.json"
}
```

UI: optional version dropdown in blueprint viewer (baseline vs current vs per-applied-proposal version).

---

### 4.8 target_key uniqueness (no conflicting shallow proposals)

Each shallow proposal carries a **`target_key`**: a stable string identifying the **single blueprint entity** being modified.

**Format (examples):**

| Target | `target_key` example |
|--------|----------------------|
| Skill instructions | `skill:Main_Auth:instructions` |
| Tool description | `tool:call_transfer:description` |
| Dialog node | `node:46d843b2-5218-41d1-b509-2973c03b6459:property:label` |
| Dialog edge | `edge:abc123:condition` |
| Global guidelines | `global:guidelines` |

**Contract guarantees:**

1. **`proposal_bundle.json` contains at most one `pending` shallow proposal per `target_key`.**
2. **At most one `applied` shallow proposal per `target_key`** (unless earlier one is `superseded`).
3. **Apply** on a proposal fails with `409 PROPOSAL_CONFLICT` if that `target_key` already has an `applied` proposal.

This ensures independent, non-overlapping changes per instruction / node / entity.

---

### 4.9 Proposal generation status file

**File:** `intermediate/proposal_generation/status.json`

```typescript
ProposalGenerationStatus {
  status:       "not_started" | "generating" | "ready" | "failed"
  started_at?:  string
  finished_at?: string
  error?:       string
  bundle_path?: string                      // "output/proposal_bundle.json"
}
```

---

## 5. UI layout specification

### 5.1 Page structure

```
┌─────────────────────────────────────────────────────────────────┐
│  Proposals — {study_title}                                       │
│  [Generate proposals]  (hidden when generation.status=ready)    │
├─────────────────────────────────────────────────────────────────┤
│  Summary banner: bundle.summary + stats (N shallow · M deep)     │
├──────────────────────────┬──────────────────────────────────────┤
│  Shallow proposals       │  Blueprint workspace                  │
│  (scrollable list)       │  (version: v0003 ▾)                  │
│                          │  - Skills / instructions viewer       │
│  [card] Apply · Reject   │  - Tools / guardrails tabs           │
│  [card] …                │  - Dialog flow graph                 │
├──────────────────────────┴──────────────────────────────────────┤
│  Deep proposals (out of scope)                                   │
│  [card] Create Jira ticket · Acknowledge · Reject                │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Shallow proposal card fields

| UI element | Source field |
|------------|--------------|
| Title | `title` |
| Body | `description` |
| Impact | `expected_impact` |
| Confidence pill | `confidence` |
| Evidence | `evidence[]` |
| Location breadcrumb | `target.display_label` |
| Preview diff | `patch.preview` or §3.10 |
| Status badge | `status` |
| Primary CTA | **Apply** → §3.6 |
| Secondary | **Reject** → §3.7 |

Selecting a card highlights `target` in the blueprint workspace (match on `target_key` / locators).

### 5.3 Deep proposal card fields

Same as shallow for title, description, evidence, confidence — plus:

| UI element | Source field |
|------------|--------------|
| Category badge | `category` |
| Out of scope note | `out_of_scope_reason` |
| Repo snippets | `repo_references[]` (expandable) |
| **Create Jira ticket** | §3.9 stub |
| **Acknowledge** / **Reject** | §3.9 / §3.7 |

### 5.4 Empty & loading states

| State | Copy / behavior |
|-------|-----------------|
| `not_started` | “Evaluation complete. Generate proposals to get VA Blueprint change suggestions.” |
| `generating` | Spinner + tail of `logs_url` (optional log panel, same pattern as Explore) |
| `failed` | Error message + **Retry** (calls §3.3 again) |
| `ready`, zero shallow + zero deep | “No proposals generated.” (unexpected; show retry) |

### 5.5 Polling

| When | Poll target | Interval | Stop when |
|------|-------------|----------|-----------|
| After §3.3 | `GET …/proposals` | 2–3 s | `generation.status` ∈ `{ ready, failed }` |

Study `meta.status` remains `complete` during proposal generation (no new top-level study status required).

---

## 6. Relationship to Results tab artifacts

| Results artifact | Proposals usage |
|------------------|-----------------|
| `evaluation_result.quantitative.aspects[]` | **Full array** passed to both LLM calls; proposals cite via `finding_type: "aspect"` |
| `evaluation_result.qualitative.hypotheses[]` | **Full array** passed to both LLM calls; proposals cite via `finding_type: "hypothesis"` |
| `artifacts.narrative_summary` | Banner context; optional evidence (`finding_type: "narrative"`) |
| `artifacts.recommendations[]` | Passed into generation; may appear as evidence (`finding_type: "recommendation"`) |
| Hypothesis `counter_examples[]` | Linked from evidence `session_ids` |

Results tab unchanged. Proposals tab is the **structured, actionable** layer.

---

## 7. Error codes (Proposals-specific)

| HTTP | `code` | When |
|------|--------|------|
| 409 | `INVALID_STATE` | Study not `complete` |
| 409 | `GENERATION_IN_PROGRESS` | Duplicate generate while running |
| 409 | `PROPOSAL_CONFLICT` | `target_key` already applied |
| 409 | `APPLY_FAILED` | Patch ops could not be applied |
| 404 | `NOT_FOUND` | Unknown `proposal_id` or blueprint `version` |
| 409 | `PROPOSAL_NOT_PENDING` | Apply/reject on non-pending proposal |

---

## 8. Example JSON fragments

### 8.1 Shallow proposal (partial text patch)

```json
{
  "id": "prop-transfer-tool-main-auth",
  "title": "Require call_transfer on second agent request",
  "description": "Sessions show repeated agent requests without transfer tool invocation.",
  "confidence": "high",
  "expected_impact": "Increase transfer tool usage when caller insists on a human.",
  "evidence": [{
    "finding_type": "hypothesis",
    "finding_id": "frustration_escalation",
    "severity": "high",
    "summary": "16% match rate; counter-examples include early transfer without tool call.",
    "session_ids": ["90f279b0-68d0-4eed-b307-98d4570780a1"]
  }],
  "target": {
    "domain": "skill.instructions",
    "skill_name": "Main_Auth",
    "field_path": "instructions",
    "display_label": "Main_Auth › Instructions › Escalation"
  },
  "target_key": "skill:Main_Auth:instructions",
  "patch": {
    "ops": [{
      "op": "insert_after",
      "anchor": "**Second Request / Refusal of Probe (Transfer Immediately):**",
      "text": "\n\n> **TOOL REQUIREMENT:** On the second explicit agent request, you MUST invoke the `call_transfer` tool.\n"
    }],
    "preview": {
      "before_excerpt": "…stop all processing immediately…",
      "after_excerpt": "…stop all processing immediately.\n\n> **TOOL REQUIREMENT:**…"
    }
  },
  "status": "pending"
}
```

### 8.2 Shallow proposal (full field replacement)

```json
{
  "id": "prop-rewrite-welcome",
  "title": "Clarify supported intents in welcome message",
  "target_key": "global:welcome_message",
  "target": {
    "domain": "welcome_message",
    "display_label": "Welcome message"
  },
  "patch": {
    "ops": [{
      "op": "replace_field",
      "field_path": "welcome_message.text",
      "value": "Thank you for calling. I can help with billing questions and payments. Payment extensions must be handled by a specialist."
    }]
  },
  "status": "pending"
}
```

### 8.3 Deep proposal

```json
{
  "id": "prop-backend-transfer-signal",
  "title": "Add transfer_tool_invoked primitive",
  "category": "evaluation_pipeline",
  "out_of_scope_reason": "Requires new rule-based signal in trace feature extraction, not a VA Blueprint edit.",
  "recommendation": "Emit a boolean primitive from CALL_TRANSFER_REQUESTED events for hypothesis predicates.",
  "evidence": [{
    "finding_type": "hypothesis",
    "finding_id": "payment_failure_transfer",
    "severity": "medium",
    "summary": "0% match due to missing payment_failed outcome label in session_outcome."
  }],
  "repo_references": [{
    "repo_path": "ypervaino/features.py",
    "relevance": "FeatureComputer session_outcome mapping"
  }],
  "status": "pending"
}
```

---

## 9. Changelog

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2026-09-01 | Initial Proposals tab contract |
| 1.1 | 2026-09-01 | Full VA Blueprint + full aspect/hypothesis results as generation inputs (§1.1) |
