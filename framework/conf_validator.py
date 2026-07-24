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

"""Validate all catalog JSON files at generate time.

Raises ValueError listing ALL errors found — fails the build fast.
"""
import json
from pathlib import Path

_GUARDRAIL_PAIRS = [
    ("allowed_apps",        "forbidden_apps"),
    ("allowed_confs",       "forbidden_confs"),
    ("allowed_stanzas",     "forbidden_stanzas"),
    ("allowed_keys",        "forbidden_keys"),
    ("allowed_operations",  "forbidden_operations"),
]


def _e(path: str, msg: str) -> str:
    return f"  [{path}] {msg}"


def _validate_guardrails(guardrails: dict, path: str) -> list:
    errors = []
    if not isinstance(guardrails, dict):
        return [_e(path, "guardrails must be a dict")]
    for allowed_key, forbidden_key in _GUARDRAIL_PAIRS:
        if allowed_key not in guardrails:
            errors.append(_e(path, f"guardrails missing key: '{allowed_key}'"))
        if forbidden_key not in guardrails:
            errors.append(_e(path, f"guardrails missing key: '{forbidden_key}'"))
    for key, val in guardrails.items():
        if (key.startswith("allowed_") or key.startswith("forbidden_")) and \
                val is not None and not isinstance(val, list):
            errors.append(_e(path, f"guardrails.{key} must be null or a list, got: {type(val).__name__}"))
    return errors


def _validate_inputs(inputs: dict, path: str) -> list:
    errors = []
    if not isinstance(inputs, dict):
        return [_e(path, "inputs must be a dict")]
    if not inputs:
        errors.append(_e(path, "inputs must not be empty"))
        return errors
    for field, rule in inputs.items():
        if field.startswith("_"):
            continue
        if not isinstance(rule, dict):
            errors.append(_e(f"{path}.inputs.{field}", "must be a dict"))
            continue
        overridable = rule.get("overridable")
        if overridable is None and "required" not in rule:
            errors.append(_e(f"{path}.inputs.{field}", "missing 'required' key"))
        if overridable is False and "default" not in rule:
            errors.append(_e(f"{path}.inputs.{field}", "overridable: false requires a 'default' value"))
    return errors


def _validate_steps(
    steps: list,
    phase: str,
    path: str,
    step_phases: dict[str, frozenset[str]],
) -> list:
    errors = []
    if not isinstance(steps, list):
        return [_e(path, f"{phase}.steps must be a list")]
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(_e(path, f"{phase}.steps[{i}] must be a dict"))
            continue
        if "name" not in step:
            errors.append(_e(path, f"{phase}.steps[{i}] missing 'name'"))
            continue
        step_name = step["name"]
        if step_name not in step_phases:
            errors.append(_e(path, f"{phase}.steps[{i}] name='{step['name']}' not in steps_catalog.json"))
        elif phase not in step_phases[step_name]:
            errors.append(
                _e(
                    path,
                    f"{phase}.steps[{i}] name='{step_name}' is not valid in phase "
                    f"'{phase}'; allowed phases: {sorted(step_phases[step_name])}",
                )
            )
    return errors


def _validate_app_block(
    app_name: str,
    ab: dict,
    path: str,
    step_phases: dict[str, frozenset[str]],
) -> list:
    errors = []
    if not isinstance(ab, dict):
        return [_e(path, "must be a dict")]
    if not isinstance(ab.get("state_store_ref"), str) or not ab["state_store_ref"].strip():
        errors.append(_e(path, "missing required key: 'state_store_ref'"))
    if not isinstance(ab.get("state_store_path"), str) or not ab["state_store_path"].strip():
        errors.append(_e(path, "missing required key: 'state_store_path'"))
    if "inputs" not in ab:
        errors.append(_e(path, "missing required key: 'inputs'"))
    else:
        errors += _validate_inputs(ab["inputs"], path)
    if "guardrails" not in ab:
        errors.append(_e(path, "missing required key: 'guardrails'"))
    else:
        errors += _validate_guardrails(ab["guardrails"], f"{path}.guardrails")
    for phase in ("precheck", "execution", "postcheck"):
        if phase not in ab:
            errors.append(_e(path, f"missing required key: '{phase}'"))
        else:
            pb = ab[phase]
            if not isinstance(pb, dict) or "steps" not in pb:
                errors.append(_e(path, f"'{phase}' must be a dict with a 'steps' key"))
            else:
                errors += _validate_steps(pb["steps"], phase, path, step_phases)
    return errors


def _validate_target(
    target_name: str,
    target: dict,
    path: str,
    step_phases: dict[str, frozenset[str]],
) -> list:
    errors = []
    if not isinstance(target.get("component_role"), str) or not target["component_role"].strip():
        errors.append(_e(path, "missing required key: 'component_role'"))
    if "apps" in target:
        apps = target["apps"]
        if not isinstance(apps, dict) or not apps:
            errors.append(_e(path, "'apps' must be a non-empty dict"))
        else:
            for app_name, app_block in apps.items():
                errors += _validate_app_block(
                    app_name,
                    app_block,
                    f"{path}.apps.{app_name}",
                    step_phases,
                )
    else:
        for req in ("state_store_ref", "state_store_path", "inputs", "guardrails",
                    "precheck", "execution", "postcheck"):
            if req not in target:
                errors.append(_e(path, f"missing required key: '{req}'"))
        if "guardrails" in target:
            errors += _validate_guardrails(target["guardrails"], f"{path}.guardrails")
        if "inputs" in target:
            errors += _validate_inputs(target["inputs"], path)
        for phase in ("precheck", "execution", "postcheck"):
            if phase in target:
                pb = target[phase]
                if not isinstance(pb, dict) or "steps" not in pb:
                    errors.append(_e(path, f"'{phase}' must be a dict with a 'steps' key"))
                else:
                    errors += _validate_steps(pb["steps"], phase, path, step_phases)
    return errors


def _validate_cluster_block(
    cluster_type: str,
    block: dict,
    path: str,
    step_phases: dict[str, frozenset[str]],
) -> list:
    errors = []
    if "targets" not in block:
        return [_e(path, "missing required key: 'targets'")]
    targets = block["targets"]
    if not isinstance(targets, dict) or not targets:
        return [_e(path, "'targets' must be a non-empty dict")]
    default_target = block.get("default_target")
    if default_target is not None and default_target not in targets:
        errors.append(_e(path, f"'default_target'='{default_target}' not in targets: {list(targets.keys())}"))
    for target_name, target_block in targets.items():
        if not isinstance(target_block, dict):
            errors.append(_e(f"{path}.targets.{target_name}", "must be a dict"))
            continue
        errors += _validate_target(
            target_name,
            target_block,
            f"{path}.targets.{target_name}",
            step_phases,
        )
    return errors


def validate_conf_file(
    conf_name: str,
    catalog: dict,
    step_phases: dict[str, frozenset[str]],
) -> list:
    errors = []
    path = f"catalog/{conf_name}.json"
    if not isinstance(catalog, dict):
        return [_e(path, "conf definition must be a dict")]
    metadata_keys = {"common", "description", "default_target", "inputs", "guardrails"}
    cluster_keys = [
        k for k in catalog
        if not k.startswith("_") and k not in metadata_keys
    ]
    if not cluster_keys:
        errors.append(_e(path, "must have at least one cluster_type block"))
        return errors
    for cluster_type in cluster_keys:
        block = catalog[cluster_type]
        if not isinstance(block, dict):
            errors.append(_e(f"{path}.{cluster_type}", "must be a dict"))
            continue
        errors += _validate_cluster_block(
            cluster_type,
            block,
            f"{path}.{cluster_type}",
            step_phases,
        )
    return errors


def validate_catalog(
    catalog: dict,
    step_phases: dict[str, frozenset[str]],
) -> None:
    if not isinstance(catalog, dict) or not catalog:
        raise ValueError("Catalog validation failed:\n  [catalog] must be a non-empty object")

    all_errors: list = []
    for conf_name, conf_definition in sorted(catalog.items()):
        if conf_name.startswith("_"):
            continue
        all_errors += validate_conf_file(conf_name, conf_definition, step_phases)

    if all_errors:
        raise ValueError("Catalog validation failed:\n" + "\n".join(all_errors))


def validate_all_confs(
    confs_dir: Path,
    step_phases: dict[str, frozenset[str]],
) -> None:
    catalog = {}
    errors = []
    for conf_path in sorted(confs_dir.glob("*.json")):
        if conf_path.stem == "template":
            continue
        try:
            catalog[conf_path.stem] = json.loads(conf_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"  [{conf_path.name}] invalid JSON: {exc}")
    if errors:
        raise ValueError("Catalog validation failed:\n" + "\n".join(errors))
    validate_catalog(catalog, step_phases)
