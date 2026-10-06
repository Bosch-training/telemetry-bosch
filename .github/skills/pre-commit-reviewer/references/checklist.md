# Manual Review Checklist

Derived from `.github/instructions/` (development, api, linting, security, testing).

Load only the sections for the `areas` reported by the script:

| Area | Sections |
|------|----------|
| `api` | Architecture, API, Typing and Style, Security and Compliance |
| `services`, `models`, `config` | Architecture, Typing and Style, Security and Compliance |
| `visualization` | Architecture, Typing and Style |
| `tests` | Tests |
| any | Scope (only for `heavy` tier) |

## Architecture
- Routes in `api/` are thin; business logic lives in `services/`.
- Schemas/ORM in `models/`; settings only via `config.py`.
- Dashboard code in `visualization/` does not query the database directly.
- Chart builders are pure functions returning Plotly figures.

## Typing and Style
- Type hints on all function signatures; `mypy --strict` clean.
- PEP 8, line length 88, no unused imports or dead code.

## Security and Compliance
- No secrets, tokens or passwords; config comes from environment variables.
- No `eval`/`exec`; ORM or parameterized queries only; inputs validated.
- Simulated data only: no real VIN, driver identity or real GPS history.
- No sensitive values in logs.
- New dependencies are pinned in `requirements.txt` with MIT/Apache-2.0/BSD licenses.

## Tests
- New or changed logic has matching tests under `tests/` mirroring `src/telemetry`.
- Tests are deterministic (no real time, network or randomness without a seed or fake).
- No tests skipped, weakened or deleted to make the commit pass.

## API
- Correct status codes and error responses; read-only endpoints for visualisation data.
- Request/response models declared with Pydantic.

## Scope
- Diff contains one logical change; no unrelated refactors or stray debug prints.
