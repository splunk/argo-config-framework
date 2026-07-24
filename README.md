# argo-config-framework

`argo-config-framework` generates Argo WorkflowTemplates from a configuration
catalog. The catalog chooses which precheck, execution, and postcheck tasks are
available for a change, while an adapter connects those tasks to platform
operations. This repository includes a Kubernetes ConfigMap adapter and an
nginx example.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)

> **Project status: alpha.** This is an experimental reference implementation,
> not a production-ready change-management system. Review the generated
> workflow, catalog rules, RBAC, container images, and failure behavior before
> using it in any environment.

## How it works

```text
catalog + step definitions + adapter + wiring
                         |
                 workflow generator
                         |
              Argo WorkflowTemplate
                         |
        prechecks -> execution -> postchecks
```

The generator creates one workflow structure. For each configuration entry, the
catalog enables the registered tasks that apply to that entry. For example, a
catalog can select:

- prechecks that read current state, detect an already-applied value, and check
  workload health;
- execution tasks that patch a ConfigMap, wait for convergence, and reload a
  process;
- postchecks that verify the new state and check workload health again.

Catalog validation checks step names, permitted phases, required fields, and
guardrail structure before YAML is generated. Runtime tasks validate the
submitted change before mutation.

## Repository layout

```text
generate.py                 source-checkout CLI
framework/
  cli.py                    installed CLI
  workflow.py               WorkflowTemplate assembly
  dag_builder.py            task construction and dependencies
  config.py                 catalog loading and step registry
  conf_validator.py         catalog validation
  scripts/                  runtime validation and resolution
adapters/
  kubernetes.json           task-to-template routing
  kubernetes_patch_builder.py
base_templates/             Kubernetes Argo WorkflowTemplates
steps/                      reusable task definitions
pipeline.json               top-level DAG dependencies
wiring.json                 phase dependencies
steps_catalog.json          registered step names and phases
examples/nginx/             local end-to-end example
tests/                      standard-library unit tests
```

## Requirements

- Python 3.11 or newer
- Argo Workflows 3.6 for the example
- `kubectl`
- Docker and kind for the local integration example

## Install

From a checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

This installs the `argo-config-framework` command. The source-checkout command
`python generate.py` provides the same interface.

An installed package can export the Kubernetes base templates:

```bash
argo-config-framework --export-base-templates ./base_templates
```

## Generate the nginx workflow

```bash
argo-config-framework \
  --adapter kubernetes \
  --catalog examples/nginx/nginx_config.json \
  --output output/nginx-workflow.yaml

argo lint --offline base_templates/*.yaml output/nginx-workflow.yaml
```

The generator only writes YAML. It does not connect to a Kubernetes cluster.

## Run the example locally

Use a dedicated kind cluster and namespace:

```bash
kind create cluster --name argo-config-test

kubectl create namespace argo --context kind-argo-config-test
kubectl apply --context kind-argo-config-test -n argo \
  -f https://github.com/argoproj/argo-workflows/releases/download/v3.6.7/install.yaml

kubectl wait --context kind-argo-config-test -n argo \
  --for=condition=available deployment/workflow-controller --timeout=180s

kubectl apply --context kind-argo-config-test -n argo \
  -f examples/nginx/nginx-configmap.yaml \
  -f examples/nginx/nginx-deployment.yaml \
  -f examples/nginx/rbac.yaml \
  -f base_templates/ \
  -f output/nginx-workflow.yaml

kubectl wait --context kind-argo-config-test -n argo \
  --for=condition=available deployment/nginx --timeout=120s
```

Submit a change:

```bash
argo submit --context kind-argo-config-test -n argo \
  --from workflowtemplate/argo-config-framework \
  -p ticket_id="NGINX-1234" \
  -p target_id="nginx" \
  -p changes='[{"conf":"nginx_rate_limit","app":"system","stanza":"http","key":"rate_limit","value":"20r/s","operation":"upsert"}]' \
  --watch
```

Inspect the resulting ConfigMap:

```bash
kubectl get configmap nginx-config \
  --context kind-argo-config-test -n argo -o jsonpath='{.data}'
```

## Catalog format

A catalog describes configuration inputs, guardrails, and the tasks selected
for each phase:

```json
{
  "my_configuration": {
    "single": {
      "default_target": "my-service",
      "targets": {
        "my-service": {
          "component_role": "my-service",
          "apps": {
            "system": {
              "state_store_ref": "my-configmap",
              "state_store_path": "data",
              "inputs": {
                "app": {"required": false, "default": "system"},
                "conf": {
                  "required": false,
                  "default": "my_configuration",
                  "overridable": false
                },
                "stanza": {"required": true},
                "key": {"required": true},
                "value": {"required": true}
              },
              "guardrails": {
                "allowed_apps": ["system"],
                "forbidden_apps": null,
                "allowed_confs": ["my_configuration"],
                "forbidden_confs": null,
                "allowed_stanzas": null,
                "forbidden_stanzas": null,
                "allowed_keys": ["key1", "key2"],
                "forbidden_keys": ["secret_key"],
                "allowed_operations": ["upsert"],
                "forbidden_operations": ["remove"]
              },
              "precheck": {
                "steps": [
                  {"name": "get_spec"},
                  {"name": "idempotency_check"},
                  {"name": "health_check"}
                ]
              },
              "execution": {
                "steps": [
                  {"name": "patch_state_store"},
                  {"name": "wait_convergence"},
                  {"name": "apply_config_agent"}
                ]
              },
              "postcheck": {
                "steps": [
                  {"name": "verify_config"},
                  {"name": "health_check"}
                ]
              }
            }
          }
        }
      }
    }
  }
}
```

Every `allowed_*` guardrail requires the matching `forbidden_*` field; use
`null` when no restriction is needed. A workflow run can contain multiple key
changes, but the changes must share one target, component role, state store,
configuration name, and stanza.

`state_store_path` is available to adapters. The Kubernetes reference adapter
stores each changed key directly in ConfigMap `data` and does not interpret
this field.

See [steps_catalog.json](steps_catalog.json) for the registered steps and their
permitted phases.

## Adapter contract

An adapter has two parts:

1. `adapters/<name>.json` maps each external task operation to an Argo
   `WorkflowTemplate` and template name.
2. `adapters/<name>_patch_builder.py` exports a callable
   `build_patch_task()` that returns a Hera `Script`.

The generator validates that the routing table provides each operation used by
the workflow wiring. See [adapters/kubernetes.json](adapters/kubernetes.json)
and [kubernetes_patch_builder.py](adapters/kubernetes_patch_builder.py) for the
reference contract.

Adapter authors provide the corresponding Argo base templates. Retry behavior
belongs in those concrete templates because Argo applies retry strategies at
the template level.

## Operational boundaries

- Workflow submitters are trusted operators. Public workflow parameters,
  including skip flags and webhook URLs, are operational controls and are not
  authorization boundaries.
- The example ServiceAccount can read pods, execute commands in matching pods,
  and read or patch ConfigMaps in its namespace. Use a dedicated namespace and
  review the permissions for your deployment.
- The ticketing and alerting templates are optional integration examples. An
  empty endpoint disables them; their payload and authentication must be
  adapted to the selected service.
- `skip_health_check=true` skips catalog-selected health checks.
- Verification fails when it receives no usable configuration evidence.
- If any requested change is already applied, the idempotency check blocks the
  whole batch.
- A patch is not automatically reverted when convergence or a later postcheck
  fails.
- Alert cleanup is catalog-driven. An adapter that must always unmute alerts
  should use an Argo exit handler or an equivalent recovery mechanism.
- Use reviewed images from a trusted registry and pin them according to your
  organization’s supply-chain policy.
- Do not store credentials, tokens, or sensitive internal URLs in catalogs,
  adapter files, or workflow parameters.

## Development

```bash
python -m pip install -e .
ruff check framework adapters generate.py tests
python -m unittest discover -s tests -v
python -m compileall -q framework adapters generate.py tests
python generate.py \
  --adapter kubernetes \
  --catalog examples/nginx/nginx_config.json \
  --output output/nginx-workflow.yaml
argo lint --offline base_templates/*.yaml output/nginx-workflow.yaml
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidance and
[SECURITY.md](SECURITY.md) for vulnerability reporting.

## License

Licensed under Apache 2.0. See [LICENSE](LICENSE).
