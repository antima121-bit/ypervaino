# Ypervaíno — Formal Model (Draft 3)

**Status:** Modeling only. No system design, architecture, or implementation details beyond v1 persistence and data-access boundaries described here.  
**Scope:** Data objects, query language, measurement layers, pipeline phases, knowledge injection, proof criteria, v1 UI surface, session discovery (Mongo) + event trace loading (BotProbe `/trace` API), and file-based study persistence for conversation-level impact and discovery analysis over bot event logs.

**Related:** User-facing and system-facing input contracts are specified in [input_schema.md](./input_schema.md).

---

## 1. Purpose

Ypervaíno analyzes virtual-agent conversations at scale to:

1. **Measure impact** of a backend change via quantitative aspects and hypothesis validation.
2. **Discover patterns** in production traffic without a predefined change descriptor (**pure discovery mode**).

**Pipeline:**

```
Phase 0:  Cohort resolution (+ conversation_predicate filter)
Phase 1:  Exploration sampling → S_explore
Phase 2:  Plan generation → AnalysisPlan (single pass)
          User reviews plan on Explore tab → clicks Execute
Phase 3:  Evaluation on D_eval → EvaluationResult
```

**Ground truth:** Session list from **MongoDB** (`AssistantSession`); full event traces from **BotProbe `/trace` API** (Elasticsearch). VA Blueprint for the same tenant/assistant. Transcripts derived from events.

**v1 constraints:**

- **No plan revision loop** — Phase 2 runs once; user approves by clicking **Execute** on the Explore tab.
- **No Argus Postgres pipeline** — Mongo for session index only; events via BotProbe `/trace`, not Mongo `AssistantEvent`.
- **File-based persistence** — all study inputs, intermediates, and outputs live under a directory keyed by `study_title`.

---

## 2. Application surface (v1)

The v1 web UI has three tabs. Each tab maps to a pipeline stage.

| Tab | Purpose | User action | Pipeline |
|-----|---------|-------------|----------|
| **New Study** | Create a study | Submit form (`CreateStudyRequest`) | Phase 0 → Phase 1 → Phase 2 |
| **Explore** | Review generated plan | **Execute plan** button (read-only plan display) | Sets `user_approved = true` → Phase 3 |
| **Results** | View outcomes | None (read-only; optional session links, export) | Displays `EvaluationResult` |

**Explore tab (v1):** Shows proposed aspects, plots, tables, and hypotheses from `AnalysisPlan`. The user does **not** edit the plan, provide feedback, or trigger re-planning. To change scope or filters, create a **new study**.

**Results tab (v1):** Shows quantitative aspect results, hypothesis support rates, counter-examples, and rendered artifacts. Session IDs may link to BotProbe or an internal trace viewer.

Field-level input definitions: [input_schema.md](./input_schema.md).

---

## 3. Study identity and persistence (v1)

Each study has metadata and a on-disk directory.

### 3.1 StudyMetadata

```
StudyMetadata {
  title:       string              // user-facing name (CreateStudyRequest.study_title)
  slug:        string              // filesystem-safe directory name
  created_at:  datetime
  updated_at:  datetime
  status:      "created" | "explored" | "running" | "complete" | "failed"
}
```

`slug = slugify(title)` with a numeric suffix on collision. All artifacts for the study are stored under `{STUDIES_ROOT}/{slug}/`.

### 3.2 Directory layout

```
{STUDIES_ROOT}/{slug}/
  meta.json                         # StudyMetadata
  input/
    create_study.json               # CreateStudyRequest (compiled to StudyQuery)
  intermediate/
    cohort_stats.json               # Phase 0: |D|, filter counts, subsample sizes
    blueprint_summary.json          # VABlueprintSummary
    change_context.json             # ChangeContext (if change fields set)
    s_explore/                      # Phase 1: session ids + ConversationDigests
    analysis_plan.json              # Phase 2 output
  output/
    evaluation_result.json          # Phase 3
    tables/
    plots/
    per_conversation/               # optional shards if large
```

**Not used in v1:** Postgres study database, Redis job queue, Argus API, or a dedicated analytics dataset store. Intermediate and output data are plain files (JSON, CSV, PNG, etc.).

### 3.3 Status transitions

```
created   — study submitted; Phase 0–2 in progress or complete
explored  — AnalysisPlan written; awaiting Execute on Explore tab
running   — Phase 3 in progress
complete  — EvaluationResult written
failed    — unrecoverable error; error detail in meta.json
```

---

## 4. Data access (v1)

VA-Argus (Postgres extraction pipeline) is **not** a runtime dependency in v1.

### 4.1 Two-source model

| Source | Role |
|--------|------|
| Mongo `AssistantSession` | Session index: list/filter by tenant, assistant, channel, date range, traffic split; expose `voice_session_id` (BotProbe UUID) and internal `_id` |
| BotProbe `GET /trace` | Full ordered event trace per session (backed by Elasticsearch, not Mongo) |

Optional Mongo enrichment: `SessionRequest` for turn-level transcript fields when event-derived transcript is insufficient.

**Not used for event loading:** Mongo `AssistantEvent` — incomplete subset of types; missing LLM/token/cost events present in BotProbe/ES.

### 4.2 Phase 0 fetch flow

1. Query `AssistantSession` with `ScopeFilter` fields (tenant, `assistant_origin_id`, optional `assistant_id`, channel, `date_range`, `traffic_split`).
2. For each candidate, call BotProbe `/trace?session_id={voice_session_id}&env=prod` (or internal hex id); materialize `ConversationRecord` from returned `events[]`.
3. Apply deduplication (§5.4) — e.g. first `SESSION_END` only on reconnect sessions (`voice_session.reconnects >= 1`).
4. Apply `conversation_predicate` if present (§6.3).
5. Apply `n_eval` subsampling if configured (§7.3).

Connection configuration: Mongo (`MONGO_URI`, `MONGO_DB_NAME`) + BotProbe trace base URL — see [input_schema.md](./input_schema.md) §2.2 and [MONGO_LOOKUP.md](./MONGO_LOOKUP.md).

---

## 5. Atomic unit: Conversation

```
ConversationRecord C = ordered, deduplicated event trace for one session_id
```

### 5.1 Event log structure

Events come from BotProbe `/trace` (normalized ES log documents). Core fields:

| Field | Description |
|-------|-------------|
| `event_type` | Enum (e.g. `LLM_INVOCATION_SUCCESS`, `USER_QUERY`, `TOOL_CALL_RESULT`) |
| `session_id` | Internal voice id (24-char hex) — resolved by BotProbe when UUID passed |
| `request_id` | Turn-level grouping (optional for session events) |
| `timestamp` | Event time (ISO string or datetime after normalization) |
| `content` | Text (user query, bot response, log message) |
| `event_value` | JSON metadata |

### 5.2 Derived structures

| Derived | Source |
|---------|--------|
| Turns | Events grouped by `request_id`, ordered by time |
| Transcript | `USER_QUERY.content` + `RESPONSE.FINAL.content` per turn |
| Session outcome | `SESSION_END`, `CALL_TRANSFER_*`, session status fields |
| Cohort labels | `CANARY_BUCKET_DECISION`, `LLM_INVOCATION_SUCCESS.model_id`, `LLM_CONFIG_RESOLVED` |

### 5.3 ConversationRecord schema

```
ConversationRecord {
  session_id:           string
  scope:                ScopeFilter
  events:               Event[]              // deduplicated
  turns:                Turn[]
  transcript:           TurnTranscript[]
  session_outcome:      Outcome
  blueprint_snapshot?:  VABlueprint          // fetched for tenant; consistent with logs
}
```

### 5.4 Event deduplication

```
EventDeduplicationPolicy {
  key:       (session_id, request_id, event_type, dedupe_dimensions...)
  strategy:  per event_type — first | last | max(field) | sum(field)
}
```

Mandatory before token counts, latency aggregates, and invocation counts. Rules live in `SystemKnowledge.dedup_rules`.

### 5.5 VA Blueprint

Fetched for the scoped tenant/assistant (bot API or Mongo). Used for:

- LLM context in planning
- Label vocabulary for semantic classifiers (skills, tools, transfer rules)
- Deviation checks vs configured intent

Not a substitute for event logs.

---

## 6. Scope, cohorts, and filters

### 6.1 ScopeFilter

```
ScopeFilter {
  tenant?:                 string
  assistant_origin_id?:   string
  assistant_id?:           string
  channel?:                "voice" | "chat"
  date_range:              { start: datetime, end: datetime }
  traffic_split?:          { dimension: string, value: string }

  conversation_predicate?: Predicate    // see §6.2 — narrows which sessions enter D
}
```

**Natural-language examples** (parsed into `conversation_predicate`):

- "main_stream used main_model"
- "guardrails were triggered"
- "Main_Auth skill was active"
- "call transfer happened"
- Composed: `AND(main_stream_model == "main_model", guardrail_triggered, agent_ever == "Main_Auth", transfer_completed)`

In v1, users select **cohort filter chips** in the New Study form; the backend compiles them to `conversation_predicate` via a static filter-atom registry ([input_schema.md](./input_schema.md) §2.3).

### 6.2 Predicate (shared language)

Predicates combine **primitive values** and **cheap classical signal values** (computed on demand for filtering):

```
Predicate ::=
    AND(p1, p2, ...)
  | OR(p1, p2, ...)
  | NOT(p)
  | Comparison(name, op, value)
  | IS_NULL(name)
  | IN(name, value_set)
  | BETWEEN(name, low, high)

ComparisonOp ::= == | != | < | <= | > | >=
```

Operand `name` references a **Primitive** from the catalog or a predefined filter atom.

### 6.3 Two roles for predicates

| Role | When | Purpose | Example |
|------|------|---------|---------|
| **Cohort predicate** | Phase 0 | Define who enters D | "only calls where transfer happened" |
| **Hypothesis predicate** | Phase 3 | Test a claim on D_eval | "early transfer waste pattern" |

Same syntax, different lifecycle. Cohort predicates are optional user/query inputs; hypothesis predicates are LLM-proposed in `AnalysisPlan`.

**Phase 0 filter flow:**

1. Resolve sessions by scope from Mongo (tenant, dates, channel, …)
2. Fetch traces via BotProbe `/trace`; materialize ConversationRecords + dedupe events
3. Compute **minimal primitive set** required by `conversation_predicate`
4. Filter to `D_filtered = { C | conversation_predicate(C) }`
5. Phase 1 sampling and Phase 3 evaluation operate on `D_filtered`

### 6.4 Cohort definitions

```
D = { C | C matches ScopeFilter including conversation_predicate }

ComparativeStudy:
  D_before  — ScopeFilter window W_before
  D_after   — ScopeFilter window W_after
```

---

## 7. User query language

### 7.1 CreateStudyRequest → StudyQuery

The New Study form submits a `CreateStudyRequest` (see [input_schema.md](./input_schema.md)). The backend compiles it to a `StudyQuery` and persists both.

```
StudyQuery ::=
    ComparativeStudy(x?, scope_before, scope_after, config)
  | SingleCohortStudy(x?, scope, config)

x       ::= ChangeDescriptor | null
config  ::= StudyConfig
```

| Query type | `x` | Cohorts |
|------------|-----|---------|
| `ComparativeStudy` | Optional; null = window comparison without attributed cause | `D_before`, `D_after` |
| `SingleCohortStudy` | Optional; null = **pure discovery** | `D` |

Each scope (`scope_before`, `scope_after`, or `scope`) is a full `ScopeFilter` including optional `conversation_predicate`.

**ComparativeStudy UI rule (v1):** Same `tenant`, `assistant_origin_id`, and `channel` for both windows; only date ranges differ.

### 7.2 ChangeDescriptor

```
ChangeDescriptor {
  description:  string
  pr_link?:     string
}
```

Context for planning only. Does **not** fix aspects or hypotheses (no change-type templates). If both fields are empty, `x = null` (pure discovery).

### 7.3 StudyConfig

```
StudyConfig {
  n_explore:           int              // user-configurable; required
  n_eval?:             int | "all"      // default "all"
  n_eval_before?:      int | "all"      // comparative; overrides n_eval for before cohort
  n_eval_after?:       int | "all"      // comparative; overrides n_eval for after cohort

  min_support:         int              // default 30
  min_rate?:           float
  significance_level:  float            // default 0.05

  pairing_turn_tolerance?: int           // δ_turns for comparative pairing; default 3
}
```

**Exploration:**

| Query type | `n_explore` |
|------------|-------------|
| `ComparativeStudy` | Even; yields `n_explore / 2` before/after pairs |
| `SingleCohortStudy` | `n_explore` diverse conversations |

**Evaluation subsampling:**

When `n_eval` (or per-cohort override) is set and `|D| > n_eval`:

- Draw **stratified random sample** preserving `(opening_intent_class, outcome_bucket)` mix
- Default `"all"` uses entire filtered cohort

Hidden v1 defaults (`min_support`, `significance_level`, `pairing_turn_tolerance`) are applied by the backend — not exposed in the UI.

---

## 8. Knowledge injection (not user query)

Three distinct knowledge blocks feed planning and computation. None are entered by the user in v1.

### 8.1 SystemKnowledge

Curated, maintainer-authored platform truth. Injected in Phase 2b and cost/aspect computation.

```
SystemKnowledge {
  instructions:         string[]          // business rules
  price_table?:         Map<model_id, { input_usd, output_usd, thinking_usd? }>
  model_aliases?:       Map<string, string>   // e.g. "main_model" → deployment id
  zero_cost_models?:    string[]          // e.g. ["main_model"] → cost = $0
  event_schema_summary: EventSchemaDoc    // hardcoded catalog for hackathon
  dedup_rules:          EventDeduplicationPolicy
}
```

**Example instructions:**

- "If `model_id == main_model`, treat inference cost as $0 (in-house)."
- "Ignore welcome_message turns for intent classification."
- "`purpose=main_stream` is the primary user-facing response LLM."

Stored in repo config (e.g. `config/system_knowledge.yaml`).

### 8.2 ChangeContext (dynamic)

Resolved from change description and optional PR. Not hardcoded.

```
ChangeContextResolver {
  input:  ChangeDescriptor
  if pr_link:
    fetch diff → LLM summarize affected modules, purposes, event types
  else:
    optional keyword RAG over bot architecture docs (.context/, llm_config.md, …)
  output: ChangeContext {
    summary:              string
    affected_modules?:    string[]
    affected_purposes?:   string[]      // e.g. main_stream, router
    affected_event_types?: string[]
  }
}
```

Injected into Phase 2b as compact summary — never full repo. Written to `intermediate/change_context.json`. Skipped when `x = null`.

### 8.3 VABlueprintSummary

Full blueprint can be huge. For planning:

```
VABlueprintSummary {
  orchestration_type:   string
  skills:               { name, tools[], trigger_hint }[]
  dialog_flow_nodes?:   string[]
  transfer_rules_summary: string
  tool_catalog:           string[]
}
```

Produced by summarizing fetched VA Blueprint for the scoped tenant. Written to `intermediate/blueprint_summary.json`.

---

## 9. Three-layer measurement model

| Layer | Name | Per conversation | Used in |
|-------|------|------------------|---------|
| 0 | **Primitive** | One scalar | Cohort filters, Aspects, (indirectly) Signals |
| 1 | **Signal** | One scalar | Hypotheses (and optionally Aspect components) |
| 2 | **Aspect** | Cohort aggregate | Quantitative analysis (Part 1) |

**Rule:** One Primitive or Signal = exactly one scalar per conversation.

### 9.1 Primitive vs Signal

| | **Primitive** | **Signal** |
|--|---------------|------------|
| Definition | Cataloged, session-level (or simple aggregate) classical extraction | Named computation spec; may be turn-level or semantic |
| Typical use | Cohort filters, aspect components, exploration features | Hypothesis operands |
| Examples | `turn_count`, `main_stream_latency_p95`, `transfer_completed` | `first_transfer_request_turn`, `opening_intent_class`, `user_query_type` |
| ML | Never | ClassicalSignal: never; SemanticSignal: yes |

**ClassicalSignal** (deterministic, not in primitive catalog):

```
ClassicalSignalSpecKind ::=
    turn_index              // first turn where condition holds
  | duration_between        // ms between event A and event B
  | regex_on_transcript     // pattern at turn or session level
  | agent_path_label        // derived path string, e.g. "welcome→Main_Auth→transfer"
  | conditional_metadata    // extract when compound condition holds
```

**SemanticSignal** (LLM/ML):

```
SemanticSignal {
  name:        string
  value_type:  T
  method:      string          // LLM-facing intent, e.g. "intent_classifier", "transfer_detector"
  spec: {
    labels?:           string[]
    description:       string   // what to detect
    prompt_hint?:      string   // optional guidance for executor
    blueprint_refs?:  string[]  // skill/tool names for context
  }
}
```

**Internal implementation** (not in AnalysisPlan — executor chooses):

```
SemanticImplementation ::=
    rule_based(keywords, regex)
  | embedding_nearest_neighbor(prototypes)
  | zero_shot_llm(prompt)
  | small_classifier(model_id)     // RF, XGBoost, etc. — future
  | llm_extract                    // expensive; counter-examples / samples only
```

Clustering (k-means, HDBSCAN) is used in **Phase 1 sampling only**, not as a SemanticSignal method in evaluation.

### 9.2 Cost tiers (execution guidance)

| Tier | What | Scale on D_eval |
|------|------|-----------------|
| Cheap | Primitives, ClassicalSignals | All |
| Medium | SemanticSignal via rules / embed / small classify | All if fast enough |
| Expensive | SemanticSignal via llm_extract | Counter-examples + capped samples |

---

## 10. Layer 0: Primitive catalog

```
Primitive {
  name:        string
  source:      EventSelector
  reducer:     Reducer
  value_type:  int | float | bool | string | null
}

EventSelector {
  event_type:   string | string[]
  filter?:      Predicate on event_value
  scope:        "session" | "turn" | "request"
}

Reducer ::=
    count | sum | mean | p50 | p95 | max | min
  | exists | first | last | distinct_count | time_diff
```

### 10.1 Catalog examples

**Session / outcome:**

| Primitive | Source | Reducer |
|-----------|--------|---------|
| `turn_count` | `USER_QUERY` | count |
| `session_duration_ms` | first → `SESSION_END` | time_diff |
| `main_stream_model` | `LLM_CONFIG_RESOLVED`, purpose=main_stream | `final_model_id` |
| `main_stream_model_invoked` | `LLM_INVOCATION_SUCCESS`, purpose=main_stream | last `model_id` |
| `transfer_completed` | `CALL_TRANSFER_COMPLETED` | exists |
| `guardrail_triggered` | `DEBUG.GUARDRAIL_TRIGGERED` | exists |
| `agent_ever_{name}` | `RESPONSE.FINAL.agent_name` | exists match |
| `interruption_count` | `INTERRUPTION_HANDLER_RESULT` | count |

**LLM / cost (per purpose or main_stream):**

| Primitive | Source | Reducer |
|-----------|--------|---------|
| `{purpose}_latency_p95` | `LLM_INVOCATION_SUCCESS.latency_ms` | p95 |
| `{purpose}_input_tokens_sum` | `TOKEN_USAGE_DETAILS.input_tokens` | sum |
| `{purpose}_estimated_cost_usd` | tokens × SystemKnowledge.price_table | sum |

Apply `zero_cost_models` from SystemKnowledge when computing cost primitives.

**Tools:**

| Primitive | Source | Reducer |
|-----------|--------|---------|
| `tool_invocation_count` | `DEBUG.TOOL_INVOKED` | count |
| `tool_error_count` | `TOOL_CALL_RESULT` error | count |

---

## 11. Layer 1: Signals in hypotheses

```
Signal ::= ClassicalSignal | SemanticSignal

Hypothesis {
  id:           string
  title:        string
  description:  string
  signals:      Signal[]
  predicate:    Predicate          // over signal names
  proof:        ProofSpec
}
```

Composite claims → multiple signals + AND/OR predicate. Never one signal encoding multiple concepts.

### 11.1 Example hypothesis

```
Hypothesis "early_transfer_waste" {
  signals: [
    SemanticSignal    { name: "opening_intent_class", method: "intent_classifier", ... },
    SemanticSignal    { name: "user_query_type", method: "intent_classifier", ... },
    Primitive-as-ref  { name: "turn_count" },
    ClassicalSignal   { name: "first_transfer_request_turn", spec: turn_index(...) },
    ClassicalSignal   { name: "transfer_executed_turn", spec: turn_index(CALL_TRANSFER_COMPLETED) },
    ClassicalSignal   { name: "session_outcome", spec: session_field }
  ]
  predicate: AND(
    user_query_type == "transfer_request",
    first_transfer_request_turn <= 2,
    transfer_executed_turn IS NOT NULL,
    (transfer_executed_turn - first_transfer_request_turn) >= 4,
    turn_count > 4,
    session_outcome IN {"transferred", "abandoned", "timeout"}
  )
}
```

Predicates may reference **primitive catalog names** directly when those primitives are listed in `primitives_required` on the plan.

---

## 12. Layer 2: Aspects (Part 1 — Quantitative)

```
Aspect {
  name:         string
  description:  string
  components:   Component[]
}

Component {
  ref:           Primitive | Signal
  aggregation:   mean | p50 | p95 | sum | rate | count
  weight?:       float
}
```

LLM-proposed from exploration; **not seeded** by change type. Examples: speed, cost, failures, conversation_length, routing, transfer_behavior, interruption.

For `ComparativeStudy`: compute per cohort → delta + significance (§15).

---

## 13. Hypothesis proof (Part 2)

```
ProofSpec {
  metric:              "match_rate" | "match_count" | "cohort_delta"
  min_support:         int              // from StudyConfig
  min_rate?:           float
  significance_test?:  chi_square | fisher | bootstrap_ci | mann_whitney
  significance_level:  float
}

HypothesisResult {
  hypothesis_id:       string
  support_count:       int
  match_rate:          float
  cohort_comparison?:  { rate_before, rate_after, delta, p_value, significant }
  counter_examples:    session_id[]
  rejected:            bool             // support_count < min_support
}
```

**Discovery rules:**

- Fully **LLM-generated** from exploration digests — no change-type templates
- Prompt **examples** allowed
- Do not tune predicates on D_eval
- "Supported" = passes min_support + (if comparative) significant cohort_delta

---

## 14. AnalysisPlan

```
AnalysisPlan {
  study_query:           StudyQuery
  exploration_summary:   string

  quantitative: {
    aspects:             Aspect[]
    suggested_plots:     PlotSpec[]
    suggested_tables:    TableSpec[]
  }

  qualitative: {
    hypotheses:          Hypothesis[]
  }

  primitives_required:   Primitive[]      // union: aspects + cohort + hypothesis refs
  signals_required:      Signal[]         // union: hypotheses + aspect components

  user_approved:         bool             // set true when user clicks Execute on Explore tab
}
```

**v1 approval model:** Phase 2a + 2b run **once** after New Study submission. The Explore tab displays the plan read-only. When the user clicks **Execute plan**, the backend sets `user_approved = true` and runs Phase 3. There is no revision history, feedback loop, or re-run of Phase 2.

---

## 15. Pipeline phases

```
Phase 0:  Cohort Resolution (+ conversation_predicate filter)
Phase 1:  Exploration Sampling → S_explore
Phase 2:  Plan Generation → AnalysisPlan
          Phase 2a: ConversationDigest per sample
          Phase 2b: Plan synthesis (single compact LLM call)
Phase 3:  Evaluation on D_eval → EvaluationResult (requires user_approved)
```

**Invariant:** `S_explore` discovers; `D_eval` measures. Never tune hypotheses on D_eval.

---

### Phase 0: Cohort resolution

```
Input:   StudyQuery
Output:  D | (D_before, D_after) after predicate filter

Steps:
  1. Query Mongo session index by ScopeFilter (tenant, dates, channel, traffic_split)
  2. Fetch full traces via BotProbe /trace per session_id; materialize ConversationRecords
  3. Fetch VA Blueprint → VABlueprintSummary; persist to intermediate/
  4. If ChangeDescriptor set: run ChangeContextResolver; persist to intermediate/
  5. Dedupe events; if conversation_predicate: compute required primitives; filter cohort
  6. Apply n_eval subsampling if configured (stratified; see §7.3)
  7. Write cohort_stats.json
```

---

### Phase 1: Exploration sampling

**Purpose:** Broad, representative sample for hypothesis discovery.

**Exploration features** (computed for every candidate in D):

```
exploration_features(C) = {
  opening_intent_class,      // SemanticSignal / lightweight classifier
  session_outcome,
  turn_count,
  session_duration_ms,
  tool_count,
  interruption_count,
  opening_sentiment?,        // optional cheap classifier
  main_stream_model,
  agent_path_summary,          // ClassicalSignal
  embedding_opening            // SBERT( first non-welcome USER_QUERY )
}
```

#### Stratified grid (primary — no user-supplied k)

1. Define strata: `(opening_intent_class × outcome_bucket × length_bucket)`  
   - `length_bucket`: e.g. short (≤4 turns), medium (5–10), long (>10)
2. For each non-empty stratum, reserve quota proportional to stratum size in D
3. Within stratum: pick medoid (closest to stratum centroid in embedding space) or random if single member
4. Fill `n_explore` slots prioritizing **empty outcome/intent combinations** first (maximize diversity)

#### Within-stratum refinement (optional)

If a stratum has many candidates: mini **HDBSCAN** or k-means with  
`k = min(stratum_size, ceil(sqrt(stratum_size)))` — internal only, not user-facing.

#### Case A: ComparativeStudy

```
Output: S_explore = { (c_before_i, c_after_i) }  i = 1 .. n_explore/2
```

Pairing rules (all required):

- Same `opening_intent_class`
- Same `outcome_bucket` (or both unresolved if comparing quality path)
- `|turn_count(c_before) - turn_count(c_after)| <= pairing_turn_tolerance`
- Minimize embedding distance within same stratum
- Pairs from **different strata** when possible (variety)
- Exclude welcome-only sessions (< 2 turns)

#### Case B: SingleCohortStudy

```
Output: S_explore = { c_i }  i = 1 .. n_explore
```

One sample per stratum until quota filled; farthest-point sampling on embeddings for remainder.

Digests are written under `intermediate/s_explore/`.

---

### Phase 2: Analysis plan generation

#### Phase 2a: ConversationDigest (per sample, parallel)

```
ConversationDigest {
  session_id,
  cohort_label?:           "before" | "after"     // comparative pairs
  opening_intent,
  outcome,
  turn_count,
  duration_ms,
  transcript_digest,       // key turns: first 3, last 2, errors, transfers, interruptions
  notable_events[],        // bullets: "2 tool errors", "3 interruptions", "transfer turn 8"
  anomaly_flags[],         // "empty tool arg", "timeout", "guardrail block"
  primitive_snapshot:      Map<name, value>       // small set of high-signal primitives
}
```

**Never** pass full raw event traces for all samples to Phase 2b.

Optional: attach **2–3 full short transcripts** (shortest, longest, most anomalous in S_explore).

If `n_explore` is very large: batch digests → intermediate theme summary → feed Phase 2b.

#### Phase 2b: Plan synthesis (single LLM call)

**Inputs:**

| Input | Content |
|-------|---------|
| ConversationDigests[] | All samples (compact) |
| Full transcript excerpts | 2–3 bounded |
| EventSchemaDoc | From SystemKnowledge.event_schema_summary |
| VABlueprintSummary | Skills, tools, transfer rules |
| ChangeDescriptor | User text (+ pr_link reference) |
| ChangeContext | From ChangeContextResolver (if applicable) |
| SystemKnowledge | Instructions + cost rules |
| conversation_predicate | If user narrowed cohort |

**Output:** `AnalysisPlan` with `user_approved = false`. Persisted to `intermediate/analysis_plan.json`. Study status → `explored`.

#### Plan approval (v1)

```
On Explore tab:
  1. Display AnalysisPlan (aspects, hypotheses, plots, tables, exploration_summary)
  2. User clicks "Execute plan"
  3. Set user_approved = true; status → running
  4. Run Phase 3
```

No edit, feedback, or re-synthesis in v1. Scope changes require a new study (New Study tab).

---

### Phase 3: Evaluation execution

```
Input:   AnalysisPlan (user_approved == true)
         D_eval from Phase 0 (already subsampled if n_eval set)

Per C in D_eval:
  1. Compute primitives_required
  2. Compute signals_required (Classical + Semantic per implementation tier)
  3. Store { session_id → { primitives, signals } }

Aggregate:
  - Aspects → AspectResult (+ comparative tests)
  - Hypotheses → HypothesisResult (+ counter_examples)

Output: EvaluationResult → output/evaluation_result.json; status → complete
```

```
EvaluationResult {
  study_query,
  analysis_plan,
  cohort_sizes:        { before?, after? } | { single }
  per_conversation:    Map<session_id, { primitives, signals }>
  quantitative:        Map<aspect_name, AspectResult>
  qualitative:         Map<hypothesis_id, HypothesisResult>
  artifacts:           { tables[], plots[], narrative_summary, recommendations? }
}
```

---

## 16. Query modes summary

| Mode | `x` | Query type | Question |
|------|-----|------------|----------|
| Impact before/after | set | `ComparativeStudy` | Did x change aspects / hypothesis rates? |
| Impact single window | set | `SingleCohortStudy` | State after x? |
| Pure discovery | null | `SingleCohortStudy` | What patterns exist? |
| Window comparison | null | `ComparativeStudy` | What changed between windows? |
| Filtered analysis | any + `conversation_predicate` | any | Above, on subset only |

---

## 17. Statistical comparison (ComparativeStudy)

```
AspectResult {
  name, before: { mean, p50, p95, sum, n }, after: { ... },
  delta, delta_pct, test: { name, statistic, p_value, significant }
}
```

| Value type | Test |
|------------|------|
| Continuous | Mann-Whitney U / bootstrap CI |
| Rates | Chi-square / Fisher |
| Counts | Poisson / chi-square |

Hypotheses: `match_rate_before`, `match_rate_after`, `delta`, significance on rates.

---

## 18. Invariants and constraints

1. One scalar per Primitive/Signal per conversation.
2. `S_explore` ≠ `D_eval`; no hypothesis tuning on D_eval.
3. Deduplicate events before primitives.
4. `min_support` gates hypothesis reporting.
5. Blueprint + logs share tenant/assistant scope.
6. `n_explore` and `n_eval` are user-configurable; defaults: required explore size, eval = `"all"`.
7. Hypotheses LLM-generated only; no change-type templates; examples in prompt OK.
8. Comparative pairing requires same `opening_intent_class`.
9. Pure discovery: `SingleCohortStudy` with `x = null`.
10. Transcript derived from events.
11. **Cohort predicate ≠ hypothesis predicate** — same syntax, different phase.
12. **SystemKnowledge** overrides naive cost inference (e.g. main_model = $0).
13. **ChangeContext** from PR/docs — dynamic, not hardcoded.
14. **Phase 3 requires explicit user approval** — `user_approved` set by Execute on Explore tab; no automatic evaluation after Phase 2.
15. **v1 session index is Mongo; event traces are BotProbe `/trace` (ES)** — not Argus Postgres; not Mongo `AssistantEvent`.
16. **v1 persistence is file-based** per study directory; no study artifact database.

---

## 19. Glossary

| Term | Definition |
|------|------------|
| **ConversationRecord** | Deduped events + derived transcript/outcome for one session |
| **conversation_predicate** | Optional Phase 0 filter on primitive/signal values |
| **CreateStudyRequest** | User form payload on New Study tab; compiles to StudyQuery |
| **Primitive** | Cataloged Layer-0 classical scalar per conversation |
| **ClassicalSignal** | Layer-1 deterministic signal (turn-index, regex, duration, …) |
| **SemanticSignal** | Layer-1 ML/LLM signal with method + spec |
| **Aspect** | Layer-2 quantitative composite for cohort aggregation |
| **Hypothesis** | Claim + signals + predicate + proof |
| **SystemKnowledge** | Curated platform rules (cost, semantics, schema) |
| **ChangeContext** | Dynamic summary from PR or docs |
| **ConversationDigest** | Compact Phase-2a sample representation |
| **S_explore** | Exploration sample (`n_explore`) |
| **D_eval** | Evaluation cohort (`n_eval` or all) |
| **Execute** | Explore-tab action that approves plan and starts Phase 3 |
| **VABlueprintSummary** | Compressed blueprint for LLM context |
| **StudyMetadata** | Title, slug, status, timestamps for a saved study |

---

## 20. Document history

| Version | Date | Notes |
|---------|------|-------|
| draft3 | 2026-08-29 | v1 scope: single plan + Execute (no revision loop); 3-tab UI; file-based study persistence; `study_title`; self-contained model |
| draft3.1 | 2026-08-30 | Dual-source data access: Mongo session index + BotProbe `/trace` for events |

---

*Next step (out of scope): output schema, API contracts, executor tool registry, frontend implementation.*