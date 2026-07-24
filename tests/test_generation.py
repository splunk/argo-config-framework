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
from unittest.mock import patch

import yaml

from framework.dag_builder import load_adapter
from framework.cli import main
from framework.patch_builder import load_patch_builder
from framework.workflow import build_workflow


ROOT = Path(__file__).parents[1]
ADAPTER = ROOT / "adapters" / "kubernetes.json"
CATALOG = ROOT / "examples" / "nginx" / "nginx_config.json"


class AdapterTests(unittest.TestCase):
    def test_kubernetes_patch_builder_is_selected(self):
        builder = load_patch_builder("kubernetes")
        self.assertEqual("adapters.kubernetes_patch_builder", builder.__module__)

    def test_missing_patch_builder_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "missing adapters/does_not_exist_patch_builder.py"):
            load_patch_builder("does_not_exist")

    def test_missing_adapter_capability_is_rejected(self):
        adapter = json.loads(ADAPTER.read_text())
        del adapter["health_check"]
        with tempfile.NamedTemporaryFile("w", suffix=".json") as tmp:
            json.dump(adapter, tmp)
            tmp.flush()
            with self.assertRaisesRegex(ValueError, "health_check.check"):
                load_adapter(tmp.name)


class GenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.yaml_text = build_workflow(
            adapter_name="kubernetes",
            adapter_path=ADAPTER,
            catalog_path=CATALOG,
        ).to_yaml()
        cls.document = yaml.safe_load(cls.yaml_text)

    def test_generates_workflow_template(self):
        self.assertEqual("WorkflowTemplate", self.document["kind"])
        self.assertEqual("argo-config-framework", self.document["metadata"]["name"])

    def test_health_check_combines_enable_and_skip_conditions(self):
        expected = (
            'inputs.parameters["precheck_health_check_enabled"] == "true"'
            ') && (inputs.parameters.skip_health_check != "true"'
        )
        self.assertIn(expected, self.yaml_text)

    def test_generated_idempotency_script_accepts_parsed_json_objects(self):
        self.assertIn(
            "spec = spec_json if isinstance(spec_json, dict) else json.loads(spec_json)",
            self.yaml_text,
        )
        self.assertNotIn(
            "spec = json.loads(spec_json) if spec_json else {}",
            self.yaml_text,
        )

    def test_workflow_inputs_are_not_embedded_in_python_literals(self):
        self.assertNotIn("r'''{{inputs.parameters.", self.yaml_text)
        self.assertIn("name: CHANGES_JSON", self.yaml_text)

    def test_public_parameters_remain_compatible(self):
        names = {
            parameter["name"]
            for parameter in self.document["spec"]["arguments"]["parameters"]
        }
        self.assertTrue({
            "ticket_id", "target_id", "changes", "target", "label",
            "run_mode", "skip_change_gate", "skip_health_check",
            "notify_webhook_url",
        }.issubset(names))

    def test_base_templates_are_valid_yaml_with_concrete_retries(self):
        state_store = yaml.safe_load(
            (ROOT / "base_templates" / "state-store-v1.yaml").read_text()
        )
        templates = {
            template["name"]: template
            for template in state_store["spec"]["templates"]
        }
        self.assertEqual("1", templates["get-spec"]["retryStrategy"]["limit"])
        self.assertEqual("1", templates["wait-convergence"]["retryStrategy"]["limit"])

    def test_patch_template_uses_environment_variable_not_shell_interpolation(self):
        text = (ROOT / "base_templates" / "state-store-v1.yaml").read_text()
        self.assertIn('--patch "$PATCH_EXPRESSION"', text)
        self.assertNotIn("--patch='{{inputs.parameters.patch_expression}}'", text)

    def test_base_templates_keep_dynamic_values_out_of_script_source(self):
        ticketing = yaml.safe_load(
            (ROOT / "base_templates" / "ticketing-v1.yaml").read_text()
        )
        ticket_source = ticketing["spec"]["templates"][0]["script"]["source"]
        self.assertNotIn("{{inputs.parameters.", ticket_source)

        agent = yaml.safe_load(
            (ROOT / "base_templates" / "config-agent-v1.yaml").read_text()
        )
        for template in agent["spec"]["templates"]:
            self.assertNotIn("{{inputs.parameters.", template["script"]["source"])

    def test_example_rbac_allows_pod_watch_for_kubectl_wait(self):
        rbac = (ROOT / "examples" / "nginx" / "rbac.yaml").read_text()
        self.assertIn('verbs: ["get", "list", "watch"]', rbac)

    def test_verification_uses_resolved_state_store_reference(self):
        self.assertIn(
            "state_store_ref",
            (ROOT / "steps" / "verify_config.json").read_text(),
        )
        text = (ROOT / "base_templates" / "config-verify-v1.yaml").read_text()
        self.assertIn('CM_NAME="${STATE_STORE_REF:-${TARGET_ID}-config}"', text)

    def test_cli_exports_base_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "sys.argv",
                [
                    "argo-config-framework",
                    "--export-base-templates",
                    tmp,
                ],
            ):
                self.assertEqual(0, main())
            self.assertTrue((Path(tmp) / "state-store-v1.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
