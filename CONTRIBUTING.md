# Contributing to argo-config-framework

Thank you for considering a contribution.

## Before submitting

By submitting a contribution, you confirm that you have the right to provide
it under the [Apache 2.0 License](LICENSE).

External contributors must complete the
[Splunk Contributor License Agreement](https://www.splunk.com/en_us/form/contributions.html)
before a pull request can be merged.

For a significant change, such as a new adapter, task type, or catalog schema,
open an issue first so the design can be discussed.

## Development setup

```bash
git checkout -b feature/my-change
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Keep changes focused and follow these project contracts:

- Python files use the repository’s Apache 2.0 header.
- Platform-specific behavior belongs in an adapter or base template.
- Register new steps in `steps_catalog.json` and document their behavior.
- An adapter provides `<name>.json` and `<name>_patch_builder.py`.
- Do not commit generated workflows, virtual environments, caches, or secrets.

## Validate a change

```bash
ruff check framework adapters generate.py tests
python -m unittest discover -s tests -v
python -m compileall -q framework adapters generate.py tests
python generate.py \
  --adapter kubernetes \
  --catalog examples/nginx/nginx_config.json \
  --output output/nginx-workflow.yaml
argo lint --offline base_templates/*.yaml output/nginx-workflow.yaml
```

Changes to Kubernetes behavior should also be exercised with the dedicated kind
example described in [README.md](README.md).

## Pull requests

Open a pull request against `main` and include:

- the reason for the change;
- user-visible or compatibility effects;
- tests performed;
- documentation updates when behavior changes.

Do not report vulnerabilities in a public issue or pull request. Follow
[SECURITY.md](SECURITY.md) instead.
