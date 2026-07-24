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

"""Command-line interface for generating Argo WorkflowTemplates."""

import argparse
from importlib.resources import files
from pathlib import Path

from .resources import data_path
from .workflow import build_workflow


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an Argo WorkflowTemplate from a configuration catalog."
    )
    parser.add_argument(
        "--adapter",
        help="Adapter name, such as kubernetes.",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        help="Path to a catalog JSON file or directory.",
    )
    parser.add_argument(
        "--output",
        default=Path("output/workflow.yaml"),
        type=Path,
        help="Output YAML path (default: output/workflow.yaml).",
    )
    parser.add_argument(
        "--cluster-type",
        default="single",
        help="Cluster type declared in the catalog (default: single).",
    )
    parser.add_argument(
        "--export-base-templates",
        type=Path,
        metavar="DIRECTORY",
        help="Write the packaged Kubernetes base templates and exit.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing files when exporting base templates.",
    )
    return parser


def _export_base_templates(destination: Path, force: bool) -> None:
    templates = data_path("base_templates")
    destination.mkdir(parents=True, exist_ok=True)
    for template in templates.iterdir():
        if not template.name.endswith(".yaml"):
            continue
        output = destination / template.name
        if output.exists() and not force:
            raise SystemExit(
                f"refusing to replace {output}; use --force to replace existing files"
            )
        output.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Exported: {output}")


def main() -> int:
    parser = _parser()
    args = parser.parse_args()

    if args.export_base_templates:
        _export_base_templates(args.export_base_templates, args.force)
        return 0
    if not args.adapter or not args.catalog:
        parser.error("--adapter and --catalog are required to generate a workflow")

    adapter_resource = files("adapters").joinpath(f"{args.adapter}.json")
    if not adapter_resource.is_file():
        raise SystemExit(f"adapter not found: {args.adapter!r}")
    if not args.catalog.exists():
        raise SystemExit(f"catalog not found: {args.catalog}")

    workflow = build_workflow(
        adapter_name=args.adapter,
        adapter_path=Path(str(adapter_resource)),
        catalog_path=args.catalog,
        cluster_type=args.cluster_type,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(workflow.to_yaml(), encoding="utf-8")
    print(f"Generated: {args.output}")
    return 0
