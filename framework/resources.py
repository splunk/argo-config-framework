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

"""Locate framework data in a source checkout or installed package."""

from pathlib import Path


_SOURCE_ROOT = Path(__file__).parent.parent
_PACKAGE_DATA = Path(__file__).parent / "data"


def data_path(relative_path: str) -> Path:
    """Return a framework data path, preferring a source checkout."""
    source_path = _SOURCE_ROOT / relative_path
    if source_path.exists():
        return source_path
    return _PACKAGE_DATA / relative_path
