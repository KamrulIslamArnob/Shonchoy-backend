"""Store supplied Neon branch URLs privately; never prints credentials or runs migrations."""

import argparse
import os
import subprocess
from pathlib import Path

from dotenv import dotenv_values

from fintrack_core.database import postgres_url

PROJECT = "winter-surf-88756036"
BRANCH = "br-billowing-star-b4ih39ph"  # The single production branch for auth and finance.
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--replace-database-urls", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
target = root / ".env"
values = dotenv_values(target) if target.exists() else {}
updates = {}
for name, pooled in [("FINTRACK_DATABASE_URL", True), ("FINTRACK_MIGRATION_DATABASE_URL", False)]:
    if values.get(name) and not args.replace_database_urls:
        print(f"Preserved existing {name}.")
        continue
    command = ["npx", "--yes", "neon@8.8.0", "connection-string", BRANCH, "--project-id", PROJECT]
    if pooled:
        command.append("--pooled")
        command.extend(["--role-name", "shonchoy_runtime"])
    else:
        command.extend(["--role-name", "neondb_owner"])
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise SystemExit(
            "Neon connection lookup failed. Sign in with npx neon@latest auth and retry."
        )
    raw = result.stdout.strip()
    postgres_url(raw)
    if not pooled:
        raw = raw.replace("-pooler.", ".")
    updates[name] = raw
if updates:
    # URL characters are data. Dotenv single quotes safely preserve them without interpolation.
    lines = []
    for name, value in updates.items():
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        lines.append(f"{name}='{escaped}'\n")
    existing = target.read_text() if target.exists() else ""
    if args.replace_database_urls:
        existing = "\n".join(
            line
            for line in existing.splitlines()
            if not any(line.startswith(name + "=") for name in updates)
        )
    target.write_text(existing + "\n" + "".join(lines))
    os.chmod(target, 0o600)
    print("Stored Neon runtime and direct migration URLs in backend/.env (mode 0600).")
print(f"Target: project {PROJECT}, branch {BRANCH}. No migration was applied.")
