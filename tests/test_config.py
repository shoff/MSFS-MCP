"""Config-file loading for LLM settings (no OS env vars required)."""

from companion_common import config, llm


SAMPLE = """
# a comment
; another comment
provider = openai
model = "gpt-4o-mini"
openai_api_key = sk-from-file
unknown_key = ignored
blank_value =
"""


def test_parse_maps_known_keys_and_ignores_the_rest():
    parsed = config.parse(SAMPLE)
    assert parsed == {
        "MSFS_COMPANION_LLM": "openai",
        "MSFS_COMPANION_MODEL": "gpt-4o-mini",  # quotes stripped
        "OPENAI_API_KEY": "sk-from-file",
    }
    assert "unknown_key" not in parsed  # unrecognized keys dropped
    # blank value produces no entry


def test_apply_fills_env_and_drives_provider(monkeypatch, tmp_path):
    for name in config.KEY_TO_ENV.values():
        monkeypatch.delenv(name, raising=False)
    conf = tmp_path / "msfs-companion.conf"
    conf.write_text("provider = local\nmodel = llama3.2\n")

    used = config.apply(conf)
    assert used == conf
    assert llm.provider() == "local"
    assert llm.model() == "llama3.2"


def test_real_env_var_overrides_the_file(monkeypatch, tmp_path):
    monkeypatch.delenv("MSFS_COMPANION_MODEL", raising=False)
    monkeypatch.setenv("MSFS_COMPANION_LLM", "anthropic")  # explicit env set first
    conf = tmp_path / "msfs-companion.conf"
    conf.write_text("provider = openai\n")

    config.apply(conf)
    assert llm.provider() == "anthropic"  # env wins over the file (setdefault)


def test_find_config_prefers_explicit_path(monkeypatch, tmp_path):
    explicit = tmp_path / "custom.conf"
    explicit.write_text("provider = openai\n")
    monkeypatch.setenv(config.CONFIG_ENV, str(explicit))
    assert config.find_config() == explicit


def test_apply_is_a_noop_without_a_file(monkeypatch, tmp_path):
    monkeypatch.delenv(config.CONFIG_ENV, raising=False)
    monkeypatch.chdir(tmp_path)  # no conf here
    monkeypatch.setattr(config, "HOME_CONFIG", tmp_path / "nope" / "config.conf")
    assert config.apply() is None
