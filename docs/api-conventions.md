# API conventions

These rules apply to every endpoint. The full endpoint list is in [api-contract.md](api-contract.md).

## Paths and payloads
- Everything lives under `/api/v1`. Resource paths are plural nouns (`/jobs`, `/roadmaps/{id}/milestones`).
- JSON is `snake_case`. IDs are UUID strings.
- Datetimes are ISO-8601 in UTC with a `Z` suffix (`2026-11-20T09:30:00Z`); dates are `YYYY-MM-DD`.
- Endpoints that depend on "today" accept `?tz=<IANA zone>` (default `UTC`). Unknown zones → 422 on field `tz`.
- `PATCH` bodies are partial: only the fields you send are changed. `PUT /profile` is also partial.

## Errors
Every non-2xx response has the same shape:

```json
{"error": {"code": "JOB_NOT_FOUND", "message": "Job not found", "details": []}}
```

| Status | Code(s) | When |
| ------ | ------- | ---- |
| 401 | `UNAUTHENTICATED`, `PASSKEY_INVALID`, `PASSKEY_REPLAY`, `CHALLENGE_EXPIRED`, `RECOVERY_CODE_INVALID` | missing/invalid session or failed ceremony |
| 403 | `SETUP_ALREADY_COMPLETE` | setup after a passkey exists |
| 404 | `NOT_FOUND`, `<RESOURCE>_NOT_FOUND` | missing resource **or another user's resource** (never 403) |
| 409 | `LAST_PASSKEY` | conflicts |
| 413 | `PAYLOAD_TOO_LARGE` | request body over `MAX_BODY_BYTES` (1 MiB) |
| 422 | `VALIDATION_ERROR`, `INVALID_ORDER` | invalid body/query; `details` = `[{"field", "message"}]` |
| 429 | `RATE_LIMITED`, `AI_RATE_LIMITED` | too many requests / Gemini quota |
| 502 | `AI_ERROR` | Gemini returned an error |
| 503 | `AI_UNAVAILABLE` | `GEMINI_API_KEY` not configured |
| 500 | `INTERNAL_ERROR` | bug — logged with the request id |

422 `details[].field` is the location of the bad value without the `body`/`query`/`path` prefix, nested
parts joined with `.` (e.g. `salary_max`, `content.sections.0.title`).

## Pagination
`?page=1&size=20` (size ≤ 200) → `{"items": [...], "total": 42, "page": 1, "size": 20, "pages": 3}`.

## Auth
httpOnly cookies `access_token` (15 min, path `/`) and `refresh_token` (7 days, path `/api/v1/auth`),
SameSite=Lax, Secure outside dev. A non-sensitive `mandy_session=1` hint cookie (not httpOnly) mirrors
whether a session exists. `Authorization: Bearer <access>` is also accepted.

## Ownership
Every query is filtered by the current user. Services load records with
`get_owned_or_404(db, Model, id, user_id)`, so probing IDs of other users always yields 404.

## Observability
Every response carries `X-Request-ID` (echoed if the client sent one). Logs are structured
(JSON outside dev) and include the request id, method, path, status and duration. Request bodies,
cookies and tokens are never logged.

## Layering
`router.py` parses input and calls the service; `service.py` holds business logic and queries;
`models.py` is DB only; `schemas.py` holds the Pydantic request/response models.
