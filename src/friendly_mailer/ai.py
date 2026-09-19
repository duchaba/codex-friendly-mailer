"""OpenAI-backed message personalization for Friendly Mailer.

This module contains the only application code that submits message content to
OpenAI. Importing the module does not create a client or perform network I/O;
the SDK is imported lazily when :func:`personalize` is called.
"""

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
    """Create a lightly rewritten email body for one recipient.

    The system prompt asks the model to retain facts, dates, links, promises,
    and intent. The response is expected to contain only plain-text body copy.

    Args:
        contact: Recipient whose name may be used to personalize the message.
        original: Original plain-text email body to rewrite.
        model: OpenAI model identifier used by the Responses API.
        client: Optional preconfigured OpenAI client. Supplying a client is
            useful for dependency injection and tests. When omitted, a client
            is created using the standard ``OPENAI_API_KEY`` environment
            variable.

    Returns:
        The model-generated email body with surrounding whitespace removed.

    Raises:
        RuntimeError: If the model response contains no body text.
        openai.OpenAIError: If authentication, quota, connection, or API
            processing fails.
    """
    # Delay the SDK import until AI mode is actually used. This lets --noai
    # operate without importing or configuring the OpenAI dependency.
    if client is None:
        from openai import OpenAI

        api: Any = OpenAI()
    else:
        api = client
    # Instructions and user content are passed separately so the original
    # message cannot accidentally replace the preservation requirements.
    response = api.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=(
            f"Recipient name: {contact.name}\n"
            "Lightly vary the wording of this original message while following all rules:\n\n"
            f"{original}"
        ),
    )
    # An empty result is not a valid email draft and must never reach Gmail.
    body = response.output_text.strip()
    if not body:
        raise RuntimeError("The AI returned an empty message")
    return body
