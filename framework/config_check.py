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


def config_check_task(
    verify_results: str,
    changes_json: str,
    expect_present: str,
    name: str,
) -> Task:
    def _check() -> None:
        import json
        import os
        import sys
        from pathlib import Path

        changes_json = os.environ["CHANGES_JSON"]
        verify_results_json = os.environ["VERIFY_RESULTS_JSON"]
        expect_present = os.environ["EXPECT_PRESENT"]

        try:
            changes = changes_json if isinstance(changes_json, list) else json.loads(changes_json)
        except (json.JSONDecodeError, TypeError) as exc:
            changes = []
            input_error = f"invalid changes JSON: {exc}"
        else:
            input_error = ""
        should_be_present = str(expect_present).strip().lower() == "true"
        phase = "POSTCHECK" if should_be_present else "PRECHECK"
        out_dir = Path("/tmp")

        try:
            raw = verify_results_json if isinstance(verify_results_json, list) else json.loads(verify_results_json)
            results = raw if isinstance(raw, list) else [raw]
        except (json.JSONDecodeError, TypeError) as exc:
            results = []
            input_error = input_error or f"invalid verification JSON: {exc}"

        SEP = "-" * 60
        failures = []
        usable_results = [
            item
            for item in results
            if isinstance(item, dict)
            and isinstance(item.get("data"), dict)
            and (item["data"] or item.get("authoritative") is True)
        ]

        if input_error:
            failures.append({"reason": input_error})
        if not isinstance(changes, list) or not changes:
            failures.append({"reason": "changes must be a non-empty array"})
        elif any(not isinstance(change, dict) for change in changes):
            failures.append({"reason": "every change must be an object"})
        if not usable_results:
            failures.append({"reason": "verification returned no usable configuration results"})

        for ci, change in enumerate(changes if isinstance(changes, list) else []):
            if not isinstance(change, dict):
                continue
            key   = change.get("key", "")
            value = str(change.get("value", ""))
            operation = change.get("operation", "upsert")

            for item in usable_results:
                host = item.get("host", "<unknown>")
                data = item["data"]
                actual_val  = data.get(key)
                found       = actual_val is not None
                value_match = found and str(actual_val).strip() == value.strip()

                if should_be_present:
                    compliant = not found if operation == "remove" else value_match
                else:
                    compliant = found if operation == "remove" else not value_match

                if not compliant:
                    failures.append({
                        "change_index": ci,
                        "key": key,
                        "expected": "<absent>" if operation == "remove" and should_be_present else value,
                        "actual": actual_val,
                        "host": host,
                        "operation": operation,
                    })

        if failures:
            msg = f"{phase} FAILED: {len(failures)} check(s) failed"
            (out_dir / "config_check_result.txt").write_text("failed")
            (out_dir / "config_check_message.txt").write_text(msg)
            print(SEP)
            print(msg)
            for f in failures:
                if "reason" in f:
                    print(f"  {f['reason']}")
                    continue
                print(f"  [{f['change_index']}] host={f['host']} key={f['key']}")
                print(f"       expected={f['expected']!r} actual={f['actual']!r}")
            print(SEP)
            sys.exit(1)

        msg = (
            f"{phase} PASSED: all {len(changes)} change(s) "
            f"verified on {len(usable_results)} source(s)"
        )
        (out_dir / "config_check_result.txt").write_text("passed")
        (out_dir / "config_check_message.txt").write_text(msg)
        print(SEP)
        print(msg)
        print(SEP)

    script = Script(
        name=name,
        source=_check,
        inputs=[
            Parameter(name="changes_json",       value=changes_json),
            Parameter(name="verify_results_json", value=verify_results),
            Parameter(name="expect_present",     value=expect_present),
        ],
        env=[
            Env(name="CHANGES_JSON", value="{{inputs.parameters.changes_json}}"),
            Env(name="VERIFY_RESULTS_JSON", value="{{inputs.parameters.verify_results_json}}"),
            Env(name="EXPECT_PRESENT", value="{{inputs.parameters.expect_present}}"),
        ],
        outputs=[
            Parameter(name="result",  value_from={"path": "/tmp/config_check_result.txt"}),
            Parameter(name="message", value_from={"path": "/tmp/config_check_message.txt"}),
        ],
        image="python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de",
    )
    return Task(name=name, inline=script)
