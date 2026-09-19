"""Gmail OAuth authentication and email-delivery helpers.

The application requests only the ``gmail.send`` scope. It cannot read,
modify, or delete mailbox content when authorized with a fresh token created
by this module.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def gmail_service(credentials_path: Path, token_path: Path):
    """Create an authenticated Gmail API service.

    Existing OAuth credentials are loaded from ``token_path``. Expired access
    tokens are refreshed when possible; otherwise Google's installed-app OAuth
    browser flow is started and the resulting credentials are stored locally.
    Google libraries are imported lazily so preview-only operation has no Gmail
    initialization overhead.

    Args:
        credentials_path: Google Desktop-app OAuth client JSON downloaded from
            Google Cloud Console.
        token_path: Location used to load and persist user authorization.

    Returns:
        A Google API discovery service configured for Gmail API version 1.

    Raises:
        OSError: If credential files cannot be read or the token cannot be
            written.
        ValueError: If OAuth JSON is malformed or incompatible.
        google.auth.exceptions.GoogleAuthError: If authorization or token
            refresh fails.
    """
    # Lazy imports keep dry runs independent of Google client initialization.
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    credentials = None
    # Reuse a local refresh token when one has already been authorized.
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            # Refresh silently when Google supplied a reusable refresh token.
            credentials.refresh(Request())
        else:
            # A first-time authorization opens the system browser and requests
            # only permission to send mail.
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            credentials = flow.run_local_server(port=0)
        token_path.write_text(credentials.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def send_message(service, message: EmailMessage) -> str:
    """Send one MIME email through the authenticated Gmail account.

    Args:
        service: Authenticated Gmail API discovery service returned by
            :func:`gmail_service`.
        message: Fully constructed MIME email to deliver.

    Returns:
        Gmail's unique message identifier for the accepted email.

    Raises:
        googleapiclient.errors.HttpError: If Gmail rejects the API request.
        KeyError: If Gmail returns a response without a message ``id``.
    """
    # Gmail expects the complete RFC 2822 message as URL-safe base64 text.
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return result["id"]
