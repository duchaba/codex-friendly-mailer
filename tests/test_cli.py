import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from friendly_mailer.cli import main


class NoAITests(unittest.TestCase):
    def test_noai_does_not_require_key_and_replaces_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contacts = root / "contacts.csv"
            message = root / "message.txt"
            outbox = root / "outbox"
            contacts.write_text("name,email\nAlex Smith,alex@example.com\n", encoding="utf-8")
            message.write_text("Hello, {name}!", encoding="utf-8")
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
            preview = next(outbox.glob("*.eml")).read_text(encoding="utf-8")
            self.assertIn("Hello, Alex!", preview)


if __name__ == "__main__":
    unittest.main()
