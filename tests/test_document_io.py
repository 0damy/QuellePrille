"""Unit tests for document atomic file saving and format handling.

Verifies APP-02 and NFR-10:
- Atomic save prevents file corruption.
- Overwrite requires explicit confirmation.
"""

import tempfile
import unittest
from pathlib import Path
from localtext.storage.document_io import DocumentIO, DocumentIOError


class TestDocumentIO(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_atomic_save_and_read(self):
        file_path = self.dir_path / "test_doc.md"
        content = "# Title\n\nSample text with umlauts: äöü and emoji 🚀."
        DocumentIO.atomic_save(file_path, content, allow_overwrite=False)

        read_content, fmt = DocumentIO.read_file(file_path)
        self.assertEqual(read_content, content)
        self.assertEqual(fmt, "markdown")

    def test_nfr10_overwrite_refused_without_flag(self):
        file_path = self.dir_path / "protected.txt"
        file_path.write_text("Existing original content", encoding="utf-8")

        with self.assertRaises(DocumentIOError) as ctx:
            DocumentIO.atomic_save(file_path, "New content", allow_overwrite=False)

        self.assertIn("already exists", str(ctx.exception))
        # Ensure original file was NOT touched
        self.assertEqual(file_path.read_text(encoding="utf-8"), "Existing original content")

        # Explicit overwrite allowed
        DocumentIO.atomic_save(file_path, "Overwritten content", allow_overwrite=True)
        self.assertEqual(file_path.read_text(encoding="utf-8"), "Overwritten content")


if __name__ == "__main__":
    unittest.main()
