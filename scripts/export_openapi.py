"""Export credential-free contracts, without connecting to a database."""

import json
from pathlib import Path

from fintrack_advisor.config import Settings as AdvisorSettings
from fintrack_advisor.main import create_app as advisor
from fintrack_core.config import Settings as CoreSettings
from fintrack_core.main import create_app as core

output = Path(__file__).resolve().parents[2] / ".local" / "backend" / "openapi"
output.mkdir(parents=True, exist_ok=True)
for name, app in [
    ("core", core(CoreSettings(_env_file=None))),
    ("advisor", advisor(AdvisorSettings(_env_file=None))),
]:
    (output / f"{name}.json").write_text(json.dumps(app.openapi(), indent=2) + "\n")
    print(f"Exported {name} OpenAPI")
