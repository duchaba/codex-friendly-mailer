"""Integration-style unit tests for the command-line workflow."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from friendly_mailer.cli import main


class NoAITests(unittest.TestCase):
    """Verify behavior that must remain local when ``--noai`` is active."""

    def test_noai_does_not_require_key_and_replaces_name(self):
        """No-AI preview succeeds without a key and expands ``{name}``."""
        # Temporary paths isolate previews and input fixtures from the project.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contacts = root / "contacts.csv"
            message = root / "message.txt"
            outbox = root / "outbox"
            contacts.write_text("name,email\nAlex Smith,alex@example.com\n", encoding="utf-8")
            message.write_text("Hello, {name}!", encoding="utf-8")
            # An explicitly empty key proves the OpenAI credential gate is
            # bypassed rather than satisfied by the developer's environment.
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                result = main(
                    [
                        str(contacts),
                        str(message),
                        "--subject",
                        "Hello",
                        "--noai",
                        "--outbox",
                        str(outbox),
                    ]
                )
            self.assertEqual(result, 0)
            # Reading the generated MIME preview tests the user-visible result.
            preview = next(outbox.glob("*.eml")).read_text(encoding="utf-8")
            self.assertIn("Hello, Alex!", preview)

    def test_send_continues_after_failure_and_does_not_retry(self):
        """CLI attempts every recipient once and persists each final state."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contacts = root / "contacts.csv"
            message = root / "message.txt"
            credentials = root / "credentials.json"
            outbox = root / "outbox"
            log = root / "send-log.jsonl"
            contacts.write_text(
                "name,email\n"
                "Alex One,alex1@example.com\n"
                "Alex Two,alex2@example.com\n"
                "Alex Three,alex3@example.com\n",
                encoding="utf-8",
            )
            message.write_text("Hello, {name}!", encoding="utf-8")
            credentials.write_text("{}", encoding="utf-8")

            with (
                patch("friendly_mailer.cli.gmail_service", return_value=object()),
                patch(
                    "friendly_mailer.cli.send_message",
                    side_effect=["gmail-1", RuntimeError("delivery failed"), "gmail-3"],
                ) as mocked_send,
                patch("friendly_mailer.cli.time.sleep"),
            ):
                result = main(
                    [
                        str(contacts),
                        str(message),
                        "--subject",
                        "Hello",
                        "--noai",
                        "--send",
                        "--yes",
                        "--credentials",
                        str(credentials),
                        "--outbox",
                        str(outbox),
                        "--log",
                        str(log),
                    ]
                )

            self.assertEqual(result, 2)
            self.assertEqual(mocked_send.call_count, 3)
            statuses = json.loads(
                (outbox / "delivery-status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [item["status"] for item in statuses], ["sent", "failed", "sent"]
            )
            self.assertEqual(len(log.read_text(encoding="utf-8").splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
