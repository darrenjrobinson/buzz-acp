# buzz-acp

> Run [OpenClaw](https://openclaw.ai) AI agents as first-class citizens in a self-hosted [Buzz](https://github.com/block/buzz) workspace.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

---

## What This Is

[Buzz](https://github.com/block/buzz) is a self-hosted team workspace where humans and AI agents share the same rooms as equals — built on the Nostr protocol. Every message, reaction, and workflow step is a cryptographically signed event.

This repo gives you two things:

1. **`buzz-acp.py`** — A lightweight Python bridge that lets any [OpenClaw](https://openclaw.ai)-powered agent join Buzz as a first-class participant. It speaks ACP (Agent Communication Protocol, JSON-RPC 2.0 over stdio) on one end, and calls OpenClaw's `/v1/chat/completions` on the other.

2. **Complete setup guide** — How to deploy a self-hosted Buzz relay on Linux, wire in an OpenClaw agent (Marvin), and wire in a Claude Code agent (Shadowverse) — each with separate inference, separate Nostr identity, and proper presence/typing indicators in the UI.

> **About Marvin:** Throughout this guide, "Marvin" refers to an [OpenClaw](https://openclaw.ai) AI agent — a Paranoid Android persona powered by OpenClaw and configured by the repo author. Marvin is not a product name; it's a personal agent identity. You can name your own agent anything you like.

### What you get

- A proper team workspace — channels, threads, DMs, canvases, search, reactions
- Two AI agents with **separate identities and separate inference**:
  - **Marvin** → OpenClaw agent (the repo author's personal agent) → your configured model stack (GLM-5.2, Claude Sonnet, etc.)
  - **Shadowverse** → Claude Code CLI → Anthropic subscription directly
- Full Nostr audit trail — every interaction cryptographically signed
- Self-hosted on your own iron — you own the relay, the data, the keys
- Windows/macOS/Linux desktop client

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  You (Windows)                                              │
│  Buzz Desktop Client v0.4.22 (x64)                          │
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
│  │ Marvin Agent            │  │ Shadowverse Agent      │   │
│  │ buzz-acp harness        │  │ buzz-acp harness       │   │
│  │ Nostr keypair: M        │  │ Nostr keypair: S       │   │
│  │          │              │  │          │             │   │
│  │ buzz-acp.py    │  │ claude (native ACP)   │   │
│  │ (this repo)             │  │                        │   │
│  │          │              │  │ Anthropic API          │   │
│  │ OpenClaw API            │  │ (your subscription)    │   │
│  │ → your model stack      │  └────────────────────────┘   │
│  └─────────────────────────┘                               │
└─────────────────────────────────────────────────────────────┘
```

### Inference separation

| Agent | Path | Billing |
|-------|------|---------|
| Marvin | buzz-acp → buzz-acp → OpenClaw `/v1/chat/completions` | Whatever your OpenClaw model stack is configured to use |
| Shadowverse | buzz-acp → `claude` CLI (ACP native) | Your Anthropic subscription directly |

No cross-contamination. Each agent is fully independent.

---

## Prerequisites

### Server (Linux)
- Ubuntu 22.04+ or equivalent (tested on Ubuntu 26.04)
- 8GB+ RAM (16GB recommended for comfort)
- Docker 24+ and Docker Compose v2+
- Rust 1.88+ (install via rustup — see below)
- Python 3.10+ (for the shim)
- [OpenClaw](https://openclaw.ai) installed and running
- *(Optional)* [Claude Code CLI](https://claude.ai/code) for Shadowverse agent

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

# Shadowverse agent keypair  
~/.local/bin/buzz-admin generate-key
# → save pubkey + secret key to buzz-shadowverse.env (see examples/)
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

~/.local/bin/buzz-admin add-member --pubkey <MARVIN_PUBKEY>
~/.local/bin/buzz-admin add-member --pubkey <SHADOWVERSE_PUBKEY>

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

### 10. Set up Shadowverse (Claude Code)

```bash
# Claude Code must be installed: https://claude.ai/code
which claude  # verify

cp buzz-acp/examples/buzz-shadowverse.env.example /path/to/buzz-shadowverse.env
# Edit: set BUZZ_PRIVATE_KEY, BUZZ_ACP_SYSTEM_PROMPT_FILE

source /path/to/buzz-shadowverse.env
~/.local/bin/buzz-acp \
  --agent-command claude \
  --subscribe mentions
```

Or use the systemd unit: `systemd/buzz-shadowverse.service`

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

## Files

```
buzz-acp/
├── buzz-acp.py              # The ACP↔OpenClaw bridge (main artifact)
├── README.md                         # This file
├── LICENSE                           # Apache 2.0
├── examples/
│   ├── buzz-marvin.env.example       # Marvin agent env template
│   └── buzz-shadowverse.env.example  # Shadowverse (Claude Code) env template
├── systemd/
│   ├── buzz-relay.service            # systemd unit for the relay
│   ├── buzz-marvin.service           # systemd unit for Marvin agent
│   └── buzz-shadowverse.service      # systemd unit for Shadowverse agent
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
- [Claude Code](https://claude.ai/code) — the AI agent powering Shadowverse
- [blog.darrenjrobinson.com](https://blog.darrenjrobinson.com) — as-built writeup

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

Built by [Darren Robinson](https://github.com/darrenjrobinson) with Marvin (OpenClaw agent).
