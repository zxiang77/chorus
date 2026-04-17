# Chorus -- Project Documentation Index

## Overview

Chorus is a multi-session Discord-to-Claude Code router. A single Discord bot (the Hub) forwards messages to per-channel Claude Code sessions (via Relays), enabling multiple simultaneous AI-powered Discord channels with full Claude Code capabilities.

## Architecture

```
                                               +-- Relay MCP <--stdio--> Claude Code Session 1
Discord Bot -- Chorus Hub (persistent) -- HTTP -+-- Relay MCP <--stdio--> Claude Code Session 2
                                               +-- Relay MCP <--stdio--> Claude Code Session 3
```

- **Hub** (Python): discord.py bot + aiohttp HTTP router + in-memory routing table
- **Relay** (TypeScript/Bun): MCP channel server, one per Claude Code session

## Phase Documentation

| Phase | Title | Status |
|-------|-------|--------|
| [01](phases/01.md) | Hub and Relay -- Core Message Routing | Complete |
| [02](phases/02.md) | MCP Integration + Missing Endpoints + Production Hardening | Complete |

## Key Files

| File | Description |
|------|-------------|
| `chorus/hub/config.py` | Config loading + shared secret management |
| `chorus/hub/router.py` | HTTP server with routing table and auth |
| `chorus/hub/bot.py` | Discord bot message handling |
| `chorus/hub/main.py` | CLI entry point |
| `chorus/relay/relay.ts` | MCP channel server |
| `chorus/README.md` | User-facing quickstart and reference |
| `chorus/config.example.json` | Example configuration |
