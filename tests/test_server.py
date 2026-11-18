import unittest

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


if __name__ == "__main__":
    unittest.main()
