"""Integration-style unit tests for the command-line workflow."""

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


if __name__ == "__main__":
    unittest.main()
