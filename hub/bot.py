"""Hub Discord bot — message handling, sender gating, and relay forwarding."""

from __future__ import annotations

import asyncio
import contextlib
import logging

import aiohttp
import discord

logger = logging.getLogger("chorus.bot")


class ChorusBot:
    """Discord bot that forwards messages to registered relays."""

    def __init__(self, config, routes_table: dict) -> None:
        self._config = config
        self._routes_table = routes_table
        self._client = None
        self._typing_tasks: dict[str, asyncio.Task] = {}

    async def handle_message(self, message) -> None:
        """Handle an incoming Discord message.

        Filters bot messages, gates by sender allowlist, looks up
        the routing table, and POSTs to the relay if registered.
        """
        author_id = str(getattr(message.author, "id", "?"))
        channel_id = str(getattr(message.channel, "id", "?"))
        logger.debug(
            "handle_message: channel=%s author=%s is_bot=%s",
            channel_id, author_id, getattr(message.author, "bot", "?"),
        )

        # Filter bot messages
        if message.author.bot:
            logger.debug("  SKIP: author is a bot")
            return

        # Gate by sender allowlist
        if author_id not in self._config.allowed_senders:
            logger.info(
                "  SKIP: author %s not in allowed_senders %s",
                author_id, self._config.allowed_senders,
            )
            return

        # Look up routing table for this channel
        logger.debug(
            "  routes_table (id=%s) keys=%s",
            id(self._routes_table), list(self._routes_table.keys()),
        )
        route = self._routes_table.get(channel_id)
        if route is None:
            # Try prefixed key format (e.g., "channel-<id>")
            route = self._routes_table.get(f"channel-{channel_id}")
        if route is None:
            logger.warning(
                "  SKIP: no registered relay for channel %s (known: %s)",
                channel_id, list(self._routes_table.keys()),
            )
            return

        # Forward message to relay
        port = route["port"]
        url = f"http://127.0.0.1:{port}/message"
        logger.info("  FORWARD: channel=%s -> %s", channel_id, url)
        payload = {
            "content": message.content,
            "meta": {
                "chat_id": channel_id,
                "message_id": str(message.id),
                "user": message.author.name,
                "user_id": str(message.author.id),
                "ts": message.created_at.isoformat(),
            },
        }

        # Determine the routing table key used for this channel
        route_key = channel_id if channel_id in self._routes_table else f"channel-{channel_id}"

        # Start typing indicator before forwarding to relay
        await self.start_typing(channel_id)

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload) as resp:
                    logger.info(
                        "  FORWARD result: status=%s channel=%s",
                        resp.status, channel_id,
                    )
            except aiohttp.ClientConnectorError as e:
                logger.warning(
                    "  Relay unreachable for channel %s (%s), removing stale route %s",
                    channel_id, e, route_key,
                )
                self._routes_table.pop(route_key, None)

    async def send_message(
        self,
        channel_id: str,
        text: str,
        reply_to: str | None = None,
        files: list[str] | None = None,
    ):
        """Send a message to a Discord channel.

        Args:
            channel_id: The Discord channel ID to send to.
            text: The message text content.
            reply_to: Optional message ID to reply to (creates a message reference).
            files: Optional list of file paths to attach.
        """
        channel = self._client.get_channel(int(channel_id))

        kwargs: dict = {}
        if reply_to is not None:
            kwargs["reference"] = discord.MessageReference(
                message_id=int(reply_to), channel_id=int(channel_id)
            )
        if files:
            kwargs["files"] = [discord.File(fp) for fp in files]

        result = await channel.send(text, **kwargs)
        await self.stop_typing(channel_id)
        return result

    async def add_reaction(self, channel_id: str, message_id: str, emoji: str):
        """Add a reaction to a Discord message."""
        channel = self._client.get_channel(int(channel_id))
        msg = await channel.fetch_message(int(message_id))
        await msg.add_reaction(emoji)

    async def fetch_messages(self, channel_id: str, limit: int) -> list[dict]:
        """Fetch the last N messages from a Discord channel.

        Returns a list of dicts with keys: id, content, author, ts.
        """
        channel = self._client.get_channel(int(channel_id))
        messages = []
        async for msg in channel.history(limit=limit):
            messages.append({
                "id": msg.id,
                "content": msg.content,
                "author": msg.author.name,
                "ts": msg.created_at.isoformat(),
            })
        return messages

    async def get_channel_info(self, channel_id: str) -> dict:
        """Fetch channel metadata.

        Returns a dict with keys: name, topic, id.
        """
        channel = self._client.get_channel(int(channel_id))
        return {
            "name": channel.name,
            "topic": channel.topic,
            "id": channel.id,
        }

    async def start_typing(self, channel_id: str) -> None:
        """Start a persistent typing indicator in a Discord channel.

        Creates an async task that triggers channel.typing() in a loop
        (re-triggering every 9s since Discord typing expires after 10s).
        The task is stored in _typing_tasks keyed by channel_id.
        """
        if self._client is None:
            return

        # Cancel any existing typing task for this channel
        if channel_id in self._typing_tasks:
            self._typing_tasks[channel_id].cancel()

        channel = self._client.get_channel(int(channel_id))

        async def _typing_loop():
            try:
                while True:
                    async with channel.typing():
                        await asyncio.sleep(9)
            except asyncio.CancelledError:
                pass

        self._typing_tasks[channel_id] = asyncio.create_task(_typing_loop())

    async def stop_typing(self, channel_id: str) -> None:
        """Stop the typing indicator for a Discord channel."""
        task = self._typing_tasks.pop(channel_id, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def close(self) -> None:
        """Cancel all active typing tasks and clean up resources."""
        channel_ids = list(self._typing_tasks.keys())
        for channel_id in channel_ids:
            await self.stop_typing(channel_id)
