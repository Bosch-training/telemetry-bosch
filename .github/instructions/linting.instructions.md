---
description: Code style, linting, and typing standards for Python files
applyTo: "**/*.py"
---
# Linting and Style Instructions

- Follow PEP 8; format with `black` (line length 88).
- Lint with `ruff check .` and fix all warnings before committing.
- Add type hints to all function signatures and keep code clean under `mypy`.
- Add docstrings to public functions and classes; comment only where code isn't self-explanatory.
- Naming: `snake_case` for functions and variables, `PascalCase` for classes, `UPPER_CASE` for constants.
- Tool configuration lives in `pyproject.toml`.
