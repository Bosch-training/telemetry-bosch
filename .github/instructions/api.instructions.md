---
description: REST API design and error-handling guidelines for FastAPI routes
applyTo: "src/telemetry/api/**/*.py,src/telemetry/main.py"
---
# API Instructions

- Declare `response_model`, status codes, and `tags` on every route; use Pydantic models for request bodies and query params.
- Use plural, noun-based resource paths (e.g. `/telemetry`) and correct HTTP verbs/status codes (201 create, 404 missing, 422 invalid).
- Validate all input (types, ranges, lengths) and return clear, structured error responses.
- Register exception handlers so unexpected errors return a generic 500 message; never expose stack traces or internals.
- Do not log or return precise location data beyond what the demo schema requires.
- Keep route handlers thin and delegate logic to `services/`.
- Add docstrings/summaries so the OpenAPI docs stay readable.
