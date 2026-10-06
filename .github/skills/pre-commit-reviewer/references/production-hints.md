# Production Hardening Hints

The bundled script is a demo-grade starting point. For team or production use:

1. **Use a dedicated secret scanner.** Replace the regex scan with `gitleaks` or `detect-secrets` (baseline file, entropy checks, allowlists).
2. **Enforce in the hook and CI, not only via the agent.** Wire the checks through the `pre-commit` framework (`.pre-commit-config.yaml`) and re-run them in CI so they cannot be bypassed with `--no-verify`.
3. **Scope tests.** Run only tests affected by the staged files (`pytest --testmon` or path mapping), and keep full runs for CI.
4. **Add SAST and dependency checks.** `bandit` or `semgrep` for code, `pip-audit` for vulnerable dependencies, and a license check for MIT/Apache-2.0/BSD only.
5. **Check staged content, not the working tree.** Run tools against the index (`git stash --keep-index` or `git show :path`) so unstaged edits do not mask problems.
6. **Structured output.** Emit SARIF or JSON (`--json` already exists) so results appear in PR annotations and dashboards.
7. **Configurable policy.** Move patterns, severity levels and file limits into a config file (e.g. `review.toml`) instead of constants in the script.
8. **Conventional commits.** Validate the commit message format and link to a ticket via a `commit-msg` hook.
9. **Performance.** Cache tool results, run checks in parallel, and set timeouts on subprocess calls.
10. **Pin and test tooling.** Pin tool versions in `requirements.txt` and add unit tests for the script itself (pattern matching, placeholder handling, hunk parsing).
11. **Agent guardrails.** Keep the skill read-only; add a hook or custom agent with restricted tools if you need to guarantee it never edits or commits.
12. **Audit trail.** Store review reports as CI artifacts for compliance traceability.
