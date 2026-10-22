"""Run every backend gate; preserve UTC evidence and fail on unavailable tools."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

root = Path(__file__).resolve().parents[1]
stamp = datetime.now(UTC).isoformat().replace(":", "-")
output = root.parent / ".local" / "reports" / "backend" / stamp
output.mkdir(parents=True, exist_ok=True)
uv = root.parent / ".local" / "tools" / "backend" / "bin" / "uv"
uv_cmd = str(uv) if uv.exists() else "uv"
commands = {
    "lock": [uv_cmd, "lock", "--check"],
    "audit-export": [
        uv_cmd,
        "export",
        "--locked",
        "--no-emit-project",
        "--format",
        "requirements-txt",
        "--output-file",
        str(output / "requirements.txt"),
    ],
    "lint": [sys.executable, "-m", "ruff", "check", "."],
    "format": [sys.executable, "-m", "ruff", "format", "--check", "."],
    "types": [sys.executable, "-m", "mypy", "--cache-dir", "../.local/cache/backend-mypy"],
    "tests": [sys.executable, "-m", "pytest", "-o", "cache_dir=../.local/cache/backend-pytest"],
    "static-analysis": [sys.executable, "-m", "bandit", "-r", "src", "alembic", "-q"],
    "dependencies": [
        sys.executable,
        "-m",
        "pip_audit",
        "--strict",
        "--disable-pip",
        "--require-hashes",
        "--no-deps",
        "-r",
        str(output / "requirements.txt"),
    ],
    "openapi": [sys.executable, "scripts/export_openapi.py"],
}
checks = []
for name, command in commands.items():
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "LANGSMITH_TRACING": "false", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        )
        code, log = result.returncode, result.stdout + result.stderr
    except (OSError, subprocess.TimeoutExpired) as error:
        code, log = 2, f"Check unavailable: {type(error).__name__}"
    (output / f"{name}.log").write_text(log)
    checks.append({"name": name, "code": code, "passed": code == 0})
    print(f"{'PASS' if code == 0 else 'FAIL'} backend {name}", flush=True)
    if code:
        print(log[-5000:], flush=True)
report = {
    "startedAt": stamp,
    "finishedAt": datetime.now(UTC).isoformat(),
    "checks": checks,
    "passed": all(c["passed"] for c in checks),
    "liveNeonVerified": False,
}
(output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
print(f"Backend evidence: {output.relative_to(root.parent)}/summary.json")
sys.exit(0 if report["passed"] else 1)
