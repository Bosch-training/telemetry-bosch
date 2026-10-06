#!/usr/bin/env bash
# Optional: copy to .git/hooks/pre-commit and make executable.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
python .github/skills/pre-commit-reviewer/scripts/review_staged.py
