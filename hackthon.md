# Ypervaíno — Formal Model (Draft 2)

**Status:** Modeling, now bound to a concrete data source (va-argus Sessions API). No architecture or implementation details.  
**Scope:** Defines the data objects, query language, analysis types, pipeline phases, and proof criteria for conversation-level impact and discovery analysis over bot event logs.

**Draft 2 change:** Draft 1 assumed direct access to a raw event log (`event_type`/`event_value` per event). Investigation of the `va-argus` repo (the "botprob" Sessions feature) showed no such raw event stream is exposed — only pre-aggregated session/turn/tool-call rows and already-computed signals. §18 defines the resulting Primitive/Signal mapping against the real API. Sections 1–17 below describe the original event-log-based model and are kept as the long-term target shape; §18 is what Phase 3 (Evaluation Execution) actually computes against today.

---

## 1. Purpose

Ypervaíno analyzes virtual-agent conversations at scale to:

1. **Measure impact** of a backend change (model swap, guardrails, interruption handling, prompt change, etc.) via quantitative aspects and hypothesis validation.
2. **Discover patterns** in production traffic without a predefined change descriptor (pure discovery mode).

The system replaces subjective, manual log inspection with a structured pipeline: cohort selection → exploration sampling → LLM-proposed analysis plan → large-scale signal computation → statistical aggregation and proof.

Ground truth is **event logs** (primary) plus **VA Blueprint** (context for the same tenant). Transcripts are derived from events; they are not fetched separately.

---

## 2. Atomic unit: Conversation

Everything operates on one atomic unit:

```
ConversationRecord C = ordered event trace for one session_id
```

### 2.1 Event log structure

Each logged event has:

| Field | Description |
|-------|-------------|
| `event_type` | Enum name (e.g. `LLM_INVOCATION_SUCCESS`, `USER_QUERY`, `TOOL_CALL_RESULT`) |
| `session_id` | Groups all events in one conversation |
| `request_id` | Groups turn-level events (optional for session-level events) |
| `created_at` | Timestamp |
| `content` | Human-readable text (user query, bot response, log message) |
| `event_value` | JSON metadata (model_id, purpose, latency_ms, tokens, tool_name, etc.) |

### 2.2 Derived structures (materialized from events)

| Derived field | Source |
|---------------|--------|
| **Turns** | Group events by `request_id`; order by `created_at` |
| **Transcript** | `USER_QUERY.content` (user) + `RESPONSE.FINAL.content` (bot) per turn |
| **Session outcome** | `SESSION_END`, `CALL_TRANSFER_COMPLETED`, `CALL_TRANSFER_ERROR`, session status fields |
| **Cohort labels** | `CANARY_BUCKET_DECISION`, `LLM_INVOCATION_SUCCESS.model_id` (by purpose), `LLM_CONFIG_RESOLVED.final_model_id` |

### 2.3 ConversationRecord schema

```
ConversationRecord {
  session_id:           string
  scope:                ScopeFilter          // tenant, assistant, channel, date range
  events:               Event[]              // raw, time-ordered, deduplicated
  turns:                Turn[]               // derived
  transcript:           TurnTranscript[]     // derived
  session_outcome:      Outcome              // derived enum
  blueprint_snapshot?:  VABlueprint          // fetched for tenant; same assistant context
}
```

### 2.4 Event deduplication

Logs may emit duplicate events for the same turn (e.g. triple `LLM_INVOCATION_SUCCESS`, `TOKEN_USAGE_DETAILS`, `RESPONSE.FINAL`). Before any computation:

```
EventDeduplicationPolicy {
  key:       (session_id, request_id, event_type, dedupe_dimensions...)
  strategy:  per event_type — first | last | max(field) | sum(field)
}
```

Deduplication is mandatory for token counts, latency aggregates, and invocation counts.

### 2.5 VA Blueprint

For the scoped tenant/assistant, the system fetches **VA Blueprint** (skills, tools, dialog flow graph, instructions, orchestration type). Blueprint and logs are consistent for the same tenant.

Blueprint is used as:

- Context for LLM during exploration and hypothesis generation
- Label/reference vocabulary for semantic classifiers (expected tools, skills, transfer rules)
- Validation of whether observed behavior deviates from configured intent

Blueprint is **not** a substitute for event logs; it enriches interpretation.

---

## 3. Scope and cohorts

### 3.1 ScopeFilter

```
ScopeFilter {
  tenant?:                string
  assistant_origin_id?:  string
  assistant_id?:          string
  channel?:               "voice" | "chat"
  date_range:             { start: datetime, end: datetime }
  traffic_split?:         { dimension: string, value: string }   // e.g. canary variant, model_id
  additional_filters?:    Predicate[]                            // optional event-based pre-filters
}
```

### 3.2 Cohort

A **cohort** is a set of conversations matching a scope:

```
D = { C | C matches ScopeFilter }
```

For comparative studies, two cohorts are resolved:

```
D_before  — conversations in window W_before
D_after   — conversations in window W_after
```

Windows may be defined by calendar date, deploy timestamp, or explicit user-provided cutoffs.

---

## 4. User query language

### 4.1 StudyQuery grammar

```
StudyQuery ::=
    ComparativeStudy(x?, W_before, W_after, S)
  | SingleCohortStudy(x?, W, S)

x  ::= ChangeDescriptor | null          // null → pure discovery mode
S  ::= StudyConfig                      // sampling and evaluation parameters
```

| Query type | Change descriptor `x` | Cohorts |
|------------|-------------------------|---------|
| `ComparativeStudy` | Optional. When present, frames impact analysis. When null, compares two windows without attributing cause. | `D_before`, `D_after` |
| `SingleCohortStudy` | Optional. When null → **pure discovery mode** (pattern mining only). | `D` |

### 4.2 ChangeDescriptor

```
ChangeDescriptor {
  description:  string          // free-text: what changed
  pr_link?:     string          // optional PR/MR URL for additional context
}
```

The change descriptor is **context** for analysis planning. It does not fix which aspects or hypotheses are produced. The LLM proposes those from exploration samples only (see §8).

Examples:

- `"Moved 10% Resound traffic to Qwen for main_stream"`
- `"Input guardrails M2 enabled on 2026-08-10"`
- `"Interruption checkpoint fix deployed 2026-08-24"`
- `null` — pure discovery

### 4.3 StudyConfig

```
StudyConfig {
  n_explore:        int           // user-configurable exploration sample size
  N_eval?:           int | "all"  // evaluation cohort size; default "all"
  min_support:       int           // minimum conversations matching a hypothesis to report (default: 30)
  min_rate?:         float         // minimum match rate to report (optional)
  significance_level: float        // default: 0.05
}
```

**Exploration sample size `n_explore`:**

| Query type | Constraint |
|------------|------------|
| `ComparativeStudy` | `n_explore` must be even; yields `n_explore / 2` before/after pairs |
| `SingleCohortStudy` | `n_explore` diverse conversations |

`n_explore` is always user-configurable.

---

## 5. Three-layer measurement model

All per-conversation measurements use three layers. Naming is fixed:

| Layer | Name | Cardinality | Used in |
|-------|------|-------------|---------|
| 0 | **Primitive** | One scalar per conversation | Aspects, Signals |
| 1 | **Signal** | One scalar per conversation | Hypotheses |
| 2 | **Aspect** | Aggregate over cohort | Quantitative analysis (Part 1) |

**Rule:** One Primitive or Signal = exactly one scalar value per conversation. Multi-concept claims use multiple Signals + a Predicate.

---

## 6. Layer 0: Primitives

A **Primitive** is atomic and directly derived from event logs (classical only).

```
Primitive {
  name:        string
  source:      EventSelector
  reducer:     Reducer
  value_type:  int | float | bool | string | null
}

EventSelector {
  event_type:   string | string[]
  filter?:      Predicate on event_value fields
  scope:        "session" | "turn" | "request"
}

Reducer ::=
    count | sum(field) | mean(field) | p50(field) | p95(field) | max(field) | min(field)
  | exists | first(field) | last(field) | distinct_count(field)
```

### 6.1 Example primitives (from event catalog)

**Session-level:**

| Primitive | EventSelector | Reducer |
|-----------|---------------|---------|
| `turn_count` | `USER_QUERY` | count |
| `session_duration_ms` | first event → `SESSION_END` | time diff |
| `canary_is_control` | `CANARY_BUCKET_DECISION` | `is_control` |
| `canary_variant_key` | `CANARY_BUCKET_DECISION` | `selected_variant_key` |
| `main_stream_model` | `LLM_CONFIG_RESOLVED` where `purpose=main_stream` | `final_model_id` |
| `session_end_reason` | `SESSION_END` | `content` |
| `transfer_completed` | `CALL_TRANSFER_COMPLETED` | exists |
| `interruption_count` | `INTERRUPTION_HANDLER_RESULT` | count |
| `interruption_merged_count` | `INTERRUPTION_HANDLER_RESULT` where `was_merged=true` | count |

**Per-purpose LLM (parameterized by `purpose`):**

| Primitive | Source field | Reducer |
|-----------|--------------|---------|
| `{purpose}_invocation_count` | `LLM_INVOCATION_SUCCESS` | count |
| `{purpose}_latency_p95` | `latency_ms` | p95 |
| `{purpose}_fallback_count` | `is_fallback=true` | count |
| `{purpose}_input_tokens_sum` | `TOKEN_USAGE_DETAILS.input_tokens` | sum |
| `{purpose}_output_tokens_sum` | `TOKEN_USAGE_DETAILS.output_tokens` | sum |
| `{purpose}_throughput_mean` | `LLM_STREAMING_THROUGHPUT.throughput_tokens_per_sec` | mean |
| `{purpose}_estimated_cost_usd` | tokens × price table | sum |

**Tools:**

| Primitive | Source | Reducer |
|-----------|--------|---------|
| `tool_invocation_count` | `DEBUG.TOOL_INVOKED` | count |
| `tool_error_count` | `TOOL_CALL_RESULT` with error | count |
| `tool_latency_p95` | `TOOL_CALL_RESULT.latency` | p95 |
| `tool_names_used` | `DEBUG.TOOL_INVOKED.name` | distinct set |

**Guardrails:**

| Primitive | Source | Reducer |
|-----------|--------|---------|
| `guardrail_check_count` | `GUARDRAIL_CHECK` | count |
| `guardrail_triggered` | `DEBUG.GUARDRAIL_TRIGGERED` | exists |

---

## 7. Layer 1: Signals

A **Signal** is one scalar per conversation, possibly requiring computation beyond raw metadata extraction. Signals are the building blocks of **Hypotheses** (Part 2).

```
Signal {
  name:        string
  mode:        Mode
  value_type:  T
  spec:        ModeSpec
}
```

### 7.1 Mode hierarchy

```
Mode ::= ClassicalMode | SemanticMode
```

#### ClassicalMode

Deterministic extraction from events or derived transcript. No ML inference.

```
ClassicalModeKind ::=
    event_exists
  | metadata_get          // json path into event_value
  | event_count
  | turn_index            // first turn where condition holds
  | duration
  | aggregate             // reducer over event subset
  | regex_match           // pattern on transcript text
  | session_field         // from session metadata / outcome
```

#### SemanticMode

Requires NLP / ML / LLM inference on transcript or turn sequence.

```
SemanticModeKind ::=
    classify              // label from text (intent, outcome quality, ...)
  | embed_similarity      // match against reference phrases / embeddings
  | sentiment
  | topic_label
  | llm_extract           // structured extraction via LLM (expensive; restricted use)
  | sequence_pattern      // pattern over turn sequence
```

**Cost tiers (for later implementation guidance):**

| Tier | Modes | Scale |
|------|-------|-------|
| Cheap | All ClassicalMode | All N conversations in D_eval |
| Medium | classify, embed_similarity, regex, sentiment | All N if model is lightweight |
| Expensive | llm_extract | Counter-examples and small samples only |

### 7.2 Signal constraints

1. One signal → one scalar per conversation.
2. Signal names are unique within a Hypothesis.
3. Composite concepts (e.g. "early transfer waste") decompose into multiple signals + predicate.
4. Semantic signals may use VA Blueprint for label definitions and pattern vocabulary.

---

## 8. Layer 2: Aspects (Quantitative analysis — Part 1)

An **Aspect** is a human-understandable summary dimension composed of one or more Primitives (and optionally Signals). Aspects are used only in **Quantitative Analysis**.

```
Aspect {
  name:         string              // e.g. "speed", "cost", "failures"
  description:  string
  components:   Component[]
}

Component {
  ref:           Primitive | Signal
  aggregation:   mean | p50 | p95 | sum | rate | count
  weight?:       float                // optional, for composite scoring
}
```

### 8.1 Standard aspect families

These are **examples** of aspect shapes the LLM may propose — not fixed templates seeded into the system:

| Aspect family | Typical components |
|---------------|-------------------|
| **speed** | main_stream latency p95, TTFT p95, throughput mean |
| **cost** | input/output/thinking tokens sum, estimated USD by purpose |
| **conversation_length** | turn_count, session_duration_ms |
| **failures** | tool_error_count, guardrail blocks, fallback count, session timeout |
| **routing** | skill distribution, wrong-skill rate (semantic signal) |
| **transfer_behavior** | transfer rate, turns-before-transfer, early-transfer rate |
| **interruption** | interruption_count, recovery rate, merged-query rate |

Aspects are **LLM-proposed** from exploration samples and change context. The system does not pre-seed aspect lists by change type.

For `ComparativeStudy`, each aspect is computed for both cohorts and compared (delta, ratio, statistical test).

---

## 9. Hypotheses (Qualitative analysis — Part 2)

Part 2 is **hypothesis-driven pattern validation** at scale. It is not manual qualitative review. Hypotheses are discovered from exploration samples and then tested statistically on the full evaluation cohort.

### 9.1 Hypothesis schema

```
Hypothesis {
  id:           string
  title:        string
  description:  string                    // natural-language claim

  signals:      Signal[]                  // all signals that must be computed

  predicate:    Predicate                 // filter over signal values

  proof:        ProofSpec
}
```

### 9.2 Predicate

Predicates combine signal values with logical and comparison operators:

```
Predicate ::=
    AND(p1, p2, ...)
  | OR(p1, p2, ...)
  | NOT(p)
  | Comparison(signal_name, op, value)
  | IS_NULL(signal_name)
  | IN(signal_name, value_set)
  | BETWEEN(signal_name, low, high)

ComparisonOp ::= == | != | < | <= | > | >=
```

### 9.3 Example hypothesis (formal)

**Claim:** User asks for transfer early; bot attempts resolution; fails; transfer or abandon after wasted turns.

```
Hypothesis {
  id: "early_transfer_waste"
  title: "Early transfer request wasted on attempted resolution"

  signals: [
    { name: "opening_intent_class",     mode: SemanticMode(classify),     value_type: label },
    { name: "user_query_type",          mode: SemanticMode(classify),     value_type: label },
    { name: "turn_count",               mode: ClassicalMode(event_count), value_type: int },
    { name: "first_transfer_request_turn", mode: SemanticMode(classify),  value_type: int|null },
    { name: "transfer_executed_turn",   mode: ClassicalMode(turn_index),  value_type: int|null },
    { name: "session_outcome",          mode: ClassicalMode(session_field), value_type: enum }
  ]

  predicate:
    user_query_type == "transfer_request"
    AND first_transfer_request_turn <= 2
    AND transfer_executed_turn IS NOT NULL
    AND (transfer_executed_turn - first_transfer_request_turn) >= 4
    AND turn_count > 4
    AND session_outcome IN {"transferred", "abandoned", "timeout"}

  proof: { ... see §9.4 }
}
```

### 9.4 ProofSpec

A hypothesis is **supported** when statistical and practical criteria are met:

```
ProofSpec {
  metric:            "match_rate" | "match_count" | "cohort_delta"
  min_support:       int              // from StudyConfig; default 30
  min_rate?:          float            // optional minimum match rate
  significance_test?: chi_square | fisher | bootstrap_ci | mann_whitney
  significance_level: float            // default 0.05
}
```

**Proof outputs per hypothesis:**

```
HypothesisResult {
  hypothesis_id:     string
  support_count:     int               // |{ C in D_eval : predicate(C) }|
  match_rate:        float             // support_count / |D_eval|
  cohort_comparison?: {                // ComparativeStudy only
    rate_before:      float
    rate_after:       float
    delta:            float
    p_value:          float
    significant:      bool
  }
  counter_examples:  session_id[]      // sample of matching conversations for drill-down
  rejected:          bool              // true if support_count < min_support
}
```

**Rules:**

- Matching the predicate on 3 of 10,000 conversations is technically true but **rejected** if below `min_support`.
- Hypothesis predicates must not be tuned on `D_eval` (overfitting). Exploration uses `S_explore` only.
- "Proved" means statistically significant and practically meaningful — not universal truth.

### 9.5 Hypothesis discovery

Hypotheses are **fully LLM-generated** from exploration samples (`S_explore`), change descriptor (if any), transcript excerpts, key events, and VA Blueprint.

- No fixed change-type templates seeded into the system.
- Prompt may include **examples** of hypothesis shape for guidance.
- The LLM proposes aspects, hypotheses, predicates, and required signals in the **AnalysisPlan** (§10).

---

## 10. AnalysisPlan

Output of the exploration + planning phase. User approves before large-scale execution.

```
AnalysisPlan {
  study_query:           StudyQuery
  exploration_summary:   string           // LLM narrative of what was observed in S_explore

  quantitative: {
    aspects:             Aspect[]
    suggested_plots:     PlotSpec[]
    suggested_tables:    TableSpec[]
  }

  qualitative: {
    hypotheses:          Hypothesis[]
  }

  signals_required:      Signal[]         // union of all signals from hypotheses + aspect components
  primitives_required:   Primitive[]      // union of all primitives referenced
}
```

Plot and table specs are declarative (axes, cohorts, aspect/hypothesis references) — rendering is out of scope for this document.

---

## 11. Pipeline phases

```
Phase 0: Cohort Resolution
Phase 1: Exploration Sampling
Phase 2: Analysis Plan Generation (LLM)
Phase 3: Evaluation Execution (at scale)
```

Strict separation: **S_explore** is for discovery only; **D_eval** is for measurement only.

### Phase 0: Cohort resolution

```
Input:   StudyQuery
Output:  D          (SingleCohortStudy)
      or D_before, D_after   (ComparativeStudy)

Action: Query event store / session index by ScopeFilter.
        Materialize ConversationRecord for each session_id.
        Fetch VA Blueprint for tenant/assistant.
        Apply EventDeduplicationPolicy.
```

### Phase 1: Exploration sampling

**Purpose:** Select a small, representative sample for LLM inspection — mimicking how a human reads a few conversations before designing an analysis.

**Input:** Cohort(s), `n_explore` from StudyConfig

#### Case A: ComparativeStudy

```
Input:   D_before (|D_before| >= n_explore)
         D_after  (|D_after|  >= n_explore)
Output:  S_explore = { (c_before_i, c_after_i) }  for i = 1 .. n_explore/2
```

**Algorithm:**

1. **Embed** each conversation → vector `e(C)`:
   - Semantic component: SBERT embedding of opening user query (or mean of turn texts)
   - Structural component: normalized `[turn_count, duration, tool_count, interruption_count, ...]`
   - Combined: `concat(semantic, structural)`

2. **Classify opening intent** for every conversation → `opening_intent_class(C)` (semantic classifier).

3. **Cluster** `D_before` → clusters `B = {B_1, ..., B_m}`  
   **Cluster** `D_after` → clusters `A = {A_1, ..., A_m}`

4. **Pair selection** — for each cluster index `j` (iterate until `n_explore/2` pairs):
   - Pick `(c_b, c_a)` minimizing `distance(e(c_b), e(c_a))`
   - **Constraints (all required):**
     - `opening_intent_class(c_b) == opening_intent_class(c_a)`
     - `|turn_count(c_b) - turn_count(c_a)| <= δ_turns` (configurable tolerance)
     - Same `assistant_origin_id` (implicit from scope)
   - Each pair from a **different cluster** to maximize variety

5. Exclude sessions with fewer than 2 turns (welcome-only) from pairing pool.

#### Case B: SingleCohortStudy

```
Input:   D (|D| >= n_explore)
Output:  S_explore = { c_i }  for i = 1 .. n_explore
```

**Algorithm:**

1. Embed + cluster `D` → clusters `{C_1, ..., C_m}`, `m >= n_explore`
2. Select one conversation per cluster (medoid or centroid-nearest)
3. If `m < n_explore`, use farthest-point sampling on embeddings for remaining slots
4. Maximize cluster spread (diverse intents, outcomes, lengths)

### Phase 2: Analysis plan generation

```
Input:   S_explore (full ConversationRecords: events, transcript, key primitives)
         ChangeDescriptor x (optional)
         VA Blueprint
Output:  AnalysisPlan

Action:  LLM inspects samples.
         Proposes aspects (Part 1), hypotheses with signals and predicates (Part 2).
         Proposes plots and tables.
         User reviews and approves (or iterates).
```

No seeding from change-type templates. Examples in the LLM prompt are permitted.

### Phase 3: Evaluation execution

```
Input:   AnalysisPlan (approved)
         D_eval = D or (D_before, D_after), size N or "all"
Output:  EvaluationResult
```

**Per conversation** `C in D_eval`:

1. Compute all required **Primitives** (Layer 0)
2. Compute all required **Signals** (Layer 1)
3. Store `{ session_id → { primitives, signals } }`

**Aggregate:**

- **Quantitative:** For each Aspect, compute cohort-level aggregates (mean, p95, sum, rate). For ComparativeStudy, compute delta and significance.
- **Qualitative:** For each Hypothesis, evaluate predicate → HypothesisResult.

```
EvaluationResult {
  study_query:        StudyQuery
  analysis_plan:      AnalysisPlan
  cohort_sizes:       { before?: int, after?: int } | { single: int }

  per_conversation:   Map<session_id, { primitives, signals }>

  quantitative: {
    aspects:          Map<aspect_name, AspectResult>
  }

  qualitative: {
    hypotheses:       Map<hypothesis_id, HypothesisResult>
  }

  artifacts:          { tables[], plots[], narrative_summary }
}
```

---

## 12. Query modes summary

| Mode | x (change) | Query type | Primary question |
|------|------------|------------|------------------|
| Impact (before/after) | Provided | `ComparativeStudy` | Did change x affect aspects H1..Hn? Are hypotheses more/less frequent after? |
| Impact (single window) | Provided | `SingleCohortStudy` | What is the state of aspects after change x? What patterns exist? |
| Pure discovery | null | `SingleCohortStudy` | What hidden patterns exist in this traffic? |
| Window comparison (no attribution) | null | `ComparativeStudy` | What changed between these two windows? |

---

## 13. Supported change domains (non-exhaustive)

The model supports any change expressible in `ChangeDescriptor`. Common domains from team work (not fixed templates):

| Domain | Example x | Likely primitives | Likely hypothesis themes |
|--------|-----------|-------------------|--------------------------|
| Main model swap | Qwen 10% for main_stream | latency, tokens, cost, tool errors | auth failures, empty tool args, quality regression |
| CQ / router model | In-house model for contextual_query | CQ latency, skill routing distribution | wrong skill, bad rewrites |
| Guardrails | Input guardrails M2 enabled | guardrail_check count, block rate | false positives, latency added |
| Interruption handling | Checkpoint fix deployed | interruption_count, recovery rate | repeat prompts, call drops mid-auth |
| Prompt change | Router system prompt updated | skill distribution, escalation rate | new failure modes |
| Language switching | Multilingual embedding rollout | query_language distribution | wrong-language responses |
| Backend optimization | Session affinity, caching | cache_hit rate, latency | no behavioral change expected |

The LLM discovers specific aspects and hypotheses from data — this table is documentation only.

---

## 14. Statistical comparison (ComparativeStudy)

For each **Aspect** across cohorts:

```
AspectResult {
  name:           string
  before:         { mean, p50, p95, sum, n }
  after:          { mean, p50, p95, sum, n }
  delta:          float
  delta_pct:      float
  test:           { name, statistic, p_value, significant }
}
```

Test selection by value type:

| Value type | Recommended test |
|------------|------------------|
| Continuous (latency, tokens) | Mann-Whitney U or bootstrap CI |
| Rates (error rate, match rate) | Chi-square or Fisher's exact |
| Counts | Poisson or chi-square |

For each **Hypothesis**:

- `match_rate_before`, `match_rate_after`, `delta`, significance test on rates.

---

## 15. Invariants and constraints

1. **One scalar per Primitive/Signal per conversation.** No combined values.
2. **S_explore ≠ D_eval.** Exploration discovers; evaluation measures. Do not tune on D_eval.
3. **Deduplicate events** before any primitive computation.
4. **min_support** gates hypothesis reporting.
5. **Blueprint + logs** refer to the same tenant/assistant scope.
6. **n_explore** is user-configurable.
7. **Hypothesis discovery** is fully LLM-generated; no seeded change-type templates.
8. **Comparative pairing** requires matching `opening_intent_class`.
9. **Pure discovery** is valid: `SingleCohortStudy` with `x = null`.
10. **Transcript is derived** from `USER_QUERY` and `RESPONSE.FINAL` events, not separately stored.

---

## 16. Glossary

| Term | Definition |
|------|------------|
| **ConversationRecord** | One session's deduplicated events + derived transcript and outcome |
| **Cohort (D)** | Set of ConversationRecords matching ScopeFilter |
| **Primitive** | Layer 0; atomic log-derived scalar per conversation |
| **Signal** | Layer 1; computed scalar per conversation (classical or semantic) |
| **Aspect** | Layer 2; human-named quantitative measure composed of primitives/signals |
| **Hypothesis** | Claim + signals + predicate + proof spec |
| **Predicate** | Boolean filter over signal values for one conversation |
| **S_explore** | Small sample for LLM exploration (`n_explore`) |
| **D_eval** | Full cohort for statistical evaluation (`N` or all) |
| **AnalysisPlan** | LLM-proposed aspects, hypotheses, plots — user-approved |
| **EvaluationResult** | Final quantitative + qualitative outputs |
| **ChangeDescriptor** | Free-text change + optional PR link; may be null |
| **VA Blueprint** | Assistant config snapshot (skills, tools, flow, instructions) |

---

## 17. Data source binding — va-argus Sessions API

**Status:** This section grounds §6 (Primitives) and §7 (Signals) in the actual data available today, via the `va-argus` repo's Sessions feature (internally called "botprob"). No raw event log is available; everything here is pre-aggregated.

### 17.1 Source endpoints

| Endpoint | Backing table(s) | Provides |
|----------|-------------------|----------|
| `GET /api/v1/sessions` | `AssistantSession` | Filterable session list |
| `GET /api/v1/sessions/{id}` | `AssistantSession` | Full session detail |
| `GET /api/v1/sessions/{id}/transcript` | `VoiceTurnMetric`, `ToolCall` | Turns + tool calls |
| `GET /api/v1/sessions/{id}/voice-metrics` | `VoiceTurnMetric` | Turn-level metrics only |
| `GET /api/v1/sessions/{id}/signals` | `ConversationSignals`, `ConversationClassification` | Pre-computed signals + RED/YELLOW/GREEN |

### 17.2 Revised Primitives (replaces §6.1 examples where unavailable)

**Session-level** (`AssistantSession`):

| Primitive | Field |
|-----------|-------|
| `session_duration_secs` | `duration_secs` |
| `is_active` | `is_active` |
| `resolution_status` | `resolution_status` |
| `escalation_status` | `escalation_status` |
| `abandonment_status` | `abandonment_status` |
| `disconnected_by` | `session_disconnected_by` |
| `reconnect_count` | `voice_session_reconnects` |
| `assistant_version` | `assistant_version` — doubles as a natural cohort-split key for `ComparativeStudy` when no explicit deploy timestamp is given |

**Turn-level** (`VoiceTurnMetric`, via `/transcript` or `/voice-metrics`):

| Primitive | Reducer |
|-----------|---------|
| `turn_count` | count of turns |
| `e2e_latency_p95` | p95(`e2e_latency`) |
| `llm_ttft_p95` | p95(`llm_node_ttft`) |
| `tts_ttfb_p95` | p95(`tts_node_ttfb`) |
| `transcript_confidence_mean` | mean(`transcript_confidence`) |
| `interruption_count` | count where `interrupted = true` |

**Tool-call-level** (`ToolCall`, via `/transcript`):

| Primitive | Reducer |
|-----------|---------|
| `tool_invocation_count` | count |
| `tool_error_count` | count where `error IS NOT NULL` |
| `tool_names_used` | distinct(`tool_name`) |

**Pre-computed** (`ConversationSignals` / `ConversationClassification`, via `/signals`):

| Primitive | Field |
|-----------|-------|
| `classification` | RED / YELLOW / GREEN — treat as a first-class Signal, not just a label |
| `matched_rule_name`, `matched_rules` | Which classification rule(s) fired |
| `signals.*` | Every column already computed by va-argus's signal engine (acoustic, LLM-judge, session-data, custom) — pass through as Primitives without recomputation |

### 17.3 What is dropped from §6.1 (not available from this source)

`LLM_INVOCATION_SUCCESS` counts, `TOKEN_USAGE_DETAILS` (tokens/cost), `CANARY_BUCKET_DECISION`, `GUARDRAIL_CHECK`/`GUARDRAIL_TRIGGERED`, `INTERRUPTION_HANDLER_RESULT` (merged-query detail). These require a raw per-event stream that va-argus does not store or expose. If needed later, they would have to come from a separate raw event source (the bot repo's own log, not va-argus) — out of scope for this draft.

### 17.4 Impact on Layer 1 (Signals) and Layer 2 (Aspects)

- **Semantic Signals** (§7.1, `classify`/`sentiment`/`sequence_pattern`) still work as designed — they run on `turns[].text` (the transcript), which va-argus does provide in full.
- **VA Blueprint** (§2.5) is still available and richer than expected: `blueprint_cache.json` already holds fetched blueprints for 98 assistants, plus a live fetch path (`signals/signal_types/llm_judge/blueprint.py`). No change needed to §2.5/§9.5.
- **Aspects** (§8.1) should be re-derived from the §17.2 primitives, e.g.: `speed` = {`e2e_latency_p95`, `llm_ttft_p95`, `tts_ttfb_p95`}; `failures` = {`tool_error_count`, `classification = RED` rate}; `conversation_length` = {`turn_count`, `session_duration_secs`}; `interruption` = {`interruption_count`}. `cost` (token-based) is not computable under this binding — drop or replace with a proxy if one is found later.

---

## 18. Document history

| Version | Date | Notes |
|---------|------|-------|
| draft1 | 2026-08-28 | Initial formal model. Modeling only. Incorporates Signal/Aspect/Primitive naming, user-configurable n_explore, LLM-only hypothesis discovery, opening-intent pairing, pure discovery mode, blueprint consistency, deduplication, min_support proof criteria. |
| draft2 | 2026-08-28 | Bound the model to the actual `va-argus` Sessions API (§17): no raw event log available, so Primitives/Signals were redefined against pre-aggregated session/turn/tool-call/signal data. Confirmed VA Blueprint is already fetchable/cached in va-argus. Dropped token/cost and raw-event-specific primitives as unavailable under this binding. |

---

*Next step (out of scope for draft2): UI design (what to ask/show/how), system architecture, and final implementation on top of the trimmed va-argus Sessions module.*