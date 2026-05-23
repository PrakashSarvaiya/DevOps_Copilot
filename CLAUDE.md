# DevOps Copilot

An agentic DevOps assistant that behaves like a junior/mid DevOps engineer. It
watches Jenkins jobs, classifies failures, plans a safe fix, executes it
through a guarded tool registry, verifies the result, and logs everything.

## Project goal (READ FIRST)

This project follows the agent loop:

```
Event → Observe → Understand Context → Plan → Choose Action → Execute → Verify
```

(REPORT stage was intentionally removed — see [Anti-goals](#anti-goals).)

### Anti-goals — do NOT extend the codebase in these directions

- ❌ **RCA platform** — root-cause-analysis dashboards, "AI explained why your build failed" UIs, hardcoded fallback diagnoses.
- ❌ **Incident manager** — ticketing, severity, resolution status, post-mortem exports.
- ❌ **Log-analyzer dashboard** — log search, severity filters as the main UX.
- ❌ **Report generator** — emailed summaries, PDF exports of agent activity.
- ❌ **LLM-driven planning** (for now) — the user explicitly wants deterministic, auditable, junior-engineer-style heuristics.

The codebase used to be an RCA platform and was deliberately pivoted away. If
you see anything pulling back toward those directions (e.g. an LLM call in the
planner, an `Incident` model, a "send report" stage), it's a regression.

The user's words: *"I want it to act like my junior and perform my task."*

## Stack

- **Backend**: FastAPI 0.110 + SQLAlchemy 2.0 (async) + Pydantic v2 + python-jose JWT.
- **DB**: SQLite (`backend/DevOps_copilot.db`) for dev, PostgreSQL via `DATABASE_URL` env for prod.
- **Frontend**: React 18 + TypeScript + Vite + TailwindCSS + lucide-react icons + Zustand store.
- **Docker**: `docker/docker-compose.yml` runs db (Postgres) + chromadb (declared but unused) + backend + frontend.

## Repo layout

```
backend/
  app/
    main.py                       FastAPI app + lifespan poll loop
    core/config.py                pydantic-settings; reads backend/.env
    core/security.py              JWT helpers
    database/db.py                async engine + SessionLocal
    api/
      deps.py                     auth dependencies (get_current_user, require_devops)
      endpoints/
        auth.py                   /api/v1/auth/* (login, register)
        jenkins.py                /api/v1/jenkins/* (connect server, list jobs, list builds)
        agent.py                  /api/v1/agent/* (run-once, webhook, tools, actions, polls, build/{id}/handle)
    models/models.py              SQLAlchemy models — see "DB schema" below
    schemas/schemas.py            Pydantic request/response models
    services/
      jenkins_client.py           Thin async Jenkins HTTP client (httpx)
      parser.py                   Regex log-error classifier (used by the agent as a context tool)
      notifier.py                 SMTP send_failure_email (supports multipart HTML)
      email_renderer.py           Jinja2 templates → (subject, plain, html) for the NOTIFY stage
      email_templates/            HTML templates (code_error, recovery_failed, release_escalation, site_down)
      agent.py                    Polling + dispatch — the entry surface
      agent_controller.py         Seven-stage state machine (OBSERVE…VERIFY + optional NOTIFY)
      agent_tools.py              ToolRegistry, SafetyClass enum, safe/blocked allowlist
      agent_knowledge.py          FailureClass enum + classifier + per-class playbooks
      agent_memory.py             Queries over the AgentAction ledger
      site_monitor.py             Independent UP/DOWN poll loop for user-registered URLs
  requirements.txt
  .env                            Local secrets — gitignored. AGENT_WEBHOOK_SECRET lives here.
  DevOps_copilot.db               Local SQLite — gitignored.

frontend/
  src/
    App.tsx                       Routes: /login, /dashboard, /jenkins
    components/Layout.tsx         Sidebar nav + auth gate
    pages/
      Dashboard.tsx               Activity feed + fetch log + tool catalog + live spinner
      JenkinsJobs.tsx             Connect server, pick monitored pipelines, view builds
      Login.tsx                   Auth
    services/api.ts               Axios w/ JWT interceptor
    store/auth_store.ts           Zustand auth state
```

## How the agent works

### Seven-stage loop (per failed build)

```
OBSERVE            → record we saw the failure
UNDERSTAND_CONTEXT → fetch console log + run parser to extract error lines
PLAN               → classify failure, look up memory, pick action sequence
CHOOSE             → validate every step against the tool registry
EXECUTE            → walk the step list; halt on first failure
VERIFY             → confirm the last step did what it said
NOTIFY (optional)  → email a human when the agent couldn't auto-recover
```

NOTIFY only fires when human help is actually needed (see "Email policy"
below). When the agent successfully retries or wipes+retries, NOTIFY is
skipped and no row is written. The idempotency check `_already_handled`
uses VERIFY as the terminal marker — VERIFY always fires; NOTIFY is the
optional 7th stage.

### Tool Registry ([agent_tools.py](backend/app/services/agent_tools.py))

Every side-effecting call goes through `ToolRegistry.call(name, args)`. Tools
have a `SafetyClass`:

| Class | Examples | Behavior |
|---|---|---|
| `READ_ONLY` | `jenkins.fetch_console`, `context.parse_errors` | No side effects |
| `SAFE_ACTION` | `jenkins.retry_build`, `jenkins.clean_workspace`, `notify.email` | On the allowlist |
| `BLOCKED` | `infra.drop_database`, `infra.delete_cluster`, etc. | Raise `ToolBlockedError` on any invocation |

`BLOCKED_KEYWORDS` does a defense-in-depth substring scan of tool arguments —
even a SAFE tool will refuse if arguments contain `"drop database"`,
`"terraform destroy"`, etc. This guards against a future LLM-driven planner
passing destructive strings into a benign tool.

### Knowledge base ([agent_knowledge.py](backend/app/services/agent_knowledge.py))

All heuristics live in one file. `classify_failure(log, parsed_errors)`
returns a `FailureClass`:

| Class | Triggers | Playbook |
|---|---|---|
| `NETWORK_TRANSIENT` | `connection timed out`, `503`, `network unreachable`, etc. | `[retry_build]` |
| `WORKER_OFFLINE` | `agent went offline`, `node disconnected` | `[retry_build]` |
| `WORKSPACE_LOCKED` | `workspace is locked`, `unable to delete` | `[clean_workspace, retry_build]` |
| `DISK_FULL` | `no space left on device` | `[]` (escalate — needs pre-approved Jenkins fix-it job, not yet wired) |
| `PORT_CONFLICT` | `address already in use` | `[]` (same as above) |
| `CODE_ERROR` | `NullPointerException`, `compilation error`, `test failed` | `[]` (notify dev — real bug, not infra) |
| `UNKNOWN` | nothing matched | `[]` |

Empty playbook ⇒ plan demotes to `NOTIFY_ONLY` / `ESCALATE` and no tools fire.

### RELEASE pipeline override

`pipeline_type=='RELEASE'` jobs do NOT use the class-specific playbook. They
always use `RELEASE_RETRY_PLAYBOOK` (a single `jenkins.retry_build` step)
regardless of failure class. If the retry fails, NOTIFY fires to
`DEFAULT_ALERT_EMAIL`. Rationale: release pipelines are sensitive; the
operator's preference is "always try one retry first, then escalate to
DevOps if it still fails." Per-build retry caps and memory-based
escalation guards still apply.

### Email policy (NOTIFY stage)

| Pipeline | Outcome | Recipient |
|---|---|---|
| BUILD + `CODE_ERROR` (compile / test failure) | always notify | commit author, fallback `DEFAULT_ALERT_EMAIL` |
| BUILD + infra-class playbook ran + VERIFY=Verified | **silent** | — |
| BUILD + infra-class playbook ran + VERIFY=Failed | always notify | commit author, fallback `DEFAULT_ALERT_EMAIL` |
| RELEASE + retry succeeded (VERIFY=Verified) | **silent** | — |
| RELEASE + retry failed / didn't run | always notify | `DEFAULT_ALERT_EMAIL` only (DevOps) |

The commit author email is resolved via `jenkins.fetch_build_details`
which reads it from Jenkins's `changeSets`. The policy lives in
`AgentController._should_notify` + `_resolve_recipient`. Update those
two methods (plus `_compose_email`) if you tune the rules.

### Memory layer ([agent_memory.py](backend/app/services/agent_memory.py))

The planner consults the audit ledger before acting:
- `retries_for_build(build_id)` — per-build cap
- `consecutive_failures_of_action(job_id, tool_name)` — if last 2 retries on this job failed, escalate
- `retry_success_rate(job_id)` — if historical success < 20% over ≥5 attempts, escalate
- `last_action_outcome_by_class(job_id, failure_class)` — future learning hook

The "did retry actually fix it?" calculation joins past `EXECUTE/jenkins.retry_build/Triggered`
rows with the *next* build by build number and checks if it ended SUCCESS.

### Polling ([agent.py](backend/app/services/agent.py))

Lifespan loop in [main.py](backend/app/main.py) wakes every
`AGENT_POLL_INTERVAL_SECONDS` (default 10). For each monitored Job:

1. Call `JenkinsClient.get_latest_build(job_name, job_url)` — single HTTP
   call to `/job/X/lastBuild/api/json`.
2. Upsert one `AgentPoll` row keyed by `job_id` (one row per job, ever — `_upsert_poll`).
3. If the latest build is `FAILURE`, dispatch the controller.

**Important behaviors:**
- Only the *latest* build matters. If a job had `#1503 FAILURE` then `#1504 SUCCESS`, the agent does nothing — the issue self-resolved.
- The controller is **idempotent**: it short-circuits if a `VERIFY` row already exists for that build_id (`_already_handled`). Safe to call from polling, webhook, or manual trigger.
- Non-failure polls write zero rows to `agent_actions` but always upsert `agent_polls` so the dashboard can prove the loop is alive.

## DB schema

| Table | Purpose | Key relationships |
|---|---|---|
| `users` | Auth | — |
| `jenkins_servers` | Registered Jenkins controllers | `owner: User` |
| `jobs` | Monitored pipelines (opt-in via UI) | `server: JenkinsServer` |
| `builds` | Synced from Jenkins; one row per build number | `job: Job` |
| `agent_actions` | Audit ledger — one row per agent loop stage | `build: Build` |
| `agent_polls` | Current-state cache, **one row per job** (upsert) | `job: Job` |
| `sites` | User-registered URLs for the site monitor. **One row per site** (upserted on each check) | `owner: User` |

`agent_actions.tool_name` and `agent_polls.job_id` (with `unique=True`) were
added after the original schema. SQLAlchemy's `create_all` adds missing
*tables* but not missing *columns* — see [Gotchas](#gotchas).

## Endpoints

All under `/api/v1`. JWT required unless noted.

### auth
- `POST /auth/register`, `POST /auth/login`

### jenkins
- `POST /jenkins/connect` — register a Jenkins server
- `GET /jenkins/servers`, `DELETE /jenkins/servers/{id}`
- `GET /jenkins/servers/{id}/available-jobs` — list jobs Jenkins reports
- `PUT /jenkins/servers/{id}/monitored-jobs` — opt in to monitoring + pipeline_type (BUILD vs RELEASE)
- `GET /jenkins/jobs?server_id=N`
- `GET /jenkins/jobs/{id}/builds`

### agent
- `POST /agent/run-once` — manually fire one poll cycle (devops role)
- `POST /agent/webhook/jenkins` — Jenkins push entry, `X-Webhook-Secret` header optional
- `POST /agent/build/{id}/handle` — manually run controller on a specific build (devops role)
- `GET /agent/tools` — registered tool catalog (introspection)
- `GET /agent/actions?limit=N` — audit ledger, most recent first, denormalized with `job_name` + `build_number`
- `GET /agent/actions/build/{id}` — per-build stage trail
- `GET /agent/polls?limit=N` — current poll status per job (one row per job)

### sites (site monitor)
- `GET /sites/` — list current user's sites
- `POST /sites/` — register a new site (`name`, `url`, optional interval/timeout/enabled)
- `PUT /sites/{id}` — update fields
- `DELETE /sites/{id}` — stop monitoring
- `POST /sites/{id}/check` — force an immediate check (ignores interval, useful for verifying alerts)

## Environment variables (`backend/.env`)

```ini
AGENT_WEBHOOK_SECRET=...            # required-ish for any exposed deployment
AGENT_ENABLED=true                  # background poll loop in main.py
AGENT_POLL_INTERVAL_SECONDS=10
AGENT_AUTO_RERUN_ENABLED=false      # set true to let planner pick RETRY / RETRY_AFTER_CLEAN
AGENT_MAX_RERUNS_PER_BUILD=1

# Site monitor
SITE_MONITOR_ENABLED=false          # second background loop, checks registered URLs
SITE_MONITOR_POLL_INTERVAL_SECONDS=30   # how often the loop wakes; each site has its own check_interval_seconds

# Required for the NOTIFY stage to actually send mail. With SMTP_HOST empty
# the agent still classifies, decides, and writes a NOTIFY row with
# status=SmtpUnconfigured — useful for dev without leaking emails.
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USERNAME=<gmail address>
SMTP_PASSWORD=<gmail app password>  # generate at Account → Security → 2-Step → App passwords
SMTP_FROM_EMAIL=<gmail address>

# Optional: JWT_SECRET, DATABASE_URL, ENVIRONMENT
```

**Note:** with `AGENT_AUTO_RERUN_ENABLED=false`, the planner classifies and
reasons correctly but always demotes to `NOTIFY_ONLY`. Flip to `true` to let
the agent actually retry / clean workspace.

Inline comments after `KEY=value` confuse some python-dotenv versions — keep
comments on their own line.

## Dev workflow

### Backend

```bash
cd backend
./venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
# OR
./venv/Scripts/python.exe -c "from app.main import app; print(len(app.routes))"   # quick import check
```

### Frontend

```bash
cd frontend
npm run dev               # vite dev server
./node_modules/.bin/tsc --noEmit -p tsconfig.app.json   # type-check
```

### Verify agent loop end-to-end

```bash
# Manually fire one poll cycle (returns outcomes per job)
curl -X POST http://localhost:8000/api/v1/agent/run-once -H "Authorization: Bearer <JWT>"

# Force the controller against an existing FAILURE build
curl -X POST http://localhost:8000/api/v1/agent/build/<id>/handle -H "Authorization: Bearer <JWT>"

# Watch the activity ledger fill up
curl http://localhost:8000/api/v1/agent/actions?limit=20 -H "Authorization: Bearer <JWT>"
```

## Gotchas

1. **Schema drift on dev SQLite**: `Base.metadata.create_all` adds missing
   *tables* on startup but does **not** add missing *columns* to existing
   tables. If you add a column (we've done this with `agent_actions.tool_name`),
   either delete `backend/DevOps_copilot.db` or `ALTER TABLE` by hand. The
   `agent_polls` table is new and was created cleanly.
2. **`jenkins_url` must match exactly** what the user registered via
   `/jenkins/connect` (trailing slashes are stripped; scheme + host + port
   must be identical). Otherwise the webhook returns `server_not_found`.
3. **Jobs must be in "Monitored Pipelines"** — opt-in via the UI. The agent
   only acts on what the user explicitly registered.
4. **Job has `pipeline_type` field** (`BUILD` or `RELEASE`). `RELEASE`
   pipelines NEVER auto-act regardless of failure class — too risky to
   retry/clean a release artifact.
5. **Webhook is now optional** since polling runs every 10s. Both code paths
   exist and are idempotent (`_already_handled`); use whichever fits.
6. **`backend/venv/`** is committed to the repo (pre-existing decision the
   user hasn't asked to revisit). Don't be surprised by `git status` noise
   there.
7. **The Dashboard auto-refreshes every 10s** via `setInterval` to mirror
   the backend poll cadence. The header has a small spinning ring + "last
   fetched Ns ago" counter as a liveness indicator.

## When adding a new safe action

The user wants the agent to "act like a junior" — keep extensions in that
shape:

1. Add a real handler in [jenkins_client.py](backend/app/services/jenkins_client.py)
   (or wherever the side effect lives).
2. Register it in [agent_tools.py](backend/app/services/agent_tools.py) as
   `SafetyClass.SAFE_ACTION` with a clear description.
3. Wire it into a playbook in [agent_knowledge.py](backend/app/services/agent_knowledge.py)
   for the FailureClass that needs it.
4. Tool-specific success check in `AgentController._step_succeeded`.
5. Tool-specific status label (e.g. `"Triggered"`, `"Wiped"`) in `_execute`.

The natural next addition is `jenkins.trigger_ops_job(ops_job_name)` — the
operator pre-creates Jenkins jobs like `op-docker-prune` and
`op-restart-payments-api`; the agent calls them by name when classifying
`DISK_FULL` or `PORT_CONFLICT`. This keeps remote execution inside Jenkins's
existing auth boundary — no SSH credentials, no shell access for the agent.

## When tempted to add an LLM

Don't, without checking with the user. They explicitly said no LLM for now.
The architecture is shaped so that swapping the rule-based `_plan()` for an
LLM-driven one is a single-file change; the `ToolRegistry.assert_safe()`
guardrail is still load-bearing even with an LLM in the loop. But the user
wants the deterministic, auditable behaviour today.
