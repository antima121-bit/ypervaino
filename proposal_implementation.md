# Ypervaíno — Proposal Generation Implementation (Option 3+)

**Audience:** Backend / pipeline implementers  
**Related:** [proposal_contract.md](./proposal_contract.md) (frontend contract), [change_context.py](./ypervaino/change_context.py), [bot_repo.py](./ypervaino/bot_repo.py)

This document describes **how to implement Phase 4** (on-demand proposal generation) and the **apply / versioning** path. Output shapes and HTTP routes are defined in [proposal_contract.md](./proposal_contract.md).

---

## 1. Strategy summary (Option 3+)

Two **independent LLM calls**, plus **deterministic post-processing**:

| Step | Mechanism | Output |
|------|-----------|--------|
| **A — Shallow** | Single structured LLM call | `shallow_proposals[]` (VA Blueprint patches) |
| **B — Deep** | Single structured LLM call | `deep_proposals[]` (backend / pipeline advisory) |
| **C — Repo context (no ReAct)** | Deterministic `grep_repo` / `read_repo_file` before Call B | Snippets injected into deep prompt |
| **D — Post-process** | Python validation | Dedupe `target_key`, validate anchors, merge bundle |

**Not in v1:** ReAct loop for deep proposals (defer to post-hackathon; reuse `change_context` pattern when `pr_link` is set).

**Hackathon priority:** Call A + apply path must work reliably. Call B + Jira stub are secondary demo value.

---

## 2. Pipeline placement

```
Phase 0  → baseline blueprint v0001 + optional dialog_flow.json
Phase 3  → evaluation_result.json  →  status: complete
Phase 4  → on POST /proposals/generate (async, poll GET /proposals)
Apply    → on POST /proposals/{id}/apply (sync per proposal)
```

Phase 4 does **not** change study `meta.status` (stays `complete`). Job state lives in `intermediate/proposal_generation/status.json`.

---

## 3. New / extended modules

| Module | Responsibility |
|--------|----------------|
| `ypervaino/blueprint_store.py` | Version manifest, read/write `v000N.json`, bump version on apply |
| `ypervaino/proposal_generator.py` | Orchestrate Phase 4 (Calls A + B, post-process, write bundle) |
| `ypervaino/proposal_shallow.py` | Build shallow prompt, parse `shallow_proposals[]` |
| `ypervaino/proposal_deep.py` | Repo snippet fetch, build deep prompt, parse `deep_proposals[]` |
| `ypervaino/proposal_validate.py` | `target_key` dedupe, anchor check, patch dry-run |
| `ypervaino/blueprint_patch.py` | Apply `BlueprintPatch` ops to blueprint dict; used by apply + validate |
| `ypervaino/study_runner.py` | Add `run_phase4_proposals(slug)` background job |
| `app.py` | Routes from [proposal_contract.md §3](./proposal_contract.md#3-http-api) |

**Phase 0 change:** After `fetch_blueprint`, persist full raw response to `intermediate/blueprint/versions/v0001.json` and initialize `manifest.json` (today only `blueprint_summary.json` is stored).

---

## 4. Phase 4 orchestration

```python
def run_phase4(store: StudyStore) -> None:
    set_status("generating")

    ctx = load_generation_context(store)   # §5

    shallow = generate_shallow_proposals(ctx)   # Call A
    snippets = fetch_repo_snippets(ctx)         # §6.3 deterministic
    deep = generate_deep_proposals(ctx, snippets)  # Call B

    bundle = post_process_bundle(shallow, deep, ctx)  # §7
    store.write_json(output/proposal_bundle.json, bundle)
    set_status("ready")
```

Run in a background thread (same pattern as Phase 3 in `study_runner.py`). Log to `intermediate/pipeline.log` with prefix `[Phase 4]`.

On failure: `status.json` → `failed`, `error` message set; do not partial-write bundle (or write bundle with empty arrays + error in status only — prefer no bundle on failure).

---

## 5. Generation context (`load_generation_context`)

Assemble once per run:

| Field | Source | Notes |
|-------|--------|-------|
| `evaluation` | `output/evaluation_result.json` | aspects, hypotheses, counter_examples, narrative |
| `recommendations` | `evaluation.artifacts.recommendations[]` | explicit input to both prompts |
| `analysis_plan` | `intermediate/analysis_plan.json` | predicates, aspect definitions |
| `blueprint` | `blueprint_store.current()` → usually `v0001` at first generation | **full VA Blueprint JSON** (not trimmed) |
| `aspect_results` | `evaluation_result` → `quantitative.aspects[]` (or top-level `aspects[]`) | passed in full to both LLM calls |
| `hypothesis_results` | `evaluation_result` → `qualitative.hypotheses[]` (or top-level `hypotheses[]`) | passed in full to both LLM calls |
| `dialog_flow` | `intermediate/blueprint/dialog_flow.json` | if missing, omit from shallow prompt |
| `change_context` | `intermediate/change_context.json` | may be `{}` |
| `event_schema` | `config/event_schema.json` | for deep call |
| `study_query` | `input/create_study.json` | tenant, assistant, change_description, pr_link |

Both LLM calls receive **complete** aspect and hypothesis result arrays from Phase 3 — not a ranked subset. The model is instructed to prioritize the worst findings; post-processing caps output count.

---

## 6. LLM Call A — Shallow (VA Blueprint)

### 6.1 Model & output

- Model: same as plan synthesis (`gpt-4.1` or configured default).
- Response: **JSON only** matching `ShallowProposal[]` subset from [proposal_contract §4.3](./proposal_contract.md#43-shallowproposal).
- Max proposals: **5** (prompt instruction); post-process may drop invalid ones.

### 6.2 Prompt structure

```
System:
  You produce VA Blueprint change proposals as JSON.
  Each proposal must include: id, title, description, confidence, expected_impact,
  evidence[], target, target_key, patch (ops + preview), status="pending".
  Use only PatchOp types from the contract.
  At most one proposal per target_key.
  Prefer partial text ops (insert_after, replace_text) for small edits;
  use replace_field for full instruction rewrites.

User:
  ## Aspect results
  {aspect_results JSON — full evaluation_result quantitative aspects}

  ## Hypothesis results
  {hypothesis_results JSON — full evaluation_result qualitative hypotheses, including counter_examples}

  ## Recommendations from Phase 3
  {recommendations}

  ## Current VA Blueprint (full)
  {full blueprint JSON — current version from blueprint_store; skills, tools, guardrails, instructions, orchestration config, etc.}

  ## Dialog flow (if present)
  {dialog_flow JSON — full graph, not a summary}

  ## Analysis plan
  {analysis_plan.quantitative.aspects + analysis_plan.qualitative.hypotheses — predicates and component definitions}

  Generate shallow_proposals[] addressing the worst findings across aspects and hypotheses.
```

**No blueprint trimming.** Pass the entire VA Blueprint payload. If token limits are hit, truncate only `dialog_flow` or repo snippets in Call B — never silently trim skill instructions in Call A.

### 6.3 Parsing

- Use `LLMClient.json_completion` with repair pass on parse failure (one retry).
- Assign UUIDs if model omits `id`.
- Force `status: "pending"`.

---

## 7. LLM Call B — Deep (backend / dev)

### 7.1 Deterministic repo snippets (before LLM, not ReAct)

Use `study_query.pr_link` + `change_context.affected_modules` + finding keywords to run fixed greps:

```python
PATTERNS = [
    "session_outcome",
    "transfer_count",
    "CALL_TRANSFER",
    "payment_failed",
    "FeatureComputer",
]
# grep_repo each pattern, max 5 matches; read_repo_file top 2 paths, max 8k chars each
```

Checkout via existing `checkout_for_change(pr_link)` if not already done in Phase 0.

If no repo checkout: deep call still runs with `event_schema` + evaluation only; `repo_references` may be empty.

### 7.2 Prompt structure

```
System:
  You produce backend/dev change proposals as JSON (deep_proposals[]).
  These are OUT OF SCOPE for VA Blueprint — pipeline, primitives, bot code, infra.
  Each needs: id, title, description, confidence, category, evidence[],
  recommendation, out_of_scope_reason, optional repo_references[], status="pending".

User:
  ## Aspect results
  {aspect_results JSON — full evaluation_result quantitative aspects}

  ## Hypothesis results
  {hypothesis_results JSON — full evaluation_result qualitative hypotheses, including counter_examples}

  ## Recommendations from Phase 3
  {recommendations}

  ## Change context
  {change_context JSON}

  ## Event schema
  {event_schema JSON — full file or substantial excerpt}

  ## Repo snippets (grep results)
  {deterministic grep/read_repo output}

  ## Shallow proposals already generated (avoid duplicating same fix)
  {titles only of shallow proposals}

  Generate deep_proposals[] for issues that CANNOT be fixed via blueprint edits alone.
  Prioritize findings with poor aspect metrics or failed/rejected hypotheses where blueprint edits are insufficient.
  Max 5 proposals.
```

---

## 8. Post-processing (`post_process_bundle`)

Run in order:

| Step | Action |
|------|--------|
| 1 | **Dedupe `target_key`** among shallow: keep highest `confidence`; mark others dropped (log) |
| 2 | **Validate targets** exist in blueprint (skill_name, node_id, tool_name) |
| 3 | **Dry-run patches** against current blueprint via `blueprint_patch.apply_ops(dry_run=True)` |
| 4 | Drop shallow proposals where any op fails anchor/field lookup |
| 5 | **Dedupe deep** by similar `title` (optional fuzzy) |
| 6 | Build `ProposalBundle` wrapper with `inputs` snapshot, `stats`, `summary` (LLM one-liner or template) |

Write `output/proposal_bundle.json`.

---

## 9. Apply path (shallow proposal)

Synchronous on `POST …/proposals/{id}/apply`:

```python
def apply_shallow_proposal(store, proposal_id):
    bundle = load_bundle()
    proposal = find_shallow(bundle, proposal_id)
    assert proposal.status == "pending"
    assert no_other_applied(proposal.target_key)

    current = blueprint_store.current_version()
    blueprint = blueprint_store.load(current)
    new_blueprint = blueprint_patch.apply_ops(blueprint, proposal.patch)  # raises on failure

    new_version = blueprint_store.append_version(
        new_blueprint,
        source="proposal_apply",
        source_proposal_id=proposal_id,
        parent_version=current,
    )
    update_proposal_status(proposal_id, "applied", applied_version=new_version)
    return new_version
```

`blueprint_patch.apply_ops` implements all `PatchOp` types from [proposal_contract §4.6](./proposal_contract.md#46-blueprintpatch).

**Conflict rule:** If `target_key` already has an `applied` proposal → `409 PROPOSAL_CONFLICT` (do not apply).

---

## 10. Blueprint store (`blueprint_store.py`)

### 10.1 Phase 0 initialization

On first blueprint fetch:

```python
def init_baseline(store, raw_blueprint: dict) -> None:
    path = store.intermediate_dir / "blueprint/versions/v0001.json"
    write_version_file(path, raw_blueprint, meta={source: "initial_fetch"})
    write_manifest(current_version="v0001", versions=[...])
```

Optionally fetch dialog flow from separate endpoint → `intermediate/blueprint/dialog_flow.json`.

### 10.2 Version bump

- Sequential: `v` + zero-padded 4 digits (`v0002`, `v0003`, …).
- Immutable files; manifest append-only.
- `append_version` updates `current_version`.

---

## 11. HTTP wiring (`app.py`)

Implement routes exactly as [proposal_contract.md §3](./proposal_contract.md#3-http-api):

| Route | Handler |
|-------|---------|
| `GET /studies/{slug}/proposals` | Read `status.json` + optional `proposal_bundle.json` + manifest pointer |
| `POST /studies/{slug}/proposals/generate` | `study_runner.enqueue_phase4(slug)` if not generating |
| `POST /studies/{slug}/proposals/{id}/apply` | §9 |
| `POST /studies/{slug}/proposals/{id}/reject` | Update status in bundle JSON |
| `POST /studies/{slug}/proposals/{id}/acknowledge` | Deep only |
| `POST /studies/{slug}/proposals/{id}/jira-stub` | Build `ticket_draft` from proposal fields (no API call) |
| `GET /studies/{slug}/blueprint/manifest` | |
| `GET /studies/{slug}/blueprint/versions/{version}` | |
| `POST /studies/{slug}/blueprint/patch` | Manual edit → same as apply |

Persist proposal status mutations back to `output/proposal_bundle.json`.

---

## 12. Logging & observability

```
[+1234ms][MainThread] [Phase 4] starting proposal generation
[+2345ms][MainThread] [Phase 4] Call A: 4 shallow proposals parsed
[+3456ms][MainThread] [Phase 4] repo grep: 12 snippets
[+4567ms][MainThread] [Phase 4] Call B: 2 deep proposals parsed
[+4678ms][MainThread] [Phase 4] post-process: 3 shallow kept, 1 dropped (anchor)
[+4700ms][MainThread] [Phase 4] complete → output/proposal_bundle.json
```

---

## 13. Config / env

| Key | Purpose |
|-----|---------|
| `OPENAI_API_KEY` | Both LLM calls |
| `PROPOSAL_SHALLOW_MODEL` | default plan model |
| `PROPOSAL_DEEP_MODEL` | default plan model |
| `PROPOSAL_MAX_SHALLOW` | default 5 |
| `PROPOSAL_MAX_DEEP` | default 5 |
| `BOT_REPO_URL`, `GITLAB_TOKEN` | Repo snippets for Call B |
| `PRODUCTION_SERVICE_TOKEN` | Blueprint + dialog flow fetch |

---

## 14. Testing checklist

| Test | Expected |
|------|----------|
| Generate on `qwen-swap-6` (complete study) | `status → ready`, bundle with ≥1 shallow |
| Duplicate generate while running | 202, single job |
| Apply one shallow proposal | `v0002` created, proposal `applied` |
| Apply second proposal (different target_key) | `v0003` |
| Apply conflicting target_key | 409 |
| Reject proposal | status `rejected`, no version bump |
| Jira stub on deep proposal | 200 + `ticket_draft` |
| Generate without change_context / pr_link | deep call still succeeds |

---

## 15. Post-hackathon upgrades

| Upgrade | Description |
|---------|-------------|
| **ReAct deep loop** | Replace §7.1 snippets with `change_context`-style agent when `pr_link` set |
| **Finding-driven shallow loop** | One LLM call per top finding for higher patch accuracy |
| **Real Jira API** | Wire `jira-stub` → create issue |
| **Publish blueprint** | Push `current_version` back to VA Blueprint API |
| **Regenerate after apply** | Mark remaining proposals `superseded` if blueprint text drift invalidates anchors |

---

## 16. Implementation order

1. `blueprint_store` + Phase 0 baseline persistence  
2. `blueprint_patch` + validate (unit-test ops against sample blueprint)  
3. `proposal_shallow` + Call A + post-process  
4. API: generate + GET proposals  
5. Apply endpoint + version bump  
6. `proposal_deep` + Call B + Jira stub  
7. `proposals.html` tab (frontend, per contract)

---

## 17. Changelog

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2026-09-01 | Option 3+ implementation plan |
| 1.1 | 2026-09-01 | Full VA Blueprint + full aspect/hypothesis results in both LLM calls |
