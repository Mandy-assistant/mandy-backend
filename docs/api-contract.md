# Mandy API contract (v1)

Shared by `mandy-backend` (FastAPI) and `mandy-frontend` (Next.js). Change both sides together.

## Topology (local dev)

| Piece     | URL / port                                  |
| --------- | ------------------------------------------- |
| Frontend  | http://localhost:3001                       |
| API       | http://localhost:8000, routes under `/api/v1` |
| Postgres  | docker, host port **5433** (5432 is taken by a local Postgres) |
| Redis     | docker, host port 6379                      |

The frontend calls **`/api/v1/...` on its own origin**; Next.js rewrites it to `http://localhost:8000/api/v1/...`.
So auth cookies are first-party for `localhost:3001`, and WebAuthn `ORIGIN=http://localhost:3001`, `RP_ID=localhost`.
`CORS_ORIGINS` still allows `http://localhost:3001` for direct calls (Swagger, tests).

## Conventions

- JSON is `snake_case`. IDs are UUID strings. Datetimes are ISO-8601 UTC (`2026-11-20T09:30:00Z`); dates are `YYYY-MM-DD`.
- Errors (every non-2xx, including 422 and 404): `{"error": {"code": "JOB_NOT_FOUND", "message": "Job not found", "details": [...]}}`.
  422 `details` items: `{"field": "salary_min", "message": "..."}` (field = last element of loc; nested joined with `.`).
- Pagination: `?page=1&size=20` → `{"items": [...], "total": 42, "page": 1, "size": 20, "pages": 3}`.
- Auth: httpOnly cookies `access_token` (15 min) and `refresh_token` (7 days, path `/api/v1/auth`), SameSite=Lax, Secure outside dev.
  `Authorization: Bearer <access>` also accepted (Swagger/tests). Protected routes → 401 `UNAUTHENTICATED`.
- Another user's record → 404 (never 403).
- AI endpoints return 503 `AI_UNAVAILABLE` when `GEMINI_API_KEY` is not set, 429 `AI_RATE_LIMITED` when Gemini quota is hit.

## Endpoints

### Health
- `GET /health` → `{"status": "ok", "db": "ok", "redis": "ok"}`

### Auth (single owner, passkeys)
WebAuthn `options` are the JSON objects produced by py_webauthn `options_to_json` (parsed, not a string) — they go straight into
`@simplewebauthn/browser` `startRegistration({ optionsJSON })` / `startAuthentication({ optionsJSON })`.
`credential` is the object those functions return. Every options call returns a `flow_id`; the challenge is stored in Redis
under it for 5 minutes and deleted on first use.

- `GET /auth/status` → `{"setup_complete": bool, "owner_name": str | null, "webauthn_rp_id": "localhost"}`
- `POST /auth/setup/options` `{display_name, email}` → `{flow_id, options}` (403 `SETUP_ALREADY_COMPLETE` once a passkey exists)
- `POST /auth/setup/verify` `{flow_id, credential, device_name?}` → `{user, recovery_codes: [8 × "ABCD-EF12"]}` + cookies
- `POST /auth/login/options` → `{flow_id, options}`
- `POST /auth/login/verify` `{flow_id, credential}` → `{user}` + cookies (401 `PASSKEY_INVALID`; replay/sign_count → 401 `PASSKEY_REPLAY`)
- `POST /auth/recover` `{code}` → `{recovery_token}` (10 min, single use; 401 `RECOVERY_CODE_INVALID`)
- `POST /auth/recover/options` `{recovery_token}` → `{flow_id, options}`
- `POST /auth/recover/verify` `{recovery_token, flow_id, credential, device_name?}` → `{user}` + cookies
- `POST /auth/passkeys/options` (signed in) → `{flow_id, options}`; `POST /auth/passkeys/verify` `{flow_id, credential, device_name?}` → `Passkey`
- `GET /auth/passkeys` → `Passkey[]`; `DELETE /auth/passkeys/{id}` → 204 (409 `LAST_PASSKEY` for the last one)
- `POST /auth/recovery-codes` (signed in) → `{recovery_codes}` (replaces all old codes)
- `POST /auth/refresh` → `{user}` + new cookies; `POST /auth/logout` → 204, clears cookies; `GET /auth/me` → `User`
- `POST /auth/dev-login` → `{user}` + cookies. **Only registered when `DEV_LOGIN_ENABLED=true` and `ENV=dev`.** For local testing/e2e without an authenticator.
- Rate limit: `/auth/login/*`, `/auth/recover*` → 5 / minute / IP → 429 `RATE_LIMITED`.
- Session hint cookie: whenever the auth cookies are set (setup/verify, login/verify, recover/verify, refresh, dev-login)
  the API also sets `mandy_session=1` — path `/`, **not** httpOnly, SameSite=Lax, Secure outside dev, max-age = refresh
  token lifetime (7 days). It carries no secret. It is cleared on logout and whenever refresh fails. (`refresh_token` is
  scoped to `/api/v1/auth`, so the Next.js proxy checks `mandy_session` for an optimistic signed-in redirect.)

`User` = `{id, email, display_name, created_at}`
`Passkey` = `{id, device_name, transports: [str], created_at, last_used_at}`

### Profile
- `GET /profile`, `PUT /profile` (body = `ProfileUpdate`, all optional) → `Profile`
- `Profile` = `{full_name, email, headline, summary, location, phone, links: {github, linkedin, portfolio, website}, target_roles: [str], preferences: {locations: [str], work_modes: ["remote"|"hybrid"|"onsite"], salary_min, salary_max, currency}, completeness: 0-100, experience: Experience[], education: Education[], skills: Skill[]}`
  (`full_name`/`email` live on the user and are updated through `PUT /profile` too.)
- `GET|POST /profile/experience`, `PATCH|DELETE /profile/experience/{id}` — `Experience` = `{id, company, title, location, start_date, end_date|null, current, description, highlights: [str]}`
- `GET|POST /profile/education`, `PATCH|DELETE /profile/education/{id}` — `Education` = `{id, school, degree, field, start_date, end_date|null, grade|null, description}`
- `GET|POST /profile/skills`, `PATCH|DELETE /profile/skills/{id}` — `Skill` = `{id, name, level: beginner|intermediate|advanced, category: language|framework|tool|ml|other}`
- 422 when `end_date < start_date`.

### Resumes
- `Resume` = `{id, title, template: "modern"|"classic", content: ResumeContent, current_version, created_at, updated_at}`
- `ResumeContent` = `{header: {full_name, headline, email, phone, location, links: [{label, url}]}, sections: Section[]}`
- `Section` = `{id: str, type: "summary"|"experience"|"education"|"skills"|"projects", title, visible: bool, text: str|null, items: SectionItem[]}`
- `SectionItem` = `{id: str, title, subtitle, location, start_date, end_date, description, bullets: [str], tags: [str], url}` (all except `id` optional/nullable; strings may be empty)
- `GET /resumes` → `Resume[]` (no content needed but allowed), `POST /resumes` `{title, template, content?}`
- `GET|PATCH|DELETE /resumes/{id}` (PATCH: `{title?, template?, content?}`)
- `POST /resumes/{id}/duplicate` → `Resume`
- `POST /resumes/{id}/versions` → `ResumeVersion`; `GET /resumes/{id}/versions` → `ResumeVersion[]` (newest first);
  `POST /resumes/{id}/versions/{version}/restore` → `Resume` (creates a new version)
- `ResumeVersion` = `{id, version, content, created_at}`
- `POST /resumes/from-profile` `{title, template}` → `Resume`

### Jobs
- `Job` = `{id, company, role, location, url, salary_min, salary_max, currency, status: saved|applied|interview|offer|rejected, applied_at: date|null, interview_at: datetime|null, notes, contact, tags: [str], position, created_at, updated_at}`
- `GET /jobs?status=&q=&sort=&page=&size=` → `Page[Job]`; `sort` ∈ `updated_at, company, role, status, applied_at, position` with optional `-` prefix (default `-updated_at`). `size` max 200.
  The board fetches with `sort=position` and groups by status.
- `POST /jobs`, `GET|PATCH|DELETE /jobs/{id}`
- `PATCH /jobs/{id}/status` `{status, position?}` → `Job` (records event; sets `applied_at` = today when moving to applied and empty)
  `position` = the card's 0-based index within the **target** status column after the move (omitted → top, index 0).
  In one transaction the target column is renumbered to contiguous `0..n-1` and the gap in the source column is closed.
  The same placement applies to `POST /jobs` (new jobs go on top unless `position` is given), `PATCH /jobs/{id}` with
  `status`/`position`, and `DELETE /jobs/{id}` (closes the gap).
- `GET /jobs/{id}/timeline` → `[{id, from_status|null, to_status, changed_at}]` (creation is the first event with `from_status: null`)

### Roadmaps
- `Roadmap` = `{id, title, goal, status: active|paused|completed, target_date, progress: 0-100, milestone_count, done_count, created_at, updated_at}`
- `RoadmapDetail` = `Roadmap` + `milestones: Milestone[]` ordered by position
- `Milestone` = `{id, roadmap_id, title, description, resources: [{title, url}], position, status: todo|in_progress|done, target_date, task_count, done_task_count}`
- `GET|POST /roadmaps`, `GET|PATCH|DELETE /roadmaps/{id}`
- `POST /roadmaps/{id}/milestones`, `PATCH|DELETE /milestones/{id}`
- `PUT /roadmaps/{id}/milestones/order` `{ids: [...]}` → `RoadmapDetail` (422 if ids don't match exactly the roadmap's milestones)
- `POST /roadmaps/generate` `{goal, target_date?, hours_per_week?}` → `RoadmapDetail` (AI: Gemini plans 4-8 milestones with resources; saved)

### Tasks
- `Task` = `{id, title, description, due_date: date|null, priority: low|medium|high, status: todo|done, completed_at, roadmap_id, milestone_id, roadmap_title, milestone_title, created_at, updated_at}`
- `GET /tasks?filter=today|upcoming|overdue|completed&priority=&roadmap_id=&milestone_id=&tz=Asia/Kolkata` → `Task[]` (no filter = all open + done)
- `POST /tasks` (defaults: priority medium), `PATCH|DELETE /tasks/{id}`, `POST /tasks/{id}/complete`, `POST /tasks/{id}/reopen`

### Focus sessions (pomodoro, powers streak + timeline)
- `POST /focus/sessions` `{task_id?, duration_minutes, started_at, ended_at}` → `FocusSession` = `{id, task_id, duration_minutes, started_at, ended_at}`
- `GET /focus/sessions?date=YYYY-MM-DD&tz=` → `FocusSession[]`

### News
- `NewsItem` = `{id, title, source, url, summary, image_url|null, category: ai|web|cloud|data|security, published_at, is_saved}`
- `GET /news?category=&q=&page=&size=` → `Page[NewsItem]` newest first; `GET /news/saved?page=&size=` → `Page[NewsItem]`
- `PUT /news/{id}/save` → `{is_saved: true}`; `DELETE /news/{id}/save` → `{is_saved: false}` (both idempotent)
- `POST /news/refresh` → `{added: int}` (pulls RSS through the `NewsProvider`; never fails the request if a feed is down)

### Dashboard
- `GET /dashboard/summary?tz=` →
```json
{
  "owner_name": "Mathan",
  "active_applications": 4, "interviews_this_week": 1,
  "next_interview": "Job | null",
  "pipeline": {"saved": 2, "applied": 2, "interview": 1, "offer": 1, "rejected": 1},
  "tasks_due_today": ["Task (max 5)"], "tasks_due_today_count": 3, "overdue_count": 2, "completed_today": 1,
  "focus_task": "Task | null  (first overdue/today task, by priority)", "up_next": "Task | null",
  "current_roadmap": {"id": "", "title": "", "progress": 50, "milestone_index": 3, "milestone_count": 4,
                       "next_milestone": "Milestone | null"} ,
  "latest_news": ["NewsItem × 3"],
  "streak": {"current_days": 12, "best_days": 21, "week_minutes": 580,
             "heatmap": [{"date": "2026-08-08", "count": 0}]},
  "timeline": [{"time": "09:00" , "title": "", "kind": "study|job|practice", "done": true}]
}
```
  `heatmap` = last 105 days (15 weeks), count = focus sessions + tasks completed that day. `timeline` = today's focus sessions (done),
  interviews today (kind job), tasks due today (time null). Cached 60 s per user in Redis, invalidated on job/task/roadmap/focus writes.

### Assistant (Gemini)
- `GET /assistant/status` → `{"enabled": bool, "model": "gemini-2.5-flash"}`
- `POST /assistant/ask` `{message, history?: [{role: "user"|"model", content}], tz?}` →
  `{reply: str (markdown), actions: [{type: "task_created"|"job_created"|"roadmap_created", id, title}]}`
  Gemini gets a compact context (open tasks, jobs pipeline, current roadmap, profile headline) and function tools
  `create_task(title, due_date?, priority?)`, `create_job(company, role, location?, url?, status?)`. Tool calls are executed for the current user.
- `POST /ai/rewrite` `{text, kind: "summary"|"bullet"|"cover_note", instruction?}` → `{text}` (used by the resume editor)

## Changes

Additions/clarifications made while implementing the backend (no breaking changes to the above):

- Auth error codes beyond the ones listed: `CHALLENGE_EXPIRED` (401, unknown/expired/already-used `flow_id`),
  `RECOVERY_TOKEN_INVALID` (401, bad/expired/used recovery token), `PASSKEY_EXISTS` (409, credential already registered),
  `PASSKEY_NOT_FOUND` (404). Refresh tokens are rotated: a used refresh token is rejected (401) and the cookies are cleared.
- `POST /auth/passkeys/verify` responds `201`. All `POST` create endpoints (`/jobs`, `/tasks`, `/roadmaps`, milestones,
  profile items, resumes, `/resumes/{id}/duplicate`, `/resumes/{id}/versions`, `/focus/sessions`, `/roadmaps/generate`)
  respond `201`; `POST /roadmaps` returns `RoadmapDetail`.
- Other error codes: 502 `AI_ERROR` (Gemini returned an error/unexpected output), 413 `PAYLOAD_TOO_LARGE` (body > 1 MiB),
  422 `INVALID_ORDER` (milestone reorder ids mismatch), `EMAIL_TAKEN` (409), `<RESOURCE>_NOT_FOUND` codes
  (`JOB_NOT_FOUND`, `TASK_NOT_FOUND`, `ROADMAP_NOT_FOUND`, `MILESTONE_NOT_FOUND`, `RESUME_NOT_FOUND`, `VERSION_NOT_FOUND`,
  `NEWS_NOT_FOUND`, `EXPERIENCE_NOT_FOUND`, `EDUCATION_NOT_FOUND`, `SKILL_NOT_FOUND`).
- `GET /health` returns 503 with the same body shape (`"status": "error"`) when Postgres or Redis is down.
- Jobs board ordering: `sort=position` added; `position` semantics for moves defined above (frontend request).
- Postgres host port is configurable via `POSTGRES_HOST_PORT` (docker compose, default `5433`) for machines where 5433
  is also taken; `DATABASE_URL` must match.
