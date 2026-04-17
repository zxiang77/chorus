# Chorus

Route a single Discord bot to multiple Claude Code sessions. Each Discord channel maps to a dedicated Claude Code session with full capabilities — tools, CLAUDE.md, hooks, skills, MCP servers, everything.

```
                                               ┌─ Relay MCP ←stdio→ Claude Code Session 1
Discord Bot ── Chorus Hub (persistent) ── HTTP ─┤─ Relay MCP ←stdio→ Claude Code Session 2
                                               └─ Relay MCP ←stdio→ Claude Code Session 3
```

**Hub** (Python) — persistent process that connects to Discord, routes messages to relays via HTTP.
**Relay** (TypeScript/Bun) — lightweight MCP server spawned by Claude Code, one per session.

## Get Started

### Prerequisites

- Python 3.10+
- [Bun](https://bun.sh) runtime
- A Discord bot with **Message Content Intent** enabled ([create one here](https://discord.com/developers/applications))
  - Permissions needed: Send Messages, Read Message History, Add Reactions, Attach Files

### Install

```bash
# Hub
pip install chorus-hub

# Relay (Claude Code plugin)
claude plugin install chorus-relay
```

> **Research preview:** Until Chorus is on the official plugin allowlist, install from our marketplace:
> ```bash
> claude plugin marketplace add chorus-marketplace --source github --repo zxiang77/chorus-marketplace
> claude plugin install chorus-relay@chorus-marketplace
> ```

### Configure

```bash
# Set your Discord bot token
export DISCORD_BOT_TOKEN="your-bot-token"

# Allow your Discord user ID (right-click your name in Discord → Copy User ID)
chorus allow <your-user-id>
```

### Run

```bash
# Terminal 1: Start the Hub
chorus hub

# Terminal 2: Connect a channel (right-click channel → Copy Channel ID)
CHORUS_CHANNEL=<channel-id> claude
```

> **Research preview:** Add `--dangerously-load-development-channels server:chorus-relay` to the `claude` command until Chorus is on the official allowlist.
>
> `chorus connect <channel-id>` prints the exact command for you.

Send a message in the Discord channel. Claude receives it and can reply.

### Multiple channels

Each channel gets its own Claude session. Open a new terminal for each one:

```bash
# Terminal 2
CHORUS_CHANNEL=1111111111 claude

# Terminal 3
CHORUS_CHANNEL=2222222222 claude
```

> **Research preview:** Add `--dangerously-load-development-channels server:chorus-relay` to each `claude` command until Chorus is on the official allowlist.

Check active sessions: `chorus status`

## Commands

| Command | Description |
|---------|-------------|
| `chorus hub` | Start the Hub (Discord bot + HTTP router) |
| `chorus status` | Show active channel-to-session mappings |
| `chorus connect <channel-id>` | Print the Claude Code launch command for a channel |
| `chorus allow <user-id>` | Add a Discord user to the sender allowlist |

## Channel context

Set a Discord channel's **topic/description** to give Claude context (e.g., "CCTrade options trading tools. Working directory: cctrade/"). The relay injects this as system prompt context automatically.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Hub won't start | Check `DISCORD_BOT_TOKEN` is set; enable Message Content Intent in Discord Developer Portal |
| Messages not arriving | Run `chorus allow <user-id>`; verify `chorus status` shows the channel |
| Relay won't register | Start the Hub first (it creates `~/.chorus/.secret` on first run) |
| Reply doesn't appear in Discord | Check bot has Send Messages permission in the channel |

## Docs

- [Reference](docs/chorus/reference.md) — configuration, environment variables, HTTP API, security
- [E2E Testing](docs/chorus/e2e-testing.md) — step-by-step manual testing guide
- [Phase History](docs/chorus/INDEX.md) — development phase documentation

## Development

```bash
# Hub tests
python -m pytest hub/tests/ -v

# Relay tests
cd relay && bun test

# Lint
ruff check hub/
```

## License

MIT
