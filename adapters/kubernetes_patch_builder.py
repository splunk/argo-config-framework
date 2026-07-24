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

"""
Patch builder for the kubernetes adapter.

Generates a kubectl-compatible JSON patch expression for a ConfigMap
from the resolved changes array [{conf, app, stanza, key, value, operation}].
"""
from hera.workflows import Env, Parameter, Script


def build_patch_task() -> Script:
    def _build() -> None:
        import json
        import os
        from pathlib import Path

        changes_json = os.environ["CHANGES_JSON"]
        ticket_id = os.environ["TICKET_ID"]
        label = os.environ["LABEL"]
        output_path = os.environ["OUTPUT_PATH"]

        changes = changes_json if isinstance(changes_json, list) else json.loads(changes_json)

        patch_data = {}
        for change in changes:
            key       = change["key"]
            value     = str(change["value"])
            operation = change.get("operation", "upsert")
            if operation == "remove":
                patch_data[key] = None
            else:
                patch_data[key] = value

        patch_expression = json.dumps({"data": patch_data})
        reason = f"ticket={ticket_id}"
        if label:
            reason += f" label={label}"

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path("/tmp/patch_expression.txt").write_text(patch_expression)
        Path("/tmp/change_reason.txt").write_text(reason)
        Path(output_path).write_text(json.dumps({
            "patch_expression": patch_expression,
            "change_reason":    reason,
        }))
        print(json.dumps({"patch_expression": patch_expression, "reason": reason}))

    return Script(
        name="build-patch",
        source=_build,
        inputs=[
            Parameter(name="changes_json"),
            Parameter(name="ticket_id"),
            Parameter(name="label",       value=""),
            Parameter(name="output_path", value="/tmp/patch_result.json"),
        ],
        env=[
            Env(name="CHANGES_JSON", value="{{inputs.parameters.changes_json}}"),
            Env(name="TICKET_ID", value="{{inputs.parameters.ticket_id}}"),
            Env(name="LABEL", value="{{inputs.parameters.label}}"),
            Env(name="OUTPUT_PATH", value="{{inputs.parameters.output_path}}"),
        ],
        outputs=[
            Parameter(name="patch_expression", value_from={"path": "/tmp/patch_expression.txt"}),
            Parameter(name="change_reason",    value_from={"path": "/tmp/change_reason.txt"}),
        ],
        image="python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de",
    )
