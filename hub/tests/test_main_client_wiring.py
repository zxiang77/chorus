"""Tests for discord.py Client wiring in the Hub startup sequence."""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestCreateDiscordClient:
    def test_hub_creates_client_with_message_content_intent(self):
        from hub.main import _create_discord_client

        client = _create_discord_client()
        assert client.intents.message_content is True
        assert client.intents.guilds is True
        assert client.intents.messages is True


class TestWireEvents:
    @pytest.mark.asyncio
    async def test_on_message_calls_bot_handle_message(self):
        from hub.main import _wire_events

        mock_client = MagicMock()
        mock_bot = MagicMock()
        mock_bot.handle_message = AsyncMock()

        _wire_events(mock_client, mock_bot)

        # Extract the on_message handler registered via client.event()
        on_message = None
        for call in mock_client.event.call_args_list:
            fn = call[0][0] if call[0] else None
            if fn and fn.__name__ == "on_message":
                on_message = fn
                break

        assert on_message is not None, "_wire_events must register an on_message handler"

        fake_msg = MagicMock()
        await on_message(fake_msg)
        mock_bot.handle_message.assert_called_once_with(fake_msg)


class TestSharedRoutesTable:
    def test_bot_and_router_share_routes_table(self):
        """After hub wiring, bot and app must reference the same routes_table dict.

        The hub command creates a shared routes_table, passes it to ChorusBot,
        creates the aiohttp app, then overwrites app["routes_table"] with the
        shared dict so both sides see the same object.
        """
        from hub.bot import ChorusBot
        from hub.config import ChorusConfig
        from hub.router import create_app

        routes_table = {}
        config = ChorusConfig(allowed_senders=["123"])
        bot = ChorusBot(config=config, routes_table=routes_table)

        callbacks = {
            "reply": bot.send_message,
            "react": bot.add_reaction,
            "fetch_messages": bot.fetch_messages,
            "channel_info": bot.get_channel_info,
            "stop_typing": bot.stop_typing,
        }
        app = create_app("secret", callbacks, routes_table=routes_table)

        assert app["routes_table"] is routes_table
        assert bot._routes_table is routes_table
