# Chorus Reference

## Configuration

Config file at `~/.chorus/config.json` (or set `CHORUS_CONFIG` env var):

```json
{
  "hub": {
    "host": "127.0.0.1",
    "port": 8799,
    "discord_token_env": "DISCORD_BOT_TOKEN"
  },
  "defaults": {
    "cwd": ".",
    "permission_relay": false,
    "allowed_senders": []
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `hub.host` | `127.0.0.1` | Hub HTTP server bind address |
| `hub.port` | `8799` | Hub HTTP server port |
| `hub.discord_token_env` | `DISCORD_BOT_TOKEN` | Env var name for the Discord bot token |
| `defaults.allowed_senders` | `[]` | Discord user IDs allowed to send messages. Empty = allow all. |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | Yes | Discord bot token |
| `CHORUS_CONFIG` | No | Path to config file (default: `~/.chorus/config.json`) |
| `CHORUS_CHANNEL` | Yes (relay) | Discord channel ID this relay handles |
| `CHORUS_HUB` | No (relay) | Hub URL (default: `http://127.0.0.1:8799`) |

## Security

- Hub and relays communicate over HTTP on **localhost only**
- A shared bearer token (`~/.chorus/.secret`, mode 0600) authenticates all Hub-Relay communication
- Sender allowlist gates which Discord users can trigger sessions
- The token is auto-generated on first Hub startup

## Hub HTTP API

All endpoints require `Authorization: Bearer <token>` header.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/register` | POST | Relay registers with Hub |
| `/unregister` | POST | Relay deregisters |
| `/reply` | POST | Relay sends message to Discord |
| `/react` | POST | Relay adds reaction |
| `/edit` | POST | Relay edits message |
| `/fetch-messages` | GET | Relay fetches channel history |
| `/channel-info` | GET | Relay gets channel description |
| `/status` | GET | Health check + active sessions |
