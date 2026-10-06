# Pre-Commit Review

**Verdict:** FAIL
**Staged files:** 3
**Checks run:** ruff, black, mypy, secrets scan, pytest

## Blockers
- `src/telemetry/services/simulator.py:42` - `eval()` used to parse a config expression. Fix: use `ast.literal_eval` or a typed Pydantic field.
- `src/telemetry/config.py:11` - Hardcoded credential. Fix: read from an environment variable and add a placeholder to `.env.example`.
- `mypy` - `simulator.py:57: Missing return type annotation`. Fix: annotate the return type.

## Warnings
- `src/telemetry/services/simulator.py:70` - New branch for engine overheating has no test. Fix: add a case in `tests/services/`.

## Suggestions
- `src/telemetry/services/simulator.py:15` - Rename `tmp` to `engine_temp_c` to show the unit.

## Summary
Not ready to commit: remove `eval` and the hardcoded credential, fix the typing error, then re-run the review.
