"""Tests for local dashboard validation, previews, and batch logging."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from friendly_mailer.core import Contact, Draft
from friendly_mailer.web import _save_batch_log, create_app


class DashboardTests(unittest.TestCase):
    """Exercise dashboard APIs without starting a real server."""

    def setUp(self):
        """Create Flask's in-process test client."""
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_dashboard_loads(self):
        """The main page renders the mailer controls."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Friendly Mailer", response.data)
        self.assertIn(b"Preview emails", response.data)
        self.assertIn(b"contact-file", response.data)
        self.assertIn(b"message-file", response.data)
        self.assertIn(b"Send now", response.data)
        self.assertIn(b"preview-summary", response.data)
        self.assertIn(b"Friendly Mailer v1.1.0", response.data)

    def test_library_loads_qa1_contacts(self):
        """The contacts selector endpoint loads an existing CSV list."""
        response = self.client.post(
            "/api/load", json={"kind": "contacts", "name": "qa1.csv"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.get_json()["contacts"]), 1)

    def test_library_rejects_path_traversal(self):
        """File selectors cannot read outside their designated folders."""
        response = self.client.post(
            "/api/load", json={"kind": "messages", "name": "../.env"}
        )
        self.assertEqual(response.status_code, 400)

    def test_message_library_returns_subject_and_body(self):
        """Selecting a message returns separate subject and body fields."""
        response = self.client.post(
            "/api/load", json={"kind": "messages", "name": "qa1.txt"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("subject", data)
        self.assertIn("message", data)

    def test_noai_preview_returns_local_substitution(self):
        """No-AI preview expands the name and returns a send token."""
        response = self.client.post(
            "/api/preview",
            json={
                "contacts": [{"name": "Alex Smith", "email": "alex@example.com"}],
                "subject": "Hello",
                "message": "Hi {name}!",
                "noai": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["drafts"][0]["body"], "Hi Alex!")
        self.assertTrue(data["token"])

    def test_batch_log_saves_exact_email_and_manifest(self):
        """Immediate delivery logging writes MIME and batch metadata first."""
        draft = Draft(Contact("Alex", "alex@example.com"), "Hello", "Hi Alex!")
        with tempfile.TemporaryDirectory() as directory:
            with patch("friendly_mailer.web.LOGS_PATH", Path(directory)):
                batch_path = _save_batch_log([("stable-id", draft)])
            self.assertEqual(len(list(batch_path.glob("*.eml"))), 1)
            self.assertTrue((batch_path / "batch.json").exists())
            self.assertIn("alex@example.com", (batch_path / "batch.json").read_text())


if __name__ == "__main__":
    unittest.main()
