import tempfile
import unittest
from pathlib import Path

from friendly_mailer.core import Contact, Draft, build_email, load_contacts, message_id


class CoreTests(unittest.TestCase):
    def test_load_contacts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contacts.csv"
            path.write_text("name,email\nAlex,Alex@Example.com\n", encoding="utf-8")
            self.assertEqual(load_contacts(path), [Contact("Alex", "alex@example.com")])

    def test_rejects_duplicate_contact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contacts.csv"
            path.write_text(
                "name,email\nAlex,a@example.com\nOther,A@example.com\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_contacts(path)

    def test_build_email_is_plain_text(self):
        draft = Draft(Contact("Alex", "alex@example.com"), "Hello", "Hi Alex!")
        message = build_email(draft)
        self.assertEqual(message["To"], "Alex <alex@example.com>")
        self.assertEqual(message.get_content().strip(), "Hi Alex!")

    def test_message_id_is_stable(self):
        contact = Contact("Alex", "alex@example.com")
        self.assertEqual(
            message_id(contact, "Hi", "Body"), message_id(contact, "Hi", "Body")
        )


if __name__ == "__main__":
    unittest.main()
