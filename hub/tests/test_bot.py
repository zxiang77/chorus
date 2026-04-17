"""Tests for hub.bot module — TDD tests written before implementation."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_config():
    """Create a minimal ChorusConfig-like object for the bot."""
    cfg = MagicMock()
    cfg.discord_token = "fake-token-for-testing"
    cfg.allowed_senders = ["111111111", "222222222"]
    return cfg


@pytest.fixture
def mock_routes_table():
    """In-memory routing table simulating registered relays."""
    return {
        "channel-100": {"port": 9001, "session_id": "sess-a"},
        "channel-200": {"port": 9002, "session_id": "sess-b"},
    }


def _make_discord_message(*, author_id="111111111", author_name="TestUser",
                          author_bot=False, channel_id="channel-100",
                          content="hello world", message_id="msg-001"):
    """Create a mock discord.Message with realistic attributes."""
    msg = MagicMock()
    msg.author.id = int(author_id) if author_id.isdigit() else author_id
    msg.author.name = author_name
    msg.author.bot = author_bot
    msg.channel.id = int(channel_id) if channel_id.lstrip("-").isdigit() else channel_id
    msg.channel.typing.return_value = MagicMock(
        __aenter__=AsyncMock(), __aexit__=AsyncMock()
    )
    msg.content = content
    msg.id = int(message_id) if message_id.lstrip("-").isdigit() else message_id
    msg.created_at = MagicMock()
    msg.created_at.isoformat.return_value = "2026-03-25T12:00:00+00:00"
    return msg


class TestBotFiltersOwnMessages:
    """Bot messages (author.bot=True) should be completely ignored."""

    @pytest.mark.asyncio
    async def test_on_message_ignores_bot_messages(self, mock_config, mock_routes_table):
        """When a message comes from a bot user, it should not be forwarded to any relay."""
        from hub.bot import ChorusBot

        bot = ChorusBot(config=mock_config, routes_table=mock_routes_table)

        bot_message = _make_discord_message(
            author_bot=True,
            author_id="999999999",
            author_name="SomeBot",
            channel_id="channel-100",
            content="I am a bot message",
        )

        # Mock aiohttp.ClientSession so we can verify no HTTP call is made
        with patch("hub.bot.aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.post = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock()

            await bot.handle_message(bot_message)

            # No HTTP call should have been made — the bot message is dropped
            mock_session.post.assert_not_called()


class TestSenderAllowlistGating:
    """Messages from users not in the allowed_senders list should be silently dropped."""

    @pytest.mark.asyncio
    async def test_message_from_non_allowed_user_is_dropped(self, mock_config, mock_routes_table):
        """A message from a user whose ID is NOT in allowed_senders should not be forwarded."""
        from hub.bot import ChorusBot

        bot = ChorusBot(config=mock_config, routes_table=mock_routes_table)

        # author_id "999999999" is not in allowed_senders ["111111111", "222222222"]
        stranger_message = _make_discord_message(
            author_id="999999999",
            author_name="Stranger",
            author_bot=False,
            channel_id="channel-100",
            content="hey there",
        )

        with patch("hub.bot.aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.post = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock()

            await bot.handle_message(stranger_message)

            # Message should be silently dropped — no relay call
            mock_session.post.assert_not_called()


class TestMessageRoutingToRelay:
    """Allowed messages should be forwarded to the correct relay via HTTP POST."""

    @pytest.mark.asyncio
    async def test_allowed_message_is_forwarded_to_correct_relay(self, mock_config, mock_routes_table):
        """An allowed user's message in a channel with a registered relay should be POSTed to that relay."""
        from hub.bot import ChorusBot

        bot = ChorusBot(config=mock_config, routes_table=mock_routes_table)

        # author_id "111111111" is in allowed_senders, channel-100 has relay on port 9001
        allowed_message = _make_discord_message(
            author_id="111111111",
            author_name="AllowedUser",
            author_bot=False,
            channel_id="100",
            content="Hello relay!",
            message_id="42",
        )

        # Use a mock HTTP response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        with patch("hub.bot.aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session_cls.return_value = MagicMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock()

            await bot.handle_message(allowed_message)

            # Verify POST was made to the relay at the correct port
            mock_session.post.assert_called_once()
            call_args = mock_session.post.call_args

            # URL should target the relay's port on localhost
            url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
            assert "9001" in str(url), f"Expected relay port 9001 in URL, got: {url}"
            assert "/message" in str(url), f"Expected /message path in URL, got: {url}"

            # Payload should contain the message content and metadata
            json_payload = call_args[1].get("json", {})
            assert json_payload["content"] == "Hello relay!"
            assert json_payload["meta"]["user"] == "AllowedUser"
            assert json_payload["meta"]["chat_id"] == "100"
            assert json_payload["meta"]["message_id"] == "42"


class TestNoRelayDropsSilently:
    """Messages for channels without a registered relay should be silently dropped."""

    @pytest.mark.asyncio
    async def test_message_for_unregistered_channel_is_dropped(self, mock_config, mock_routes_table):
        """When a message arrives in a channel that has no relay registered, it should be silently ignored."""
        from hub.bot import ChorusBot

        bot = ChorusBot(config=mock_config, routes_table=mock_routes_table)

        # Use a channel ID not in the routing table (only "channel-100" and "channel-200" are registered)
        message_no_relay = _make_discord_message(
            author_id="111111111",
            author_name="AllowedUser",
            author_bot=False,
            channel_id="999",  # Not in routing table
            content="Hello, anyone there?",
        )

        with patch("hub.bot.aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.post = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock()

            # Should complete without error — no relay, so silently dropped
            await bot.handle_message(message_no_relay)

            # No HTTP call should have been made
            mock_session.post.assert_not_called()


class TestDiscordCallbacks:
    """Discord callback methods that the router uses to interact with Discord."""

    @pytest.mark.asyncio
    async def test_send_message_calls_discord_channel_send(self, mock_config, mock_routes_table):
        """send_message callback should fetch the channel by ID and call .send() with the text."""
        from hub.bot import ChorusBot

        bot = ChorusBot(config=mock_config, routes_table=mock_routes_table)

        # Mock the discord.py client that the bot wraps
        mock_client = MagicMock()
        mock_channel = MagicMock()
        mock_channel.send = AsyncMock(return_value=MagicMock(id=12345))
        mock_client.get_channel = MagicMock(return_value=mock_channel)
        bot._client = mock_client

        await bot.send_message(channel_id="100", text="Hello from relay!")

        # Verify the correct channel was fetched
        mock_client.get_channel.assert_called_once_with(100)

        # Verify send was called with the message text
        mock_channel.send.assert_called_once()
        call_kwargs = mock_channel.send.call_args
        assert "Hello from relay!" in str(call_kwargs), (
            f"Expected 'Hello from relay!' in send args, got: {call_kwargs}"
        )

    @pytest.mark.asyncio
    async def test_add_reaction_calls_discord_message_add_reaction(self, mock_config, mock_routes_table):
        """add_reaction callback should fetch the message and add the specified emoji reaction."""
        from hub.bot import ChorusBot

        bot = ChorusBot(config=mock_config, routes_table=mock_routes_table)

        mock_client = MagicMock()
        mock_channel = MagicMock()
        mock_discord_message = MagicMock()
        mock_discord_message.add_reaction = AsyncMock()
        mock_channel.fetch_message = AsyncMock(return_value=mock_discord_message)
        mock_client.get_channel = MagicMock(return_value=mock_channel)
        bot._client = mock_client

        await bot.add_reaction(channel_id="100", message_id="42", emoji="thumbsup")

        # Verify the correct channel was fetched
        mock_client.get_channel.assert_called_once_with(100)

        # Verify the message was fetched
        mock_channel.fetch_message.assert_called_once_with(42)

        # Verify the reaction was added
        mock_discord_message.add_reaction.assert_called_once_with("thumbsup")

    @pytest.mark.asyncio
    async def test_fetch_messages_returns_list_of_message_dicts(self, mock_config, mock_routes_table):
        """fetch_messages should call channel.history(limit=N) and return a list of message dicts."""
        from hub.bot import ChorusBot

        bot = ChorusBot(config=mock_config, routes_table=mock_routes_table)

        # Build two mock discord.Message objects returned by channel.history()
        mock_msg_1 = MagicMock()
        mock_msg_1.id = 1001
        mock_msg_1.content = "First message"
        mock_msg_1.author.name = "Alice"
        mock_msg_1.created_at.isoformat.return_value = "2026-03-25T10:00:00+00:00"

        mock_msg_2 = MagicMock()
        mock_msg_2.id = 1002
        mock_msg_2.content = "Second message"
        mock_msg_2.author.name = "Bob"
        mock_msg_2.created_at.isoformat.return_value = "2026-03-25T10:01:00+00:00"

        # channel.history() returns an async iterator in discord.py
        mock_channel = MagicMock()

        async def fake_history(limit=None):
            for m in [mock_msg_1, mock_msg_2]:
                yield m

        mock_channel.history = fake_history

        mock_client = MagicMock()
        mock_client.get_channel = MagicMock(return_value=mock_channel)
        bot._client = mock_client

        result = await bot.fetch_messages(channel_id="100", limit=10)

        # Verify the correct channel was fetched
        mock_client.get_channel.assert_called_once_with(100)

        # Verify result is a list of dicts with the expected keys
        assert isinstance(result, list)
        assert len(result) == 2

        assert result[0]["id"] == 1001
        assert result[0]["content"] == "First message"
        assert result[0]["author"] == "Alice"
        assert result[0]["ts"] == "2026-03-25T10:00:00+00:00"

        assert result[1]["id"] == 1002
        assert result[1]["content"] == "Second message"
        assert result[1]["author"] == "Bob"
        assert result[1]["ts"] == "2026-03-25T10:01:00+00:00"

    @pytest.mark.asyncio
    async def test_get_channel_info_returns_channel_metadata(self, mock_config, mock_routes_table):
        """get_channel_info should return a dict with name, topic, and id of the channel."""
        from hub.bot import ChorusBot

        bot = ChorusBot(config=mock_config, routes_table=mock_routes_table)

        mock_channel = MagicMock()
        mock_channel.name = "general"
        mock_channel.topic = "Main discussion channel"
        mock_channel.id = 100

        mock_client = MagicMock()
        mock_client.get_channel = MagicMock(return_value=mock_channel)
        bot._client = mock_client

        result = await bot.get_channel_info(channel_id="100")

        # Verify the correct channel was fetched
        mock_client.get_channel.assert_called_once_with(100)

        # Verify result has the expected keys and values
        assert isinstance(result, dict)
        assert result["name"] == "general"
        assert result["topic"] == "Main discussion channel"
        assert result["id"] == 100


class TestTypingIndicator:
    """Typing indicator should show while relay is processing and stop on reply."""

    @pytest.mark.asyncio
    async def test_typing_indicator_started_when_message_forwarded_to_relay(
        self, mock_config, mock_routes_table
    ):
        """When handle_message successfully forwards to a relay, start_typing(channel_id) should be called.

        The typing indicator must begin BEFORE the HTTP POST to the relay so the user
        sees the typing indicator immediately while the relay processes the message.
        """
        from hub.bot import ChorusBot

        bot = ChorusBot(config=mock_config, routes_table=mock_routes_table)

        # Track the order of operations to verify start_typing is called before the POST
        call_order = []

        # Create a mock start_typing that records when it was called

        async def tracking_start_typing(channel_id):
            call_order.append(("start_typing", channel_id))

        bot.start_typing = tracking_start_typing

        # message in channel-100 from allowed user -> should route to relay on port 9001
        allowed_message = _make_discord_message(
            author_id="111111111",
            author_name="AllowedUser",
            author_bot=False,
            channel_id="100",
            content="Please process this",
            message_id="55",
        )

        # Mock HTTP response so the POST succeeds
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        with patch("hub.bot.aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()

            def tracking_post(*args, **kwargs):
                call_order.append(("post", args[0] if args else kwargs.get("url", "")))
                return mock_response

            mock_session.post = MagicMock(side_effect=tracking_post)
            mock_session_cls.return_value = MagicMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock()

            await bot.handle_message(allowed_message)

        # Verify start_typing was called with the correct channel_id
        start_typing_calls = [c for c in call_order if c[0] == "start_typing"]
        assert len(start_typing_calls) == 1, (
            f"start_typing should be called exactly once, got: {start_typing_calls}"
        )
        assert start_typing_calls[0][1] == "100", (
            f"start_typing should be called with the channel_id '100', got: {start_typing_calls[0][1]}"
        )

        # Verify start_typing was called BEFORE the relay POST
        start_idx = next(i for i, c in enumerate(call_order) if c[0] == "start_typing")
        post_idx = next(i for i, c in enumerate(call_order) if c[0] == "post")
        assert start_idx < post_idx, (
            f"start_typing (index {start_idx}) must happen before POST (index {post_idx}). "
            f"Call order: {call_order}"
        )

    @pytest.mark.asyncio
    async def test_typing_indicator_stopped_when_reply_received(
        self, mock_config, mock_routes_table
    ):
        """When a reply comes back from the relay, stop_typing should be called for that channel.

        The router's /reply handler should invoke a stop_typing callback after successfully
        sending the reply, so the typing indicator disappears.
        """
        from hub.bot import ChorusBot

        bot = ChorusBot(config=mock_config, routes_table=mock_routes_table)

        # The bot must have start_typing and stop_typing methods
        assert hasattr(bot, "start_typing"), (
            "ChorusBot must have a start_typing method"
        )
        assert hasattr(bot, "stop_typing"), (
            "ChorusBot must have a stop_typing method"
        )

        # Simulate starting a typing indicator
        # start_typing should create an async task stored in _typing_tasks
        mock_client = MagicMock()
        mock_channel = MagicMock()
        mock_channel.typing.return_value = MagicMock(
            __aenter__=AsyncMock(), __aexit__=AsyncMock()
        )
        mock_client.get_channel = MagicMock(return_value=mock_channel)
        bot._client = mock_client

        await bot.start_typing("100")

        # Verify a typing task is now active for this channel
        assert hasattr(bot, "_typing_tasks"), (
            "ChorusBot must have a _typing_tasks dict to track active typing indicators"
        )
        assert "100" in bot._typing_tasks, (
            f"After start_typing('100'), _typing_tasks should contain '100'. "
            f"Got keys: {list(bot._typing_tasks.keys())}"
        )
        task = bot._typing_tasks["100"]
        assert isinstance(task, asyncio.Task), (
            f"_typing_tasks['100'] should be an asyncio.Task, got: {type(task)}"
        )
        assert not task.done(), "Typing task should still be running before stop_typing"

        # Now stop the typing indicator
        await bot.stop_typing("100")

        # The task should be cancelled
        assert task.cancelled() or task.done(), (
            "After stop_typing('100'), the typing task should be cancelled"
        )
        # The channel should be removed from _typing_tasks
        assert "100" not in bot._typing_tasks, (
            f"After stop_typing('100'), channel '100' should be removed from _typing_tasks. "
            f"Got keys: {list(bot._typing_tasks.keys())}"
        )
