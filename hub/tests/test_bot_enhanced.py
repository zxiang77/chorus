"""Tests for enhanced send_message with reply_to, files, and bot cleanup."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def bot():
    from hub.bot import ChorusBot

    cfg = MagicMock()
    cfg.allowed_senders = []
    b = ChorusBot(config=cfg, routes_table={})

    mock_client = MagicMock()
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock(return_value=MagicMock(id=99999))
    mock_client.get_channel = MagicMock(return_value=mock_channel)
    b._client = mock_client

    return b, mock_channel


class TestSendMessageReplyTo:
    @pytest.mark.asyncio
    async def test_reply_to_passes_message_reference(self, bot):
        b, mock_channel = bot
        import discord

        await b.send_message(channel_id="100", text="replying", reply_to="42")

        mock_channel.send.assert_called_once()
        call_kwargs = mock_channel.send.call_args
        ref = call_kwargs.kwargs.get("reference") or (
            call_kwargs[1].get("reference") if len(call_kwargs) > 1 else None
        )
        assert ref is not None, "send_message with reply_to must pass a reference kwarg"
        assert ref.message_id == 42
        assert ref.channel_id == 100

    @pytest.mark.asyncio
    async def test_send_message_without_reply_to_has_no_reference(self, bot):
        b, mock_channel = bot

        await b.send_message(channel_id="100", text="no reply")

        call_kwargs = mock_channel.send.call_args
        ref = call_kwargs.kwargs.get("reference")
        assert ref is None


class TestSendMessageFiles:
    @pytest.mark.asyncio
    async def test_files_passes_discord_file_objects(self, bot):
        import tempfile
        import os

        b, mock_channel = bot

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"test content")
            tmp_path = f.name

        try:
            await b.send_message(channel_id="100", text="with file", files=[tmp_path])

            call_kwargs = mock_channel.send.call_args
            file_arg = call_kwargs.kwargs.get("files") or call_kwargs.kwargs.get("file")
            assert file_arg is not None, "send_message with files must pass file(s) to channel.send"
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_send_message_without_files_sends_no_files(self, bot):
        b, mock_channel = bot

        await b.send_message(channel_id="100", text="plain")

        call_kwargs = mock_channel.send.call_args
        files_arg = call_kwargs.kwargs.get("files")
        assert files_arg is None or files_arg == []


class TestBotClose:
    @pytest.mark.asyncio
    async def test_close_cancels_all_typing_tasks(self):
        from hub.bot import ChorusBot

        cfg = MagicMock()
        cfg.allowed_senders = []
        b = ChorusBot(config=cfg, routes_table={})

        mock_client = MagicMock()
        mock_channel = MagicMock()
        mock_channel.typing.return_value = MagicMock(
            __aenter__=AsyncMock(), __aexit__=AsyncMock(return_value=False)
        )
        mock_client.get_channel = MagicMock(return_value=mock_channel)
        b._client = mock_client

        await b.start_typing("100")
        await b.start_typing("200")
        assert len(b._typing_tasks) == 2

        await b.close()
        assert len(b._typing_tasks) == 0
