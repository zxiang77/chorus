# CLAUDE.md

Guidance for Claude Code when working on this repository.

## Project

Chorus routes a single Discord bot to multiple Claude Code sessions. It has two components:

- **`hub/`** — Python 3.10+, published to PyPI as `chorus-hub`. A persistent daemon that owns the Discord gateway connection and an aiohttp router on `localhost:8799`. Installed with `pip install chorus-hub`, run as `chorus hub`.
- **`relay/`** — TypeScript, runs on [Bun](https://bun.sh). Distributed as a Claude Code plugin (`chorus-relay`). One relay process is spawned per Claude Code session; it registers with the Hub over HTTP and bridges Discord events into Claude's MCP transcript.

See `README.md` for user-facing install/run docs. See `docs/chorus/reference.md` for the config schema, HTTP API, and security model.

## Layout

```
hub/
  main.py       # Click CLI: hub, status, connect, allow
  bot.py        # discord.py event handlers → ChorusBot
  router.py     # aiohttp app: /register, /unregister, /deliver, /status
  config.py     # load_config(), load_or_create_secret()
  tests/        # pytest, 50+ tests, run with `python -m pytest hub/tests/`

relay/
  relay.ts      # MCP server: registers with Hub, emits notifications/claude/channel
  relay.test.ts # bun test
  mcp.test.ts
```

The Hub and Relay communicate over HTTP with a shared bearer token from `~/.chorus/.secret` (created on first Hub start). Config lives at `~/.chorus/config.json`.

## Commands

```bash
# Hub — tests, lint, run locally
python -m pytest hub/tests/ -v
ruff check hub/
chorus hub                          # start the Hub (needs DISCORD_BOT_TOKEN)

# Relay — tests, typecheck
cd relay && bun test
cd relay && bun run tsc --noEmit    # typecheck

# Editable install for local Hub development
pip install -e .
```

## Conventions

- **Python**: PEP 8, 4-space indent, `snake_case` functions, `CamelCase` classes. Ruff enforces line length 100. Module-level `logger = logging.getLogger(__name__)`. Async functions don't need a prefix — the discord.py / aiohttp ecosystem doesn't use one.
- **TypeScript (relay)**: strict mode, `camelCase`, explicit return types on exported functions.
- **Logging**: the Hub logs to stderr at DEBUG. `CHORUS_LOG=<path>` also writes to a file — use this when debugging a running instance.
- **Errors**: prefer narrow `try`/`except` around the specific call that can fail, with a user-facing `click.echo(..., err=True); raise SystemExit(1)` for CLI commands. Don't wrap whole command bodies in a blanket except.

## Channel-agnostic design

The Hub and Relay are written against an abstract "channel" concept, not Discord specifically. The only Discord-specific code lives in `hub/bot.py`. When adding Telegram / iMessage / Slack support, new channel adapters should sit alongside `bot.py` and feed the same `ChorusBot`-shaped interface. Avoid leaking Discord-specific types into `router.py` or `relay.ts`.

## Testing

- Hub tests mock the Discord client and the aiohttp client — none of them hit a live Discord gateway or a real HTTP server. See `hub/tests/test_main.py` for CLI coverage, `test_router.py` for the HTTP surface, `test_bot.py` for event handling.
- Relay tests run under `bun test` and mock the MCP transport and HTTP.
- There is no CI-run end-to-end test — `docs/chorus/e2e-testing.md` has the manual procedure against a real Discord bot.

## Releasing

- **`chorus-hub` on PyPI**: bump `version` in `pyproject.toml`, tag the commit (`v0.1.1`, etc.), push the tag. Trusted publishing (OIDC) handles the upload.
- **`chorus-relay` plugin**: changes land in `zxiang77/chorus-marketplace` (a separate repo). Update the marketplace's `relay/` alongside any relay changes here.

## When fixing a user-facing bug

- Add a test in `hub/tests/` (or `relay/*.test.ts`) that fails on `main` and passes after the fix.
- Keep CLI errors friendly: one line to `stderr` with a concrete next step, `SystemExit(1)`. No raw stacktraces for expected failure modes like "Hub not running" or "auth rejected".
