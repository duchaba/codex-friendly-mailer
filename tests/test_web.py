"""Tests for local dashboard validation, previews, and batch logging."""

import json
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
        self.assertIn(b"delivery-result", response.data)
        self.assertIn(b"delivery-sent", response.data)
        self.assertIn(b"Friendly Mailer v2.0", response.data)

    def test_library_loads_contact_circle(self):
        """The contacts selector endpoint loads an existing SQLite circle."""
        response = self.client.post(
            "/api/load", json={"kind": "contacts", "name": "circle0-qa"}
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

    def test_send_continues_after_failure_and_does_not_retry(self):
        """One failed recipient does not stop or retry the remaining batch."""
        contacts = [
            {"name": "Alex One", "email": "alex1@example.com"},
            {"name": "Alex Two", "email": "alex2@example.com"},
            {"name": "Alex Three", "email": "alex3@example.com"},
        ]
        preview = self.client.post(
            "/api/preview",
            json={
                "contacts": contacts,
                "subject": "Hello",
                "message": "Hi {name}!",
                "noai": True,
            },
        )
        self.assertEqual(preview.status_code, 200)
        token = preview.get_json()["token"]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch("friendly_mailer.web.LOGS_PATH", root / "logs"),
                patch("friendly_mailer.web.LOG_PATH", root / "send-log.jsonl"),
                patch("friendly_mailer.web.gmail_service", return_value=object()),
                patch(
                    "friendly_mailer.web.send_message",
                    side_effect=["gmail-1", RuntimeError("delivery failed"), "gmail-3"],
                ) as mocked_send,
                patch("friendly_mailer.web.time.sleep"),
            ):
                response = self.client.post(
                    "/api/send", json={"token": token, "immediate": True}
                )

            self.assertEqual(response.status_code, 200)
            result = response.get_json()
            self.assertEqual(len(result["sent"]), 2)
            self.assertEqual(len(result["failed"]), 1)
            self.assertEqual(result["pending"], [])
            self.assertEqual(mocked_send.call_count, 3)

            status_files = list((root / "logs").glob("*/delivery-status.json"))
            self.assertEqual(len(status_files), 1)
            statuses = json.loads(status_files[0].read_text(encoding="utf-8"))
            self.assertEqual(
                [item["status"] for item in statuses], ["sent", "failed", "sent"]
            )

    def test_large_campaign_sends_in_fifty_recipient_batches(self):
        """A campaign above 50 is accepted and summarized in ordered chunks."""
        contacts = [
            {"name": f"Person {number}", "email": f"person{number}@example.com"}
            for number in range(1, 54)
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("friendly_mailer.web.OUTBOX_PATH", root / "outbox"):
                preview = self.client.post(
                    "/api/preview",
                    json={
                        "contacts": contacts,
                        "subject": "Hello",
                        "message": "Hi {name}!",
                        "noai": True,
                    },
                )
            self.assertEqual(preview.status_code, 200)
            token = preview.get_json()["token"]

            with (
                patch("friendly_mailer.web.LOGS_PATH", root / "logs"),
                patch("friendly_mailer.web.LOG_PATH", root / "send-log.jsonl"),
                patch("friendly_mailer.web.gmail_service", return_value=object()),
                patch("friendly_mailer.web.send_message", return_value="gmail-id") as send,
                patch("friendly_mailer.web.time.sleep"),
            ):
                response = self.client.post(
                    "/api/send", json={"token": token, "immediate": True}
                )

            self.assertEqual(response.status_code, 200)
            result = response.get_json()
            self.assertEqual(send.call_count, 53)
            self.assertEqual(result["batchSize"], 50)
            self.assertEqual(result["batchCount"], 2)
            self.assertEqual(
                result["batches"],
                [
                    {"batch": 1, "total": 50, "sent": 50, "failed": 0, "pending": 0},
                    {"batch": 2, "total": 3, "sent": 3, "failed": 0, "pending": 0},
                ],
            )
            status_file = next((root / "logs").glob("*/delivery-status.json"))
            statuses = json.loads(status_file.read_text(encoding="utf-8"))
            self.assertEqual([item["batch"] for item in statuses[:50]], [1] * 50)
            self.assertEqual([item["batch"] for item in statuses[50:]], [2] * 3)


if __name__ == "__main__":
    unittest.main()
