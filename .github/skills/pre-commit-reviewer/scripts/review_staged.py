"""Run read-only pre-commit checks against staged files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "Private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "Hardcoded credential": re.compile(
        r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*['\"][^'\"]{8,}['\"]"
    ),
}
REPO_ROOT = Path(__file__).resolve().parents[4]
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
PLACEHOLDER = re.compile(r"(?i)changeme|placeholder|example|your[_-]|<.*>|xxx")
UNSAFE_CALL = re.compile(r"\b(eval|exec)\s*\(")
SENSITIVE_FILE = re.compile(r"(^|/)\.env(\..+)?$")

# Review priority: lower index is reviewed first.
AREA_PRIORITY = ["api", "services", "models", "config", "visualization"]
AREA_PRIORITY += ["tests", "other", "docs"]
CODE_AREAS = set(AREA_PRIORITY) - {"other", "docs"}
LIGHT_MAX_LINES = 30
HEAVY_MIN_LINES = 400
HEAVY_MIN_FILES = 15
MAX_PRINTED_FINDINGS = 20
MAX_REVIEW_ORDER = 10


@dataclass
class Finding:
    severity: str  # blocker | warning
    check: str
    location: str
    message: str


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, check=False
    )  # noqa: S603


def staged_files() -> list[str]:
    out = run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    files = [f for f in out.stdout.splitlines() if f]
    # Never inspect real env files; only .env.example is allowed.
    return [f for f in files if not SENSITIVE_FILE.search(f) or f.endswith(".example")]


def area_of(path: str) -> str:
    if path.startswith("tests/"):
        return "tests"
    if path.startswith("src/telemetry/api/") or path.endswith("telemetry/main.py"):
        return "api"
    for area in ("services", "models", "visualization"):
        if path.startswith(f"src/telemetry/{area}/"):
            return area
    if path.endswith("telemetry/config.py"):
        return "config"
    if path.startswith("docs/") or path.endswith((".md", ".txt")):
        return "docs"
    return "other"


def changed_lines(files: list[str]) -> dict[str, int]:
    out = run(["git", "diff", "--cached", "--numstat", "--diff-filter=ACMR"])
    counts: dict[str, int] = {}
    for row in out.stdout.splitlines():
        added, deleted, path = row.split("\t", 2)
        if path in files:
            # Binary files report "-"; count them as one line.
            counts[path] = (int(added) + int(deleted)) if added != "-" else 1
    return counts


def choose_tier(file_count: int, total: int, areas: set[str], has_blocker: bool) -> str:
    if has_blocker:
        return "fail-fast"
    if not areas & CODE_AREAS or total <= LIGHT_MAX_LINES:
        return "light"
    if total >= HEAVY_MIN_LINES or file_count >= HEAVY_MIN_FILES:
        return "heavy"
    return "standard"


def review_order(counts: dict[str, int]) -> list[str]:
    ranked = sorted(counts, key=lambda p: (AREA_PRIORITY.index(area_of(p)), -counts[p]))
    return [f"{p}({counts[p]})" for p in ranked[:MAX_REVIEW_ORDER]]


def added_lines(path: str) -> list[tuple[int, str]]:
    diff = run(["git", "diff", "--cached", "-U0", "--", path]).stdout
    result: list[tuple[int, str]] = []
    line_no = 0
    for line in diff.splitlines():
        hunk = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
        if hunk:
            line_no = int(hunk.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            result.append((line_no, line[1:]))
            line_no += 1
    return result


def scan_content(files: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        for line_no, text in added_lines(path):
            loc = f"{path}:{line_no}"
            for kind, pattern in SECRET_PATTERNS.items():
                if pattern.search(text) and not PLACEHOLDER.search(text):
                    findings.append(Finding("blocker", "secrets", loc, kind))
            if path.startswith("src/") and path.endswith(".py"):
                if UNSAFE_CALL.search(text):
                    findings.append(
                        Finding("blocker", "security", loc, "eval/exec is forbidden")
                    )
    return findings


def tool_check(name: str, cmd: list[str]) -> list[Finding]:
    result = run(cmd)
    if result.returncode == 0:
        return []
    detail = (result.stdout + result.stderr).strip().splitlines()
    summary = detail[-1] if detail else "failed"
    return [Finding("blocker", name, "-", summary)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", action="store_true", help="also run pytest")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    files = staged_files()
    if not files:
        print("No staged files.")
        return 0

    counts = changed_lines(files)
    total = sum(counts.values())
    areas = {area_of(f) for f in files}
    py_files = [f for f in files if f.endswith(".py") and Path(f).exists()]
    src_files = [f for f in py_files if f.startswith("src/")]
    if not VENV_PYTHON.exists():
        print(f"Virtual environment missing: create it at {VENV_PYTHON.parent.parent}")
        return 1
    py = str(VENV_PYTHON)

    # Cheap checks first; slow ones run only if nothing has failed yet.
    findings = scan_content(files)
    if py_files:
        findings += tool_check("ruff", [py, "-m", "ruff", "check", *py_files])
        findings += tool_check("black", [py, "-m", "black", "--check", *py_files])
    slow: list[tuple[str, list[str]]] = []
    if src_files:
        slow.append(("mypy", [py, "-m", "mypy", *src_files]))
    if args.tests and py_files:
        slow.append(("pytest", [py, "-m", "pytest", "-q"]))
    skipped: list[str] = []
    for name, cmd in slow:
        if any(f.severity == "blocker" for f in findings):
            skipped.append(name)
        else:
            findings += tool_check(name, cmd)
    if len(files) >= HEAVY_MIN_FILES:
        findings.append(
            Finding("warning", "scope", "-", f"{len(files)} files staged; split?")
        )

    blockers = [f for f in findings if f.severity == "blocker"]
    tier = choose_tier(len(files), total, areas, bool(blockers))
    order = [] if tier in ("fail-fast", "light") else review_order(counts)
    if args.json:
        payload = {
            "tier": tier,
            "files": len(files),
            "changed_lines": total,
            "areas": sorted(areas),
            "skipped": skipped,
            "review_order": order,
            "findings": [asdict(f) for f in findings],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"tier={tier} files={len(files)} changed={total} "
            f"areas={','.join(sorted(areas))}"
        )
        if skipped:
            print(f"skipped (blockers found): {', '.join(skipped)}")
        for f in findings[:MAX_PRINTED_FINDINGS]:
            print(f"[{f.severity.upper()}] {f.check} {f.location} - {f.message}")
        if len(findings) > MAX_PRINTED_FINDINGS:
            print(f"... {len(findings) - MAX_PRINTED_FINDINGS} more findings")
        if order:
            print("review_order:", " ".join(order))
        print("RESULT:", "FAIL" if blockers else "PASS")
    return 1 if blockers else 0


if __name__ == "__main__":
    sys.exit(main())
