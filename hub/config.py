"""Chorus Hub configuration loading and shared secret management."""

import json
import os
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_CONFIG_DIR = Path.home() / ".chorus"
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8799
_DEFAULT_TOKEN_ENV = "DISCORD_BOT_TOKEN"


@dataclass
class ChorusConfig:
    hub_host: str = _DEFAULT_HOST
    hub_port: int = _DEFAULT_PORT
    discord_token: str | None = None
    allowed_senders: list[str] = field(default_factory=list)


def resolve_config_dir() -> Path:
    """Directory that holds ``.env``, ``.secret``, and ``config.json``.

    Respects ``CHORUS_CONFIG`` (taking its parent) when set; otherwise falls
    back to ``~/.chorus``.
    """
    chorus_config_env = os.environ.get("CHORUS_CONFIG")
    if chorus_config_env:
        return Path(chorus_config_env).parent
    return _DEFAULT_CONFIG_DIR


def write_dotenv_value(path: Path, key: str, value: str) -> None:
    """Upsert ``key=value`` in a dotenv file; chmod 0600.

    Preserves other lines (including comments) in order. Duplicate lines
    for the same key collapse into a single updated line. Creates the
    parent directory if missing.
    """
    existing: list[str] = []
    if path.exists():
        try:
            existing = path.read_text().splitlines()
        except (OSError, UnicodeDecodeError):
            existing = []

    new_lines: list[str] = []
    replaced = False
    for line in existing:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, _ = stripped.partition("=")
            if k.strip() == key:
                if not replaced:
                    new_lines.append(f"{key}={value}")
                    replaced = True
                continue
        new_lines.append(line)
    if not replaced:
        new_lines.append(f"{key}={value}")

    content = "\n".join(new_lines)
    if not content.endswith("\n"):
        content += "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600


def _read_dotenv_value(path: Path, key: str) -> str | None:
    """Best-effort dotenv read. Returns the value for ``key`` or ``None``.

    A missing file, unreadable file, or malformed content is treated as
    "not configured" — callers want graceful fallback, not an exception.
    """
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        k, _, v = stripped.partition("=")
        if k.strip() == key:
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            return v
    return None


def load_config(config_dir: Path | None = None) -> ChorusConfig:
    """Load configuration from config.json file with sensible defaults.

    Resolution order:
    1. CHORUS_CONFIG env var (full path to a JSON file)
    2. config_dir / config.json (config_dir defaults to ~/.chorus)
    3. Built-in defaults
    """
    chorus_config_env = os.environ.get("CHORUS_CONFIG")

    if chorus_config_env:
        config_path = Path(chorus_config_env)
    else:
        if config_dir is None:
            config_dir = _DEFAULT_CONFIG_DIR
        config_path = config_dir / "config.json"

    data: dict = {}
    if config_path.exists():
        data = json.loads(config_path.read_text())

    hub_section = data.get("hub", {})
    defaults_section = data.get("defaults", {})

    host = hub_section.get("host", _DEFAULT_HOST)
    port = hub_section.get("port", _DEFAULT_PORT)
    token_env = hub_section.get("discord_token_env", _DEFAULT_TOKEN_ENV)
    allowed = defaults_section.get("allowed_senders", [])

    discord_token = os.environ.get(token_env)
    if discord_token is None:
        env_file = config_path.parent / ".env"
        discord_token = _read_dotenv_value(env_file, "DISCORD_BOT_TOKEN")

    return ChorusConfig(
        hub_host=host,
        hub_port=port,
        discord_token=discord_token,
        allowed_senders=allowed,
    )


def load_or_create_secret(config_dir: Path | None = None) -> str:
    """Load or create the shared bearer token secret.

    If ~/.chorus/.secret exists, read and return its contents.
    Otherwise, generate a random token, write it with mode 0o600, and return it.
    """
    if config_dir is None:
        config_dir = _DEFAULT_CONFIG_DIR

    secret_path = config_dir / ".secret"

    if secret_path.exists():
        return secret_path.read_text().strip()

    token = secrets.token_urlsafe(32)
    secret_path.write_text(token)
    os.chmod(secret_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    return token
