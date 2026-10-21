"""Initialize missing local settings with random tokens; preserve existing values."""

import os
from pathlib import Path
from secrets import token_urlsafe

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
for filename, name in [
    (".env", "FINTRACK_DEV_API_KEY"),
    (".env.advisor", "FINTRACK_ADVISOR_DEV_API_KEY"),
]:
    target = root / filename
    if dotenv_values(target).get(name):
        print(f"Preserved {filename} development token.")
        continue
    with target.open("a") as file:
        file.write(f"\n{name}={token_urlsafe(48)}\n")
    os.chmod(target, 0o600)
    print(f"Initialized {filename} with a private random development token.")
