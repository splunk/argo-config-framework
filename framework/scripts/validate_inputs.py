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

from hera.workflows import Env, Parameter, Script


def validate_inputs() -> Script:
    def _validate() -> None:
        import json
        import os
        import re
        import sys

        ticket_id = os.environ["TICKET_ID"]
        target_id = os.environ["TARGET_ID"]
        changes = os.environ["CHANGES"]

        TICKET_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_.\-]*"
        TARGET_ID_PATTERN = r"[a-z0-9][a-z0-9\-]*"
        OPERATION_PATTERN = r"(upsert|remove)"

        errors = []
        if not re.fullmatch(TICKET_ID_PATTERN, ticket_id):
            errors.append(f"ticket_id={ticket_id!r} does not match pattern {TICKET_ID_PATTERN!r}")
        if not re.fullmatch(TARGET_ID_PATTERN, target_id):
            errors.append(f"target_id={target_id!r} does not match pattern {TARGET_ID_PATTERN!r}")
        try:
            parsed = changes if isinstance(changes, list) else json.loads(changes)
            if not isinstance(parsed, list) or not parsed:
                errors.append("changes must be a non-empty JSON array")
            else:
                for i, c in enumerate(parsed):
                    if not isinstance(c, dict):
                        errors.append(f"changes[{i}] must be a JSON object")
                        continue
                    op = c.get("operation", "upsert")
                    if not isinstance(op, str) or not re.fullmatch(OPERATION_PATTERN, op):
                        errors.append(f"changes[{i}].operation={op!r} is invalid")
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append(f"changes is not valid JSON: {exc}")

        if errors:
            print("VALIDATION FAILED:\n" + "\n".join(f"  - {e}" for e in errors))
            sys.exit(1)
        print("ok")

    return Script(
        name="validate-inputs",
        image="python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de",
        source=_validate,
        inputs=[
            Parameter(name="ticket_id"),
            Parameter(name="target_id"),
            Parameter(name="changes"),
        ],
        env=[
            Env(name="TICKET_ID", value="{{inputs.parameters.ticket_id}}"),
            Env(name="TARGET_ID", value="{{inputs.parameters.target_id}}"),
            Env(name="CHANGES", value="{{inputs.parameters.changes}}"),
        ],
    )
