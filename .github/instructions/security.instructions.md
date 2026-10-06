---
description: Compliance and sensitive-information handling rules
applyTo: "**"
---
# Security and Compliance Instructions

## Compliance
- Telemetry data is demo/simulated only; never use real vehicle or customer data.
- Do not collect or store personal data (driver identity, real VIN, real GPS history).
- Use only permissively licensed open-source dependencies (MIT, Apache-2.0, BSD) and pin versions in `requirements.txt`.
- Follow OWASP basics: no `eval`/`exec`, parameterized queries only, validate all input.

## Sensitive information
- Never hardcode secrets, API keys, tokens, or passwords in code, tests, or docs.
- Load configuration from environment variables; commit only `.env.example` with placeholder values.
- Keep `.env` and any real `.env.*` files in `.gitignore`; do not read or print them.
- Do not log sensitive values (credentials, tokens, precise location data).
- If a secret is committed by mistake, rotate it immediately.
