# Sample walkthrough — comparative Qwen main_stream study

A line-by-line pass through the Ypervaíno pipeline in plain English.

**Example setup:**

| Field | Value |
|-------|--------|
| Tenant | resound |
| Assistant | `x` (assistant origin id) |
| Channel | voice |
| Study type | Comparative (before / after) |
| Before window | date 1 → date 2 (pre-deploy) |
| After window | date 1 → date 2 (post-deploy) |
| Change | Qwen model deployed for `main_stream` |

---

## 1. You submit the study (New Study tab)

You fill in:

- Study title
- Tenant: **resound**
- Assistant: **x**
- Channel: **voice**
- **Comparative** mode: before dates + after dates
- Change note: e.g. “Qwen deployed for main_stream”
- Optional cohort filters: e.g. main stream model is Qwen (after window)
- Sample sizes: `n_explore`, `n_eval`
- Min support and significance level (backend defaults if not shown in UI)

You click **Submit**.

The backend saves `studies/{slug}/input/create_study.json` and starts **Phase 0 → 1 → 2** in the background. Study status: `created`.

---

## 2. Phase 0 — Find conversations and build features

### 2a. List sessions from Mongo

- Query `AssistantSession` for resound + assistant x + voice + date range.
- **Before cohort:** sessions in the pre-deploy window.
- **After cohort:** sessions in the post-deploy window.
- Result: lists of session UUIDs (`voice_session_id`).

### 2b. Load full logs for each session

- For each UUID: `GET BotProbe /trace?session_id=…&env=prod`.
- Full event stream (USER_QUERY, LLM_*, TOKEN_*, tools, etc.).
- **Not** Mongo `AssistantEvent` (incomplete subset).

### 2c. Build one conversation record per session

- Sort events by time.
- Dedupe (e.g. keep first `SESSION_END` on reconnect calls).
- Derive transcript from `USER_QUERY` + `RESPONSE.FINAL`.
- Flag reconnect sessions when `voice_session.reconnects >= 1`.

### 2d. Compute primitives (cached per session)

From `config/primitives.yaml`, for example:

- `turn_count`
- `main_stream_model` / `main_stream_model_invoked`
- `main_stream_latency_p95`
- `main_stream_estimated_cost_usd` (Qwen priced via `system_knowledge.yaml`; zero-cost only for `main_model`, `cq_model`, `router_model`)
- `tool_error_count`, `guardrail_triggered`, `transfer_completed`, etc.

Cached under `studies/{slug}/cache/features/{session_id}.json`.

### 2e. Apply cohort filters (if you set any)

- Example: “main stream model is qwen-…” → keep only matching sessions.
- Produces **D_before** and **D_after** (filtered sets).

### 2f. Fetch VA Blueprint

- HTTP call to bot blueprint API (or Mongo path) for resound + assistant x.
- Skills, tools, agents, transfer rules → `intermediate/blueprint_summary.json`.

### 2g. Change context (because you described the Qwen deploy)

- `ChangeContextResolver` reads your change description (and PR/MR link if provided).
- Summarizes affected modules, purposes (`main_stream`), event types → `intermediate/change_context.json`.

### 2h. Opening intent lexicon (one LLM call per study)

- Uses blueprint + `config/event_schema.json` + pilot stats from ~200 random sessions.
- Builds intent labels (billing, transfer, etc.) → `cache/intent_lexicon.json`.
- Scores every session’s opening intent (rule-based, cached in `FeatureVector`).

### 2i. Subsample for evaluation (if configured)

- If `n_eval` is not `"all"`, stratified subsample from each cohort.
- Writes `intermediate/cohort_stats.json` (counts before/after, filter stats).

Phase 0 does **not** change status to `explored` yet — that happens after Phase 2b.

---

## 3. Phase 1 — Pick sessions to explore

Goal: a **small, diverse sample** for the LLM to read — not the full cohort.

1. Split candidates into strata: opening intent × outcome bucket × length bucket.
2. Allocate `n_explore` quotas across strata (proportional; favor rare combinations).
3. Within each stratum: pick medoid + diverse neighbors (SBERT embeddings).
4. **Comparative:** pair before/after sessions with the same opening intent when possible.
5. Output: `intermediate/s_explore/manifest.json` (session ids for exploration).

---

## 4. Phase 2a — Build conversation digests

For each session in **S_explore**:

- Full transcript
- Short bullets (tools used, transfers, guardrails, model seen, odd patterns)
- Primitive snapshot (turn count, model, latency, cost, …)

Saved as `intermediate/s_explore/{session_id}.digest.json`.

No hypotheses yet — only structured summaries for planning.

---

## 5. Phase 2b — LLM writes the analysis plan (one structured call)

**Inputs:** all digests, blueprint summary, change context (“Qwen on main_stream”), event schema, system knowledge (cost rules), allowed signal methods (`config/semantic_methods.yaml`), artifact templates (`config/artifact_templates.yaml`).

**LLM outputs `intermediate/analysis_plan.json`:**

- **Aspects (quantitative),** e.g.:
  - Speed: `main_stream_latency_p95`
  - Cost: `main_stream_estimated_cost_usd`
  - Reliability: tool errors, guardrail rate, turn count
- **Hypotheses (qualitative claims)** with named signals + predicates, e.g.:
  - “After Qwen, auth flows have more tool errors”
  - “Transfer requests resolve in fewer turns”
- **Signals:** rule-based keywords, turn indices, intent classes — all declared in the plan
- **Suggested plots/tables** from the closed template list
- `user_approved: false`

Backend validates: JSON schema, predicate closure (every name defined), safe regex, allowed semantic methods.

Study status → **`explored`**. UI polls until Explore tab can load the plan.

---

## 6. You review (Explore tab)

You see:

- Cohort sizes (before / after)
- Proposed aspects and hypotheses
- Exploration summary text
- Planned charts and tables

**v1:** you do not edit the plan. To change scope or filters, create a new study.

You click **Execute plan** → `user_approved: true`, status → **`running`**, Phase 3 starts.

---

## 7. Phase 3 — Run the plan on the full evaluation cohort

For **every session** in D_eval (before + after, possibly thousands):

### 7a. Compute required primitives

Only those listed in `analysis_plan.primitives_required` (latency, cost, turn count, …).

### 7b. Compute required signals

- **Classical:** regex on transcript, turn index of transfer, duration between events, etc.
- **Semantic:** `rule_based` keyword scores, `intent_classifier` from cache
- Expensive LLM signals (`zero_shot_llm`, `llm_extract`) only where the plan caps scope — never blindly on full D_eval

### 7c. Evaluate each hypothesis predicate

Per session: does this conversation match the claim? (true / false)

### 7d. Aggregate aspects

- Before cohort: mean / p95 of latency, mean cost, etc.
- After cohort: same
- **Delta** + significance tests (Mann-Whitney, chi-square, Fisher — per value type)

### 7e. Hypothesis results

- Support count and match rate per cohort
- Reject hypotheses below `min_support`
- Select **counter-example** session ids (for BotProbe links)

### 7f. Render artifacts (deterministic, no LLM)

- PNG: e.g. `aspect_before_after_bar` for speed
- CSV: aspect summary, hypothesis summary, counter-examples
- Numbers come only from `evaluation_result` — not invented at render time

### 7g. Narrative summary (one LLM call)

Plain-English summary of what changed, with caveats.

**Output:** `output/evaluation_result.json`, `output/plots/`, `output/tables/`. Status → **`complete`**.

---

## 8. Results tab

You see:

- Before vs after on speed, cost, errors, conversation length, etc.
- Which hypotheses **held up** statistically
- Counter-examples — click session id → BotProbe trace viewer (`BOTPROBE_BASE_URL?session_id=…`)
- Optional export (zip / CSV)

---

## One-line summary

**Mongo finds which calls → BotProbe gives full logs → engine computes metrics → a small sample plus LLM proposes a test plan → you approve → engine runs that plan on all calls → charts, stats, and narrative tell you if Qwen on main_stream helped or hurt.**

---

## What this Qwen example depends on

| Step | Qwen-specific |
|------|----------------|
| Cohort split | Date windows = before / after deploy |
| Model detection | `LLM_CONFIG_RESOLVED` / `LLM_INVOCATION_SUCCESS` with `purpose=main_stream` |
| Cost | Qwen in `config/system_knowledge.yaml` `price_table`; not zero-cost unless id is `main_model` / alias |
| Change context | Planner focuses hypotheses on main_stream latency, cost, quality |
| Comparison | Aspects on `main_stream_latency_p95`, `main_stream_estimated_cost_usd`, etc. |

---

## Related docs

- [problem_statement_modelling.md](./problem_statement_modelling.md) — formal model
- [architecture.md](./architecture.md) — modules and algorithms
- [UI_design.md](./UI_design.md) — 3-tab flow
- [api.md](./api.md) — HTTP endpoints and polling
- [MONGO_LOOKUP.md](./MONGO_LOOKUP.md) — session ids + BotProbe `/trace`

---

## Document history

| Version | Date | Notes |
|---------|------|-------|
| v1 | 2026-08-30 | Initial sample walkthrough (comparative Qwen main_stream) |
