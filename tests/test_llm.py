"""Provider-agnostic LLM helper: selection, dispatch, and JSON extraction.

No network: the openai/anthropic SDKs are stubbed via sys.modules so we can
assert exactly what each provider path sends and how it parses the reply.
"""

import sys
import types

import pytest

from companion_common import llm


class Boom(Exception):
    pass


# --------------------------------------------------------------- selection
def test_provider_defaults_and_aliases(monkeypatch):
    monkeypatch.delenv("MSFS_COMPANION_LLM", raising=False)
    monkeypatch.delenv("MSFS_COMPANION_MODEL", raising=False)
    assert llm.provider() == "anthropic"
    assert llm.model() == "claude-opus-4-8"
    for alias in ("ollama", "llama", "local", "LOCALHOST"):
        monkeypatch.setenv("MSFS_COMPANION_LLM", alias)
        assert llm.provider() == "local"
        assert llm.model_label() == "llama3.1 (local)"
    monkeypatch.setenv("MSFS_COMPANION_LLM", "nonsense")
    assert llm.provider() == "anthropic"  # unknown -> safe default


def test_model_override_wins(monkeypatch):
    monkeypatch.setenv("MSFS_COMPANION_LLM", "openai")
    monkeypatch.setenv("MSFS_COMPANION_MODEL", "gpt-5-turbo")
    assert llm.model() == "gpt-5-turbo"
    assert llm.model_label() == "gpt-5-turbo"


def test_credentials_by_provider(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MSFS_COMPANION_LLM", "anthropic")
    assert not llm.have_credentials()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert llm.have_credentials()
    monkeypatch.setenv("MSFS_COMPANION_LLM", "openai")
    assert not llm.have_credentials()
    monkeypatch.setenv("MSFS_COMPANION_LLM", "local")
    assert llm.have_credentials()  # local needs no key


# ----------------------------------------------------------- JSON extraction
def test_extract_json_tolerates_fences_and_prose():
    assert llm._extract_json('{"a": 1}', Boom) == {"a": 1}
    assert llm._extract_json('```json\n{"a": 1}\n```', Boom) == {"a": 1}
    assert llm._extract_json('Sure! Here you go:\n{"a": 1}\nHope that helps.', Boom) == {"a": 1}
    with pytest.raises(Boom):
        llm._extract_json("not json at all", Boom)


# ------------------------------------------------ openai / local dispatch
def _install_fake_openai(monkeypatch, captured, *, content='{"ok": true}', refusal=None, raise_kind=None):
    mod = types.ModuleType("openai")

    class AuthenticationError(Exception):
        pass

    class APIConnectionError(Exception):
        pass

    class BadRequestError(Exception):
        pass

    mod.AuthenticationError = AuthenticationError
    mod.APIConnectionError = APIConnectionError
    mod.BadRequestError = BadRequestError

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            captured["_last_create"] = dict(kwargs)  # just this call's kwargs
            if raise_kind == "auth":
                raise AuthenticationError("bad key")
            if raise_kind == "conn":
                raise APIConnectionError("no server")
            # emulate a newer OpenAI model rejecting max_tokens
            if raise_kind == "token" and "max_tokens" in kwargs:
                raise BadRequestError(
                    "Unsupported parameter: 'max_tokens' is not supported with this model. "
                    "Use 'max_completion_tokens' instead."
                )
            msg = types.SimpleNamespace(content=content, refusal=refusal)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    class OpenAI:
        def __init__(self, base_url=None, api_key=None):
            captured["base_url"] = base_url
            captured["api_key"] = api_key
            self.chat = types.SimpleNamespace(completions=_Completions())

    mod.OpenAI = OpenAI
    monkeypatch.setitem(sys.modules, "openai", mod)
    return mod


def test_local_provider_hits_localhost_with_json_object(monkeypatch):
    monkeypatch.setenv("MSFS_COMPANION_LLM", "local")
    monkeypatch.delenv("MSFS_COMPANION_MODEL", raising=False)
    monkeypatch.delenv("MSFS_COMPANION_LLM_BASE_URL", raising=False)
    captured = {}
    _install_fake_openai(monkeypatch, captured, content='{"summary": "hi"}')

    out = llm.call_json(system="sys", user="u", schema={"type": "object"}, error_cls=Boom)
    assert out == {"summary": "hi"}
    assert captured["base_url"] == llm.DEFAULT_LOCAL_BASE_URL
    assert captured["model"] == "llama3.1"
    assert captured["response_format"] == {"type": "json_object"}
    # the schema is pinned into the system prompt for schema-agnostic servers
    assert "JSON Schema" in captured["messages"][0]["content"]


def test_token_param_fallback_for_newer_models(monkeypatch):
    # A model that rejects max_tokens and demands max_completion_tokens must be
    # handled transparently (this is the "Error code: 400 ... use
    # max_completion_tokens" the user hit).
    monkeypatch.setenv("MSFS_COMPANION_LLM", "local")  # prefers max_tokens first
    captured = {}
    _install_fake_openai(monkeypatch, captured, content='{"ok": true}', raise_kind="token")
    out = llm.call_json(system="s", user="u", schema={"type": "object"}, error_cls=Boom)
    assert out == {"ok": True}
    last = captured["_last_create"]
    assert "max_completion_tokens" in last and "max_tokens" not in last


def test_openai_provider_uses_strict_json_schema(monkeypatch):
    monkeypatch.setenv("MSFS_COMPANION_LLM", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MSFS_COMPANION_MODEL", raising=False)
    captured = {}
    _install_fake_openai(monkeypatch, captured, content='{"ok": true}')

    out = llm.call_json(system="sys", user="u", schema={"type": "object"}, error_cls=Boom)
    assert out == {"ok": True}
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["api_key"] == "sk-test"


def test_openai_missing_key_raises_caller_error(monkeypatch):
    monkeypatch.setenv("MSFS_COMPANION_LLM", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(Boom) as exc:
        llm.call_json(system="s", user="u", schema={"type": "object"},
                      error_cls=Boom, fallback_note="Keep the default.")
    assert "OPENAI_API_KEY" in str(exc.value) and "Keep the default." in str(exc.value)


def test_local_connection_error_names_the_server(monkeypatch):
    monkeypatch.setenv("MSFS_COMPANION_LLM", "local")
    captured = {}
    _install_fake_openai(monkeypatch, captured, raise_kind="conn")
    with pytest.raises(Boom) as exc:
        llm.call_json(system="s", user="u", schema={"type": "object"}, error_cls=Boom)
    assert "local LLM server" in str(exc.value)


def test_refusal_raises_refusal_message(monkeypatch):
    monkeypatch.setenv("MSFS_COMPANION_LLM", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured = {}
    _install_fake_openai(monkeypatch, captured, content=None, refusal="I cannot help with that")
    with pytest.raises(Boom) as exc:
        llm.call_json(system="s", user="u", schema={"type": "object"},
                      error_cls=Boom, refusal_msg="declined, keeping default")
    assert "declined" in str(exc.value)
