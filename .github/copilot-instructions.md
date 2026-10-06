# Project Name
Vehicle Telemetry Visualisation

# Project Description
A small demo Python application that visualises simulated vehicle telemetry (speed, engine RPM, fuel level, engine temperature, GPS location). It simulates, validates and stores the readings, exposes them through a simple REST API, and presents them in an interactive dashboard with time-series charts, gauges and a GPS route map. It is for demonstration only and is not production-grade.

# Tech Stack
- Python 3.11+
- FastAPI + Uvicorn (REST API serving data to the dashboard)
- Pydantic (data models and validation)
- SQLite via SQLAlchemy (storage)
- Streamlit (interactive dashboard)
- Plotly (charts, gauges and GPS route map)
- pandas (shaping telemetry data for charts)
- pytest (testing)
- Ruff and Black (linting and formatting)
- python-dotenv (configuration)

# Folder Structure
```
telemetry-bosch/
├── .github/
│   ├── copilot-instructions-2.md
│   └── instructions/        # Scoped *.instructions.md files
├── src/
│   └── telemetry/
│       ├── __init__.py
│       ├── main.py          # FastAPI app entry point
│       ├── api/             # Routes (read-only data for visualisation)
│       ├── models/          # Pydantic schemas and DB models
│       ├── services/        # Business logic, telemetry simulator, data aggregation
│       ├── visualization/   # Dashboard app, chart builders, map and gauge components
│       └── config.py        # Settings loaded from environment
├── tests/                   # Mirrors src/telemetry structure
├── .env.example             # Placeholder config values only
├── requirements.txt
├── pyproject.toml           # Ruff, Black, pytest config
└── README.md
```

# Visualisation Guidelines
- Keep chart-building logic in pure functions under `visualization/` that take data and return Plotly figures, so they can be unit tested without running Streamlit.
- The dashboard reads data through the REST API or the service layer; it must not query the database directly.
- Show units on every metric (km/h, RPM, %, °C) and label axes and legends clearly.
- Handle empty or missing data gracefully with a clear placeholder message instead of an error.
- Downsample or limit points per chart to keep the dashboard responsive.
- Use simulated GPS data only; never plot real vehicle locations.

# Detailed Instructions
Follow the scoped instruction files below. Each applies to matching files, and all apply to any change.

- [Development](./instructions/development.instructions.md): architecture, layering, simulator and data rules (`src/**/*.py`)
- [API](./instructions/api.instructions.md): FastAPI routes, validation, error handling (`src/telemetry/api/`, `main.py`)
- [Testing](./instructions/testing.instructions.md): pytest, coverage, test data rules (`tests/**/*.py`)
- [Linting and style](./instructions/linting.instructions.md): Ruff, Black, mypy, naming (`**/*.py`)
- [Security and compliance](./instructions/security.instructions.md): compliance, secrets, sensitive data (all files)
