---
description: Development guidelines for the telemetry application source code
applyTo: "src/**/*.py"
---
# Development Instructions

- Keep layers separate: `api/` (routes only), `services/` (business logic and simulator), `models/` (Pydantic schemas and SQLAlchemy models), `config.py` (settings).
- Routes must be thin: validate input with Pydantic, delegate to a service, return a response model.
- Use `async def` for route handlers; keep blocking DB work in services behind a session dependency (`Depends`).
- Simulated readings must stay within realistic ranges (speed, RPM, fuel 0-100%, engine temperature, valid GPS lat/lon) and be validated before storage.
- Use fake VINs and coordinates only; never include real vehicle, driver, or customer data.
- Read configuration from `config.py` (environment variables via python-dotenv); never hardcode values.
- Use SQLAlchemy parameterized queries/ORM only; no `eval`/`exec`, no string-built SQL.
- Pin every new dependency in `requirements.txt` and use only MIT, Apache-2.0, or BSD licensed packages.
- Follow [coding standards](./linting.instructions.md) and add tests per [testing instructions](./testing.instructions.md).
