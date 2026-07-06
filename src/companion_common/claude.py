"""Backward-compatible alias for the provider-agnostic LLM helper.

The companion apps originally called Claude directly through this module; it
now supports OpenAI and local (Llama-style) backends too. The real
implementation lives in ``companion_common.llm``; this re-exports it so any
older import of ``companion_common.claude`` keeps working.
"""

from __future__ import annotations

from .llm import (  # noqa: F401
    MAX_TOKENS,
    MODEL,
    call_json,
    have_credentials,
    model,
    model_label,
    provider,
)
