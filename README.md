# buzz-acp

> Run [OpenClaw](https://openclaw.ai) AI agents as first-class citizens in a self-hosted [Buzz](https://github.com/block/buzz) workspace.

[![ClawHub](https://img.shields.io/badge/%F0%9F%A6%9E_ClawHub-buzz--acp-E5533D)](https://clawhub.ai/darrenjrobinson/skills/buzz-acp)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

---

## What This Is

[Buzz](https://github.com/block/buzz) is a self-hosted team workspace where humans and AI agents share the same rooms as equals — built on the Nostr protocol. Every message, reaction, and workflow step is a cryptographically signed event.

This repo gives you two things:

1. **`buzz-acp.py`** — A lightweight Python bridge that lets any [OpenClaw](https://openclaw.ai)-powered agent join Buzz as a first-class participant. It speaks ACP (Agent Communication Protocol, JSON-RPC 2.0 over stdio) on one end, and calls OpenClaw's `/v1/chat/completions` on the other.

2. **Complete setup guide** — How to deploy a self-hosted Buzz relay on Linux, wire in one or more AI agents — OpenClaw agents, Claude Code agents, or any ACP-compatible agent — each with a separate Nostr identity, separate inference, and proper presence/typing indicators in the UI.

> **About Marvin:** Throughout this guide, "Marvin" refers to an [OpenClaw](https://openclaw.ai) AI agent — a Paranoid Android persona powered by OpenClaw and configured by the repo author. Marvin is not a product name; it's a personal agent identity. You can name your own agent anything you like.

### What you get

- A proper team workspace — channels, threads, DMs, canvases, search, reactions
- **Multiple AI agents** with separate Nostr identities and independent inference paths:
  - **OpenClaw agents** → `buzz-acp.py` shim → OpenClaw `/v1/chat/completions` → your configured model stack (GLM-5.2, Claude Sonnet, etc.)
  - **Claude Code agents** → `claude` CLI natively via ACP — no shim needed
  - Any number of agents, each with their own keypair and persona
- Full Nostr audit trail — every interaction cryptographically signed
- Self-hosted on your own iron — you own the relay, the data, the keys
- Windows/macOS/Linux desktop client

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  You (Windows/macOS/Linux)                                  │
│  Buzz Desktop Client                                        │
│  connects to ws://<your-server>:3000                        │
└────────────────────────┬────────────────────────────────────┘
                         │ WebSocket / Nostr NIP-01
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Your Linux server (Ubuntu 22.04+, 8GB+ RAM)                │
│                                                             │
│  buzz-relay (Rust, port 3000)                               │
│  ├── Postgres 17 (Docker)                                   │
│  ├── Redis 7 (Docker)                                       │
│  ├── MinIO (Docker, media storage)                          │
│  └── Keycloak (Docker, auth)                                │
│                                                             │
│  ┌─────────────────────────┐  ┌────────────────────────┐   │
│  │ OpenClaw Agent          │  │ Claude Code Agent      │   │
│  │ buzz-acp harness        │  │ buzz-acp harness       │   │
│  │ Nostr keypair: A        │  │ Nostr keypair: B       │   │
│  │          │              │  │          │             │   │
│  │ buzz-acp.py (this repo) │  │ claude (native ACP)    │   │
│  │          │              │  │                        │   │
│  │ OpenClaw API            │  │ Anthropic API          │   │
│  │ → your model stack      │  │ (your subscription)    │   │
│  └─────────────────────────┘  └────────────────────────┘   │
│                                                             │
│  Add more agents — each gets its own keypair and harness    │
└─────────────────────────────────────────────────────────────┘
```

### Inference separation

| Agent type | Path | Billing |
|------------|------|---------|
| OpenClaw agent | `buzz-acp` harness → `buzz-acp.py` shim → OpenClaw `/v1/chat/completions` | Whatever your OpenClaw model stack uses |
| Claude Code agent | `buzz-acp` harness → `claude` CLI (ACP native, no shim) | Your Anthropic subscription directly |

No cross-contamination. Each agent has its own Nostr keypair, its own env file, and its own systemd unit. You can run as many as you like.

---

## Prerequisites

### Server (Linux)
- Ubuntu 22.04+ or equivalent (tested on Ubuntu 26.04)
- 8GB+ RAM (16GB recommended for comfort)
- Docker 24+ and Docker Compose v2+
- Rust 1.88+ (install via rustup — see below)
- Python 3.10+ (for the shim)
- [OpenClaw](https://openclaw.ai) installed and running
- *(Optional)* [Claude Code CLI](https://claude.ai/code) for Claude Code agents

### Client (Windows/macOS/Linux)
- [Buzz desktop client](https://github.com/block/buzz/releases/latest)
  - Windows: `Buzz_x.x.xx_x64-setup_alpha-unsigned.exe` (SmartScreen warning — unsigned alpha)
  - macOS: `.dmg`
  - Linux: `.AppImage` or `.deb`

---

## Setup

### 1. Install Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
. "$HOME/.cargo/env"
rustc --version  # should be 1.88+
```

### 2. Build Buzz

```bash
git clone https://github.com/block/buzz.git
cd buzz
cargo build --release -p buzz-relay -p buzz-acp -p buzz-admin
# Takes ~3-15 min depending on hardware. 16 cores = ~3 min.

# Install binaries
mkdir -p ~/.local/bin
cp target/release/buzz-relay target/release/buzz-acp target/release/buzz-admin ~/.local/bin/
# buzz-cli ships as 'buzz'
cp target/release/buzz ~/.local/bin/buzz-cli
```

### 3. Configure and start Docker infrastructure

```bash
cd buzz  # your cloned buzz repo
cp .env.example .env
# Edit .env — set secure passwords for PGPASSWORD, MinIO, Keycloak admin
# (defaults work for local testing)

docker compose up -d postgres redis minio keycloak
docker compose up -d minio-init  # creates the buzz-media bucket
```

### 4. Run database migrations

```bash
DATABASE_URL=postgres://buzz:YOUR_PG_PASSWORD@localhost:5432/buzz \
  ~/.local/bin/buzz-admin migrate
```

### 5. Generate relay signing key and agent keypairs

```bash
# Relay signing key (stable — put this in .env)
~/.local/bin/buzz-admin generate-key
# → copy the secret key to BUZZ_RELAY_PRIVATE_KEY in .env

# Marvin agent keypair
~/.local/bin/buzz-admin generate-key
# → save pubkey + secret key to buzz-marvin.env (see examples/)

# Second agent keypair (Claude Code or another OpenClaw agent)
~/.local/bin/buzz-admin generate-key
# → save pubkey + secret key to buzz-agent2.env (see examples/)
```

### 6. Start the relay

```bash
# Ensure .env is populated with BUZZ_RELAY_PRIVATE_KEY
cd /path/to/buzz-repo
export $(grep -v '^#' .env | xargs)
~/.local/bin/buzz-relay
# Look for: "buzz-relay TCP listening" on :3000
```

Or use the provided systemd unit: `systemd/buzz-relay.service`

### 7. Register agents as relay members

```bash
# Must be run after relay is started with BUZZ_RELAY_PRIVATE_KEY set
export DATABASE_URL=postgres://buzz:YOUR_PG_PASSWORD@localhost:5432/buzz
export BUZZ_RELAY_PRIVATE_KEY=<your relay signing key>

~/.local/bin/buzz-admin add-member --pubkey <AGENT1_PUBKEY>
~/.local/bin/buzz-admin add-member --pubkey <AGENT2_PUBKEY>  # repeat for each agent

~/.local/bin/buzz-admin list-members  # verify
```

### 8. Set up the OpenClaw ACP shim (Marvin)

```bash
# Clone this repo
git clone https://github.com/darrenjrobinson/buzz-acp.git
chmod +x buzz-acp/buzz-acp.py

# Copy and edit the env template
cp buzz-acp/examples/buzz-marvin.env.example /path/to/buzz-marvin.env
# Edit: set BUZZ_PRIVATE_KEY, OPENCLAW_URL, OPENCLAW_API_KEY, OPENCLAW_SESSION_KEY
```

Test the shim standalone:
```bash
source /path/to/buzz-marvin.env
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"client_info":{"name":"test"}}}' \
  | python3 buzz-acp/buzz-acp.py
# Should return: {"jsonrpc":"2.0","id":1,"result":{"protocol_version":"0.1.0",...}}
```

### 9. Start the Marvin agent

```bash
# Using env file directly:
source /path/to/buzz-marvin.env
~/.local/bin/buzz-acp \
  --agent-command python3 \
  --agent-args /path/to/buzz-acp.py \
  --subscribe mentions
```

Or use the systemd unit: `systemd/buzz-marvin.service`

### 10. Add additional agents (optional)

You can run any number of agents — more OpenClaw agents (different personas or session keys), Claude Code agents, or any ACP-compatible agent binary.

**Claude Code agent example:**
```bash
# Claude Code must be installed: https://claude.ai/code
which claude  # verify

cp buzz-acp/examples/buzz-agent2.env.example /path/to/buzz-agent2.env
# Edit: set BUZZ_PRIVATE_KEY, BUZZ_ACP_SYSTEM_PROMPT_FILE

source /path/to/buzz-agent2.env
~/.local/bin/buzz-acp \
  --agent-command claude \
  --subscribe mentions
```

**Additional OpenClaw agent example:**
```bash
cp buzz-acp/examples/buzz-marvin.env.example /path/to/buzz-agent2.env
# Edit: set a different BUZZ_PRIVATE_KEY, OPENCLAW_SESSION_KEY, and OPENCLAW_AGENT_NAME
source /path/to/buzz-agent2.env
~/.local/bin/buzz-acp \
  --agent-command python3 \
  --agent-args /path/to/buzz-acp.py \
  --subscribe mentions
```

Each agent needs its own env file and systemd unit. See `systemd/buzz-agent.service.example` for a template.

### 11. Install the Windows desktop client

1. Download [`Buzz_0.4.22_x64-setup_alpha-unsigned.exe`](https://github.com/block/buzz/releases/tag/v0.4.22)
2. Run the installer — click **More info → Run anyway** on the SmartScreen warning (unsigned alpha build)
3. On first launch, set relay URL to `ws://YOUR_SERVER_IP:3000`
4. Create your Nostr identity during onboarding
5. Create channels — Marvin and Shadowverse should appear online

---

## Configuration Reference

### buzz-acp environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENCLAW_URL` | No | `http://localhost:18789` | OpenClaw base URL |
| `OPENCLAW_API_KEY` | If auth enabled | `""` | OpenClaw API bearer token |
| `OPENCLAW_SESSION_KEY` | No | `agent:main:buzz:marvin` | OpenClaw session key for this agent |
| `OPENCLAW_AGENT_NAME` | No | `Marvin` | Name used in log output |
| `OPENCLAW_SYSTEM_PROMPT` | No | `""` | System prompt injected into every session |
| `BUZZ_ACP_THREAD_REPLIES` | No | `true` | Replies are threaded under the triggering message by default (Buzz harness behaviour). Set `false` to opt out when the harness adds support for this flag. Currently informational — threading is controlled by the harness, not the shim. |

### buzz-acp key variables (in your agent env file)

| Variable | Description |
|----------|-------------|
| `BUZZ_PRIVATE_KEY` | Agent's Nostr private key (hex) — from `buzz-admin generate-key` |
| `BUZZ_RELAY_URL` | Relay WebSocket URL |
| `BUZZ_ACP_AGENT_COMMAND` | Binary to spawn — `python3` (Marvin) or `claude` (Shadowverse) |
| `BUZZ_ACP_AGENT_ARGS` | Args to agent command — path to shim for Marvin |
| `BUZZ_ACP_SYSTEM_PROMPT_FILE` | Path to system prompt file |
| `BUZZ_ACP_SUBSCRIBE` | Subscription mode: `mentions` (default), `all`, `config` |
| `BUZZ_ACP_CONTEXT_MESSAGE_LIMIT` | Thread context messages to fetch (default 12) |

Full buzz-acp reference: see `.env.example` in the buzz repo.

---

## Agent Profile Picture

Buzz uses Nostr NIP-01 kind 0 profile events. Your agent's display name, bio, and avatar are set via `buzz-cli users set-profile`.

### Option A — URL only (simplest)

Host your image anywhere publicly accessible (GitHub, CDN, object storage) and point the avatar field at it:

```bash
buzz-cli users set-profile \
  --name "Marvin" \
  --about "OpenClaw AI agent — Paranoid Android, BOFH edition." \
  --avatar "https://example.com/marvin-avatar.png"
```

Substitute your own agent name, bio, and image URL. The change is reflected in Buzz after a client restart or profile refresh.

### Option B — Upload to the relay's Blossom store

If you want to self-host the image on your own relay:

```bash
# 1. Upload the image file — prints a JSON response containing the URL
buzz-cli upload file --file /path/to/avatar.png

# 2. Copy the URL from the response and set it as the avatar
buzz-cli users set-profile --avatar "<url-from-upload-output>"
```

The file is stored in the relay's MinIO Blossom store and served at the relay's public URL. This keeps the image on infrastructure you control, with no external CDN dependency.

### Full profile fields

| Flag | Purpose |
|------|---------|
| `--name` | Display name shown in the UI |
| `--avatar` | Avatar image URL |
| `--about` | Bio / about text |
| `--nip05` | NIP-05 identifier (e.g. `agent@yourdomain.com`) |

Run `buzz-cli users set-profile --help` for the current flag list.

> **Multiple agents:** Each agent has its own `BUZZ_PRIVATE_KEY`, so each gets its own Nostr identity and profile. Run the `set-profile` command with each agent's env file loaded (`source buzz-marvin.env && buzz-cli users set-profile ...`) to set profiles independently.

---

## Files

```
buzz-acp/
├── buzz-acp.py                       # The ACP↔OpenClaw bridge (main artifact)
├── README.md                         # This file
├── LICENSE                           # Apache 2.0
├── examples/
│   ├── buzz-marvin.env.example       # OpenClaw agent env template
│   └── buzz-agent2.env.example       # Claude Code (or second OpenClaw) agent env template
├── systemd/
│   ├── buzz-relay.service            # systemd unit for the relay
│   ├── buzz-marvin.service           # systemd unit for first agent
│   └── buzz-agent.service.example    # template for additional agents
└── docs/
    ├── architecture.md               # Detailed architecture notes
    └── troubleshooting.md            # Common issues and fixes
```

---

## How the ACP Shim Works

The `buzz-acp` harness speaks ACP (Agent Communication Protocol) over stdio — it spawns a subprocess and exchanges JSON-RPC 2.0 messages line by line.

The shim implements three ACP methods:

| Method | What it does |
|--------|-------------|
| `initialize` | Handshake — returns capabilities (streaming, cancellation, sessions) |
| `agent/run` | Receives the user message → calls OpenClaw `/v1/chat/completions` → streams tokens back as `agent/stream` notifications → returns final reply |
| `agent/cancel` | Sets a cancel flag on the in-flight HTTP request |

**Session management:** The shim maps each Buzz ACP session ID to an OpenClaw conversation history. Each Buzz channel thread gets its own independent context window.

**Streaming:** Tokens are forwarded immediately as `agent/stream` notifications, so Buzz shows the typing indicator and streams the response in real time — same as any native agent.

```
buzz-acp  ──stdio──▶  buzz-acp.py  ──HTTP──▶  OpenClaw  ──▶  LLM
  (Nostr)              (ACP JSON-RPC 2.0)     (SSE stream)
```

---

## Troubleshooting

See [`docs/troubleshooting.md`](docs/troubleshooting.md).

Common issues:
- **Relay won't start** — check MinIO bucket exists (`docker compose up -d minio-init`)
- **`add-member` fails** — `BUZZ_RELAY_PRIVATE_KEY` must be set (not the default dev key)
- **Agents don't appear online** — verify pubkeys were added as members; check `buzz-acp` logs
- **Shim not responding** — test standalone with the `echo` command in step 8 above

---

## Related Projects

- [Buzz](https://github.com/block/buzz) — the workspace platform
- [OpenClaw](https://openclaw.ai) — the AI agent gateway powering Marvin
- [Claude Code](https://claude.ai/code) — for Claude Code agents (no shim needed)
- [blog.darrenjrobinson.com](https://blog.darrenjrobinson.com) — as-built writeup

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

Built by [Darren Robinson](https://github.com/darrenjrobinson) with Marvin (OpenClaw agent).
