"""Tests for graceful shutdown and stale relay removal — TDD tests for ST-5."""

import contextlib
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_config():
    """Create a minimal ChorusConfig-like object."""
    cfg = MagicMock()
    cfg.discord_token = "fake-token"
    cfg.allowed_senders = ["111111111"]
    cfg.hub_host = "127.0.0.1"
    cfg.hub_port = 8799
    return cfg


@pytest.fixture
def mock_routes_table():
    """In-memory routing table with two relays registered."""
    return {
        "channel-100": {"port": 9001, "session_id": "sess-a"},
        "channel-200": {"port": 9002, "session_id": "sess-b"},
    }


def _make_discord_message(*, author_id="111111111", author_name="TestUser",
                          author_bot=False, channel_id="100",
                          content="hello world", message_id="msg-001"):
    """Create a mock discord.Message with realistic attributes."""
    msg = MagicMock()
    msg.author.id = int(author_id)
    msg.author.name = author_name
    msg.author.bot = author_bot
    msg.channel.id = int(channel_id)
    msg.content = content
    msg.id = int(message_id) if message_id.isdigit() else message_id
    msg.created_at = MagicMock()
    msg.created_at.isoformat.return_value = "2026-03-25T12:00:00+00:00"
    return msg


class TestHubShutdownSequence:
    """Hub shutdown should stop the bot and HTTP server cleanly."""

    @pytest.mark.asyncio
    async def test_hub_shutdown_stops_bot_and_server_in_correct_order(self, mock_config):
        """When _start_hub is interrupted, it should stop the Discord bot and
        clean up the HTTP server runner. The bot should be closed before the
        runner is cleaned up (bot first, then HTTP server).

        This tests that hub/main.py's _start_hub coroutine has proper
        shutdown logic — currently the Event().wait() only has runner.cleanup()
        in the finally block but does NOT close the bot.
        """
        from hub.main import cli

        # Track the cleanup call order
        cleanup_order = []

        # Create mock objects that record when they are cleaned up
        mock_runner = MagicMock()
        mock_runner.setup = AsyncMock()
        mock_runner.cleanup = AsyncMock(
            side_effect=lambda: cleanup_order.append("runner.cleanup")
        )

        mock_site = MagicMock()
        mock_site.start = AsyncMock()

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        mock_bot.add_reaction = AsyncMock()
        mock_bot.fetch_messages = AsyncMock()
        mock_bot.get_channel_info = AsyncMock()
        # The bot must have a close method that the shutdown calls
        mock_bot.close = AsyncMock(
            side_effect=lambda: cleanup_order.append("bot.close")
        )

        import asyncio

        async def fake_start_hub(coro):
            """Actually run the coroutine but interrupt it immediately."""
            # Run the coroutine, but signal it to stop quickly
            task = asyncio.ensure_future(coro)
            # Let setup and start happen
            await asyncio.sleep(0.05)
            # Cancel to simulate SIGINT
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        with (
            patch("hub.main.load_config", return_value=mock_config),
            patch("hub.main.load_or_create_secret", return_value="fake-secret"),
            patch("hub.main.create_app", return_value=MagicMock()),
            patch("hub.main.ChorusBot", return_value=mock_bot),
            patch("hub.main.AppRunner", return_value=mock_runner),
            patch("hub.main.TCPSite", return_value=mock_site),
            patch("hub.main.asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(fake_start_hub(coro))),
        ):
            from click.testing import CliRunner
            runner = CliRunner()
            runner.invoke(cli, ["hub"])

        # The key assertion: bot.close must be called during shutdown
        assert mock_bot.close.called, (
            "Hub shutdown must call bot.close() to cleanly stop the Discord client. "
            "Currently _start_hub only calls runner.cleanup() in the finally block."
        )

        # Verify both cleanup actions were performed
        assert "bot.close" in cleanup_order, (
            "bot.close must be called during shutdown"
        )
        assert "runner.cleanup" in cleanup_order, (
            "runner.cleanup must be called during shutdown"
        )

        # Bot should be closed before the HTTP server is cleaned up
        bot_idx = cleanup_order.index("bot.close")
        runner_idx = cleanup_order.index("runner.cleanup")
        assert bot_idx < runner_idx, (
            f"Bot should be closed before HTTP server. Order was: {cleanup_order}"
        )


class TestStaleRelayRemoval:
    """When a relay's HTTP server is unreachable, the bot should remove it from the routing table."""

    @pytest.mark.asyncio
    async def test_bot_removes_stale_relay_on_post_connection_error(self, mock_config, mock_routes_table):
        """When handle_message tries to POST to a relay and gets a connection error,
        the bot should remove that relay from the routing table.

        Currently handle_message does not catch connection errors — the aiohttp
        POST will raise and the stale entry stays in the table forever.
        """
        import aiohttp

        from hub.bot import ChorusBot

        bot = ChorusBot(config=mock_config, routes_table=mock_routes_table)

        # Message targets channel-100 which has relay on port 9001
        message = _make_discord_message(
            author_id="111111111",
            channel_id="100",
            content="trigger stale removal",
        )

        # Verify the relay entry exists before the message
        assert "channel-100" in mock_routes_table, "Pre-condition: channel-100 must be in routing table"
        assert "channel-200" in mock_routes_table, "Pre-condition: channel-200 must be in routing table"

        # Mock aiohttp to raise a connection error when POSTing to the relay
        mock_session = MagicMock()
        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientConnectorError(
                connection_key=MagicMock(), os_error=OSError("Connection refused")
            )
        )
        mock_post_ctx.__aexit__ = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_post_ctx)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock()

        with patch("hub.bot.aiohttp.ClientSession", return_value=mock_session_ctx):
            await bot.handle_message(message)

        # After the connection error, channel-100 should be removed from routes
        assert "channel-100" not in mock_routes_table, (
            "Stale relay for channel-100 should be removed from routing table after "
            "connection error. Currently handle_message does not catch the error."
        )

        # Other entries should NOT be affected
        assert "channel-200" in mock_routes_table, (
            "channel-200 should not be removed — only the stale relay is removed"
        )

    @pytest.mark.asyncio
    async def test_bot_logs_warning_when_removing_stale_relay(self, mock_config, mock_routes_table, caplog):
        """When a stale relay is removed, the bot should log a warning so operators
        can diagnose relay crashes.

        The warning must include the channel ID so the operator knows which relay died.
        """
        import aiohttp

        from hub.bot import ChorusBot

        bot = ChorusBot(config=mock_config, routes_table=mock_routes_table)

        message = _make_discord_message(
            author_id="111111111",
            channel_id="100",
            content="trigger warning log",
        )

        # Mock aiohttp to raise a connection error
        mock_session = MagicMock()
        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientConnectorError(
                connection_key=MagicMock(), os_error=OSError("Connection refused")
            )
        )
        mock_post_ctx.__aexit__ = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_post_ctx)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock()

        with (
            patch("hub.bot.aiohttp.ClientSession", return_value=mock_session_ctx),
            caplog.at_level(logging.WARNING, logger="hub.bot"),
        ):
            await bot.handle_message(message)

        # A warning should have been logged about the stale relay
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_messages) > 0, (
            "Bot must log a WARNING when removing a stale relay. "
            "No warning was logged during handle_message with connection error."
        )

        # The warning should mention the channel so operators can identify which relay crashed
        combined = " ".join(warning_messages)
        assert "100" in combined or "channel-100" in combined, (
            f"Warning must mention the channel ID. Got warnings: {warning_messages}"
        )

    @pytest.mark.asyncio
    async def test_stale_relay_removal_preserves_other_entries(self, mock_config):
        """Removing a stale relay for one channel must not disturb other channels'
        relay entries. This verifies the removal is targeted, not a full table clear.

        Uses a table with 3 entries where only the middle one is stale.
        """
        import aiohttp

        from hub.bot import ChorusBot

        routes = {
            "channel-100": {"port": 9001, "session_id": "sess-a"},
            "channel-200": {"port": 9002, "session_id": "sess-b"},
            "channel-300": {"port": 9003, "session_id": "sess-c"},
        }
        bot = ChorusBot(config=mock_config, routes_table=routes)

        # Target channel-200 (the "stale" one)
        message = _make_discord_message(
            author_id="111111111",
            channel_id="200",
            content="trigger removal of channel-200",
        )

        # Mock aiohttp to raise connection error
        mock_session = MagicMock()
        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientConnectorError(
                connection_key=MagicMock(), os_error=OSError("Connection refused")
            )
        )
        mock_post_ctx.__aexit__ = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_post_ctx)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock()

        with patch("hub.bot.aiohttp.ClientSession", return_value=mock_session_ctx):
            await bot.handle_message(message)

        # channel-200 should be removed (stale relay)
        assert "channel-200" not in routes, (
            "channel-200 should be removed after connection error to its relay"
        )

        # channel-100 and channel-300 must remain intact
        assert "channel-100" in routes, (
            "channel-100 must not be removed — it's a healthy relay"
        )
        assert routes["channel-100"]["port"] == 9001, (
            "channel-100 entry must be unchanged"
        )
        assert "channel-300" in routes, (
            "channel-300 must not be removed — it's a healthy relay"
        )
        assert routes["channel-300"]["port"] == 9003, (
            "channel-300 entry must be unchanged"
        )

        # Exactly 2 entries should remain
        assert len(routes) == 2, (
            f"Expected 2 entries remaining in routing table, got {len(routes)}: {list(routes.keys())}"
        )
