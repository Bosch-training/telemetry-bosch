# Telemetry Visualisation — Phased Implementation Plan

Implements [telemetry-visualisation-spec.md](./telemetry-visualisation-spec.md) (approved). Each phase is a self-contained increment: it has its own deliverables, automated tests, and a "done when" check that can be run **without later phases**. Complete phases in dependency order; do not start a phase until the previous exit gate is green.

## Phase overview

| # | Phase | Depends on | Independently verified by |
|---|---|---|---|
| 0 | Project scaffold and tooling | — | `ruff`, `black --check`, `pytest` run (empty suite passes), package imports |
| 1 | Config, schemas, ORM and DB session | 0 | Unit tests (ranges, DB round-trip on in-memory SQLite) |
| 2 | Telemetry service (queries, insert, prune) | 1 | Service tests against temp DB, no HTTP |
| 3 | Simulator core (pure generator) | 1 | Unit tests, no DB, no threads, seeded RNG |
| 4 | Simulator runner and app lifespan | 2, 3 | Integration test + `uvicorn` run fills DB |
| 5 | Read API, error handling, `/health` | 2 | `TestClient` tests with simulator disabled |
| 6 | Dashboard shell (page, selector, tiles, polling, banner) | 5 (4 for live data) | Route test + manual check against seeded DB |
| 7 | Dashboard charts and fuel bar | 6 | Manual check + payload-shape tests |
| 8 | Dashboard map | 6 | Manual check |
| 9 | Hardening, docs and acceptance run | 4–8 | Spec §14 checklist |

Phases 3 and 5 can run in parallel after Phase 2 (3 needs only Phase 1). Phases 7 and 8 are independent of each other.

Global rules for every phase (from `.github/instructions/`):
- Layers stay separate: `api/` routes only, `services/` logic, `models/` schemas + ORM, `config.py` settings.
- Type hints and docstrings on public code; Ruff + Black (line length 88) + mypy clean.
- Tests use `pytest`, in-memory/temp SQLite, fake data only, and cover normal, boundary and invalid cases; coverage ≥ 80 % (`pytest --cov=src`).
- Pin every new dependency in `requirements.txt`; MIT/Apache-2.0/BSD only. No secrets; only `.env.example` is committed.

**Standard exit gate (applies to every phase):** `ruff check .` · `black --check .` · `mypy src` · `pytest --cov=src` all pass.

---

## Phase 0 — Project scaffold and tooling

**Goal:** an installable, lint-clean, empty package so every later phase has a working toolchain.

**Deliverables**
- `pyproject.toml`: package metadata (src layout), Ruff, Black, mypy, pytest (`pythonpath = ["src"]`, `testpaths = ["tests"]`) config.
- `requirements.txt` (pinned): `fastapi`, `uvicorn`, `sqlalchemy`, `pydantic`, `python-dotenv`; dev: `pytest`, `pytest-cov`, `httpx` (for `TestClient`), `ruff`, `black`, `mypy`.
- `.env.example` with placeholders for all spec §9 variables plus `SIM_ENABLED=true`; `.gitignore` covering `.env`, `.env.*` (except `.env.example`), `*.db`, caches, venv.
- Skeleton: `src/telemetry/{__init__,main,config}.py`, `api/`, `models/`, `services/`, `static/` (each Python package with `__init__.py`), `tests/conftest.py`.
- `main.py` with a bare `FastAPI()` app (no routes yet).

**Tests / verification**
- `tests/test_main.py`: app imports and `app.title` is set.
- Standard exit gate.

**Done when:** fresh venv → `pip install -r requirements.txt` → exit gate green.

---

## Phase 1 — Config, schemas, ORM and DB session

**Goal:** typed settings and the `TelemetryReading` data model, validated and persistable.

**Deliverables**
- `config.py`: `Settings` loaded from env via python-dotenv with defaults from spec §9 (`DATABASE_URL`, `SIM_INTERVAL_SECONDS`, `SIM_VEHICLE_COUNT`, `RETENTION_MINUTES`, `DASHBOARD_POLL_SECONDS`, `SIM_ENABLED`); cached accessor; bounds validation (e.g. interval > 0, vehicle count 1–10).
- `models/schemas.py`: Pydantic `TelemetryReading` (spec §5 ranges, `vehicle_id` 1–32 chars with a safe-character pattern, UTC-aware timestamp) plus a create-variant without `id`.
- `models/orm.py`: SQLAlchemy `TelemetryReadingORM`, index on `(vehicle_id, timestamp)`.
- `models/database.py`: engine/session factory from settings, `init_db()` (create tables), `get_session` dependency.

**Tests**
- `tests/test_config.py`: defaults, env overrides, invalid values rejected.
- `tests/models/test_schemas.py`: each field at min, max, just-outside (e.g. speed -0.1 / 250 / 250.1, lat ±90, lon ±180, fuel 0/100, temp -40/150); bad `vehicle_id`; naive timestamp handling.
- `tests/models/test_orm.py`: insert + read round-trip on in-memory SQLite; schema ↔ ORM conversion.

**Done when:** exit gate green; no other phase code required.

---

## Phase 2 — Telemetry service

**Goal:** all data access in one tested service layer.

**Deliverables** (`services/telemetry.py`, session-injected functions)
- `add_reading(session, reading)`.
- `list_vehicles(session)` — distinct IDs, sorted.
- `get_latest(session, vehicle_id)` — newest reading or `None`.
- `get_recent(session, vehicle_id, limit)` — newest `limit` rows returned **oldest→newest**.
- `prune_older_than(session, cutoff)` — returns deleted count.
- ORM/parameterised queries only.

**Tests** (`tests/services/test_telemetry.py`, temp DB, hand-built readings)
- Ordering oldest→newest; `limit` honoured (1, exact count, > count); empty DB → `[]` / `None`.
- Vehicles isolated from each other; distinct and sorted vehicle list.
- Prune removes only rows older than the cutoff, boundary row kept.

**Done when:** exit gate green; no HTTP or simulator involved.

---

## Phase 3 — Simulator core (pure generator)

**Goal:** deterministic, side-effect-free generation of valid readings.

**Deliverables** (`services/simulator.py` — generator part only)
- `VehicleSimulator` class: per-vehicle state, `next_reading(now) -> TelemetryReading`, injectable `random.Random` for seeding.
- Behaviour per spec §8: bounded speed random walk, RPM derived from speed + noise, fuel monotonic non-increasing and ≥ 0, temperature warming to ~90 °C then stabilising, GPS stepping along a hardcoded fake loop (constant list, generic location).
- Output is validated through the Pydantic schema; invalid readings are dropped (returns `None`) rather than raised.
- Helper `make_vehicle_ids(count)` → `DEMO-VEH-001…`.

**Tests** (`tests/services/test_simulator.py`, seeded RNG)
- 10 000 consecutive readings: all fields inside §5 ranges.
- Fuel never increases or goes below 0; temperature converges near 90 °C; route wraps around at loop end.
- Same seed → same sequence; different vehicles have independent state.
- Forced out-of-range value is dropped, not stored/raised.

**Done when:** exit gate green; no DB, threads or sleeps in the tests.

---

## Phase 4 — Simulator runner and app lifespan

**Goal:** the app fills the DB on its own at startup.

**Deliverables**
- Async runner in `services/simulator.py`: every `SIM_INTERVAL_SECONDS` generates a reading per vehicle, stores via the service, prunes older than `RETENTION_MINUTES` (pruning at a coarse cadence, e.g. every 60 ticks). Blocking DB work runs via `asyncio.to_thread`; per-tick exceptions are logged (no location data in logs) and do not kill the loop.
- `main.py` lifespan: `init_db()`, start runner task if `SIM_ENABLED`, cancel cleanly on shutdown.

**Tests**
- Runner test with tiny interval (e.g. 0.01 s) and a temp DB: after a short wait, rows exist for every configured vehicle; cancel stops it with no leftover task.
- Prune test: seeded old rows are removed after a prune tick.
- Lifespan test: `TestClient` context with `SIM_ENABLED=false` starts no task; with `true` produces rows.
- Error-resilience: a service call that raises once does not stop later ticks.

**Manual check:** `uvicorn telemetry.main:app --app-dir src`, then inspect the SQLite file (row count grows; ranges sane).

**Done when:** exit gate green and the manual check shows growing data with no manual DB setup.

---

## Phase 5 — Read API, error handling and `/health`

**Goal:** the full REST contract from spec §6 (except `GET /`), tested without the simulator.

**Deliverables**
- `api/telemetry.py` router (`tags=["telemetry"]`, `response_model`, summaries/docstrings): `GET /vehicles`, `GET /telemetry/latest`, `GET /telemetry`.
- Query validation: `vehicle_id` required, 1–32 chars, safe pattern; `limit` 1–300 default 60.
- Unknown vehicle → `404` (spec §16.2); known vehicle with no data → `404` on `/latest`, `[]` on `/telemetry`.
- `GET /health` → `{"status": "ok"}`.
- Global exception handler: generic 500 body `{"detail": "Internal server error"}`, no stack trace; `{"detail": ...}` shape for 404/422.
- Session dependency overridden in tests.

**Tests** (`tests/api/test_telemetry.py`, `TestClient`, seeded temp DB, simulator disabled)
- 200 for each route with correct shape and oldest→newest order.
- 404 unknown vehicle / no latest; 422 for missing `vehicle_id`, `limit` = 0, 301, non-numeric, over-long or malformed `vehicle_id`.
- Boundary `limit` 1 and 300.
- Forced service exception → 500 with generic message and no traceback text.
- OpenAPI schema lists all routes with the `telemetry` tag.

**Done when:** exit gate green; `curl` against a running app returns valid JSON for each route (acceptance #4).

---

## Phase 6 — Dashboard shell

**Goal:** a working page that polls the API and shows live number tiles, with no third-party libraries yet.

**Deliverables**
- `static/index.html` (inline JS/CSS, vanilla): vehicle dropdown from `/vehicles`, four tiles (speed, RPM, temp, fuel), "● Live" indicator, "Connection lost" banner with continued retry, desktop layout skeleton with placeholders for charts and map.
- Poll loop every `DASHBOARD_POLL_SECONDS` calling `/telemetry?limit=60`; tiles show the newest item; temp tile turns red above 110 °C.
- All values written via `textContent` only; no `innerHTML`.
- `main.py`: `GET /` route (`HTMLResponse`) that injects the poll interval; `StaticFiles` mounted at `/static` (spec §16.3–4).

**Tests**
- `tests/api/test_dashboard.py`: `GET /` → 200 `text/html`, contains poll interval constant and expected element IDs; `/static/…` served; API routes not shadowed.
- Static check (test or grep gate): no `innerHTML` in `index.html`.

**Manual check:** page loads, tiles populate within 5 s, values change every ~2 s, stopping the server shows the banner and restarting clears it, switching vehicles updates tiles.

**Done when:** exit gate green and manual check passes.

---

## Phase 7 — Charts and fuel bar

**Goal:** history visualisation for speed, RPM and temperature plus the fuel progress bar.

**Deliverables**
- Vendor Chart.js at a pinned version to `static/vendor/chartjs/` with its MIT licence file and a version note.
- Three line charts (last 60 points, animations off, in-place data updates rather than re-creating charts); fuel bar width = latest `fuel_level_pct` (clamped 0–100).
- Chart state reset when the selected vehicle changes.

**Tests**
- Extend `test_dashboard.py`: vendor asset served (200, JS content type); page references the local asset path (no external CDN URL for Chart.js).
- `/telemetry` payload contains the fields the charts use (contract test with seeded data).

**Manual check:** three charts fill with ≤ 60 points and scroll as new data arrives; fuel bar drops slowly; no console errors; no layout shift on each update.

**Done when:** exit gate green and manual check passes.

---

## Phase 8 — Map

**Goal:** vehicle position and trail on a Leaflet map.

**Deliverables**
- Vendor Leaflet at a pinned version to `static/vendor/leaflet/` (CSS, JS, marker images) with BSD-2 licence file.
- OpenStreetMap tile layer with attribution; single marker on newest point; polyline trail from the last 60 points; map auto-pans to the marker.
- Graceful tile failure: marker and trail still render when tiles can't load.
- Trail/marker reset on vehicle change.

**Tests**
- Vendor assets served; page references local Leaflet paths.
- Optional: simulator-loop coordinates test asserting the fake loop is a closed, valid lat/lon path (guards the "generic location, no real fleet" rule).

**Manual check:** marker moves along the loop, trail grows to ≤ 60 points, offline (tiles blocked) the marker still moves.

**Done when:** exit gate green and manual check passes.

---

## Phase 9 — Hardening, documentation and acceptance

**Goal:** prove the spec §14 acceptance criteria and make the project runnable by a newcomer.

**Deliverables**
- `README.md`: install, config table (mirrors §9), run command (`uvicorn telemetry.main:app --app-dir src`), test/lint commands, known limitations, "demo data only" notice.
- Default bind to `127.0.0.1` documented; no CORS enabled (verified).
- Security pass: no secrets in repo, `.gitignore` effective, no location data in logs, no `eval`/`exec`, no raw SQL (grep gate).
- Coverage ≥ 80 %; remove dead code.

**Acceptance checklist (spec §14)**

| # | Criterion | How verified |
|---|---|---|
| 1 | `uvicorn …` starts simulator + API, no manual DB setup | Fresh clone run (Phase 4/9) |
| 2 | `/` shows all five panels within 5 s | Manual, timed |
| 3 | Panels update at poll interval without reload | Manual (network tab shows 2 s cadence) |
| 4 | Invalid input → 422, unknown vehicle → 404 | Phase 5 tests |
| 5 | Tests pass; Ruff and Black clean | Standard exit gate |

**Done when:** every row above is ticked on a fresh virtualenv.

---

## Risks and notes

- **Blocking DB in async code:** keep all SQLAlchemy calls in services and call them via `asyncio.to_thread` / sync dependencies to avoid blocking the event loop (SQLite file with `check_same_thread=False` and per-call sessions).
- **SQLite concurrency:** simulator writes and API reads share one file; enable WAL mode in `init_db()` and keep transactions short.
- **Map tiles need internet:** only OSM tiles are external; document this in the README.
- **Timestamps:** store and return timezone-aware UTC (SQLite drops tzinfo — normalise on read).
- **Scope guard:** no auth, WebSockets, alerts or export (spec §2 non-goals).
