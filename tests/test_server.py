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


if __name__ == "__main__":
    unittest.main()
