from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Contact:
    name: str
    email: str


@dataclass(frozen=True)
class Draft:
    contact: Contact
    subject: str
    body: str


def load_contacts(path: Path) -> list[Contact]:
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
    content = "\0".join((contact.email, subject, original)).encode()
    return hashlib.sha256(content).hexdigest()[:20]


def build_email(draft: Draft, sender: str | None = None) -> EmailMessage:
    message = EmailMessage()
    message["To"] = f"{draft.contact.name} <{draft.contact.email}>"
    if sender:
        message["From"] = sender
    message["Subject"] = draft.subject
    message.set_content(draft.body.rstrip() + "\n")
    return message


def read_sent_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            ids.add(json.loads(line)["id"])
    return ids
