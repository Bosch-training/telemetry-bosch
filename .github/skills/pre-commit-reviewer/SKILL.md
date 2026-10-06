---
name: pre-commit-reviewer
description: 'Review staged git changes before commit. Use when asked to review before commit, pre-commit review, check staged changes, review my diff, or verify a commit is ready. Runs ruff, black, mypy, pytest and a secret/unsafe-code scan on staged files, then produces a PASS/FAIL report against the project standards. Adapts review depth to diff size to save tokens.'
argument-hint: 'Optional: --tests to also run pytest, --json for machine output'
---

# Pre-Commit Reviewer

Reviews only what is staged (`git diff --cached`) and reports blockers, warnings and suggestions before the user commits. Read-only: never modify, stage or commit files.

## When to Use
- "Review before I commit", "check my staged changes", "is this ready to commit?"
- Before running `git commit` on changes under `src/` or `tests/`

## Procedure
0. All tools run from the project `.venv` (`.venv/bin/python`); the script uses it automatically and fails if `.venv` is missing. Run the script with `.venv/bin/python`, and any extra commands (ruff, black, mypy, pytest) via `.venv/bin/python -m <tool>`.
1. Run the triage script first. It is cheap and decides how deep the review goes:
   `.venv/bin/python .github/skills/pre-commit-reviewer/scripts/review_staged.py` (add `--tests` when `src/` or `tests/` is staged; `--json` for JSON).
   - "No staged files." means stop and tell the user.
   - The script skips `.env*` files (except `.env.example`); never open them yourself.
2. Branch on the `tier=` value in the first output line:

   | Tier | Meaning | What to do |
   |------|---------|-----------|
   | `fail-fast` | Script found blockers | Do **not** read the diff or checklist. Report the blockers with fixes and verdict `FAIL`. Note any `skipped` tools and tell the user to re-run after fixing. |
   | `light` | Docs/config only, or 30 or fewer changed lines, no findings | Do not load the checklist. Glance at `git diff --cached -U0` only if the change touches code; verdict is usually `PASS`. |
   | `standard` | Moderate code change, no findings | Review files in `review_order` using `git diff --cached -U0 -- <file>`, one file at a time. Load only the [checklist](./references/checklist.md) sections matching `areas`. |
   | `heavy` | 400 or more changed lines, or 15 or more files | Review only the first entries of `review_order` (highest-risk areas first). Mark the rest "not reviewed in depth" and recommend splitting the commit. Ask the user before reading more. |

3. Classify each finding as:
   - **Blocker**: secrets, `eval`/`exec`, lint/type/test failures, real (non-simulated) data, missing tests for new logic.
   - **Warning**: missing type hints, large diff, unrelated changes mixed in.
   - **Suggestion**: readability or naming improvements.
4. Write the report using [the report template](./assets/report-template.md); see [a sample](./assets/sample-report.md). Omit empty sections and keep it short.
5. Verdict: `FAIL` if any blocker, else `PASS` (with warnings). Do not fix issues unless the user asks.

## Token Rules
- Never run `git diff --cached` without `-U0` and a file path; never print the whole diff.
- Do not re-read files or re-run the script unless the user changed something.
- Do not load [production hints](./references/production-hints.md) unless the user asks about hardening, CI or hooks.
- Do not review unstaged or untracked files.

## Rules
- Cite `file:line` for each finding and give a one-line fix.
- Never print secret values; show only the file, line and kind of secret.
