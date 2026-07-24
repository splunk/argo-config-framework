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
Build Hera DAG tasks from steps/ JSON definitions.

Each step JSON has:
  base_template  : adapter namespace ("state_store", "config_agent", "health_check",
                   "config_verify", "alerting", "ticket_check", "builtin")
  call           : function name within that namespace
  inputs         : dict of param name -> Argo expression string
  when_flag      : name of a DAG input boolean parameter (task skips when "false")
  when           : raw Argo when expression (overrides when_flag)

DAG wiring is read exclusively from wiring.json — not from step JSONs.
"""
import json
from pathlib import Path

from hera.workflows import Parameter, Task
from hera.workflows import models as m

from .resources import data_path

_STEPS_DIR = data_path("steps")
_WIRING = json.loads(data_path("wiring.json").read_text(encoding="utf-8"))
_PIPELINE = json.loads(data_path("pipeline.json").read_text(encoding="utf-8"))

# loaded once per generate run via load_adapter()
_ADAPTER: dict = {}


def load_adapter(adapter_path: str | Path) -> None:
    global _ADAPTER
    adapter = json.loads(Path(adapter_path).read_text(encoding="utf-8"))
    if not isinstance(adapter, dict):
        raise ValueError("Adapter JSON must be an object")

    errors = []
    step_names = {
        name
        for phase in ("precheck", "execution", "postcheck")
        for name in steps_for_phase(phase)
    }
    for step_name in sorted(step_names):
        step = load_step(step_name)
        if step["base_template"] == "builtin":
            continue
        entry = adapter.get(step["base_template"], {}).get(step["call"])
        if not isinstance(entry, dict):
            errors.append(
                f"{step_name}: missing {step['base_template']}.{step['call']}"
            )
        elif not all(
            isinstance(entry.get(key), str) and entry[key]
            for key in ("template_name", "template")
        ):
            errors.append(
                f"{step_name}: {step['base_template']}.{step['call']} requires "
                "non-empty template_name and template"
            )
    if errors:
        raise ValueError("Invalid adapter:\n  - " + "\n  - ".join(errors))
    _ADAPTER = adapter


# ── helpers ───────────────────────────────────────────────────────────────────
def _expression_body(expression: str) -> str:
    expression = expression.strip()
    if expression.startswith("{{=") and expression.endswith("}}"):
        return expression[3:-2].strip()
    return expression


def _when(step: dict) -> str | None:
    expressions = []
    if "when" in step:
        expressions.append(_expression_body(step["when"]))
    elif flag := step.get("when_flag"):
        expressions.append(f'inputs.parameters["{flag}"] == "true"')
    expressions.extend(
        _expression_body(expression)
        for expression in step.get("when_all", [])
    )
    if not expressions:
        return None
    body = " && ".join(f"({expression})" for expression in expressions)
    return f"{{{{={body}}}}}"


def _template_ref(base_template: str, call: str) -> m.TemplateRef:
    entry = _ADAPTER.get(base_template, {}).get(call)
    if entry is None:
        raise NotImplementedError(
            f"Adapter has no entry for base_template={base_template!r} call={call!r}. "
            f"Add it to your adapter JSON."
        )
    return m.TemplateRef(name=entry["template_name"], template=entry["template"])


def _sso(argo_name: str) -> str:
    return f"({argo_name}.Succeeded || {argo_name}.Skipped || {argo_name}.Omitted)"


# ── adapter-dispatch task builder ─────────────────────────────────────────────

def _build_adapter_task(step: dict) -> Task:
    """Generic builder for any step dispatched through the adapter JSON."""
    inp = step.get("inputs", {})
    params = [Parameter(name=k, value=v) for k, v in inp.items()]
    task = Task(
        name=step["argo_task_name"],
        template_ref=_template_ref(step["base_template"], step["call"]),
        arguments=params,
    )
    w = _when(step)
    if w:
        task.when = w
    return task


# ── builtin task builders ──────────────────────────────────────────────────────
# Builtins run inline Python scripts — no adapter templateRef needed.

def _build_builtin_idempotency_check(step: dict) -> Task:
    from .idempotency_check import idempotency_check_task
    inp = step["inputs"]
    task = idempotency_check_task(
        changes_json=inp["changes_json"],
        spec_json=inp.get("spec_json", "{}"),
    )
    w = _when(step)
    if w:
        task.when = w
    return task


def _build_builtin_config_check(step: dict) -> Task:
    from .config_check import config_check_task
    inp = step["inputs"]
    task = config_check_task(
        verify_results=inp["verify_results"],
        changes_json=inp["changes_json"],
        expect_present=inp["expect_present"],
        name=step["argo_task_name"],
    )
    w = _when(step)
    if w:
        task.when = w
    return task


_BUILTIN_BUILDERS = {
    "idempotency_check": _build_builtin_idempotency_check,
    "config_check":      _build_builtin_config_check,
}


# ── public step loader ────────────────────────────────────────────────────────

def load_step(name: str) -> dict:
    return json.loads((_STEPS_DIR / f"{name}.json").read_text(encoding="utf-8"))


def steps_for_phase(phase: str) -> list[str]:
    return [n for n in _WIRING.get(phase, {}) if not n.startswith("_")]


def _resolve_argo_task_name(step_name: str, phase: str) -> str:
    step = load_step(step_name)
    by_phase = step.get("argo_task_names_by_phase", {})
    return by_phase.get(phase, step["argo_task_name"])


# ── main build entry point ────────────────────────────────────────────────────

def build_task(step_name: str, phase: str | None = None) -> Task:
    step = load_step(step_name)
    if phase:
        step = dict(step)
        step["when_flag"] = f"{phase}_{step_name}_enabled"
        by_phase = step.get("argo_task_names_by_phase", {})
        if phase in by_phase:
            step["argo_task_name"] = by_phase[phase]

    base = step["base_template"]
    call = step["call"]

    if base == "builtin":
        builder = _BUILTIN_BUILDERS.get(call)
        if builder is None:
            raise NotImplementedError(
                f"No builtin builder for call={call!r} (step={step_name!r})."
            )
        task = builder(step)
    else:
        task = _build_adapter_task(step)

    return task


# ── wiring helpers ────────────────────────────────────────────────────────────

def wire_phase_depends(tasks: dict[str, Task], phase: str) -> None:
    phase_wiring = _WIRING.get(phase, {})
    for step_name, deps in phase_wiring.items():
        if step_name.startswith("_") or not deps:
            continue
        argo_name = _resolve_argo_task_name(step_name, phase)
        task = tasks.get(argo_name)
        if task is None:
            continue
        parts = [_sso(_resolve_argo_task_name(d, phase)) for d in deps]
        task.depends = " && ".join(parts)


def wire_pipeline_depends(tasks: dict[str, Task]) -> None:
    for task_name, spec in _PIPELINE.items():
        if task_name.startswith("_"):
            continue
        task = tasks.get(task_name)
        if task is None:
            continue
        if "depends_expr" in spec:
            task.depends = spec["depends_expr"]
        elif spec.get("depends"):
            # Sequential pipeline steps: require Succeeded (not SSO) so
            # downstream tasks don't run when upstream was Omitted due to failure.
            parts = [f"{dep}.Succeeded" for dep in spec["depends"]]
            task.depends = " && ".join(parts)
        if "when" in spec:
            task.when = spec["when"]


def wire_depends(tasks: dict[str, Task], phase: str) -> None:
    wire_phase_depends(tasks, phase)
