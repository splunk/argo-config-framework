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
import tempfile
import unittest

from framework.config import STEP_PHASES, load_conf_catalog
from framework.conf_validator import validate_catalog


ROOT = Path(__file__).parents[1]
NGINX_CATALOG = ROOT / "examples" / "nginx" / "nginx_config.json"


class CatalogTests(unittest.TestCase):
    def test_aggregate_catalog_is_validated_and_loaded(self):
        loaded = json.loads(load_conf_catalog(NGINX_CATALOG))
        self.assertIn("nginx_rate_limit", loaded)

    def test_directory_catalog_has_same_normalized_shape(self):
        aggregate = json.loads(NGINX_CATALOG.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nginx_rate_limit.json"
            path.write_text(json.dumps(aggregate["nginx_rate_limit"]))
            loaded = json.loads(load_conf_catalog(tmp))
        self.assertEqual(aggregate, loaded)

    def test_wrong_phase_step_is_rejected(self):
        catalog = json.loads(NGINX_CATALOG.read_text())
        app = catalog["nginx_rate_limit"]["single"]["targets"]["nginx"]["apps"]["system"]
        app["execution"]["steps"].append({"name": "health_check"})
        with self.assertRaisesRegex(ValueError, "not valid in phase 'execution'"):
            validate_catalog(catalog, STEP_PHASES)

    def test_missing_guardrail_pair_is_rejected(self):
        catalog = json.loads(NGINX_CATALOG.read_text())
        guardrails = catalog["nginx_rate_limit"]["single"]["targets"]["nginx"]["apps"]["system"]["guardrails"]
        del guardrails["forbidden_apps"]
        with self.assertRaisesRegex(ValueError, "forbidden_apps"):
            validate_catalog(catalog, STEP_PHASES)

    def test_empty_state_store_reference_is_rejected(self):
        catalog = json.loads(NGINX_CATALOG.read_text())
        app = catalog["nginx_rate_limit"]["single"]["targets"]["nginx"]["apps"]["system"]
        app["state_store_ref"] = ""
        with self.assertRaisesRegex(ValueError, "state_store_ref"):
            validate_catalog(catalog, STEP_PHASES)


if __name__ == "__main__":
    unittest.main()
