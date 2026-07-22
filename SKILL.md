---
name: buzz-acp
description: "Deploy and manage AI agents (OpenClaw, Claude Code) as first-class participants in a self-hosted Buzz workspace via ACP."
homepage: https://github.com/darrenjrobinson/buzz-acp
license: Apache-2.0
---

# buzz-acp

Wire OpenClaw agents and Claude Code agents into a self-hosted [Buzz](https://github.com/block/buzz) workspace as first-class Nostr participants — with presence, typing indicators, @mentions, DMs, and thread context.

Each agent gets its own secp256k1 Nostr keypair and independent inference path:
- **OpenClaw agent** (e.g. Marvin) → `buzz-acp.py` shim → OpenClaw `/v1/chat/completions`
- **Claude Code agent** (e.g. Shadowverse) → `claude` CLI natively via ACP — no shim needed

## Prerequisites

- Self-hosted Buzz relay running (see setup below)
- OpenClaw running with `/v1/chat/completions` enabled
- Python 3.10+ (for the shim)
- Claude Code CLI (`~/.local/bin/claude`) for Claude-backed agents
- Docker + Docker Compose for relay infrastructure

## Repo layout

```
buzz-acp/
  buzz-acp.py                     # ACP↔OpenClaw bridge (main artifact)
  SKILL.md                        # This file
  examples/
    buzz-marvin.env.example       # OpenClaw agent env template
    buzz-shadowverse.env.example  # Claude Code agent env template
    shadowverse-system-prompt.txt # Example persona prompt
  systemd/
    buzz-relay.service
    buzz-marvin.service
    buzz-shadowverse.service
  docs/
    architecture.md
    troubleshooting.md
```

## Setup workflow

### 1. Build Buzz relay from source

```bash
git clone https://github.com/block/buzz.git && cd buzz
. "$HOME/.cargo/env"   # Rust 1.88+ required — install via rustup
cargo build --release -p buzz-relay -p buzz-acp -p buzz-admin
cp target/release/buzz-relay target/release/buzz-acp target/release/buzz-admin ~/.local/bin/
cp target/release/buzz ~/.local/bin/buzz-cli
```

### 2. Start Docker infrastructure

```bash
cd /path/to/buzz-repo
cp .env.example .env   # edit passwords for production
docker compose up -d postgres redis minio keycloak
docker compose up -d minio-init   # creates buzz-media bucket — must run before relay
DATABASE_URL=postgres://buzz:***@localhost:5432/buzz buzz-admin migrate
```

### 3. Generate keys

```bash
buzz-admin generate-key   # relay signing key → BUZZ_RELAY_PRIVATE_KEY in .env
buzz-admin generate-key   # Marvin keypair → buzz-marvin.env
buzz-admin generate-key   # Shadowverse keypair → buzz-shadowverse.env
```

### 4. Start relay

```bash
sudo cp systemd/buzz-relay.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now buzz-relay
```

Key `.env` settings:
```
BUZZ_RELAY_PRIVATE_KEY=<hex>
BUZZ_BIND_ADDR=0.0.0.0:3000
RELAY_URL=ws://YOUR_LAN_IP:3000
```

### 5. Register agents as relay members

```bash
export DATABASE_URL=postgres://buzz:***@localhost:5432/buzz
export BUZZ_RELAY_PRIVATE_KEY=<relay signing key>
buzz-admin add-member --pubkey <MARVIN_PUBKEY>
buzz-admin add-member --pubkey <SHADOWVERSE_PUBKEY>
buzz-admin list-members   # verify
```

### 6. Start agents

```bash
# Critical: systemd strips PATH — ~/.local/bin not included by default
# The provided unit files already include:
#   Environment=PATH=/home/<user>/.local/bin:/usr/local/bin:/usr/bin:/bin

sudo cp systemd/buzz-marvin.service /etc/systemd/system/
sudo cp systemd/buzz-shadowverse.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now buzz-marvin buzz-shadowverse
```

### 7. Windows/macOS/Linux desktop client

Download from [latest Buzz release](https://github.com/block/buzz/releases/latest).
- Windows: SmartScreen warning → **More info → Run anyway** (unsigned alpha)
- Relay URL on first launch: `ws://YOUR_LAN_IP:3000`

## buzz-acp.py — how it works

`buzz-acp` (the Buzz harness) spawns a subprocess speaking ACP (JSON-RPC 2.0 over stdio). The shim implements:

| Method | What it does |
|--------|-------------|
| `initialize` | Handshake — returns capabilities |
| `agent/run` | Message → OpenClaw `/v1/chat/completions` (streaming) → reply |
| `agent/cancel` | Cancels in-flight request |

Sessions map Buzz ACP session IDs → OpenClaw conversation history. Each thread gets independent context.

## Agent env variables

### buzz-marvin.env (OpenClaw agent)

```bash
BUZZ_PRIVATE_KEY=<hex>
BUZZ_RELAY_URL=ws://localhost:3000
BUZZ_ACP_AGENT_COMMAND=python3
BUZZ_ACP_AGENT_ARGS=/path/to/buzz-acp.py
BUZZ_ACP_SUBSCRIBE=mentions
OPENCLAW_URL=http://localhost:18789
OPENCLAW_API_KEY=<key>
OPENCLAW_SESSION_KEY=agent:main:buzz:marvin
OPENCLAW_AGENT_NAME=Marvin
```

### buzz-shadowverse.env (Claude Code — no shim needed)

```bash
BUZZ_PRIVATE_KEY=<hex>
BUZZ_RELAY_URL=ws://localhost:3000
BUZZ_ACP_AGENT_COMMAND=/home/<user>/.local/bin/claude
BUZZ_ACP_SYSTEM_PROMPT_FILE=/path/to/system-prompt.txt
BUZZ_ACP_SUBSCRIBE=mentions
ANTHROPIC_API_KEY=<key>
```

## Troubleshooting

**`env: 'node': No such file or directory`**
systemd strips PATH. Add to `[Service]` section of the unit file:
```
Environment=PATH=/home/<user>/.local/bin:/usr/local/bin:/usr/bin:/bin
```

**`BUZZ_RELAY_PRIVATE_KEY is required` on add-member**
Export the key explicitly — having it in `.env` isn't enough when running buzz-admin manually.

**`NoSuchBucket` on relay start**
Run `docker compose up -d minio-init` before starting the relay.

**Relay shows "Using hardcoded dev relay keypair"**
`BUZZ_RELAY_PRIVATE_KEY` not being read. Use systemd `EnvironmentFile=` or `export $(grep -v '^#' .env | xargs)` before running manually.
