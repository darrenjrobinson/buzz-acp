#!/usr/bin/env python3
"""
buzz-acp.py — ACP ↔ OpenClaw bridge for Buzz

Speaks ACP (JSON-RPC 2.0 over stdio) on one end.
Calls OpenClaw /v1/chat/completions on the other.

buzz-acp spawns this as a subprocess and thinks it's talking to a coding agent.
It's actually talking to OpenClaw (and through it, whatever model is configured —
GLM-5.2, Claude Sonnet, or any model in your OpenClaw stack).

Usage:
    Set in your buzz-acp env:
        BUZZ_ACP_AGENT_COMMAND=python3
        BUZZ_ACP_AGENT_ARGS=/path/to/buzz-acp.py
    Or mark executable and set:
        BUZZ_ACP_AGENT_COMMAND=/path/to/buzz-acp.py

Environment variables:
    OPENCLAW_URL            OpenClaw base URL  (default: http://localhost:18789)
    OPENCLAW_API_KEY        OpenClaw API key   (required if auth is enabled)
    OPENCLAW_SESSION_KEY    Session key        (default: agent:main:buzz:marvin)
    OPENCLAW_AGENT_NAME     Display name for logs (default: Marvin)
    OPENCLAW_SYSTEM_PROMPT  Optional system prompt override (inline text)

ACP protocol: JSON-RPC 2.0 over stdin/stdout.
Each line is one complete JSON-RPC message.

Author:  Marvin (OpenClaw agent) + Darren Robinson
Repo:    https://github.com/darrenjrobinson/buzz-acp
License: Apache 2.0
"""

import sys
import json
import os
import threading
import uuid
import logging
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OPENCLAW_URL      = os.environ.get("OPENCLAW_URL", "http://localhost:18789")
OPENCLAW_API_KEY  = os.environ.get("OPENCLAW_API_KEY", "")
SESSION_KEY       = os.environ.get("OPENCLAW_SESSION_KEY", "agent:main:buzz:marvin")
AGENT_NAME        = os.environ.get("OPENCLAW_AGENT_NAME", "Marvin")
SYSTEM_PROMPT     = os.environ.get("OPENCLAW_SYSTEM_PROMPT", "")

# ---------------------------------------------------------------------------
# Logging — stderr only (stdout is the ACP wire)
# ---------------------------------------------------------------------------
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format=f"[{AGENT_NAME}-shim] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ACP constants
# ---------------------------------------------------------------------------
ACP_VERSION   = "0.1.0"
CAPABILITIES  = {"streaming": True, "cancellation": True, "sessions": True}

# ---------------------------------------------------------------------------
# Per-session conversation history
# Map: acp_session_id → list of {"role": ..., "content": ...}
# ---------------------------------------------------------------------------
_sessions: dict[str, list[dict]] = {}
_sessions_lock = threading.Lock()

# Active run cancel events: req_id → threading.Event
_active_runs: dict = {}

# ---------------------------------------------------------------------------
# Wire helpers
# ---------------------------------------------------------------------------
_write_lock = threading.Lock()

def _send(obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with _write_lock:
        sys.stdout.write(line)
        sys.stdout.flush()

def _respond(req_id, result: dict) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})

def _error(req_id, code: int, msg: str) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": msg}})

def _notify(method: str, params: dict) -> None:
    _send({"jsonrpc": "2.0", "method": method, "params": params})

# ---------------------------------------------------------------------------
# OpenClaw call
# ---------------------------------------------------------------------------
def _call_openclaw(session_id: str, user_text: str, cancel: threading.Event) -> str:
    with _sessions_lock:
        history = _sessions.setdefault(session_id, [])
        if SYSTEM_PROMPT and not history:
            history.append({"role": "system", "content": SYSTEM_PROMPT})
        history.append({"role": "user", "content": user_text})
        messages = list(history)

    url     = f"{OPENCLAW_URL.rstrip('/')}/v1/chat/completions"
    payload = json.dumps({
        "model":       "default",
        "messages":    messages,
        "stream":      True,
        "session_key": SESSION_KEY,
    }).encode()
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if OPENCLAW_API_KEY:
        headers["Authorization"] = f"Bearer {OPENCLAW_API_KEY}"

    req    = Request(url, data=payload, headers=headers, method="POST")
    chunks = []

    try:
        with urlopen(req, timeout=300) as resp:
            for raw in resp:
                if cancel.is_set():
                    break
                line = raw.decode("utf-8").rstrip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                token = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if token:
                    chunks.append(token)
                    _notify("agent/stream", {"session_id": session_id, "content": token})
    except (HTTPError, URLError) as exc:
        log.error("OpenClaw request failed: %s", exc)
        raise

    reply = "".join(chunks)
    with _sessions_lock:
        _sessions[session_id].append({"role": "assistant", "content": reply})
    return reply

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _handle_initialize(req_id, params: dict) -> None:
    log.info("initialize from %s", params.get("client_info", {}).get("name", "?"))
    _respond(req_id, {
        "protocol_version": ACP_VERSION,
        "server_info": {"name": f"buzz-acp ({AGENT_NAME})", "version": "1.0.0"},
        "capabilities": CAPABILITIES,
    })


def _handle_agent_run(req_id, params: dict) -> None:
    session_id = params.get("session_id") or str(uuid.uuid4())
    messages   = params.get("messages", [])

    user_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_text = msg.get("content", "")
            break

    if not user_text:
        _respond(req_id, {"session_id": session_id, "content": "", "stop_reason": "end_turn"})
        return

    log.info("agent/run session=%s len=%d", session_id, len(user_text))
    cancel = threading.Event()
    _active_runs[req_id] = cancel

    try:
        reply       = _call_openclaw(session_id, user_text, cancel)
        stop_reason = "cancelled" if cancel.is_set() else "end_turn"
        _respond(req_id, {"session_id": session_id, "content": reply, "stop_reason": stop_reason})
    except Exception as exc:
        _error(req_id, -32000, f"OpenClaw error: {exc}")
    finally:
        _active_runs.pop(req_id, None)


def _handle_agent_cancel(req_id, params: dict) -> None:
    target = params.get("id")
    ev     = _active_runs.get(target)
    if ev:
        ev.set()
        log.info("agent/cancel: cancelled %s", target)
    _respond(req_id, {"cancelled": ev is not None})


HANDLERS = {
    "initialize":   _handle_initialize,
    "agent/run":    _handle_agent_run,
    "agent/cancel": _handle_agent_cancel,
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main() -> None:
    log.info("starting — agent=%s relay=%s session=%s", AGENT_NAME, OPENCLAW_URL, SESSION_KEY)
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            log.warning("bad JSON: %s", exc)
            continue

        req_id  = msg.get("id")
        method  = msg.get("method", "")
        params  = msg.get("params", {})
        handler = HANDLERS.get(method)

        if handler is None:
            log.warning("unknown method: %s", method)
            if req_id is not None:
                _error(req_id, -32601, f"Method not found: {method}")
            continue

        # Each request in its own thread — keeps read loop unblocked
        # and allows concurrent cancellation
        threading.Thread(target=handler, args=(req_id, params), daemon=True).start()

    log.info("stdin closed — exiting")


if __name__ == "__main__":
    main()
