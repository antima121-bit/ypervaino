from __future__ import annotations

import json
import random
from typing import Any, Callable

from ypervaino.artifacts import render_plots, render_tables
from ypervaino.blueprint_store import init_baseline, load_blueprint
from ypervaino.change_context import resolve_change_context
from ypervaino.config_loader import load_artifact_templates, load_filter_atoms
from ypervaino.data_layer import (
    fetch_blueprint,
    fetch_session_id_list,
    load_or_fetch_conversation,
    parse_dt,
    blueprint_for_llm,
    blueprint_routing_context,
)
from ypervaino.digest import build_digests_parallel
from ypervaino.embeddings import apply_opening_embeddings
from ypervaino.evaluation import run_evaluation
from ypervaino.exploration import build_exploration_manifest
from ypervaino.features import compute_features
from ypervaino.intent import apply_intent_to_features, build_intent_lexicon
from ypervaino.llm_client import LLMClient, DEFAULT_LLM_CONFIG, PLAN_SYNTHESIZER_LLM_CONFIG
from ypervaino.parallel import run_parallel, worker_count
from ypervaino.plan_validator import PlanValidationError, primitive_catalog_for_prompt, validate_plan
from ypervaino.sampling import stratified_subsample
from ypervaino.settings import MAX_TRACE_SESSIONS
from ypervaino.study_store import StudyStore
from ypervaino.timing import StudyTimer


def compile_predicate(filters: list[dict]) -> list[dict]:
    atoms = {a["id"]: a for a in load_filter_atoms()}
    compiled = []
    for f in filters or []:
        atom = atoms.get(f.get("atom_id") or f.get("id"))
        if atom:
            compiled.append({**atom, "user_value": f.get("value")})
    return compiled


from ypervaino.pipeline_filters import filter_failure_reasons


def _apply_traffic_split(fv: dict, traffic_split: dict | None) -> bool:
    if not traffic_split:
        return True
    want = traffic_split.get("value")
    got = fv.get("traffic_split_variant")
    return got == want if want is not None else True


def _eval_target(n_eval: Any) -> int:
    if n_eval in (None, "all"):
        return MAX_TRACE_SESSIONS
    return int(n_eval)


def _collect_filtered_sessions(
    ids: list[str],
    target: int,
    process_fn: Callable[[str], tuple[str, dict[str, Any]] | None],
    *,
    label: str,
    timer: StudyTimer,
) -> tuple[list[str], dict[str, dict[str, Any]], int]:
    """Fetch traces and compute features until `target` sessions pass filters."""
    pool = list(ids)
    random.shuffle(pool)
    kept: list[str] = []
    features_out: dict[str, dict[str, Any]] = {}
    scanned = 0
    batch_size = max(worker_count() * 4, 8)

    with timer.track("0", "FeatureComputer", counts={"sessions_in": len(pool)}):
        offset = 0
        while offset < len(pool) and len(kept) < target:
            batch = pool[offset : offset + batch_size]
            offset += len(batch)
            scanned += len(batch)
            results = run_parallel(
                batch,
                process_fn,
                max_workers=worker_count(),
                label=f"phase0-features-{label}",
            )
            for row in results:
                if not row or len(kept) >= target:
                    continue
                sid, fv = row
                kept.append(sid)
                features_out[sid] = fv

    if len(kept) < target:
        timer.log.warning(
            "Phase 0: cohort %s — only %d/%d passed filters after scanning %d/%d sessions",
            label, len(kept), target, scanned, len(pool),
        )
    else:
        timer.log.info(
            "Phase 0: cohort %s — reached target %d (scanned %d/%d sessions)",
            label, target, scanned, len(pool),
        )
    return kept, features_out, len(pool)


def _session_feature_file(session_id: str) -> str:
    return f"cache/features/{session_id}.json"


def write_cohort_sets(
    store: StudyStore,
    stats: dict[str, Any],
    manifest: dict[str, Any] | None = None,
) -> None:
    eval_by_cohort = stats.get("session_ids") or {}
    eval_ids = [sid for ids in eval_by_cohort.values() for sid in ids]
    explore_ids = list(manifest.get("session_ids") or []) if manifest else []
    payload = {
        "schema_version": "1.0",
        "eval": {
            "by_cohort": eval_by_cohort,
            "session_ids": eval_ids,
            "feature_files": [_session_feature_file(sid) for sid in eval_ids],
            "count": len(eval_ids),
        },
        "exploration": {
            "by_cohort": (manifest.get("by_cohort") or {}) if manifest else {},
            "session_ids": explore_ids,
            "feature_files": [_session_feature_file(sid) for sid in explore_ids],
            "count": len(explore_ids),
        },
    }
    store.write_json(store.intermediate_dir / "cohort_sets.json", payload)


def phase0_cohort(store: StudyStore, req: dict[str, Any], timer: StudyTimer) -> dict[str, Any]:
    tenant = req["tenant"]
    assistant_origin_id = req["assistant_origin_id"]
    channel = req.get("channel") or "voice"
    n_eval = req.get("n_eval", "all")
    compiled = compile_predicate(req.get("cohort_filters") or [])
    traffic_split = req.get("traffic_split")
    timer.log.info(
        "Phase 0: cohort discovery tenant=%s assistant=%s filters=%d traffic_split=%s",
        tenant, assistant_origin_id, len(compiled), bool(traffic_split),
    )

    def window_ids(start_s: str, end_s: str) -> list[str]:
        return fetch_session_id_list(
            tenant, assistant_origin_id, channel, parse_dt(start_s), parse_dt(end_s),
            assistant_id=req.get("assistant_id"), limit=None,
        )

    eval_target = _eval_target(n_eval)
    timer.log.info("Phase 0: eval target per cohort=%d (n_eval=%s)", eval_target, n_eval)

    with timer.track("0", "MongoSessionIndex"):
        if req["study_type"] == "comparative":
            cohorts_mongo = {
                "before": window_ids(req["date_range_before"]["start"], req["date_range_before"]["end"]),
                "after": window_ids(req["date_range_after"]["start"], req["date_range_after"]["end"]),
            }
        else:
            dr = req["date_range"]
            cohorts_mongo = {"all": window_ids(dr["start"], dr["end"])}

    timer.log.info("Phase 0: mongo cohort sizes %s", {k: len(v) for k, v in cohorts_mongo.items()})

    features: dict[str, dict] = {}
    filtered: dict[str, list[str]] = {}

    def _process_session(sid: str) -> tuple[str, dict[str, Any]] | None:
        try:
            conv = load_or_fetch_conversation(store, sid)
            if conv is None:
                timer.log.warning("Phase 0: session %s skipped — trace fetch failed", sid)
                return None
            fv = compute_features(conv, include_embedding=False)
            if not _apply_traffic_split(fv, traffic_split):
                timer.log.info(
                    "Phase 0: session %s dropped — traffic_split mismatch (variant=%s)",
                    sid, fv.get("traffic_split_variant"),
                )
                return None
            store.write_json(store.features_dir / f"{sid}.json", fv)
            if compiled:
                failures = filter_failure_reasons(fv, compiled)
                if failures:
                    timer.log.info(
                        "Phase 0: session %s dropped — cohort filter: %s",
                        sid, "; ".join(failures),
                    )
                    return None
            return sid, fv
        except Exception as e:
            timer.log.warning("Phase 0: session %s skipped — %s", sid, e)
            return None

    for label, ids in cohorts_mongo.items():
        kept, fv_map, _raw_n = _collect_filtered_sessions(
            ids, eval_target, _process_session, label=label, timer=timer,
        )
        filtered[label] = kept
        features.update(fv_map)

    with timer.track("0", "OpeningEmbeddings"):
        n_embedded = apply_opening_embeddings(features)
        for sid, fv in features.items():
            store.write_json(store.features_dir / f"{sid}.json", fv)
        timer.log.info("Phase 0: embedded %d opening texts via OpenAI (parallel batches)", n_embedded)

    # Stratified subsample if a batch overshoots the target
    for label, ids in list(filtered.items()):
        if len(ids) > eval_target:
            items = [(sid, features[sid]) for sid in ids]
            filtered[label] = stratified_subsample(items, eval_target)
            timer.log.info("Phase 0: cohort %s subsampled to n_eval=%d", label, eval_target)

    kept_ids = {sid for ids in filtered.values() for sid in ids}
    features = {sid: fv for sid, fv in features.items() if sid in kept_ids}

    with timer.track("0", "BlueprintFetcher"):
        bp_raw = fetch_blueprint(tenant, assistant_origin_id, channel)
        init_baseline(store, bp_raw)
        bp_ctx = blueprint_routing_context(bp_raw)
        timer.log.info(
            "Phase 0: blueprint orchestration=%s skills=%d baseline=v0001",
            bp_ctx.get("orchestration_type"), len(bp_ctx.get("skills") or []),
        )

    change_ctx = None
    if req.get("change_description") or req.get("pr_link"):
        timer.log.info("Phase 0: resolving change context (pr=%s)", bool(req.get("pr_link")))
        with timer.track("0", "ChangeContextResolver"):
            change_ctx = resolve_change_context(
                req.get("change_description") or "",
                req.get("pr_link"),
                bp_raw,
            )
            store.write_json(store.intermediate_dir / "change_context.json", change_ctx)

    all_ids = [sid for ids in filtered.values() for sid in ids]
    pilot = random.sample(all_ids, min(200, len(all_ids))) if all_ids else []
    with timer.track("0", "IntentLexiconBuilder"):
        lexicon = build_intent_lexicon(store, bp_raw, [features[s] for s in pilot if s in features])
        apply_intent_to_features(store, all_ids, lexicon)
        for sid in all_ids:
            if sid in features:
                features[sid] = store.read_json(store.features_dir / f"{sid}.json")

    stats = {
        "tenant": tenant,
        "assistant_origin_id": assistant_origin_id,
        "raw_counts": {k: len(v) for k, v in cohorts_mongo.items()},
        "filtered_counts": {k: len(v) for k, v in filtered.items()},
        "session_ids": filtered,
        "n_explore": int(req.get("n_explore") or 100),
    }
    store.write_json(store.intermediate_dir / "cohort_stats.json", stats)
    write_cohort_sets(store, stats)
    timer.log.info(
        "Phase 0 complete — filtered_counts=%s explore_pool=%d",
        stats["filtered_counts"], len(all_ids),
    )
    return {"stats": stats, "features": features, "blueprint": bp_raw, "change_context": change_ctx}


def phase1_sample(store: StudyStore, stats: dict, req: dict, features: dict[str, dict], timer: StudyTimer) -> dict[str, Any]:
    timer.log.info("Phase 1: exploration sampling n_explore=%s", req.get("n_explore"))
    with timer.track("1", "ExplorationSampler"):
        manifest = build_exploration_manifest(
            req["study_type"],
            stats["session_ids"],
            features,
            int(req.get("n_explore") or 100),
            int(req.get("pairing_turn_tolerance") or 3),
        )
    store.write_json(store.intermediate_dir / "s_explore" / "manifest.json", manifest)
    write_cohort_sets(store, stats, manifest)
    timer.log.info("Phase 1 complete — %d exploration sessions selected", len(manifest.get("session_ids") or []))
    return manifest


def phase2a_digests(store: StudyStore, manifest: dict, timer: StudyTimer) -> None:
    n = len(manifest.get("session_ids") or [])
    timer.log.info("Phase 2a: building digests for %d sessions", n)
    with timer.track("2a", "DigestBuilder"):
        build_digests_parallel(store, manifest)


def build_plan_synthesizer_prompt(
    *,
    change: dict[str, Any],
    req: dict[str, Any],
    stats: dict[str, Any],
    bp_ctx: dict[str, Any],
    blueprint_json: str,
    digests: list[dict[str, Any]],
    allowed_plots: list[str],
    allowed_tables: list[str],
    primitive_catalog: list[dict[str, Any]],
) -> str:
    skill_names = [s.get("name") for s in (bp_ctx.get("skills") or [])]
    change_json = json.dumps(change, default=str, ensure_ascii=False)
    digests_json = json.dumps(digests, default=str, ensure_ascii=False)
    catalog_json = json.dumps(primitive_catalog, default=str, ensure_ascii=False)
    filtered_counts = json.dumps(stats.get("filtered_counts", {}))

    return f"""# 1. TASK

You are **Ypervaíno PlanSynthesizer**.

A production change has been deployed to a voice virtual agent. You are given:
- **What changed** (change context)
- **How the bot is built** (VA blueprint)
- **What happened in a sample of real calls** (exploration digests)

Your job is to derive a complete **AnalysisPlan** from the change: decide everything Phase 3 should measure and test on the full eval cohort to understand **how the change is behaving in production**.

The change is the primary lens. Every aspect and hypothesis should be **justified by the change** — metrics that would not help assess this change should be omitted. Within that scope, be **exhaustive**: include every relevant primitive and semantic pattern you can compute. **There is no limit** on the number of aspects or hypotheses; **more is preferred** when change-relevant.

Phase 3 executes your plan unchanged on the eval cohort. Return **valid JSON only** matching the AnalysisPlan schema. Set `"user_approved": false`.

---

# 2. OUTPUT SCHEMA — field meanings

## Top level

| Field | Meaning |
|-------|---------|
| `exploration_summary` | 2–4 sentences summarizing what you observed in exploration digests, tied to the change. |
| `quantitative` | Numeric measurement plan: aspects + plot/table specs. |
| `qualitative` | Hypothesis plan: per-session patterns to validate (successes and failures). |
| `primitives_required` | **Non-empty.** Every catalog primitive Phase 3 must load. Include all primitives used by aspects and hypothesis predicates. |
| `signals_required` | **Optional.** New semantic labels **not** in the primitive catalog. Omit if primitives suffice. |
| `user_approved` | Always `false`. |

## `quantitative.aspects[]`

Each aspect = one measurable quantity aggregated across the eval cohort.

| Field | Meaning |
|-------|---------|
| `id` | Stable snake_case key (used in results and artifact bindings). |
| `name` | Human-readable label for UI. **Include unit in parentheses**: `(ms)`, `(sec)`, `(count)`, `(rate)`, `(usd)`, `(string)`. |
| `description` | 1–2 sentences: what this measures and **why it matters for assessing this change**. |
| `components[]` | **Exactly one entry.** Per-session primitive value, then one cohort aggregation. |

**Component fields:**
- `ref.kind`: `"primitive"` or `"signal"`
- `ref.name`: name from `primitives_required` or `signals_required`
- `aggregation`: cohort rollup across sessions — `mean`, `p50`, `p95`, `sum`, `rate`, `count`
  - Use `rate` for booleans (share of sessions where true / count > 0)

**Two-level aggregation (read carefully):**
1. **Session level** — the primitive is computed per call (e.g. `main_stream_latency_p95` is already the p95 of LLM latencies *within that session*).
2. **Cohort level** — the single component's `aggregation` rolls those session values up (e.g. `mean` = average session p95 across the cohort).

| Primitive | Already per session | Cohort `aggregation` means |
|-----------|---------------------|----------------------------|
| `*_latency_p95` | p95 of latencies in that call | `mean` → typical session tail; `p95` → tail of session tails |
| `turn_count` | turns in that call | `mean` → avg turns per call |
| `transfer_completed` | boolean | `rate` → % of calls |

**Design rules:**
- **Exactly one component per aspect.** One aspect = one cohort-level number in results.
- If you want both mean and cohort p95 for the same primitive, create **two separate aspects** with distinct `id` and `name` — never two components in one aspect.
- Prefer **one primitive → one aspect** (with one aggregation). Do not bundle unrelated metrics.
- Aspect **name** must state the cohort aggregation: e.g. `Main-stream latency mean (ms)` vs `Main-stream latency cohort p95 (ms)`.
- Primitives ending in `_p95` are **not** raw latency streams — do not pair `mean` + `p95` components on the same primitive in one aspect.

**BAD — one aspect, two aggregations on the same primitive:**
```json
{{"id": "contextual_query_latency", "components": [
  {{"ref": {{"name": "contextual_query_latency_p95"}}, "aggregation": "mean"}},
  {{"ref": {{"name": "contextual_query_latency_p95"}}, "aggregation": "p95"}}
]}}
```

**GOOD — two aspects:**
```json
{{"id": "contextual_query_latency_mean", "name": "Contextual-query latency mean (ms)", "components": [
  {{"ref": {{"kind": "primitive", "name": "contextual_query_latency_p95"}}, "aggregation": "mean"}}
]}},
{{"id": "contextual_query_latency_cohort_p95", "name": "Contextual-query latency cohort p95 (ms)", "components": [
  {{"ref": {{"kind": "primitive", "name": "contextual_query_latency_p95"}}, "aggregation": "p95"}}
]}}
```

## `quantitative.suggested_plots[]` / `suggested_tables[]`

| Field | Meaning |
|-------|---------|
| `id` | Unique artifact spec id |
| `title` | Display title |
| `description` | What the visualization shows |
| `template` | Must be from Allowed plot/table templates |
| `bindings` | Template params (e.g. `aspect_ids`, `hypothesis_ids`, `metric_name`) |

## `signals_required[]` (optional)

New per-session labels not in the primitive catalog.

| Field | Meaning |
|-------|---------|
| `name` | snake_case; used in predicates |
| `method` | **`rule_based` only** — keywords/regex over utterances |
| `value_type` | `boolean`, `string`, `integer`, or `float` |
| `spec` | Method-specific config |

For `rule_based`: non-empty `keywords[]` and/or `regex[]`, plus `scope` (`session`, `opening_turns`, `turn`).

## `qualitative.hypotheses[]`

Each hypothesis = a per-session pattern testable on the eval cohort.

| Field | Meaning |
|-------|---------|
| `id` | Stable snake_case key |
| `title` | Short label; suffix `(positive)` or `(negative)` optional if `polarity` set |
| `description` | What behavior this captures and why it matters for the change |
| `polarity` | **`positive`** or **`negative`** — whether a high conditional match rate is good or bad |
| `scope_predicate` | **When this hypothesis applies** (denominator). Per-session boolean. Example: `payment_intent == 1` |
| `predicate` | **Eval predicate** (numerator). Tested only on scope-applicable sessions. Example: `auth_flow_prompted == 1` |
| `signals` | Optional refs used by scope or eval predicates |
| `proof` | Optional: `metric`, `min_support`, `significance_level` |

**Two-pass evaluation:** sessions must pass `scope_predicate` to be applicable; `predicate` is evaluated only on applicable sessions. Conditional rate = matches / applicable.

**Include both positive and negative hypotheses:**
- **Negative / risk:** failure modes, regressions, friction (e.g. user asked for agent but transfer did **not** complete).
- **Positive / success:** behaviors working as intended (e.g. user asked for transfer and call **was** transferred; payment intent completed without tool errors).

Cover the full behavior surface area relevant to the change — not only problems.

---

# 3. INSTRUCTIONS

## Change-first planning
1. Read the change context and identify affected systems (model, routing, tools, prompts, skills).
2. From the primitive catalog, include **every primitive** that could indicate change impact.
3. Add **signals** for transcript patterns the change should affect but that are not in the catalog.
4. Propose **many aspects** (one per relevant primitive) and **many hypotheses** (positive and negative).
5. Ground claims in exploration digests; do not invent metrics unrelated to the change.

## Primitives vs signals
- `primitives_required`: only names from **Allowed primitives catalog**.
- `signals_required`: only for labels **not** in that catalog.
- Never invent primitive names (`transfer_count`, `llm_error_count`, etc.).
- For transfer/escalation use `transfer_completed` or `session_outcome`.

## Aspects
- **One component per aspect** — never multiple components on the same primitive in one aspect.
- Name must include unit in parentheses and reflect the cohort aggregation (`mean`, `rate`, `cohort p95`, etc.).
- Latency primitives ending in `_p95`: pick one cohort aggregation; put it in the aspect name:
  - `aggregation: "mean"` → `"Main-stream latency mean (ms)"` (average session tail)
  - `aggregation: "p95"` → separate aspect `"Main-stream latency cohort p95 (ms)"` (worst session tails)
- Booleans / flags → `rate`. Counts → `mean` or `sum` (one aspect each, not both unless separate aspects).

## Rule-based signals (when needed)
- **`method` must be `rule_based`** — do not use `intent_classifier`, `embedding_nearest_neighbor`, `zero_shot_llm`, or `llm_extract`.
- Search text = **raw utterances only** (no `User:` / `Bot:` prefixes).
- `scope: opening_turns` → first user utterance; `scope: session` → all dialogue utterances.

## Hypotheses
- Every hypothesis MUST include `scope_predicate`, `polarity`, and `predicate` (eval).
- Use **`and` / `or`** for boolean combinations (not `&&` / `||`).
- `scope_predicate` = relevant population (e.g. `payment_intent == 1`).
- `predicate` = claim to test on that population (e.g. `auth_flow_prompted == 1`).
- Combine conditions with `and` / `or`, e.g. `payment_intent == 1 and human_agent_request == 0`.
- Predicates may only reference names in `primitives_required` or `signals_required`.
- Boolean signals: compare with `== 1` (true) or `== 0` (false).
- Pair opposites where useful: success path vs failure path for the same user intent.

## Study type
- `single_cohort`: monitor/discover how the change is performing (e.g. new model rollout).
- `comparative`: before/after; same aspects enable cohort comparison.

## Templates
- Plot/table templates must be from the allowed lists below and match study type.

---

# 4. EXAMPLE (illustrative — adapt to this study and change)

```json
{{
  "exploration_summary": "After the main_stream model swap, sessions use main_model with p95 latency ~1–2s. Payment flows show tool errors in some calls; transfers often succeed when explicitly requested.",
  "quantitative": {{
    "aspects": [
      {{
        "id": "main_stream_latency_mean",
        "name": "Main-stream latency mean (ms)",
        "description": "Average per-session p95 main-stream latency across the cohort — typical tail under the new deployment.",
        "components": [{{"ref": {{"kind": "primitive", "name": "main_stream_latency_p95"}}, "aggregation": "mean"}}]
      }},
      {{
        "id": "transfer_completion_rate",
        "name": "Transfer completion rate (rate)",
        "description": "Share of sessions where transfer completed — key outcome for handoff flows.",
        "components": [{{"ref": {{"kind": "primitive", "name": "transfer_completed"}}, "aggregation": "rate"}}]
      }},
      {{
        "id": "tool_error_rate",
        "name": "Tool error rate (rate)",
        "description": "Share of sessions with at least one tool error — indicates integration failures.",
        "components": [{{"ref": {{"kind": "primitive", "name": "tool_error_count"}}, "aggregation": "rate"}}]
      }},
      {{
        "id": "turn_count_mean",
        "name": "Turn count mean (count)",
        "description": "Average user turns per session — longer calls may indicate confusion or loops.",
        "components": [{{"ref": {{"kind": "primitive", "name": "turn_count"}}, "aggregation": "mean"}}]
      }}
    ],
    "suggested_plots": [
      {{
        "id": "plot_latency",
        "title": "Main-stream latency distribution",
        "description": "Histogram of main-stream p95 latency across eval cohort.",
        "template": "distribution_histogram",
        "bindings": {{"metric_name": "main_stream_latency_p95", "cohort": "all"}}
      }}
    ],
    "suggested_tables": [
      {{
        "id": "table_aspects",
        "title": "Aspect summary",
        "description": "All aspect aggregates for the eval cohort.",
        "template": "aspect_summary",
        "bindings": {{"aspect_ids": ["main_stream_latency_mean", "transfer_completion_rate", "tool_error_rate", "turn_count_mean"]}}
      }}
    ]
  }},
  "qualitative": {{
    "hypotheses": [
      {{
        "id": "transfer_request_succeeded",
        "title": "Transfer request succeeded (positive)",
        "description": "User asked for transfer/agent and the call was successfully transferred — expected success path.",
        "polarity": "positive",
        "scope_predicate": "asked_for_transfer == 1",
        "predicate": "transfer_completed == 1"
      }},
      {{
        "id": "transfer_request_failed",
        "title": "Transfer request failed (negative)",
        "description": "User asked for transfer/agent but transfer did not complete — regression or routing failure.",
        "polarity": "negative",
        "scope_predicate": "asked_for_transfer == 1",
        "predicate": "transfer_completed == 0"
      }},
      {{
        "id": "high_latency_before_transfer",
        "title": "High latency before transfer (negative)",
        "description": "Slow main-stream responses precede transfer — possible frustration escalation.",
        "polarity": "negative",
        "scope_predicate": "transfer_completed == 1",
        "predicate": "main_stream_latency_p95 >= 2000"
      }}
    ]
  }},
  "primitives_required": [
    "main_stream_latency_p95",
    "transfer_completed",
    "tool_error_count",
    "turn_count"
  ],
  "signals_required": [
    {{
      "name": "asked_for_transfer",
      "method": "rule_based",
      "value_type": "boolean",
      "spec": {{
        "keywords": ["transfer me", "speak to agent", "representative"],
        "regex": ["\\\\btransfer\\\\b"],
        "min_hits": 1,
        "scope": "session"
      }}
    }}
  ],
  "user_approved": false
}}
```

---

# 5. INPUT VALUES

## Study metadata
- **Study type:** {req.get('study_type')}
- **Cohort sizes (post-filter eval pool):** {filtered_counts}

## Change context
```json
{change_json}
```

## Blueprint orchestration (summary)
- Orchestration: {bp_ctx.get('orchestration_type')}
- Skills: {skill_names}

## Full VA Blueprint
```json
{blueprint_json}
```

## Exploration digests (all {len(digests)} sessions)
```json
{digests_json}
```

## Allowed plot templates
{allowed_plots}

## Allowed table templates
{allowed_tables}

## Allowed primitives catalog
Each entry is precomputed per session in Phase 3. **Only use primitive names from this list in `primitives_required` and aspect components.**

```json
{catalog_json}
```
"""


def phase2b_plan(store: StudyStore, req: dict, manifest: dict, stats: dict, timer: StudyTimer) -> dict[str, Any]:
    explore_ids = manifest.get("session_ids") or []
    timer.log.info("Phase 2b: synthesizing analysis plan from %d digests", len(explore_ids))
    digests = []
    for sid in explore_ids:
        p = store.intermediate_dir / "s_explore" / f"{sid}.digest.json"
        if p.exists():
            digests.append(store.read_json(p))
    bp = load_blueprint(store)
    bp_ctx = blueprint_routing_context(bp)
    change = store.read_json(store.intermediate_dir / "change_context.json") if (store.intermediate_dir / "change_context.json").exists() else {}
    templates = load_artifact_templates()
    allowed_plots = list((templates.get("plots") or {}).keys())
    allowed_tables = list((templates.get("tables") or {}).keys())
    primitive_catalog = primitive_catalog_for_prompt()

    base_prompt = build_plan_synthesizer_prompt(
        change=change,
        req=req,
        stats=stats,
        bp_ctx=bp_ctx,
        blueprint_json=blueprint_for_llm(bp, max_chars=None),
        digests=digests,
        allowed_plots=allowed_plots,
        allowed_tables=allowed_tables,
        primitive_catalog=primitive_catalog,
    )

    llm = LLMClient()
    plan = None
    last_errors: list[str] = []
    with timer.track("2b", "PlanSynthesizer", llm=PLAN_SYNTHESIZER_LLM_CONFIG):
        for attempt in range(2):
            prompt = base_prompt if attempt == 0 else base_prompt + f"\n\nFix these validation errors:\n{last_errors}"
            timer.log.info("Phase 2b: PlanSynthesizer attempt %d/2", attempt + 1)
            plan = llm.json_completion(
                prompt,
                schema_name="analysis_plan",
                model=PLAN_SYNTHESIZER_LLM_CONFIG["model"],
                reasoning=PLAN_SYNTHESIZER_LLM_CONFIG["reasoning"],
                text=PLAN_SYNTHESIZER_LLM_CONFIG["text"],
                max_output_tokens=PLAN_SYNTHESIZER_LLM_CONFIG["max_output_tokens"],
            )
            last_errors = validate_plan(plan)
            if not last_errors:
                break
            timer.log.warning("Phase 2b: plan validation errors: %s", last_errors)
        if last_errors:
            raise PlanValidationError(last_errors)

    plan.setdefault("schema_version", "1.0")
    plan["user_approved"] = False
    plan["study_query"] = req
    store.write_json(store.intermediate_dir / "analysis_plan.json", plan)
    timer.log.info(
        "Phase 2b complete — aspects=%d hypotheses=%d",
        len((plan.get("quantitative") or {}).get("aspects") or []),
        len((plan.get("qualitative") or {}).get("hypotheses") or []),
    )
    return plan


def phase3_evaluate(store: StudyStore, req: dict, stats: dict, plan: dict, timer: StudyTimer) -> dict[str, Any]:
    n_sessions = sum(len(v) for v in stats.get("session_ids", {}).values())
    timer.log.info("Phase 3: evaluating %d sessions", n_sessions)
    with timer.track("3", "SignalExecutor"):
        eval_out = run_evaluation(plan, stats["session_ids"], store, req, load_or_fetch_conversation)
    for sid, row in eval_out["per_conversation"].items():
        store.write_json(store.output_dir / "per_conversation" / f"{sid}.json", row)

    narrative = ""
    with timer.track("3", "NarrativeSummarizer", llm=DEFAULT_LLM_CONFIG):
        try:
            narrative = LLMClient().json_completion(
                f"Summarize evaluation results as JSON {{summary, recommendations[]}}:\n{json.dumps({'aspects': eval_out['aspects'], 'hypotheses': eval_out['hypotheses']}, default=str)[:12000]}",
                schema_name="narrative_summary",
            )
        except Exception:
            narrative = {"summary": "Evaluation complete.", "recommendations": []}

    is_comparative = req["study_type"] == "comparative"
    result = {
        "schema_version": "1.0",
        "study_type": req["study_type"],
        "cohort_sizes": {
            # single_cohort studies store their ids under "all", not
            # "before"/"after" -- report null there instead of a silent 0/0
            # next to a nonzero total (fixed once already; came back with
            # this rewrite).
            "before": len(stats["session_ids"].get("before") or []) if is_comparative else None,
            "after": len(stats["session_ids"].get("after") or []) if is_comparative else None,
            "total": sum(len(v) for v in stats["session_ids"].values()),
        },
        "quantitative": {"aspects": eval_out["aspects"]},
        "qualitative": {"hypotheses": eval_out["hypotheses"]},
        "aspects": eval_out["aspects"],
        "hypotheses": eval_out["hypotheses"],
        "artifacts": {
            "narrative_summary": narrative.get("summary") if isinstance(narrative, dict) else str(narrative),
            "recommendations": narrative.get("recommendations", []) if isinstance(narrative, dict) else [],
        },
        "exploration_summary": plan.get("exploration_summary") or "",
    }
    with timer.track("3", "ArtifactRenderer"):
        result["artifacts"]["tables"] = render_tables(store.output_dir, result, is_comparative)
        result["artifacts"]["plots"] = render_plots(store.output_dir, result, plan, is_comparative)
    store.write_json(store.output_dir / "evaluation_result.json", result)
    timer.log.info(
        "Phase 3 complete — aspects=%d hypotheses=%d artifacts=%d tables %d plots",
        len(result.get("aspects") or []),
        len(result.get("hypotheses") or []),
        len((result.get("artifacts") or {}).get("tables") or []),
        len((result.get("artifacts") or {}).get("plots") or []),
    )
    return result
