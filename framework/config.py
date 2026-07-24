# Copyright 2026 Splunk Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
from pathlib import Path

from .resources import data_path

# ── Workflow constants ─────────────────────────────────────────────────────────

WORKFLOW_TIMEOUT = 3600  # seconds

# ── Steps catalog ─────────────────────────────────────────────────────────────

_STEPS_CATALOG_PATH = data_path("steps_catalog.json")
_STEP_ITEMS = json.loads(_STEPS_CATALOG_PATH.read_text(encoding="utf-8"))
STEP_PHASES: dict[str, frozenset[str]] = {
    item["name"]: frozenset(item.get("phases", []))
    for item in _STEP_ITEMS
}
KNOWN_STEPS: frozenset[str] = frozenset(STEP_PHASES)

# ── Catalog loader + validation ────────────────────────────────────────────────

def load_conf_catalog(catalog_path: str | Path) -> str:
    from .conf_validator import validate_catalog

    catalog_path = Path(catalog_path)
    if catalog_path.is_dir():
        catalog = {}
        for p in sorted(catalog_path.glob("*.json")):
            if p.stem != "template":
                catalog[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    else:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    validate_catalog(catalog, STEP_PHASES)
    return json.dumps(catalog)
