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

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from framework.config import KNOWN_STEPS
from framework.config_check import config_check_task
from framework.idempotency_check import idempotency_check_task
from framework.scripts.enforce_inputs import enforce_inputs
from framework.scripts.resolve_conf import resolve_conf
from framework.scripts.validate_inputs import validate_inputs
from adapters.kubernetes_patch_builder import build_patch_task


ROOT = Path(__file__).parents[1]
CATALOG = json.loads((ROOT / "examples" / "nginx" / "nginx_config.json").read_text())


def run_source(source, **environment):
    with patch.dict("os.environ", environment, clear=False):
        with redirect_stdout(io.StringIO()):
            return source()


def change(**overrides):
    value = {
        "conf": "nginx_rate_limit",
        "app": "system",
        "stanza": "http",
        "key": "rate_limit",
        "value": "20r/s",
        "operation": "upsert",
    }
    value.update(overrides)
    return value


class InputValidationTests(unittest.TestCase):
    def test_non_object_change_is_rejected_cleanly(self):
        source = validate_inputs().source
        with self.assertRaises(SystemExit):
            run_source(
                source,
                TICKET_ID="NGINX-123",
                TARGET_ID="nginx",
                CHANGES=json.dumps(["not-an-object"]),
            )

    def test_valid_change_passes(self):
        run_source(
            validate_inputs().source,
            TICKET_ID="NGINX-123",
            TARGET_ID="nginx",
            CHANGES=json.dumps([change()]),
        )


class ResolveConfTests(unittest.TestCase):
    def run_resolve(self, changes):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "resolved.json"
            run_source(
                resolve_conf().source,
                CHANGES_JSON=json.dumps(changes),
                TARGET="",
                CLUSTER_TYPE="single",
                KNOWN_STEPS_JSON=json.dumps(sorted(KNOWN_STEPS)),
                CONF_CATALOG_JSON=json.dumps(CATALOG),
                OUTPUT_PATH=str(output),
            )
            return json.loads(output.read_text())

    def test_same_scope_multi_key_batch_is_supported(self):
        resolved = self.run_resolve(
            [change(), change(key="timeout", value="90")]
        )
        self.assertEqual(2, len(resolved["changes"]))
        self.assertEqual("nginx", resolved["target"])

    def test_missing_app_uses_unambiguous_catalog_app(self):
        resolved = self.run_resolve([change(app="")])
        self.assertEqual("system", resolved["changes"][0]["app"])

    def test_cross_stanza_batch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must share"):
            self.run_resolve([change(), change(stanza="server", key="timeout")])

    def test_duplicate_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate change key"):
            self.run_resolve([change(), change(value="30r/s")])

    def test_non_object_change_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be an object"):
            self.run_resolve([change(), "bad"])


class ConfigCheckTests(unittest.TestCase):
    def source(self, expect_present="true"):
        return config_check_task(
            verify_results="[]",
            changes_json="[]",
            expect_present=expect_present,
            name="test-config-check",
        ).inline.source

    def test_postcheck_upsert_passes_with_authoritative_result(self):
        run_source(
            self.source(),
            CHANGES_JSON=json.dumps([change()]),
            VERIFY_RESULTS_JSON=json.dumps([{
                "host": "configmap/nginx-config",
                "data": {"rate_limit": "20r/s"},
                "authoritative": True,
            }]),
            EXPECT_PRESENT="true",
        )

    def test_postcheck_remove_passes_when_key_is_absent(self):
        run_source(
            self.source(),
            CHANGES_JSON=json.dumps([change(operation="remove", value="")]),
            VERIFY_RESULTS_JSON=json.dumps([{
                "host": "configmap/nginx-config",
                "data": {},
                "authoritative": True,
            }]),
            EXPECT_PRESENT="true",
        )

    def test_precheck_remove_fails_when_key_is_already_absent(self):
        with self.assertRaises(SystemExit):
            run_source(
                self.source(expect_present="false"),
                CHANGES_JSON=json.dumps([change(operation="remove", value="")]),
                VERIFY_RESULTS_JSON=json.dumps([{
                    "host": "configmap/nginx-config",
                    "data": {},
                    "authoritative": True,
                }]),
                EXPECT_PRESENT="false",
            )

    def test_empty_verification_fails_closed(self):
        with self.assertRaises(SystemExit):
            run_source(
                self.source(),
                CHANGES_JSON=json.dumps([change()]),
                VERIFY_RESULTS_JSON="[]",
                EXPECT_PRESENT="true",
            )

    def test_wrong_postcheck_value_fails(self):
        with self.assertRaises(SystemExit):
            run_source(
                self.source(),
                CHANGES_JSON=json.dumps([change()]),
                VERIFY_RESULTS_JSON=json.dumps([{
                    "host": "configmap/nginx-config",
                    "data": {"rate_limit": "10r/s"},
                    "authoritative": True,
                }]),
                EXPECT_PRESENT="true",
            )

    def test_malformed_verification_fails_closed(self):
        with self.assertRaises(SystemExit):
            run_source(
                self.source(),
                CHANGES_JSON=json.dumps([change()]),
                VERIFY_RESULTS_JSON="{bad-json",
                EXPECT_PRESENT="true",
            )


class GuardrailTests(unittest.TestCase):
    def resolved_change(self, **overrides):
        app = CATALOG["nginx_rate_limit"]["single"]["targets"]["nginx"]["apps"]["system"]
        resolved = change()
        resolved.update({
            "inputs": app["inputs"],
            "guardrails": app["guardrails"],
            "state_store_ref": app["state_store_ref"],
        })
        resolved.update(overrides)
        return resolved

    def test_forbidden_key_is_rejected(self):
        changes = [self.resolved_change(key="ssl_certificate_key")]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                run_source(
                    enforce_inputs().source,
                    CHANGES_JSON=json.dumps(changes),
                    LABEL="",
                    RESOLVED_CONF_JSON=json.dumps({
                        "target": "nginx",
                        "component_role": "nginx",
                    }),
                    OUTPUT_PATH=str(Path(tmp) / "result.txt"),
                )

    def test_allowed_change_is_accepted(self):
        changes = [self.resolved_change()]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "result.txt"
            run_source(
                enforce_inputs().source,
                CHANGES_JSON=json.dumps(changes),
                LABEL="",
                RESOLVED_CONF_JSON=json.dumps({
                    "target": "nginx",
                    "component_role": "nginx",
                }),
                OUTPUT_PATH=str(output),
            )
            self.assertEqual("ok", output.read_text())


class PatchBuilderTests(unittest.TestCase):
    def test_shell_sensitive_value_is_encoded_as_json_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "result.json"
            run_source(
                build_patch_task().source,
                CHANGES_JSON=json.dumps([change(value="O'Reilly; $(not-a-command) '''")]),
                TICKET_ID="NGINX-123",
                LABEL="",
                OUTPUT_PATH=str(output),
            )
            result = json.loads(output.read_text())
            patch = json.loads(result["patch_expression"])
            self.assertEqual(
                "O'Reilly; $(not-a-command) '''",
                patch["data"]["rate_limit"],
            )


class IdempotencyTests(unittest.TestCase):
    def source(self):
        return idempotency_check_task("[]", "{}").inline.source

    def test_parsed_spec_object_blocks_already_applied_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                run_source(
                    self.source(),
                    CHANGES_JSON=json.dumps([change()]),
                    SPEC_JSON=json.dumps({"data": {"rate_limit": "20r/s"}}),
                    OUTPUT_PATH=str(Path(tmp) / "result.txt"),
                )

    def test_malformed_spec_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "not valid JSON"):
                run_source(
                    self.source(),
                    CHANGES_JSON=json.dumps([change()]),
                    SPEC_JSON="{bad-json",
                    OUTPUT_PATH=str(Path(tmp) / "result.txt"),
                )


if __name__ == "__main__":
    unittest.main()
