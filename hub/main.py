"""Chorus Hub CLI entry point — click commands for hub, status, connect, allow."""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import click
import discord
import nest_asyncio
from aiohttp.web import AppRunner, TCPSite

from hub.bot import ChorusBot
from hub.config import load_config, load_or_create_secret
from hub.router import create_app

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)

# When CHORUS_LOG is set, also write to a file for debugging.
_log_file = os.environ.get("CHORUS_LOG")
if _log_file:
    _fh = logging.FileHandler(_log_file)
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(name)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S"
    ))
    logging.getLogger().addHandler(_fh)

logger = logging.getLogger("chorus.hub")

# Allow nested event loops — needed when the CLI is invoked from within
# an already-running asyncio loop (e.g., Jupyter, pytest-asyncio).
nest_asyncio.apply()


def _create_discord_client() -> discord.Client:
    """Create a discord.Client with the required intents for Chorus."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.messages = True
    return discord.Client(intents=intents)


def _wire_events(client: discord.Client, bot: ChorusBot) -> None:
    """Register Discord event handlers that delegate to the ChorusBot."""

    @client.event
    async def on_message(message):
        logger.debug(
            "on_message received: channel=%s author=%s(%s) content=%r",
            getattr(message.channel, "id", "?"),
            getattr(message.author, "name", "?"),
            getattr(message.author, "id", "?"),
            (message.content or "")[:200],
        )
        await bot.handle_message(message)

    @client.event
    async def on_ready():
        logger.info("Discord bot connected as %s (id=%s)", client.user, client.user.id)
        guilds = [(g.name, g.id) for g in client.guilds]
        logger.info("Bot is in %d guild(s): %s", len(guilds), guilds)


@click.group()
def cli() -> None:
    """Chorus Hub — Discord-to-Claude relay orchestrator."""


@cli.command()
@click.argument("channel_id")
def connect(channel_id: str) -> None:
    """Print the Claude Code launch command for a given channel.

    The relay must be registered as an MCP server named 'chorus-relay'
    (via the installed plugin or `claude mcp add`). During the research
    preview, --dangerously-load-development-channels is required.
    """
    click.echo(
        f"CHORUS_CHANNEL={channel_id} claude "
        f"--dangerously-load-development-channels server:chorus-relay"
    )


@cli.command()
@click.argument("user_id")
def allow(user_id: str) -> None:
    """Add a user ID to the allowed_senders list in config."""
    config_env = os.environ.get("CHORUS_CONFIG")
    if config_env:
        config_path = Path(config_env)
    else:
        config_path = Path.home() / ".chorus" / "config.json"

    data: dict = {}
    if config_path.exists():
        data = json.loads(config_path.read_text())

    defaults = data.setdefault("defaults", {})
    allowed = defaults.setdefault("allowed_senders", [])

    if user_id not in allowed:
        allowed.append(user_id)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2))
    click.echo(f"Added {user_id} to allowed_senders.")


def _fetch_status() -> dict:
    """Fetch status from the running Hub's /status endpoint.

    This function is separated so tests can mock it without needing a live server.
    """
    import hub.config

    cfg = load_config()
    secret = hub.config.load_or_create_secret()
    import urllib.request

    url = f"http://{cfg.hub_host}:{cfg.hub_port}/status"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {secret}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


@cli.command()
def status() -> None:
    """Fetch and display active sessions from the Hub."""
    from urllib.error import HTTPError, URLError

    try:
        data = _fetch_status()
    except HTTPError as e:
        if e.code in (401, 403):
            click.echo(
                f"Error: Hub rejected the request ({e.code} {e.reason}). "
                "Check that ~/.chorus/.secret matches the running Hub.",
                err=True,
            )
        else:
            click.echo(f"Error: Hub returned {e.code} {e.reason}.", err=True)
        raise SystemExit(1)
    except URLError as e:
        cfg = load_config()
        click.echo(
            f"Error: Hub is not running (could not reach {cfg.hub_host}:{cfg.hub_port}: {e.reason}).\n"
            "Start it with `chorus hub`.",
            err=True,
        )
        raise SystemExit(1)

    count = data.get("count", 0)
    routes = data.get("routes", {})

    click.echo(f"Active sessions: {count}")
    for channel_id, info in routes.items():
        port = info.get("port", "?")
        session_id = info.get("session_id", "?")
        registered_at = info.get("registered_at", "?")
        click.echo(f"  {channel_id}  port={port}  session={session_id}  since={registered_at}")


@cli.command()
def hub() -> None:
    """Start the Hub — Discord bot + HTTP router."""
    logger.info("Starting Chorus Hub")
    cfg = load_config()
    logger.info(
        "Config loaded: host=%s port=%s allowed_senders=%s",
        cfg.hub_host, cfg.hub_port, cfg.allowed_senders,
    )
    secret = load_or_create_secret()
    logger.info("Secret loaded (len=%d)", len(secret))

    if not cfg.discord_token:
        logger.error("DISCORD_BOT_TOKEN not set")
        raise SystemExit(1)
    logger.info("Discord token present (len=%d)", len(cfg.discord_token))

    # Shared routing table — same dict in bot and router
    routes_table: dict = {}
    logger.debug("Created shared routes_table id=%s", id(routes_table))

    bot = ChorusBot(cfg, routes_table=routes_table)

    callbacks = {
        "reply": bot.send_message,
        "react": bot.add_reaction,
        "fetch_messages": bot.fetch_messages,
        "channel_info": bot.get_channel_info,
        "stop_typing": bot.stop_typing,
    }

    app = create_app(secret, callbacks, routes_table=routes_table)

    # Create discord.py client and wire events
    client = _create_discord_client()
    bot._client = client
    _wire_events(client, bot)

    async def _start_hub():
        runner = None
        try:
            runner = AppRunner(app)
            await runner.setup()
            site = TCPSite(runner, cfg.hub_host, cfg.hub_port)
            await site.start()
            logger.info("HTTP router listening on %s:%s", cfg.hub_host, cfg.hub_port)
            logger.info("Starting Discord client...")

            # Start Discord client (blocks until disconnected)
            await client.start(cfg.discord_token)
        finally:
            await bot.close()
            if not client.is_closed():
                await client.close()
            if runner is not None:
                await runner.cleanup()

    asyncio.run(_start_hub())
