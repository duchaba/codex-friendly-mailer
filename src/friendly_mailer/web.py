"""Local web dashboard for editing, previewing, and sending email batches."""

from __future__ import annotations

import csv
import io
import json
import secrets
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from flask import Flask, jsonify, render_template, request

from . import __version__
from .ai import personalize
from .cli import DEFAULT_LIMIT, load_local_env
from .core import (
    Contact,
    Draft,
    build_email,
    format_message_file,
    message_id,
    parse_message_file,
    read_sent_ids,
)
from .gmail import gmail_service, send_message


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTACTS_PATH = PROJECT_ROOT / "contacts" / "qa1.csv"
MESSAGE_PATH = PROJECT_ROOT / "messages" / "qa1.txt"
OUTBOX_PATH = PROJECT_ROOT / "outbox"
LOG_PATH = PROJECT_ROOT / "send-log.jsonl"
LOGS_PATH = PROJECT_ROOT / "logs"
CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"
TOKEN_PATH = PROJECT_ROOT / "token.json"
MAX_BATCHES = 20

# Previewed drafts stay in memory and are addressed by an unguessable token.
# This ensures the Send action delivers exactly what the user reviewed.
_preview_batches: dict[str, list[tuple[str, Draft]]] = {}
_batch_lock = Lock()


def _contacts_from_payload(payload: Any) -> list[Contact]:
    """Validate contacts supplied by the browser.

    Args:
        payload: JSON value expected to be a list of name/email dictionaries.

    Returns:
        Validated contacts in browser order.

    Raises:
        ValueError: If the list or any contact field is invalid or duplicated.
    """
    if not isinstance(payload, list) or not payload:
        raise ValueError("Add at least one recipient")
    if len(payload) > DEFAULT_LIMIT:
        raise ValueError(f"A batch may contain at most {DEFAULT_LIMIT} recipients")

    contacts: list[Contact] = []
    seen: set[str] = set()
    for number, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Recipient {number} is invalid")
        name = str(item.get("name", "")).strip()
        email = str(item.get("email", "")).strip().lower()
        if not name:
            raise ValueError(f"Recipient {number} needs a name")
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError(f"Recipient {number} has an invalid email address")
        if email in seen:
            raise ValueError(f"Duplicate email address: {email}")
        seen.add(email)
        contacts.append(Contact(name, email))
    return contacts


def _load_contacts() -> list[dict[str, str]]:
    """Load dashboard contacts from the qa1 CSV file.

    Returns:
        Serializable contact dictionaries, or an empty list when absent.
    """
    if not CONTACTS_PATH.exists():
        return []
    with CONTACTS_PATH.open(newline="", encoding="utf-8-sig") as handle:
        return [
            {"name": (row.get("name") or "").strip(), "email": (row.get("email") or "").strip()}
            for row in csv.DictReader(handle)
        ]


def _library_files(folder: Path, suffix: str) -> list[str]:
    """List editable library files in stable alphabetical order.

    Args:
        folder: Contacts or messages directory to inspect.
        suffix: Required lowercase file extension, including the leading dot.

    Returns:
        File names only, excluding directories and nested paths.
    """
    if not folder.exists():
        return []
    return sorted(
        (path.name for path in folder.iterdir() if path.is_file() and path.suffix.lower() == suffix),
        key=str.casefold,
    )


def _library_path(kind: str, name: str) -> Path:
    """Resolve a browser-selected library file without allowing traversal.

    Args:
        kind: Either ``contacts`` or ``messages``.
        name: Base file name selected in the dashboard.

    Returns:
        Absolute path inside the appropriate project folder.

    Raises:
        ValueError: If the kind, extension, or file name is invalid.
    """
    settings = {
        "contacts": (PROJECT_ROOT / "contacts", ".csv"),
        "messages": (PROJECT_ROOT / "messages", ".txt"),
    }
    if kind not in settings:
        raise ValueError("Unknown library type")
    folder, suffix = settings[kind]
    if Path(name).name != name or Path(name).suffix.lower() != suffix:
        raise ValueError("Invalid library file name")
    return folder / name


def _save_inputs(
    contacts: list[Contact],
    message: str,
    subject: str,
    contact_file: str = "qa1.csv",
    message_file: str = "qa1.txt",
) -> None:
    """Persist the editable qa1 contacts and source message.

    Args:
        contacts: Validated contacts to write as CSV.
        message: Plain-text source email body.
        subject: Subject saved as first-line message metadata.
        contact_file: Selected CSV file name inside the contacts folder.
        message_file: Selected text file name inside the messages folder.

    Returns:
        None.
    """
    contacts_path = _library_path("contacts", contact_file)
    message_path = _library_path("messages", message_file)
    contacts_path.parent.mkdir(parents=True, exist_ok=True)
    message_path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=["name", "email"], lineterminator="\n")
    writer.writeheader()
    writer.writerows(asdict(contact) for contact in contacts)
    contacts_path.write_text(buffer.getvalue(), encoding="utf-8")
    message_path.write_text(format_message_file(subject, message), encoding="utf-8")


def _save_batch_log(batch: list[tuple[str, Draft]]) -> Path:
    """Save the exact generated MIME messages before Gmail delivery.

    Args:
        batch: Stable message IDs paired with the reviewed/generated drafts.

    Returns:
        Timestamped batch directory under ``logs``. The timestamp uses the
        local clock and 24-hour ``YYYY-MM-DD-HH-MM`` formatting.
    """
    batch_path = LOGS_PATH / datetime.now().astimezone().strftime("%Y-%m-%d-%H-%M")
    batch_path.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, str]] = []
    for number, (draft_id, draft) in enumerate(batch, start=1):
        filename = f"{number:03d}-{draft_id}.eml"
        (batch_path / filename).write_bytes(build_email(draft).as_bytes())
        manifest.append(
            {
                "id": draft_id,
                "file": filename,
                "name": draft.contact.name,
                "recipient": draft.contact.email,
                "subject": draft.subject,
            }
        )
    (batch_path / "batch.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return batch_path


def create_app() -> Flask:
    """Create and configure the local Flask dashboard application.

    Returns:
        Configured Flask application with page, save, preview, and send routes.
    """
    load_local_env(PROJECT_ROOT / ".env")
    app = Flask(__name__)

    @app.get("/")
    def dashboard():
        """Render the dashboard with the saved qa1 data."""
        content = MESSAGE_PATH.read_text(encoding="utf-8") if MESSAGE_PATH.exists() else ""
        subject, message = parse_message_file(content)
        return render_template(
            "dashboard.html",
            initial={
                "contacts": _load_contacts(),
                "message": message,
                "subject": subject,
                "contactFiles": _library_files(PROJECT_ROOT / "contacts", ".csv"),
                "messageFiles": _library_files(PROJECT_ROOT / "messages", ".txt"),
                "contactFile": "qa1.csv",
                "messageFile": "qa1.txt",
                "appVersion": __version__,
            },
        )

    @app.post("/api/load")
    def load_library_file():
        """Load one selected contacts or message file into the dashboard."""
        try:
            data = request.get_json(force=True)
            kind = str(data.get("kind", ""))
            name = str(data.get("name", ""))
            path = _library_path(kind, name)
            if not path.exists():
                raise ValueError(f"File not found: {name}")
            if kind == "messages":
                subject, message = parse_message_file(path.read_text(encoding="utf-8"))
                return jsonify({"ok": True, "message": message, "subject": subject})
            with path.open(newline="", encoding="utf-8-sig") as handle:
                contacts = [
                    {
                        "name": (row.get("name") or "").strip(),
                        "email": (row.get("email") or "").strip(),
                    }
                    for row in csv.DictReader(handle)
                ]
            return jsonify({"ok": True, "contacts": contacts})
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/save")
    def save_inputs():
        """Validate and save contacts and source message without sending."""
        try:
            data = request.get_json(force=True)
            contacts = _contacts_from_payload(data.get("contacts"))
            message = str(data.get("message", "")).strip()
            subject = str(data.get("subject", "")).strip()
            if not message or not subject:
                raise ValueError("Subject and message are required")
            contact_file = str(data.get("contactFile") or "qa1.csv")
            message_file = str(data.get("messageFile") or "qa1.txt")
            _save_inputs(contacts, message, subject, contact_file, message_file)
            return jsonify({"ok": True, "message": "Saved selected contacts and message"})
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/preview")
    def preview():
        """Generate a reviewable batch and return its one-time token."""
        try:
            data = request.get_json(force=True)
            contacts = _contacts_from_payload(data.get("contacts"))
            message = str(data.get("message", "")).strip()
            subject = str(data.get("subject", "")).strip()
            noai = bool(data.get("noai"))
            model = str(data.get("model") or "gpt-5.6-luna").strip()
            if not message or not subject:
                raise ValueError("Subject and message are required")

            batch: list[tuple[str, Draft]] = []
            OUTBOX_PATH.mkdir(parents=True, exist_ok=True)
            for number, contact in enumerate(contacts, start=1):
                body = (
                    message.replace("{name}", contact.name.split()[0])
                    if noai
                    else personalize(contact, message, model=model)
                )
                draft = Draft(contact, subject, body)
                draft_id = message_id(contact, subject, message)
                (OUTBOX_PATH / f"{number:03d}-{draft_id}.eml").write_bytes(
                    build_email(draft).as_bytes()
                )
                batch.append((draft_id, draft))

            token = secrets.token_urlsafe(24)
            with _batch_lock:
                if len(_preview_batches) >= MAX_BATCHES:
                    _preview_batches.pop(next(iter(_preview_batches)))
                _preview_batches[token] = batch
            return jsonify(
                {
                    "ok": True,
                    "token": token,
                    "drafts": [
                        {
                            "name": draft.contact.name,
                            "email": draft.contact.email,
                            "subject": draft.subject,
                            "body": draft.body,
                        }
                        for _, draft in batch
                    ],
                }
            )
        except Exception as exc:  # SDK errors are converted to a dashboard message.
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/send")
    def send_batch():
        """Log and send exactly one previously generated batch.

        The dashboard's preview flow requires the traditional ``SEND N``
        phrase. The explicitly labeled Send-now flow passes ``immediate=true``
        and proceeds without that second confirmation.
        """
        try:
            data = request.get_json(force=True)
            token = str(data.get("token", ""))
            with _batch_lock:
                batch = _preview_batches.get(token)
            if not batch:
                raise ValueError("Preview expired. Generate a new preview before sending")
            immediate = data.get("immediate") is True
            if not immediate and data.get("confirmation") != f"SEND {len(batch)}":
                raise ValueError(f"Type SEND {len(batch)} exactly to confirm")
            duplicates = [draft.contact.email for draft_id, draft in batch if draft_id in read_sent_ids(LOG_PATH)]
            if duplicates:
                raise ValueError("Already sent this message to: " + ", ".join(duplicates))

            # Persist every exact MIME message before the first delivery call.
            batch_path = _save_batch_log(batch)
            service = gmail_service(CREDENTIALS_PATH, TOKEN_PATH)
            sent: list[str] = []
            delivery_path = batch_path / "delivery.jsonl"
            with LOG_PATH.open("a", encoding="utf-8") as log, delivery_path.open(
                "a", encoding="utf-8"
            ) as delivery_log:
                for number, (draft_id, draft) in enumerate(batch, start=1):
                    gmail_id = send_message(service, build_email(draft))
                    record = {
                        "id": draft_id,
                        "gmail_id": gmail_id,
                        "recipient": draft.contact.email,
                        "sent_at": datetime.now(timezone.utc).isoformat(),
                    }
                    log.write(json.dumps(record) + "\n")
                    log.flush()
                    delivery_log.write(json.dumps(record) + "\n")
                    delivery_log.flush()
                    sent.append(draft.contact.email)
                    if number < len(batch):
                        time.sleep(1)
            with _batch_lock:
                _preview_batches.pop(token, None)
            return jsonify({"ok": True, "sent": sent, "logFolder": str(batch_path)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    return app


def main() -> None:
    """Start the dashboard on the local computer only.

    Returns:
        None. This function blocks while Flask serves requests.
    """
    create_app().run(host="127.0.0.1", port=8765, debug=False)


if __name__ == "__main__":
    main()
