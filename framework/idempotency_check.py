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

from hera.workflows import Env, Parameter, Script, Task


def idempotency_check_task(changes_json: str, spec_json: str) -> Task:
    def _check() -> None:
        import json
        import os
        import sys
        from pathlib import Path

        changes_json = os.environ["CHANGES_JSON"]
        spec_json = os.environ["SPEC_JSON"]
        output_path = os.environ["OUTPUT_PATH"]

        changes = changes_json if isinstance(changes_json, list) else json.loads(changes_json)
        if not isinstance(changes, list) or not changes:
            raise ValueError("changes_json must be a non-empty array")
        if any(not isinstance(change, dict) for change in changes):
            raise ValueError("every change must be an object")

        try:
            spec = spec_json if isinstance(spec_json, dict) else json.loads(spec_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"spec_json is not valid JSON: {exc}") from exc
        if not isinstance(spec, dict):
            raise ValueError("spec_json must be a JSON object")
        data = spec.get("data", {})
        if not isinstance(data, dict):
            raise ValueError("spec_json.data must be a JSON object")

        out_dir = Path(output_path).parent
        check_details = []
        blocks = []

        for i, change in enumerate(changes):
            key       = change.get("key", "")
            value_str = str(change.get("value", ""))
            operation = change.get("operation", "upsert")

            current_val = data.get(key)
            key_present = current_val is not None
            value_match = key_present and str(current_val).strip() == value_str.strip()

            detail = {
                "index": i, "key": key,
                "requested_value": value_str,
                "current_value":   str(current_val) if current_val is not None else None,
                "operation":       operation,
            }
            check_details.append(detail)

            if operation in ("upsert", "update") and value_match:
                blocks.append({
                    "index": i,
                    "reason": (
                        f"IDEMPOTENCY BLOCK: key={key!r} is already set to {value_str!r}. "
                        "No change needed."
                    ),
                    "detail": detail,
                })
            elif operation == "remove" and not key_present:
                blocks.append({
                    "index": i,
                    "reason": (
                        f"IDEMPOTENCY BLOCK: key={key!r} not found in spec. Nothing to remove."
                    ),
                    "detail": detail,
                })

        if blocks:
            msg = (
                f"IDEMPOTENCY BLOCK: {len(blocks)}/{len(changes)} change(s) already applied:\n"
                + "\n".join(f"  [{b['index']}] {b['reason']}" for b in blocks)
            )
            Path(output_path).write_text("blocked")
            (out_dir / "idempotency_message.txt").write_text(msg)
            (out_dir / "idempotency_detail.txt").write_text(json.dumps({"blocked": blocks, "all_checks": check_details}))
            print(msg)
            sys.exit(1)

        msg = f"PROCEED: all {len(changes)} change(s) are safe to apply."
        Path(output_path).write_text("proceed")
        (out_dir / "idempotency_message.txt").write_text(msg)
        (out_dir / "idempotency_detail.txt").write_text(json.dumps({"all_checks": check_details}))
        print(msg)

    script = Script(
        name="check-idempotency",
        source=_check,
        inputs=[
            Parameter(name="changes_json", value=changes_json),
            Parameter(name="spec_json",    value=spec_json),
            Parameter(name="output_path",  value="/tmp/idempotency_result.txt"),
        ],
        env=[
            Env(name="CHANGES_JSON", value="{{inputs.parameters.changes_json}}"),
            Env(name="SPEC_JSON", value="{{inputs.parameters.spec_json}}"),
            Env(name="OUTPUT_PATH", value="{{inputs.parameters.output_path}}"),
        ],
        outputs=[
            Parameter(name="result",  value_from={"path": "/tmp/idempotency_result.txt"}),
            Parameter(name="message", value_from={"path": "/tmp/idempotency_message.txt"}),
            Parameter(name="detail",  value_from={"path": "/tmp/idempotency_detail.txt"}),
        ],
        image="python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de",
    )
    return Task(name="check-idempotency", inline=script)
