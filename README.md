# Chorus

**Route a single Discord bot to multiple Claude Code sessions.** Like the [official Discord plugin](https://github.com/anthropics/claude-plugins-official/tree/main/external_plugins/discord), but multi-session — each Discord channel gets its own Claude Code session, all through one bot.

![Chorus routing a Discord channel to a Claude Code session](docs/chorus/hero.png)

## What it does

- **One bot, many channels, many sessions.** Each Discord channel maps to a dedicated Claude Code session with its own working directory and context.
- **Full Claude Code capabilities per session** — tools, CLAUDE.md, hooks, skills, MCP servers, everything. The relay is a plain MCP plugin; nothing is stripped down.
- **Channel topic becomes the system prompt** — set a channel's Discord topic to "CCTrade options research, cwd: cctrade/" and that context loads automatically. Zero-config per-workspace routing.

## Quick start

### Prerequisites

- Python 3.10+
- [Bun](https://bun.sh) runtime (the relay is a Bun MCP server)
- A Discord bot with **Message Content Intent** enabled ([Discord Developer Portal](https://discord.com/developers/applications))
  - Required permissions: Send Messages, Read Message History, Add Reactions, Attach Files

### Install

```bash
# Hub
pip install chorus-hub

# Relay (Claude Code plugin)
claude plugin install chorus-relay
```

> **Research preview:** Until Chorus is on the official plugin allowlist, install from our marketplace:
> ```bash
> claude plugin marketplace add zxiang77/chorus-marketplace
> claude plugin install chorus-relay@chorus-marketplace
> ```

### Configure

```bash
# Save your Discord bot token (stored at ~/.chorus/.env, chmod 0600)
chorus configure <your-bot-token>

# Allow your Discord user ID (right-click your name in Discord → Copy User ID)
chorus allow <your-user-id>
```

> `chorus configure` writes to `~/.chorus/.env` so the Hub picks it up on every start. Exporting `DISCORD_BOT_TOKEN` in your shell still works and takes precedence. Run `chorus configure` with no args to see current state.

### Run

```bash
# Terminal 1: start the Hub
chorus hub

# Terminal 2: connect a channel (right-click channel → Copy Channel ID)
CHORUS_CHANNEL=<channel-id> claude
```

> **Research preview:** append `--dangerously-load-development-channels server:chorus-relay` to the `claude` command until Chorus is on the official allowlist.
>
> `chorus connect <channel-id>` prints the exact command.

Post a message in the Discord channel — Claude receives it, can reply, react, fetch history, and edit messages.

### Multiple channels

Each channel gets its own Claude session. Open a new terminal per channel:

```bash
# Terminal A
CHORUS_CHANNEL=1111111111 claude

# Terminal B
CHORUS_CHANNEL=2222222222 claude
```

Check active sessions with `chorus status`.

## How it works

```mermaid
flowchart LR
    U["Discord user"] -- "DM / channel msg" --> B(("Discord bot"))
    B <-- "gateway" --> H["Chorus Hub<br/>(persistent, :8799)"]
    H <-- "HTTP + bearer" --> R1["Relay MCP<br/>channel A"]
    H <-- "HTTP + bearer" --> R2["Relay MCP<br/>channel B"]
    H <-- "HTTP + bearer" --> R3["Relay MCP<br/>channel C"]
    R1 <-- "stdio MCP" --> C1["Claude Code<br/>session A"]
    R2 <-- "stdio MCP" --> C2["Claude Code<br/>session B"]
    R3 <-- "stdio MCP" --> C3["Claude Code<br/>session C"]
```

**Hub** — one persistent Python process per machine. Holds the single Discord gateway connection, runs an aiohttp router on `localhost:8799`, owns the channel→relay routing table.

**Relay** — a short-lived TypeScript/Bun MCP server, one per Claude Code session. On startup it registers its channel and port with the Hub over HTTP; inbound Discord messages become `notifications/claude/channel` in the session's transcript.

The HTTP seam between Hub and Relay is the key design choice. Claude Code sessions come and go without re-authing the bot; one bot identity serves arbitrarily many sessions; the relay stays stateless (crash and the next session picks up). Hub and Relay authenticate with a shared bearer token in `~/.chorus/.secret`.

### What a message looks like end-to-end

```mermaid
sequenceDiagram
    participant U as You (Discord)
    participant B as Discord bot
    participant H as Chorus Hub
    participant R as Relay (MCP)
    participant C as Claude Code

    U->>B: "hey, what's the status?"
    B->>H: on_message(channel=123, text)
    Note over H: look up routing table:<br/>channel 123 → relay on :9001
    H->>R: POST /deliver (bearer)
    R->>C: notifications/claude/channel
    Note over C: Claude reads the msg,<br/>decides to reply
    C->>R: tool: reply(text)
    R->>H: POST /reply (bearer)
    H->>B: bot.send_message(channel, text)
    B->>U: Discord shows the reply
```

Inbound is push (Discord gateway → Hub → relay notification). Outbound uses the `reply` tool exposed by the relay to Claude; the reply flows back through the Hub so there's only ever one Discord connection, regardless of how many sessions are active.

## Commands

| Command | Description |
|---------|-------------|
| `chorus hub` | Start the Hub (Discord bot + HTTP router) |
| `chorus status` | Show active channel-to-session mappings |
| `chorus connect <channel-id>` | Print the Claude Code launch command for a channel |
| `chorus allow <user-id>` | Add a Discord user to the sender allowlist |
| `chorus configure <token>` | Save the Discord bot token to `~/.chorus/.env` |
| `chorus configure` | Show token + hub status |
| `chorus configure clear` | Remove the saved token |

## Channel context

Set a Discord channel's **topic/description** in Discord's channel settings. The relay reads it on startup and injects it as system-prompt context automatically. Example topic: *"CCTrade options trading research. Working directory: cctrade/. Use `cctrade/CLAUDE.md` for conventions."*

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Hub won't start | Run `chorus configure <token>` (or export `DISCORD_BOT_TOKEN`); enable Message Content Intent in Discord Developer Portal |
| Messages not arriving | Run `chorus allow <user-id>`; verify `chorus status` shows the channel |
| Relay won't register | Start the Hub first (it creates `~/.chorus/.secret` on first run) |
| Reply doesn't appear in Discord | Check the bot has Send Messages permission in the channel |

## Roadmap

Architecture is channel-agnostic — Telegram and iMessage are the obvious next stops (Claude Code's channels API already supports them). Track progress or chime in on [issues](https://github.com/zxiang77/chorus/issues).

## Docs

- [Reference](docs/chorus/reference.md) — configuration schema, environment variables, HTTP API, security model
- [E2E Testing](docs/chorus/e2e-testing.md) — step-by-step manual testing guide

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
