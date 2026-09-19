# Friendly Mailer

A review-first command-line app that lightly varies a personal message for each friend with the OpenAI API, then sends approved drafts through your Gmail account. It uses Gmail OAuth; your Gmail password is never requested or stored.

Use this only for people who reasonably expect to hear from you. It intentionally caps each run at 50 recipients and refuses to resend the same source message to the same address.

## Setup

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
export OPENAI_API_KEY="your-api-key"
```

For Gmail:

1. In Google Cloud Console, create or select a project.
2. Enable the Gmail API.
3. Configure the OAuth consent screen.
4. Create an OAuth client ID of type **Desktop app**.
5. Download its JSON file into this directory as `credentials.json`.

The first send opens Google's consent page. The resulting refresh token is stored locally as `token.json`. Both credential files are ignored by Git. The app requests only permission to send mail—not to read, delete, or manage it.

## Prepare input

Create a CSV with exactly the required `name` and `email` headers (additional columns are ignored):

```csv
name,email
Alex,alex@example.com
Sam,sam@example.com
```

Put the original message in a UTF-8 text file. The subject is provided separately and is not AI-generated.

## Preview, then send

Start with a dry run:

```bash
friendly-mailer contacts.csv message.txt --subject "Checking in"
```

Every draft is printed and saved as an `.eml` file in `outbox/`. Review those files. When satisfied, generate a fresh set and send it:

```bash
friendly-mailer contacts.csv message.txt --subject "Checking in" --send
```

At the prompt, type the exact confirmation shown. Add `--yes` only for intentional non-interactive use. Other useful options:

```bash
friendly-mailer --help
friendly-mailer contacts.csv message.txt --subject "Hello" --model gpt-5.6-luna --delay 2
```

The default model is `gpt-5.6-luna`, chosen for a lightweight rewriting task. Override it with `--model`. If generation or sending fails, the command exits nonzero. Successful sends are appended to `send-log.jsonl`, which prevents accidental duplicate sends.

To skip OpenAI and use the original message without AI rewriting, add `--noai`. Any `{name}` placeholder is replaced locally with the recipient's first name, and no contact or message data is sent to OpenAI:

```bash
friendly-mailer contacts.csv message.txt --subject "Checking in" --noai
friendly-mailer contacts.csv message.txt --subject "Checking in" --noai --send
```

## Security notes

- Never commit `credentials.json`, `token.json`, `.env`, or the outbox.
- Revoke access at any time from your Google Account's third-party connections page.
- Drafts can contain private text. Delete `outbox/` when you no longer need the previews.
- Test first with your own email address.
