"""Unit tests for deterministic contact and MIME-message utilities."""

import tempfile
import unittest
from pathlib import Path

from friendly_mailer.core import (
    Contact,
    Draft,
    build_email,
    format_message_file,
    load_contacts,
    message_id,
    parse_message_file,
)


class CoreTests(unittest.TestCase):
    """Exercise validation, normalization, MIME creation, and stable IDs."""

    def test_load_contacts(self):
        """CSV loading preserves names and normalizes email case."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contacts.csv"
            path.write_text("name,email\nAlex,Alex@Example.com\n", encoding="utf-8")
            self.assertEqual(load_contacts(path), [Contact("Alex", "alex@example.com")])

    def test_rejects_duplicate_contact(self):
        """Addresses differing only by case are rejected as duplicates."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contacts.csv"
            path.write_text(
                "name,email\nAlex,a@example.com\nOther,A@example.com\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_contacts(path)

    def test_build_email_is_plain_text(self):
        """MIME construction sets the recipient and a plain-text body."""
        draft = Draft(Contact("Alex", "alex@example.com"), "Hello", "Hi Alex!")
        message = build_email(draft)
        self.assertEqual(message["To"], "Alex <alex@example.com>")
        self.assertEqual(message.get_content().strip(), "Hi Alex!")

    def test_message_id_is_stable(self):
        """Identical logical inputs always produce the same send identifier."""
        contact = Contact("Alex", "alex@example.com")
        self.assertEqual(
            message_id(contact, "Hi", "Body"), message_id(contact, "Hi", "Body")
        )

    def test_message_subject_metadata_round_trip(self):
        """Subject metadata serializes and parses without entering the body."""
        content = format_message_file("Welcome back", "Hello, {name}!")
        self.assertEqual(
            parse_message_file(content), ("Welcome back", "Hello, {name}!\n")
        )

    def test_message_without_metadata_uses_default_subject(self):
        """Legacy body-only message files retain their complete content."""
        self.assertEqual(parse_message_file("Hello!", "Fallback"), ("Fallback", "Hello!"))


if __name__ == "__main__":
    unittest.main()
