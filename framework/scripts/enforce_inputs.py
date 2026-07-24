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


def enforce_inputs() -> Script:
    """Validate operator-provided inputs against the inputs/guardrails block from the conf catalog."""

    def _enforce() -> None:
        import json
        import os
        from pathlib import Path

        changes_json = os.environ["CHANGES_JSON"]
        label = os.environ["LABEL"]
        resolved_conf_json = os.environ["RESOLVED_CONF_JSON"]
        output_path = os.environ["OUTPUT_PATH"]

        resolved = resolved_conf_json if isinstance(resolved_conf_json, dict) else json.loads(resolved_conf_json)
        changes = changes_json if isinstance(changes_json, list) else json.loads(changes_json)

        errors = []

        for i, change in enumerate(changes):
            conf      = change.get("conf", "")
            app       = change.get("app", "")
            stanza    = change.get("stanza", "")
            key       = change.get("key", "")
            value     = change.get("value", "")
            operation = change.get("operation", "upsert")
            guardrails   = change.get("guardrails", {})
            inputs_rules = change.get("inputs", {})

            prefix = f"changes[{i}] ({conf}/{app})"

            provided_values = {
                "app": app, "conf": conf,
                "stanza": stanza, "key": key, "value": value,
                "label": label,
            }

            for field, rule in inputs_rules.items():
                if not isinstance(rule, dict) or field.startswith("_"):
                    continue
                provided = provided_values.get(field, "")
                overridable = rule.get("overridable")

                if overridable is False:
                    fixed_val = rule.get("default", "")
                    if provided and provided != str(fixed_val):
                        errors.append(
                            f"{prefix}: field '{field}' is set to '{fixed_val}' and cannot be overridden. Got: '{provided}'"
                        )
                    provided_values[field] = str(fixed_val) if fixed_val is not None else ""
                else:
                    if not provided and "default" in rule:
                        provided_values[field] = str(rule["default"]) if rule["default"] is not None else ""
                        provided = provided_values[field]
                    if rule.get("required") and not provided:
                        errors.append(f"{prefix}: field '{field}' is required but was not provided.")

            app  = provided_values.get("app",  app)
            conf = provided_values.get("conf", conf)

            def _forbidden(val, lst, lbl):
                if lst is not None and val and val in lst:
                    errors.append(f"{prefix}: {lbl}='{val}' is forbidden for conf={conf}: {lst}")

            def _allowed(val, lst, lbl):
                if lst is not None and val and val not in lst:
                    errors.append(f"{prefix}: {lbl}='{val}' is not in the allowed list for conf={conf}: {lst}")

            _allowed( app,       guardrails.get("allowed_apps"),        "app")
            _forbidden(app,      guardrails.get("forbidden_apps"),       "app")
            _allowed( conf,      guardrails.get("allowed_confs"),        "conf")
            _forbidden(conf,     guardrails.get("forbidden_confs"),      "conf")
            _forbidden(operation,guardrails.get("forbidden_operations"), "operation")
            _allowed(  operation,guardrails.get("allowed_operations"),   "operation")
            _forbidden(stanza,   guardrails.get("forbidden_stanzas"),    "stanza")
            _allowed(  stanza,   guardrails.get("allowed_stanzas"),      "stanza")
            _forbidden(key,      guardrails.get("forbidden_keys"),       "key")
            _allowed(  key,      guardrails.get("allowed_keys"),         "key")

        if errors:
            raise SystemExit(
                "INPUT VALIDATION FAILED:\n" + "\n".join(f"  - {e}" for e in errors)
            )

        out_dir = Path(output_path).parent
        Path(output_path).write_text("ok")
        (out_dir / "enforce_summary.txt").write_text(json.dumps({
            "target":         resolved.get("target", ""),
            "component_role": resolved.get("component_role", ""),
            "label":          label,
            "changes":        len(changes),
        }, indent=2))

        print(json.dumps({"result": "ok", "changes_validated": len(changes)}))

    return Script(
        name="enforce-inputs",
        source=_enforce,
        inputs=[
            Parameter(name="changes_json"),
            Parameter(name="label",              value=""),
            Parameter(name="resolved_conf_json"),
            Parameter(name="output_path",        value="/tmp/enforce_inputs_result.txt"),
        ],
        env=[
            Env(name="CHANGES_JSON", value="{{inputs.parameters.changes_json}}"),
            Env(name="LABEL", value="{{inputs.parameters.label}}"),
            Env(name="RESOLVED_CONF_JSON", value="{{inputs.parameters.resolved_conf_json}}"),
            Env(name="OUTPUT_PATH", value="{{inputs.parameters.output_path}}"),
        ],
        outputs=[
            Parameter(name="result",  value_from={"path": "/tmp/enforce_inputs_result.txt"}),
            Parameter(name="summary", value_from={"path": "/tmp/enforce_summary.txt"}),
        ],
        image="python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de",
    )
