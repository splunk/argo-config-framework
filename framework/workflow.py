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

"""Build an Argo WorkflowTemplate from an adapter and configuration catalog."""
import json
from pathlib import Path

from hera.workflows import DAG, Parameter, Task, WorkflowTemplate

from .config import (
    KNOWN_STEPS,
    load_conf_catalog,
    WORKFLOW_TIMEOUT,
)
from .dag_builder import (
    build_task,
    load_adapter,
    steps_for_phase,
    wire_phase_depends,
    wire_pipeline_depends,
)
from .scripts.resolve_conf import resolve_conf as resolve_conf_script_fn
from .scripts.enforce_inputs import enforce_inputs as enforce_inputs_script_fn
from .scripts.validate_inputs import validate_inputs as validate_inputs_script_fn
from .patch_builder import load_patch_builder

WORKFLOW_NAME = "argo-config-framework"


def _param(name: str) -> str:
    return f"{{{{inputs.parameters.{name}}}}}"


def _task_out(task_name: str, param_name: str) -> str:
    return f"{{{{tasks.{task_name}.outputs.parameters.{param_name}}}}}"


# ── WorkflowTemplate builder ──────────────────────────────────────────────────

def build_workflow(
    adapter_path: str | Path,
    catalog_path: str | Path,
    cluster_type: str = "single",
    adapter_name: str | None = None,
) -> WorkflowTemplate:

    load_adapter(adapter_path)
    conf_catalog_json = load_conf_catalog(catalog_path)
    resolved_adapter_name = adapter_name or Path(adapter_path).stem

    _PRECHECK_STEPS  = steps_for_phase("precheck")
    _EXECUTION_STEPS = steps_for_phase("execution")
    _POSTCHECK_STEPS = steps_for_phase("postcheck")

    _validate_inputs_tmpl = validate_inputs_script_fn()
    _resolve_conf_tmpl    = resolve_conf_script_fn()
    _enforce_inputs_tmpl  = enforce_inputs_script_fn()
    _build_patch_tmpl     = load_patch_builder(resolved_adapter_name)()

    with WorkflowTemplate(
        name=WORKFLOW_NAME,
        entrypoint="run",
        service_account_name="argo-config-framework",
        active_deadline_seconds=WORKFLOW_TIMEOUT,
        arguments=[
            Parameter(name="ticket_id",
                      description="Change management ticket ID (e.g. PROJ-123)"),
            Parameter(name="target_id",
                      description="The target system being changed"),
            Parameter(name="changes",
                      description=(
                          'JSON array of changes. Each: {"conf": "nginx_rate_limit", "app": "system", '
                          '"stanza": "http", "key": "rate_limit", "value": "20r/s", "operation": "upsert"}'
                      )),
            Parameter(name="target",    value="",
                      description="Target component. Auto-picked from catalog default_target when empty."),
            Parameter(name="label",     value="",
                      description="Component group label when multiple groups exist."),
            Parameter(name="run_mode",  value="full",
                      enum=["full", "only_precheck", "only_postcheck"],
                      description="full=all phases. only_precheck=stop after pre-checks. only_postcheck=skip to post-checks."),
            Parameter(name="skip_change_gate",  value="false",
                      enum=["true", "false"],
                      description="Skip change management gate check."),
            Parameter(name="skip_health_check", value="false",
                      enum=["true", "false"],
                      description="Skip health check."),
            Parameter(name="notify_webhook_url", value="",
                      description="Optional webhook URL for notifications (leave empty to disable)."),
        ],
    ) as wf:

        # ── DAG: pre-checks ───────────────────────────────────────────────────
        with DAG(
            name="pre-checks",
            inputs=[
                Parameter(name="target_id"),
                Parameter(name="ticket_id",         value=""),
                Parameter(name="component_role",    value=""),
                Parameter(name="state_store_ref",   value=""),
                Parameter(name="label",             value=""),
                Parameter(name="changes",           value="[]"),
                Parameter(name="conf",              value=""),
                Parameter(name="stanza",            value=""),
                Parameter(name="skip_change_gate",  value="false"),
                Parameter(name="skip_health_check", value="false"),
                *[Parameter(name=f"precheck_{s}_enabled", value="false") for s in _PRECHECK_STEPS],
            ],
        ) as pre_checks:
            _pre_tasks: dict[str, Task] = {}
            for _sname in _PRECHECK_STEPS:
                _t = build_task(_sname, phase="precheck")
                _pre_tasks[_t.name] = _t
            wire_phase_depends(_pre_tasks, "precheck")

        # ── DAG: execution ────────────────────────────────────────────────────
        with DAG(
            name="execution",
            inputs=[
                Parameter(name="target_id"),
                Parameter(name="component_role",      value=""),
                Parameter(name="state_store_ref",     value=""),
                Parameter(name="patch_expression",    value=""),
                Parameter(name="change_reason",       value=""),
                Parameter(name="label",               value=""),
                Parameter(name="notify_webhook_url",  value=""),
                *[Parameter(name=f"execution_{s}_enabled", value="false") for s in _EXECUTION_STEPS],
            ],
        ) as execution:
            _exec_tasks: dict[str, Task] = {}
            for _sname in _EXECUTION_STEPS:
                _t = build_task(_sname, phase="execution")
                _exec_tasks[_t.name] = _t
            wire_phase_depends(_exec_tasks, "execution")

        # ── DAG: post-checks ──────────────────────────────────────────────────
        with DAG(
            name="post-checks",
            inputs=[
                Parameter(name="target_id"),
                Parameter(name="component_role",     value=""),
                Parameter(name="state_store_ref",    value=""),
                Parameter(name="label",              value=""),
                Parameter(name="changes",            value="[]"),
                Parameter(name="conf",               value=""),
                Parameter(name="stanza",             value=""),
                Parameter(name="skip_health_check",  value="false"),
                Parameter(name="notify_webhook_url", value=""),
                *[Parameter(name=f"postcheck_{s}_enabled", value="false") for s in _POSTCHECK_STEPS],
            ],
        ) as post_checks:
            _post_tasks: dict[str, Task] = {}
            for _sname in _POSTCHECK_STEPS:
                _t = build_task(_sname, phase="postcheck")
                _post_tasks[_t.name] = _t
            wire_phase_depends(_post_tasks, "postcheck")

        # ── DAG: run (entrypoint) ─────────────────────────────────────────────
        with DAG(
            name="run",
            fail_fast=False,
            inputs=[
                Parameter(name="ticket_id"),
                Parameter(name="target_id"),
                Parameter(name="changes"),
                Parameter(name="target",             value=""),
                Parameter(name="label",              value=""),
                Parameter(name="run_mode",           value="full"),
                Parameter(name="skip_change_gate",   value="false"),
                Parameter(name="skip_health_check",  value="false"),
                Parameter(name="notify_webhook_url", value=""),
            ],
        ):

            # Step 1 — validate inputs
            validate_input = Task(
                name="validate-input",
                template=_validate_inputs_tmpl,
                arguments=[
                    Parameter(name="ticket_id", value=_param("ticket_id")),
                    Parameter(name="target_id", value=_param("target_id")),
                    Parameter(name="changes",   value=_param("changes")),
                ],
            )

            # Step 2 — resolve conf catalog entry
            resolve_conf_task = Task(
                name="resolve-conf",
                template=_resolve_conf_tmpl,
                arguments=[
                    Parameter(name="changes_json",      value=_param("changes")),
                    Parameter(name="target",            value=_param("target")),
                    Parameter(name="cluster_type",      value=cluster_type),
                    Parameter(name="known_steps_json",  value=json.dumps(sorted(KNOWN_STEPS))),
                    Parameter(name="conf_catalog_json", value=conf_catalog_json),
                ],
            )

            # Step 3 — enforce inputs (guardrails)
            enforce_inputs_task = Task(
                name="enforce-inputs",
                template=_enforce_inputs_tmpl,
                arguments=[
                    Parameter(name="changes_json",       value=_task_out("resolve-conf", "changes")),
                    Parameter(name="label",              value=_param("label")),
                    Parameter(name="resolved_conf_json", value=_task_out("resolve-conf", "resolved_conf")),
                ],
            )

            # Step 4 — build patch expression (adapter-specific)
            build_patch_task = Task(
                name="build-patch",
                template=_build_patch_tmpl,
                arguments=[
                    Parameter(name="changes_json", value=_task_out("resolve-conf", "changes")),
                    Parameter(name="ticket_id",    value=_param("ticket_id")),
                    Parameter(name="label",        value=_param("label")),
                ],
            )

            # Step 5 — pre-checks phase DAG
            _pre_checks = Task(
                name="pre-checks",
                template=pre_checks,
                arguments=[
                    Parameter(name="target_id",         value=_param("target_id")),
                    Parameter(name="ticket_id",         value=_param("ticket_id")),
                    Parameter(name="component_role",    value=_task_out("resolve-conf", "component_role")),
                    Parameter(name="state_store_ref",   value=_task_out("resolve-conf", "state_store_ref")),
                    Parameter(name="label",             value=_param("label")),
                    Parameter(name="changes",           value=_task_out("resolve-conf", "changes")),
                    Parameter(name="conf",              value=_task_out("resolve-conf", "conf")),
                    Parameter(name="stanza",            value=_task_out("resolve-conf", "stanza")),
                    Parameter(name="skip_change_gate",  value=_param("skip_change_gate")),
                    Parameter(name="skip_health_check", value=_param("skip_health_check")),
                    *[
                        Parameter(
                            name=f"precheck_{s}_enabled",
                            value=_task_out("resolve-conf", f"precheck_{s}_enabled"),
                        )
                        for s in _PRECHECK_STEPS
                    ],
                ],
                when='{{=inputs.parameters.run_mode != "only_postcheck"}}',
            )

            # Step 6 — execution phase DAG
            _execution = Task(
                name="execution",
                template=execution,
                arguments=[
                    Parameter(name="target_id",        value=_param("target_id")),
                    Parameter(name="component_role",   value=_task_out("resolve-conf", "component_role")),
                    Parameter(name="state_store_ref",  value=_task_out("resolve-conf", "state_store_ref")),
                    Parameter(name="patch_expression", value=_task_out("build-patch", "patch_expression")),
                    Parameter(name="change_reason",    value=_task_out("build-patch", "change_reason")),
                    Parameter(name="label",               value=_param("label")),
                    Parameter(name="notify_webhook_url",  value=_param("notify_webhook_url")),
                    *[
                        Parameter(
                            name=f"execution_{s}_enabled",
                            value=_task_out("resolve-conf", f"execution_{s}_enabled"),
                        )
                        for s in _EXECUTION_STEPS
                    ],
                ],
                when='{{=inputs.parameters.run_mode == "full"}}',
            )

            # Step 7 — post-checks phase DAG
            _post_checks = Task(
                name="post-checks",
                template=post_checks,
                arguments=[
                    Parameter(name="target_id",         value=_param("target_id")),
                    Parameter(name="component_role",    value=_task_out("resolve-conf", "component_role")),
                    Parameter(name="state_store_ref",   value=_task_out("resolve-conf", "state_store_ref")),
                    Parameter(name="label",             value=_param("label")),
                    Parameter(name="changes",           value=_task_out("resolve-conf", "changes")),
                    Parameter(name="conf",              value=_task_out("resolve-conf", "conf")),
                    Parameter(name="stanza",            value=_task_out("resolve-conf", "stanza")),
                    Parameter(name="skip_health_check",  value=_param("skip_health_check")),
                    Parameter(name="notify_webhook_url", value=_param("notify_webhook_url")),
                    *[
                        Parameter(
                            name=f"postcheck_{s}_enabled",
                            value=_task_out("resolve-conf", f"postcheck_{s}_enabled"),
                        )
                        for s in _POSTCHECK_STEPS
                    ],
                ],
                when='{{=inputs.parameters.run_mode != "only_precheck"}}',
            )

            # Wire run DAG depends from pipeline.json
            wire_pipeline_depends({
                "validate-input": validate_input,
                "resolve-conf":   resolve_conf_task,
                "enforce-inputs": enforce_inputs_task,
                "build-patch":    build_patch_task,
                "pre-checks":     _pre_checks,
                "execution":      _execution,
                "post-checks":    _post_checks,
            })

    return wf
