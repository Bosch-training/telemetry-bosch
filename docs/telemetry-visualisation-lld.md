# Vehicle Telemetry Visualisation — Low-Level Design (LLD)

| | |
|---|---|
| **Implements** | [telemetry-visualisation-spec.md](./telemetry-visualisation-spec.md) |
| **Delivery plan** | [telemetry-visualisation-plan.md](./telemetry-visualisation-plan.md) |
| **Scope** | Proof of concept. Simulated data only. Not production-grade. |
| **Diagrams** | [Mermaid](https://mermaid.js.org/) — render in GitHub and VS Code (Markdown Preview Mermaid support) |

Status legend used throughout: ✅ implemented (plan phases 0–2) · 🔲 designed, not yet implemented (phases 3–9).

---

## 1. Design overview

A FastAPI app hosts three things in one process: a background **simulator** that writes readings, a read-only **REST API**, and a static **dashboard** that polls the API. All persistence goes through one **service layer** onto SQLite.

### 1.1 Design principles

- **Strict layering** — `api/` (thin routes) → `services/` (logic) → `models/` (schemas + ORM + DB session). `config.py` is read by anyone; nobody reads the environment directly.
- **Validate at the boundary** — every reading passes through the Pydantic schema before storage; every query parameter is validated before it reaches a service.
- **Pure core, impure shell** — the simulator generator is deterministic (injected RNG); threading/async/DB live only in the runner.
- **Sync DB, async edge** — SQLAlchemy sessions are synchronous; async code calls them via `asyncio.to_thread`.

### 1.2 Package / module diagram

```mermaid
flowchart TB
    subgraph Browser
        D["static/index.html<br/>(vanilla JS, Chart.js, Leaflet)"]
    end

    subgraph telemetry["src/telemetry"]
        MAIN["main.py 🔲<br/>app, lifespan, GET /, /static"]
        subgraph api["api/"]
            R["telemetry.py 🔲<br/>routes + exception handlers"]
        end
        subgraph services["services/"]
            SVC["telemetry.py ✅<br/>queries, insert, prune"]
            SIM["simulator.py 🔲<br/>VehicleSimulator + runner"]
        end
        subgraph models["models/"]
            SCH["schemas.py ✅<br/>Pydantic"]
            ORM["orm.py ✅<br/>SQLAlchemy"]
            DB["database.py ✅<br/>engine, session, init_db"]
        end
        CFG["config.py ✅<br/>Settings"]
    end

    SQLITE[("SQLite file<br/>telemetry.db")]

    D -- "HTTP JSON (poll)" --> R
    D -- "GET /, /static/*" --> MAIN
    MAIN --> R
    MAIN --> SIM
    MAIN --> DB
    R --> SVC
    R --> SCH
    SIM --> SVC
    SIM --> SCH
    SVC --> ORM
    SVC --> SCH
    ORM --> SCH
    DB --> ORM
    DB --> SQLITE
    CFG -. "settings" .-> MAIN
    CFG -.-> SIM
    CFG -.-> DB
    CFG -.-> R
```

**Dependency rules** (enforced by review): `models` imports nothing from `services`/`api`; `services` never imports `api`; `api` never touches `ORM` or `Session` queries directly.

---

## 2. Class diagrams

### 2.1 Configuration and data model ✅

```mermaid
classDiagram
    class Settings {
        <<pydantic BaseModel, frozen>>
        +str database_url = "sqlite:///./telemetry.db"
        +float sim_interval_seconds = 1.0  (gt 0)
        +int sim_vehicle_count = 2  (1..10)
        +int retention_minutes = 60  (gt 0)
        +float dashboard_poll_seconds = 2.0  (gt 0)
        +bool sim_enabled = true
    }
    class ConfigModule {
        <<module config.py>>
        +load_settings() Settings
        +get_settings() Settings  «lru_cache»
    }

    class TelemetryReadingCreate {
        <<pydantic BaseModel>>
        +str vehicle_id  (1..32, ^[A-Za-z0-9_-]+$)
        +datetime timestamp  (UTC-normalised)
        +float speed_kmh  (0..250)
        +int engine_rpm  (0..8000)
        +float fuel_level_pct  (0..100)
        +float engine_temp_c  (-40..150)
        +float latitude  (-90..90)
        +float longitude  (-180..180)
        -_normalise_timestamp(value) datetime
    }
    class TelemetryReading {
        <<pydantic BaseModel, from_attributes>>
        +int id
    }
    class SchemasModule {
        <<module schemas.py>>
        +VEHICLE_ID_PATTERN str
        +ensure_utc(value) datetime
    }

    class Base {
        <<DeclarativeBase>>
    }
    class TelemetryReadingORM {
        <<table telemetry_readings>>
        +int id  «PK»
        +str vehicle_id  «String(32)»
        +datetime timestamp  «DateTime(tz)»
        +float speed_kmh
        +int engine_rpm
        +float fuel_level_pct
        +float engine_temp_c
        +float latitude
        +float longitude
        +from_schema(reading)$ TelemetryReadingORM
    }

    class DatabaseModule {
        <<module database.py>>
        +create_db_engine(database_url) Engine
        +get_engine() Engine  «lru_cache»
        +create_session_factory(engine) sessionmaker
        +init_db(engine?) None
        +get_session() Iterator~Session~
    }

    TelemetryReading --|> TelemetryReadingCreate
    TelemetryReadingORM --|> Base
    TelemetryReadingORM ..> TelemetryReadingCreate : from_schema(reading)
    TelemetryReading ..> TelemetryReadingORM : model_validate(row)
    ConfigModule ..> Settings : builds
    DatabaseModule ..> Settings : database_url
    DatabaseModule ..> Base : create_all
    SchemasModule ..> TelemetryReadingCreate : ensure_utc
```

### 2.2 Service layer ✅

```mermaid
classDiagram
    class TelemetryService {
        <<module services/telemetry.py>>
        +add_reading(session, reading: TelemetryReadingCreate) TelemetryReading
        +list_vehicles(session) list~str~
        +get_latest(session, vehicle_id) TelemetryReading | None
        +get_recent(session, vehicle_id, limit) list~TelemetryReading~
        +prune_older_than(session, cutoff) int
    }
    class Session {
        <<SQLAlchemy>>
    }
    TelemetryService ..> Session : injected, caller owns lifecycle
    TelemetryService ..> TelemetryReadingORM
    TelemetryService ..> TelemetryReading
```

Contracts:

| Function | Ordering / semantics | Empty case |
|---|---|---|
| `add_reading` | Insert + commit, returns stored row with generated `id` | — |
| `list_vehicles` | `SELECT DISTINCT vehicle_id ORDER BY vehicle_id` | `[]` |
| `get_latest` | `ORDER BY timestamp DESC, id DESC LIMIT 1` | `None` |
| `get_recent` | Newest `limit` rows (`timestamp DESC, id DESC`), **reversed** to oldest→newest | `[]` |
| `prune_older_than` | `DELETE … WHERE timestamp < cutoff` (strict; boundary row kept), commit, returns deleted count; naive cutoff treated as UTC | `0` |

### 2.3 Simulator 🔲

```mermaid
classDiagram
    class VehicleSimulator {
        -str vehicle_id
        -random.Random rng
        -float speed_kmh
        -float fuel_level_pct
        -float engine_temp_c
        -int route_index
        +VehicleSimulator(vehicle_id, rng, start_index=0)
        +next_reading(now: datetime) TelemetryReadingCreate | None
        -_step_speed() float
        -_rpm_for(speed) int
        -_step_fuel() float
        -_step_temp() float
        -_step_position() tuple~float, float~
    }
    class SimulatorModule {
        <<module services/simulator.py>>
        +ROUTE_LOOP tuple~tuple~float,float~~
        +make_vehicle_ids(count) list~str~
        +run_simulator(settings, session_factory, simulators) Coroutine
        -_tick(session_factory, simulators, now) int
        -_prune(session_factory, retention_minutes, now) int
    }
    class TelemetryService {
        <<module>>
    }
    class TelemetryReadingCreate

    SimulatorModule o-- "1..10" VehicleSimulator : one per vehicle
    VehicleSimulator ..> TelemetryReadingCreate : validates & returns
    SimulatorModule ..> TelemetryService : add_reading / prune_older_than
```

**Generator behaviour (`VehicleSimulator.next_reading`)**

| Field | Rule |
|---|---|
| `speed_kmh` | Bounded random walk: `speed += rng.uniform(-Δ, +Δ)`, clamped to `[0, 120]` (typical band, schema allows 250) |
| `engine_rpm` | `idle + speed * k + rng.gauss(0, σ)`, rounded and clamped to `[0, 8000]` |
| `fuel_level_pct` | `max(0, fuel − ε)` each tick — monotonic non-increasing, ≥ 0 |
| `engine_temp_c` | Exponential approach to ~90 °C plus small noise; starts ambient (~20 °C) |
| `latitude/longitude` | Advance `route_index` along `ROUTE_LOOP` (hardcoded fake coordinates in a generic location), wrap with `% len`; vehicles start at different offsets |
| `vehicle_id` | `make_vehicle_ids(n)` → `DEMO-VEH-001 … DEMO-VEH-00n` |

The reading is built with `TelemetryReadingCreate.model_validate(...)`; on `ValidationError` it returns `None` (the runner skips it). Same seed ⇒ same sequence; each vehicle owns independent state.

### 2.4 API layer 🔲

```mermaid
classDiagram
    class TelemetryRouter {
        <<APIRouter tags=telemetry>>
        +list_vehicles_route(session) list~str~  «GET /vehicles»
        +latest_route(vehicle_id, session) TelemetryReading  «GET /telemetry/latest»
        +recent_route(vehicle_id, limit=60, session) list~TelemetryReading~  «GET /telemetry»
    }
    class AppRoutes {
        <<main.py>>
        +health() dict  «GET /health»
        +dashboard() HTMLResponse  «GET /»
        +unhandled_exception_handler(request, exc) JSONResponse
        +lifespan(app) AsyncIterator
    }
    class Deps {
        <<api dependencies>>
        +VehicleIdParam = Annotated~str, Query(min 1, max 32, pattern)~
        +LimitParam = Annotated~int, Query(ge 1, le 300)~
        +require_known_vehicle(vehicle_id, session) str
    }

    TelemetryRouter ..> Deps
    TelemetryRouter ..> TelemetryService : delegates
    TelemetryRouter ..> TelemetryReading : response_model
    AppRoutes ..> TelemetryRouter : include_router
    AppRoutes ..> SimulatorModule : starts in lifespan
    AppRoutes ..> DatabaseModule : init_db()
```

---

## 3. Database design ✅

```mermaid
erDiagram
    TELEMETRY_READINGS {
        INTEGER id PK
        VARCHAR_32 vehicle_id "NOT NULL, indexed (composite)"
        DATETIME timestamp "NOT NULL, UTC, indexed (composite)"
        FLOAT speed_kmh "NOT NULL"
        INTEGER engine_rpm "NOT NULL"
        FLOAT fuel_level_pct "NOT NULL"
        FLOAT engine_temp_c "NOT NULL"
        FLOAT latitude "NOT NULL"
        FLOAT longitude "NOT NULL"
    }
```

- Single table; vehicles are not a separate entity (the "known vehicles" set is `DISTINCT vehicle_id`).
- Index `ix_telemetry_vehicle_timestamp (vehicle_id, timestamp)` serves `get_latest`, `get_recent` and range pruning per vehicle.
- Row volume: `vehicle_count × 3600 / interval` ≈ 7 200 rows for the defaults (retention 60 min) — pruning keeps it bounded.
- File databases: `PRAGMA journal_mode=WAL` set in `init_db()` so simulator writes and API reads don't block each other; `check_same_thread=False` because `asyncio.to_thread` uses pool threads. In-memory databases use `StaticPool` so one connection is shared (tests).
- **Timestamps:** SQLite drops tzinfo. Writes are always UTC; `TelemetryReadingCreate` re-normalises (naive ⇒ UTC) on every read via `model_validate`.

---

## 4. Sequence diagrams

### 4.1 Application startup and shutdown 🔲

```mermaid
sequenceDiagram
    autonumber
    participant U as uvicorn
    participant M as main.lifespan
    participant C as config.get_settings
    participant DB as database.init_db
    participant S as simulator.run_simulator (Task)

    U->>M: startup
    M->>C: get_settings()
    C-->>M: Settings
    M->>DB: init_db() (create tables, WAL)
    alt sim_enabled
        M->>S: asyncio.create_task(run_simulator(...))
    else disabled
        Note over M: no task started
    end
    M-->>U: yield (serving requests)
    U->>M: shutdown
    opt task running
        M->>S: task.cancel()
        S-->>M: CancelledError (awaited, swallowed)
    end
```

### 4.2 Simulator tick 🔲

```mermaid
sequenceDiagram
    autonumber
    participant R as run_simulator loop
    participant V as VehicleSimulator[i]
    participant T as asyncio.to_thread
    participant SV as services.telemetry
    participant DB as SQLite

    loop every SIM_INTERVAL_SECONDS
        R->>T: _tick(session_factory, simulators, now)
        activate T
        loop each vehicle
            T->>V: next_reading(now)
            V-->>T: TelemetryReadingCreate | None
            alt reading is not None
                T->>SV: add_reading(session, reading)
                SV->>DB: INSERT (parameterised)
            else dropped
                Note over T: skip, no raise
            end
        end
        deactivate T
        opt tick_count % 60 == 0
            R->>T: _prune(retention_minutes, now)
            T->>SV: prune_older_than(session, now - retention)
            SV->>DB: DELETE WHERE timestamp < cutoff
        end
        Note over R: exception in a tick → logged (no location data),<br/>loop continues
        R->>R: await asyncio.sleep(interval)
    end
```

### 4.3 Dashboard poll (happy path) 🔲

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser (index.html)
    participant A as FastAPI
    participant Dep as get_session / require_known_vehicle
    participant SV as services.telemetry
    participant DB as SQLite

    B->>A: GET /
    A-->>B: HTML (POLL_SECONDS injected)
    B->>A: GET /vehicles
    A->>Dep: session
    A->>SV: list_vehicles(session)
    SV->>DB: SELECT DISTINCT
    A-->>B: 200 ["DEMO-VEH-001", ...]
    loop every POLL_SECONDS
        B->>A: GET /telemetry?vehicle_id=...&limit=60
        A->>Dep: validate params, require_known_vehicle
        A->>SV: get_recent(session, vehicle_id, 60)
        SV->>DB: SELECT ... ORDER BY timestamp DESC LIMIT 60
        SV-->>A: list[TelemetryReading] (oldest→newest)
        A-->>B: 200 JSON
        B->>B: update tiles, charts, fuel bar, marker/trail (textContent only)
    end
```

### 4.4 Error handling 🔲

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant A as FastAPI
    participant V as Param validation
    participant D as require_known_vehicle
    participant SV as Service
    participant H as Exception handlers

    C->>A: GET /telemetry?vehicle_id=..&limit=..
    A->>V: validate query
    alt invalid (missing, limit 0/301, bad id)
        V-->>C: 422 {"detail": [...]}
    else valid
        A->>D: vehicle in list_vehicles?
        alt unknown vehicle
            D-->>C: 404 {"detail": "Vehicle not found"}
        else known
            A->>SV: get_recent(...)
            alt service raises
                SV-->>H: Exception
                Note over H: log type only, no stack trace in body
                H-->>C: 500 {"detail": "Internal server error"}
            else ok
                SV-->>C: 200 JSON
            end
        end
    end
```

### 4.5 Dashboard connection-loss handling 🔲

```mermaid
stateDiagram-v2
    [*] --> Loading
    Loading --> Live : first fetch ok
    Loading --> ConnectionLost : fetch fails
    Live --> Live : poll ok (update panels)
    Live --> ConnectionLost : fetch fails (show banner)
    ConnectionLost --> ConnectionLost : retry fails
    ConnectionLost --> Live : retry ok (hide banner)
    Live --> Loading : vehicle changed (reset charts/map)
```

---

## 5. Activity diagram — building one simulated reading 🔲

```mermaid
flowchart TD
    A([next_reading now]) --> B[Step speed: random walk, clamp 0..120]
    B --> C[RPM = idle + speed*k + noise, clamp 0..8000]
    C --> D[Fuel = max 0, fuel - epsilon]
    D --> E[Temp approaches ~90 C + noise]
    E --> F[route_index = route_index+1 mod len ROUTE_LOOP]
    F --> G[Build TelemetryReadingCreate]
    G --> H{Pydantic valid?}
    H -- yes --> I([return reading])
    H -- no --> J([return None - dropped])
```

---

## 6. Component and deployment view

```mermaid
flowchart LR
    subgraph Host["Developer machine (127.0.0.1)"]
        subgraph Proc["uvicorn process: telemetry.main:app"]
            direction TB
            EL["asyncio event loop<br/>(routes, simulator task)"]
            TP["worker threads<br/>(sync routes, to_thread)"]
            EL --> TP
        end
        F[("telemetry.db<br/>+ WAL files")]
        TP --> F
    end
    BR["Browser<br/>Chart.js + Leaflet (vendored)"]
    OSM["OpenStreetMap tile server<br/>(only external dependency)"]
    BR -- "HTTP :8000" --> Proc
    BR -- "tiles (optional)" --> OSM
```

Run command: `uvicorn telemetry.main:app --app-dir src` (binds `127.0.0.1` by default; no CORS).

---

## 7. API specification 🔲

| Method & path | Params | Success | Errors |
|---|---|---|---|
| `GET /vehicles` | — | `200` `list[str]` | `500` |
| `GET /telemetry/latest` | `vehicle_id` (required, 1–32, `^[A-Za-z0-9_-]+$`) | `200` `TelemetryReading` | `404` unknown vehicle or no data; `422` invalid id |
| `GET /telemetry` | `vehicle_id` (as above), `limit` int 1–300, default 60 | `200` `list[TelemetryReading]` oldest→newest | `404` unknown vehicle; `422` invalid input |
| `GET /health` | — | `200` `{"status": "ok"}` | — |
| `GET /` | — | `200` `text/html` dashboard | — |
| `GET /static/*` | — | static assets (`StaticFiles`) | `404` |

Response shape (`TelemetryReading`):

```json
{
  "id": 1,
  "vehicle_id": "DEMO-VEH-001",
  "timestamp": "2026-01-01T12:00:00Z",
  "speed_kmh": 50.0,
  "engine_rpm": 2000,
  "fuel_level_pct": 75.0,
  "engine_temp_c": 90.0,
  "latitude": 10.0,
  "longitude": 20.0
}
```

Error bodies are always `{"detail": ...}`; the 500 body is the constant `"Internal server error"`.

**Route design notes**

- Routes are `async def` (per project rules) and stay thin: validated params → service call → return. Because the injected `Session` is synchronous, DB work in routes must not block the event loop: either the route calls the service through `run_in_threadpool`, or the sync service is exposed through a sync dependency. The chosen approach is to wrap service calls in `fastapi.concurrency.run_in_threadpool`.
- `require_known_vehicle` is an API dependency that checks `vehicle_id in list_vehicles(session)` and raises `HTTPException(404)`.
- **Open point:** `list_vehicles` is derived from stored readings, so a "known vehicle with no readings" (spec §16.2) cannot occur while it is DB-derived — such a vehicle is simply unknown and returns `404` on both routes. Making `/telemetry` return `[]` for a configured-but-empty vehicle would require validating against the configured IDs (`make_vehicle_ids(sim_vehicle_count)`) instead. Decide before Phase 5.

---

## 8. Dashboard design 🔲

### 8.1 Frontend modules (single `index.html`, inline JS)

```mermaid
classDiagram
    class Poller {
        +int POLL_SECONDS  «injected by GET /»
        +start() void
        +tick() Promise
        -fetchJson(url) Promise
    }
    class State {
        +string selectedVehicle
        +Reading[] readings
        +bool connectionLost
    }
    class VehicleSelector {
        +populate(ids) void
        +onChange() void
    }
    class Tiles {
        +render(latest) void
        -markTempHot(temp > 110) void
    }
    class Charts {
        +Chart speedChart
        +Chart rpmChart
        +Chart tempChart
        +update(readings) void
        +reset() void
    }
    class FuelBar {
        +render(fuelPct clamp 0..100) void
    }
    class MapView {
        +Leaflet map
        +Marker marker
        +Polyline trail
        +update(readings) void
        +reset() void
    }
    class Banner {
        +show() void
        +hide() void
    }

    Poller --> State
    Poller --> Tiles
    Poller --> Charts
    Poller --> FuelBar
    Poller --> MapView
    Poller --> Banner
    VehicleSelector --> State
    VehicleSelector ..> Charts : reset on change
    VehicleSelector ..> MapView : reset on change
```

### 8.2 Panel data mapping

| Panel | Field(s) used | Update rule |
|---|---|---|
| Speed / RPM / Temp tiles | newest item's `speed_kmh`, `engine_rpm`, `engine_temp_c` | `textContent`; temp tile red when > 110 °C |
| Three line charts | last ≤ 60 readings, x = `timestamp`, y = metric | update datasets in place, animations off |
| Fuel bar | newest `fuel_level_pct` (clamped 0–100) | set bar width + label |
| Map | marker = newest lat/lon; trail = last ≤ 60 points | `setLatLng` / `setLatLngs`, auto-pan; tile failure tolerated |
| Status | fetch result | "● Live" vs "Connection lost" banner |

Rules: only `textContent` (never `innerHTML`); only the single poll call `/telemetry?limit=60`; all Chart.js/Leaflet assets are served from `/static/vendor/…`.

---

## 9. Cross-cutting design

### 9.1 Configuration

| Env var | Field | Default | Validation |
|---|---|---|---|
| `DATABASE_URL` | `database_url` | `sqlite:///./telemetry.db` | non-empty |
| `SIM_INTERVAL_SECONDS` | `sim_interval_seconds` | `1` | > 0 |
| `SIM_VEHICLE_COUNT` | `sim_vehicle_count` | `2` | 1–10 |
| `RETENTION_MINUTES` | `retention_minutes` | `60` | > 0 |
| `DASHBOARD_POLL_SECONDS` | `dashboard_poll_seconds` | `2` | > 0 |
| `SIM_ENABLED` | `sim_enabled` | `true` | bool |

`load_settings()` calls `load_dotenv()`, reads only those names, and validates via Pydantic; `get_settings()` caches the result (tests call `cache_clear()`).

### 9.2 Concurrency model

- One writer (simulator, via `to_thread`) and many readers (API). WAL allows concurrent read/write; transactions are one commit per call, kept short.
- Sessions are never shared across threads: the runner opens a session per tick/prune from `create_session_factory`; API requests get one per request from `get_session`.
- Shutdown: lifespan cancels the simulator task and awaits it; an in-flight DB call finishes inside its thread.

### 9.3 Error and logging policy

- Services raise ordinary exceptions; API turns expected cases into 404/422 and everything else into the generic 500 via a catch-all handler.
- Logs contain event type and counts only — **never** latitude/longitude, DB URLs with credentials, or stack traces in HTTP responses.

### 9.4 Security controls

| Concern | Control |
|---|---|
| Injection | ORM / bound parameters only; `vehicle_id` pattern-restricted; no `eval`/`exec` |
| XSS | `textContent` only; static gate test for `innerHTML` |
| Data privacy | Fake IDs and a generic fake route; no personal data |
| Secrets | None in code; `.env*` git-ignored, only `.env.example` committed |
| Network | Binds `127.0.0.1`; no CORS; no auth (non-goal) |
| Supply chain | Pinned MIT/Apache/BSD dependencies; vendored frontend libs with licences |

### 9.5 Extensibility notes (not in scope)

Swapping SQLite for another DB needs only `DATABASE_URL` (engine setup already branches on backend). WebSockets, alerts and export are explicit non-goals.

---

## 10. Traceability

| Design element | Spec | Plan phase | Status | Tests |
|---|---|---|---|---|
| `Settings`, `get_settings` | §9 | 1 | ✅ | `tests/test_config.py` |
| `TelemetryReading*` schemas | §5 | 1 | ✅ | `tests/models/test_schemas.py` |
| `TelemetryReadingORM` + index | §5 | 1 | ✅ | `tests/models/test_orm.py` |
| `database.py` (engine, WAL, session) | §3, risks | 1 | ✅ | `tests/models/test_database.py` |
| Telemetry service | §6, §16.2 | 2 | ✅ | `tests/services/test_telemetry.py` |
| `VehicleSimulator`, `make_vehicle_ids` | §8 | 3 | 🔲 | `tests/services/test_simulator.py` |
| Simulator runner + lifespan | §3, §16.7 | 4 | 🔲 | runner / lifespan tests |
| Routes, handlers, `/health` | §6, §16.2 | 5 | 🔲 | `tests/api/test_telemetry.py` |
| Dashboard shell | §7, §16.3–4 | 6 | 🔲 | `tests/api/test_dashboard.py` |
| Charts + fuel bar | §7 | 7 | 🔲 | dashboard + payload tests |
| Map | §7, §16.5 | 8 | 🔲 | dashboard asset tests |
