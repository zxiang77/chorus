"""Tests for hub.main CLI module — TDD tests written before implementation."""

import json
from unittest.mock import patch

from click.testing import CliRunner


def test_connect_prints_channel_launch_command():
    """connect must print the launch command with --dangerously-load-development-channels.

    During the research preview, custom channels require this flag to bypass
    the approved allowlist. The server:chorus-relay syntax references the MCP
    server name from the installed plugin's .mcp.json.
    """
    from hub.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["connect", "1485159010754887800"])

    assert result.exit_code == 0, result.output
    assert "CHORUS_CHANNEL=1485159010754887800" in result.output
    assert "--dangerously-load-development-channels" in result.output
    assert "server:chorus-relay" in result.output


def test_allow_adds_user_id_to_config_allowed_senders(tmp_path, monkeypatch):
    """chorus allow <user_id> reads config, appends user_id to allowed_senders, and writes it back."""
    from hub.main import cli

    # Set up a config directory with an existing config.json
    config_dir = tmp_path / ".chorus"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({
        "hub": {"host": "127.0.0.1", "port": 8799},
        "defaults": {"allowed_senders": ["existing_user_111"]},
    }))

    # Point CHORUS_CONFIG to our tmp config file so the allow command uses it
    monkeypatch.setenv("CHORUS_CONFIG", str(config_file))

    runner = CliRunner()
    result = runner.invoke(cli, ["allow", "new_user_222"])

    assert result.exit_code == 0

    # Read the config file back and verify user was added
    updated_config = json.loads(config_file.read_text())
    allowed = updated_config["defaults"]["allowed_senders"]
    assert "new_user_222" in allowed
    # Original user should still be there
    assert "existing_user_111" in allowed
    assert len(allowed) == 2


def test_status_fetches_and_displays_active_sessions(monkeypatch):
    """chorus status makes an HTTP GET to /status and displays the active sessions."""
    from hub.main import cli

    # Mock the HTTP call that status makes to the Hub's /status endpoint.
    # The status command should read the secret and Hub URL from config,
    # then GET /status and display the result.
    fake_status_response = {
        "count": 2,
        "routes": {
            "channel_111": {
                "port": 9001,
                "session_id": "sess-aaa",
                "registered_at": "2026-03-25T10:00:00",
            },
            "channel_222": {
                "port": 9002,
                "session_id": "sess-bbb",
                "registered_at": "2026-03-25T11:00:00",
            },
        },
    }

    # Mock the internal _fetch_status helper so the test doesn't need a
    # running Hub server.  The implementer should expose a _fetch_status()
    # function in hub.main that performs the HTTP GET and returns a dict.
    with patch("hub.main._fetch_status", return_value=fake_status_response):
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0
    output = result.output
    # Should show session count or individual channels
    assert "channel_111" in output or "2" in output
    # Should display at least one channel ID
    assert "channel_111" in output
    assert "channel_222" in output


def test_hub_command_calls_startup_orchestration_in_order():
    """chorus hub calls load_config, load_or_create_secret, create_app with callbacks, ChorusBot, and asyncio.run.

    This verifies that the hub command wires together all components in the
    correct order: config first, then secret, then app + bot, then run the
    async event loop. The current hub command is a placeholder that just prints
    a message — this test will fail until the real startup is implemented.

    Implementation note for hub.main: add these imports:
        from hub.config import load_or_create_secret
        from hub.router import create_app
        from hub.bot import ChorusBot
        import asyncio
    """
    import hub.main as hub_main_module
    from hub.main import cli

    # Gate: verify the hub module has the necessary imports for startup.
    # If these attributes don't exist, the feature is not yet implemented.
    required_attrs = ["load_or_create_secret", "create_app", "ChorusBot"]
    missing = [attr for attr in required_attrs if not hasattr(hub_main_module, attr)]
    assert not missing, (
        f"hub.main is missing imports for startup orchestration: {missing}. "
        f"The hub command must import load_or_create_secret from hub.config, "
        f"create_app from hub.router, and ChorusBot from hub.bot."
    )

    # If we get past the gate, test the full orchestration with mocks.
    from unittest.mock import MagicMock, patch

    fake_config = MagicMock()
    fake_config.hub_host = "127.0.0.1"
    fake_config.hub_port = 8799
    fake_config.discord_token = "fake-discord-token"
    fake_secret = "test-secret-abc"
    fake_app = MagicMock()
    fake_app.__getitem__ = MagicMock(return_value={})  # app["routes_table"]
    fake_bot = MagicMock()

    call_order = []

    def track_load_config(*a, **kw):
        call_order.append("load_config")
        return fake_config

    def track_load_or_create_secret(*a, **kw):
        call_order.append("load_or_create_secret")
        return fake_secret

    def track_create_app(*a, **kw):
        call_order.append("create_app")
        return fake_app

    def track_chorus_bot(*a, **kw):
        call_order.append("ChorusBot")
        return fake_bot

    def track_asyncio_run(*a, **kw):
        call_order.append("asyncio.run")

    with (
        patch("hub.main.load_config", side_effect=track_load_config) as mock_cfg,
        patch("hub.main.load_or_create_secret", side_effect=track_load_or_create_secret) as mock_secret,
        patch("hub.main.create_app", side_effect=track_create_app) as mock_app,
        patch("hub.main.ChorusBot", side_effect=track_chorus_bot) as mock_bot,
        patch("hub.main.asyncio.run", side_effect=track_asyncio_run) as mock_run,
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["hub"])

    assert result.exit_code == 0, f"CLI failed: {result.output}"

    # Verify all components were called
    assert mock_cfg.called, \
        "hub command must call load_config() to get configuration"
    assert mock_secret.called, \
        "hub command must call load_or_create_secret() to get the Bearer token"
    assert mock_app.called, \
        "hub command must call create_app() to create the HTTP router"
    assert mock_bot.called, \
        "hub command must call ChorusBot() to create the Discord bot"
    assert mock_run.called, \
        "hub command must call asyncio.run() to start the async event loop"

    # Verify orchestration order: config and secret before app and bot,
    # and asyncio.run last
    assert call_order.index("load_config") < call_order.index("create_app"), \
        "load_config must be called before create_app"
    assert call_order.index("load_or_create_secret") < call_order.index("create_app"), \
        "load_or_create_secret must be called before create_app"
    assert call_order.index("create_app") < call_order.index("asyncio.run"), \
        "create_app must be called before asyncio.run"
    assert call_order.index("ChorusBot") < call_order.index("asyncio.run"), \
        "ChorusBot must be created before asyncio.run"

    # Verify create_app receives the secret
    app_call_args = mock_app.call_args
    assert app_call_args[0][0] == fake_secret or app_call_args[1].get("secret") == fake_secret, \
        "create_app must receive the shared secret"


def test_fetch_status_sends_bearer_auth_header(tmp_path, monkeypatch):
    """_fetch_status reads the shared secret and includes it as a Bearer token in the HTTP request.

    The current implementation does NOT include the Bearer token — this test
    will fail until the auth header is added to _fetch_status.
    """
    from unittest.mock import MagicMock, patch

    from hub.main import _fetch_status

    # Set up a config dir with a .secret file containing a known token
    config_dir = tmp_path / ".chorus"
    config_dir.mkdir()
    secret_file = config_dir / ".secret"
    secret_file.write_text("my-test-secret-token")

    # Also create a config.json so load_config works
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({
        "hub": {"host": "127.0.0.1", "port": 8799},
    }))
    monkeypatch.setenv("CHORUS_CONFIG", str(config_file))

    # Mock urlopen to capture the Request object and inspect its headers.
    # Also mock load_or_create_secret at the source module so that when
    # _fetch_status calls it, it returns our known token. Currently
    # _fetch_status does NOT call load_or_create_secret at all, so the
    # Authorization header will be missing — that is the expected TDD failure.
    captured_requests = []

    def fake_urlopen(req):
        captured_requests.append(req)
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok", "count": 0, "routes": {}}'
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with (
        patch("hub.config.load_or_create_secret", return_value="my-test-secret-token"),
        patch("urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        _fetch_status()

    # Verify the request was made
    assert len(captured_requests) == 1, "Expected exactly one HTTP request"

    req = captured_requests[0]
    auth_header = req.get_header("Authorization")
    assert auth_header is not None, \
        "_fetch_status must include an Authorization header in the HTTP request"
    assert auth_header == "Bearer my-test-secret-token", \
        f"Expected 'Bearer my-test-secret-token', got '{auth_header}'"
