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

from ..config import KNOWN_STEPS


def resolve_conf() -> Script:
    def _resolve() -> None:
        import json
        import os
        from pathlib import Path

        changes_json = os.environ["CHANGES_JSON"]
        target = os.environ["TARGET"]
        cluster_type = os.environ["CLUSTER_TYPE"]
        known_steps_json = os.environ["KNOWN_STEPS_JSON"]
        conf_catalog_json = os.environ["CONF_CATALOG_JSON"]
        output_path = os.environ["OUTPUT_PATH"]

        changes = changes_json if isinstance(changes_json, list) else json.loads(changes_json)
        if not changes:
            raise ValueError("changes must be a non-empty list")
        invalid_items = [
            f"changes[{i}] must be an object"
            for i, change in enumerate(changes)
            if not isinstance(change, dict)
        ]
        if invalid_items:
            raise ValueError("resolve_conf errors:\n  - " + "\n  - ".join(invalid_items))

        known_steps = set(known_steps_json if isinstance(known_steps_json, list) else json.loads(known_steps_json))

        def _load_catalog(conf: str) -> dict:
            if conf_catalog_json:
                full = conf_catalog_json if isinstance(conf_catalog_json, dict) else json.loads(conf_catalog_json)
                if conf not in full:
                    raise ValueError(
                        f"conf={conf!r} not found in catalog. "
                        f"Available: {', '.join(sorted(full.keys()))}"
                    )
                return full[conf]
            raise ValueError(f"conf={conf!r} not found: conf_catalog_json is empty.")

        def _get_target_block(catalog: dict, conf: str, resolved_target: str):
            stack_block = catalog.get(cluster_type)
            if stack_block is None:
                raise ValueError(
                    f"conf={conf!r} has no '{cluster_type}' block — "
                    f"this conf is not supported on {cluster_type} clusters."
                )
            rt = resolved_target
            if not rt:
                default_target = stack_block.get("default_target") or catalog.get("default_target")
                if not default_target:
                    available = list(stack_block.get("targets", {}).keys())
                    raise ValueError(
                        f"target is required for conf={conf} on {cluster_type} clusters "
                        f"(no default_target set). Valid targets: {', '.join(available)}"
                    )
                rt = default_target
            target_block = stack_block.get("targets", {}).get(rt)
            if target_block is None:
                available = list(stack_block.get("targets", {}).keys())
                raise ValueError(
                    f"target={rt!r} not found for conf={conf}, cluster_type={cluster_type}. "
                    f"Valid targets: {', '.join(available)}"
                )
            return rt, target_block

        def _resolve_app_block(conf: str, app: str, target_block: dict) -> dict:
            apps = target_block.get("apps")
            if apps is None:
                return {
                    "state_store_ref":  target_block.get("state_store_ref", ""),
                    "state_store_path": target_block.get("state_store_path", ""),
                    "inputs":           target_block.get("inputs", {}),
                    "guardrails":       target_block.get("guardrails", {}),
                    "precheck":         target_block.get("precheck", {}).get("steps", []),
                    "execution":        target_block.get("execution", {}).get("steps", []),
                    "postcheck":        target_block.get("postcheck", {}).get("steps", []),
                }
            if app in apps:
                ab = apps[app]
            elif "*" in apps:
                ab = apps["*"]
            else:
                available = [k for k in apps if k != "*"]
                raise ValueError(
                    f"conf={conf!r}: app={app!r} not found and no '*' fallback. "
                    f"Available apps: {available}"
                )
            return {
                "state_store_ref":  ab.get("state_store_ref", ""),
                "state_store_path": ab.get("state_store_path", ""),
                "inputs":           ab.get("inputs", {}),
                "guardrails":       ab.get("guardrails", {}),
                "precheck":         ab.get("precheck", {}).get("steps", []),
                "execution":        ab.get("execution", {}).get("steps", []),
                "postcheck":        ab.get("postcheck", {}).get("steps", []),
            }

        first_conf = changes[0].get("conf", "")
        if not first_conf:
            raise ValueError("resolve_conf errors:\n  - changes[0]: missing 'conf'")
        first_catalog = _load_catalog(first_conf)
        resolved_target, _ = _get_target_block(first_catalog, first_conf, target)

        errors = []
        resolved_changes = []

        for i, change in enumerate(changes):
            conf      = change.get("conf", "")
            app       = change.get("app", "")
            stanza    = change.get("stanza", "")
            key       = change.get("key", "")
            value     = str(change.get("value", ""))
            operation = change.get("operation", "upsert")

            change_errors = []
            for field, val in [("conf", conf), ("stanza", stanza), ("key", key)]:
                if not val:
                    change_errors.append(f"changes[{i}]: missing '{field}'")

            if change_errors:
                errors.extend(change_errors)
                continue

            try:
                catalog = _load_catalog(conf)
                _, tblock = _get_target_block(catalog, conf, resolved_target)
                if not app:
                    apps = tblock.get("apps", {})
                    app = tblock.get("default_app", "")
                    if not app:
                        explicit_apps = [name for name in apps if name != "*"]
                        if len(explicit_apps) == 1:
                            app = explicit_apps[0]
                    if not app:
                        raise ValueError(
                            f"conf={conf!r}: app is required because no unambiguous default is configured"
                        )
                ab = _resolve_app_block(conf, app, tblock)
                component_role = tblock.get("component_role", "")
            except ValueError as exc:
                errors.append(f"changes[{i}]: {exc}")
                continue

            resolved_changes.append({
                "index":            i,
                "conf":             conf,
                "app":              app,
                "stanza":           stanza,
                "key":              key,
                "value":            value,
                "operation":        operation,
                "state_store_ref":  ab["state_store_ref"],
                "state_store_path": ab["state_store_path"],
                "inputs":           ab["inputs"],
                "guardrails":       ab["guardrails"],
                "precheck":         ab["precheck"],
                "execution":        ab["execution"],
                "postcheck":        ab["postcheck"],
                "component_role":   component_role,
            })

        if errors:
            raise ValueError("resolve_conf errors:\n" + "\n".join(f"  - {e}" for e in errors))

        all_steps = []
        for rc in resolved_changes:
            all_steps += rc["precheck"] + rc["execution"] + rc["postcheck"]
        unknown = {s["name"] for s in all_steps} - known_steps
        if unknown:
            raise ValueError(
                f"Unknown step name(s): {sorted(unknown)}. Register them in steps_catalog.json first."
            )

        def _union_steps(phase: str) -> list:
            seen = set()
            result = []
            for rc in resolved_changes:
                for s in rc[phase]:
                    if s["name"] not in seen:
                        seen.add(s["name"])
                        result.append(s)
            return result

        union_precheck  = _union_steps("precheck")
        union_execution = _union_steps("execution")
        union_postcheck = _union_steps("postcheck")

        component_roles = {rc["component_role"] for rc in resolved_changes}
        if len(component_roles) > 1:
            raise ValueError(
                f"All changes must target the same component_role but got: {sorted(component_roles)}. "
                "Use separate runs for different targets."
            )
        component_role = component_roles.pop()

        distinct_confs = list(dict.fromkeys(rc["conf"] for rc in resolved_changes))
        scopes = {
            (
                rc["component_role"],
                rc["state_store_ref"],
                rc["conf"],
                rc["stanza"],
            )
            for rc in resolved_changes
        }
        if len(scopes) != 1:
            rendered_scopes = [
                {
                    "component_role": role,
                    "state_store_ref": store,
                    "conf": conf,
                    "stanza": stanza,
                }
                for role, store, conf, stanza in sorted(scopes)
            ]
            raise ValueError(
                "All changes in one run must share component_role, state_store_ref, "
                f"conf, and stanza. Got: {rendered_scopes}"
            )

        duplicate_keys = []
        seen_keys = set()
        for rc in resolved_changes:
            identity = (rc["app"], rc["conf"], rc["stanza"], rc["key"])
            if identity in seen_keys:
                duplicate_keys.append("/".join(identity))
            seen_keys.add(identity)
        if duplicate_keys:
            raise ValueError(
                f"Duplicate change key(s) in one run: {sorted(set(duplicate_keys))}"
            )

        resolved = {
            "target":         resolved_target,
            "cluster_type":   cluster_type,
            "component_role": component_role,
            "changes":        resolved_changes,
            "precheck":       union_precheck,
            "execution":      union_execution,
            "postcheck":      union_postcheck,
            "distinct_confs": distinct_confs,
        }

        first_rc = resolved_changes[0]
        out = Path(output_path).parent
        (out / "resolved_state_store_ref.txt").write_text(first_rc["state_store_ref"])
        (out / "resolved_state_store_path.txt").write_text(first_rc["state_store_path"])
        (out / "resolved_conf_name.txt").write_text(first_rc["conf"])
        (out / "resolved_stanza.txt").write_text(first_rc["stanza"])
        (out / "resolved_key.txt").write_text(first_rc["key"])
        (out / "resolved_value.txt").write_text(first_rc["value"])
        (out / "resolved_app.txt").write_text(first_rc["app"])
        (out / "resolved_operation.txt").write_text(first_rc["operation"])

        Path(output_path).write_text(json.dumps(resolved, indent=2))
        (out / "resolved_target.txt").write_text(resolved_target)
        (out / "resolved_component_role.txt").write_text(component_role)
        (out / "resolved_changes.txt").write_text(json.dumps(resolved_changes))
        (out / "resolved_distinct_confs.txt").write_text(json.dumps(distinct_confs))
        (out / "resolved_precheck_steps.txt").write_text(json.dumps(union_precheck))
        (out / "resolved_execution_steps.txt").write_text(json.dumps(union_execution))
        (out / "resolved_postcheck_steps.txt").write_text(json.dumps(union_postcheck))

        precheck_names  = {s["name"] for s in union_precheck}
        execution_names = {s["name"] for s in union_execution}
        postcheck_names = {s["name"] for s in union_postcheck}
        for step_name in known_steps:
            (out / f"precheck_{step_name}_enabled.txt").write_text(
                "true" if step_name in precheck_names else "false"
            )
            (out / f"execution_{step_name}_enabled.txt").write_text(
                "true" if step_name in execution_names else "false"
            )
            (out / f"postcheck_{step_name}_enabled.txt").write_text(
                "true" if step_name in postcheck_names else "false"
            )

        print(json.dumps(resolved))

    return Script(
        name="resolve-conf",
        source=_resolve,
        inputs=[
            Parameter(name="changes_json"),
            Parameter(name="target",            value=""),
            Parameter(name="cluster_type"),
            Parameter(name="known_steps_json",  value="[]"),
            Parameter(name="conf_catalog_json", value=""),
            Parameter(name="output_path",       value="/tmp/resolved_conf.json"),
        ],
        env=[
            Env(name="CHANGES_JSON", value="{{inputs.parameters.changes_json}}"),
            Env(name="TARGET", value="{{inputs.parameters.target}}"),
            Env(name="CLUSTER_TYPE", value="{{inputs.parameters.cluster_type}}"),
            Env(name="KNOWN_STEPS_JSON", value="{{inputs.parameters.known_steps_json}}"),
            Env(name="CONF_CATALOG_JSON", value="{{inputs.parameters.conf_catalog_json}}"),
            Env(name="OUTPUT_PATH", value="{{inputs.parameters.output_path}}"),
        ],
        outputs=[
            Parameter(name="resolved_conf",        value_from={"path": "/tmp/resolved_conf.json"}),
            Parameter(name="target",               value_from={"path": "/tmp/resolved_target.txt"}),
            Parameter(name="component_role",       value_from={"path": "/tmp/resolved_component_role.txt"}),
            Parameter(name="state_store_ref",      value_from={"path": "/tmp/resolved_state_store_ref.txt"}),
            Parameter(name="state_store_path",     value_from={"path": "/tmp/resolved_state_store_path.txt"}),
            Parameter(name="conf",                 value_from={"path": "/tmp/resolved_conf_name.txt"}),
            Parameter(name="stanza",               value_from={"path": "/tmp/resolved_stanza.txt"}),
            Parameter(name="key",                  value_from={"path": "/tmp/resolved_key.txt"}),
            Parameter(name="value",                value_from={"path": "/tmp/resolved_value.txt"}),
            Parameter(name="app",                  value_from={"path": "/tmp/resolved_app.txt"}),
            Parameter(name="operation",            value_from={"path": "/tmp/resolved_operation.txt"}),
            Parameter(name="changes",              value_from={"path": "/tmp/resolved_changes.txt"}),
            Parameter(name="distinct_confs",       value_from={"path": "/tmp/resolved_distinct_confs.txt"}),
            Parameter(name="precheck_steps",       value_from={"path": "/tmp/resolved_precheck_steps.txt"}),
            Parameter(name="execution_steps",      value_from={"path": "/tmp/resolved_execution_steps.txt"}),
            Parameter(name="postcheck_steps",      value_from={"path": "/tmp/resolved_postcheck_steps.txt"}),
            *[
                Parameter(
                    name=f"{phase}_{s}_enabled",
                    value_from={"path": f"/tmp/{phase}_{s}_enabled.txt"},
                )
                for s in sorted(KNOWN_STEPS)
                for phase in ("precheck", "execution", "postcheck")
            ],
        ],
        image="python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de",
    )
