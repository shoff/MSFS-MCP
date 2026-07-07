"""Provider-agnostic structured-JSON LLM call for the companion apps.

Both companion features (the controls advisor and the flight debrief) ask an
LLM for a single schema-constrained JSON object. That call is centralized here
so it can target three kinds of backend, selected by ``MSFS_COMPANION_LLM``:

  anthropic (default) - Claude via the ``anthropic`` SDK.
  openai              - OpenAI (or any hosted OpenAI-compatible API) via ``openai``.
  local               - a locally-run OpenAI-compatible server: Ollama, LM Studio,
                        llama.cpp's server, vLLM, etc. Same code path as ``openai``
                        with a localhost base URL and no API key required. This is
                        how you run a Llama / Mistral / Qwen model with no cloud.

Environment variables
  MSFS_COMPANION_LLM          anthropic | openai | local   (aliases: ollama, llama -> local)
  MSFS_COMPANION_MODEL        model id; sensible per-provider default otherwise
  MSFS_COMPANION_LLM_BASE_URL OpenAI-compatible base URL (local default below)
  ANTHROPIC_API_KEY           credentials for the anthropic provider
  OPENAI_API_KEY              credentials for the openai provider (not needed for local)

Each caller passes its own exception class and no-credentials message so its UI
keeps a domain-specific error type; every failure mode is raised as that class
with a human-readable message.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

@dataclass
class LLMExchange:
    """One request/response with the model — recorded so the UI can show EXACTLY
    what was sent and received (this integration uses a single structured-output
    call, not multi-step tool calls)."""

    provider: str
    model: str
    system: str
    user: str
    schema: dict = field(default_factory=dict)
    response: str = ""
    ok: bool = True
    error: str = ""


HISTORY: list[LLMExchange] = []
MAX_HISTORY = 40


def _record(ex: LLMExchange) -> LLMExchange:
    HISTORY.append(ex)
    del HISTORY[:-MAX_HISTORY]
    return ex


DEFAULT_MODELS = {
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-4o",
    "local": "llama3.1",
}
DEFAULT_LOCAL_BASE_URL = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible endpoint
MAX_TOKENS = 16000

_PROVIDER_ALIASES = {"ollama": "local", "llama": "local", "localhost": "local", "": "anthropic"}


def provider() -> str:
    """The configured backend: 'anthropic' | 'openai' | 'local'."""
    name = os.environ.get("MSFS_COMPANION_LLM", "anthropic").strip().lower()
    name = _PROVIDER_ALIASES.get(name, name)
    return name if name in DEFAULT_MODELS else "anthropic"


def model() -> str:
    """The model id to use (explicit override, else the provider's default)."""
    return os.environ.get("MSFS_COMPANION_MODEL") or DEFAULT_MODELS[provider()]


def model_label() -> str:
    """Human label for the plan/debrief 'source', e.g. 'llama3.1 (local)'."""
    return f"{model()} (local)" if provider() == "local" else model()


# Backward-compatible alias (evaluated at import; prefer model()/model_label()).
MODEL = model()


def have_credentials() -> bool:
    """Whether the configured provider has what it needs to make a call."""
    p = provider()
    if p == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if p == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    return True  # local server needs no key


def no_credentials_msg(fallback_note: str = "") -> str:
    """Provider-appropriate 'set your key' message, plus a caller's fallback note."""
    p = provider()
    if p == "anthropic":
        base = ("No Anthropic credentials found — set ANTHROPIC_API_KEY (or switch to a "
                "local model with MSFS_COMPANION_LLM=local).")
    elif p == "openai":
        base = ("No OpenAI credentials found — set OPENAI_API_KEY (or switch to a local "
                "model with MSFS_COMPANION_LLM=local).")
    else:
        base = ""  # local server needs no key
    return (base + (" " + fallback_note if fallback_note else "")).strip()


# Live observers of AI activity (the AI Activity tab registers one). Called from
# the worker thread on request-start and on completion; keep them cheap/thread-safe.
_LISTENERS: list = []


def add_listener(fn) -> None:
    if fn not in _LISTENERS:
        _LISTENERS.append(fn)


def remove_listener(fn) -> None:
    if fn in _LISTENERS:
        _LISTENERS.remove(fn)


def _notify(ex: LLMExchange) -> None:
    for fn in list(_LISTENERS):
        try:
            fn(ex)
        except Exception:
            pass


def call_json(
    *,
    system: str,
    user: str,
    schema: dict,
    error_cls: type[Exception],
    fallback_note: str = "",
    refusal_msg: str = "The model declined this request.",
    max_tokens: int = MAX_TOKENS,
) -> dict:
    """Blocking LLM call returning a parsed JSON object.

    Run from a worker thread — it blocks on the network. Dispatches to the
    configured provider. Every failure mode is raised as ``error_cls``.
    Records the exchange to HISTORY and notifies live listeners on start and
    completion, so the UI can show exactly what was sent and received.
    """
    creds_msg = no_credentials_msg(fallback_note)
    ex = _record(LLMExchange(provider=provider(), model=model(), system=system,
                             user=user, schema=schema, response="⏳ waiting for the model…"))
    _notify(ex)  # request is visible immediately (live)
    try:
        if provider() == "anthropic":
            result, raw = _call_anthropic(system, user, schema, error_cls, creds_msg, refusal_msg, max_tokens)
        else:
            result, raw = _call_openai_compatible(system, user, schema, error_cls, creds_msg, refusal_msg, max_tokens)
    except Exception as exc:
        ex.ok = False
        ex.error = str(exc)
        ex.response = ""
        _notify(ex)
        raise
    ex.response = raw
    _notify(ex)
    return result


# --------------------------------------------------------------- Anthropic
def _call_anthropic(system, user, schema, error_cls, no_credentials_msg, refusal_msg, max_tokens):
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
            model=model(),
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
    return json.loads(text), text


# ------------------------------------------- OpenAI / local (OpenAI-compatible)
def _call_openai_compatible(system, user, schema, error_cls, no_credentials_msg, refusal_msg, max_tokens):
    p = provider()
    if not have_credentials():
        raise error_cls(no_credentials_msg)

    try:
        import openai
    except ImportError as exc:
        raise error_cls(
            "The 'openai' package is not installed (needed for the openai/local "
            "providers). Run: pip install openai"
        ) from exc

    base_url = os.environ.get("MSFS_COMPANION_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    if p == "local":
        base_url = base_url or DEFAULT_LOCAL_BASE_URL
    api_key = os.environ.get("OPENAI_API_KEY") or ("ollama" if p == "local" else None)
    client = openai.OpenAI(base_url=base_url, api_key=api_key)

    # OpenAI enforces the schema natively (strict json_schema). Local servers
    # vary in schema support, so ask for a JSON object and pin the shape in the
    # prompt — robust across Ollama / LM Studio / llama.cpp.
    if p == "openai":
        system_msg = system
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "companion_result", "schema": schema, "strict": True},
        }
    else:
        system_msg = system + "\n\n" + _schema_instruction(schema)
        response_format = {"type": "json_object"}

    base_kwargs = dict(
        model=model(),
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user},
        ],
        response_format=response_format,
    )
    # Newer OpenAI models reject `max_tokens` and require `max_completion_tokens`;
    # older ones and most local servers want `max_tokens`. Prefer the right one
    # per provider and fall back to the other if the API asks for it.
    prefer = "max_completion_tokens" if p == "openai" else "max_tokens"
    try:
        response = _create_with_token_fallback(client, openai, base_kwargs, max_tokens, prefer)
    except openai.AuthenticationError as exc:
        raise error_cls("The LLM API key was rejected — check OPENAI_API_KEY.") from exc
    except openai.APIConnectionError as exc:
        raise error_cls(_connection_msg(p, base_url)) from exc
    except openai.BadRequestError as exc:
        raise error_cls(f"The model rejected the request: {exc}") from exc

    choice = response.choices[0]
    if getattr(choice.message, "refusal", None):
        raise error_cls(refusal_msg)
    content = choice.message.content
    if not content:
        raise error_cls("The model returned an empty response.")
    return _extract_json(content, error_cls), content


def _create_with_token_fallback(client, openai, base_kwargs, max_tokens, prefer):
    """Call chat.completions with the preferred token-limit parameter, retrying
    once with the other name if the model reports it as unsupported."""
    other = "max_completion_tokens" if prefer == "max_tokens" else "max_tokens"
    kwargs = dict(base_kwargs)
    kwargs[prefer] = max_tokens
    try:
        return client.chat.completions.create(**kwargs)
    except openai.BadRequestError as exc:
        msg = str(exc).lower()
        if other in msg and ("unsupported" in msg or "not supported" in msg or "instead" in msg):
            kwargs.pop(prefer, None)
            kwargs[other] = max_tokens
            return client.chat.completions.create(**kwargs)
        raise


def _schema_instruction(schema: dict) -> str:
    return (
        "Respond with ONLY a single JSON object conforming to this JSON Schema. "
        "No prose, no explanation, no markdown code fences.\n"
        "JSON Schema:\n" + json.dumps(schema)
    )


def _connection_msg(p: str, base_url: str | None) -> str:
    if p == "local":
        return (
            f"Could not reach a local LLM server at {base_url or DEFAULT_LOCAL_BASE_URL}. "
            "Is it running? (e.g. `ollama serve` and `ollama pull llama3.1`)."
        )
    return "Could not reach the LLM API — check your connection."


def _extract_json(text: str, error_cls: type[Exception]) -> dict:
    """Parse a JSON object, tolerating markdown fences or surrounding prose
    that smaller local models sometimes emit despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise error_cls("The model did not return valid JSON.") from None
