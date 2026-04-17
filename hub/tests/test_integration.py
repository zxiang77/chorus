"""Integration tests for the full Hub message flow.

Verifies router + bot wiring end-to-end WITHOUT a real Discord connection.
Uses aiohttp test utilities for the Hub router and a mock relay HTTP server
to capture forwarded messages.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from hub.bot import ChorusBot
from hub.router import create_app

TEST_SECRET = "integration-test-secret-xyz"
TEST_CHANNEL_ID = "555666777"
TEST_USER_ID = "111111111"


def _make_config(allowed_senders=None):
    """Create a minimal config object for the bot."""
    cfg = MagicMock()
    cfg.discord_token = "fake-token"
    cfg.allowed_senders = allowed_senders or [TEST_USER_ID]
    return cfg


def _make_discord_message(
    *,
    author_id=TEST_USER_ID,
    author_name="IntegrationUser",
    author_bot=False,
    channel_id=TEST_CHANNEL_ID,
    content="Hello from Discord!",
    message_id="msg-integration-001",
):
    """Create a mock Discord message with realistic attributes."""
    msg = MagicMock()
    msg.author.id = int(author_id)
    msg.author.name = author_name
    msg.author.bot = author_bot
    msg.channel.id = int(channel_id)
    msg.content = content
    msg.id = int(message_id) if message_id.lstrip("-").isdigit() else message_id
    msg.created_at = MagicMock()
    msg.created_at.isoformat.return_value = "2026-03-25T14:00:00+00:00"
    return msg


class TestFullRoundTrip:
    """Full round-trip: message in -> relay notification -> reply -> Discord send."""

    @pytest.mark.asyncio
    async def test_message_flows_from_discord_through_hub_to_relay_and_back(self):
        """End-to-end: a Discord message reaches the mock relay, then the relay
        replies via POST /reply, and the Discord send callback is invoked."""

        # --- Step 1: Set up the mock relay that records received messages ---
        relay_received = []

        async def relay_message_handler(request):
            body = await request.json()
            relay_received.append(body)
            return web.json_response({"ok": True})

        relay_app = web.Application()
        relay_app.router.add_post("/message", relay_message_handler)

        # Start mock relay on a random port
        relay_runner = web.AppRunner(relay_app)
        await relay_runner.setup()
        relay_site = web.TCPSite(relay_runner, "127.0.0.1", 0)
        await relay_site.start()
        relay_port = relay_site._server.sockets[0].getsockname()[1]

        try:
            # --- Step 2: Set up the Hub router with a mock Discord send callback ---
            discord_send_calls = []

            async def mock_reply_callback(channel_id, text, reply_to=None, files=None):
                discord_send_calls.append({
                    "channel_id": channel_id,
                    "text": text,
                    "reply_to": reply_to,
                    "files": files,
                })
                return {"message_id": "discord-msg-999"}

            callbacks = {
                "reply": mock_reply_callback,
                "react": AsyncMock(),
                "edit": AsyncMock(),
                "fetch_messages": AsyncMock(return_value=[]),
                "channel_info": AsyncMock(return_value={"name": "test", "topic": ""}),
            }

            hub_app = create_app(secret=TEST_SECRET, callbacks=callbacks)

            async with TestClient(TestServer(hub_app)) as hub_client:
                # --- Step 3: Register the mock relay via POST /register ---
                reg_resp = await hub_client.post(
                    "/register",
                    json={
                        "channel_id": TEST_CHANNEL_ID,
                        "port": relay_port,
                        "session_id": "integration-sess-1",
                    },
                    headers={"Authorization": f"Bearer {TEST_SECRET}"},
                )
                assert reg_resp.status == 200
                reg_body = await reg_resp.json()
                assert reg_body["status"] == "registered"

                # --- Step 4: Create bot wired to the Hub's routing table ---
                config = _make_config()
                routes_table = hub_app["routes_table"]
                bot = ChorusBot(config=config, routes_table=routes_table)

                # --- Step 5: Simulate an inbound Discord message ---
                discord_msg = _make_discord_message(
                    content="What is the weather today?",
                    channel_id=TEST_CHANNEL_ID,
                )
                await bot.handle_message(discord_msg)

                # Give the async HTTP call a moment to complete
                await asyncio.sleep(0.1)

                # --- Step 6: Verify the mock relay received the message ---
                assert len(relay_received) == 1, (
                    f"Expected 1 message at relay, got {len(relay_received)}"
                )
                forwarded = relay_received[0]
                assert forwarded["content"] == "What is the weather today?"
                assert forwarded["meta"]["chat_id"] == TEST_CHANNEL_ID
                assert forwarded["meta"]["user"] == "IntegrationUser"
                assert forwarded["meta"]["user_id"] == TEST_USER_ID

                # --- Step 7: Simulate the relay calling POST /reply ---
                reply_resp = await hub_client.post(
                    "/reply",
                    json={
                        "channel_id": TEST_CHANNEL_ID,
                        "text": "It is sunny and 72F today!",
                        "reply_to": "msg-integration-001",
                    },
                    headers={"Authorization": f"Bearer {TEST_SECRET}"},
                )
                assert reply_resp.status == 200

                # --- Step 8: Verify the Discord send callback was invoked ---
                assert len(discord_send_calls) == 1, (
                    f"Expected 1 Discord send call, got {len(discord_send_calls)}"
                )
                sent = discord_send_calls[0]
                assert sent["channel_id"] == TEST_CHANNEL_ID
                assert sent["text"] == "It is sunny and 72F today!"
                assert sent["reply_to"] == "msg-integration-001"

        finally:
            await relay_runner.cleanup()


class TestStatusShowsRegisteredRelay:
    """GET /status reflects registered relays accurately."""

    @pytest.mark.asyncio
    async def test_status_shows_registered_relay_with_correct_details(self):
        """After a relay registers, GET /status should list it with port and session ID."""
        callbacks = {
            "reply": AsyncMock(),
            "react": AsyncMock(),
            "edit": AsyncMock(),
            "fetch_messages": AsyncMock(return_value=[]),
            "channel_info": AsyncMock(return_value={"name": "test", "topic": ""}),
        }
        hub_app = create_app(secret=TEST_SECRET, callbacks=callbacks)

        async with TestClient(TestServer(hub_app)) as hub_client:
            auth = {"Authorization": f"Bearer {TEST_SECRET}"}

            # Status should be empty initially
            initial_resp = await hub_client.get("/status", headers=auth)
            assert initial_resp.status == 200
            initial_body = await initial_resp.json()
            assert initial_body["count"] == 0
            assert initial_body["routes"] == {}

            # Register a relay
            await hub_client.post(
                "/register",
                json={
                    "channel_id": "888999000",
                    "port": 9876,
                    "session_id": "sess-status-test",
                },
                headers=auth,
            )

            # Status should now show the registered relay
            status_resp = await hub_client.get("/status", headers=auth)
            assert status_resp.status == 200
            status_body = await status_resp.json()
            assert status_body["count"] == 1
            assert "888999000" in status_body["routes"]

            route_entry = status_body["routes"]["888999000"]
            assert route_entry["port"] == 9876
            assert route_entry["session_id"] == "sess-status-test"
            assert "registered_at" in route_entry


class TestUnregisteredChannelDropsSilently:
    """Messages for channels without a registered relay are silently dropped."""

    @pytest.mark.asyncio
    async def test_message_for_unregistered_channel_does_not_reach_any_relay(self):
        """When the bot receives a message in a channel with no relay,
        no HTTP call is made and no error is raised."""

        # Set up a mock relay to verify it does NOT receive anything
        relay_received = []

        async def relay_message_handler(request):
            body = await request.json()
            relay_received.append(body)
            return web.json_response({"ok": True})

        relay_app = web.Application()
        relay_app.router.add_post("/message", relay_message_handler)

        relay_runner = web.AppRunner(relay_app)
        await relay_runner.setup()
        relay_site = web.TCPSite(relay_runner, "127.0.0.1", 0)
        await relay_site.start()
        relay_port = relay_site._server.sockets[0].getsockname()[1]

        try:
            callbacks = {
                "reply": AsyncMock(),
                "react": AsyncMock(),
                "edit": AsyncMock(),
                "fetch_messages": AsyncMock(return_value=[]),
                "channel_info": AsyncMock(return_value={"name": "test", "topic": ""}),
            }
            hub_app = create_app(secret=TEST_SECRET, callbacks=callbacks)

            async with TestClient(TestServer(hub_app)) as hub_client:
                auth = {"Authorization": f"Bearer {TEST_SECRET}"}

                # Register a relay for channel 111, but NOT for channel 999
                await hub_client.post(
                    "/register",
                    json={
                        "channel_id": "111",
                        "port": relay_port,
                        "session_id": "sess-registered",
                    },
                    headers=auth,
                )

                # Create bot wired to the Hub's routing table
                config = _make_config()
                routes_table = hub_app["routes_table"]
                bot = ChorusBot(config=config, routes_table=routes_table)

                # Send a message to unregistered channel 999
                unregistered_msg = _make_discord_message(
                    channel_id="999",
                    content="This should be dropped",
                )
                await bot.handle_message(unregistered_msg)
                await asyncio.sleep(0.1)

                # The relay should NOT have received anything
                assert len(relay_received) == 0, (
                    f"Relay should not receive messages for unregistered channels, "
                    f"but got {len(relay_received)} messages"
                )

                # Now send a message to the registered channel 111 to confirm
                # the relay IS reachable (proving the drop was intentional)
                registered_msg = _make_discord_message(
                    channel_id="111",
                    content="This should arrive",
                )
                await bot.handle_message(registered_msg)
                await asyncio.sleep(0.1)

                assert len(relay_received) == 1, (
                    "Relay should receive exactly 1 message (for the registered channel)"
                )
                assert relay_received[0]["content"] == "This should arrive"

        finally:
            await relay_runner.cleanup()


class TestAuthEnforcement:
    """Bearer token auth is enforced across the full integration flow."""

    @pytest.mark.asyncio
    async def test_relay_registration_and_reply_require_auth(self):
        """Registration and reply both fail with 401 when auth is missing,
        and succeed with the correct Bearer token."""
        callbacks = {
            "reply": AsyncMock(return_value={"message_id": "999"}),
            "react": AsyncMock(),
            "edit": AsyncMock(),
            "fetch_messages": AsyncMock(return_value=[]),
            "channel_info": AsyncMock(return_value={"name": "test", "topic": ""}),
        }
        hub_app = create_app(secret=TEST_SECRET, callbacks=callbacks)

        async with TestClient(TestServer(hub_app)) as hub_client:
            # Registration without auth fails
            fail_resp = await hub_client.post(
                "/register",
                json={
                    "channel_id": "123",
                    "port": 9001,
                    "session_id": "sess-noauth",
                },
            )
            assert fail_resp.status == 401

            # Registration with auth succeeds
            auth = {"Authorization": f"Bearer {TEST_SECRET}"}
            ok_resp = await hub_client.post(
                "/register",
                json={
                    "channel_id": "123",
                    "port": 9001,
                    "session_id": "sess-auth",
                },
                headers=auth,
            )
            assert ok_resp.status == 200

            # Reply without auth fails
            fail_reply = await hub_client.post(
                "/reply",
                json={
                    "channel_id": "123",
                    "text": "no auth reply",
                },
            )
            assert fail_reply.status == 401

            # Reply with auth succeeds
            ok_reply = await hub_client.post(
                "/reply",
                json={
                    "channel_id": "123",
                    "text": "authed reply",
                },
                headers=auth,
            )
            assert ok_reply.status == 200
