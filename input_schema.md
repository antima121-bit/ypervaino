# Ypervaíno — Input Schema (v1)

**Source of truth for modeling:** [draft3.md](./draft3.md)  
**Status:** Input schema only. Output schema is out of scope for this document.

---

## 1. User-facing inputs

Everything the user (or UI) submits explicitly. Mapped to UI tab where it is captured.

### 1.1 Tab: **New Study**

Submitted once when the user creates a study. Persisted as `studies/<study_slug>/input/create_study.json`.

#### Required fields

| Field | Type | Validation | Maps to (draft3) |
|-------|------|------------|------------------|
| `study_title` | `string` | Non-empty; unique among saved studies; used as directory name after slugify | `StudyMetadata.title` + storage path |
| `study_type` | `"comparative"` \| `"single_cohort"` | Required | `ComparativeStudy` \| `SingleCohortStudy` |
| `tenant` | `string` | Required; must exist in env | `ScopeFilter.tenant` |
| `assistant_origin_id` | `string` | Required | `ScopeFilter.assistant_origin_id` |
| `channel` | `"voice"` \| `"chat"` | Required; default `"voice"` in UI | `ScopeFilter.channel` |

#### Date / time windows

| Field | Type | When required | Maps to |
|-------|------|---------------|---------|
| `date_range` | `DateTimeRange` | `study_type == "single_cohort"` | `ScopeFilter.date_range` |
| `date_range_before` | `DateTimeRange` | `study_type == "comparative"` | `scope_before.date_range` |
| `date_range_after` | `DateTimeRange` | `study_type == "comparative"` | `scope_after.date_range` |

```typescript
DateTimeRange {
  start: string   // ISO 8601 datetime
  end:   string   // ISO 8601 datetime
}
```

**ComparativeStudy UI rule:** Same `tenant`, `assistant_origin_id`, and `channel` for both windows; only date ranges differ.

#### Optional fields — change context

| Field | Type | Default | Maps to |
|-------|------|---------|---------|
| `change_description` | `string` | empty | `ChangeDescriptor.description` |
| `pr_link` | `string` | null | `ChangeDescriptor.pr_link` |

If both are empty → **pure discovery mode** (`x = null` in draft3).

#### Optional fields — scope refinement

| Field | Type | Default | Maps to |
|-------|------|---------|---------|
| `assistant_id` | `string` | null | `ScopeFilter.assistant_id` (pin one published version) |
| `cohort_filters` | `CohortFilter[]` | `[]` | compiled → `ScopeFilter.conversation_predicate` |
| `traffic_split` | `TrafficSplit` | null | `ScopeFilter.traffic_split` |

```typescript
CohortFilter {
  atom_id: string    // key from system FilterAtom registry (see §2.3)
  value?: string | string[] | number | boolean   // when atom requires user value
}

TrafficSplit {
  dimension: string   // e.g. "canary_variant", "model_id"
  value:     string
}
```

**v1 cohort filter atoms (UI chips):**

| `atom_id` | UI label | User value needed? |
|-----------|----------|-------------------|
| `main_stream_model_is` | Main stream model is… | yes (model id) |
| `purpose_used` | LLM purpose used in call | yes (e.g. `main_stream`, `kb_stream`) |
| `skill_active` | Skill / agent was active | yes (e.g. `Main_Auth`) |
| `guardrail_triggered` | Guardrails triggered | no |
| `transfer_completed` | Call transfer happened | no |
| `interruption_occurred` | Interruption occurred | no |

#### Optional fields — sampling

| Field | Type | Default | Maps to |
|-------|------|---------|---------|
| `n_explore` | `integer` | `100` | `StudyConfig.n_explore` |
| `n_eval` | `integer` \| `"all"` | `"all"` | `StudyConfig.n_eval` |
| `n_eval_before` | `integer` \| `"all"` | same as `n_eval` | `StudyConfig.n_eval_before` (comparative only) |
| `n_eval_after` | `integer` \| `"all"` | same as `n_eval` | `StudyConfig.n_eval_after` (comparative only) |

**Validation:** If `study_type == "comparative"`, `n_explore` must be **even**.

#### Hidden defaults (not shown in v1 UI; applied by backend)

| Field | Default | Maps to |
|-------|---------|---------|
| `min_support` | `30` | `StudyConfig.min_support` |
| `significance_level` | `0.05` | `StudyConfig.significance_level` |
| `pairing_turn_tolerance` | `3` | `StudyConfig.pairing_turn_tolerance` |

---

### 1.2 Tab: **Explore**

**Not a form of study parameters.** This tab displays Phase 2 output and accepts one user action.

| User action | Type | Effect |
|-------------|------|--------|
| **Execute plan** | button click | Sets plan approved; runs Phase 3; navigates to Results when done |

**Displayed (read-only, from `AnalysisPlan`):**

| Section | Content |
|---------|---------|
| Quantitative | Proposed **aspects**, **plot** specs, **table** specs |
| Qualitative | Proposed **hypotheses** (title, description, signal summary) |
| Meta | `exploration_summary`, cohort sizes after Phase 0, `n_explore` sample count |

**v1 explicitly excluded:** edit plan, delete hypothesis, revise with feedback, re-run Phase 2.

---

### 1.3 Tab: **Results**

**No user inputs.** Read-only view of `EvaluationResult` (output schema, later).

Optional v1 affordances (navigation, not schema inputs):

- Click session id → open BotProbe (or trace viewer) with `session_id` pre-filled
- Export CSV / JSON from study directory

---

### 1.4 Complete user-facing object: `CreateStudyRequest`

```json
{
  "study_title": "Resound Qwen 10% Aug 20-22",
  "study_type": "comparative",

  "change_description": "Moved 10% main_stream traffic to Qwen",
  "pr_link": "https://gitlab.com/.../merge_requests/123",

  "tenant": "resound",
  "assistant_origin_id": "875df174-e8ad-419d-8269-5b064593f865",
  "assistant_id": null,
  "channel": "voice",

  "date_range_before": {
    "start": "2026-08-20T00:00:00+05:30",
    "end": "2026-08-21T23:59:59+05:30"
  },
  "date_range_after": {
    "start": "2026-08-22T00:00:00+05:30",
    "end": "2026-08-23T23:59:59+05:30"
  },

  "cohort_filters": [
    { "atom_id": "main_stream_model_is", "value": "main_model" }
  ],
  "traffic_split": null,

  "n_explore": 100,
  "n_eval": 5000
}
```

**Single cohort example** uses `date_range` instead of `date_range_before` / `date_range_after`.

---

### 1.5 UI tab flow (v1)

```
New Study tab
  User fills CreateStudyRequest → Submit
  Backend: Phase 0 → Phase 1 → Phase 2
  Persist under studies/<study_slug>/
  Auto-switch or link to Explore tab

Explore tab
  Show AnalysisPlan (read-only)
  User clicks "Execute plan"
  Backend: Phase 3
  Switch to Results tab when complete

Results tab
  Show EvaluationResult artifacts
```

---

## 2. System-facing inputs

Not entered by the user. Loaded from config, code, or environment at runtime.

### 2.1 `SystemKnowledge` (static, repo / config file)

Maintainer-authored platform rules. Same for all studies.

| Key | Purpose |
|-----|---------|
| `instructions[]` | e.g. "If model_id is main_model, inference cost is $0" |
| `price_table` | model_id → { input_usd, output_usd, thinking_usd? } per token |
| `zero_cost_models[]` | e.g. `["main_model"]` |
| `model_aliases` | deployment name aliases |
| `event_schema_summary` | Event types + key metadata paths (hackathon: hardcoded) |
| `dedup_rules` | `EventDeduplicationPolicy` per event_type |

**File suggestion:** `config/system_knowledge.yaml` or `config/event_schema.json`

---

### 2.2 Mongo connection (environment)

Direct Mongo access for v1 (no Argus Postgres pipeline required).

| Env var | Purpose |
|---------|---------|
| `MONGO_URI` | Connection string |
| `MONGO_DB_NAME` | Database (e.g. bot_prod, bot_development) |

**Collections read (v1 minimum):**

| Collection | Use |
|------------|-----|
| `assistant_event` | Primary event trace per session |
| `AssistantSession` or session index | List sessions by tenant, time, assistant; outcome fields |
| Optional: `session_request` | Enrichment if needed for tool/outcome (Phase 0+) |

Session list query uses scope fields from `CreateStudyRequest`; events loaded per `session_id`.

---

### 2.3 Filter atom registry (static, code)

Maps UI `cohort_filters[].atom_id` → `conversation_predicate` operands.

```yaml
# example entry
- id: main_stream_model_is
  label: "Main stream model is"
  primitive: main_stream_model_invoked
  op: "=="
  value_type: string

- id: guardrail_triggered
  label: "Guardrails triggered"
  primitive: guardrail_triggered
  op: "=="
  value: true
```

**File suggestion:** `config/filter_atoms.yaml`

---

### 2.4 Primitive catalog (static, code)

Layer-0 definitions for Phase 0 filters, Phase 3 computation, exploration features.

**File suggestion:** `config/primitives.yaml` or Python module `primitives/catalog.py`

References `event_schema_summary` for field paths.

---

### 2.5 VA Blueprint fetch (automatic per study)

| Input (from user study) | System action |
|-------------------------|---------------|
| `tenant`, `assistant_origin_id` | HTTP call to bot `POST /service/va-blueprint/extract_blueprint` OR direct Mongo blueprint path |

Output: `VABlueprintSummary` stored in study directory as `intermediate/blueprint_summary.json`.

**Env (if using bot API):**

| Env var | Purpose |
|---------|---------|
| `BOT_API_BASE_URL` | Bot service URL |
| `BOT_SERVICE_TOKEN` | Auth for blueprint endpoint |

---

### 2.6 `ChangeContextResolver` (automatic when change fields set)

| Trigger | System action |
|---------|---------------|
| `pr_link` present | Fetch PR/MR diff → LLM summarize → `ChangeContext` |
| `change_description` only | Optional keyword RAG over bot docs (v1: LLM summarize description alone is acceptable) |
| Both empty | Skip; pure discovery |

Stored: `intermediate/change_context.json`

---

### 2.7 LLM / embedding providers (environment)

Used in Phase 1 (intent classification, embeddings), Phase 2b (plan synthesis), Phase 3 (semantic signals).

| Env var | Purpose |
|---------|---------|
| `OPENAI_API_KEY` or equivalent | Plan generation, classifiers |
| Model names | Config defaults for planner vs cheap classifier |

---

### 2.8 File storage layout (v1 persistence)

Root: `STUDIES_ROOT` env var or `./studies/`

```
studies/<study_slug>/
  input/
    create_study.json          # CreateStudyRequest
  intermediate/
    cohort_stats.json          # Phase 0: |D|, filter counts
    s_explore/                 # Phase 1: session ids + digests
    blueprint_summary.json
    change_context.json        # if applicable
    analysis_plan.json         # Phase 2 output
  output/
    evaluation_result.json     # Phase 3
    tables/
    plots/
    per_conversation/          # optional shards if large
  meta.json                    # status: created | explored | running | complete | failed
```

`study_slug = slugify(study_title)` with collision suffix if needed.

**Not used in v1:** Postgres study table, Redis job queue (optional later), Argus API.

---

### 2.9 External links (config only)

| Config | Purpose |
|--------|---------|
| `BOTPROBE_BASE_URL` | Results tab session links, e.g. `{base}?session_id={id}` |

---

### 2.10 Semantic signal execution defaults (static)

Maps `SemanticSignal.method` → implementation (rules, embed, small LM). Not user-configurable in v1.

**File suggestion:** `config/semantic_methods.yaml`

---

## 3. Compile mapping: `CreateStudyRequest` → draft3 `StudyQuery`

```
if study_type == "single_cohort":
  StudyQuery = SingleCohortStudy(
    x = ChangeDescriptor or null,
    scope = ScopeFilter(
      tenant, assistant_origin_id, assistant_id, channel,
      date_range,
      conversation_predicate = compile(cohort_filters),
      traffic_split
    ),
    config = StudyConfig(n_explore, n_eval, min_support, ...)
  )

if study_type == "comparative":
  StudyQuery = ComparativeStudy(
    x = ChangeDescriptor or null,
    scope_before = ScopeFilter(..., date_range_before, ...),
    scope_after  = ScopeFilter(..., date_range_after, ...),
    config = StudyConfig(n_explore, n_eval, n_eval_before, n_eval_after, ...)
  )
```

Phase 2 produces `AnalysisPlan`. User **Execute** on Explore tab → `analysis_plan.user_approved = true` → Phase 3.

---

## 4. Summary table

| Category | v1 user-facing? | Examples |
|----------|-----------------|----------|
| Study identity | yes | title, study_type |
| Change context | yes (optional) | change_description, pr_link |
| Scope | yes | tenant, assistant_origin_id, channel, date range(s) |
| Cohort filters | yes (optional) | cohort_filters chips |
| Sampling | yes (optional) | n_explore, n_eval |
| Plan approval | yes (one button) | Execute on Explore tab |
| SystemKnowledge | no | cost rules, event schema |
| Mongo / env | no | MONGO_URI, MONGO_DB_NAME |
| Filter atoms / primitives | no | config files |
| Blueprint / ChangeContext | no | auto from study scope + PR |
| Study directory | no | derived from study_title |

---

## 5. Document history

| Version | Date | Notes |
|---------|------|-------|
| v1 | 2026-08-29 | Initial input schema; v1 scope: no plan loop, 3 tabs, Mongo direct, file storage |