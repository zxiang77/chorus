# Chorus E2E Testing Guide (from source / contributors)

Step-by-step guide to test the full message flow: Discord → Hub → Relay → Claude Code → reply back. **End users should follow [getting-started.md](getting-started.md) instead** — this guide installs from a local clone for contributors who are modifying chorus itself.

## Prerequisites

1. **Discord bot** — create one at the [Discord Developer Portal](https://discord.com/developers/applications):
   - Enable **Message Content Intent** under Bot settings
   - Grant permissions: Send Messages, Read Message History, Add Reactions, Attach Files
   - Invite the bot to your Discord server

2. **Discord channel** — pick (or create) a channel for testing. Copy the channel ID:
   - Right-click the channel → Copy Channel ID (enable Developer Mode in Discord settings if you don't see this)

3. **Your Discord user ID** — needed for the sender allowlist:
   - Right-click your username → Copy User ID

4. **Clone and install from source**:
   ```bash
   git clone https://github.com/zxiang77/chorus.git
   cd chorus

   # Hub (Python)
   pip install -e ".[dev]"

   # Relay (TypeScript/Bun)
   cd relay && bun install && cd ..
   ```

## Step 1: Configure

```bash
# Save your bot token to ~/.chorus/.env (chmod 0600)
chorus configure <your-bot-token-here>

# Add yourself to the sender allowlist
chorus allow <your-discord-user-id>
```

> Exporting `DISCORD_BOT_TOKEN` in your shell also works and takes precedence
> over the saved value. Use whichever fits your workflow.

Verify config exists:
```bash
cat ~/.chorus/config.json
# Should show your user ID in allowed_senders
```

## Step 2: Start the Hub

```bash
chorus hub
```

You should see (log lines on stderr):
```
[hh:mm:ss] [chorus.hub] INFO: HTTP router listening on 127.0.0.1:8799
[hh:mm:ss] [chorus.hub] INFO: Discord bot connected as YourBotName#1234 (id=...)
```

If you see `Error: No Discord token configured` — re-run `chorus configure <token>`
from Step 1, or export `DISCORD_BOT_TOKEN` in this shell.

Leave this terminal running.

## Step 3: Start a Claude Code session with the Relay

In a **new terminal**, launch Claude Code with the relay channel enabled. During the
research preview, custom channels require the development flag:

```bash
CHORUS_CHANNEL=<your-channel-id> claude --dangerously-load-development-channels server:chorus-relay
```

Claude Code will prompt you to confirm loading the development channel. The relay
registers with the Hub on startup and pushes inbound Discord messages into the
session via `notifications/claude/channel`.

Or use the convenience command:
```bash
chorus connect <your-channel-id>
# Prints the full command — copy and run it
```

## Step 4: Test the message flow

1. **Send a message** in the Discord channel (from your account, not the bot)
2. The Hub should route it to the Relay → Claude Code session
3. Claude should see the message and can reply using the `reply` tool
4. The reply should appear in the Discord channel

## Step 5: Verify with `chorus status`

In a **third terminal**:
```bash
chorus status
```

Should show your active session:
```
Active sessions: 1
  <channel-id>  port=<port>  session=relay-<id>  since=<timestamp>
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Hub prints nothing after "listening on..." | Bot token may be wrong or Message Content Intent not enabled | Check token; enable intent in Discord Developer Portal |
| Message sent but Claude doesn't receive it | Sender not in allowlist, or channel not registered | Run `chorus allow <user-id>`; check `chorus status` shows the channel |
| `chorus status` shows 0 sessions | Relay didn't register with Hub | Check Relay terminal for errors; verify `~/.chorus/.secret` exists |
| Relay fails with "CHORUS_CHANNEL required" | Env var not set | Set `CHORUS_CHANNEL=<id>` before the claude command |
| Relay fails reading secret | Hub hasn't run yet (no `~/.chorus/.secret`) | Start the Hub first — it auto-generates the secret on first run |
| Claude receives message but reply doesn't appear in Discord | Reply tool error or Hub disconnected | Check Hub terminal for errors; verify bot has Send Messages permission |

## Multiple Channels

Run multiple Claude sessions, each with a different channel:

```bash
# Terminal 2: session for #frontend
CHORUS_CHANNEL=123456789012345678 claude --dangerously-load-development-channels server:chorus-relay

# Terminal 3: session for #backend
CHORUS_CHANNEL=987654321098765432 claude --dangerously-load-development-channels server:chorus-relay
```

Each channel routes to its own isolated Claude Code session. Verify with `chorus status`.
