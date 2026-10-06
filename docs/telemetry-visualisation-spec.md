# Vehicle Telemetry Visualisation — Technical Specification (MVP / PoC)

| | |
|---|---|
| **Status** | Approved (2026-10-05) — see §16 for clarifications |
| **Scope** | Proof of concept only. Not production-grade. |
| **Data** | Simulated only. No real vehicle, driver, or customer data. |

## 1. Purpose

Show simulated vehicle telemetry (speed, engine RPM, fuel level, engine temperature, GPS position) on a simple web dashboard, backed by the existing FastAPI + SQLite telemetry service.

## 2. Goals and Non-Goals

**Goals**
- Live-ish dashboard: gauges for current values, line charts for recent history, and a map for the vehicle position.
- Minimal moving parts: one Python service, one static HTML page, no build step.
- Reuse the REST API, validation, and storage from the telemetry service.

**Non-Goals**
- Authentication, multi-user/multi-tenant support, HA, scaling, or performance tuning.
- Real vehicle data, real VINs, or persistent GPS history.
- Alerting, historical analytics, data export, mobile layout polish.
- WebSockets/streaming (polling is sufficient for the PoC).

## 3. Architecture

```
┌─────────────┐   writes   ┌──────────────┐   ORM    ┌──────────┐
│ Simulator   │──────────▶│ Services     │────────▶│ SQLite   │
│ (services/) │            │ (services/)  │          │          │
└─────────────┘            └──────▲───────┘          └──────────┘
                                  │
                           ┌──────┴───────┐   JSON over HTTP (poll)   ┌─────────────────┐
                           │ REST API     │◀────────────────────────│ Dashboard       │
                           │ (api/)       │                          │ static HTML+JS  │
                           └──────────────┘                          └─────────────────┘
```

- **Simulator** generates a reading every `SIM_INTERVAL_SECONDS` for a small set of fake vehicles and stores it after Pydantic validation.
- **API** exposes read endpoints (see §5); handlers stay thin and delegate to services.
- **Dashboard** is a static page served by the same FastAPI app (`StaticFiles`), polling the API every 2 seconds.

## 4. Technology Choices

| Concern | Choice | License |
|---|---|---|
| Backend | FastAPI, Uvicorn, SQLAlchemy, Pydantic (existing stack) | MIT / BSD |
| Charts | Chart.js (vendored or CDN, version pinned) | MIT |
| Map | Leaflet + OpenStreetMap tiles (version pinned) | BSD-2 |
| Frontend | Vanilla JS, single `index.html`; no framework or bundler | — |

New Python dependencies, if any, are pinned in `requirements.txt`. Frontend libraries are pinned by version in the HTML (or vendored under `static/vendor/`).

## 5. Data Model

`TelemetryReading` (Pydantic schema and SQLAlchemy model):

| Field | Type | Valid range / notes |
|---|---|---|
| `id` | int | Primary key |
| `vehicle_id` | str | Fake ID, e.g. `DEMO-VEH-001`; 1–32 chars |
| `timestamp` | datetime (UTC) | Set by the simulator |
| `speed_kmh` | float | 0–250 |
| `engine_rpm` | int | 0–8000 |
| `fuel_level_pct` | float | 0–100 |
| `engine_temp_c` | float | -40–150 |
| `latitude` | float | -90–90 (simulated route only) |
| `longitude` | float | -180–180 (simulated route only) |

Storage: SQLite file, path from `DATABASE_URL`. Readings older than `RETENTION_MINUTES` (default 60) are pruned by the simulator loop to keep the DB small.

## 6. API Contract

All routes declare `response_model`, status codes, and `tags=["telemetry"]`.

| Method & path | Description | Response |
|---|---|---|
| `GET /vehicles` | List known demo vehicle IDs | `200` `list[str]` |
| `GET /telemetry/latest?vehicle_id=` | Latest reading for a vehicle | `200` `TelemetryReading`; `404` if none |
| `GET /telemetry?vehicle_id=&limit=` | Recent readings, oldest→newest. `limit` 1–300, default 60 | `200` `list[TelemetryReading]`; `422` on invalid input |
| `GET /health` | Liveness check | `200` `{"status": "ok"}` |
| `GET /` | Serves the dashboard | `200` HTML |

Errors use a structured body `{"detail": "..."}`; unexpected errors return a generic 500 message with no stack trace.

## 7. Dashboard Design

Single page, one vehicle selector (dropdown from `/vehicles`).

| Panel | Visual | Source |
|---|---|---|
| Speed | Number tile + line chart (last 60 points) | `/telemetry` |
| Engine RPM | Number tile + line chart | `/telemetry` |
| Engine temperature | Number tile + line chart; tile turns red above 110 °C | `/telemetry` |
| Fuel level | Horizontal progress bar (0–100 %) | `/telemetry/latest` |
| Position | Leaflet map with one marker and a short trail (last 60 points) | `/telemetry` |

Behaviour:
- On load: fetch `/vehicles`, select the first, fetch history, render.
- Every 2 s: fetch `/telemetry?limit=60` and refresh charts, tiles, and marker.
- If a fetch fails, show a "Connection lost" banner and keep retrying; no other error handling.
- Render values with `textContent`, never `innerHTML`.

Layout (desktop only):

```
┌──────────────────────────────────────────────┐
│ Vehicle: [DEMO-VEH-001 ▾]        ● Live       │
├───────────┬───────────┬───────────┬──────────┤
│ Speed     │ RPM       │ Temp      │ Fuel     │
├───────────┴───────────┼───────────┴──────────┤
│ Speed / RPM / Temp    │ Map (Leaflet)        │
│ line charts           │                      │
└───────────────────────┴──────────────────────┘
```

## 8. Simulator Behaviour

- Speed follows a bounded random walk (0–120 km/h typical); RPM is derived from speed with noise.
- Fuel decreases slowly and never drops below 0; temperature rises toward ~90 °C then stabilises with noise.
- GPS moves along a hardcoded fake loop (coordinates in a generic location, not tied to real people or fleets).
- Every reading is validated against §5 ranges before storage; invalid readings are dropped.

## 9. Configuration

Loaded via `config.py` from environment variables (see `.env.example`, placeholders only):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./telemetry.db` | Storage |
| `SIM_INTERVAL_SECONDS` | `1` | Reading frequency |
| `SIM_VEHICLE_COUNT` | `2` | Number of fake vehicles |
| `RETENTION_MINUTES` | `60` | Pruning window |
| `DASHBOARD_POLL_SECONDS` | `2` | Exposed to the page via a small config endpoint or template constant |

## 10. Project Layout (additions)

```
src/telemetry/
├── api/telemetry.py        # routes above
├── services/simulator.py   # background generator
├── services/telemetry.py   # queries (latest, recent, vehicles)
├── models/                 # schemas + ORM model
└── static/
    └── index.html          # dashboard (inline JS/CSS)
tests/                      # mirrors src/telemetry
docs/telemetry-visualisation-spec.md
```

## 11. Security and Compliance (PoC level)

- Simulated data only; fake VINs and coordinates; no personal data.
- ORM / parameterised queries only; all query params validated (types, ranges, lengths).
- No secrets in code or docs; config via env vars; only `.env.example` committed.
- No precise real-world location is logged.
- Dashboard binds to `127.0.0.1` by default; CORS not enabled (same-origin page).
- Third-party frontend libraries are MIT/BSD with pinned versions.

## 12. Testing (minimal)

- **Unit:** schema range validation; simulator output stays within bounds; service queries return ordered, limited results.
- **API:** `TestClient` tests for each route (200, 404, 422).
- **Manual:** run app, open `/`, confirm charts update every ~2 s, map marker moves, and the banner appears when the server is stopped.

## 13. Delivery Plan

| Step | Deliverable | Est. |
|---|---|---|
| 1 | Models, DB setup, config | 0.5 d |
| 2 | Simulator + storage service | 0.5 d |
| 3 | Read API endpoints + tests | 0.5 d |
| 4 | Dashboard page (tiles, charts, map) | 1 d |
| 5 | README run instructions, manual check | 0.5 d |

## 14. Acceptance Criteria

1. `uvicorn telemetry.main:app` starts the simulator and API with no manual DB setup.
2. Opening `/` shows all five panels populated for the selected vehicle within 5 s.
3. Panels update automatically at the polling interval without a page reload.
4. Out-of-range or invalid API input returns `422`; unknown vehicle returns `404`.
5. Tests pass; Ruff and Black report no issues.

## 15. Known Limitations and Future Ideas

- Polling adds latency and load; SSE/WebSocket would be the next step.
- SQLite and in-process simulator are single-node only.
- No auth, rate limiting, or historical queries.
- Possible later additions: threshold alerts, trip replay, time-range picker, multi-vehicle overview.

## 16. Approval Clarifications

Decisions taken at approval to remove ambiguity; they refine, not change, the scope above.

1. **Fuel tile source:** the 2 s poll fetches only `/telemetry?limit=60`; the fuel bar uses the newest item of that response. `/telemetry/latest` remains available in the API.
2. **Unknown vehicle:** `/telemetry/latest` and `/telemetry` return `404` for a `vehicle_id` that is not in `/vehicles`; a known vehicle with no readings yet returns `404` on `/latest` and `[]` on `/telemetry`.
3. **Poll interval:** `DASHBOARD_POLL_SECONDS` is injected into the page by the `GET /` handler (no extra config endpoint).
4. **Serving `/`:** an explicit route returns `static/index.html`; `StaticFiles` is mounted under `/static` only, so it cannot shadow API routes.
5. **Frontend libraries:** Chart.js and Leaflet are vendored under `static/vendor/` at pinned versions (no CDN at runtime). Map tiles come from OpenStreetMap and need internet access; the map must degrade gracefully (marker and trail still render) if tiles fail.
6. **Startup command:** `uvicorn telemetry.main:app --app-dir src` (or `pip install -e .`).
7. **Simulator lifecycle:** started and stopped in the FastAPI lifespan, controllable via config so tests can disable it.
