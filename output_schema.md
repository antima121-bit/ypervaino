# Ypervaíno — Output Schema (v1)

**Source of truth (model):** [problem_statement_modelling.md](./problem_statement_modelling.md)  
**Implementation:** [architecture.md](./architecture.md)  
**User inputs:** [input_schema.md](./input_schema.md)  
**UI consumption:** [UI_design.md](./UI_design.md)

JSON shapes for every artifact the pipeline **writes**. User-facing inputs are in `input_schema.md`; this document covers intermediates, the analysis plan, and evaluation results.

**Conventions**

- `datetime` — ISO 8601 string  
- `session_id` — BotProbe / AssistantSession UUID unless noted  
- Maps in prose become JSON objects keyed by string id  
- Optional fields marked with `?`  
- File paths are relative to `studies/{slug}/`

---

## 1. File index

| Path | Phase | Schema section |
|------|-------|----------------|
| `meta.json` | all | §2 StudyMetadata |
| `input/create_study.json` | submit | [input_schema.md](./input_schema.md) §1.4 (input, not output) |
| `input/study_query.json` | submit | §3 StudyQuery (compiled) |
| `cache/intent_lexicon.json` | 0 | §4 IntentLexicon |
| `cache/features/{session_id}.json` | 0+ | §5 FeatureVector |
| `intermediate/cohort_stats.json` | 0 | §6 CohortStats |
| `intermediate/blueprint_summary.json` | 0 | §7 VABlueprintSummary |
| `intermediate/change_context.json` | 0 | §8 ChangeContext |
| `intermediate/s_explore/manifest.json` | 1 | §9 ExplorationManifest |
| `intermediate/s_explore/{session_id}.digest.json` | 2a | §10 ConversationDigest |
| `intermediate/analysis_plan.json` | 2b | §11 AnalysisPlan |
| `intermediate/timing.jsonl` | all | §12 TimingLogEntry (append-only) |
| `output/evaluation_result.json` | 3 | §13 EvaluationResult |
| `output/per_conversation/{shard}.json` | 3 | §14 PerConversationShard |
| `output/plots/{id}.png` | 3 | binary; registered in §13 |
| `output/tables/{id}.csv` | 3 | binary; registered in §13 |

---

## 2. StudyMetadata

**File:** `meta.json`  
**Updated by:** StudyRunner on every status transition.

```typescript
StudyMetadata {
  title:       string
  slug:        string
  created_at:  datetime
  updated_at:  datetime
  status:      "created" | "explored" | "running" | "complete" | "failed"
  error?:      string              // set when status == "failed"
}
```

```json
{
  "title": "Resound Qwen 10% Aug 20-22",
  "slug": "resound-qwen-10-aug-20-22",
  "created_at": "2026-08-22T10:00:00+05:30",
  "updated_at": "2026-08-22T10:04:12+05:30",
  "status": "explored"
}
```

---

## 3. StudyQuery

**File:** `input/study_query.json` (compiled from `CreateStudyRequest`)  
**Embedded in:** `AnalysisPlan.study_query`, `EvaluationResult.study_query`

```typescript
StudyQuery =
  | { type: "comparative"; change: ChangeDescriptor | null; scope_before: ScopeFilter; scope_after: ScopeFilter; config: StudyConfig }
  | { type: "single_cohort"; change: ChangeDescriptor | null; scope: ScopeFilter; config: StudyConfig }

ChangeDescriptor {
  description: string
  pr_link?:    string | null
}

ScopeFilter {
  tenant:                   string
  assistant_origin_id:      string
  assistant_id?:            string | null
  channel:                  "voice" | "chat"
  date_range:               DateTimeRange
  traffic_split?:           TrafficSplit | null
  conversation_predicate?:  Predicate | null   // compiled from cohort_filters
}

DateTimeRange { start: datetime; end: datetime }

TrafficSplit { dimension: string; value: string }

StudyConfig {
  n_explore:                integer
  n_eval?:                  integer | "all"
  n_eval_before?:           integer | "all"    // comparative only
  n_eval_after?:            integer | "all"    // comparative only
  min_support:              integer            // default 30
  min_rate?:                number | null
  significance_level:       number             // default 0.05
  pairing_turn_tolerance?:  integer            // default 3
}
```

---

## 4. IntentLexicon

**File:** `cache/intent_lexicon.json`  
**Produced by:** IntentLexiconBuilder (Phase 0)

```typescript
IntentLexicon {
  version:  string
  intents:  { [intent_id: string]: IntentSignature }
}

IntentSignature {
  label:               string
  description:         string
  skills:              string[]
  nodes:               string[]
  tools:               string[]
  agent_names:         string[]
  event_type_hints:    string[]
  keywords:            string[]
  purposes:            string[]
  negative_keywords?:  string[]
}
```

---

## 5. FeatureVector

**File:** `cache/features/{session_id}.json`  
**Produced by:** FeatureComputer (Phase 0+)

```typescript
FeatureVector {
  session_id:            string
  events_fingerprint:    string
  computed_at:           datetime

  turn_count:            integer
  session_duration_ms:   integer
  session_outcome:       string
  main_stream_model:     string | null
  tool_invocation_count: integer
  tool_error_count:      integer
  transfer_completed:    boolean
  guardrail_triggered:   boolean
  interruption_count:    integer
  agent_path:            string

  opening_intent_class:  string
  opening_intent_score:  number
  outcome_bucket:        string
  length_bucket:         "short" | "medium" | "long"
  embedding_opening:     number[]           // SBERT dim (e.g. 384)

  searchable_text:       string
  matched_tokens:        string[]
  structured_hits: {
    agent_names:         string[]
    tool_names:          string[]
    skill_names:         string[]
    node_names:          string[]
    purposes:            string[]
    event_types_seen:    string[]
  }
}
```

---

## 6. CohortStats

**File:** `intermediate/cohort_stats.json`  
**Produced by:** CohortResolver (Phase 0)

```typescript
CohortStats {
  study_type:     "comparative" | "single_cohort"
  resolved_at:    datetime

  // counts after scope + conversation_predicate, before n_eval subsample
  cohort_sizes:   ComparativeCohortSizes | SingleCohortSizes

  // session ids selected for Phase 3 evaluation
  d_eval_ids:     ComparativeEvalIds | SingleEvalIds

  n_explore:      integer
  filter_counts?: {
    candidates_from_index:  integer
    after_predicate:        integer
    after_n_eval_subsample: integer
  }
}

ComparativeCohortSizes { before: integer; after: integer }
SingleCohortSizes      { single: integer }

ComparativeEvalIds { before: string[]; after: string[] }
SingleEvalIds      { single: string[] }
```

```json
{
  "study_type": "comparative",
  "resolved_at": "2026-08-22T10:01:00+05:30",
  "cohort_sizes": { "before": 1842, "after": 1901 },
  "d_eval_ids": { "before": ["uuid-1", "..."], "after": ["uuid-2", "..."] },
  "n_explore": 100,
  "filter_counts": {
    "candidates_from_index": 2100,
    "after_predicate": 3743,
    "after_n_eval_subsample": 5000
  }
}
```

---

## 7. VABlueprintSummary

**File:** `intermediate/blueprint_summary.json`  
**Produced by:** BlueprintFetcher (Phase 0)

```typescript
VABlueprintSummary {
  orchestration_type:      string
  skills:                  SkillSummary[]
  dialog_flow_nodes?:      string[]
  transfer_rules_summary:  string
  tool_catalog:            string[]
}

SkillSummary {
  name:          string
  tools:         string[]
  trigger_hint?: string
}
```

---

## 8. ChangeContext

**File:** `intermediate/change_context.json`  
**Produced by:** ChangeContextResolver (Phase 0, when change fields set)  
**Absent when:** `change` is null (pure discovery / window comparison without descriptor).

```typescript
ChangeContext {
  summary:                string
  mr_title?:              string
  mr_auto_summary?:       string
  affected_modules?:      string[]
  affected_purposes?:     string[]
  affected_event_types?:  string[]
}
```

---

## 9. ExplorationManifest

**File:** `intermediate/s_explore/manifest.json`  
**Produced by:** ExplorationSampler (Phase 1)

```typescript
ExplorationManifest {
  n_explore:     integer
  study_type:    "comparative" | "single_cohort"
  sampled_at:    datetime

  // comparative: paired samples
  pairs?:        { before_session_id: string; after_session_id: string }[]

  // single cohort: flat list
  session_ids?:  string[]
}
```

---

## 10. ConversationDigest

**File:** `intermediate/s_explore/{session_id}.digest.json`  
**Produced by:** DigestBuilder (Phase 2a)

```typescript
ConversationDigest {
  session_id:           string
  cohort_label?:        "before" | "after"     // comparative only

  opening_intent:       string
  outcome:              string
  turn_count:           integer
  duration_ms:          integer

  transcript_digest:    TranscriptTurn[]       // full transcript, all turns
  notable_events:       string[]
  anomaly_flags:        string[]
  primitive_snapshot:   { [primitive_name: string]: Scalar }
}

TranscriptTurn {
  turn_index:  integer
  speaker:     "user" | "assistant"
  text:        string
  agent_name?: string | null
}

Scalar = number | string | boolean | null
```

---

## 11. AnalysisPlan

**File:** `intermediate/analysis_plan.json`  
**Produced by:** PlanSynthesizer (Phase 2b)  
**Consumed by:** Explore tab (read-only), Phase 3 executor (after approval)

```typescript
AnalysisPlan {
  schema_version:        "1.0"
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

  primitives_required:   PrimitiveRef[]
  signals_required:      SignalSpec[]

  user_approved:         boolean              // false until Execute plan; then true
  synthesized_at:        datetime
}
```

### 11.1 Aspect

```typescript
Aspect {
  id:           string                 // stable slug, e.g. "speed"
  name:         string                 // display name
  description:  string
  components:   AspectComponent[]
}

AspectComponent {
  ref:           PrimitiveRef | SignalRef
  aggregation:   "mean" | "p50" | "p95" | "sum" | "rate" | "count"
  weight?:       number
}
```

### 11.2 Hypothesis

```typescript
Hypothesis {
  id:           string
  title:        string
  description:  string
  signals:      SignalRef[]            // subset of signals_required
  predicate:    Predicate
  proof:        ProofSpec
}

ProofSpec {
  metric:               "match_rate" | "match_count" | "cohort_delta"
  min_support:          integer
  min_rate?:            number | null
  significance_test?:   "chi_square" | "fisher" | "bootstrap_ci" | "mann_whitney" | null
  significance_level:   number
}
```

### 11.3 Predicate (JSON encoding)

Operand `name` references a primitive catalog name or a signal name from `signals_required` / `primitives_required`.

```typescript
Predicate =
  | { op: "AND"; args: Predicate[] }
  | { op: "OR";  args: Predicate[] }
  | { op: "NOT"; arg:  Predicate }
  | { op: "IS_NULL"; name: string }
  | { op: "IN"; name: string; values: Scalar[] }
  | { op: "BETWEEN"; name: string; low: Scalar; high: Scalar }
  | { op: "cmp"; name: string; cmp: "==" | "!=" | "<" | "<=" | ">" | ">="; value: Scalar }
```

```json
{
  "op": "AND",
  "args": [
    { "op": "cmp", "name": "user_query_type", "cmp": "==", "value": "transfer_request" },
    { "op": "cmp", "name": "turn_count", "cmp": ">", "value": 4 },
    { "op": "IN", "name": "session_outcome", "values": ["transferred", "abandoned", "timeout"] }
  ]
}
```

### 11.4 Signal specs

All signals in `signals_required` must be declared here. Phase 3 executes these specs verbatim.

```typescript
SignalSpec =
  | PrimitiveRef
  | ClassicalSignalSpec
  | SemanticSignalSpec

PrimitiveRef {
  kind:  "primitive"
  name:  string                         // catalog name, e.g. "turn_count"
}

SignalRef {
  kind:   "signal"
  name:   string
}

ClassicalSignalSpec {
  kind:        "classical"
  name:        string
  value_type:  "int" | "float" | "bool" | "string" | "null"
  spec:        ClassicalSpecBody
}

ClassicalSpecBody =
  | { type: "turn_index"; event_type: string | string[]; event_value_filter?: object }
  | { type: "duration_between"; event_a: EventAnchor; event_b: EventAnchor }
  | { type: "regex_on_transcript"; pattern: string; scope: "session" | "turn"; case_sensitive?: boolean }
  | { type: "agent_path_label" }
  | { type: "conditional_metadata"; event_type: string; field_path: string; when?: object }

EventAnchor { event_type: string; selector?: "first" | "last" }

SemanticSignalSpec {
  kind:        "semantic"
  name:        string
  value_type:  "int" | "float" | "bool" | "string"
  method:      "rule_based" | "zero_shot_llm" | "llm_extract" | "embedding_nearest_neighbor"
  spec:        SemanticSpecBody
}

SemanticSpecBody {
  description:      string
  labels?:          string[]
  prompt_hint?:     string
  blueprint_refs?:  string[]
  keywords?:        string[]             // rule_based
  regex?:           string[]             // rule_based
  min_hits?:        integer              // rule_based; default 1
  prototypes?:      { label: string; text: string }[]   // embedding_nearest_neighbor
}
```

**Validation rules (PlanSynthesizer post-check):**

1. Every `name` in `hypothesis.predicate` ∈ names from `signals_required` ∪ `primitives_required`.  
2. Every `PlotSpec` / `TableSpec` `template` ∈ `config/artifact_templates.yaml`.  
3. All `regex` patterns compile; `method` ∈ `config/semantic_methods.yaml` allowlist.  
4. `llm_extract` and `zero_shot_llm` must not appear as the only method for signals required on full `D_eval` without an explicit cap in executor config.

### 11.5 Plot and table specs

```typescript
PlotSpec {
  id:           string
  title:        string
  description:  string
  template:     string                 // e.g. "aspect_before_after_bar"
  bindings:     object                 // template-specific; see artifact_templates.yaml
}

TableSpec {
  id:           string
  title:        string
  description:  string
  template:     string                 // e.g. "hypothesis_summary"
  bindings:     object
}
```

Example bindings:

```json
{
  "id": "speed_comparison",
  "title": "Speed before vs after",
  "description": "Main stream latency comparison",
  "template": "aspect_before_after_bar",
  "bindings": { "aspect_ids": ["speed"] }
}
```

### 11.6 Example AnalysisPlan (truncated)

```json
{
  "schema_version": "1.0",
  "study_query": { "type": "comparative", "change": { "description": "Qwen 10% canary" }, "scope_before": {}, "scope_after": {}, "config": { "n_explore": 100, "n_eval": "all", "min_support": 30, "significance_level": 0.05 } },
  "exploration_summary": "After window shows higher tool error rate on authentication flows...",
  "quantitative": {
    "aspects": [
      {
        "id": "speed",
        "name": "Speed",
        "description": "Main stream response latency",
        "components": [{ "ref": { "kind": "primitive", "name": "main_stream_latency_p95" }, "aggregation": "p95" }]
      }
    ],
    "suggested_plots": [{ "id": "speed_bar", "title": "Speed", "description": "Before/after latency", "template": "aspect_before_after_bar", "bindings": { "aspect_ids": ["speed"] } }],
    "suggested_tables": [{ "id": "aspect_table", "title": "Aspect summary", "description": "All aspects", "template": "aspect_summary", "bindings": {} }]
  },
  "qualitative": {
    "hypotheses": [
      {
        "id": "early_transfer_waste",
        "title": "Early transfer waste",
        "description": "Users request transfer early but bot continues for many turns",
        "signals": [{ "kind": "signal", "name": "user_query_type" }, { "kind": "primitive", "name": "turn_count" }],
        "predicate": { "op": "AND", "args": [{ "op": "cmp", "name": "user_query_type", "cmp": "==", "value": "transfer_request" }, { "op": "cmp", "name": "turn_count", "cmp": ">", "value": 4 }] },
        "proof": { "metric": "cohort_delta", "min_support": 30, "significance_level": 0.05, "significance_test": "chi_square" }
      }
    ]
  },
  "primitives_required": [{ "kind": "primitive", "name": "turn_count" }, { "kind": "primitive", "name": "main_stream_latency_p95" }],
  "signals_required": [
    {
      "kind": "semantic",
      "name": "user_query_type",
      "value_type": "string",
      "method": "rule_based",
      "spec": { "description": "Classify first user intent", "labels": ["transfer_request", "billing", "other"], "keywords": ["transfer", "agent"], "regex": ["\\btransfer\\b"], "min_hits": 1 }
    }
  ],
  "user_approved": false,
  "synthesized_at": "2026-08-22T10:03:00+05:30"
}
```

---

## 12. TimingLogEntry

**File:** `intermediate/timing.jsonl` (one JSON object per line)

```typescript
TimingLogEntry {
  ts:           datetime
  study_slug:   string
  phase:        "0" | "1" | "2a" | "2b" | "3"
  component:    string
  session_id?:  string
  duration_ms:  number
  cache_hit?:   boolean
  counts?:      object
  llm?:         { model: string; tokens_in: integer; tokens_out: integer }
  error?:       string | null
}
```

---

## 13. EvaluationResult

**File:** `output/evaluation_result.json`  
**Produced by:** Phase 3 (SignalExecutor → aggregators → ArtifactRenderer → NarrativeSummarizer)

```typescript
EvaluationResult {
  schema_version:     "1.0"
  study_query:        StudyQuery
  analysis_plan:      AnalysisPlan           // user_approved == true
  evaluated_at:       datetime

  cohort_sizes:       ComparativeCohortSizes | SingleCohortSizes

  quantitative:       { [aspect_id: string]: AspectResult }
  qualitative:        { [hypothesis_id: string]: HypothesisResult }

  artifacts: {
    plots:              RenderedArtifact[]
    tables:             RenderedArtifact[]
    narrative_summary:  string
    recommendations?:   string[]
  }

  // optional inline map; large studies use shards (§14) instead
  per_conversation?:  { [session_id: string]: ConversationSignals }
}

RenderedArtifact {
  id:           string
  title:        string
  description:  string
  path:         string                 // relative to study dir, e.g. "output/plots/speed_bar.png"
  mime_type:    string                 // "image/png" | "text/csv"
}

ConversationSignals {
  cohort_label?:  "before" | "after"    // comparative only
  primitives:     { [name: string]: Scalar }
  signals:        { [name: string]: Scalar }
}
```

### 13.1 AspectResult

```typescript
AspectResult {
  aspect_id:    string
  name:         string

  // single cohort
  single?:      CohortAggregate

  // comparative
  before?:      CohortAggregate
  after?:       CohortAggregate
  delta?:       number
  delta_pct?:   number
  test?:        SignificanceTest
}

CohortAggregate {
  mean?:   number
  p50?:    number
  p95?:    number
  sum?:    number
  rate?:   number
  count?:  integer
  n:       integer
}

SignificanceTest {
  name:         string                 // e.g. "mann_whitney", "chi_square"
  statistic?:   number
  p_value:      number
  significant:  boolean                // p_value < significance_level
}
```

### 13.2 HypothesisResult

```typescript
HypothesisResult {
  hypothesis_id:       string
  title:               string
  support_count:       integer
  match_rate:          number           // 0–100 percentage

  // single cohort
  rejected:            boolean          // support_count < min_support

  // comparative
  cohort_comparison?: {
    rate_before:       number
    rate_after:        number
    support_before:    integer
    support_after:     integer
    delta:             number
    p_value:           number
    significant:       boolean
  }

  counter_examples:    string[]         // session_ids for BotProbe links
  counter_example_notes?: { session_id: string; note: string }[]   // optional llm_extract
}
```

### 13.3 Example EvaluationResult (truncated)

```json
{
  "schema_version": "1.0",
  "study_query": {},
  "analysis_plan": { "user_approved": true },
  "evaluated_at": "2026-08-22T10:15:00+05:30",
  "cohort_sizes": { "before": 1842, "after": 1901 },
  "quantitative": {
    "speed": {
      "aspect_id": "speed",
      "name": "Speed",
      "before": { "p95": 410, "n": 1842 },
      "after": { "p95": 585, "n": 1901 },
      "delta": 175,
      "delta_pct": 42.7,
      "test": { "name": "mann_whitney", "p_value": 0.001, "significant": true }
    }
  },
  "qualitative": {
    "early_transfer_waste": {
      "hypothesis_id": "early_transfer_waste",
      "title": "Early transfer waste",
      "support_count": 171,
      "match_rate": 4.5,
      "rejected": false,
      "cohort_comparison": {
        "rate_before": 4.2,
        "rate_after": 18.6,
        "support_before": 77,
        "support_after": 94,
        "delta": 14.4,
        "p_value": 0.0001,
        "significant": true
      },
      "counter_examples": ["session-uuid-a", "session-uuid-b", "session-uuid-c"]
    }
  },
  "artifacts": {
    "plots": [{ "id": "speed_bar", "title": "Speed", "description": "Before/after latency", "path": "output/plots/speed_bar.png", "mime_type": "image/png" }],
    "tables": [{ "id": "hypothesis_table", "title": "Hypotheses", "description": "Summary", "path": "output/tables/hypothesis_table.csv", "mime_type": "text/csv" }],
    "narrative_summary": "Tool error rate increased significantly in authentication flows after the canary..."
  }
}
```

---

## 14. PerConversationShard

**File:** `output/per_conversation/{shard_id}.json`  
**Used when:** `|D_eval|` is large; histogram templates read these shards.

```typescript
PerConversationShard {
  shard_id:    string
  session_ids: string[]
  records:     { [session_id: string]: ConversationSignals }
}
```

---

## 15. UI field mapping

| UI region | Source fields |
|-----------|---------------|
| Explore header — cohort sizes | `cohort_stats.json` → `cohort_sizes` |
| Explore header — n_explore | `cohort_stats.json` → `n_explore` |
| Explore — summary | `analysis_plan.json` → `exploration_summary` |
| Explore — aspects / plots / tables / hypotheses | `analysis_plan.json` → `quantitative`, `qualitative` |
| Results — aspect cards | `evaluation_result.json` → `quantitative` |
| Results — hypothesis cards | `evaluation_result.json` → `qualitative` |
| Results — counter-examples | `qualitative[].counter_examples` |
| Results — plots / tables | `evaluation_result.json` → `artifacts.plots`, `artifacts.tables` |
| Results — narrative | `artifacts.narrative_summary` |
| New Study progress / errors | `meta.json` → `status`, `error` |

---

## 16. Document history

| Version | Date | Notes |
|---------|------|-------|
| v1 | 2026-08-30 | Initial output schema: intermediates, AnalysisPlan, EvaluationResult, predicate/signal JSON encoding |
