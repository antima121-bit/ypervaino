# Ypervaíno — HTTP API (v1)

**Related:** [input_schema.md](./input_schema.md) (request bodies), [output_schema.md](./output_schema.md) (response shapes), [proposal_contract.md](./proposal_contract.md) (Proposals tab), [architecture.md](./architecture.md) (StudyRunner), [UI_design.md](./UI_design.md) (tab flow)

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
| 409 | `INVALID_STATE` | Execute on wrong status, Phase 3 already running, Proposals tab before `complete` |
| 409 | `GENERATION_IN_PROGRESS` | Duplicate `POST …/proposals/generate` while Phase 4 running |
| 409 | `PROPOSAL_CONFLICT` | Apply shallow proposal when `target_key` already applied |
| 409 | `APPLY_FAILED` | Patch anchor/field not found in blueprint |
| 409 | `PROPOSAL_NOT_PENDING` | Apply/reject on non-pending proposal |
| 500 | `INTERNAL_ERROR` | Unhandled pipeline failure |
| 503 | `UPSTREAM_ERROR` | Mongo, BotProbe trace API, Bot API, or LLM unavailable |

On pipeline failure StudyRunner sets `meta.json` → `status: "failed"` and `error`; poll endpoints return that message.

### 1.2 Long-running work

Phases 0–2 (submit) and Phase 3 (execute) run **asynchronously** in a background worker thread. The HTTP handler returns immediately with current `status`; the UI **polls** until terminal state.

| Phase | Trigger | Running status | Terminal success | Terminal failure |
|-------|---------|----------------|------------------|------------------|
| 0–2 | `POST /studies` | `created` | `explored` | `failed` |
| 3 | `POST /studies/{slug}/execute` | `running` | `complete` | `failed` |
| 4 | `POST /studies/{slug}/proposals/generate` | `generating`* | `ready`* | `failed`* |

\*Phase 4 job state is in `intermediate/proposal_generation/status.json`; study `meta.status` stays `complete`.

**Poll interval (UI):** 2–5 s. No WebSockets in v1.

---

## 2. Static pages

| Path | Tab |
|------|-----|
| `GET /` or `GET /new-study` | New Study |
| `GET /explore?study={slug}` | Explore |
| `GET /results?study={slug}` | Results |
| `GET /proposals?study={slug}` | Proposals |

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

## 7. Proposals tab

**Contract:** [proposal_contract.md](./proposal_contract.md) — full request/response shapes, storage paths, and error codes.

**Requires:** `meta.status == "complete"` and `output/evaluation_result.json` exist.

Phase 4 runs **on demand** when the user triggers generation. Study status does not change during Phase 4.

### 7.1 Get proposal status + bundle

```
GET /api/v1/ypervaino/studies/{slug}/proposals
```

**Response 200:**

```json
{
  "meta": {
    "title": "qwen swap",
    "slug": "qwen-swap-6",
    "status": "complete"
  },
  "generation": {
    "status": "not_started",
    "started_at": null,
    "finished_at": null,
    "error": null,
    "logs_url": "/api/v1/ypervaino/studies/qwen-swap-6/logs?tail=100"
  },
  "bundle": null,
  "blueprint": {
    "current_version": "v0001",
    "manifest_url": "/api/v1/ypervaino/studies/qwen-swap-6/blueprint/manifest"
  }
}
```

| `generation.status` | Meaning |
|---------------------|---------|
| `not_started` | User has not triggered Phase 4 |
| `generating` | Phase 4 running — poll this endpoint |
| `ready` | `bundle` populated (`output/proposal_bundle.json`) |
| `failed` | `generation.error` set |

When `ready`, `bundle` is a [ProposalBundle](./proposal_contract.md#41-proposalbundle) (`shallow_proposals[]`, `deep_proposals[]`).

**Response 409:** study not `complete` (`INVALID_STATE`).

---

### 7.2 Generate proposals (Phase 4, on demand)

```
POST /api/v1/ypervaino/studies/{slug}/proposals/generate
```

**Request body:** empty `{}`.

**Requires:** `status == "complete"`.

If already `generating`, return `202` with current job (no duplicate worker). If already `ready`, return `200` with existing bundle unless `?force=true` (optional).

**Response 202:**

```json
{
  "slug": "qwen-swap-6",
  "generation": {
    "status": "generating",
    "started_at": "2026-09-01T17:30:00+05:30",
    "poll_url": "/api/v1/ypervaino/studies/qwen-swap-6/proposals"
  }
}
```

UI polls §7.1 every 2–3 s until `ready` or `failed`.

---

### 7.3 Blueprint version manifest

```
GET /api/v1/ypervaino/studies/{slug}/blueprint/manifest
```

**Response 200:** [BlueprintVersionManifest](./proposal_contract.md#47-blueprintversionmanifest).

---

### 7.4 Get blueprint JSON by version

```
GET /api/v1/ypervaino/studies/{slug}/blueprint/versions/{version}
```

| Param | Example |
|-------|---------|
| `version` | `v0001`, `v0003`, or `current` |

**Response 200:**

```json
{
  "version": "v0003",
  "created_at": "2026-09-01T17:45:00+05:30",
  "source": "proposal_apply",
  "source_proposal_id": "prop-transfer-tool-main-auth",
  "parent_version": "v0002",
  "blueprint": { }
}
```

`blueprint` is the full VA Blueprint payload (same shape as VA Blueprint API `extract_blueprint`).

---

### 7.5 Apply one shallow proposal

```
POST /api/v1/ypervaino/studies/{slug}/proposals/{proposal_id}/apply
```

**Request body:** empty `{}`.

**Requires:** `generation.status == "ready"`, proposal `status == "pending"`, no other `applied` proposal with same `target_key`.

**Response 200:**

```json
{
  "proposal_id": "prop-transfer-tool-main-auth",
  "proposal_status": "applied",
  "applied_at": "2026-09-01T17:45:00+05:30",
  "blueprint": {
    "previous_version": "v0002",
    "new_version": "v0003",
    "manifest": { }
  },
  "apply_result": {
    "success": true,
    "ops_applied": 2,
    "warnings": []
  }
}
```

Each successful apply writes a new immutable version under `intermediate/blueprint/versions/`.

**Response 409:** `PROPOSAL_CONFLICT`, `APPLY_FAILED`, or `PROPOSAL_NOT_PENDING`.

---

### 7.6 Reject proposal (shallow or deep)

```
POST /api/v1/ypervaino/studies/{slug}/proposals/{proposal_id}/reject
```

**Request body (optional):**

```json
{ "reason": "Already fixed in prod" }
```

**Response 200:** `{ "proposal_id": "...", "proposal_status": "rejected" }`

---

### 7.7 Acknowledge deep proposal

```
POST /api/v1/ypervaino/studies/{slug}/proposals/{proposal_id}/acknowledge
```

**Response 200:** `{ "proposal_id": "...", "proposal_status": "acknowledged" }`

---

### 7.8 Create Jira ticket (stub)

```
POST /api/v1/ypervaino/studies/{slug}/proposals/{proposal_id}/jira-stub
```

**Response 200 (v1 — no real Jira API):**

```json
{
  "proposal_id": "prop-backend-transfer-signal",
  "stub": true,
  "ticket_draft": {
    "summary": "Add rule-based transfer_tool_invoked primitive",
    "description": "…",
    "labels": ["ypervaino", "voice-bot"],
    "study_slug": "qwen-swap-6",
    "evidence_session_ids": ["57e2f8b3-6a9f-4cca-ad1e-fcfc22e7f115"]
  },
  "message": "Jira integration not configured; copy draft to create ticket manually."
}
```

---

### 7.9 Manual blueprint patch (optional)

```
POST /api/v1/ypervaino/studies/{slug}/blueprint/patch
```

**Request body:** `{ "target": BlueprintTarget, "patch": BlueprintPatch, "note?": string }` — same shapes as shallow proposals ([proposal_contract.md §4.5–4.6](./proposal_contract.md#45-blueprinttarget)).

**Response 200:** same as §7.5 apply success (`new_version`, `apply_result`).

---

### 7.10 Blueprint diff (optional)

```
GET /api/v1/ypervaino/studies/{slug}/blueprint/diff?from=v0001&to=v0003&target_key=skill:Main_Auth:instructions
```

**Response 200:** `{ from_version, to_version, target_key, before_excerpt, after_excerpt, unified_diff? }`

If unimplemented, UI uses `patch.preview` on the proposal card.

**UI mapping:** [UI_design.md](./UI_design.md) §4.

---

## 8. Optional debug endpoints (v1.1)

Not required for the 4-tab UI; useful during development against real Mongo data.

### 8.1 Session transcript preview

```
GET /api/v1/ypervaino/sessions/{session_id}/transcript?tenant={tenant}
```

**Response 200:** turn list from Mongo `SessionRequest` ([MONGO_LOOKUP.md](./MONGO_LOOKUP.md) §3). Full event trace for pipeline use comes from BotProbe `/trace` (§4 same doc).

### 8.2 Cohort size estimate (dry run)

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

## 9. End-to-end flow (API sequence)

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

Proposals tab  (requires status: complete)
  GET  /studies/{slug}/proposals         → generation status + bundle
  POST /studies/{slug}/proposals/generate → 202, generation: generating
  GET  /studies/{slug}/proposals         → poll until ready | failed
  GET  /studies/{slug}/blueprint/versions/current → workspace viewer
  POST /studies/{slug}/proposals/{id}/apply       → new blueprint version (per proposal)
  POST /studies/{slug}/proposals/{id}/reject
  POST /studies/{slug}/proposals/{id}/acknowledge  (deep only)
  POST /studies/{slug}/proposals/{id}/jira-stub    (deep only, stub)
```

---

## 10. Implementation notes

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

## 11. Document history

| Version | Date | Notes |
|---------|------|-------|
| v1 | 2026-08-30 | Initial API contract: lookup, study lifecycle, explore, execute, results, export |
| v1.1 | 2026-08-30 | Dual-source data: Mongo session index + BotProbe `/trace` for events |
| v1.2 | 2026-09-01 | Proposals tab (Phase 4): generate, apply, blueprint versioning — see [proposal_contract.md](./proposal_contract.md) |
