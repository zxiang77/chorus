"""Tests that the /reply handler calls stop_typing after successful send."""

from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from hub.router import create_app


SECRET = "test-secret"


def _auth_header():
    return {"Authorization": f"Bearer {SECRET}"}


@pytest.fixture
async def client_with_stop_typing():
    """Create a TestClient with a tracked stop_typing callback."""
    stop_typing_calls: list[str] = []

    async def mock_reply(channel_id, text, reply_to=None, files=None):
        return {"id": 12345}

    async def mock_stop_typing(channel_id):
        stop_typing_calls.append(channel_id)

    callbacks = {
        "reply": mock_reply,
        "react": AsyncMock(),
        "edit": AsyncMock(),
        "fetch_messages": AsyncMock(return_value=[]),
        "channel_info": AsyncMock(return_value={"name": "ch", "topic": "t", "id": 1}),
        "stop_typing": mock_stop_typing,
    }

    app = create_app(SECRET, callbacks)
    async with TestClient(TestServer(app)) as client:
        client._stop_typing_calls = stop_typing_calls
        yield client


@pytest.fixture
async def client_without_stop_typing():
    """Create a TestClient without a stop_typing callback."""
    async def mock_reply(channel_id, text, reply_to=None, files=None):
        return {"id": 12345}

    callbacks = {
        "reply": mock_reply,
        "react": AsyncMock(),
        "edit": AsyncMock(),
        "fetch_messages": AsyncMock(return_value=[]),
        "channel_info": AsyncMock(return_value={"name": "ch", "topic": "t", "id": 1}),
    }

    app = create_app(SECRET, callbacks)
    async with TestClient(TestServer(app)) as client:
        yield client


class TestReplyStopTyping:
    """POST /reply should call stop_typing after the reply callback succeeds."""

    @pytest.mark.asyncio
    async def test_reply_calls_stop_typing(self, client_with_stop_typing):
        client = client_with_stop_typing
        resp = await client.post(
            "/reply",
            json={"channel_id": "100", "text": "hello"},
            headers=_auth_header(),
        )
        assert resp.status == 200
        assert client._stop_typing_calls == ["100"]

    @pytest.mark.asyncio
    async def test_reply_without_stop_typing_callback_still_works(
        self, client_without_stop_typing
    ):
        """If stop_typing callback is not provided, reply should still work."""
        client = client_without_stop_typing
        resp = await client.post(
            "/reply",
            json={"channel_id": "100", "text": "hello"},
            headers=_auth_header(),
        )
        assert resp.status == 200
