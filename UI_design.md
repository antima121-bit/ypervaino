# Ypervaíno — UI Design (v1)

**Source of truth:** [draft3.md](./draft3.md), [input_schema.md](./input_schema.md)
**Scope:** Screen-by-screen UI spec for the 3 v1 tabs. No visual mockup file — this is the
structural/behavioral spec; styling follows the existing va-argus dark theme (IBM Plex
Sans/Mono, teal accent, RED/YELLOW/GREEN semantic colors) so it reads as one product family.

---

## 0. Global shell

- Persistent left rail or top tab bar with exactly **3 tabs**: **New Study**, **Explore**, **Results**.
- No "Sessions" tab in Ypervaíno itself — session-level drill-down is a link **out** to BotProbe
  (`BOTPROBE_BASE_URL?session_id={id}`), per input_schema.md §2.9. Ypervaíno does not
  reimplement a session/transcript browser.
- A study is identified by `study_title` (user-entered, slugified for storage). There is no
  "studies list" screen specified in v1 — out of scope unless Dwijesh adds one to architecture.md.

---

## 1. Tab: New Study

**Purpose:** Collect one `CreateStudyRequest` (input_schema.md §1.1), submit it, and hand off to Explore.

### 1.1 Fields, in form order

| Section | Field | Control | Required | Notes |
|---|---|---|---|---|
| Identity | `study_title` | text input | yes | Must be unique; becomes the storage slug |
| Identity | `study_type` | segmented control: **Comparative** / **Single Cohort** | yes | Drives which date fields show below |
| What changed? | `change_description` | textarea | no | Empty + empty `pr_link` ⇒ pure discovery |
| What changed? | `pr_link` | text input (URL) | no | Triggers `ChangeContextResolver` server-side |
| Scope | `tenant` | dropdown | yes | |
| Scope | `assistant_origin_id` | dropdown (depends on tenant) | yes | |
| Scope | `assistant_id` | dropdown, optional | no | "Pin a specific published version" |
| Scope | `channel` | segmented control: **Voice** / **Chat** | yes | defaults to Voice |
| Scope (single) | `date_range` | date-range picker | yes, if `study_type == single_cohort` | |
| Scope (comparative) | `date_range_before` | date-range picker | yes, if `study_type == comparative` | |
| Scope (comparative) | `date_range_after` | date-range picker | yes, if `study_type == comparative` | |
| Cohort filters | `cohort_filters[]` | multi-select chip list, sourced from the filter-atom registry (§2.3) | no | See §1.2 below |
| Cohort filters | `traffic_split` | two linked inputs: dimension + value | no | e.g. `canary_variant` = `treatment` |
| Sampling | `n_explore` | number input | no, default 100 | Must be **even** when `study_type == comparative` — validate client-side |
| Sampling | `n_eval` | number input **or** "All" toggle | no, default "all" | |
| Sampling | `n_eval_before` / `n_eval_after` | number inputs, shown only in comparative mode, only if user overrides `n_eval` | no | |

**Explicitly NOT on this form** (input_schema.md §1.1 "hidden defaults"): `min_support`,
`significance_level`, `pairing_turn_tolerance`. These are backend constants for v1 — do not
add an "Advanced settings" section exposing them.

### 1.2 Cohort filter chips (v1 fixed set)

Render as a row of toggle chips, sourced from the static registry (input_schema.md §2.3):

| Chip label | Needs a value? |
|---|---|
| Main stream model is… | yes — text/dropdown for model id |
| LLM purpose used in call | yes — e.g. `main_stream`, `kb_stream` |
| Skill / agent was active | yes — e.g. `Main_Auth` |
| Guardrails triggered | no — boolean chip |
| Call transfer happened | no — boolean chip |
| Interruption occurred | no — boolean chip |

Selected chips compile client-side into `cohort_filters[]` on submit; the actual
`conversation_predicate` compilation happens server-side.

### 1.3 Comparative-mode constraint

When `study_type == "comparative"`: `tenant`, `assistant_origin_id`, and `channel` are shared
across both windows — render them once, not duplicated per window. Only the two date ranges differ.

### 1.4 Submit behavior

- Button: **"Start Analysis"**.
- Client-side validation: required fields present; `n_explore` even for comparative.
- On submit: POST `CreateStudyRequest`, disable the button, show a progress state
  ("Resolving cohort…" → "Sampling conversations…" → "Generating plan…") while Phase 0–2 run
  server-side synchronously (or poll `meta.json` status: `created` → `explored`).
- On `explored`: navigate to **Explore**.
- On `failed`: show the error from `meta.json`, stay on this tab, do not silently retry.

---

## 2. Tab: Explore

**Purpose:** Read-only display of the `AnalysisPlan` Phase 2 produced. One action: **Execute**.

### 2.1 Layout

| Region | Content | Source |
|---|---|---|
| Header | Study title, study type badge, cohort sizes after Phase 0 | `meta.json`, `cohort_stats.json` |
| Summary card | `exploration_summary` narrative | `analysis_plan.json` |
| Quantitative section | Proposed **aspects** (name + description), suggested plot/table specs (rendered as placeholders/labels, not live charts yet — no data until Phase 3) | `analysis_plan.json.quantitative` |
| Qualitative section | Proposed **hypotheses**: title, description, signal names referenced (no raw predicate syntax shown to the user) | `analysis_plan.json.qualitative` |

### 2.2 The one interaction

- Single primary button: **"Execute plan"**.
- **No** per-aspect or per-hypothesis include/exclude toggles. **No** edit-in-place. **No**
  "regenerate" or feedback box. This is a deliberate v1 constraint (draft3 §14, §2 table) —
  do not add approval granularity here even if it looks like an obvious improvement; scope
  changes go through a **new study**, not a plan revision.
- On click: POST execute → sets `analysis_plan.user_approved = true`, study status → `running`
  → Phase 3 runs → on completion, status → `complete` → navigate to **Results**.
- Show a progress/loading state for the duration of Phase 3 (can be long on large `n_eval`).

### 2.3 Empty/edge states

- If Phase 2 produced zero hypotheses (rare, e.g. extremely narrow cohort): show the
  quantitative section only, with a note, and Execute still runs aspects-only evaluation.

---

## 3. Tab: Results

**Purpose:** Read-only view of `EvaluationResult`. No inputs.

### 3.1 Layout

| Region | Content | Source |
|---|---|---|
| Header | Study title, cohort sizes | `evaluation_result.json.cohort_sizes` |
| Quantitative | One card per Aspect: before/after (or single value), delta, delta_pct, significance test result | `evaluation_result.json.quantitative` |
| Qualitative | One card per Hypothesis: `match_rate` (or `rate_before`/`rate_after` for comparative), `support_count`, `rejected` flag if under `min_support`, significance | `evaluation_result.json.qualitative` |
| Artifacts | Rendered tables/plots per `suggested_plots`/`suggested_tables` from the plan | `evaluation_result.json.artifacts` |
| Narrative | `artifacts.narrative_summary` (and `recommendations` if present) | `evaluation_result.json.artifacts` |

### 3.2 Session drill-down (v1 affordance, not a tab)

- Where a hypothesis or artifact references specific `session_id`s (counter-examples, matches),
  render each as a link: `{BOTPROBE_BASE_URL}?session_id={id}`, opening BotProbe in a new tab.
- Do not build an in-app transcript viewer for v1 — that scope belongs to BotProbe.

### 3.3 Export

- "Export" affordance: download the study's `output/` JSON/CSV directly (file-based, no export
  pipeline to build — it's already sitting on disk per input_schema.md §2.8).

---

## 4. What this deliberately does NOT include (v1 scope discipline)

Cutting these is a feature of the design, not a gap to fill later without discussion:

- A studies list/dashboard screen (open question — confirm with Dwijesh if needed for demo)
- In-app session/transcript browser (that's BotProbe's job)
- Plan editing, hypothesis approve/reject, re-planning, or a feedback loop on Explore
- Exposing `min_support` / `significance_level` / `pairing_turn_tolerance` as user controls
- Any Postgres/Argus-backed data path — v1 reads Mongo directly

---

## 5. Divergence from the current `ypervaino-live` prototype

The working demo in this repo (built before draft3.md existed) differs from this spec in
ways that should NOT be treated as bugs, but do need reconciling before "v1" is real:

| Prototype has | v1 spec (draft3 + input_schema) says | Action |
|---|---|---|
| A 4th "Sessions" tab with its own transcript browser | No Sessions tab — link out to BotProbe instead | Drop the tab, or keep it labeled clearly as a temporary BotProbe stand-in |
| Per-hypothesis approve/reject toggles on Explore | Explore is read-only + single Execute button | Simplify Explore to match |
| `min_support` / `significance_level` as user-facing Advanced Settings | Hidden backend defaults | Move to backend constants, remove from New Study form |
| SQLite + synthetic seeded data | Direct MongoDB read (v1), file-based study persistence | Pending: real `MONGO_URI` — see "mongo thing" |
| Stateless (no saved studies) | File-based persistence per `study_title` under `studies/` | Add once backend is being rebuilt to spec |

---

## 6. Document history

| Version | Date | Notes |
|---------|------|-------|
| v1 | 2026-08-29 | First UI design pass against draft3.md + input_schema.md |
