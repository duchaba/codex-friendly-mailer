from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .ai import personalize
from .core import Draft, build_email, load_contacts, message_id, read_sent_ids
from .gmail import gmail_service, send_message


DEFAULT_LIMIT = 50


def load_local_env(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE settings without overriding the shell environment."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        if key and key.replace("_", "").isalnum():
            os.environ.setdefault(key, value)


def parser() -> argparse.ArgumentParser:
    app = argparse.ArgumentParser(description="Personalize and send reviewable emails to friends")
    app.add_argument("contacts", type=Path, help="CSV with name,email columns")
    app.add_argument("message", type=Path, help="UTF-8 text file containing the original message")
    app.add_argument("--subject", required=True, help="Email subject (kept identical for all recipients)")
    app.add_argument("--model", default="gpt-5.6-luna", help="OpenAI model ID")
    app.add_argument(
        "--noai",
        action="store_true",
        help="Skip OpenAI and use the original message, replacing {name} locally",
    )
    app.add_argument("--outbox", type=Path, default=Path("outbox"))
    app.add_argument("--send", action="store_true", help="Send after generating and displaying previews")
    app.add_argument("--yes", action="store_true", help="Skip the final interactive confirmation")
    app.add_argument("--credentials", type=Path, default=Path("credentials.json"))
    app.add_argument("--token", type=Path, default=Path("token.json"))
    app.add_argument("--log", type=Path, default=Path("send-log.jsonl"))
    app.add_argument("--delay", type=float, default=1.0, help="Seconds between sends")
    app.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum contacts per run")
    return app


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        load_local_env()
        contacts = load_contacts(args.contacts)
        original = args.message.read_text(encoding="utf-8").strip()
        if not original:
            raise ValueError("Message file is empty")
        if args.limit < 1 or len(contacts) > min(args.limit, DEFAULT_LIMIT):
            raise ValueError(f"This run has {len(contacts)} contacts; maximum is {min(args.limit, DEFAULT_LIMIT)}")
        if not args.noai and not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("Set OPENAI_API_KEY before running")

        args.outbox.mkdir(parents=True, exist_ok=True)
        drafts: list[tuple[str, Draft]] = []
        for number, contact in enumerate(contacts, start=1):
            if args.noai:
                print(f"Preparing {number}/{len(contacts)} for {contact.name}…", file=sys.stderr)
                body = original.replace("{name}", contact.name.split()[0])
            else:
                print(f"Generating {number}/{len(contacts)} for {contact.name}…", file=sys.stderr)
                body = personalize(contact, original, model=args.model)
            draft = Draft(contact=contact, subject=args.subject, body=body)
            draft_id = message_id(contact, args.subject, original)
            preview_path = args.outbox / f"{number:03d}-{draft_id}.eml"
            preview_path.write_bytes(build_email(draft).as_bytes())
            drafts.append((draft_id, draft))
            print(f"\n--- {contact.name} <{contact.email}> ---\nSubject: {args.subject}\n\n{body}\n")

        print(f"Saved {len(drafts)} preview(s) in {args.outbox.resolve()}")
        if not args.send:
            print("Dry run only. Re-run with --send after reviewing the previews.")
            return 0

        sent_ids = read_sent_ids(args.log)
        duplicates = [draft.contact.email for draft_id, draft in drafts if draft_id in sent_ids]
        if duplicates:
            raise ValueError("Already sent this message to: " + ", ".join(duplicates))
        if not args.credentials.exists():
            raise ValueError(f"Gmail OAuth credentials not found: {args.credentials}")
        if not args.yes:
            answer = input(f"Type SEND {len(drafts)} to send these emails: ").strip()
            if answer != f"SEND {len(drafts)}":
                print("Cancelled; nothing was sent.")
                return 1

        service = gmail_service(args.credentials, args.token)
        with args.log.open("a", encoding="utf-8") as log:
            for number, (draft_id, draft) in enumerate(drafts, start=1):
                gmail_id = send_message(service, build_email(draft))
                record = {
                    "id": draft_id,
                    "gmail_id": gmail_id,
                    "recipient": draft.contact.email,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                }
                log.write(json.dumps(record) + "\n")
                log.flush()
                print(f"Sent {number}/{len(drafts)} to {draft.contact.email}")
                if number < len(drafts):
                    time.sleep(max(0, args.delay))
        return 0
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
