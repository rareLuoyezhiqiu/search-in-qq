"""Check local Markdown file references without network or third-party packages."""

import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")


def missing_local_targets(document):
    failures = []
    for match in LINK.finditer(document.read_text(encoding="utf-8")):
        target = match.group(1).strip().strip("<>")
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        destination = document.parent / unquote(parsed.path)
        if not destination.is_file():
            failures.append(target)
    return failures


class DocumentationTests(unittest.TestCase):
    def test_repository_local_links_resolve(self):
        for document in sorted(ROOT.rglob("*.md")):
            if any(part in {".git", "node_modules", ".venv"} for part in document.parts):
                continue
            with self.subTest(document=str(document.relative_to(ROOT))):
                self.assertEqual([], missing_local_targets(document))

    def test_missing_target_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "plan.md"
            document.write_text("[验收](missing.md)", encoding="utf-8")
            self.assertEqual(["missing.md"], missing_local_targets(document))

    def test_relative_unicode_target_resolves(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "验收.md").write_text("# 用例", encoding="utf-8")
            (folder / "docs").mkdir()
            document = folder / "docs" / "plan.md"
            document.write_text("[验收](../验收.md)", encoding="utf-8")
            self.assertEqual([], missing_local_targets(document))

    def test_external_urls_and_same_page_anchors_are_not_files(self):
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "plan.md"
            document.write_text(
                "[官方](https://example.com/docs) [本节](#section)", encoding="utf-8"
            )
            self.assertEqual([], missing_local_targets(document))


if __name__ == "__main__":
    unittest.main()
