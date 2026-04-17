"""Tests for hub.router — Hub HTTP Router.

TDD tests: written before implementation exists.
All tests should FAIL because hub.router module does not exist yet.
"""

from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

# Guard import so tests are collected even when the module doesn't exist.
# Each test will fail at fixture setup time with a clear message.
try:
    from hub.router import create_app
except ImportError:
    create_app = None


TEST_SECRET = "test-secret-token-abc123"


def _make_callbacks():
    """Create a dict of async mock callbacks matching the router's expected interface."""
    return {
        "reply": AsyncMock(return_value={"message_id": "999"}),
        "react": AsyncMock(return_value=None),
        "edit": AsyncMock(return_value=None),
        "fetch_messages": AsyncMock(return_value=[]),
        "channel_info": AsyncMock(return_value={"name": "test", "topic": ""}),
    }


def _auth_header():
    return {"Authorization": f"Bearer {TEST_SECRET}"}


@pytest.fixture
async def router_client():
    """Create an aiohttp TestClient for the router app, manage lifecycle."""
    if create_app is None:
        pytest.fail("hub.router module does not exist yet (TDD: expected failure)")
    callbacks = _make_callbacks()
    app = create_app(secret=TEST_SECRET, callbacks=callbacks)
    async with TestClient(TestServer(app)) as client:
        client._test_callbacks = callbacks
        yield client


class TestRegisterEndpoint:
    """POST /register adds entry to routing table, returns 200."""

    @pytest.mark.asyncio
    async def test_register_adds_entry_and_returns_200(self, router_client):
        resp = await router_client.post(
            "/register",
            json={"channel_id": "12345", "port": 9001, "session_id": "sess-abc"},
            headers=_auth_header(),
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["status"] == "registered"
        assert body["channel_id"] == "12345"

    @pytest.mark.asyncio
    async def test_register_visible_in_status(self, router_client):
        """After registering, the channel should appear in /status."""
        await router_client.post(
            "/register",
            json={"channel_id": "12345", "port": 9001, "session_id": "sess-abc"},
            headers=_auth_header(),
        )
        resp = await router_client.get("/status", headers=_auth_header())
        assert resp.status == 200
        body = await resp.json()
        assert "12345" in str(body)


class TestUnregisterEndpoint:
    """POST /unregister removes entry from routing table, returns 200."""

    @pytest.mark.asyncio
    async def test_unregister_removes_entry_and_returns_200(self, router_client):
        # First register a channel
        await router_client.post(
            "/register",
            json={"channel_id": "12345", "port": 9001, "session_id": "sess-abc"},
            headers=_auth_header(),
        )
        # Now unregister it
        resp = await router_client.post(
            "/unregister",
            json={"channel_id": "12345"},
            headers=_auth_header(),
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["status"] == "unregistered"
        assert body["channel_id"] == "12345"

        # Verify it is gone from status
        status_resp = await router_client.get("/status", headers=_auth_header())
        status_body = await status_resp.json()
        # The channel should no longer appear in the active routes
        routes = status_body.get("routes", status_body.get("sessions", {}))
        assert "12345" not in str(routes)


class TestReplyEndpoint:
    """POST /reply calls the reply callback with correct arguments."""

    @pytest.mark.asyncio
    async def test_reply_invokes_callback_with_correct_args(self, router_client):
        reply_cb = router_client._test_callbacks["reply"]

        resp = await router_client.post(
            "/reply",
            json={
                "channel_id": "12345",
                "text": "Hello from relay!",
                "reply_to": "msg-42",
                "files": ["/tmp/screenshot.png"],
            },
            headers=_auth_header(),
        )
        assert resp.status == 200

        # Verify the reply callback was invoked with the exact arguments
        reply_cb.assert_called_once()
        call_kwargs = reply_cb.call_args
        # The callback should receive channel_id, text, and optional reply_to/files
        args = call_kwargs.kwargs if call_kwargs.kwargs else {}
        positional = call_kwargs.args if call_kwargs.args else ()

        # Accept either positional or keyword args — assert the values are present
        all_args = str(positional) + str(args)
        assert "12345" in all_args, "channel_id should be passed to reply callback"
        assert "Hello from relay!" in all_args, "text should be passed to reply callback"
        assert "msg-42" in all_args, "reply_to should be passed to reply callback"


class TestStatusEndpoint:
    """GET /status returns routing table summary with active sessions."""

    @pytest.mark.asyncio
    async def test_status_returns_summary_with_registered_sessions(self, router_client):
        # Register two channels
        await router_client.post(
            "/register",
            json={"channel_id": "111", "port": 9001, "session_id": "sess-1"},
            headers=_auth_header(),
        )
        await router_client.post(
            "/register",
            json={"channel_id": "222", "port": 9002, "session_id": "sess-2"},
            headers=_auth_header(),
        )

        resp = await router_client.get("/status", headers=_auth_header())
        assert resp.status == 200
        body = await resp.json()

        # Status should contain both registered channels
        body_str = str(body)
        assert "111" in body_str, "Channel 111 should appear in status"
        assert "222" in body_str, "Channel 222 should appear in status"
        # Status should indicate the number of active sessions
        # Accept either a count field or counting entries in a routes/sessions dict
        if "count" in body:
            assert body["count"] == 2
        elif "routes" in body:
            assert len(body["routes"]) == 2
        elif "sessions" in body:
            assert len(body["sessions"]) == 2
        else:
            # At minimum, both channel IDs must be present
            assert "111" in body_str and "222" in body_str


class TestFetchMessagesEndpoint:
    """GET /fetch-messages returns messages from the fetch_messages callback."""

    @pytest.mark.asyncio
    async def test_fetch_messages_calls_callback_and_returns_json_array(
        self, router_client
    ):
        """GET /fetch-messages?channel_id=X&limit=20 invokes the fetch_messages
        callback with the correct arguments and returns the result as a JSON array."""
        messages = [
            {"id": "m1", "content": "hello", "author": "alice", "ts": "2025-01-01T00:00:00Z"},
            {"id": "m2", "content": "world", "author": "bob", "ts": "2025-01-01T00:01:00Z"},
        ]
        fetch_cb = router_client._test_callbacks["fetch_messages"]
        fetch_cb.return_value = messages

        resp = await router_client.get(
            "/fetch-messages?channel_id=12345&limit=20",
            headers=_auth_header(),
        )
        assert resp.status == 200, f"Expected 200, got {resp.status}"

        body = await resp.json()
        assert isinstance(body, list), f"Expected JSON array, got {type(body).__name__}"
        assert len(body) == 2
        assert body[0]["id"] == "m1"
        assert body[1]["content"] == "world"

        # Verify callback was called with correct args
        fetch_cb.assert_called_once()
        call_kwargs = fetch_cb.call_args.kwargs if fetch_cb.call_args.kwargs else {}
        call_args = fetch_cb.call_args.args if fetch_cb.call_args.args else ()
        all_args = str(call_kwargs) + str(call_args)
        assert "12345" in all_args, "channel_id should be passed to fetch_messages callback"


class TestChannelInfoEndpoint:
    """GET /channel-info returns channel metadata from the channel_info callback."""

    @pytest.mark.asyncio
    async def test_channel_info_calls_callback_and_returns_metadata(
        self, router_client
    ):
        """GET /channel-info?channel_id=X invokes the channel_info callback
        and returns a JSON object with name, topic, and id."""
        info_cb = router_client._test_callbacks["channel_info"]
        info_cb.return_value = {
            "name": "general",
            "topic": "General discussion",
            "id": "12345",
        }

        resp = await router_client.get(
            "/channel-info?channel_id=12345",
            headers=_auth_header(),
        )
        assert resp.status == 200, f"Expected 200, got {resp.status}"

        body = await resp.json()
        assert body["name"] == "general"
        assert body["topic"] == "General discussion"
        assert body["id"] == "12345"

        # Verify callback was called with correct channel_id
        info_cb.assert_called_once()
        call_kwargs = info_cb.call_args.kwargs if info_cb.call_args.kwargs else {}
        call_args = info_cb.call_args.args if info_cb.call_args.args else ()
        all_args = str(call_kwargs) + str(call_args)
        assert "12345" in all_args, "channel_id should be passed to channel_info callback"


class TestBearerTokenAuth:
    """All endpoints reject requests without valid Bearer token with 401."""

    @pytest.mark.asyncio
    async def test_register_rejects_missing_token(self, router_client):
        resp = await router_client.post(
            "/register",
            json={"channel_id": "12345", "port": 9001, "session_id": "sess-abc"},
            # No Authorization header
        )
        assert resp.status == 401, "Missing token should return 401"

    @pytest.mark.asyncio
    async def test_register_rejects_wrong_token(self, router_client):
        resp = await router_client.post(
            "/register",
            json={"channel_id": "12345", "port": 9001, "session_id": "sess-abc"},
            headers={"Authorization": "Bearer wrong-secret-token"},
        )
        assert resp.status == 401, "Wrong token should return 401"

    @pytest.mark.asyncio
    async def test_fetch_messages_rejects_missing_token(self, router_client):
        """GET /fetch-messages without auth should return 401."""
        resp = await router_client.get(
            "/fetch-messages?channel_id=12345&limit=10",
            # No Authorization header
        )
        assert resp.status == 401, (
            f"GET /fetch-messages without auth should return 401, got {resp.status}"
        )

    @pytest.mark.asyncio
    async def test_channel_info_rejects_missing_token(self, router_client):
        """GET /channel-info without auth should return 401."""
        resp = await router_client.get(
            "/channel-info?channel_id=12345",
            # No Authorization header
        )
        assert resp.status == 401, (
            f"GET /channel-info without auth should return 401, got {resp.status}"
        )

    @pytest.mark.asyncio
    async def test_all_endpoints_require_auth(self, router_client):
        """Every endpoint should return 401 when no auth header is provided."""
        endpoints = [
            ("POST", "/register", {"channel_id": "1", "port": 9001, "session_id": "s"}),
            ("POST", "/unregister", {"channel_id": "1"}),
            ("POST", "/reply", {"channel_id": "1", "text": "hi"}),
            ("POST", "/react", {"channel_id": "1", "message_id": "m1", "emoji": "👍"}),
            ("POST", "/edit", {"channel_id": "1", "message_id": "m1", "text": "edited"}),
            ("GET", "/status", None),
            ("GET", "/fetch-messages?channel_id=1&limit=10", None),
            ("GET", "/channel-info?channel_id=1", None),
        ]

        for method, path, payload in endpoints:
            if method == "POST":
                resp = await router_client.post(path, json=payload)
            else:
                resp = await router_client.get(path)

            assert resp.status == 401, (
                f"{method} {path} should return 401 without auth, got {resp.status}"
            )
