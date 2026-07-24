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

import json
from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).parents[1]
LOCAL_RECORDS = {
    ".structured-dev-state",
    "implementation-log.md",
    "plan.md",
    "research.md",
}
LICENSE_MARKER = "Licensed under the Apache License, Version 2.0"


def public_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if (
            relative.parts[0] in {".git", ".venv", "output"}
            or "__pycache__" in relative.parts
            or relative.name in LOCAL_RECORDS
            or relative.suffix == ".pyc"
        ):
            continue
        yield path


class RepositoryTests(unittest.TestCase):
    def test_json_and_yaml_documents_parse(self):
        for path in public_files():
            with self.subTest(path=path.relative_to(ROOT)):
                if path.suffix == ".json":
                    json.loads(path.read_text(encoding="utf-8"))
                elif path.suffix in {".yaml", ".yml"}:
                    list(yaml.safe_load_all(path.read_text(encoding="utf-8")))

    def test_python_files_have_license_header(self):
        for path in public_files():
            if path.suffix != ".py":
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn(
                    LICENSE_MARKER,
                    "\n".join(path.read_text(encoding="utf-8").splitlines()[:15]),
                )

    def test_relative_markdown_links_resolve(self):
        link_pattern = re.compile(r"\[[^\]]+\]\((?!https?://|#)([^)]+)\)")
        for path in public_files():
            if path.suffix != ".md":
                continue
            for target in link_pattern.findall(path.read_text(encoding="utf-8")):
                target_path = target.split("#", 1)[0]
                if not target_path:
                    continue
                with self.subTest(path=path.relative_to(ROOT), target=target):
                    self.assertTrue((path.parent / target_path).exists())

    def test_public_files_do_not_describe_private_history(self):
        prohibited = re.compile(
            r"\b("
            + "|".join(
                [
                    "OSS " + "version",
                    "R" + "AF",
                    "hard" + "ening",
                    "internal " + "packages",
                    "migra" + "tion",
                ]
            )
            + r")\b",
            re.IGNORECASE,
        )
        for path in public_files():
            if path.suffix not in {".py", ".md", ".json", ".yaml", ".yml", ".toml"}:
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(prohibited.search(path.read_text(encoding="utf-8")))

    def test_runtime_images_are_digest_pinned(self):
        image_pattern = re.compile(r"^\s*image:\s*(\S+)", re.MULTILINE)
        for path in public_files():
            if path.suffix not in {".yaml", ".yml"}:
                continue
            for image in image_pattern.findall(path.read_text(encoding="utf-8")):
                with self.subTest(path=path.relative_to(ROOT), image=image):
                    self.assertIn("@sha256:", image)


if __name__ == "__main__":
    unittest.main()
