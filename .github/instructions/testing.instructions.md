---
description: Unit testing guidelines using pytest
applyTo: "tests/**/*.py"
---
# Testing Instructions

- Use `pytest` with `pytest-cov`; use FastAPI `TestClient` for API tests.
- Name files `test_<module>.py` in `tests/`, mirroring the `src/telemetry` structure.
- Use arrange-act-assert and fixtures (`conftest.py`) for shared setup.
- Use an in-memory or temporary SQLite database; no real network or external services.
- Cover normal, boundary (e.g. 0 or max speed, fuel 0/100, lat/lon limits) and invalid input cases, including expected 4xx responses.
- Assert error responses never expose stack traces.
- Use fake data only (fake VINs and coordinates); no secrets in tests.
- Target at least 80% coverage. Run with `pytest --cov=src`.
