"""Pure data and message-building utilities for Friendly Mailer.

Functions in this module do not call OpenAI or Gmail. Keeping parsing,
validation, identifier creation, and MIME construction here makes those
behaviors deterministic and easy to test without network credentials.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SUBJECT_RE = re.compile(r"^\{subject:\s*(.*?)\}\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Contact:
    """A validated email recipient.

    Attributes:
        name: Display name used for addressing and personalization.
        email: Normalized, lowercase destination email address.
    """

    name: str
    email: str


@dataclass(frozen=True)
class Draft:
    """A complete plain-text email waiting for preview or delivery.

    Attributes:
        contact: Recipient of the email.
        subject: Subject line shared with the MIME message.
        body: Plain-text message body.
    """

    contact: Contact
    subject: str
    body: str


def parse_message_file(content: str, default_subject: str = "Touch base") -> tuple[str, str]:
    """Separate optional subject metadata from a message file.

    The recognized first-line format is ``{subject: Welcome back}``. Only the
    first line is treated as metadata, so similar text elsewhere remains part
    of the message body.

    Args:
        content: Complete text loaded from a message file.
        default_subject: Subject returned when no metadata line is present.

    Returns:
        A ``(subject, body)`` tuple with the metadata line removed from body.
    """
    first_line, separator, remainder = content.partition("\n")
    match = SUBJECT_RE.fullmatch(first_line.strip())
    if not match:
        return default_subject, content
    subject = match.group(1).strip() or default_subject
    return subject, remainder.lstrip("\r\n") if separator else ""


def format_message_file(subject: str, body: str) -> str:
    """Serialize a subject and body using the message-file metadata format.

    Args:
        subject: Subject text to place in the first-line metadata record.
        body: Plain-text email body.

    Returns:
        File content ending with one newline.

    Raises:
        ValueError: If the subject or body is empty, or the subject contains a
            line break or closing brace that would corrupt the metadata record.
    """
    clean_subject = subject.strip()
    clean_body = body.strip()
    if not clean_subject or not clean_body:
        raise ValueError("Subject and message are required")
    if "\n" in clean_subject or "\r" in clean_subject or "}" in clean_subject:
        raise ValueError("Subject cannot contain a line break or closing brace")
    return f"{{subject: {clean_subject}}}\n\n{clean_body}\n"


def load_contacts(path: Path) -> list[Contact]:
    """Read and validate contacts from a CSV file.

    Email addresses are normalized to lowercase. Duplicate addresses are
    rejected after normalization so a recipient cannot be contacted twice in
    one run merely because capitalization differs.

    Args:
        path: UTF-8 or UTF-8-with-BOM CSV containing ``name`` and ``email``
            header columns. Additional columns are ignored.

    Returns:
        Validated contacts in their original CSV order.

    Raises:
        OSError: If the file cannot be opened or read.
        ValueError: If headers are missing, a row is invalid, an address is
            duplicated, or the file contains no contacts.
    """
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {"name", "email"}.issubset(reader.fieldnames):
            raise ValueError("Contacts CSV must have 'name' and 'email' columns")
        contacts = []
        seen: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            name = (row.get("name") or "").strip()
            email = (row.get("email") or "").strip().lower()
            if not name:
                raise ValueError(f"Row {row_number}: name is required")
            if not EMAIL_RE.fullmatch(email):
                raise ValueError(f"Row {row_number}: invalid email address {email!r}")
            if email in seen:
                raise ValueError(f"Row {row_number}: duplicate email address {email!r}")
            seen.add(email)
            contacts.append(Contact(name=name, email=email))
    if not contacts:
        raise ValueError("Contacts CSV contains no contacts")
    return contacts


def message_id(contact: Contact, subject: str, original: str) -> str:
    """Build a stable identifier used to prevent accidental duplicate sends.

    The identifier deliberately uses the original message rather than an AI
    draft because AI output may vary between runs. A NUL separator prevents
    ambiguous concatenations of the three fields.

    Args:
        contact: Recipient whose normalized address identifies the destination.
        subject: Email subject line.
        original: Original, pre-personalization message body.

    Returns:
        The first 20 hexadecimal characters of a SHA-256 digest.
    """
    content = "\0".join((contact.email, subject, original)).encode()
    return hashlib.sha256(content).hexdigest()[:20]


def build_email(draft: Draft, sender: str | None = None) -> EmailMessage:
    """Convert a draft into a standards-compliant plain-text MIME message.

    Args:
        draft: Recipient, subject, and body to encode.
        sender: Optional value for the ``From`` header. Gmail can populate the
            sender from the authorized account when this is omitted.

    Returns:
        An :class:`email.message.EmailMessage` ready for preview or Gmail.
    """
    message = EmailMessage()
    message["To"] = f"{draft.contact.name} <{draft.contact.email}>"
    if sender:
        message["From"] = sender
    message["Subject"] = draft.subject
    message.set_content(draft.body.rstrip() + "\n")
    return message


def read_sent_ids(path: Path) -> set[str]:
    """Load previously delivered message identifiers from a JSON Lines log.

    Args:
        path: Send-log path. A nonexistent path represents an empty history.

    Returns:
        Unique values from the ``id`` field of nonblank log records.

    Raises:
        OSError: If an existing log cannot be read.
        json.JSONDecodeError: If a nonblank line is not valid JSON.
        KeyError: If a log record has no ``id`` field.
    """
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            ids.add(json.loads(line)["id"])
    return ids
