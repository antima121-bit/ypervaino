# Ypervaíno — HTTP API (v1)

**Related:** [input_schema.md](./input_schema.md) (request bodies), [output_schema.md](./output_schema.md) (response shapes), [architecture.md](./architecture.md) (StudyRunner), [UI_design.md](./UI_design.md) (tab flow)

Thin REST layer over **StudyRunner**. All study artifacts are persisted under `studies/{slug}/` on disk; API endpoints read/write via StudyStore.

**Reference data:** sample event shapes for development live in [`sample_data/sample_logs.txt`](./sample_data/sample_logs.txt) (event types + `event_value` metadata from real logs).

---

## 1. Conventions

| Item | Value |
|------|--------|
| Base URL (local) | `http://localhost:8765` |
| API prefix | `/api/v1/ypervaino` |
| Content-Type | `application/json` (requests and JSON responses) |
| Auth | None in v1 (local / internal tool) |
| Study key | `{slug}` — filesystem-safe id from `study_title` |
| Timestamps | ISO 8601 with timezone |

### 1.1 Error envelope

All error responses use:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable description",
    "details": {}
  }
}
```

| HTTP | `code` | When |
|------|--------|------|
| 400 | `VALIDATION_ERROR` | Invalid CreateStudyRequest, bad slug, plan not approvable |
| 404 | `NOT_FOUND` | Unknown study slug |
| 409 | `CONFLICT` | Duplicate `study_title` |
| 409 | `INVALID_STATE` | Execute on wrong status, Phase 3 already running |
| 500 | `INTERNAL_ERROR` | Unhandled pipeline failure |
| 503 | `UPSTREAM_ERROR` | Mongo, BotProbe trace API, Bot API, or LLM unavailable |

On pipeline failure StudyRunner sets `meta.json` → `status: "failed"` and `error`; poll endpoints return that message.

### 1.2 Long-running work

Phases 0–2 (submit) and Phase 3 (execute) run **asynchronously** in a background worker thread. The HTTP handler returns immediately with current `status`; the UI **polls** until terminal state.

| Phase | Trigger | Running status | Terminal success | Terminal failure |
|-------|---------|----------------|------------------|------------------|
| 0–2 | `POST /studies` | `created` | `explored` | `failed` |
| 3 | `POST /studies/{slug}/execute` | `running` | `complete` | `failed` |

**Poll interval (UI):** 2–5 s. No WebSockets in v1.

---

## 2. Static pages

| Path | Tab |
|------|-----|
| `GET /` or `GET /new-study` | New Study |
| `GET /explore?study={slug}` | Explore |
| `GET /results?study={slug}` | Results |

Pages call the JSON API below. `study` query param identifies the study slug.

---

## 3. Lookup endpoints (New Study form)

### 3.1 List tenants

```
GET /api/v1/ypervaino/tenants
```

**Response 200:**

```json
{
  "tenants": ["resound", "acme", "..."]
}
```

**Source:** Mongo `AssistantSession.distinct("tenant")`.

---

### 3.2 List assistants for tenant

```
GET /api/v1/ypervaino/assistants?tenant={tenant}
```

| Query | Required |
|-------|----------|
| `tenant` | yes |

**Response 200:**

```json
{
  "assistants": [
    {
      "assistant_origin_id": "875df174-e8ad-419d-8269-5b064593f865",
      "label": "Resound Voice Assistant",
      "published_versions": [
        { "assistant_id": "abc-123", "label": "v42 — 2026-08-20" }
      ]
    }
  ]
}
```

**Source:** Mongo session index / assistant metadata (exact query TBD in implementation).

---

### 3.3 Check study title availability

```
GET /api/v1/ypervaino/studies/check-title?title={study_title}
```

**Response 200:**

```json
{
  "title": "My Study",
  "slug": "my-study",
  "available": true
}
```

If slug exists (with or without numeric suffix collision rules): `"available": false`.

---

### 3.4 Cohort filter atom registry

```
GET /api/v1/ypervaino/config/filter-atoms
```

**Response 200:** static registry for UI chips ([input_schema.md](./input_schema.md) §2.3).

```json
{
  "atoms": [
    {
      "atom_id": "main_stream_model_is",
      "label": "Main stream model is…",
      "value_required": true,
      "value_type": "string"
    },
    {
      "atom_id": "guardrail_triggered",
      "label": "Guardrails triggered",
      "value_required": false
    }
  ]
}
```

---

## 4. Study lifecycle

### 4.1 Create study (Phase 0 → 2)

```
POST /api/v1/ypervaino/studies
```

**Request body:** `CreateStudyRequest` — see [input_schema.md](./input_schema.md) §1.4.

**Server actions:**

1. Validate body (same rules as [UI_design.md](./UI_design.md) §1.5 + server-side checks).
2. Compile → `StudyQuery`; write `input/create_study.json`, `input/study_query.json`.
3. Write `meta.json` with `status: "created"`.
4. Start background job: Phase 0 → 1 → 2.
5. Return `202 Accepted` with metadata.

**Response 202:**

```json
{
  "slug": "resound-qwen-10-aug-20-22",
  "title": "Resound Qwen 10% Aug 20-22",
  "status": "created",
  "poll_url": "/api/v1/ypervaino/studies/resound-qwen-10-aug-20-22/status"
}
```

**Response 409:** duplicate title (`CONFLICT`).

---

### 4.2 Get study metadata

```
GET /api/v1/ypervaino/studies/{slug}
```

**Response 200:** [StudyMetadata](./output_schema.md#2-studymetadata)

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

### 4.3 Poll study status (New Study progress + Execute progress)

```
GET /api/v1/ypervaino/studies/{slug}/status
```

Lightweight endpoint for UI spinners. Reads `meta.json` plus optional progress hints from intermediate files.

**Response 200:**

```json
{
  "slug": "resound-qwen-10-aug-20-22",
  "status": "created",
  "error": null,
  "progress_hints": {
    "cohort_stats_ready": true,
    "s_explore_ready": false,
    "analysis_plan_ready": false
  }
}
```

| Field | Meaning |
|-------|---------|
| `progress_hints.cohort_stats_ready` | `intermediate/cohort_stats.json` exists |
| `progress_hints.s_explore_ready` | `intermediate/s_explore/manifest.json` exists |
| `progress_hints.analysis_plan_ready` | `intermediate/analysis_plan.json` exists |

When `status == "failed"`, `error` is set ([UI_design.md](./UI_design.md) §1.6).

When `status == "explored"`, UI navigates to Explore tab.

When `status == "complete"`, UI navigates to Results tab.

---

## 5. Explore tab

### 5.1 Get explore payload

```
GET /api/v1/ypervaino/studies/{slug}/explore
```

**Requires:** `status` ∈ `{ "explored", "running", "complete" }` (plan must exist).

**Response 200:**

```json
{
  "meta": {
    "title": "Resound Qwen 10% Aug 20-22",
    "slug": "resound-qwen-10-aug-20-22",
    "status": "explored"
  },
  "cohort_stats": { },
  "analysis_plan": { }
}
```

- `cohort_stats` — [CohortStats](./output_schema.md#6-cohortstats) (cohort sizes, `n_explore`).
- `analysis_plan` — [AnalysisPlan](./output_schema.md#11-analysisplan) (`user_approved` false until execute).

**Response 404:** study not found.  
**Response 409:** plan not ready yet (`status == "created"`).

**UI mapping:** [UI_design.md](./UI_design.md) §2 — read-only; no computed hypothesis numbers on this tab.

---

### 5.2 Execute plan (Phase 3)

```
POST /api/v1/ypervaino/studies/{slug}/execute
```

**Request body:** empty `{}` (v1 has no per-hypothesis toggles).

**Requires:** `status == "explored"` and `analysis_plan.user_approved == false`.

**Server actions:**

1. Set `analysis_plan.user_approved = true`.
2. Set `meta.status = "running"`.
3. Start background Phase 3 job.
4. Return `202 Accepted`.

**Response 202:**

```json
{
  "slug": "resound-qwen-10-aug-20-22",
  "status": "running",
  "poll_url": "/api/v1/ypervaino/studies/resound-qwen-10-aug-20-22/status"
}
```

**Response 409:** wrong status or already approved / running.

UI polls §4.3 until `status == "complete"` or `failed`, then navigates to Results.

---

## 6. Results tab

### 6.1 Get evaluation result

```
GET /api/v1/ypervaino/studies/{slug}/results
```

**Requires:** `status == "complete"`.

**Response 200:**

```json
{
  "meta": {
    "title": "Resound Qwen 10% Aug 20-22",
    "slug": "resound-qwen-10-aug-20-22",
    "status": "complete"
  },
  "cohort_stats": { },
  "evaluation_result": { }
}
```

- `evaluation_result` — [EvaluationResult](./output_schema.md#13-evaluationresult) including `artifacts.plots`, `artifacts.tables`, `narrative_summary`.

**Response 409:** evaluation not finished (`status` is `running` or earlier).

---

### 6.2 Download artifact file

```
GET /api/v1/ypervaino/studies/{slug}/artifacts/{path}
```

| Param | Example |
|-------|---------|
| `path` | `plots/speed_bar.png`, `tables/hypothesis_summary.csv` |

Serves files under `studies/{slug}/output/`. Path must not escape study directory (no `..`).

**Response 200:** file bytes with appropriate `Content-Type`.

---

### 6.3 Export study bundle

```
GET /api/v1/ypervaino/studies/{slug}/export
```

**Response 200:** `application/zip` stream of `output/` (and optionally key intermediates).

**Requires:** `status == "complete"`.

Alternative v1: return JSON listing downloadable paths instead of zip — implementation choice; UI only needs one stable export action ([UI_design.md](./UI_design.md) §3.5).

---

## 7. Optional debug endpoints (v1.1)

Not required for the 3-tab UI; useful during development against real Mongo data.

### 7.1 Session transcript preview

```
GET /api/v1/ypervaino/sessions/{session_id}/transcript?tenant={tenant}
```

**Response 200:** turn list from Mongo `SessionRequest` ([MONGO_LOOKUP.md](./MONGO_LOOKUP.md) §3). Full event trace for pipeline use comes from BotProbe `/trace` (§4 same doc).

### 7.2 Cohort size estimate (dry run)

```
POST /api/v1/ypervaino/cohort/preview
```

**Request body:** subset of `CreateStudyRequest` scope fields (tenant, dates, filters).

**Response 200:**

```json
{
  "candidate_count": 2100,
  "after_predicate_estimate": null
}
```

Runs Phase 0 index query only — no LLM, no plan. Helps validate scope before submit.

---

## 8. End-to-end flow (API sequence)

```
New Study tab
  GET  /tenants
  GET  /assistants?tenant=...
  GET  /config/filter-atoms
  GET  /studies/check-title?title=...
  POST /studies                          → 202, status: created
  GET  /studies/{slug}/status            → poll until explored | failed

Explore tab
  GET  /studies/{slug}/explore           → analysis_plan + cohort_stats
  POST /studies/{slug}/execute           → 202, status: running
  GET  /studies/{slug}/status            → poll until complete | failed

Results tab
  GET  /studies/{slug}/results           → evaluation_result
  GET  /studies/{slug}/artifacts/...     → PNG / CSV
  GET  /studies/{slug}/export            → zip (optional)
```

---

## 9. Implementation notes

| Topic | Decision |
|-------|----------|
| Worker model | Single background thread per study job in v1; no Redis queue |
| Idempotency | `POST /execute` rejected if already `running` or `complete` |
| CORS | Enable for local dev if UI served separately |
| Mongo | Read-only session index; `MONGO_URI` / `MONGO_DB_NAME` |
| Event traces | BotProbe `GET /trace`; `BOTPROBE_TRACE_BASE_URL` / `BOTPROBE_TRACE_ENV` |
| LLM keys | `OPENAI_API_KEY`, optional `GEMINI_API_KEY` for fallback |
| BotProbe links | Client-side only: `BOTPROBE_BASE_URL?session_id={id}` — same id as `/trace` input |

Event field paths for primitives and filters: [`config/event_schema.json`](./config/event_schema.json) (validated against BotProbe `/trace` samples and [`sample_data/sample_logs.txt`](./sample_data/sample_logs.txt)).

---

## 10. Document history

| Version | Date | Notes |
|---------|------|-------|
| v1 | 2026-08-30 | Initial API contract: lookup, study lifecycle, explore, execute, results, export |
| v1.1 | 2026-08-30 | Dual-source data: Mongo session index + BotProbe `/trace` for events |
