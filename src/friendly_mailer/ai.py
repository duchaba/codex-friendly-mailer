from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openai import OpenAI

from .core import Contact


SYSTEM_PROMPT = """You lightly personalize personal email messages.
Preserve every factual claim, date, link, request, promise, and the sender's intent.
Do not invent shared memories, personal facts, urgency, or commitments.
Keep the same tone and approximately the same length. Address the recipient by first name.
Return only the email body in plain text: no subject, commentary, markdown, or code fences."""


def personalize(
    contact: Contact,
    original: str,
    *,
    model: str = "gpt-5.6-luna",
    client: "OpenAI | None" = None,
) -> str:
    if client is None:
        from openai import OpenAI

        api: Any = OpenAI()
    else:
        api = client
    response = api.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=(
            f"Recipient name: {contact.name}\n"
            "Lightly vary the wording of this original message while following all rules:\n\n"
            f"{original}"
        ),
    )
    body = response.output_text.strip()
    if not body:
        raise RuntimeError("The AI returned an empty message")
    return body
