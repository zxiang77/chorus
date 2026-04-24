# Getting Started with Chorus

A step-by-step walkthrough from zero to your first Claude session driven by a Discord channel. Each step shows the exact command to run and what you should see when it works.

**Time:** ~10 minutes, most of it in the Discord Developer Portal.

## Prerequisites

Before you start, make sure you have:

- Python **3.10+** on your PATH (`python --version`)
- [Bun](https://bun.sh) installed (`bun --version`) — the relay runs on Bun
- A Discord account and a server you can invite a bot to
- [Claude Code](https://docs.claude.com/en/docs/claude-code) installed and working (`claude --version`)

## Step 1 — Create a Discord bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**. Name it.
2. Sidebar → **Bot**. Scroll to **Privileged Gateway Intents** → enable **Message Content Intent**. Without this the bot receives empty messages.
3. On the same page, **Reset Token** and copy it — it's shown once.
4. Sidebar → **OAuth2** → **URL Generator**. Scopes: `bot`. Bot Permissions: **Send Messages**, **Read Message History**, **Add Reactions**, **Attach Files**. Copy the generated URL, open it, and add the bot to a server you're in.

> For DM-only use you technically need zero permissions, but selecting these now saves a trip when you want to use guild channels.

## Step 2 — Install the Hub and Relay

```bash
# Hub (Python package)
pip install chorus-hub

# Relay (Claude Code plugin)
claude plugin marketplace add zxiang77/chorus-marketplace
claude plugin install chorus-relay@chorus-marketplace
```

**What you should see:**

```
Successfully installed chorus-hub-0.1.0
...
Plugin installed: chorus-relay
```

## Step 3 — Configure

```bash
# Save the bot token (stored at ~/.chorus/.env, chmod 0600)
chorus configure <paste-bot-token-from-step-1>

# Add your own Discord user ID to the sender allowlist.
# Get your ID: Discord → User Settings → Advanced → Developer Mode,
# then right-click your name in any channel → Copy User ID
chorus allow <your-discord-user-id>
```

**What you should see:**

```
Token saved to /Users/you/.chorus/.env.
Added <your-user-id> to allowed_senders.
```

Verify:

```bash
chorus configure
```

```
Token:  set (MTIzNG… from /Users/you/.chorus/.env)
Hub:    127.0.0.1:8799
Allowed senders: 1
```

## Step 4 — Start the Hub

Open **terminal 1**. The Hub stays running.

```bash
chorus hub
```

**What you should see (log lines on stderr):**

```
[hh:mm:ss] [chorus.hub] INFO: Starting Chorus Hub
[hh:mm:ss] [chorus.hub] INFO: Config loaded: host=127.0.0.1 port=8799 allowed_senders=['<your-id>']
[hh:mm:ss] [chorus.hub] INFO: Secret loaded (len=43)
[hh:mm:ss] [chorus.hub] INFO: Discord token present (len=72)
[hh:mm:ss] [chorus.hub] INFO: HTTP router listening on 127.0.0.1:8799
[hh:mm:ss] [chorus.hub] INFO: Discord bot connected as YourBotName#1234 (id=...)
[hh:mm:ss] [chorus.hub] INFO: Bot is in 1 guild(s): [(...)]
```

If you see `Error: No Discord token configured.` — re-run `chorus configure <token>` from Step 3.

Leave this terminal alone.

## Step 5 — Launch a Claude session attached to a channel

Pick a Discord channel (DM with the bot, or a text channel in the server you invited it to). **Right-click the channel → Copy Channel ID** (Developer Mode must be on).

Open **terminal 2**:

```bash
# Prints the launch command with the right flags
chorus connect <your-channel-id>
```

**What you should see:**

```
CHORUS_CHANNEL=<your-channel-id> claude --dangerously-load-development-channels server:chorus-relay
```

Copy that line and run it. Claude Code starts up and the relay registers with the Hub.

> During the research preview, `--dangerously-load-development-channels` is required. Claude Code will prompt you once to confirm.

## Step 6 — Send your first message

In Discord, in the channel you just attached, type a message:

```
hello, are you there?
```

Over in **terminal 2** (the Claude session), you'll see the message arrive as a `<channel source="chorus-relay" ...>` block. Claude can call the `reply` tool to send a response — watch it appear back in the Discord channel.

You can also:
- React with any emoji (`react` tool)
- Edit a previous bot message (`edit` tool) — useful for "working…" → result updates
- Fetch recent history (`fetch_messages` tool)

## Step 7 — Verify with `chorus status`

Open **terminal 3**:

```bash
chorus status
```

**What you should see:**

```
Active sessions: 1
  <channel-id>  port=<port>  session=relay-<id>  since=<timestamp>
```

That's it — one Discord channel, one Claude Code session, wired together.

## Going further

**Multiple channels.** Open another terminal, pick a different channel ID, and repeat Step 5. Each channel runs its own Claude session with its own working directory and context.

**Per-channel context.** Set the Discord channel's **topic** to something like:

```
CCTrade options research. cwd: cctrade/. Conventions in cctrade/CLAUDE.md.
```

The relay reads the topic on startup and injects it as system-prompt context. Zero-config per-workspace routing.

**Lock down who can reach the bot.** `chorus allow <user-id>` already restricts senders. For groups, add everyone you want to reach the bot with the same command. Users not on the list are silently ignored.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `chorus status` shows no sessions | The relay didn't register. Look for errors in the terminal running `claude` — most common cause is running without the `--dangerously-load-development-channels` flag. |
| Bot is online in Discord but messages don't arrive in Claude | You're not on the allowlist. Run `chorus allow <your-user-id>`. |
| `chorus hub` exits with "No Discord token configured" | Run `chorus configure <token>`. The error message names this explicitly. |
| Claude replies but nothing shows in Discord | Check the bot has **Send Messages** permission in that channel; re-check Step 1's permissions. |
| Relay fails on startup reading the secret | Start the Hub first — it auto-generates `~/.chorus/.secret` on first run. |

## See also

- [Architecture & reference](reference.md) — config schema, HTTP API, security model
- [E2E testing guide](e2e-testing.md) — validation checklist for contributors
