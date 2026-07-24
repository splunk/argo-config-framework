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

"""Load the patch builder that belongs to the selected adapter."""
from collections.abc import Callable
from importlib import import_module
import re


_ADAPTER_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def load_patch_builder(adapter_name: str) -> Callable:
    if not _ADAPTER_NAME.fullmatch(adapter_name):
        raise ValueError(
            f"Invalid adapter name {adapter_name!r}; use lowercase letters, digits, and underscores."
        )

    module_name = f"adapters.{adapter_name}_patch_builder"
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise ValueError(
                f"Adapter {adapter_name!r} is missing {module_name.replace('.', '/')}.py"
            ) from exc
        raise

    builder = getattr(module, "build_patch_task", None)
    if not callable(builder):
        raise ValueError(f"{module_name} must define a callable build_patch_task()")
    return builder


__all__ = ["load_patch_builder"]
