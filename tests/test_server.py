import tempfile
import unittest
from pathlib import Path

from app.knowledge import list_topics, read_material
from app.store import NotFound

from app.server import Handler


class HandlerRoutingTests(unittest.TestCase):
    def test_session_collection_route(self):
        self.assertEqual(
            Handler._match_client_path("/api/clients/Avery%20Chen/sessions"),
            ("Avery Chen", None),
        )

    def test_session_item_route(self):
        self.assertEqual(
            Handler._match_client_path("/api/clients/Avery%20Chen/sessions/3"),
            ("Avery Chen", 3),
        )

    def test_invalid_session_number_does_not_match(self):
        self.assertIsNone(
            Handler._match_client_path("/api/clients/Avery%20Chen/sessions/latest")
        )

    def test_other_notes_routes_decode_client_and_filename(self):
        self.assertEqual(
            Handler._match_other_notes_path("/api/clients/Avery%20Chen/other-notes"),
            ("Avery Chen", None),
        )
        self.assertEqual(
            Handler._match_other_notes_path("/api/clients/Avery%20Chen/other-notes/Intake%20%231%3F.md"),
            ("Avery Chen", "Intake #1?.md"),
        )


class KnowledgeTests(unittest.TestCase):
    def test_lists_and_reads_nested_markdown_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Educational materials"
            career = root / "Career" / "Planning"
            career.mkdir(parents=True)
            (career / "Worksheet 1.md").write_text("# Career worksheet", encoding="utf-8")
            (career / "attachment.pdf").touch()
            (root / "Overview.md").touch()
            outside = Path(directory) / "outside.md"
            outside.write_text("Private", encoding="utf-8")
            (root / "linked.md").symlink_to(outside)
            self.assertEqual([topic["path"] for topic in list_topics(root)], [".", "Career/Planning"])
            relative = "Career/Planning/Worksheet 1.md"
            self.assertEqual(list_topics(root)[1]["materials"], [{"path": relative, "title": "Worksheet 1"}])
            self.assertEqual(read_material(root, relative)["content"], "# Career worksheet")
            for path in ("../outside.md", "linked.md", "Career/Planning/attachment.pdf"):
                with self.subTest(path=path), self.assertRaises(NotFound):
                    read_material(root, path)


if __name__ == "__main__":
    unittest.main()
