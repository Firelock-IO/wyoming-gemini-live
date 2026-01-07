# wyoming-gemini-live

A **Gemini Live (native-audio) voice gateway** that:
- streams **16 kHz PCM** audio *to* Gemini Live in realtime,
- streams **native Gemini audio (24 kHz) back** (downsampled to 16 kHz),
- executes **Home Assistant actions** via tool/function calling (HA REST API),
- and exposes a simple **Wyoming TCP** interface for audio I/O.

This repo is intentionally shaped to be:
- **a standalone container** (Docker / Compose),
- **and** a **Home Assistant local add-on** (copy this folder into your HA add-ons directory).

> Reality check: Home Assistant’s current Assist pipeline is turn-based (buffer → STT → LLM → TTS).  
> Gemini Live is full‑duplex streaming. This project is the “clean sidecar” path that avoids forking HA core.

---

## What you get

- **Full-duplex** Gemini Live audio (interruptions supported by the Live API).
- **Dynamic Home Assistant context injection**:
  - the gateway fetches your HA entities,
  - injects a curated device list into the system prompt,
  - so Gemini picks correct `entity_id`s instead of guessing.
- **Tool execution**:
  - Gemini calls `control_home_assistant(...)`,
  - gateway calls HA `/api/services/<domain>/<service>` with your token,
  - gateway replies to Gemini with tool results.

---

## Architecture

```
[Mic/Speaker Client]
     |
     |  Wyoming TCP (audio-start/chunk/stop)
     v
[wyoming-gemini-live container]
     |
     |  Gemini Live WebSocket (native audio)
     v
[Gemini Live model]
     |
     |  Tool calls
     v
[Home Assistant REST API]
```

---

## Quickstart (Docker Compose)

1) Copy env template and fill it out:

```bash
cp .env.example .env
```

2) Start the service:

```bash
docker compose up -d --build
docker logs -f wyoming-gemini-live
```

It listens on `0.0.0.0:10700` by default.

---

## Quickstart (uv, local dev)

```bash
uv sync
export GEMINI_API_KEY="..."
export HA_URL="http://homeassistant.local:8123"
export HA_TOKEN="..."
uv run python -m wyoming_gemini_live
```

---

## Home Assistant Add-on (local)

This repo includes a `config.yaml` so it can be used as a **local add-on**.

1) In HA, enable Advanced Mode.
2) Use an add-ons folder (commonly `/addons` or `/addon_configs`) and copy this repository folder into it.
3) Go to **Settings → Add-ons → Add-on store → ⋮ → Repositories** and add the local folder (or browse local add-ons).
4) Install **Wyoming Gemini Live**.
5) In add-on options, set:
   - `gemini_api_key`
   - `ha_token`
   - `ha_url` (default `http://supervisor/core` works for HAOS)
6) Start the add-on and check logs.

---

## Audio client / satellite options

This gateway expects a client that can speak Wyoming audio events:
- `audio-start`
- `audio-chunk`
- `audio-stop`

You can:
- write a small client (Python, Go, Rust, etc),
- or adapt an existing Wyoming mic/speaker client,
- or run a “satellite” device that forwards audio to this server.

> ESPHome / Atom Echo voice devices do **not** currently speak Wyoming TCP directly.  
> For those, you’ll need a bridge layer (future work / separate project).

---

## Configuration

You can configure via environment variables or HA add-on options (`/data/options.json`).

| Setting | Env var | Default |
|---|---|---|
| Gemini API key | `GEMINI_API_KEY` | (required) |
| HA URL | `HA_URL` | `http://homeassistant.local:8123` |
| HA token | `HA_TOKEN` | (required for device control) |
| Model | `MODEL` | `gemini-2.5-flash-native-audio-preview-12-2025` |
| Port | `PORT` | `10700` |
| Allowed domains | `ALLOWED_DOMAINS` | `light,switch,cover,climate,lock,scene,script` |
| Max context entities | `MAX_CONTEXT_ENTITIES` | `200` |
| Allowlist patterns | `ENTITY_ALLOWLIST` | empty |
| Blocklist patterns | `ENTITY_BLOCKLIST` | empty |
| Log level | `LOG_LEVEL` | `info` |

---

## Roadmap (pragmatic)

- Multi-client support (per-connection Gemini sessions).
- Better streaming resampler (stateful polyphase / soxr).
- HA entity exposure parity (use only “exposed to assistants” entities when available).
- Optional MCP client mode (Home Assistant can act as an MCP server).
- Zeroconf advertising for auto-discovery.

---

## Safety + cost notes

Gemini Live is realtime. If you keep sessions open, you can burn tokens while nobody talks.
This gateway:
- keeps sessions per Wyoming connection,
- uses short “silence tail” after `audio-stop` to trigger VAD.

You should still monitor billing and rate limits.

---

## License

Apache-2.0 (see `LICENSE`).
