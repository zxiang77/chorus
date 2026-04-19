"""Tests for the `chorus configure` CLI command."""

import json
import stat

from click.testing import CliRunner


def _config_setup(tmp_path, monkeypatch):
    """Point CHORUS_CONFIG at a tmp config.json so .env lives in tmp_path."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({}))
    monkeypatch.setenv("CHORUS_CONFIG", str(config_file))
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    return config_file


def test_configure_save_writes_token_to_env_file(tmp_path, monkeypatch):
    _config_setup(tmp_path, monkeypatch)
    from hub.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["configure", "MTIzNGFiY2Q="])

    assert result.exit_code == 0, result.output
    env_file = tmp_path / ".env"
    assert env_file.exists()
    assert "DISCORD_BOT_TOKEN=MTIzNGFiY2Q=" in env_file.read_text()


def test_configure_save_sets_mode_0600(tmp_path, monkeypatch):
    _config_setup(tmp_path, monkeypatch)
    from hub.main import cli

    runner = CliRunner()
    runner.invoke(cli, ["configure", "abc"])

    env_file = tmp_path / ".env"
    mode = stat.S_IMODE(env_file.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_configure_save_preserves_other_keys(tmp_path, monkeypatch):
    _config_setup(tmp_path, monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("# header\nOTHER=keep-me\n")

    from hub.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["configure", "new-token"])

    assert result.exit_code == 0, result.output
    content = env_file.read_text()
    assert "OTHER=keep-me" in content
    assert "DISCORD_BOT_TOKEN=new-token" in content
    assert "# header" in content


def test_configure_save_replaces_existing_token(tmp_path, monkeypatch):
    _config_setup(tmp_path, monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("DISCORD_BOT_TOKEN=old-token\nOTHER=keep\n")

    from hub.main import cli

    runner = CliRunner()
    runner.invoke(cli, ["configure", "new-token"])

    content = env_file.read_text()
    assert "old-token" not in content
    assert "DISCORD_BOT_TOKEN=new-token" in content
    assert "OTHER=keep" in content


def test_configure_save_trims_whitespace_on_token(tmp_path, monkeypatch):
    _config_setup(tmp_path, monkeypatch)
    from hub.main import cli

    runner = CliRunner()
    runner.invoke(cli, ["configure", "  padded-token  "])

    content = (tmp_path / ".env").read_text()
    assert "DISCORD_BOT_TOKEN=padded-token" in content


def test_configure_save_echoes_confirmation(tmp_path, monkeypatch):
    _config_setup(tmp_path, monkeypatch)
    from hub.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["configure", "MTIzNGFiY2Q="])
    assert "saved" in result.output.lower() or "configured" in result.output.lower()
    # Do NOT leak the full token in stdout
    assert "MTIzNGFiY2Q=" not in result.output
