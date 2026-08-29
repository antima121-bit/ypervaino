# Ypervaíno — UI Design (v1)

**Source of truth:** [draft3.md](./draft3.md), [input_schema.md](./input_schema.md)
**Scope:** Screen-by-screen UI spec for the 3 v1 tabs — layout, every field, every state
(loading / empty / error), copy, and interaction rules. Styling follows the existing
va-argus dark theme (IBM Plex Sans/Mono, teal accent, RED/YELLOW/GREEN semantic colors)
so it reads as one product family, not a bolted-on tool.

---

## 0. Screen inventory

| # | Tab | One-line job | Inputs | Outputs |
|---|---|---|---|---|
| 1 | **New Study** | Collect `CreateStudyRequest`, kick off Phase 0–2 | Full form (§1) | Navigates to Explore on success |
| 2 | **Explore** | Show `AnalysisPlan`, get one approval | None (read-only) + **Execute** button | Navigates to Results on completion |
| 3 | **Results** | Show `EvaluationResult` | None (read-only) | Session links out to BotProbe, export |

No 4th tab. No studies-list screen in v1 scope proper — see §7 for the recommendation on that
open question.

---

## 1. Tab: New Study

**Purpose:** Collect one `CreateStudyRequest` (input_schema.md §1.1), submit it, and hand off to Explore.

### 1.1 Layout sketch

```
┌─────────────────────────────────────────────────────────────┐
│  New Study                                                   │
│  Study title  [________________________________]             │
│  Study type   ( Comparative )  ( Single Cohort )              │
│                                                                │
│  ── What changed? (optional) ─────────────────────────────    │
│  Description  [                                    ]          │
│  PR / MR link [________________________________]              │
│                                                                │
│  ── Scope ─────────────────────────────────────────────────   │
│  Tenant [▾]   Assistant [▾]   Assistant version [▾, optional]  │
│  Channel  ( Voice )  ( Chat )                                  │
│                                                                │
│   -- comparative --              -- single cohort --          │
│   Before window [date–date]      Window [date–date]           │
│   After  window [date–date]                                   │
│                                                                │
│  ── Cohort filters (optional) ─────────────────────────────    │
│  [Main stream model is…] [Purpose used] [Skill active]         │
│  [Guardrails triggered] [Transfer happened] [Interruption]     │
│  Traffic split: dimension [___] value [___]                    │
│                                                                │
│  ── Sampling ──────────────────────────────────────────────    │
│  Exploration size (n_explore) [100]                            │
│  Evaluation size  ( All )  ( Custom: [_____] )                 │
│                                                                │
│                                   [ Start Analysis → ]         │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Fields, in form order

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
| Cohort filters | `cohort_filters[]` | multi-select chip list, sourced from the filter-atom registry (§2.3) | no | See §1.3 below |
| Cohort filters | `traffic_split` | two linked inputs: dimension + value | no | e.g. `canary_variant` = `treatment` |
| Sampling | `n_explore` | number input | no, default 100 | Must be **even** when `study_type == comparative` |
| Sampling | `n_eval` | number input **or** "All" toggle | no, default "all" | |
| Sampling | `n_eval_before` / `n_eval_after` | number inputs, shown only in comparative mode, only if user overrides `n_eval` | no | |

**Explicitly NOT on this form** (input_schema.md §1.1 "hidden defaults"): `min_support`,
`significance_level`, `pairing_turn_tolerance`. These are backend constants for v1 — do not
add an "Advanced settings" section exposing them.

### 1.3 Cohort filter chips (v1 fixed set)

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

### 1.4 Comparative-mode constraint

When `study_type == "comparative"`: `tenant`, `assistant_origin_id`, and `channel` are shared
across both windows — render them once, not duplicated per window. Only the two date ranges differ.

### 1.5 Validation (client-side, before submit)

| Rule | Error copy |
|---|---|
| `study_title` empty | "Give this study a name." |
| `study_title` not unique | "A study called '{title}' already exists. Pick a different name." |
| `tenant` / `assistant_origin_id` unset | "Choose a tenant and assistant." |
| Date range missing/incomplete for the selected `study_type` | "Set the {before/after/} date range." |
| `date_range_before` end date is after `date_range_after` start date (overlap) | "Before and after windows overlap — pick non-overlapping ranges." |
| `n_explore` odd, `study_type == comparative` | "Exploration size must be even in Comparative mode (splits evenly before/after)." |
| `n_explore` < 4 | "Pick at least 4 — anything smaller isn't a useful sample." |
| Cohort filter chip selected but its value field is empty (e.g. "Skill active" with no skill named) | "Add a value for '{chip label}', or remove the filter." |

Block submit until all raised errors clear; show inline, next to the offending field — not a
single toast at the top.

### 1.6 Submit / progress / error states

- Button: **"Start Analysis"**, disabled while any validation error is showing.
- **Submitting:** button becomes a spinner + "Starting…"; whole form becomes read-only (no
  editing mid-submit).
- **Progress** (Phase 0–2 running server-side): replace the form with a simple step tracker,
  polling `meta.json.status`:
  ```
  ● Resolving cohort         (status: created)
  ○ Sampling conversations
  ○ Generating plan
  ```
  Each step fills in as the backend advances; this is display-only, not literally 3 separate
  API calls — poll one status field and map it to step-completion.
- **Success** (`status == "explored"`): auto-navigate to **Explore** for this study.
- **Failure** (`status == "failed"`): stay on **New Study**, keep the filled-in form values,
  show an error banner above the submit button with the message from `meta.json.error`
  (e.g. "Cohort resolution failed: no sessions matched this scope — try widening the date
  range or removing a cohort filter."). Do **not** silently retry.
- **Empty cohort edge case**: if Phase 0 resolves zero sessions, treat as a `failed` status
  with that specific message rather than proceeding to an empty Phase 1.

---

## 2. Tab: Explore

**Purpose:** Read-only display of the `AnalysisPlan` Phase 2 produced. One action: **Execute**.

### 2.1 Layout sketch

```
┌─────────────────────────────────────────────────────────────┐
│  {study_title}                    [Comparative]  [Execute →]  │
│  Before: 1,842 sessions   After: 1,901 sessions                │
│                                                                │
│  ── What we found ─────────────────────────────────────────    │
│  "{exploration_summary — 2-4 sentence narrative}"               │
│                                                                │
│  ── Proposed aspects ──────────────────────────────────────    │
│  • Speed — {description}                                       │
│  • Failures — {description}                                    │
│  • Conversation length — {description}                         │
│  Suggested plots/tables: {labels only, no data yet}             │
│                                                                │
│  ── Proposed hypotheses ───────────────────────────────────    │
│  ┌ {title} ──────────────────────────────────────────────┐    │
│  │ {description}                                          │    │
│  │ signals used: opening_intent_class, transfer_executed…  │    │
│  └─────────────────────────────────────────────────────────┘   │
│  (repeat per hypothesis)                                        │
│                                                                │
│                                              [ Execute plan ]   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Layout regions

| Region | Content | Source |
|---|---|---|
| Header | Study title, study type badge, cohort sizes after Phase 0 | `meta.json`, `cohort_stats.json` |
| Summary card | `exploration_summary` narrative | `analysis_plan.json` |
| Quantitative section | Proposed **aspects** (name + description), suggested plot/table specs (labels only — no live charts, no data exists until Phase 3) | `analysis_plan.json.quantitative` |
| Qualitative section | Proposed **hypotheses**: title, description, signal names referenced (no raw predicate syntax shown to the user) | `analysis_plan.json.qualitative` |

### 2.3 The one interaction

- Single primary button: **"Execute plan"** (also mirrored at the top-right of the header for
  long plans, so the user isn't forced to scroll back up).
- **No** per-aspect or per-hypothesis include/exclude toggles. **No** edit-in-place. **No**
  "regenerate" or feedback box. This is a deliberate v1 constraint (draft3 §14, §2 table) —
  do not add approval granularity here even if it looks like an obvious improvement; scope
  changes go through a **new study**, not a plan revision.
- On click: POST execute → sets `analysis_plan.user_approved = true`, study status → `running`
  → Phase 3 runs → on completion, status → `complete` → navigate to **Results**.

### 2.4 States

- **Loading** (this tab reached before `analysis_plan.json` exists — shouldn't normally happen
  since New Study only navigates here once `explored`, but guard anyway): full-page spinner,
  "Loading plan…".
- **Executing** (Phase 3 running): replace the Execute button with a disabled spinner state
  ("Running evaluation…"); the plan content above stays visible (read-only) so the user can
  keep reviewing while it runs. Poll `meta.json.status` for `running` → `complete`/`failed`.
- **Execution failed**: banner above the plan: "Evaluation failed: {error}. The plan is
  unchanged — you can retry Execute, or start a new study." Execute button re-enabled.
- **Zero hypotheses** (Phase 2 produced aspects only — e.g. an extremely narrow or very clean
  cohort): show the quantitative section, and in place of the qualitative section a plain note:
  "No hypotheses were proposed from this sample — the aspects above will still be evaluated."
  Execute still runs (aspects-only evaluation).
- **Zero aspects AND zero hypotheses** (degenerate plan): treat as a Phase 2 failure, not a
  valid empty plan — show the same failure banner as New Study's `failed` status, with Execute
  disabled and a link back to New Study.

---

## 3. Tab: Results

**Purpose:** Read-only view of `EvaluationResult`. No inputs.

### 3.1 Layout sketch

```
┌─────────────────────────────────────────────────────────────┐
│  {study_title}                                   [Export ↓]   │
│  Before: 1,842 sessions   After: 1,901 sessions                │
│                                                                │
│  ── Aspects ───────────────────────────────────────────────    │
│  ┌ Speed ──────────┐ ┌ Failures ───────┐ ┌ Conv. length ────┐  │
│  │ before  410ms    │ │ before  3.1%    │ │ before  6.2 turns│  │
│  │ after   585ms    │ │ after   7.8%    │ │ after   6.6 turns│  │
│  │ +42.7% significant│ │ +151% significant│ │ +6.5% not sig. │  │
│  └──────────────────┘ └─────────────────┘ └──────────────────┘  │
│                                                                │
│  ── Hypotheses ────────────────────────────────────────────    │
│  ┌ {title} ──────────────────────────────────────────────┐    │
│  │ before 4.2%  after 18.6%  p<0.001  significant          │    │
│  │ 171 matching sessions → [view in BotProbe]              │    │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
│  ── Summary ───────────────────────────────────────────────    │
│  "{narrative_summary}"                                          │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Layout regions

| Region | Content | Source |
|---|---|---|
| Header | Study title, cohort sizes | `evaluation_result.json.cohort_sizes` |
| Quantitative | One card per Aspect: before/after (or single value for `SingleCohortStudy`), delta, delta_pct, significance test result | `evaluation_result.json.quantitative` |
| Qualitative | One card per Hypothesis: `match_rate` (or `rate_before`/`rate_after` for comparative), `support_count`, `rejected` flag if under `min_support`, significance | `evaluation_result.json.qualitative` |
| Artifacts | Rendered tables/plots per `suggested_plots`/`suggested_tables` from the plan | `evaluation_result.json.artifacts` |
| Narrative | `artifacts.narrative_summary` (and `recommendations` if present) | `evaluation_result.json.artifacts` |

### 3.3 Rejected hypothesis treatment

A hypothesis with `rejected: true` (support below `min_support`) still renders — visibly
de-emphasized (lower opacity, a small "below minimum sample size" tag) rather than hidden.
Hiding it would look like the system silently dropped a claim; showing it de-emphasized makes
the min_support gate legible (matches draft3 §13's intent: "technically true but rejected").

### 3.4 Session drill-down (v1 affordance, not a tab)

- Where a hypothesis or artifact references specific `session_id`s (counter-examples, matches),
  render each as a link: `{BOTPROBE_BASE_URL}?session_id={id}`, opening BotProbe in a new tab.
- Do not build an in-app transcript viewer for v1 — that scope belongs to BotProbe.
- If `BOTPROBE_BASE_URL` isn't configured (e.g. local/demo environment), render the session ids
  as plain (non-clickable) monospace text instead of a dead link.

### 3.5 Export

- "Export" button (top-right of header): downloads the study's `output/` JSON/CSV directly —
  file-based, no export pipeline to build, it's already sitting on disk (input_schema.md §2.8).

### 3.6 States

- **Loading**: full-page spinner, "Loading results…" — should be near-instant since this tab is
  only reachable once `evaluation_result.json` exists.
- **No comparative delta available** (`SingleCohortStudy`, or pure discovery): aspect cards show
  a single value, no before/after columns, no significance test row.
- **Empty artifacts**: if `suggested_plots`/`suggested_tables` was empty in the plan, omit the
  Artifacts region entirely rather than showing an empty box.

---

## 4. What this deliberately does NOT include (v1 scope discipline)

Cutting these is a feature of the design, not a gap to fill later without discussion:

- A studies list/dashboard screen as part of the 3-tab spec — see §7 for the recommendation
- In-app session/transcript browser (that's BotProbe's job)
- Plan editing, hypothesis approve/reject, re-planning, or a feedback loop on Explore
- Exposing `min_support` / `significance_level` / `pairing_turn_tolerance` as user controls
- Any Postgres/Argus-backed data path — v1 reads Mongo directly

---

## 5. Cross-cutting interaction rules

- **Navigation is one-directional per study**: New Study → Explore → Results. There's no "back
  to Explore" from Results in v1 (the plan is immutable once executed) and no "back to New
  Study" from Explore except via the failure banner's escape hatch (§2.4).
- **No optimistic UI**: every state transition (submit, execute) waits for the backend's actual
  status field rather than assuming success client-side — Phase 0–3 durations are unpredictable
  (Mongo query size, LLM latency), so a fake "done" would be actively misleading.
- **Numbers are never invented client-side**: percentages, deltas, and significance labels are
  rendered exactly as computed server-side in `EvaluationResult` — no client-side rounding
  decisions beyond display formatting (e.g. 1 decimal place for percentages).
- **Copy tone**: direct, specific, no apologetic hedging in error states ("Cohort resolution
  failed: no sessions matched this scope" not "Oops, something went wrong!").

---

## 6. Visual language (inherited, not new)

No new design system — extend va-argus's existing tokens so Ypervaíno reads as a feature of
the same product, not a separate tool:

| Token | Value | Use |
|---|---|---|
| `--signal` (teal) | `#3fe0d6` | Primary actions (Start Analysis, Execute plan) |
| `--success` / `--warning` / `--critical` | green / amber / red | Significant-good, not-significant, significant-bad deltas |
| `--surface`, `--line` | dark card backgrounds, hairline borders | Cards for aspects/hypotheses |
| IBM Plex Sans / IBM Plex Mono | body / data | Mono for session ids, model ids, numbers in tables |

---

## 7. Open question, resolved: studies list

draft3.md doesn't specify a studies-list screen, but v1 has file-based persistence
(`studies/<slug>/`) which implies studies accumulate on disk with no way to get back to one
after leaving it — a real gap for a multi-study demo, not just a nice-to-have.

**Recommendation:** add a lightweight 4th surface, not a 4th tab — a dropdown or small list
under the product name in the header ("My Studies") that reads `studies/*/meta.json` and links
straight to that study's current tab (Explore if `explored`, Results if `complete`, New Study
form pre-filled if `failed` and the user wants to retry). This keeps the 3-tab pipeline model
intact while not stranding every study after the first. **Confirm with Dwijesh before building**
— this is a proposal, not something draft3.md asked for.

---

## 8. Document history

| Version | Date | Notes |
|---------|------|-------|
| v1 | 2026-08-29 | First UI design pass against draft3.md + input_schema.md |
| v1.1 | 2026-08-29 | Added wireframe sketches, validation copy, full loading/empty/error states for all 3 tabs, cross-cutting interaction rules, visual token table, and a resolved recommendation for the studies-list open question |
