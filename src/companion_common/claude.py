"""Shared Claude (Anthropic) structured-JSON call for the companion apps.

Both the controls advisor and the flight debrief ask Claude for a single
schema-constrained JSON object. The boilerplate around that — the import
guard, the credential check, the ``messages.create`` call, error translation,
the refusal check and text extraction — was duplicated in both. It lives here
once. Each caller passes its own exception class so its UI keeps a
domain-specific error type, and its own no-credentials message.

The model is env-configurable (``MSFS_COMPANION_MODEL``) so it can be pointed
at a newer model without a code change.
"""

from __future__ import annotations

import json
import os

# The model both companion features use. Override with MSFS_COMPANION_MODEL.
MODEL = os.environ.get("MSFS_COMPANION_MODEL", "claude-opus-4-8")

MAX_TOKENS = 16000


def have_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def call_json(
    *,
    system: str,
    user: str,
    schema: dict,
    error_cls: type[Exception],
    no_credentials_msg: str,
    refusal_msg: str = "Claude declined this request.",
    max_tokens: int = MAX_TOKENS,
) -> dict:
    """Blocking Claude call returning a parsed JSON object.

    Run from a worker thread — it blocks on the network. Every failure mode
    (missing package, missing/rejected credentials, connection error, refusal)
    is raised as ``error_cls`` carrying a human-readable message.
    """
    try:
        import anthropic
    except ImportError as exc:
        raise error_cls(
            "The 'anthropic' package is not installed. Run: pip install anthropic"
        ) from exc

    if not have_credentials():
        raise error_cls(no_credentials_msg)

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.AuthenticationError as exc:
        raise error_cls("Anthropic API key was rejected — check ANTHROPIC_API_KEY.") from exc
    except anthropic.APIConnectionError as exc:
        raise error_cls("Could not reach the Anthropic API — check your connection.") from exc

    if response.stop_reason == "refusal":
        raise error_cls(refusal_msg)
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)
