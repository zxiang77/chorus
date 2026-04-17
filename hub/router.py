"""Hub HTTP Router — aiohttp server with routing table and Bearer token auth."""

from __future__ import annotations

import datetime
import logging

from aiohttp import web

logger = logging.getLogger("chorus.router")


def _check_auth(request: web.Request, secret: str) -> bool:
    """Return True if the request has a valid Bearer token."""
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {secret}"


def create_app(secret: str, callbacks: dict,
               routes_table: dict[str, dict] | None = None) -> web.Application:
    """Create and return an aiohttp Application with routing table endpoints.

    Args:
        secret: Bearer token required for all endpoints.
        callbacks: Dict of async callback functions with keys:
            reply, react, edit, fetch_messages, channel_info.
        routes_table: Optional shared routing table dict. If None, creates a new one.

    Returns:
        Configured aiohttp.web.Application.
    """
    if routes_table is None:
        routes_table = {}

    async def handle_register(request: web.Request) -> web.Response:
        if not _check_auth(request, secret):
            logger.warning("/register UNAUTHORIZED from %s", request.remote)
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        channel_id = body["channel_id"]
        routes_table[channel_id] = {
            "port": body["port"],
            "session_id": body["session_id"],
            "registered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        logger.info(
            "/register channel=%s port=%s session=%s (routes_table id=%s, size=%d)",
            channel_id, body["port"], body["session_id"],
            id(routes_table), len(routes_table),
        )
        return web.json_response({"status": "registered", "channel_id": channel_id})

    async def handle_unregister(request: web.Request) -> web.Response:
        if not _check_auth(request, secret):
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        channel_id = body["channel_id"]
        routes_table.pop(channel_id, None)
        return web.json_response({"status": "unregistered", "channel_id": channel_id})

    async def handle_reply(request: web.Request) -> web.Response:
        if not _check_auth(request, secret):
            logger.warning("/reply UNAUTHORIZED")
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        logger.info(
            "/reply channel=%s text=%r reply_to=%s",
            body.get("channel_id"), (body.get("text") or "")[:120], body.get("reply_to"),
        )
        result = await callbacks["reply"](
            channel_id=body["channel_id"],
            text=body["text"],
            reply_to=body.get("reply_to"),
            files=body.get("files"),
        )
        stop_typing = callbacks.get("stop_typing")
        if stop_typing:
            await stop_typing(channel_id=body["channel_id"])
        message_id = str(result.id) if hasattr(result, "id") else str(result)
        return web.json_response({"status": "ok", "message_id": message_id})

    async def handle_react(request: web.Request) -> web.Response:
        if not _check_auth(request, secret):
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        await callbacks["react"](
            channel_id=body["channel_id"],
            message_id=body["message_id"],
            emoji=body["emoji"],
        )
        return web.json_response({"status": "ok"})

    async def handle_edit(request: web.Request) -> web.Response:
        if not _check_auth(request, secret):
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        await callbacks["edit"](
            channel_id=body["channel_id"],
            message_id=body["message_id"],
            text=body["text"],
        )
        return web.json_response({"status": "ok"})

    async def handle_fetch_messages(request: web.Request) -> web.Response:
        if not _check_auth(request, secret):
            return web.json_response({"error": "unauthorized"}, status=401)
        channel_id = request.query["channel_id"]
        limit = int(request.query.get("limit", 50))
        result = await callbacks["fetch_messages"](
            channel_id=channel_id,
            limit=limit,
        )
        return web.json_response(result)

    async def handle_channel_info(request: web.Request) -> web.Response:
        if not _check_auth(request, secret):
            return web.json_response({"error": "unauthorized"}, status=401)
        channel_id = request.query["channel_id"]
        result = await callbacks["channel_info"](channel_id=channel_id)
        return web.json_response(result)

    async def handle_status(request: web.Request) -> web.Response:
        if not _check_auth(request, secret):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response({
            "status": "ok",
            "count": len(routes_table),
            "routes": {
                cid: {
                    "port": entry["port"],
                    "session_id": entry["session_id"],
                    "registered_at": entry["registered_at"],
                }
                for cid, entry in routes_table.items()
            },
        })

    app = web.Application()
    app.router.add_post("/register", handle_register)
    app.router.add_post("/unregister", handle_unregister)
    app.router.add_post("/reply", handle_reply)
    app.router.add_post("/react", handle_react)
    app.router.add_post("/edit", handle_edit)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/fetch-messages", handle_fetch_messages)
    app.router.add_get("/channel-info", handle_channel_info)

    # Store routing table on app for external access (e.g., bot module)
    app["routes_table"] = routes_table

    return app
