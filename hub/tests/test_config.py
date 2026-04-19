"""Tests for hub.config module — TDD tests written before implementation."""

import json
import os
import stat


def test_load_config_returns_defaults_when_no_config_file(tmp_path, monkeypatch):
    """When no config file exists and no env var is set, load_config returns sensible defaults."""
    # Point config home to an empty tmp dir so no real ~/.chorus interferes
    config_dir = tmp_path / ".chorus"
    config_dir.mkdir()

    monkeypatch.delenv("CHORUS_CONFIG", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    from hub.config import load_config

    cfg = load_config(config_dir=config_dir)

    assert cfg.hub_host == "127.0.0.1"
    assert cfg.hub_port == 8799
    assert cfg.discord_token is None  # no env var set
    assert cfg.allowed_senders == []


def test_load_config_reads_from_json_file(tmp_path, monkeypatch):
    """When a config.json file exists in the config dir, its values override defaults."""
    config_dir = tmp_path / ".chorus"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({
        "hub": {
            "host": "0.0.0.0",
            "port": 9000,
            "discord_token_env": "MY_CUSTOM_TOKEN_VAR",
        },
        "defaults": {
            "allowed_senders": ["user123", "user456"],
        },
    }))

    monkeypatch.delenv("CHORUS_CONFIG", raising=False)
    monkeypatch.setenv("MY_CUSTOM_TOKEN_VAR", "fake-discord-token-abc")

    from hub.config import load_config

    cfg = load_config(config_dir=config_dir)

    assert cfg.hub_host == "0.0.0.0"
    assert cfg.hub_port == 9000
    assert cfg.discord_token == "fake-discord-token-abc"
    assert cfg.allowed_senders == ["user123", "user456"]


def test_load_config_uses_chorus_config_env_var(tmp_path, monkeypatch):
    """CHORUS_CONFIG env var overrides the default config file path."""
    # Put the config file in a non-standard location
    custom_config = tmp_path / "custom" / "my-chorus.json"
    custom_config.parent.mkdir(parents=True)
    custom_config.write_text(json.dumps({
        "hub": {
            "host": "10.0.0.1",
            "port": 7777,
        },
    }))

    monkeypatch.setenv("CHORUS_CONFIG", str(custom_config))
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    from hub.config import load_config

    # When CHORUS_CONFIG is set, load_config reads from that path
    # regardless of the config_dir parameter
    cfg = load_config()

    assert cfg.hub_host == "10.0.0.1"
    assert cfg.hub_port == 7777
    assert cfg.allowed_senders == []  # defaults for missing keys


def test_load_or_create_secret_creates_new_file_with_restricted_mode(tmp_path):
    """When no secret file exists, load_or_create_secret creates one with random token and mode 0o600."""
    config_dir = tmp_path / ".chorus"
    config_dir.mkdir()
    secret_path = config_dir / ".secret"

    from hub.config import load_or_create_secret

    token = load_or_create_secret(config_dir=config_dir)

    # Token should be a non-empty string
    assert isinstance(token, str)
    assert len(token) >= 16  # reasonable minimum length for a security token

    # File should have been created
    assert secret_path.exists()

    # File contents should match the returned token
    assert secret_path.read_text().strip() == token

    # File permissions should be owner-only read/write (0o600)
    file_mode = stat.S_IMODE(secret_path.stat().st_mode)
    assert file_mode == 0o600, f"Expected mode 0o600, got {oct(file_mode)}"


def test_load_config_reads_token_from_env_file(tmp_path, monkeypatch):
    """When shell env is unset and .env has DISCORD_BOT_TOKEN, it's used."""
    config_dir = tmp_path / ".chorus"
    config_dir.mkdir()
    (config_dir / ".env").write_text("DISCORD_BOT_TOKEN=token-from-file\n")

    monkeypatch.delenv("CHORUS_CONFIG", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    from hub.config import load_config

    cfg = load_config(config_dir=config_dir)
    assert cfg.discord_token == "token-from-file"


def test_shell_env_wins_over_env_file(tmp_path, monkeypatch):
    """Shell env var beats the .env file when both set the token."""
    config_dir = tmp_path / ".chorus"
    config_dir.mkdir()
    (config_dir / ".env").write_text("DISCORD_BOT_TOKEN=from-file\n")

    monkeypatch.delenv("CHORUS_CONFIG", raising=False)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "from-shell")

    from hub.config import load_config

    cfg = load_config(config_dir=config_dir)
    assert cfg.discord_token == "from-shell"


def test_env_file_ignores_comments_and_blank_lines(tmp_path, monkeypatch):
    config_dir = tmp_path / ".chorus"
    config_dir.mkdir()
    (config_dir / ".env").write_text(
        "# header comment\n"
        "\n"
        "DISCORD_BOT_TOKEN=the-token\n"
        "# trailing\n"
    )
    monkeypatch.delenv("CHORUS_CONFIG", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    from hub.config import load_config

    cfg = load_config(config_dir=config_dir)
    assert cfg.discord_token == "the-token"


def test_env_file_strips_surrounding_quotes(tmp_path, monkeypatch):
    config_dir = tmp_path / ".chorus"
    config_dir.mkdir()
    (config_dir / ".env").write_text('DISCORD_BOT_TOKEN="quoted-value"\n')
    monkeypatch.delenv("CHORUS_CONFIG", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    from hub.config import load_config

    cfg = load_config(config_dir=config_dir)
    assert cfg.discord_token == "quoted-value"


def test_malformed_env_file_is_not_an_error(tmp_path, monkeypatch):
    """A garbled .env file is treated as 'no token', not an exception."""
    config_dir = tmp_path / ".chorus"
    config_dir.mkdir()
    (config_dir / ".env").write_text("this is not a valid dotenv >>> @@@\n")
    monkeypatch.delenv("CHORUS_CONFIG", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    from hub.config import load_config

    cfg = load_config(config_dir=config_dir)
    assert cfg.discord_token is None


def test_env_file_used_when_chorus_config_env_var_set(tmp_path, monkeypatch):
    """When CHORUS_CONFIG points at a custom file, .env next to it is used."""
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    (custom_dir / "chorus.json").write_text("{}")
    (custom_dir / ".env").write_text("DISCORD_BOT_TOKEN=custom-env-file-token\n")

    monkeypatch.setenv("CHORUS_CONFIG", str(custom_dir / "chorus.json"))
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    from hub.config import load_config

    cfg = load_config()
    assert cfg.discord_token == "custom-env-file-token"


def test_load_or_create_secret_reuses_existing_secret(tmp_path):
    """When a secret file already exists, load_or_create_secret returns its contents without overwriting."""
    config_dir = tmp_path / ".chorus"
    config_dir.mkdir()
    secret_path = config_dir / ".secret"

    existing_secret = "my-pre-existing-secret-token-12345"
    secret_path.write_text(existing_secret)
    os.chmod(secret_path, 0o600)

    from hub.config import load_or_create_secret

    token = load_or_create_secret(config_dir=config_dir)

    assert token == existing_secret
    # File should not have been modified
    assert secret_path.read_text() == existing_secret
